import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Select, View
import re
from typing import Optional

from utils.player import YTDLSource, Song, PlayerManager
from utils.prompt_manager import prompt_manager

# Spotify URL 正則表達式
SPOTIFY_REGEX = re.compile(r'https?://open\.spotify\.com/track/([a-zA-Z0-9]+)')


class ModeSelectView(View):
    """模式選擇選單"""

    def __init__(self, guild_id: int, current_preset: str = None):
        super().__init__(timeout=60)
        self.guild_id = guild_id

        # 建立選項
        options = []
        presets = prompt_manager.get_all_presets()

        for key, preset in presets.items():
            options.append(
                discord.SelectOption(
                    label=preset['name'],
                    description=preset['description'][:50],
                    value=key,
                    default=(key == current_preset)
                )
            )

        # 建立選擇選單
        select = Select(
            placeholder="選擇推薦模式...",
            options=options,
            custom_id="mode_select"
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        """選擇後的回調"""
        selected_key = interaction.data['values'][0]
        preset = prompt_manager.get_preset(selected_key)

        if not preset:
            await interaction.response.send_message("❌ 模式不存在", ephemeral=True)
            return

        success = prompt_manager.set_preset(self.guild_id, selected_key)

        if success:
            embed = discord.Embed(
                title=f"✅ 已切換至 {preset['name']}",
                description=preset['description'],
                color=discord.Color.green()
            )
            # 顯示 prompt 預覽
            prompt_preview = preset['prompt'][:300] + "..." if len(preset['prompt']) > 300 else preset['prompt']
            embed.add_field(
                name="推薦策略",
                value=f"```\n{prompt_preview}\n```",
                inline=False
            )
            await interaction.response.edit_message(embed=embed, view=None)
        else:
            await interaction.response.send_message("❌ 切換失敗", ephemeral=True)


class Music(commands.Cog):
    """音樂播放指令"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.player_manager = PlayerManager(bot)
        self.spotify = None
        self._setup_spotify()

    def _setup_spotify(self):
        """設定 Spotify API（如有憑證）"""
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

            if SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET:
                self.spotify = spotipy.Spotify(
                    auth_manager=SpotifyClientCredentials(
                        client_id=SPOTIFY_CLIENT_ID,
                        client_secret=SPOTIFY_CLIENT_SECRET
                    )
                )
                print("Spotify API 已連接")
        except Exception as e:
            print(f"Spotify 設定失敗（可忽略）: {e}")

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        """確保使用者在語音頻道中"""
        if not interaction.user.voice:
            await interaction.response.send_message(
                "❌ 你需要先加入一個語音頻道！",
                ephemeral=True
            )
            return False

        if not interaction.guild.voice_client:
            await interaction.user.voice.channel.connect()
        elif interaction.guild.voice_client.channel != interaction.user.voice.channel:
            await interaction.guild.voice_client.move_to(interaction.user.voice.channel)

        return True

    async def _search_spotify(self, url: str) -> Optional[str]:
        """從 Spotify URL 取得歌曲搜尋關鍵字"""
        if not self.spotify:
            return None

        match = SPOTIFY_REGEX.match(url)
        if not match:
            return None

        try:
            track_id = match.group(1)
            track = self.spotify.track(track_id)
            artists = ", ".join([a['name'] for a in track['artists']])
            return f"{track['name']} {artists}"
        except Exception:
            return None

    @app_commands.command(name="play", description="播放音樂（支援 YouTube 網址、搜尋、Spotify 連結）")
    @app_commands.describe(query="歌曲名稱、YouTube 網址或 Spotify 連結")
    async def play(self, interaction: discord.Interaction, query: str):
        """播放音樂"""
        if not await self._ensure_voice(interaction):
            return

        await interaction.response.defer(thinking=True)

        player = self.player_manager.get_player(interaction.guild)

        try:
            # 處理 Spotify 連結
            if 'spotify.com' in query:
                search_query = await self._search_spotify(query)
                if search_query:
                    query = f"ytsearch:{search_query}"
                else:
                    await interaction.followup.send("❌ 無法解析 Spotify 連結，請確認連結是否正確")
                    return

            # 搜尋/取得歌曲資訊
            data = await YTDLSource.from_url(query, loop=self.bot.loop)

            song = Song(
                title=data.get('title', '未知標題'),
                url=data.get('webpage_url', query),
                stream_url=data.get('url'),
                duration=data.get('duration', 0),
                thumbnail=data.get('thumbnail'),
                requester=interaction.user
            )

            # 建立嵌入訊息
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

            await interaction.followup.send(embed=embed)

        except Exception as e:
            await interaction.followup.send(f"❌ 播放失敗: {str(e)}")

    @app_commands.command(name="pause", description="暫停播放")
    async def pause(self, interaction: discord.Interaction):
        """暫停播放"""
        vc = interaction.guild.voice_client

        if not vc or not vc.is_playing():
            await interaction.response.send_message("❌ 目前沒有正在播放的音樂", ephemeral=True)
            return

        vc.pause()
        await interaction.response.send_message("⏸️ 已暫停播放")

    @app_commands.command(name="resume", description="繼續播放")
    async def resume(self, interaction: discord.Interaction):
        """繼續播放"""
        vc = interaction.guild.voice_client

        if not vc or not vc.is_paused():
            await interaction.response.send_message("❌ 目前沒有暫停的音樂", ephemeral=True)
            return

        vc.resume()
        await interaction.response.send_message("▶️ 繼續播放")

    @app_commands.command(name="skip", description="跳過目前歌曲")
    async def skip(self, interaction: discord.Interaction):
        """跳過目前歌曲"""
        player = self.player_manager.get_player(interaction.guild)

        if not player.current:
            await interaction.response.send_message("❌ 目前沒有正在播放的音樂", ephemeral=True)
            return

        skipped_title = player.current.title
        player.skip()
        await interaction.response.send_message(f"⏭️ 已跳過: **{skipped_title}**")

    @app_commands.command(name="stop", description="停止播放並離開頻道")
    async def stop(self, interaction: discord.Interaction):
        """停止播放"""
        player = self.player_manager.get_player(interaction.guild)
        await player.stop()
        self.player_manager.remove_player(interaction.guild.id)
        await interaction.response.send_message("⏹️ 已停止播放並離開頻道")

    @app_commands.command(name="queue", description="顯示播放佇列")
    async def queue(self, interaction: discord.Interaction):
        """顯示播放佇列"""
        player = self.player_manager.get_player(interaction.guild)

        embed = discord.Embed(title="📜 播放佇列", color=discord.Color.blue())

        if player.current:
            embed.add_field(
                name="🎵 正在播放",
                value=f"[{player.current.title}]({player.current.url}) [{player.current.duration_str}]",
                inline=False
            )

        if player.queue:
            queue_list = []
            for i, song in enumerate(list(player.queue)[:10], 1):
                queue_list.append(f"`{i}.` [{song.title}]({song.url}) [{song.duration_str}]")

            embed.add_field(
                name=f"📝 等待播放 ({len(player.queue)} 首)",
                value="\n".join(queue_list) if queue_list else "佇列是空的",
                inline=False
            )

            if len(player.queue) > 10:
                embed.set_footer(text=f"還有 {len(player.queue) - 10} 首歌曲...")
        else:
            if not player.current:
                embed.description = "佇列是空的，使用 `/play` 來播放音樂！"

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="np", description="顯示目前播放的歌曲")
    async def nowplaying(self, interaction: discord.Interaction):
        """顯示目前播放的歌曲"""
        player = self.player_manager.get_player(interaction.guild)

        if not player.current:
            await interaction.response.send_message("❌ 目前沒有正在播放的音樂", ephemeral=True)
            return

        song = player.current
        loop_status = ["關閉", "🔂 單曲循環", "🔁 佇列循環"][player.loop_mode]
        autoplay_status = "✨ 開啟" if player.autoplay else "關閉"

        # 判斷是否為自動播放的歌曲
        is_autoplay = song.requester is None

        embed = discord.Embed(
            title="🎵 正在播放" + (" (自動播放)" if is_autoplay else ""),
            description=f"[{song.title}]({song.url})",
            color=discord.Color.gold() if is_autoplay else discord.Color.purple()
        )
        embed.add_field(name="時長", value=song.duration_str, inline=True)
        embed.add_field(name="點播者", value=song.requester.mention if song.requester else "🤖 自動播放", inline=True)
        embed.add_field(name="循環模式", value=loop_status, inline=True)
        embed.add_field(name="自動播放", value=autoplay_status, inline=True)

        if song.thumbnail:
            embed.set_thumbnail(url=song.thumbnail)

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="previous", description="播放上一首歌曲")
    async def previous(self, interaction: discord.Interaction):
        """播放上一首歌曲"""
        player = self.player_manager.get_player(interaction.guild)

        if not player.history:
            await interaction.response.send_message("❌ 沒有上一首歌曲的紀錄", ephemeral=True)
            return

        prev_song = player.history[-1]  # 預覽上一首
        success = player.previous()

        if success:
            await interaction.response.send_message(f"⏮️ 正在播放上一首: **{prev_song.title}**")
        else:
            await interaction.response.send_message("❌ 無法播放上一首", ephemeral=True)

    @app_commands.command(name="loop", description="切換循環模式（關閉 → 單曲 → 佇列）")
    async def loop(self, interaction: discord.Interaction):
        """切換循環模式"""
        player = self.player_manager.get_player(interaction.guild)

        # 循環切換：0 → 1 → 2 → 0
        player.loop_mode = (player.loop_mode + 1) % 3

        statuses = [
            "❌ 循環模式已關閉",
            "🔂 單曲循環已開啟",
            "🔁 佇列循環已開啟"
        ]
        await interaction.response.send_message(statuses[player.loop_mode])

    @app_commands.command(name="shuffle", description="隨機打亂播放佇列")
    async def shuffle(self, interaction: discord.Interaction):
        """隨機打亂佇列"""
        player = self.player_manager.get_player(interaction.guild)

        if len(player.queue) < 2:
            await interaction.response.send_message("❌ 佇列中需要至少 2 首歌曲才能打亂", ephemeral=True)
            return

        player.shuffle()
        await interaction.response.send_message(f"🔀 已隨機打亂 {len(player.queue)} 首歌曲")

    @app_commands.command(name="volume", description="調整音量 (0-100)")
    @app_commands.describe(volume="音量大小 (0-100)")
    async def volume(self, interaction: discord.Interaction, volume: int):
        """調整音量"""
        if not 0 <= volume <= 100:
            await interaction.response.send_message("❌ 音量必須在 0-100 之間", ephemeral=True)
            return

        player = self.player_manager.get_player(interaction.guild)
        player.volume = volume / 100

        vc = interaction.guild.voice_client
        if vc and vc.source:
            vc.source.volume = player.volume

        await interaction.response.send_message(f"🔊 音量已調整為 {volume}%")

    @app_commands.command(name="clear", description="清空播放佇列")
    async def clear(self, interaction: discord.Interaction):
        """清空播放佇列"""
        player = self.player_manager.get_player(interaction.guild)
        count = len(player.queue)
        player.clear_queue()
        await interaction.response.send_message(f"🗑️ 已清空 {count} 首歌曲")

    @app_commands.command(name="autoplay", description="切換自動播放（佇列空時自動搜尋相關歌曲）")
    async def autoplay(self, interaction: discord.Interaction):
        """切換自動播放模式"""
        player = self.player_manager.get_player(interaction.guild)
        player.autoplay = not player.autoplay

        if player.autoplay:
            await interaction.response.send_message(
                "✨ **自動播放已開啟**\n"
                "當佇列播放完畢時，會自動搜尋並播放相關歌曲"
            )
        else:
            player.autoplay_history.clear()
            await interaction.response.send_message(
                "⏹️ **自動播放已關閉**\n"
                "佇列播放完畢後將停止"
            )

    @app_commands.command(name="prompt", description="查看目前的 AI 推薦 pre-prompt")
    async def prompt_view(self, interaction: discord.Interaction):
        """查看目前的 pre-prompt"""
        current_prompt = prompt_manager.get_prompt(interaction.guild.id)
        current_preset = prompt_manager.get_current_preset_key(interaction.guild.id)
        is_custom = prompt_manager.is_custom(interaction.guild.id)

        embed = discord.Embed(
            title="🤖 AI 推薦 Pre-prompt",
            color=discord.Color.blue()
        )

        # 顯示目前模式
        if current_preset:
            preset_info = prompt_manager.get_preset(current_preset)
            mode_text = f"{preset_info['name']}"
        elif is_custom:
            mode_text = "📝 自訂模式"
        else:
            mode_text = "🎵 通用模式"

        embed.add_field(name="目前模式", value=mode_text, inline=False)

        # 如果 prompt 太長，截斷顯示
        display_prompt = current_prompt[:1000] + "..." if len(current_prompt) > 1000 else current_prompt

        embed.add_field(
            name="內容",
            value=f"```\n{display_prompt}\n```",
            inline=False
        )
        embed.set_footer(text="使用 /mode 切換模式 | /prompt_set 自訂 | /prompt_reset 重設")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="mode", description="切換 AI 推薦模式")
    async def mode_switch(self, interaction: discord.Interaction):
        """顯示可用的推薦模式並切換"""
        presets = prompt_manager.get_all_presets()
        current_preset = prompt_manager.get_current_preset_key(interaction.guild.id)

        embed = discord.Embed(
            title="🎛️ AI 推薦模式",
            description="選擇一個模式來改變 AI 的推薦風格",
            color=discord.Color.purple()
        )

        # 列出所有模式
        mode_list = []
        for key, preset in presets.items():
            current_mark = " ✅" if key == current_preset else ""
            mode_list.append(f"**{preset['name']}**{current_mark}\n└ {preset['description']}")

        embed.add_field(
            name="可用模式",
            value="\n\n".join(mode_list),
            inline=False
        )

        # 建立選擇選單
        view = ModeSelectView(interaction.guild.id, current_preset)

        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="mode_set", description="直接設定 AI 推薦模式")
    @app_commands.describe(mode="模式名稱")
    @app_commands.choices(mode=[
        app_commands.Choice(name="🎵 通用模式", value="default"),
        app_commands.Choice(name="🎤 華語流行", value="mandopop"),
        app_commands.Choice(name="🇯🇵 日本流行", value="jpop"),
        app_commands.Choice(name="🇰🇷 韓國流行", value="kpop"),
        app_commands.Choice(name="🌍 歐美流行", value="western"),
        app_commands.Choice(name="😌 放鬆模式", value="chill"),
        app_commands.Choice(name="🔥 嗨歌模式", value="energetic"),
        app_commands.Choice(name="📻 經典懷舊", value="retro"),
        app_commands.Choice(name="🎸 獨立音樂", value="indie"),
        app_commands.Choice(name="🎌 動漫專屬", value="anime"),
    ])
    async def mode_set(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        """直接設定推薦模式"""
        preset = prompt_manager.get_preset(mode.value)
        if not preset:
            await interaction.response.send_message("❌ 找不到該模式", ephemeral=True)
            return

        success = prompt_manager.set_preset(interaction.guild.id, mode.value)

        if success:
            embed = discord.Embed(
                title=f"✅ 已切換至 {preset['name']}",
                description=preset['description'],
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ 切換失敗，請稍後再試", ephemeral=True)

    @app_commands.command(name="prompt_set", description="設定 AI 推薦的 pre-prompt")
    @app_commands.describe(prompt="新的 pre-prompt 內容")
    async def prompt_set(self, interaction: discord.Interaction, prompt: str):
        """設定 pre-prompt"""
        # 檢查權限（只有管理員可以修改）
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ 你需要「管理伺服器」權限才能修改 pre-prompt",
                ephemeral=True
            )
            return

        # 檢查長度
        if len(prompt) > 2000:
            await interaction.response.send_message(
                "❌ Pre-prompt 太長了（最多 2000 字元）",
                ephemeral=True
            )
            return

        if len(prompt) < 10:
            await interaction.response.send_message(
                "❌ Pre-prompt 太短了（至少 10 字元）",
                ephemeral=True
            )
            return

        success = prompt_manager.set_prompt(interaction.guild.id, prompt)

        if success:
            embed = discord.Embed(
                title="✅ Pre-prompt 已更新",
                color=discord.Color.green()
            )
            display_prompt = prompt[:500] + "..." if len(prompt) > 500 else prompt
            embed.add_field(
                name="新的 Pre-prompt",
                value=f"```\n{display_prompt}\n```",
                inline=False
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ 儲存失敗，請稍後再試", ephemeral=True)

    @app_commands.command(name="prompt_reset", description="重設 AI 推薦的 pre-prompt 為預設值")
    async def prompt_reset(self, interaction: discord.Interaction):
        """重設 pre-prompt"""
        # 檢查權限
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message(
                "❌ 你需要「管理伺服器」權限才能重設 pre-prompt",
                ephemeral=True
            )
            return

        if not prompt_manager.is_custom(interaction.guild.id):
            await interaction.response.send_message(
                "ℹ️ 目前已經是使用預設的 pre-prompt",
                ephemeral=True
            )
            return

        success = prompt_manager.reset_prompt(interaction.guild.id)

        if success:
            await interaction.response.send_message("✅ 已重設為預設的 pre-prompt")
        else:
            await interaction.response.send_message("❌ 重設失敗，請稍後再試", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Music(bot))
