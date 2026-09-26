"""Check audio preservation and per-disc credits without downloading music."""

import json
import shutil
import subprocess
import unittest
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

from mutagen.id3 import APIC, TALB, TIT2, TPE1, TPOS, TRCK
from mutagen.mp3 import MP3

import audio_jobs


ROOT = Path(__file__).resolve().parent


@unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg required")
class LocalAudioTests(unittest.TestCase):
    def test_album_download_archive_keeps_separate_mp3s_and_removes_only_its_temp_files(self):
        temp_root = ROOT / f"test_audio_{uuid.uuid4().hex}"
        job_id = uuid.uuid4().hex
        directory = temp_root / job_id
        directory.mkdir(parents=True)
        other = temp_root / "keep.txt"
        other.write_text("unrelated file", encoding="utf-8")
        try:
            (directory / "01.mp3").write_bytes(b"first audio")
            (directory / "02.mp3").write_bytes(b"second audio")
            filename = audio_jobs._prepare_download(directory, "Test Albüm")
            job = {"id": job_id, "state": "done", "kind": "album", "title": "Test", "filename": filename}
            with patch.object(audio_jobs, "DOWNLOADS", temp_root), patch.dict(audio_jobs.JOBS, {job_id: job}, clear=True):
                path = audio_jobs.download_path(job_id)
                with zipfile.ZipFile(path) as archive:
                    self.assertEqual(archive.namelist(), ["01.mp3", "02.mp3"])
                    self.assertEqual(archive.read("02.mp3"), b"second audio")
                audio_jobs.downloaded(job_id)
                self.assertFalse(directory.exists())
                self.assertTrue(other.exists())
                self.assertEqual(audio_jobs.snapshot(job_id)["state"], "downloaded")
                self.assertIsNone(audio_jobs.download_path(job_id))
        finally:
            if temp_root.resolve().parent == ROOT and temp_root.name.startswith("test_audio_"):
                for path in directory.glob("*"):
                    path.unlink()
                if directory.exists():
                    directory.rmdir()
                other.unlink(missing_ok=True)
                temp_root.rmdir()

    def test_album_credits_match_disc_and_track_and_keep_cover_and_audio(self):
        directory = ROOT / f"test_audio_{uuid.uuid4().hex}"
        directory.mkdir()
        paths = [directory / "disc1.mp3", directory / "disc2.mp3"]
        details = {"kind": "album", "title": "Test", "label": "Test Label", "barcode": "12345",
                   "producer": ["Producer One", "Producer Two"], "tracks": [
                       {"disc": 1, "number": 1, "producer": ["Producer One"], "isrc": ["TR1234567890"]},
                       {"disc": 2, "number": 1, "producer": ["Producer Two"], "isrc": ["TR1234567891"]}]}
        try:
            for disc, path in enumerate(paths, 1):
                subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", "sine=frequency=440:duration=1", "-y", str(path)], check=True)
                audio = MP3(path)
                audio.tags.add(TIT2(encoding=3, text="Test"))
                audio.tags.add(TPE1(encoding=3, text="Artist"))
                audio.tags.add(TALB(encoding=3, text="Album"))
                audio.tags.add(TRCK(encoding=3, text="1/1"))
                audio.tags.add(TPOS(encoding=3, text=f"{disc}/2"))
                audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, data=b"cover-test"))
                audio.save()
            audio_jobs._enrich(directory, details)
            for index, path in enumerate(paths):
                audio = MP3(path)
                self.assertGreater(audio.info.length, 0.9)
                self.assertEqual(audio.tags.getall("APIC")[0].data, b"cover-test")
                self.assertEqual(audio.tags["TPUB"].text[0], "Test Label")
                self.assertEqual(audio.tags["TSRC"].text[0], details["tracks"][index]["isrc"][0])
                self.assertEqual(audio.tags["TXXX:PRODUCER"].text[0], details["tracks"][index]["producer"][0])
                self.assertEqual(audio.tags["TXXX:BARCODE"].text[0], "12345")
                embedded = json.loads(audio.tags["TXXX:MUZIK_BILGISI_JSON"].text[0])
                self.assertEqual(embedded["track"]["disc"], index + 1)
                self.assertEqual(embedded["metadata"], details)
        finally:
            if directory.resolve().parent == ROOT and directory.name.startswith("test_audio_"):
                for path in paths:
                    path.unlink(missing_ok=True)
                directory.rmdir()


if __name__ == "__main__":
    unittest.main()
