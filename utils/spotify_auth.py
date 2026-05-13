"""
Spotify User OAuth2 認證模組

負責：
- 產生 Spotify 授權連結
- 處理 OAuth2 回調
- 儲存/讀取每位使用者的 token
- 自動刷新過期 token
"""

import json
import os
import asyncio
import time
from typing import Optional
from pathlib import Path

import aiohttp

from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI, SPOTIFY_SCOPES


# Token 儲存路徑
DATA_DIR = Path(__file__).parent.parent / "data"
TOKEN_FILE = DATA_DIR / "spotify_tokens.json"


class SpotifyAuth:
    """管理 Spotify User OAuth2 認證"""

    def __init__(self):
        self.enabled = bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)
        self._tokens: dict[str, dict] = {}  # {discord_user_id: token_data}
        self._pending_states: dict[str, str] = {}  # {state: discord_user_id}
        self._load_tokens()

        if self.enabled:
            print("✅ Spotify OAuth2 已設定")
        else:
            print("⚠️ Spotify OAuth2 未設定（缺少 CLIENT_ID 或 CLIENT_SECRET）")

    # ─── Token 持久化 ────────────────────────────────────────

    def _load_tokens(self):
        """從檔案載入 tokens"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            if TOKEN_FILE.exists():
                with open(TOKEN_FILE, 'r') as f:
                    self._tokens = json.load(f)
                print(f"  已載入 {len(self._tokens)} 位使用者的 Spotify Token")
        except Exception as e:
            print(f"  載入 Spotify Token 失敗: {e}")

    def _save_tokens(self):
        """儲存 tokens 到檔案"""
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(TOKEN_FILE, 'w') as f:
                json.dump(self._tokens, f, indent=2)
        except Exception as e:
            print(f"  儲存 Spotify Token 失敗: {e}")

    # ─── OAuth2 流程 ─────────────────────────────────────────

    def get_auth_url(self, discord_user_id: int) -> str:
        """產生 Spotify 授權連結"""
        import secrets
        from urllib.parse import urlencode

        state = secrets.token_urlsafe(32)
        self._pending_states[state] = str(discord_user_id)

        params = {
            "client_id": SPOTIFY_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": SPOTIFY_REDIRECT_URI,
            "scope": " ".join(SPOTIFY_SCOPES),
            "state": state,
            "show_dialog": "true",
        }
        return f"https://accounts.spotify.com/authorize?{urlencode(params)}"

    async def handle_callback(self, code: str, state: str) -> Optional[str]:
        """
        處理 OAuth2 回調，交換 code 取得 token

        Returns:
            成功時回傳 discord_user_id，失敗回傳 None
        """
        discord_user_id = self._pending_states.pop(state, None)
        if not discord_user_id:
            return None

        token_data = await self._exchange_code(code)
        if not token_data:
            return None

        token_data['obtained_at'] = int(time.time())
        self._tokens[discord_user_id] = token_data
        self._save_tokens()

        return discord_user_id

    async def _exchange_code(self, code: str) -> Optional[dict]:
        """用 authorization code 交換 access token"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": SPOTIFY_REDIRECT_URI,
                    },
                    auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        error = await resp.text()
                        print(f"  Spotify token 交換失敗: {resp.status} {error}")
                        return None
        except Exception as e:
            print(f"  Spotify token 交換錯誤: {e}")
            return None

    # ─── Token 管理 ──────────────────────────────────────────

    def is_logged_in(self, discord_user_id: int) -> bool:
        """檢查使用者是否已登入 Spotify"""
        return str(discord_user_id) in self._tokens

    async def get_access_token(self, discord_user_id: int) -> Optional[str]:
        """取得有效的 access token（自動刷新過期 token）"""
        user_id = str(discord_user_id)
        token_data = self._tokens.get(user_id)
        if not token_data:
            return None

        # 檢查是否過期（提前 60 秒刷新）
        obtained_at = token_data.get('obtained_at', 0)
        expires_in = token_data.get('expires_in', 3600)
        if time.time() > obtained_at + expires_in - 60:
            print(f"  Spotify token 已過期，正在刷新...")
            refreshed = await self._refresh_token(token_data.get('refresh_token'))
            if refreshed:
                refreshed['obtained_at'] = int(time.time())
                # refresh token 不一定會回傳新的，保留舊的
                if 'refresh_token' not in refreshed:
                    refreshed['refresh_token'] = token_data['refresh_token']
                self._tokens[user_id] = refreshed
                self._save_tokens()
                return refreshed['access_token']
            else:
                # 刷新失敗，移除 token
                del self._tokens[user_id]
                self._save_tokens()
                return None

        return token_data['access_token']

    async def _refresh_token(self, refresh_token: str) -> Optional[dict]:
        """用 refresh token 取得新的 access token"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://accounts.spotify.com/api/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    auth=aiohttp.BasicAuth(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    else:
                        print(f"  Spotify token 刷新失敗: {resp.status}")
                        return None
        except Exception as e:
            print(f"  Spotify token 刷新錯誤: {e}")
            return None

    def logout(self, discord_user_id: int) -> bool:
        """登出（刪除 token）"""
        user_id = str(discord_user_id)
        if user_id in self._tokens:
            del self._tokens[user_id]
            self._save_tokens()
            return True
        return False


# 全域實例
spotify_auth = SpotifyAuth()
