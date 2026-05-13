"""
音樂播放器模組

雙佇列設計：
- user_queue:    使用者用 /play、/sync 加入的歌曲（優先播放）
- auto_queue:    自動播放推薦的歌曲（user_queue 為空時才播放）

播放順序：user_queue → auto_queue → 觸發自動補充 auto_queue
"""

import asyncio
import re
import discord
import yt_dlp
from dataclasses import dataclass
from typing import Optional
from collections import deque

from config import (
    YTDL_OPTIONS,
    FFMPEG_OPTIONS,
    DEFAULT_VOLUME,
    MAX_QUEUE_SIZE,
    AUTOPLAY_ENABLED,
    AUTOPLAY_MAX_HISTORY,
    AUTOPLAY_LOW_WATERMARK,
    AUTOPLAY_TARGET_SIZE,
)
from utils.lastfm_api import lastfm_api
from utils.recommender import MusicRecommender, canonical_artist_key, canonical_track_key, parse_track_seed
from utils.spotify_api import spotify_api
from utils.youtube_matcher import YouTubeMatcher


# ─── 資料結構 ────────────────────────────────────────────────

@dataclass
class Song:
    """代表一首歌曲"""
    title: str
    url: str
    stream_url: str
    duration: int
    thumbnail: Optional[str] = None
    requester: Optional[discord.Member] = None
    spotify_id: Optional[str] = None
    is_autoplay: bool = False
    artist: Optional[str] = None
    source_title: Optional[str] = None
    recommendation_reason: str = ""

    @property
    def duration_str(self) -> str:
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


# ─── YouTube 音源 ────────────────────────────────────────────

class YTDLSource(discord.PCMVolumeTransformer):
    """YouTube 音源處理器"""

    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = DEFAULT_VOLUME):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url: str, *, loop: asyncio.AbstractEventLoop = None):
        loop = loop or asyncio.get_event_loop()
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        if data and 'entries' in data:
            data = data['entries'][0]
        return data

    @classmethod
    async def create_source(cls, data: dict, *, volume: float = DEFAULT_VOLUME):
        stream_url = data.get('url')
        source = discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS, stderr=None)
        return cls(source, data=data, volume=volume)


# ─── YouTube 搜尋 ────────────────────────────────────────────

NON_MUSIC_KEYWORDS = [
    '新聞', '快訊', '報導', '訪問', '專訪', '記者', '主播',
    'news', 'interview', 'reaction', 'podcast', 'talk show',
    '開箱', '教學', '評測', 'review', 'unboxing', 'tutorial',
    '直播', 'live stream', '實況',
    'SETN', 'ETtoday', 'tvbs', '三立', '中天', '民視', '東森',
]


def _is_likely_music(entry: dict) -> bool:
    title = entry.get('title', '').lower()
    duration = entry.get('duration', 0)
    if duration and (duration < 60 or duration > 600):
        return False
    for kw in NON_MUSIC_KEYWORDS:
        if kw.lower() in title:
            return False
    return True


async def search_youtube(query: str, loop: asyncio.AbstractEventLoop = None) -> list[dict]:
    """搜尋 YouTube，三段式 + 過濾"""
    loop = loop or asyncio.get_event_loop()
    ytdl_opts = dict(YTDL_OPTIONS)
    ytdl_opts.update({
        'format': 'bestaudio/best', 'noplaylist': True,
        'nocheckcertificate': True, 'ignoreerrors': True,
        'quiet': True, 'no_warnings': True,
        'default_search': 'ytsearch', 'source_address': '0.0.0.0',
    })
    ytdl = yt_dlp.YoutubeDL(ytdl_opts)

    async def _do_search(sq: str) -> list[dict]:
        try:
            data = await loop.run_in_executor(None, lambda q=sq: ytdl.extract_info(q, download=False))
            if not data or 'entries' not in data:
                return []
            results = []
            for e in data.get('entries', []):
                if e and _is_likely_music(e):
                    vid = e.get('id')
                    results.append({
                        'id': vid,
                        'title': e.get('title', '未知標題'),
                        'url': e.get('webpage_url') or f"https://www.youtube.com/watch?v={vid}",
                        'duration': e.get('duration', 0),
                        'thumbnail': e.get('thumbnail'),
                        'channel': e.get('channel') or e.get('uploader'),
                    })
            return results
        except Exception:
            return []

    results = await _do_search(f"ytsearch10:{query} official audio")
    if not results:
        results = await _do_search(f"ytsearch10:{query} MV")
    if not results:
        results = await _do_search(f"ytsearch12:{query}")
    return results


# ─── 音樂播放器 ──────────────────────────────────────────────

class MusicPlayer:
    """
    每個伺服器的音樂播放器

    雙佇列：
      user_queue  — 使用者手動點播（/play, /sync）
      auto_queue  — 自動播放推薦（Spotify 紀錄）

    播放優先序：單曲循環 > user_queue > auto_queue > 佇列循環 > 觸發自動補充
    """

    def __init__(self, bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild

        # 雙佇列
        self.user_queue: deque[Song] = deque(maxlen=MAX_QUEUE_SIZE)
        self.auto_queue: deque[Song] = deque(maxlen=MAX_QUEUE_SIZE)

        self.history: deque[Song] = deque(maxlen=50)
        self.current: Optional[Song] = None
        self.volume = DEFAULT_VOLUME
        self.loop_mode = 0  # 0=關閉, 1=單曲循環, 2=佇列循環
        self.is_playing = False

        # 自動播放
        self.autoplay = AUTOPLAY_ENABLED
        self.played_youtube_ids: set[str] = set()
        self.played_spotify_ids: set[str] = set()
        self.played_track_keys: set[str] = set()
        self.recommended_keys: set[str] = set()
        self.recommended_youtube_ids: set[str] = set()
        self.autoplay_fill_lock = asyncio.Lock()
        self.autoplay_task: Optional[asyncio.Task] = None
        self.recommender = MusicRecommender(lastfm_api=lastfm_api)
        self.youtube_matcher = YouTubeMatcher()
        self.spotify_user_id: Optional[int] = None

        # UI
        self.text_channel: Optional[discord.TextChannel] = None

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        return self.guild.voice_client

    @property
    def queue(self) -> deque[Song]:
        """合併佇列（用於顯示 /queue）"""
        combined = deque(self.user_queue)
        combined.extend(self.auto_queue)
        return combined

    # ─── 佇列操作 ────────────────────────────────────────────

    def add_to_queue(self, song: Song) -> int:
        """加入使用者佇列"""
        self.user_queue.append(song)
        return len(self.user_queue)

    def add_to_auto_queue(self, song: Song):
        """加入自動播放佇列"""
        self.auto_queue.append(song)

    def clear_queue(self):
        """清空使用者佇列"""
        self.user_queue.clear()

    def clear_all_queues(self):
        """清空所有佇列"""
        self.user_queue.clear()
        self.auto_queue.clear()

    def skip(self):
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

    def previous(self) -> bool:
        if not self.history:
            return False
        if self.current:
            self.user_queue.appendleft(self.current)
        prev_song = self.history.pop()
        self.user_queue.appendleft(prev_song)
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()
        return True

    def shuffle(self):
        """打亂使用者佇列"""
        import random
        lst = list(self.user_queue)
        random.shuffle(lst)
        self.user_queue = deque(lst, maxlen=MAX_QUEUE_SIZE)

    def _extract_video_id(self, url: str) -> Optional[str]:
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        ]
        for p in patterns:
            m = re.search(p, url)
            if m:
                return m.group(1)
        return None

    # ─── 自動播放 ────────────────────────────────────────────

    async def _fill_auto_queue(self):
        """補充 auto_queue：Last.fm 相似曲 + Spotify 偏好 + YouTube 命中驗證。"""
        async with self.autoplay_fill_lock:
            if len(self.auto_queue) >= AUTOPLAY_TARGET_SIZE:
                return
            if not self.current:
                return

            try:
                seed_artist, seed_title = self._seed_from_song(self.current)
                spotify_recent: list[dict] = []
                spotify_top: list[dict] = []

                if self.spotify_user_id:
                    spotify_recent = await spotify_api.get_recently_played(self.spotify_user_id, limit=30)
                    spotify_top = await spotify_api.get_top_tracks(self.spotify_user_id, limit=20, time_range="short_term")

                if not seed_artist and spotify_recent:
                    seed_artist = spotify_recent[0]['artists'][0] if spotify_recent[0].get('artists') else ""
                    seed_title = spotify_recent[0].get('name') or seed_title

                if not seed_title:
                    print("  自動播放：沒有可用的推薦 seed")
                    return

                target_count = max(AUTOPLAY_TARGET_SIZE - len(self.auto_queue), 0)
                print(f"\n自動播放：補充推薦 seed={seed_artist} {seed_title}".strip())

                recommendations = await self.recommender.recommend_for_seed(
                    artist=seed_artist,
                    title=seed_title,
                    spotify_recent=spotify_recent,
                    spotify_top=spotify_top,
                    played_keys=self._known_track_keys(),
                    recommended_keys=self.recommended_keys,
                    guild_artists=self._guild_artist_keys(),
                    limit=max(target_count * 3, AUTOPLAY_TARGET_SIZE),
                )

                for candidate in recommendations:
                    if len(self.auto_queue) >= AUTOPLAY_TARGET_SIZE:
                        break
                    if candidate.key in self._known_track_keys() or candidate.key in self.recommended_keys:
                        continue

                    query = f"{candidate.artist} {candidate.title}"
                    yt_results = await search_youtube(query, loop=self.bot.loop)
                    video = self.youtube_matcher.select_best(candidate, yt_results)
                    if not video:
                        print(f"    找不到合適 YouTube 結果: {query}")
                        continue

                    vid = video.get('id')
                    if vid and (vid in self.played_youtube_ids or vid in self.recommended_youtube_ids):
                        continue

                    song = Song(
                        title=video['title'],
                        url=video['url'],
                        stream_url='',
                        duration=video.get('duration') or candidate.duration,
                        thumbnail=video.get('thumbnail') or candidate.album_image,
                        requester=None,
                        spotify_id=candidate.spotify_id,
                        is_autoplay=True,
                        artist=candidate.artist,
                        source_title=candidate.title,
                        recommendation_reason=candidate.reason,
                    )
                    self.auto_queue.append(song)
                    self.recommended_keys.add(candidate.key)
                    if vid:
                        self.recommended_youtube_ids.add(vid)
                    print(f"    推薦加入: {candidate.artist} - {candidate.title} -> {video['title']}")

                self._trim_autoplay_memory()
                print(f"  推薦佇列現有 {len(self.auto_queue)} 首")

            except Exception as e:
                print(f"自動播放補充失敗: {e}")
                import traceback
                traceback.print_exc()

    def _seed_from_song(self, song: Song) -> tuple[str, str]:
        if song.artist and song.source_title:
            return song.artist, song.source_title
        if song.artist:
            _, parsed_title = parse_track_seed(song.source_title or song.title)
            return song.artist, parsed_title or song.source_title or song.title
        return parse_track_seed(song.source_title or song.title)

    def _song_track_key(self, song: Song) -> Optional[str]:
        artist, title = self._seed_from_song(song)
        if not title:
            return None
        return canonical_track_key(artist, title)

    def _known_track_keys(self) -> set[str]:
        keys = set(self.played_track_keys)
        for song in [self.current, *list(self.user_queue), *list(self.auto_queue)]:
            if song:
                key = self._song_track_key(song)
                if key:
                    keys.add(key)
        return keys

    def _guild_artist_keys(self) -> set[str]:
        artists = set()
        for song in [self.current, *list(self.history), *list(self.user_queue)]:
            if not song:
                continue
            artist, _ = self._seed_from_song(song)
            if artist:
                artists.add(canonical_artist_key(artist))
        return artists

    def _remember_played_song(self, song: Song):
        if song.spotify_id:
            self.played_spotify_ids.add(song.spotify_id)
        if song.url:
            vid = self._extract_video_id(song.url)
            if vid:
                self.played_youtube_ids.add(vid)
        key = self._song_track_key(song)
        if key:
            self.played_track_keys.add(key)
            self.recommended_keys.discard(key)

        self._trim_autoplay_memory()

    def _trim_autoplay_memory(self):
        for memory in (
            self.played_youtube_ids,
            self.played_spotify_ids,
            self.played_track_keys,
            self.recommended_keys,
            self.recommended_youtube_ids,
        ):
            while len(memory) > AUTOPLAY_MAX_HISTORY * 2:
                memory.pop()

    def _schedule_auto_fill(self):
        if not self.autoplay or len(self.auto_queue) >= AUTOPLAY_LOW_WATERMARK:
            return
        if self.autoplay_task and not self.autoplay_task.done():
            return
        self.autoplay_task = self.bot.loop.create_task(self._fill_auto_queue())

    # ─── 播放控制 ────────────────────────────────────────────

    def _next_song(self) -> Optional[Song]:
        """
        從佇列中取出下一首歌

        優先序：user_queue > auto_queue
        當使用者加入新歌時，auto_queue 的歌會被「插隊」
        """
        if self.user_queue:
            return self.user_queue.popleft()
        elif self.auto_queue:
            return self.auto_queue.popleft()
        return None

    async def play_next(self):
        """播放下一首"""
        # 歷史紀錄
        if self.current and self.loop_mode != 1:
            self.history.append(self.current)
            self._remember_played_song(self.current)

        # ─── 決定下一首歌 ───
        if self.loop_mode == 1 and self.current:
            # 單曲循環
            song = self.current

        elif self.user_queue or self.auto_queue:
            # 佇列循環：把當前歌放回 user_queue 尾端
            if self.loop_mode == 2 and self.current and not self.current.is_autoplay:
                self.user_queue.append(self.current)

            song = self._next_song()
            if not song:
                self.current = None
                self.is_playing = False
                return

        elif self.loop_mode == 2 and self.current:
            # 佇列循環：兩個佇列都空但有當前歌
            song = self.current

        elif self.autoplay and self.current:
            # 兩個佇列都空 → 觸發自動播放補充
            print(f"\n{'=' * 50}")
            print("所有佇列已空，補充自動播放...")
            print(f"{'=' * 50}")

            await self._fill_auto_queue()

            if self.auto_queue:
                song = self.auto_queue.popleft()
            else:
                self.current = None
                self.is_playing = False
                if self.text_channel:
                    try:
                        await self.text_channel.send("⏹️ 自動播放結束。使用 `/login` 綁定 Spotify 以啟用推薦。")
                    except Exception:
                        pass
                return
        else:
            self.current = None
            self.is_playing = False
            return

        self.current = song
        self.is_playing = True
        self._schedule_auto_fill()

        try:
            if not self.voice_client:
                print("錯誤: 沒有語音連線")
                return

            print(f"正在取得串流: {song.title}")
            data = await YTDLSource.from_url(song.url, loop=self.bot.loop)

            if not data:
                print("錯誤: 無法取得串流，跳到下一首")
                await self.play_next()
                return

            source = await YTDLSource.create_source(data, volume=self.volume)

            def after_playing(error):
                if error:
                    print(f"播放錯誤: {error}")
                asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

            self.voice_client.play(source, after=after_playing)
            print(f"▶ 播放中: {song.title}" + (" [自動]" if song.is_autoplay else ""))

            # 自動播放 Embed 通知
            if song.is_autoplay and self.text_channel:
                try:
                    embed = discord.Embed(
                        title="🤖 DJ 模式",
                        description="根據你的 Spotify 播放紀錄推薦",
                        color=discord.Color.gold()
                    )
                    embed.add_field(name="🎵 正在播放", value=f"[{song.title}]({song.url})", inline=False)
                    if song.duration:
                        embed.add_field(name="⏱ 時長", value=song.duration_str, inline=True)
                    if song.thumbnail:
                        embed.set_thumbnail(url=song.thumbnail)
                    embed.set_footer(text="推薦歌曲 | 使用 /play 插入指定歌曲會優先播放")
                    await self.text_channel.send(embed=embed)
                except Exception as e:
                    print(f"  通知失敗: {e}")

        except Exception as e:
            import traceback
            print(f"播放失敗: {e}")
            traceback.print_exc()
            await self.play_next()

    async def stop(self):
        """停止播放"""
        self.user_queue.clear()
        self.auto_queue.clear()
        self.history.clear()
        self.played_youtube_ids.clear()
        self.played_spotify_ids.clear()
        self.played_track_keys.clear()
        self.recommended_keys.clear()
        self.recommended_youtube_ids.clear()
        if self.autoplay_task and not self.autoplay_task.done():
            self.autoplay_task.cancel()
        self.current = None
        self.is_playing = False
        self.loop_mode = 0

        if self.voice_client:
            self.voice_client.stop()
            await self.voice_client.disconnect()


# ─── 播放器管理 ──────────────────────────────────────────────

class PlayerManager:
    def __init__(self, bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}

    def get_player(self, guild: discord.Guild) -> MusicPlayer:
        if guild.id not in self.players:
            self.players[guild.id] = MusicPlayer(self.bot, guild)
        return self.players[guild.id]

    def remove_player(self, guild_id: int):
        if guild_id in self.players:
            del self.players[guild_id]
