"""Public metadata lookup for Spotify links; no audio is fetched."""

from __future__ import annotations

import json
import re
import threading
import time
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


SPOTIFY_ID = re.compile(r"^[A-Za-z0-9]{22}$")
MUSICBRAINZ_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
MUSICBRAINZ_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "MuzikBilgi/1.0 (personal metadata lookup; https://musicbrainz.org)"
MB_LOCK = threading.Lock()
LAST_MB_REQUEST = 0.0
CACHE: dict[str, tuple[float, dict]] = {}
CACHE_LOCK = threading.Lock()


def parse_spotify_url(raw_url: str) -> tuple[str, str, str]:
    if not isinstance(raw_url, str) or len(raw_url) > 2048:
        raise ValueError("Spotify şarkı veya albüm bağlantısı girin.")
    parsed = urlparse(raw_url.strip())
    if parsed.scheme != "https" or parsed.hostname != "open.spotify.com" or parsed.port:
        raise ValueError("open.spotify.com şarkı veya albüm bağlantısı girin.")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and re.fullmatch(r"intl-[a-z]{2}(?:-[a-z]{2})?", parts[0], re.I):
        parts = parts[1:]
    if len(parts) != 2 or parts[0] not in {"album", "track"} or not SPOTIFY_ID.fullmatch(parts[1]):
        raise ValueError("Bağlantı bir Spotify şarkısına veya albümüne ait olmalı.")
    kind, spotify_id = parts
    return kind, spotify_id, f"https://open.spotify.com/{kind}/{spotify_id}"


def _get_json(url: str, *, musicbrainz: bool = False) -> dict:
    global LAST_MB_REQUEST
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    if musicbrainz:
        with MB_LOCK:
            wait = 1.1 - (time.monotonic() - LAST_MB_REQUEST)
            if wait > 0:
                time.sleep(wait)
            LAST_MB_REQUEST = time.monotonic()
            with urlopen(request, timeout=10) as response:
                return json.load(response)
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def _artist_credit(credit: list | None) -> str | None:
    if not credit:
        return None
    value = "".join(
        item if isinstance(item, str) else item.get("name", "") + item.get("joinphrase", "")
        for item in credit
    ).strip()
    return value or None


def _related(rels: list | None, types: set[str]) -> list[str]:
    names: list[str] = []
    for relation in rels or []:
        if relation.get("type", "").lower() not in types:
            continue
        name = (relation.get("artist") or {}).get("name")
        if name and name not in names:
            names.append(name)
    return names


def _url_relations(url_entry: dict) -> list[dict]:
    relations: list[dict] = []
    for group in url_entry.get("relation-list", []):
        relations.extend(group.get("relations", []))
    relations.extend(url_entry.get("relations", []))
    return relations


def _linked_entity(canonical_url: str, kind: str) -> tuple[str, str] | None:
    query = urlencode({"query": f'url:"{canonical_url}"', "fmt": "json", "limit": "5"})
    data = _get_json(f"{MUSICBRAINZ_BASE}/url/?{query}", musicbrainz=True)
    for entry in data.get("urls", []):
        if entry.get("resource") != canonical_url:
            continue
        for relation in _url_relations(entry):
            for entity_type in (("release", "release-group") if kind == "album" else ("recording",)):
                entity_id = (relation.get(entity_type) or {}).get("id", "")
                if MUSICBRAINZ_ID.fullmatch(entity_id):
                    return entity_type, entity_id
    return None


def _names_from_genres(entity: dict) -> list[str]:
    return [item["name"] for item in entity.get("genres", []) if item.get("name")]


def _release_details(release_id: str, result: dict) -> None:
    includes = "recordings+artist-credits+labels+recording-level-rels+artist-rels+release-groups+isrcs+genres"
    release = _get_json(f"{MUSICBRAINZ_BASE}/release/{release_id}?{urlencode({'inc': includes, 'fmt': 'json'})}", musicbrainz=True)
    result["title"] = release.get("title") or result["title"]
    result["artist"] = _artist_credit(release.get("artist-credit"))
    result["date"] = release.get("date") or (release.get("release-group") or {}).get("first-release-date")
    result["label"] = ", ".join(dict.fromkeys(
        item["label"]["name"] for item in release.get("label-info", [])
        if item.get("label", {}).get("name")
    )) or None
    result["barcode"] = release.get("barcode")
    result["genre"] = _names_from_genres(release) or _names_from_genres(release.get("release-group") or {})
    result["musicbrainz_url"] = f"https://musicbrainz.org/release/{release_id}"
    album_producers = _related(release.get("relations"), {"producer", "co-producer", "executive producer"})
    tracks = []
    for medium in release.get("media", []):
        for item in medium.get("tracks", []):
            recording = item.get("recording") or {}
            producers = _related(recording.get("relations"), {"producer", "co-producer", "executive producer"})
            for producer in producers:
                if producer not in album_producers:
                    album_producers.append(producer)
            tracks.append({
                "disc": medium.get("position"),
                "number": item.get("position"),
                "title": item.get("title") or recording.get("title"),
                "artist": _artist_credit(item.get("artist-credit")) or _artist_credit(recording.get("artist-credit")) or result["artist"],
                "duration_ms": item.get("length") or recording.get("length"),
                "producer": producers,
                "isrc": recording.get("isrcs") or [],
            })
    result["producer"] = album_producers
    result["tracks"] = tracks
    result["duration_ms"] = sum(track["duration_ms"] or 0 for track in tracks) or None


def _recording_details(recording_id: str, result: dict) -> None:
    includes = "artist-credits+artist-rels+isrcs+genres+releases"
    recording = _get_json(f"{MUSICBRAINZ_BASE}/recording/{recording_id}?{urlencode({'inc': includes, 'fmt': 'json'})}", musicbrainz=True)
    result["title"] = recording.get("title") or result["title"]
    result["artist"] = _artist_credit(recording.get("artist-credit"))
    result["producer"] = _related(recording.get("relations"), {"producer", "co-producer", "executive producer"})
    result["genre"] = _names_from_genres(recording)
    result["isrc"] = recording.get("isrcs") or []
    result["duration_ms"] = recording.get("length")
    result["musicbrainz_url"] = f"https://musicbrainz.org/recording/{recording_id}"
    releases = recording.get("releases") or []
    if releases:
        official = next((item for item in releases if item.get("status") == "Official"), releases[0])
        result["album"] = official.get("title")
        result["date"] = official.get("date")


def lookup(raw_url: str) -> dict:
    kind, spotify_id, canonical_url = parse_spotify_url(raw_url)
    with CACHE_LOCK:
        cached = CACHE.get(canonical_url)
        if cached and cached[0] > time.time():
            return cached[1]

    oembed_url = "https://open.spotify.com/oembed?" + urlencode({"url": canonical_url})
    oembed = _get_json(oembed_url)
    if oembed.get("provider_name") != "Spotify":
        raise ValueError("Spotify bu bağlantıyı tanımadı.")
    result = {
        "kind": kind,
        "spotify_id": spotify_id,
        "spotify_url": canonical_url,
        "title": oembed.get("title"),
        "cover_url": oembed.get("thumbnail_url"),
        "artist": None,
        "producer": [],
        "date": None,
        "genre": [],
        "label": None,
        "barcode": None,
        "album": None,
        "isrc": [],
        "duration_ms": None,
        "tracks": [],
        "musicbrainz_url": None,
        "sources": ["Spotify oEmbed"],
        "note": None,
    }
    try:
        linked = _linked_entity(canonical_url, kind)
        if linked:
            entity_type, entity_id = linked
            if entity_type == "release":
                _release_details(entity_id, result)
            elif entity_type == "recording":
                _recording_details(entity_id, result)
            else:
                result["musicbrainz_url"] = f"https://musicbrainz.org/release-group/{entity_id}"
            result["sources"].append("MusicBrainz doğrudan bağlantı eşleşmesi")
        else:
            result["note"] = "MusicBrainz'de bu Spotify bağlantısına bağlı bir kayıt bulunamadı. Sanatçı ve yapımcı bilgileri doğrulanamadı."
    except Exception:
        result["note"] = "MusicBrainz bilgilerine şu anda erişilemedi; Spotify'ın temel bilgileri gösteriliyor."
    with CACHE_LOCK:
        if len(CACHE) > 100:
            CACHE.clear()
        CACHE[canonical_url] = (time.time() + 600, result)
    return result
