"""End-to-end check of browser-side ID3 and ZIP output using a real MP3."""

import json
import shutil
import subprocess
import unittest
import uuid
import zipfile
from pathlib import Path

from mutagen.id3 import ID3
from mutagen.mp3 import MP3


ROOT = Path(__file__).parent.resolve()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("node"), "ffmpeg and Node.js required")
class TaggingTests(unittest.TestCase):
    def test_mp3_and_album_zip_keep_audio_and_embed_metadata(self):
        token = uuid.uuid4().hex
        paths = {name: ROOT / f"test_tagging_{token}_{name}" for name in
                 ("source.mp3", "tagged.mp3", "album.zip", "metadata.json")}
        try:
            subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=1", "-y", str(paths["source.mp3"]),
            ], check=True)
            paths["metadata.json"].write_text(json.dumps({
                "kind": "album", "title": "Test Albüm", "artist": "Test Sanatçı",
                "date": "2026-09-25", "genre": ["Pop"], "label": "Test Label",
                "barcode": "123456", "spotify_url": "https://open.spotify.com/album/test",
                "musicbrainz_url": None, "tracks": [{"title": "Birinci", "number": 1, "disc": 1,
                    "artist": "Test Sanatçı", "producer": ["Test Yapımcı"],
                    "isrc": ["TR1234567890"], "duration_ms": 1000}],
            }), encoding="utf-8")
            script = """
const fs = require('fs');
const {tagMp3} = require(process.argv[1]);
const {zip} = require(process.argv[2]);
const data = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const cover = Uint8Array.from(Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64'));
const output = tagMp3(fs.readFileSync(process.argv[4]), data, data.tracks[0], cover, 'image/png');
fs.writeFileSync(process.argv[5], output);
zip([{name:'01 Birinci.mp3',bytes:output},{name:'02 Birinci.mp3',bytes:output}]).arrayBuffer().then(buffer => fs.writeFileSync(process.argv[6], Buffer.from(buffer)));
"""
            subprocess.run(["node", "-e", script, str(ROOT / "id3.js"), str(ROOT / "zip.js"),
                            str(paths["metadata.json"]), str(paths["source.mp3"]),
                            str(paths["tagged.mp3"]), str(paths["album.zip"])], check=True)
            tags = ID3(paths["tagged.mp3"])
            self.assertEqual(tags["TIT2"].text[0], "Birinci")
            self.assertEqual(tags["TPE1"].text[0], "Test Sanatçı")
            self.assertEqual(tags["TALB"].text[0], "Test Albüm")
            self.assertEqual(tags["TPUB"].text[0], "Test Label")
            self.assertEqual(tags["TSRC"].text[0], "TR1234567890")
            self.assertEqual(tags.getall("TXXX:PRODUCER")[0].text[0], "Test Yapımcı")
            self.assertEqual(tags.getall("APIC")[0].mime, "image/png")
            self.assertGreater(MP3(paths["tagged.mp3"]).info.length, 0.9)
            with zipfile.ZipFile(paths["album.zip"]) as zipped:
                self.assertEqual(zipped.namelist(), ["01 Birinci.mp3", "02 Birinci.mp3"])
                self.assertEqual(zipped.read("01 Birinci.mp3"), paths["tagged.mp3"].read_bytes())
        finally:
            for path in paths.values():
                if path.resolve().parent == ROOT and path.name.startswith(f"test_tagging_{token}_"):
                    path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
