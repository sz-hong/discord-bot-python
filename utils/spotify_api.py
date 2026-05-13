"""
Spotify User API 模組

使用 User OAuth2 Token 呼叫 Spotify Web API
取得使用者的播放狀態和播放紀錄
"""

import asyncio
from typing import Optional

import aiohttp

from utils.spotify_auth import spotify_auth


class SpotifyUserAPI:
    """呼叫需要 User Token 的 Spotify API"""

    BASE_URL = "https://api.spotify.com/v1"

    async def _request(self, discord_user_id: int, endpoint: str, params: dict = None) -> Optional[dict]:
        """發送 authenticated GET request"""
        token = await spotify_auth.get_access_token(discord_user_id)
        if not token:
            return None

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.BASE_URL}/{endpoint}",
                    headers={"Authorization": f"Bearer {token}"},
                    params=params,
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 204:
                        return None  # No content (沒有在播放)
                    else:
                        error = await resp.text()
                        print(f"  Spotify API 錯誤 ({endpoint}): {resp.status} {error[:200]}")
                        return None
        except Exception as e:
            print(f"  Spotify API 請求失敗 ({endpoint}): {e}")
            return None

    async def get_currently_playing(self, discord_user_id: int) -> Optional[dict]:
        """
        取得使用者目前正在播放的歌曲

        Returns:
            {
                name: str,
                artists: [str],
                album: str,
                album_image: str,
                spotify_id: str,
                search_query: str,    # "歌手 歌名" (用於 YouTube 搜尋)
                duration_ms: int,
                progress_ms: int,
                is_playing: bool,
            }
            或 None（沒有在播放）
        """
        data = await self._request(discord_user_id, "me/player/currently-playing")
        if not data or not data.get('item'):
            return None

        track = data['item']
        artists = [a['name'] for a in track.get('artists', [])]

        return {
            'name': track['name'],
            'artists': artists,
            'album': track.get('album', {}).get('name', '未知'),
            'album_image': self._get_album_image(track),
            'spotify_id': track['id'],
            'search_query': f"{artists[0]} {track['name']}" if artists else track['name'],
            'duration_ms': track.get('duration_ms', 0),
            'progress_ms': data.get('progress_ms', 0),
            'is_playing': data.get('is_playing', False),
        }

    async def get_recently_played(self, discord_user_id: int, limit: int = 10) -> list[dict]:
        """
        取得使用者最近播放的歌曲

        Returns:
            [
                {
                    name: str,
                    artists: [str],
                    album: str,
                    album_image: str,
                    spotify_id: str,
                    search_query: str,
                    played_at: str,
                },
                ...
            ]
        """
        data = await self._request(
            discord_user_id, "me/player/recently-played",
            params={"limit": min(limit, 50)},
        )
        if not data or not data.get('items'):
            return []

        tracks = []
        seen = set()
        for item in data['items']:
            track = item.get('track', {})
            if not track or track['id'] in seen:
                continue
            seen.add(track['id'])

            artists = [a['name'] for a in track.get('artists', [])]
            tracks.append({
                'name': track['name'],
                'artists': artists,
                'album': track.get('album', {}).get('name', '未知'),
                'album_image': self._get_album_image(track),
                'spotify_id': track['id'],
                'search_query': f"{artists[0]} {track['name']}" if artists else track['name'],
                'duration_ms': track.get('duration_ms', 0),
                'played_at': item.get('played_at', ''),
            })

        return tracks

    async def get_top_tracks(
        self,
        discord_user_id: int,
        limit: int = 20,
        time_range: str = "short_term",
    ) -> list[dict]:
        """取得使用者常聽歌曲，作為推薦加權訊號。"""
        if time_range not in {"short_term", "medium_term", "long_term"}:
            time_range = "short_term"

        data = await self._request(
            discord_user_id,
            "me/top/tracks",
            params={"limit": min(limit, 50), "time_range": time_range},
        )
        if not data or not data.get('items'):
            return []

        tracks = []
        for track in data['items']:
            artists = [a['name'] for a in track.get('artists', [])]
            tracks.append({
                'name': track['name'],
                'artists': artists,
                'album': track.get('album', {}).get('name', '未知'),
                'album_image': self._get_album_image(track),
                'spotify_id': track['id'],
                'search_query': f"{artists[0]} {track['name']}" if artists else track['name'],
                'duration_ms': track.get('duration_ms', 0),
            })

        return tracks

    async def get_autoplay_tracks(self, discord_user_id: int, limit: int = 5, exclude_ids: set = None) -> list[dict]:
        """
        取得自動播放用的歌曲：從最近播放紀錄中挑選

        策略：取得最近播放的歌，排除已在歷史中的，回傳前 limit 首
        """
        exclude_ids = exclude_ids or set()
        recent = await self.get_recently_played(discord_user_id, limit=30)

        results = []
        for track in recent:
            if track['spotify_id'] not in exclude_ids:
                results.append(track)
                if len(results) >= limit:
                    break

        return results

    def _get_album_image(self, track: dict) -> Optional[str]:
        """取得專輯封面圖片 URL"""
        images = track.get('album', {}).get('images', [])
        if images:
            # 取中等大小
            for img in images:
                if img.get('width', 0) == 300:
                    return img['url']
            return images[0]['url']
        return None


# 全域實例
spotify_api = SpotifyUserAPI()
