import unittest
from unittest.mock import patch

import metadata


ALBUM_ID = "4GHjuL2otqfI3tRLk7v5XF"
RELEASE_ID = "e7579d8b-ba86-4ba2-a575-491b408fb91c"


class MetadataTests(unittest.TestCase):
    def setUp(self):
        metadata.CACHE.clear()

    def test_spotify_url_is_normalized_and_other_hosts_are_rejected(self):
        self.assertEqual(
            metadata.parse_spotify_url(f"https://open.spotify.com/intl-tr/album/{ALBUM_ID}?si=abc"),
            ("album", ALBUM_ID, f"https://open.spotify.com/album/{ALBUM_ID}"),
        )
        with self.assertRaises(ValueError):
            metadata.parse_spotify_url(f"https://open.spotify.com.evil.test/album/{ALBUM_ID}")

    def test_exact_musicbrainz_relation_adds_artist_producer_tracks_and_label(self):
        responses = [
            {"provider_name": "Spotify", "title": "Rapido", "thumbnail_url": "https://i.scdn.co/image/example"},
            {"urls": [{"resource": f"https://open.spotify.com/album/{ALBUM_ID}", "relation-list": [{"relations": [{"release": {"id": RELEASE_ID}}]}]}]},
            {
                "title": "Rapido", "date": "2026-09-18", "artist-credit": [{"name": "Artist", "joinphrase": ""}],
                "label-info": [{"label": {"name": "Example Label"}}],
                "relations": [{"type": "producer", "artist": {"name": "Album Producer"}}],
                "media": [{"position": 1, "tracks": [{"position": 1, "title": "Song", "length": 124000,
                    "recording": {"isrcs": ["XX1234567890"], "relations": [{"type": "producer", "artist": {"name": "Track Producer"}}]}}]}],
            },
        ]
        with patch.object(metadata, "_get_json", side_effect=responses):
            result = metadata.lookup(f"https://open.spotify.com/album/{ALBUM_ID}")
        self.assertEqual(result["artist"], "Artist")
        self.assertEqual(result["producer"], ["Album Producer", "Track Producer"])
        self.assertEqual(result["label"], "Example Label")
        self.assertEqual(result["tracks"][0]["isrc"], ["XX1234567890"])
        self.assertEqual(result["duration_ms"], 124000)

    def test_missing_relation_does_not_invent_credits(self):
        responses = [
            {"provider_name": "Spotify", "title": "Example", "thumbnail_url": "https://i.scdn.co/image/example"},
            {"urls": [{"resource": f"https://open.spotify.com/album/{ALBUM_ID}", "relation-list": []}]},
        ]
        with patch.object(metadata, "_get_json", side_effect=responses):
            result = metadata.lookup(f"https://open.spotify.com/album/{ALBUM_ID}")
        self.assertIsNone(result["artist"])
        self.assertEqual(result["producer"], [])
        self.assertIsNotNone(result["note"])


if __name__ == "__main__":
    unittest.main()
