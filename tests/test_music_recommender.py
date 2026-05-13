import unittest

from utils.recommender import CandidateTrack
from utils.recommender import MusicRecommender, canonical_track_key


class FakeLastFM:
    async def get_similar_tracks(self, artist, title, limit=20):
        return [
            CandidateTrack(artist="Unknown", title="High Match", source="lastfm", match_score=0.95),
            CandidateTrack(artist="YOASOBI", title="Lower Match", source="lastfm", match_score=0.65),
            CandidateTrack(artist="Aimer", title="Already Played", source="lastfm", match_score=0.90),
        ]


class MusicRecommenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_combines_lastfm_candidates_with_preference_signals(self):
        recommender = MusicRecommender(lastfm_api=FakeLastFM())

        results = await recommender.recommend_for_seed(
            artist="Aimer",
            title="Brave Shine",
            preferred_artists={"YOASOBI"},
            guild_artists={"YOASOBI"},
            played_keys={canonical_track_key("Aimer", "Already Played")},
            limit=2,
        )

        self.assertEqual([track.title for track in results], ["Lower Match", "High Match"])

    async def test_falls_back_to_spotify_recent_when_lastfm_has_no_candidates(self):
        class EmptyLastFM:
            async def get_similar_tracks(self, artist, title, limit=20):
                return []

        recommender = MusicRecommender(lastfm_api=EmptyLastFM())

        results = await recommender.recommend_for_seed(
            artist="Aimer",
            title="Brave Shine",
            spotify_recent=[
                {"artists": ["LiSA"], "name": "Gurenge", "spotify_id": "sp1", "duration_ms": 237000},
            ],
            limit=1,
        )

        self.assertEqual(results[0].artist, "LiSA")
        self.assertEqual(results[0].title, "Gurenge")


if __name__ == "__main__":
    unittest.main()
