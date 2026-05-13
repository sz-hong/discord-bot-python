import unittest

from utils.recommender import CandidateTrack, RecommendationRanker, canonical_track_key, parse_track_seed


class RecommendationRankerTests(unittest.TestCase):
    def test_parse_track_seed_prefers_artist_dash_title_format(self):
        seed = parse_track_seed("Aimer - Brave Shine (Official Audio)")

        self.assertEqual(seed, ("Aimer", "Brave Shine"))

    def test_parse_track_seed_handles_youtube_topic_title_format(self):
        seed = parse_track_seed("Brave Shine")

        self.assertEqual(seed, ("", "Brave Shine"))

    def test_excludes_played_and_recommended_tracks_by_canonical_key(self):
        candidates = [
            CandidateTrack(artist="Aimer", title="Brave Shine", source="lastfm", match_score=0.95),
            CandidateTrack(artist="LiSA", title="Gurenge", source="lastfm", match_score=0.80),
            CandidateTrack(artist="YOASOBI", title="Idol", source="lastfm", match_score=0.70),
        ]
        ranker = RecommendationRanker()

        ranked = ranker.rank(
            candidates,
            played_keys={canonical_track_key("Aimer", "Brave Shine")},
            recommended_keys={canonical_track_key("LiSA", "Gurenge")},
            limit=5,
        )

        self.assertEqual([track.title for track in ranked], ["Idol"])

    def test_limits_repeated_artists_before_allowing_extra_tracks(self):
        candidates = [
            CandidateTrack(artist="Aimer", title="Brave Shine", source="lastfm", match_score=0.95),
            CandidateTrack(artist="Aimer", title="Spark Again", source="lastfm", match_score=0.90),
            CandidateTrack(artist="LiSA", title="Gurenge", source="lastfm", match_score=0.80),
        ]
        ranker = RecommendationRanker(max_per_artist=1)

        ranked = ranker.rank(candidates, limit=3)

        self.assertEqual([track.artist for track in ranked[:2]], ["Aimer", "LiSA"])
        self.assertEqual(ranked[2].title, "Spark Again")

    def test_scores_spotify_and_guild_affinity_above_raw_match(self):
        candidates = [
            CandidateTrack(artist="Unknown", title="High Match", source="lastfm", match_score=0.90),
            CandidateTrack(artist="YOASOBI", title="Lower Match", source="lastfm", match_score=0.65),
        ]
        ranker = RecommendationRanker()

        ranked = ranker.rank(
            candidates,
            preferred_artists={"yoasobi"},
            guild_artists={"yoasobi"},
            limit=2,
        )

        self.assertEqual(ranked[0].title, "Lower Match")


if __name__ == "__main__":
    unittest.main()
