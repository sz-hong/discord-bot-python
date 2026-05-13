"""
Recommendation ranking primitives.

This module is intentionally independent from Discord, Spotify, and YouTube
clients so the recommendation rules can be tested without network access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Iterable, Optional


_BRACKETED_TEXT = re.compile(r"[\[\(【（].*?[\]\)】）]")
_NON_WORD = re.compile(r"[^0-9a-zA-Z\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")
_VERSION_MARKERS = re.compile(
    r"\b(official\s+audio|official\s+video|music\s+video|mv|lyrics?|hd|hq|4k)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateTrack:
    """A track candidate before resolving it to a playable YouTube video."""

    artist: str
    title: str
    source: str
    match_score: float = 0.0
    duration: int = 0
    spotify_id: Optional[str] = None
    album_image: Optional[str] = None
    reason: str = ""
    source_scores: dict[str, float] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return canonical_track_key(self.artist, self.title)


def normalize_text(value: str) -> str:
    """Normalize multilingual music metadata for rough equality checks."""
    value = _BRACKETED_TEXT.sub(" ", value or "")
    value = value.lower()
    value = _NON_WORD.sub(" ", value)
    return " ".join(value.split())


def canonical_track_key(artist: str, title: str) -> str:
    return f"{normalize_text(artist)}::{normalize_text(title)}"


def canonical_artist_key(artist: str) -> str:
    return normalize_text(artist)


def parse_track_seed(title: str) -> tuple[str, str]:
    """Extract a rough artist/title seed from common YouTube title formats."""
    cleaned = _BRACKETED_TEXT.sub(" ", title or "")
    cleaned = _VERSION_MARKERS.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -|")

    for separator in (" - ", " – ", " — "):
        if separator in cleaned:
            left, right = cleaned.split(separator, 1)
            return left.strip(), right.strip()

    return "", cleaned


class RecommendationRanker:
    """Score and de-duplicate recommendation candidates."""

    def __init__(self, max_per_artist: int = 1):
        self.max_per_artist = max(1, max_per_artist)

    def rank(
        self,
        candidates: Iterable[CandidateTrack],
        *,
        played_keys: set[str] | None = None,
        recommended_keys: set[str] | None = None,
        preferred_artists: set[str] | None = None,
        guild_artists: set[str] | None = None,
        limit: int = 5,
    ) -> list[CandidateTrack]:
        played_keys = played_keys or set()
        recommended_keys = recommended_keys or set()
        preferred_artists = {canonical_artist_key(a) for a in (preferred_artists or set())}
        guild_artists = {canonical_artist_key(a) for a in (guild_artists or set())}

        best_by_key: dict[str, tuple[float, CandidateTrack]] = {}
        for candidate in candidates:
            if not candidate.artist or not candidate.title:
                continue
            if candidate.key in played_keys or candidate.key in recommended_keys:
                continue

            score = self._score(candidate, preferred_artists, guild_artists)
            existing = best_by_key.get(candidate.key)
            if not existing or score > existing[0]:
                best_by_key[candidate.key] = (score, candidate)

        scored = sorted(best_by_key.values(), key=lambda item: item[0], reverse=True)

        selected: list[CandidateTrack] = []
        deferred: list[CandidateTrack] = []
        artist_counts: dict[str, int] = {}

        for _, candidate in scored:
            artist_key = canonical_artist_key(candidate.artist)
            if artist_counts.get(artist_key, 0) >= self.max_per_artist:
                deferred.append(candidate)
                continue
            selected.append(candidate)
            artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
            if len(selected) >= limit:
                return selected

        for candidate in deferred:
            selected.append(candidate)
            if len(selected) >= limit:
                break

        return selected

    def _score(
        self,
        candidate: CandidateTrack,
        preferred_artists: set[str],
        guild_artists: set[str],
    ) -> float:
        artist_key = canonical_artist_key(candidate.artist)
        score = candidate.match_score * 60

        if candidate.source == "lastfm":
            score += 5
        elif candidate.source == "spotify":
            score += 3

        if artist_key in preferred_artists:
            score += 25
        if artist_key in guild_artists:
            score += 15

        title = normalize_text(candidate.title)
        if any(marker in title for marker in ("cover", "remix", "nightcore", "karaoke")):
            score -= 30

        return score


class MusicRecommender:
    """Collect candidates from providers and return ranked recommendations."""

    def __init__(self, *, lastfm_api=None, ranker: RecommendationRanker | None = None):
        self.lastfm_api = lastfm_api
        self.ranker = ranker or RecommendationRanker()

    async def recommend_for_seed(
        self,
        *,
        artist: str,
        title: str,
        spotify_recent: list[dict] | None = None,
        spotify_top: list[dict] | None = None,
        played_keys: set[str] | None = None,
        recommended_keys: set[str] | None = None,
        preferred_artists: set[str] | None = None,
        guild_artists: set[str] | None = None,
        limit: int = 5,
    ) -> list[CandidateTrack]:
        spotify_recent = spotify_recent or []
        spotify_top = spotify_top or []
        preferred_artists = set(preferred_artists or set())

        for track in spotify_top:
            first_artist = _first_artist(track)
            if first_artist:
                preferred_artists.add(first_artist)

        candidates: list[CandidateTrack] = []
        if self.lastfm_api:
            candidates.extend(await self.lastfm_api.get_similar_tracks(artist, title, limit=max(limit * 4, 20)))

        spotify_candidates = [
            self._candidate_from_spotify_track(track, source="spotify", match_score=0.52)
            for track in spotify_recent
        ]
        spotify_candidates.extend(
            self._candidate_from_spotify_track(track, source="spotify", match_score=0.48)
            for track in spotify_top
        )
        spotify_candidates = [candidate for candidate in spotify_candidates if candidate]

        if candidates:
            candidates.extend(spotify_candidates)
        else:
            candidates = spotify_candidates

        return self.ranker.rank(
            candidates,
            played_keys=played_keys,
            recommended_keys=recommended_keys,
            preferred_artists=preferred_artists,
            guild_artists=guild_artists,
            limit=limit,
        )

    def _candidate_from_spotify_track(
        self,
        track: dict,
        *,
        source: str,
        match_score: float,
    ) -> Optional[CandidateTrack]:
        title = track.get("name") or track.get("title")
        artist = _first_artist(track)
        if not artist or not title:
            return None

        duration = int((track.get("duration_ms") or 0) / 1000) if track.get("duration_ms") else int(track.get("duration") or 0)
        return CandidateTrack(
            artist=artist,
            title=title,
            source=source,
            match_score=match_score,
            duration=duration,
            spotify_id=track.get("spotify_id") or track.get("id"),
            album_image=track.get("album_image"),
            reason=f"{source}_fallback",
        )


def _first_artist(track: dict) -> str:
    artists = track.get("artists") or []
    if not artists:
        return ""

    first = artists[0]
    if isinstance(first, dict):
        return (first.get("name") or "").strip()
    return str(first).strip()
