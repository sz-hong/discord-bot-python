"""
輕量 HTTP 伺服器 — 處理 Spotify OAuth2 回調

Bot 啟動時在背景開一個 HTTP server (預設 port 8888)，
等使用者在瀏覽器授權後 Spotify 會重導到這裡。
"""

import asyncio
from aiohttp import web

from utils.spotify_auth import spotify_auth
from config import SPOTIFY_REDIRECT_URI


class AuthServer:
    """處理 Spotify OAuth2 callback 的輕量伺服器"""

    def __init__(self):
        self.app = web.Application()
        self.app.router.add_get("/callback", self._handle_callback)
        self.runner = None

    async def _handle_callback(self, request: web.Request) -> web.Response:
        """處理 Spotify OAuth2 回調"""
        code = request.query.get("code")
        state = request.query.get("state")
        error = request.query.get("error")

        if error:
            return web.Response(
                text=self._html_page("❌ 授權失敗", f"Spotify 回傳錯誤: {error}"),
                content_type="text/html",
            )

        if not code or not state:
            return web.Response(
                text=self._html_page("❌ 參數缺失", "缺少 code 或 state 參數"),
                content_type="text/html",
            )

        discord_user_id = await spotify_auth.handle_callback(code, state)

        if discord_user_id:
            return web.Response(
                text=self._html_page(
                    "✅ 授權成功！",
                    "你的 Spotify 帳號已成功連結到 Discord 機器人。<br>你可以關閉此頁面，回到 Discord 使用 <code>/sync</code> 同步播放。"
                ),
                content_type="text/html",
            )
        else:
            return web.Response(
                text=self._html_page("❌ 授權失敗", "無效的 state 參數，請重新使用 /login 指令。"),
                content_type="text/html",
            )

    def _html_page(self, title: str, message: str) -> str:
        """產生簡單的 HTML 回應頁面"""
        return f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            display: flex; justify-content: center; align-items: center;
            min-height: 100vh; margin: 0;
            background: linear-gradient(135deg, #1DB954 0%, #191414 100%);
            color: white;
        }}
        .card {{
            background: rgba(0,0,0,0.6); border-radius: 16px;
            padding: 40px; text-align: center; max-width: 400px;
            backdrop-filter: blur(10px);
        }}
        h1 {{ font-size: 2em; margin-bottom: 10px; }}
        p {{ font-size: 1.1em; opacity: 0.9; line-height: 1.6; }}
        code {{ background: rgba(255,255,255,0.15); padding: 2px 8px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{title}</h1>
        <p>{message}</p>
    </div>
</body>
</html>"""

    async def start(self):
        """啟動 HTTP 伺服器"""
        try:
            # 從 REDIRECT_URI 中解析 port
            port = 8888
            if SPOTIFY_REDIRECT_URI:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(SPOTIFY_REDIRECT_URI)
                    if parsed.port:
                        port = parsed.port
                except Exception:
                    pass

            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            site = web.TCPSite(self.runner, "0.0.0.0", port)
            await site.start()
            print(f"✅ OAuth2 回調伺服器已啟動 (port {port})")
        except Exception as e:
            print(f"⚠️ OAuth2 回調伺服器啟動失敗: {e}")
            print("  Spotify 登入功能將無法使用")

    async def stop(self):
        """停止 HTTP 伺服器"""
        if self.runner:
            await self.runner.cleanup()
