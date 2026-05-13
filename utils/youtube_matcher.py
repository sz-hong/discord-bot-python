"""
YouTube search-result scoring for music candidates.
"""

from __future__ import annotations

from typing import Optional

from utils.recommender import CandidateTrack, normalize_text


_BAD_VERSION_MARKERS = {
    "cover",
    "reaction",
    "remix",
    "nightcore",
    "karaoke",
    "live",
    "1 hour",
    "loop",
    "interview",
    "tutorial",
}


class YouTubeMatcher:
    """Pick the most likely official music result for a candidate track."""

    def __init__(self, min_score: float = 55):
        self.min_score = min_score

    def select_best(self, candidate: CandidateTrack, videos: list[dict]) -> Optional[dict]:
        scored = []
        for video in videos:
            score = self.score(candidate, video)
            if score >= self.min_score:
                scored.append((score, video))

        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1]

    def score(self, candidate: CandidateTrack, video: dict) -> float:
        title = normalize_text(video.get("title", ""))
        channel = normalize_text(video.get("channel") or video.get("uploader") or "")
        artist = normalize_text(candidate.artist)
        track_title = normalize_text(candidate.title)

        if not title or not track_title:
            return 0

        score = 0.0

        if track_title in title:
            score += 40
        else:
            title_tokens = set(track_title.split())
            if title_tokens and len(title_tokens.intersection(title.split())) / len(title_tokens) >= 0.75:
                score += 25

        if artist and (artist in title or artist in channel):
            score += 25

        if artist and (channel == f"{artist} topic" or channel.endswith(" topic")):
            score += 25
        elif artist and "official" in channel and artist in channel:
            score += 20

        if "official audio" in title or "official video" in title or "music video" in title:
            score += 10

        duration = int(video.get("duration") or 0)
        if candidate.duration and duration:
            diff = abs(candidate.duration - duration)
            if diff <= max(8, candidate.duration * 0.08):
                score += 15
            elif diff > max(45, candidate.duration * 0.35):
                score -= 25

        for marker in _BAD_VERSION_MARKERS:
            if marker in title:
                score -= 45

        return score
