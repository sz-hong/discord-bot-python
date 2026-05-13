import unittest

from utils.youtube_matcher import YouTubeMatcher
from utils.recommender import CandidateTrack


class YouTubeMatcherTests(unittest.TestCase):
    def test_prefers_official_topic_match_over_cover(self):
        matcher = YouTubeMatcher()
        candidate = CandidateTrack(artist="Aimer", title="Brave Shine", source="lastfm", duration=233)
        videos = [
            {
                "id": "cover123",
                "title": "Brave Shine - Aimer cover by singer",
                "duration": 232,
                "channel": "Singer Channel",
            },
            {
                "id": "topic123",
                "title": "Brave Shine",
                "duration": 233,
                "channel": "Aimer - Topic",
            },
        ]

        selected = matcher.select_best(candidate, videos)

        self.assertEqual(selected["id"], "topic123")

    def test_rejects_video_when_title_does_not_match_candidate(self):
        matcher = YouTubeMatcher()
        candidate = CandidateTrack(artist="Aimer", title="Brave Shine", source="lastfm", duration=233)
        videos = [
            {
                "id": "wrong123",
                "title": "LiSA - Gurenge Official Music Video",
                "duration": 230,
                "channel": "LiSA Official YouTube",
            }
        ]

        selected = matcher.select_best(candidate, videos)

        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
