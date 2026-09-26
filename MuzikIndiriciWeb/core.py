"""Download directly linked MP3/FLAC files and write their metadata."""

from __future__ import annotations

import base64
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, COMM, ID3, ID3NoHeaderError, TALB, TBPM, TCOM, TCON, TCOP,
    TDRC, TIT2, TLAN, TPE1, TPE2, TPOS, TPUB, TRCK, TSRC, USLT,
)
from mutagen.mp3 import MP3

FORMATS = {"mp3", "flac"}
MAX_COVER = 10 * 1024 * 1024
TEXT_FIELDS = (
    "title", "artist", "album", "album_artist", "date", "genre", "composer",
    "isrc", "publisher", "copyright", "comment", "lyrics", "language", "bpm",
)


def clean(value):
    return "" if value is None else str(value).strip()


def safe_filename(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:150] or "Bilinmeyen"


def positive_int(value, label):
    try:
        number = int(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{label} pozitif bir tam sayı olmalı.") from exc
    if number < 1:
        raise ValueError(f"{label} pozitif bir tam sayı olmalı.")
    return number


def check_url(value):
    parsed = urlparse(value)
    if parsed.hostname and parsed.hostname.lower() in {"spotify.com", "open.spotify.com"}:
        raise ValueError("Spotify bağlantısı doğrudan ses dosyası değildir. MP3 veya FLAC dosyasının bağlantısını girin.")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Bağlantı http(s) ile başlayan doğrudan dosya URL'si olmalı.")
    return value


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("Geçersiz istek.")
    album = payload.get("album") or {}
    tracks = payload.get("tracks")
    if not isinstance(album, dict) or not isinstance(tracks, list) or not tracks:
        raise ValueError("En az bir parça gerekli.")
    if len(tracks) > 500:
        raise ValueError("Bir seferde en fazla 500 parça eklenebilir.")
    workers = positive_int(payload.get("workers", 4), "Eşzamanlı indirme sayısı")
    if workers > 8:
        raise ValueError("En fazla 8 eşzamanlı indirme kullanılabilir.")
    output_dir = Path(clean(payload.get("output_dir")) or str(Path.home() / "Music" / "MuzikIndirici")).expanduser()
    cover = payload.get("cover") or {}
    if not isinstance(cover, dict):
        raise ValueError("Kapak bilgisi geçersiz.")
    if cover.get("url"):
        check_url(clean(cover["url"]))
    if cover.get("data") and len(clean(cover["data"])) > MAX_COVER * 1.5:
        raise ValueError("Kapak 10 MB sınırını aşıyor.")
    normalized = []
    for index, raw in enumerate(tracks, 1):
        if not isinstance(raw, dict):
            raise ValueError(f"{index}. parça geçersiz.")
        meta = {key: clean(album.get(key)) for key in TEXT_FIELDS}
        meta.update({key: clean(raw[key]) for key in TEXT_FIELDS if key in raw})
        if not meta["title"] or not meta["artist"]:
            raise ValueError(f"{index}. parçada ad ve sanatçı gerekli.")
        url = check_url(clean(raw.get("url")))
        fmt = clean(raw.get("format")).lower() or Path(urlparse(url).path).suffix.lstrip(".").lower()
        if fmt not in FORMATS:
            raise ValueError(f"{index}. parçada format MP3 veya FLAC olmalı.")
        meta["track_number"] = positive_int(raw.get("track_number") or index, "Parça numarası")
        meta["disc_number"] = positive_int(raw.get("disc_number") or 1, "Disk numarası")
        normalized.append({"url": url, "format": fmt, "meta": meta})
    track_total = len(normalized)
    disc_total = max(item["meta"]["disc_number"] for item in normalized)
    for item in normalized:
        item["meta"]["track_total"] = track_total
        item["meta"]["disc_total"] = disc_total
    return normalized, output_dir, workers, cover


def image_bytes(cover):
    source = clean(cover.get("url"))
    encoded = clean(cover.get("data"))
    if encoded:
        try:
            image = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError("Kapak dosyası okunamadı.") from exc
    elif source:
        request = Request(source, headers={"User-Agent": "MuzikIndiriciWeb/1.0"})
        with urlopen(request, timeout=30) as response:
            image = response.read(MAX_COVER + 1)
    else:
        return None
    if len(image) > MAX_COVER:
        raise ValueError("Kapak 10 MB sınırını aşıyor.")
    if image.startswith(b"\xff\xd8\xff"):
        return image, "image/jpeg"
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return image, "image/png"
    raise ValueError("Kapak JPEG veya PNG olmalı.")


def tag_file(path, fmt, meta, cover):
    if fmt == "mp3":
        MP3(path)  # Invalid responses such as HTML must never become finished files.
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        mapping = {
            TIT2: "title", TPE1: "artist", TALB: "album", TPE2: "album_artist",
            TDRC: "date", TCON: "genre", TCOM: "composer", TSRC: "isrc",
            TPUB: "publisher", TCOP: "copyright", TLAN: "language", TBPM: "bpm",
        }
        for frame, field in mapping.items():
            if meta[field]:
                tags.setall(frame.__name__, [frame(encoding=3, text=meta[field])])
        tags.setall("TRCK", [TRCK(encoding=3, text=f"{meta['track_number']}/{meta['track_total']}")])
        tags.setall("TPOS", [TPOS(encoding=3, text=f"{meta['disc_number']}/{meta['disc_total']}")])
        if meta["comment"]:
            tags.setall("COMM", [COMM(encoding=3, lang="eng", desc="", text=meta["comment"])])
        if meta["lyrics"]:
            tags.setall("USLT", [USLT(encoding=3, lang="eng", desc="", text=meta["lyrics"])])
        if cover:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=cover[1], type=3, desc="Cover", data=cover[0]))
        tags.save(path)
    else:
        audio = FLAC(path)
        mapping = {
            "TITLE": "title", "ARTIST": "artist", "ALBUM": "album",
            "ALBUMARTIST": "album_artist", "DATE": "date", "GENRE": "genre",
            "COMPOSER": "composer", "ISRC": "isrc", "PUBLISHER": "publisher",
            "COPYRIGHT": "copyright", "COMMENT": "comment", "LYRICS": "lyrics",
            "LANGUAGE": "language", "BPM": "bpm", "TRACKNUMBER": "track_number",
            "TRACKTOTAL": "track_total", "DISCNUMBER": "disc_number",
            "DISCTOTAL": "disc_total",
        }
        for tag, field in mapping.items():
            if meta[field]:
                audio[tag] = str(meta[field])
        if cover:
            picture = Picture()
            picture.type, picture.mime, picture.data = 3, cover[1], cover[0]
            audio.clear_pictures()
            audio.add_picture(picture)
        audio.save()


def destinations(tracks, output_dir):
    used = set()
    paths = []
    for item in tracks:
        meta = item["meta"]
        folder = output_dir
        if meta["album"]:
            folder /= safe_filename(f"{meta['album_artist'] or meta['artist']} - {meta['album']}")
        disc = f"{meta['disc_number']:02d}-" if meta["disc_total"] > 1 else ""
        stem = safe_filename(f"{disc}{meta['track_number']:02d} - {meta['artist']} - {meta['title']}")
        path = folder / f"{stem}.{item['format']}"
        duplicate = 2
        while str(path).casefold() in used:
            path = folder / f"{stem} ({duplicate}).{item['format']}"
            duplicate += 1
        used.add(str(path).casefold())
        paths.append(path)
    return paths


def download_one(item, path, cover):
    if path.exists():
        return "atlandı", "Dosya zaten var."
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".indir-", suffix=f".{item['format']}", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        request = Request(item["url"], headers={"User-Agent": "MuzikIndiriciWeb/1.0"})
        with urlopen(request, timeout=60) as response, temp_path.open("wb") as target:
            shutil.copyfileobj(response, target, 1024 * 1024)
        tag_file(temp_path, item["format"], item["meta"], cover)
        if path.exists():
            return "atlandı", "Dosya zaten var."
        temp_path.replace(path)
        return "tamamlandı", ""
    finally:
        temp_path.unlink(missing_ok=True)


def process(payload, progress):
    tracks, output_dir, workers, cover_spec = validate(payload)
    cover = image_bytes(cover_spec)
    paths = destinations(tracks, output_dir)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, item, path, cover): (item, path)
                   for item, path in zip(tracks, paths)}
        for future in as_completed(futures):
            item, path = futures[future]
            try:
                status, detail = future.result()
            except Exception as exc:
                status, detail = "hata", str(exc)
            progress({"title": item["meta"]["title"], "status": status,
                      "detail": detail, "path": str(path)})
    return str(output_dir)
