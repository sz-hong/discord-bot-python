"""
Last.fm recommendation provider.
"""

from __future__ import annotations

import os
from typing import Optional

import aiohttp

from utils.recommender import CandidateTrack


class LastFMAPI:
    BASE_URL = "https://ws.audioscrobbler.com/2.0/"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("LASTFM_API_KEY")
        self.enabled = bool(self.api_key)

    async def get_similar_tracks(self, artist: str, title: str, limit: int = 20) -> list[CandidateTrack]:
        if not self.enabled or not artist or not title:
            return []

        params = {
            "method": "track.getSimilar",
            "artist": artist,
            "track": title,
            "autocorrect": 1,
            "limit": max(limit, 1),
            "api_key": self.api_key,
            "format": "json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.BASE_URL, params=params) as resp:
                    if resp.status != 200:
                        print(f"  Last.fm API 錯誤: {resp.status}")
                        return []
                    data = await resp.json()
        except Exception as e:
            print(f"  Last.fm API 請求失敗: {e}")
            return []

        return self.parse_similar_tracks(data)

    def parse_similar_tracks(self, data: dict) -> list[CandidateTrack]:
        raw_tracks = data.get("similartracks", {}).get("track", [])
        if isinstance(raw_tracks, dict):
            raw_tracks = [raw_tracks]

        candidates: list[CandidateTrack] = []
        for raw in raw_tracks:
            title = (raw.get("name") or "").strip()
            artist_data = raw.get("artist") or {}
            artist = (artist_data.get("name") if isinstance(artist_data, dict) else artist_data) or ""
            artist = artist.strip()

            if not artist or not title:
                continue

            candidates.append(
                CandidateTrack(
                    artist=artist,
                    title=title,
                    source="lastfm",
                    match_score=_to_float(raw.get("match")),
                    duration=_to_int(raw.get("duration")),
                    reason="lastfm_track_similar",
                )
            )

        return candidates


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


lastfm_api = LastFMAPI()
