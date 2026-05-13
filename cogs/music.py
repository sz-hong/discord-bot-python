"""
Discord 音樂指令 Cog

指令：
  /play       播放音樂（YouTube / Spotify 連結 / 搜尋）
  /sync       同步 Spotify 正在播放的歌曲
  /login      綁定 Spotify 帳號
  /logout     解除 Spotify 綁定
  /np         顯示目前播放的歌曲
  /queue      顯示佇列
  /skip       跳過
  /previous   上一首
  /pause      暫停
  /resume     繼續
  /stop       停止
  /loop       循環模式
  /shuffle    打亂佇列
  /volume     音量
  /clear      清空佇列
  /autoplay   自動播放開關
"""

import re
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View
from typing import Optional

from utils.player import YTDLSource, Song, PlayerManager, search_youtube
from utils.spotify_auth import spotify_auth
from utils.spotify_api import spotify_api

SPOTIFY_REGEX = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')


# ─── 播放控制按鈕 ────────────────────────────────────────────

class MusicControlView(View):
    """音樂播放控制按鈕"""

    def __init__(self, player_manager, guild_id: int):
        super().__init__(timeout=None)
        self.player_manager = player_manager
        self.guild_id = guild_id

    def _get_player(self):
        return self.player_manager.players.get(self.guild_id)

    @discord.ui.button(label="上一首", emoji="⏮️", style=discord.ButtonStyle.secondary, custom_id="music:previous")
    async def previous_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player or not player.history:
            await interaction.response.send_message("❌ 沒有上一首歌曲", ephemeral=True)
            return
        prev_song = player.history[-1]
        player.previous()
        await interaction.response.send_message(f"⏮️ 正在播放上一首: **{prev_song.title}**")

    @discord.ui.button(label="暫停/繼續", emoji="⏯️", style=discord.ButtonStyle.primary, custom_id="music:pause_resume")
    async def pause_resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if not vc:
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)
            return
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ 已暫停")
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ 繼續播放")
        else:
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)

    @discord.ui.button(label="跳過", emoji="⏭️", style=discord.ButtonStyle.secondary, custom_id="music:skip")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player or not player.current:
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)
            return
        skipped = player.current.title
        player.skip()
        await interaction.response.send_message(f"⏭️ 已跳過: **{skipped}**")

    @discord.ui.button(label="停止", emoji="⏹️", style=discord.ButtonStyle.danger, custom_id="music:stop")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player:
            await interaction.response.send_message("❌ 沒有播放器", ephemeral=True)
            return
        await player.stop()
        self.player_manager.remove_player(self.guild_id)
        await interaction.response.send_message("⏹️ 已停止播放")

    @discord.ui.button(label="循環", emoji="🔁", style=discord.ButtonStyle.secondary, custom_id="music:loop")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player:
            await interaction.response.send_message("❌ 沒有播放器", ephemeral=True)
            return
        player.loop_mode = (player.loop_mode + 1) % 3
        statuses = ["❌ 循環關閉", "🔂 單曲循環", "🔁 佇列循環"]
        await interaction.response.send_message(statuses[player.loop_mode])

    @discord.ui.button(label="佇列", emoji="📜", style=discord.ButtonStyle.secondary, custom_id="music:queue", row=1)
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player:
            await interaction.response.send_message("❌ 沒有播放器", ephemeral=True)
            return
        embed = _build_queue_embed(player)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="打亂", emoji="🔀", style=discord.ButtonStyle.secondary, custom_id="music:shuffle", row=1)
    async def shuffle_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player or len(player.queue) < 2:
            await interaction.response.send_message("❌ 佇列需要至少 2 首歌", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(f"🔀 已打亂 {len(player.queue)} 首歌曲")

    @discord.ui.button(label="自動播放", emoji="✨", style=discord.ButtonStyle.secondary, custom_id="music:autoplay", row=1)
    async def autoplay_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self._get_player()
        if not player:
            await interaction.response.send_message("❌ 沒有播放器", ephemeral=True)
            return
        player.autoplay = not player.autoplay
        if player.autoplay:
            await interaction.response.send_message("✨ 自動播放已開啟")
        else:
            player.recommended_keys.clear()
            player.recommended_youtube_ids.clear()
            await interaction.response.send_message("⏹️ 自動播放已關閉")


# ─── 共用工具 ────────────────────────────────────────────────

def _build_queue_embed(player) -> discord.Embed:
    """建立雙佇列 Embed"""
    embed = discord.Embed(title="📜 播放佇列", color=discord.Color.blue())

    if player.current:
        tag = " 🤖" if player.current.is_autoplay else ""
        embed.add_field(
            name="🎵 正在播放",
            value=f"[{player.current.title}]({player.current.url}) [{player.current.duration_str}]{tag}",
            inline=False,
        )

    # 使用者佇列
    if player.user_queue:
        lines = [f"`{i}.` [{s.title}]({s.url}) [{s.duration_str}]" for i, s in enumerate(list(player.user_queue)[:10], 1)]
        embed.add_field(name=f"📝 指定歌單 ({len(player.user_queue)} 首)", value="\n".join(lines), inline=False)
        if len(player.user_queue) > 10:
            embed.set_footer(text=f"還有 {len(player.user_queue) - 10} 首...")

    # 推薦佇列
    if player.auto_queue:
        lines = [f"`{i}.` 🤖 [{s.title}]({s.url}) [{s.duration_str}]" for i, s in enumerate(list(player.auto_queue)[:5], 1)]
        embed.add_field(name=f"✨ 推薦歌單 ({len(player.auto_queue)} 首)", value="\n".join(lines), inline=False)

    if not player.current and not player.user_queue and not player.auto_queue:
        embed.description = "佇列是空的，使用 `/play` 來播放音樂！"

    return embed


# ─── Music Cog ───────────────────────────────────────────────

class Music(commands.Cog):
    """音樂播放指令"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.player_manager = PlayerManager(bot)

    def _make_controls(self, guild_id: int) -> MusicControlView:
        """建立播放控制按鈕"""
        return MusicControlView(self.player_manager, guild_id)

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """確保使用者在語音頻道"""
        if not interaction.user.voice:
            await interaction.response.send_message("❌ 你需要先加入語音頻道！", ephemeral=True)
            return False
        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()
        elif interaction.guild.voice_client.channel != interaction.user.voice.channel:
            await interaction.guild.voice_client.move_to(interaction.user.voice.channel)
        return True

    # ─── Spotify 帳號指令 ────────────────────────────────────

    @app_commands.command(name="login", description="綁定你的 Spotify 帳號（用於同步播放和自動推薦）")
    async def login(self, interaction: discord.Interaction):
        """綁定 Spotify"""
        if not spotify_auth.enabled:
            await interaction.response.send_message("❌ Spotify OAuth2 未設定，請聯絡管理員", ephemeral=True)
            return

        if spotify_auth.is_logged_in(interaction.user.id):
            await interaction.response.send_message(
                "✅ 你已經綁定 Spotify 了！\n使用 `/sync` 同步播放，或 `/logout` 解除綁定。",
                ephemeral=True
            )
            return

        auth_url = spotify_auth.get_auth_url(interaction.user.id)

        embed = discord.Embed(
            title="🔗 綁定 Spotify 帳號",
            description="點擊下方按鈕登入 Spotify，授權後即可使用以下功能：",
            color=discord.Color.green()
        )
        embed.add_field(name="🎵 /sync", value="同步 Spotify 正在播放的歌曲", inline=False)
        embed.add_field(name="✨ 自動播放", value="佇列空時自動從你的 Spotify 紀錄推薦歌曲", inline=False)
        embed.set_footer(text="授權完成後回到 Discord 即可使用")

        view = View()
        view.add_item(discord.ui.Button(label="登入 Spotify", url=auth_url, style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="logout", description="解除 Spotify 帳號綁定")
    async def logout(self, interaction: discord.Interaction):
        """解除綁定"""
        if spotify_auth.logout(interaction.user.id):
            await interaction.response.send_message("✅ 已解除 Spotify 綁定", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 你還沒有綁定 Spotify", ephemeral=True)

    # ─── 同步播放 ────────────────────────────────────────────

    @app_commands.command(name="sync", description="同步 Spotify 正在播放的歌曲到語音頻道")
    async def sync(self, interaction: discord.Interaction):
        """同步 Spotify 當前播放"""
        if not spotify_auth.is_logged_in(interaction.user.id):
            await interaction.response.send_message("❌ 請先使用 `/login` 綁定 Spotify 帳號", ephemeral=True)
            return

        if not await self._ensure_voice(interaction):
            return

        await interaction.response.defer(thinking=True)

        player = self.player_manager.get_player(interaction.guild)
        player.text_channel = interaction.channel
        player.spotify_user_id = interaction.user.id

        # 取得 Spotify 當前播放
        current = await spotify_api.get_currently_playing(interaction.user.id)

        if not current:
            await interaction.followup.send("❌ 你的 Spotify 目前沒有在播放歌曲\n💡 先在 Spotify 播放一首歌，再使用 `/sync`")
            return

        search_query = current['search_query']
        print(f"Sync: 搜尋 '{search_query}'")

        # YouTube 搜尋
        yt_results = await search_youtube(search_query, loop=self.bot.loop)
        if not yt_results:
            await interaction.followup.send(f"❌ 在 YouTube 找不到: {search_query}")
            return

        video = yt_results[0]
        data = await YTDLSource.from_url(video['url'], loop=self.bot.loop)
        if not data:
            await interaction.followup.send("❌ 無法取得音源")
            return

        song = Song(
            title=data.get('title', current['name']),
            url=data.get('webpage_url', video['url']),
            stream_url=data.get('url'),
            duration=data.get('duration', 0),
            thumbnail=current.get('album_image') or data.get('thumbnail'),
            requester=interaction.user,
            spotify_id=current['spotify_id'],
            artist=current['artists'][0] if current.get('artists') else None,
            source_title=current['name'],
        )

        embed = discord.Embed(color=discord.Color.green())
        if player.is_playing:
            position = player.add_to_queue(song)
            embed.title = "📝 已加入佇列 (Spotify 同步)"
            embed.description = f"[{song.title}]({song.url})"
            embed.add_field(name="佇列位置", value=f"#{position}", inline=True)
        else:
            player.add_to_queue(song)
            await player.play_next()
            embed.title = "🎵 正在播放 (Spotify 同步)"
            embed.description = f"[{song.title}]({song.url})"

        embed.add_field(name="Spotify", value=f"{' / '.join(current['artists'])} — {current['name']}", inline=False)
        embed.add_field(name="時長", value=song.duration_str, inline=True)
        embed.add_field(name="點播者", value=interaction.user.mention, inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)

        await interaction.followup.send(embed=embed, view=self._make_controls(interaction.guild.id))

    # ─── 播放 ────────────────────────────────────────────────

    @app_commands.command(name="play", description="播放音樂（YouTube / Spotify 連結 / 搜尋）")
    @app_commands.describe(query="歌曲名稱、YouTube 網址或 Spotify 連結")
    async def play(self, interaction: discord.Interaction, query: str):
        """播放音樂"""
        if not await self._ensure_voice(interaction):
            return

        await interaction.response.defer(thinking=True)

        player = self.player_manager.get_player(interaction.guild)
        player.text_channel = interaction.channel

        # 自動綁定 Spotify user（給自動播放用）
        if spotify_auth.is_logged_in(interaction.user.id):
            player.spotify_user_id = interaction.user.id

        spotify_track_info = None

        try:
            # Spotify 連結 → 轉成 YouTube 搜尋
            if 'spotify.com' in query:
                match = SPOTIFY_REGEX.match(query)
                if match and spotify_auth.is_logged_in(interaction.user.id):
                    # 用 User API 取得歌曲資訊
                    token = await spotify_auth.get_access_token(interaction.user.id)
                    if token:
                        import aiohttp
                        async with aiohttp.ClientSession() as session:
                            async with session.get(
                                f"https://api.spotify.com/v1/tracks/{match.group(1)}",
                                headers={"Authorization": f"Bearer {token}"}
                            ) as resp:
                                if resp.status == 200:
                                    track = await resp.json()
                                    artists = ", ".join([a['name'] for a in track['artists']])
                                    spotify_track_info = {
                                        "spotify_id": track['id'],
                                        "artist": track['artists'][0]['name'] if track.get('artists') else None,
                                        "title": track['name'],
                                        "album_image": (
                                            track.get('album', {}).get('images', [{}])[0].get('url')
                                            if track.get('album', {}).get('images') else None
                                        ),
                                    }
                                    query = f"ytsearch:{track['name']} {artists}"
                                else:
                                    await interaction.followup.send("❌ 無法解析 Spotify 連結")
                                    return
                else:
                    await interaction.followup.send("❌ 請先用 `/login` 綁定 Spotify 才能播放 Spotify 連結")
                    return

            data = await YTDLSource.from_url(query, loop=self.bot.loop)

            song = Song(
                title=data.get('title', '未知標題'),
                url=data.get('webpage_url', query),
                stream_url=data.get('url'),
                duration=data.get('duration', 0),
                thumbnail=(spotify_track_info or {}).get('album_image') or data.get('thumbnail'),
                requester=interaction.user,
                spotify_id=(spotify_track_info or {}).get('spotify_id'),
                artist=(spotify_track_info or {}).get('artist'),
                source_title=(spotify_track_info or {}).get('title'),
            )

            embed = discord.Embed(color=discord.Color.green())
            if player.is_playing:
                position = player.add_to_queue(song)
                embed.title = "📝 已加入播放佇列"
                embed.description = f"[{song.title}]({song.url})"
                embed.add_field(name="佇列位置", value=f"#{position}", inline=True)
            else:
                player.add_to_queue(song)
                await player.play_next()
                embed.title = "🎵 正在播放"
                embed.description = f"[{song.title}]({song.url})"

            embed.add_field(name="時長", value=song.duration_str, inline=True)
            embed.add_field(name="點播者", value=song.requester.mention, inline=True)
            if song.thumbnail:
                embed.set_thumbnail(url=song.thumbnail)

            await interaction.followup.send(embed=embed, view=self._make_controls(interaction.guild.id))

        except Exception as e:
            await interaction.followup.send(f"❌ 播放失敗: {str(e)}")

    # ─── 基本控制指令 ────────────────────────────────────────

    @app_commands.command(name="pause", description="暫停播放")
    async def pause(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)
            return
        vc.pause()
        await interaction.response.send_message("⏸️ 已暫停播放")

    @app_commands.command(name="resume", description="繼續播放")
    async def resume(self, interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            await interaction.response.send_message("❌ 沒有暫停的音樂", ephemeral=True)
            return
        vc.resume()
        await interaction.response.send_message("▶️ 繼續播放")

    @app_commands.command(name="skip", description="跳過目前歌曲")
    async def skip(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)
            return
        skipped = player.current.title
        player.skip()
        await interaction.response.send_message(f"⏭️ 已跳過: **{skipped}**")

    @app_commands.command(name="stop", description="停止播放並離開頻道")
    async def stop(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        await player.stop()
        self.player_manager.remove_player(interaction.guild.id)
        await interaction.response.send_message("⏹️ 已停止播放")

    @app_commands.command(name="np", description="顯示目前播放的歌曲")
    async def nowplaying(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        if not player.current:
            await interaction.response.send_message("❌ 沒有正在播放的音樂", ephemeral=True)
            return

        song = player.current
        loop_text = ["關閉", "🔂 單曲循環", "🔁 佇列循環"][player.loop_mode]
        is_auto = song.requester is None

        embed = discord.Embed(
            title="🎵 正在播放" + (" (自動)" if is_auto else ""),
            description=f"[{song.title}]({song.url})",
            color=discord.Color.gold() if is_auto else discord.Color.purple()
        )
        embed.add_field(name="時長", value=song.duration_str, inline=True)
        embed.add_field(name="點播者", value=song.requester.mention if song.requester else "🤖 自動播放", inline=True)
        embed.add_field(name="循環", value=loop_text, inline=True)
        embed.add_field(name="自動播放", value="✨ 開啟" if player.autoplay else "關閉", inline=True)
        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)

        await interaction.response.send_message(embed=embed, view=self._make_controls(interaction.guild.id))

    @app_commands.command(name="previous", description="播放上一首歌曲")
    async def previous(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        if not player.history:
            await interaction.response.send_message("❌ 沒有上一首紀錄", ephemeral=True)
            return
        prev_song = player.history[-1]
        success = player.previous()
        if success:
            await interaction.response.send_message(f"⏮️ 上一首: **{prev_song.title}**")
        else:
            await interaction.response.send_message("❌ 無法播放上一首", ephemeral=True)

    @app_commands.command(name="queue", description="顯示播放佇列")
    async def queue(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        embed = _build_queue_embed(player)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="loop", description="切換循環模式")
    async def loop(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        player.loop_mode = (player.loop_mode + 1) % 3
        statuses = ["❌ 循環關閉", "🔂 單曲循環", "🔁 佇列循環"]
        await interaction.response.send_message(statuses[player.loop_mode])

    @app_commands.command(name="shuffle", description="隨機打亂指定歌單")
    async def shuffle(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        if len(player.user_queue) < 2:
            await interaction.response.send_message("❌ 指定歌單需要至少 2 首歌曲", ephemeral=True)
            return
        player.shuffle()
        await interaction.response.send_message(f"🔀 已打亂指定歌單 ({len(player.user_queue)} 首)")

    @app_commands.command(name="volume", description="調整音量 (0-100)")
    @app_commands.describe(volume="音量大小 (0-100)")
    async def volume(self, interaction: discord.Interaction, volume: int):
        if not 0 <= volume <= 100:
            await interaction.response.send_message("❌ 音量必須在 0-100 之間", ephemeral=True)
            return
        player = self.player_manager.get_player(interaction.guild)
        player.volume = volume / 100
        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = player.volume
        await interaction.response.send_message(f"🔊 音量: {volume}%")

    @app_commands.command(name="clear", description="清空佇列")
    @app_commands.describe(target="要清空的佇列")
    @app_commands.choices(target=[
        app_commands.Choice(name="📝 指定歌單", value="user"),
        app_commands.Choice(name="✨ 推薦歌單", value="auto"),
        app_commands.Choice(name="🗑️ 全部", value="all"),
    ])
    async def clear(self, interaction: discord.Interaction, target: app_commands.Choice[str] = None):
        player = self.player_manager.get_player(interaction.guild)
        choice = target.value if target else "user"

        if choice == "user":
            count = len(player.user_queue)
            player.clear_queue()
            await interaction.response.send_message(f"🗑️ 已清空指定歌單 ({count} 首)")
        elif choice == "auto":
            count = len(player.auto_queue)
            player.auto_queue.clear()
            await interaction.response.send_message(f"🗑️ 已清空推薦歌單 ({count} 首)")
        else:
            u = len(player.user_queue)
            a = len(player.auto_queue)
            player.clear_all_queues()
            await interaction.response.send_message(f"🗑️ 已清空全部 (指定 {u} 首 + 推薦 {a} 首)")

    @app_commands.command(name="autoplay", description="切換自動播放")
    async def autoplay(self, interaction: discord.Interaction):
        player = self.player_manager.get_player(interaction.guild)
        player.autoplay = not player.autoplay

        if player.autoplay:
            # 自動綁定
            if spotify_auth.is_logged_in(interaction.user.id):
                player.spotify_user_id = interaction.user.id
                await interaction.response.send_message("✨ **自動播放已開啟**\n佇列空時會根據你的 Spotify 播放紀錄推薦歌曲")
            else:
                await interaction.response.send_message("✨ **自動播放已開啟**\n💡 使用 `/login` 綁定 Spotify 可獲得更好的推薦")
        else:
            player.recommended_keys.clear()
            player.recommended_youtube_ids.clear()
            await interaction.response.send_message("⏹️ **自動播放已關閉**")


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
