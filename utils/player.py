import asyncio
import discord
import yt_dlp
from dataclasses import dataclass
from typing import Optional
from collections import deque

from config import YTDL_OPTIONS, FFMPEG_OPTIONS, DEFAULT_VOLUME, MAX_QUEUE_SIZE, AUTOPLAY_ENABLED, AUTOPLAY_MAX_HISTORY
from utils.ai_recommender import ai_recommender


@dataclass
class Song:
    """代表一首歌曲的資料"""
    title: str
    url: str
    stream_url: str
    duration: int
    thumbnail: Optional[str] = None
    requester: Optional[discord.Member] = None

    @property
    def duration_str(self) -> str:
        """將秒數轉換為可讀格式"""
        minutes, seconds = divmod(self.duration, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"


class YTDLSource(discord.PCMVolumeTransformer):
    """YouTube 音源處理器"""

    def __init__(self, source: discord.AudioSource, *, data: dict, volume: float = DEFAULT_VOLUME):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('webpage_url')

    @classmethod
    async def from_url(cls, url: str, *, loop: asyncio.AbstractEventLoop = None):
        """從 URL 建立音源"""
        loop = loop or asyncio.get_event_loop()
        ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))

        if data and 'entries' in data:
            data = data['entries'][0]

        return data

    @classmethod
    async def search_similar_songs(cls, title: str, artist: str = None, *, loop: asyncio.AbstractEventLoop = None, exclude_ids: set = None):
        """搜尋類似歌曲"""
        loop = loop or asyncio.get_event_loop()
        exclude_ids = exclude_ids or set()

        # 不使用 extract_flat，取得完整資訊
        ytdl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,  # 忽略錯誤繼續搜尋
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
        }
        ytdl = yt_dlp.YoutubeDL(ytdl_opts)

        try:
            import re

            # 清理標題（移除常見的非歌曲資訊）
            clean_title = title

            # 移除各種括號內容
            clean_title = re.sub(r'\[.*?\]|\(.*?\)|【.*?】|「.*?」|《.*?》', ' ', clean_title)

            # 移除 hashtag
            clean_title = re.sub(r'#\S+', ' ', clean_title)

            # 移除常見關鍵字
            clean_title = re.sub(r'MV|Official|Music Video|Lyric|lyrics|官方|完整版|HD|HQ|4K|纯享|合辑|精选|现场|Live|Cover|翻唱', ' ', clean_title, flags=re.IGNORECASE)

            # 移除表情符號
            clean_title = re.sub(r'[🔥✨💕🎵🎶❤️💜💙🌟⭐️😊🥰]+', ' ', clean_title)

            # 移除 ｜ 和之後的內容（通常是節目名稱）
            clean_title = re.sub(r'[｜|].*$', '', clean_title)

            # 移除多餘空格
            clean_title = re.sub(r'\s+', ' ', clean_title).strip()

            print(f"清理後標題: '{clean_title}'")

            # 如果清理後太短，嘗試提取歌手和歌名
            if len(clean_title) < 3:
                # 嘗試從原標題提取《歌名》
                song_match = re.search(r'《(.+?)》', title)
                if song_match:
                    clean_title = song_match.group(1)
                else:
                    clean_title = title[:20]

            # 建立搜尋關鍵字 - 搜尋更多結果
            search_query = f"ytsearch10:{clean_title}"

            print(f"自動播放搜尋: {search_query}")

            search_data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(search_query, download=False)
            )

            if not search_data:
                print("搜尋結果為空")
                return []

            # 處理搜尋結果
            entries = search_data.get('entries', [])
            if not entries:
                print("沒有找到任何結果")
                return []

            related = []
            for entry in entries:
                if entry:
                    video_id = entry.get('id')
                    webpage_url = entry.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"

                    is_excluded = video_id in exclude_ids if video_id else False
                    status = "(已排除)" if is_excluded else "(可播放)"
                    print(f"  找到: {entry.get('title')[:40]}... {status}")

                    if video_id and video_id not in exclude_ids:
                        related.append({
                            'id': video_id,
                            'title': entry.get('title', '未知標題'),
                            'url': webpage_url,
                            'duration': entry.get('duration', 0),
                            'thumbnail': entry.get('thumbnail'),
                        })

            print(f"找到 {len(related)} 首可播放的相關歌曲")
            return related

        except Exception as e:
            print(f"搜尋類似歌曲失敗: {e}")
            import traceback
            traceback.print_exc()
            return []

    @classmethod
    async def create_source(cls, data: dict, *, volume: float = DEFAULT_VOLUME):
        """建立可播放的音源"""
        stream_url = data.get('url')
        print(f"建立音源，格式: {data.get('ext', '未知')}, acodec: {data.get('acodec', '未知')}")
        source = discord.FFmpegPCMAudio(
            stream_url,
            **FFMPEG_OPTIONS,
            stderr=None  # 不要顯示 FFmpeg 錯誤到 stderr
        )
        return cls(source, data=data, volume=volume)


class MusicPlayer:
    """每個伺服器的音樂播放器"""

    def __init__(self, bot, guild: discord.Guild):
        self.bot = bot
        self.guild = guild
        self.queue: deque[Song] = deque(maxlen=MAX_QUEUE_SIZE)
        self.history: deque[Song] = deque(maxlen=50)  # 播放歷史（上一首用）
        self.current: Optional[Song] = None
        self.volume = DEFAULT_VOLUME
        self.loop_mode = 0  # 0=關閉, 1=單曲循環, 2=佇列循環
        self.is_playing = False
        self._task: Optional[asyncio.Task] = None
        # 自動播放相關
        self.autoplay = AUTOPLAY_ENABLED  # 自動播放開關
        self.autoplay_history: set[str] = set()  # 記錄已播放的影片 ID，避免重複
        self.last_autoplay_song: Optional[Song] = None  # 用於標記自動播放的歌曲

    @property
    def voice_client(self) -> Optional[discord.VoiceClient]:
        """取得語音客戶端"""
        return self.guild.voice_client

    def add_to_queue(self, song: Song) -> int:
        """加入播放佇列，回傳佇列位置"""
        self.queue.append(song)
        return len(self.queue)

    def clear_queue(self):
        """清空播放佇列"""
        self.queue.clear()

    def skip(self):
        """跳過目前歌曲"""
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

    def previous(self) -> bool:
        """播放上一首歌曲，回傳是否成功"""
        if not self.history:
            return False

        # 把目前歌曲放回佇列最前面
        if self.current:
            self.queue.appendleft(self.current)

        # 從歷史紀錄取出上一首
        prev_song = self.history.pop()
        self.queue.appendleft(prev_song)

        # 停止目前播放（會觸發 play_next）
        if self.voice_client and self.voice_client.is_playing():
            self.voice_client.stop()

        return True

    def shuffle(self):
        """隨機打亂佇列"""
        import random
        queue_list = list(self.queue)
        random.shuffle(queue_list)
        self.queue = deque(queue_list, maxlen=MAX_QUEUE_SIZE)

    def _extract_video_id(self, url: str) -> Optional[str]:
        """從 YouTube URL 提取影片 ID"""
        import re
        patterns = [
            r'(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]{11})',
            r'youtube\.com\/embed\/([a-zA-Z0-9_-]{11})',
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return None

    async def _get_autoplay_songs(self) -> list[Song]:
        """取得自動播放的歌曲列表（優先使用 AI 推薦，一次加入多首）"""
        if not self.current:
            print("自動播放：沒有當前歌曲")
            return []

        try:
            print(f"自動播放：根據 '{self.current.title}' 搜尋相關歌曲")

            songs_to_add = []

            # 取得播放歷史的標題列表
            history_titles = [song.title for song in list(self.history)[-10:]]
            excluded_titles = [song.title for song in list(self.history)[-20:]]

            # 嘗試使用 AI 推薦
            if ai_recommender.enabled:
                print("使用 AI 智慧推薦...")
                recommendations = await ai_recommender.get_recommendations(
                    current_song=self.current.title,
                    play_history=history_titles,
                    excluded_songs=excluded_titles,
                    count=5,
                    guild_id=self.guild.id
                )

                # 搜尋所有 AI 推薦的歌曲並加入列表
                for rec in recommendations:
                    print(f"搜尋 AI 推薦: {rec}")
                    related = await self._search_youtube(rec)

                    for video in related[:1]:  # 每個推薦只取第一個搜尋結果
                        video_id = video.get('id')
                        if video_id and video_id not in self.autoplay_history:
                            song = Song(
                                title=video.get('title', '未知標題'),
                                url=video.get('url'),
                                stream_url='',
                                duration=video.get('duration', 0),
                                thumbnail=video.get('thumbnail'),
                                requester=None
                            )
                            songs_to_add.append(song)
                            # 預先加入歷史避免重複
                            self.autoplay_history.add(video_id)
                            print(f"  ✓ 加入佇列: {video.get('title')}")
                            break  # 只取第一個結果

                if songs_to_add:
                    print(f"AI 推薦成功，共 {len(songs_to_add)} 首歌曲加入佇列")
                    return songs_to_add
                else:
                    print("AI 推薦的歌曲都已播放過，改用傳統搜尋")

            # 如果 AI 推薦失敗或未啟用，使用傳統搜尋
            print("使用傳統關鍵字搜尋...")
            related = await YTDLSource.search_similar_songs(
                self.current.title,
                loop=self.bot.loop,
                exclude_ids=self.autoplay_history
            )

            if not related:
                print("自動播放：找不到相關歌曲")
                return []

            # 加入所有未播放過的歌曲
            for video in related[:5]:  # 最多加入 5 首
                video_id = video.get('id')
                if video_id and video_id not in self.autoplay_history:
                    song = Song(
                        title=video.get('title', '未知標題'),
                        url=video.get('url'),
                        stream_url='',
                        duration=video.get('duration', 0),
                        thumbnail=video.get('thumbnail'),
                        requester=None
                    )
                    songs_to_add.append(song)
                    self.autoplay_history.add(video_id)
                    print(f"  ✓ 加入佇列: {video.get('title')}")

            if songs_to_add:
                print(f"傳統搜尋成功，共 {len(songs_to_add)} 首歌曲加入佇列")
            else:
                print("自動播放：所有相關歌曲都已播放過")

            return songs_to_add

        except Exception as e:
            print(f"自動播放搜尋失敗: {e}")
            import traceback
            traceback.print_exc()
            return []
            return None

    async def _search_youtube(self, query: str) -> list[dict]:
        """使用關鍵字搜尋 YouTube"""
        ytdl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'quiet': True,
            'no_warnings': True,
            'default_search': 'ytsearch',
            'source_address': '0.0.0.0',
        }
        ytdl = yt_dlp.YoutubeDL(ytdl_opts)

        try:
            search_query = f"ytsearch3:{query}"
            search_data = await self.bot.loop.run_in_executor(
                None, lambda: ytdl.extract_info(search_query, download=False)
            )

            if not search_data or 'entries' not in search_data:
                return []

            results = []
            for entry in search_data.get('entries', []):
                if entry:
                    video_id = entry.get('id')
                    results.append({
                        'id': video_id,
                        'title': entry.get('title', '未知標題'),
                        'url': entry.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}",
                        'duration': entry.get('duration', 0),
                        'thumbnail': entry.get('thumbnail'),
                    })

            return results

        except Exception as e:
            print(f"YouTube 搜尋失敗: {e}")
            return []

    async def play_next(self):
        """播放下一首歌曲"""
        # 將目前歌曲加入歷史紀錄
        if self.current and self.loop_mode != 1:
            self.history.append(self.current)
            # 記錄到自動播放歷史（避免重複推薦）
            if self.current.url:
                video_id = self._extract_video_id(self.current.url)
                if video_id:
                    self.autoplay_history.add(video_id)
                    # 限制歷史大小
                    if len(self.autoplay_history) > AUTOPLAY_MAX_HISTORY:
                        self.autoplay_history.pop()

        if self.loop_mode == 1 and self.current:
            # 單曲循環模式
            song = self.current
        elif self.queue:
            song = self.queue.popleft()
            # 佇列循環模式：播完的歌曲加回佇列尾端
            if self.loop_mode == 2 and self.current:
                self.queue.append(self.current)
        else:
            # 佇列循環模式：佇列空了但還有當前歌曲
            if self.loop_mode == 2 and self.current:
                song = self.current
            # 自動播放模式：佇列空了，搜尋相關歌曲並批次加入佇列
            elif self.autoplay and self.current:
                print("佇列已空，正在搜尋相關歌曲...")
                autoplay_songs = await self._get_autoplay_songs()
                if not autoplay_songs:
                    print("無法找到相關歌曲，停止播放")
                    self.current = None
                    self.is_playing = False
                    return
                # 將所有歌曲加入佇列
                for s in autoplay_songs:
                    self.queue.append(s)
                # 取出第一首來播放
                song = self.queue.popleft()
                self.last_autoplay_song = song
            else:
                self.current = None
                self.is_playing = False
                return

        self.current = song
        self.is_playing = True

        try:
            # 檢查是否有語音連線
            if not self.voice_client:
                print("錯誤: 沒有語音連線")
                return

            # 重新取得串流 URL（可能已過期）
            print(f"正在取得串流: {song.title}")
            data = await YTDLSource.from_url(song.url, loop=self.bot.loop)

            if not data:
                print("錯誤: 無法取得串流資料")
                await self.play_next()
                return

            print(f"串流 URL: {data.get('url', '無')[:50]}...")
            source = await YTDLSource.create_source(data, volume=self.volume)

            def after_playing(error):
                if error:
                    print(f"播放錯誤: {error}")
                # 使用 asyncio 安排下一首
                asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

            print("開始播放...")
            self.voice_client.play(source, after=after_playing)
            print(f"播放中: {song.title}")

        except Exception as e:
            import traceback
            print(f"播放失敗: {e}")
            traceback.print_exc()
            await self.play_next()

    async def stop(self):
        """停止播放並清空佇列"""
        self.queue.clear()
        self.history.clear()
        self.autoplay_history.clear()
        self.current = None
        self.is_playing = False
        self.loop_mode = 0
        self.last_autoplay_song = None

        if self.voice_client:
            self.voice_client.stop()
            await self.voice_client.disconnect()


class PlayerManager:
    """管理所有伺服器的播放器"""

    def __init__(self, bot):
        self.bot = bot
        self.players: dict[int, MusicPlayer] = {}

    def get_player(self, guild: discord.Guild) -> MusicPlayer:
        """取得或建立伺服器的播放器"""
        if guild.id not in self.players:
            self.players[guild.id] = MusicPlayer(self.bot, guild)
        return self.players[guild.id]

    def remove_player(self, guild_id: int):
        """移除伺服器的播放器"""
        if guild_id in self.players:
            del self.players[guild_id]
