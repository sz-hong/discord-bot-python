import unittest

from utils.lastfm_api import LastFMAPI


class LastFMAPITests(unittest.TestCase):
    def test_parses_similar_tracks_into_candidates(self):
        api = LastFMAPI(api_key="test-key")
        payload = {
            "similartracks": {
                "track": [
                    {
                        "name": "Gurenge",
                        "match": "0.82",
                        "duration": "237",
                        "artist": {"name": "LiSA"},
                    },
                    {
                        "name": "",
                        "match": "0.5",
                        "artist": {"name": "Broken"},
                    },
                ]
            }
        }

        candidates = api.parse_similar_tracks(payload)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].artist, "LiSA")
        self.assertEqual(candidates[0].title, "Gurenge")
        self.assertEqual(candidates[0].match_score, 0.82)
        self.assertEqual(candidates[0].duration, 237)
        self.assertEqual(candidates[0].source, "lastfm")


if __name__ == "__main__":
    unittest.main()
