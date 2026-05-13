import discord
from discord.ext import commands
import asyncio

from config import DISCORD_TOKEN
from utils.auth_server import AuthServer


class MusicBot(commands.Bot):
    """Discord Music Bot"""

    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            description="Spotify + YouTube 音樂機器人"
        )
        self.auth_server = AuthServer()

    async def setup_hook(self):
        """載入 Cog、啟動 OAuth 伺服器、同步指令"""
        # 啟動 OAuth2 回調伺服器
        await self.auth_server.start()

        # 載入音樂 Cog
        await self.load_extension("cogs.music")
        print("✅ 已載入音樂模組")

        # 同步指令
        synced = await self.tree.sync()
        print(f"✅ 已同步 {len(synced)} 個斜線指令")
        for cmd in synced:
            print(f"  /{cmd.name}")

    async def on_ready(self):
        print(f"\n{'=' * 50}")
        print(f"Bot 已上線！")
        print(f"登入為: {self.user.name} (ID: {self.user.id})")
        print(f"Discord.py 版本: {discord.__version__}")
        print(f"連接到 {len(self.guilds)} 個伺服器")

        # 同步到各伺服器（立即生效）
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                print(f"  已同步 {len(synced)} 個指令到: {guild.name}")
            except Exception as e:
                print(f"  同步到 {guild.name} 失敗: {e}")

        print(f"{'=' * 50}\n")

        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="/play | /sync"
            )
        )

    async def on_voice_state_update(self, member, before, after):
        """自動離開空頻道"""
        if member.bot:
            return
        vc = member.guild.voice_client
        if not vc:
            return
        if len(vc.channel.members) == 1:
            await asyncio.sleep(30)
            if vc and len(vc.channel.members) == 1:
                await vc.disconnect()
                print(f"自動離開空頻道: {vc.channel.name}")

    async def close(self):
        """關閉時停止 OAuth 伺服器"""
        await self.auth_server.stop()
        await super().close()


def main():
    if not DISCORD_TOKEN:
        print("錯誤: 請在 .env 設定 DISCORD_TOKEN")
        return

    bot = MusicBot()

    try:
        bot.run(DISCORD_TOKEN)
    except discord.LoginFailure:
        print("錯誤: Discord Token 無效")
    except Exception as e:
        print(f"錯誤: {e}")


if __name__ == "__main__":
    main()
