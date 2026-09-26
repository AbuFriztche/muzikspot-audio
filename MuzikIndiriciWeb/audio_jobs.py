"""Local, bounded spotDL jobs. Spotify supplies metadata; audio comes from another provider."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

from metadata import lookup, parse_spotify_url


ROOT = Path(__file__).resolve().parent
# spotDL sanitizes leading dots in output directories, so use a plain temp name.
DOWNLOADS = Path(os.environ.get("AUDIO_TEMP_DIR", str(ROOT / "audio-temp"))).resolve()
_local_spotdl = ROOT / ".venv" / ("Scripts/spotdl.exe" if sys.platform == "win32" else "bin/spotdl")
SPOTDL = _local_spotdl if _local_spotdl.is_file() else Path(shutil.which("spotdl") or str(_local_spotdl))
FFMPEG = shutil.which("ffmpeg")
JOBS: dict[str, dict] = {}
LOCK = threading.Lock()
MAX_ACTIVE = 3
TEMP_LIFETIME = 15 * 60


def available() -> bool:
    return SPOTDL.is_file() and bool(FFMPEG)


def _files(job: dict) -> list[dict]:
    directory = DOWNLOADS / job["id"]
    return [
        {"name": path.name, "bytes": path.stat().st_size}
        for path in _file_paths(directory)
    ] if directory.is_dir() else []


def _file_paths(directory: Path) -> list[Path]:
    return [path for path in sorted(directory.glob("*.mp3"))
            if path.is_file() and path.stat().st_size > 0]


def snapshot(job_id: str, owner: str | None = None) -> dict | None:
    try:
        if uuid.UUID(job_id).hex != job_id:
            return None
    except (ValueError, AttributeError):
        return None
    with LOCK:
        job = JOBS.get(job_id)
        if job is None or (owner is not None and job.get("owner", "local") != owner):
            return None
        result = {key: job.get(key) for key in ("id", "state", "kind", "title", "message", "error", "source")}
    result["files"] = _files(job)
    if job["state"] == "done":
        result["download"] = {"name": job["filename"], "url": f"/api/audio-jobs/{job_id}/download"}
    return result


def list_jobs(owner: str = "local") -> list[dict]:
    with LOCK:
        ids = [key for key, job in JOBS.items() if job.get("owner", "local") == owner][-10:][::-1]
    return [state for job_id in ids if (state := snapshot(job_id, owner))]


def download_path(job_id: str, owner: str | None = None) -> Path | None:
    state = snapshot(job_id, owner)
    if not state or state["state"] != "done":
        return None
    path = DOWNLOADS / job_id / state["download"]["name"]
    if path.is_file():
        return path
    return None


def start(raw_url: str, owner: str = "local") -> dict:
    kind, _, canonical = parse_spotify_url(raw_url)
    if not available():
        raise RuntimeError("İndirme sunucusunda spotDL ve FFmpeg kurulmalı.")
    with LOCK:
        active = sum(job["state"] in {"queued", "running"} for job in JOBS.values())
        if active >= MAX_ACTIVE:
            raise RuntimeError("Aynı anda en fazla üç indirme işi çalışabilir.")
        job_id = uuid.uuid4().hex
        job = {"id": job_id, "owner": owner, "url": canonical, "kind": kind, "title": "Albüm" if kind == "album" else "Şarkı", "state": "queued",
               "message": "İndirme sırasına alındı.", "error": None, "source": "YouTube / YouTube Music"}
        JOBS[job_id] = job
    threading.Thread(target=_run, args=(job,), daemon=True).start()
    return snapshot(job_id)


def _set(job: dict, **values) -> None:
    with LOCK:
        job.update(values)


def _remove_temp(job_id: str) -> None:
    """Remove only this app's UUID-named temporary job directory."""
    try:
        if uuid.UUID(job_id).hex != job_id:
            return
        directory = (DOWNLOADS / job_id).resolve()
        if directory.parent != DOWNLOADS.resolve() or directory.name != job_id:
            return
        shutil.rmtree(directory)
    except (OSError, ValueError):
        pass


def downloaded(job_id: str) -> None:
    with LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        job.update(state="downloaded", message="Dosya tarayıcıya gönderildi.")
    _remove_temp(job_id)


def _expire(job_id: str) -> None:
    with LOCK:
        job = JOBS.get(job_id)
        if job is None or job["state"] in {"queued", "running"}:
            return
        if job["state"] == "done":
            job.update(state="expired", message="İndirme süresi doldu. Yeniden İndir'e bas.")
    _remove_temp(job_id)


def _schedule_cleanup(job_id: str) -> None:
    timer = threading.Timer(TEMP_LIFETIME, _expire, args=(job_id,))
    timer.daemon = True
    timer.start()


def _prepare_download(directory: Path, title: str) -> str:
    files = _file_paths(directory)
    if len(files) == 1:
        return files[0].name
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100] or "Album"
    filename += ".zip"
    with zipfile.ZipFile(directory / filename, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files:
            archive.write(path, arcname=path.name)
    return filename


def _enrich(directory: Path, details: dict) -> None:
    """Add verified MusicBrainz credits to the tags written by spotDL."""
    try:
        from mutagen.id3 import TIPL, TPUB, TSRC, TXXX
        from mutagen.mp3 import MP3
    except ImportError:
        return
    tracks = details.get("tracks") or []
    for path in directory.glob("*.mp3"):
        audio = MP3(path)
        if audio.tags is None:
            continue
        tags = audio.tags
        def position(key: str) -> int | None:
            value = tags.get(key)
            try:
                return int(str(value.text[0]).split("/")[0]) if value else None
            except (ValueError, IndexError):
                return None
        number, disc = position("TRCK"), position("TPOS") or 1
        track = next((item for item in tracks if item.get("number") == number and (item.get("disc") or 1) == disc), None)
        # Album lookup aggregates all producer credits; only use credits for this track.
        producers = (track or {}).get("producer") if details.get("kind") == "album" else details.get("producer")
        producers = producers or []
        if producers:
            tags.delall("TIPL")
            tags.add(TIPL(encoding=3, people=[("producer", name) for name in producers]))
            tags.delall("TXXX:PRODUCER")
            tags.add(TXXX(encoding=3, desc="PRODUCER", text=producers))
        if details.get("label"):
            tags.delall("TPUB")
            tags.add(TPUB(encoding=3, text=details["label"]))
        isrc = (track or {}).get("isrc") or (details.get("isrc") if details.get("kind") == "track" else [])
        if isrc:
            tags.delall("TSRC")
            tags.add(TSRC(encoding=3, text=isrc))
        if details.get("barcode"):
            tags.delall("TXXX:BARCODE")
            tags.add(TXXX(encoding=3, desc="BARCODE", text=details["barcode"]))
        tags.delall("TXXX:MUZIK_BILGISI_JSON")
        tags.add(TXXX(encoding=3, desc="MUZIK_BILGISI_JSON",
                      text=json.dumps({"metadata": details, "track": track}, ensure_ascii=False)))
        tags.save(path, v2_version=3)


def _run(job: dict) -> None:
    directory = DOWNLOADS / job["id"]
    try:
        directory.mkdir(parents=True, exist_ok=False)
        _set(job, state="running", message="Spotify bilgileri ve ses eşleşmesi aranıyor.")
        try:
            details = lookup(job["url"])
            _set(job, title=details.get("title") or job["title"])
        except Exception:
            details = None
        command = [str(SPOTDL), "download", job["url"], "--format", "mp3",
                   "--threads", "4", "--ffmpeg", str(FFMPEG),
                   "--output", str(directory / "{disc-number}-{track-number} - {artists} - {title}.{output-ext}"),
                   "--simple-tui", "--log-level", "INFO", "--print-errors"]
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace")
        tail: list[str] = []
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.strip()
            if clean:
                tail.append(clean[-250:])
                tail = tail[-8:]
                count = len(list(directory.glob("*.mp3")))
                _set(job, message=f"Ses indiriliyor ve etiketleniyor… {count} MP3 hazır.")
        code = process.wait()
        files = _files(job)
        tag_warning = False
        if files and details:
            try:
                _enrich(directory, details)
            except Exception:
                tag_warning = True
        if files:
            filename = _prepare_download(directory, job["title"])
            message = f"{len(files)} MP3 hazır. Tarayıcı indirmesi başlatılıyor…"
            if code or (details and job["kind"] == "album" and len(details.get("tracks") or []) > len(files)):
                message += " Bazı parçalar bulunamamış olabilir."
            if tag_warning:
                message += " Ek MusicBrainz etiketleri yazılamadı; temel şarkı etiketleri mevcut."
            _set(job, state="done", filename=filename, message=message, error=None)
        else:
            reason = next((line for line in reversed(tail) if "error" in line.lower() or "failed" in line.lower()), None)
            _set(job, state="failed", message="Ses dosyası hazırlanamadı.",
                 error=reason or "Alternatif ses kaynağı bu parça için kullanılabilir bir dosya döndürmedi.")
    except Exception as exc:
        _set(job, state="failed", message="Ses dosyası hazırlanamadı.", error=str(exc)[:300])
    finally:
        if job["state"] == "failed":
            _remove_temp(job["id"])
        _schedule_cleanup(job["id"])
