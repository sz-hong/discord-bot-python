import discord
from discord.ext import commands
import asyncio

from config import DISCORD_TOKEN


class MusicBot(commands.Bot):
    """Discord Music Bot 主類別"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="一個簡單的音樂機器人"
        )

    async def setup_hook(self):
        """載入 Cogs 並同步指令"""
        # 載入音樂 Cog
        await self.load_extension("cogs.music")
        print("已載入音樂模組")

        # 同步斜線指令（Cog 載入後指令會自動註冊到 tree）
        synced = await self.tree.sync()
        print(f"已同步 {len(synced)} 個全域斜線指令")

        # 列出所有已註冊的指令
        for cmd in synced:
            print(f"  - /{cmd.name}")

    async def on_ready(self):
        """Bot 啟動完成"""
        print(f"{'=' * 50}")
        print(f"Bot 已上線！")
        print(f"登入為: {self.user.name} (ID: {self.user.id})")
        print(f"Discord.py 版本: {discord.__version__}")
        print(f"連接到 {len(self.guilds)} 個伺服器")

        # 同步指令到所有已加入的伺服器（立即生效）
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"  已同步 {len(synced)} 個指令到: {guild.name}")
            except Exception as e:
                print(f"  同步到 {guild.name} 失敗: {e}")

        print(f"{'=' * 50}")

        # 設定狀態
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | 音樂機器人"
            )
        )

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState
    ):
        """處理語音狀態更新（自動離開空頻道）"""
        if member.bot:
            return

        # 檢查 Bot 是否在語音頻道
        voice_client = member.guild.voice_client
        if not voice_client:
            return

        # 如果頻道只剩 Bot 自己，等待 30 秒後離開
        if len(voice_client.channel.members) == 1:
            await asyncio.sleep(30)
            # 再次檢查
            if voice_client and len(voice_client.channel.members) == 1:
                await voice_client.disconnect()
                print(f"已自動離開空頻道: {voice_client.channel.name}")


def main():
    """主程式入口"""
    if not DISCORD_TOKEN:
        print("錯誤: 請在 .env 檔案中設定 DISCORD_TOKEN")
        print("步驟:")
        print("1. 複製 .env.example 為 .env")
        print("2. 在 .env 中填入你的 Discord Bot Token")
        return

    bot = MusicBot()

    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("錯誤: Discord Token 無效，請確認 Token 是否正確")
    except Exception as e:
        print(f"錯誤: {e}")


if __name__ == "__main__":
    main()
