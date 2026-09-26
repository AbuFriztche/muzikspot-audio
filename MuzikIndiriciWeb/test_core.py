"""Small end-to-end check using files served by a local HTTP server."""

import base64
import functools
import shutil
import subprocess
import threading
import unittest
import uuid
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import ID3

from core import process, validate


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg=="
)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


class DownloadTest(unittest.TestCase):
    def test_album_files_have_tags_and_cover(self):
        root = Path(__file__).parent / ("test_run_" + uuid.uuid4().hex)
        root.mkdir()
        try:
            source = root / "source"
            source.mkdir()
            for fmt in ("mp3", "flac"):
                subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                     "-i", "sine=frequency=440:duration=1", "-y", str(source / f"song.{fmt}")],
                    check=True, stdout=subprocess.DEVNULL,
                )
            server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(source)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                payload = {
                    "album": {"album": "Test Albüm", "album_artist": "Test Sanatçı", "date": "2026", "genre": "Pop"},
                    "tracks": [
                        {"url": base + "/song.mp3", "title": "Birinci", "artist": "Test Sanatçı", "format": "mp3"},
                        {"url": base + "/song.flac", "title": "İkinci", "artist": "Test Sanatçı", "format": "flac"},
                    ],
                    "cover": {"data": base64.b64encode(PNG_1X1).decode()},
                    "output_dir": str(root / "output"), "workers": 2,
                }
                events = []
                process(payload, events.append)
                self.assertEqual([event["status"] for event in events].count("tamamlandı"), 2)
                outputs = list((root / "output").rglob("*.*"))
                self.assertEqual(len(outputs), 2)
                mp3 = ID3(next(path for path in outputs if path.suffix == ".mp3"))
                flac = FLAC(next(path for path in outputs if path.suffix == ".flac"))
                self.assertEqual(mp3["TIT2"].text[0], "Birinci")
                self.assertEqual(mp3["TALB"].text[0], "Test Albüm")
                self.assertTrue(mp3.getall("APIC"))
                self.assertEqual(flac["title"][0], "İkinci")
                self.assertEqual(flac["album"][0], "Test Albüm")
                self.assertTrue(flac.pictures)
            finally:
                server.shutdown()
                server.server_close()
        finally:
            if root.resolve().is_relative_to(Path(__file__).parent.resolve()):
                shutil.rmtree(root)

    def test_spotify_page_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Spotify bağlantısı"):
            validate({
                "album": {},
                "tracks": [{"url": "https://open.spotify.com/album/example", "title": "Örnek", "artist": "Sanatçı", "format": "mp3"}],
            })


if __name__ == "__main__":
    unittest.main()
