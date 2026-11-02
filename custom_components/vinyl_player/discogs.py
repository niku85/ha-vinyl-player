"""Pure helpers for turning Discogs API responses into the Vinyl Player export.

This module deliberately has **no third-party imports** (no Home Assistant,
no aiohttp) so it can be shared between the Home Assistant integration and the
standalone ``scripts/discogs_export.py`` export script.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any
from collections.abc import Iterable

API_BASE = "https://api.discogs.com"
USER_AGENT = "HAVinylPlayer/0.2 +https://github.com/niku85/ha-vinyl-player"
PER_PAGE = 100
EXPORT_VERSION = 1

# Discogs adds " (2)", " (3)" … to disambiguate artists with the same name.
_DISAMBIGUATION = re.compile(r"\s+\(\d+\)$")
_SORT_PREFIX = re.compile(r"^(the|a|an|die|der|das)\s+", re.IGNORECASE)


def auth_headers(token: str) -> dict[str, str]:
    """Return the HTTP headers for an authenticated Discogs request."""
    return {
        "Authorization": f"Discogs token={token}",
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.discogs.v2.discogs+json",
    }


def collection_url(username: str, page: int, per_page: int = PER_PAGE) -> str:
    """URL for one page of the user's whole collection (folder 0 = "All")."""
    return (
        f"{API_BASE}/users/{username}/collection/folders/0/releases"
        f"?page={page}&per_page={per_page}&sort=artist&sort_order=asc"
    )


def release_url(release_id: int) -> str:
    """URL of a single release (used for the tracklist)."""
    return f"{API_BASE}/releases/{release_id}"


def clean_artist(name: str) -> str:
    """Strip the Discogs disambiguation suffix, e.g. ``Nirvana (2)``."""
    return _DISAMBIGUATION.sub("", (name or "").strip())


def join_artists(artists: Iterable[dict[str, Any]]) -> str:
    """Join Discogs artist credits honouring their ``join`` strings."""
    parts: list[str] = []
    artists = list(artists or [])
    for idx, artist in enumerate(artists):
        name = clean_artist(artist.get("anv") or artist.get("name") or "")
        parts.append(name)
        join = (artist.get("join") or "").strip()
        if idx < len(artists) - 1:
            if join in ("", ","):
                parts.append(", " if join == "," else " & ")
            else:
                parts.append(f" {join} ")
    return "".join(parts).strip() or "Unknown Artist"


def sort_key(text: str) -> str:
    """Case-insensitive sort key ignoring leading articles."""
    return _SORT_PREFIX.sub("", (text or "").strip()).casefold()


def is_vinyl(formats: Iterable[dict[str, Any]]) -> bool:
    """True when at least one of the release formats is vinyl."""
    return any((fmt.get("name") or "").casefold() == "vinyl" for fmt in formats or [])


def format_text(formats: Iterable[dict[str, Any]]) -> str:
    """Human readable format string, e.g. ``2×Vinyl, LP, Album``."""
    chunks: list[str] = []
    for fmt in formats or []:
        name = fmt.get("name") or ""
        qty = str(fmt.get("qty") or "1")
        head = f"{qty}×{name}" if qty not in ("", "1") else name
        desc = [d for d in fmt.get("descriptions") or [] if d]
        chunks.append(", ".join([head, *desc]) if desc else head)
    return "; ".join(c for c in chunks if c)


def parse_collection_item(item: dict[str, Any]) -> dict[str, Any]:
    """Convert one ``collection/folders/0/releases`` entry to an export record."""
    info = item.get("basic_information") or {}
    formats = info.get("formats") or []
    labels = info.get("labels") or []
    release_id = int(info.get("id") or item.get("id"))
    year = info.get("year") or None
    return {
        "id": release_id,
        "instance_id": item.get("instance_id"),
        "master_id": info.get("master_id") or None,
        "artist": join_artists(info.get("artists") or []),
        "artists": [clean_artist(a.get("name", "")) for a in info.get("artists") or []],
        "title": (info.get("title") or "").strip() or "Untitled",
        "year": int(year) if year else None,
        "formats": sorted(
            {fmt.get("name") for fmt in formats if fmt.get("name")}
            | {d for fmt in formats for d in fmt.get("descriptions") or []}
        ),
        "format_text": format_text(formats),
        "vinyl": is_vinyl(formats),
        "genres": info.get("genres") or [],
        "styles": info.get("styles") or [],
        "labels": sorted({clean_artist(lbl.get("name", "")) for lbl in labels if lbl.get("name")}),
        "catno": next((lbl.get("catno") for lbl in labels if lbl.get("catno")), None),
        "cover_url": info.get("cover_image") or None,
        "thumb_url": info.get("thumb") or None,
        "cover_file": None,
        "thumb_file": None,
        # Hand-editable fields – kept across re-exports (see merge_user_fields).
        "ma_query": None,
        "tag_id": None,
        "hidden": False,
        "date_added": item.get("date_added"),
        "rating": item.get("rating") or 0,
    }


def build_releases(
    items: Iterable[dict[str, Any]], *, vinyl_only: bool = True
) -> list[dict[str, Any]]:
    """Parse, de-duplicate (by release id) and sort collection items."""
    seen: dict[int, dict[str, Any]] = {}
    for item in items:
        try:
            record = parse_collection_item(item)
        except (TypeError, ValueError):
            continue
        if vinyl_only and not record["vinyl"]:
            continue
        seen.setdefault(record["id"], record)
    return sorted(
        seen.values(),
        key=lambda r: (sort_key(r["artist"]), r["year"] or 9999, sort_key(r["title"])),
    )


# Fields the user may edit by hand in collection.json; a re-export keeps them.
USER_FIELDS = ("ma_query", "tag_id", "hidden")


def merge_user_fields(
    releases: list[dict[str, Any]], previous: Iterable[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """Copy ``ma_query`` / ``tag_id`` / ``hidden`` from a previous export."""
    old = {int(r["id"]): r for r in previous or [] if r.get("id") is not None}
    for release in releases:
        prev = old.get(int(release["id"]))
        if not prev:
            continue
        for field in USER_FIELDS:
            if prev.get(field) not in (None, "", False, []):
                release[field] = prev[field]
    return releases


def tag_ids(release: dict[str, Any]) -> list[str]:
    """``tag_id`` may be a single string or a list (several tags per record)."""
    value = release.get("tag_id")
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    return [str(v).strip() for v in values if str(v).strip()]


def normalize(text: str | None) -> str:
    """Loose title comparison: case/punctuation-insensitive, no (Remastered) etc."""
    text = re.sub(r"\(.*?\)|\[.*?\]", "", (text or "").casefold())
    text = text.split(" - ")[0]
    return re.sub(r"[\W_]+", "", text)


def album_matches(release: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Does a Music Assistant search result look like this record?"""
    want, got = normalize(release.get("title")), normalize(candidate.get("name"))
    if not want or not got or not (want == got or got.startswith(want) or want.startswith(got)):
        return False
    artists = [normalize(a.get("name")) for a in candidate.get("artists") or []]
    if not artists:
        return True
    wanted = [normalize(a) for a in release.get("artists") or [release.get("artist")]]
    return any(w and (w in a or a in w) for w in wanted for a in artists)


def build_export(username: str, releases: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap the releases in the versioned export document."""
    return {
        "version": EXPORT_VERSION,
        "source": "discogs",
        "username": username,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(releases),
        "releases": releases,
    }


def cover_filename(release_id: int, url: str | None) -> str:
    """File name used for a cached cover."""
    ext = ".jpg"
    if url:
        match = re.search(r"\.(jpe?g|png|webp|gif)(?:$|[?#])", url, re.IGNORECASE)
        if match:
            ext = "." + match.group(1).lower().replace("jpeg", "jpg")
    return f"{release_id}{ext}"


def _duration_seconds(text: str | None) -> int | None:
    """``"4:20"`` → 260, ``"1:02:03"`` → 3723."""
    if not text:
        return None
    try:
        total = 0
        for part in text.strip().split(":"):
            total = total * 60 + int(part)
    except ValueError:
        return None
    return total or None


def parse_tracklist(release: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a Discogs release tracklist (headings dropped, index tracks expanded)."""
    tracks: list[dict[str, Any]] = []

    def add(track: dict[str, Any]) -> None:
        title = (track.get("title") or "").strip()
        if not title:
            return
        tracks.append(
            {
                "position": (track.get("position") or "").strip(),
                "title": title,
                "duration": _duration_seconds(track.get("duration")),
            }
        )

    for track in release.get("tracklist") or []:
        kind = track.get("type_", "track")
        if kind == "heading":
            continue
        if kind == "index" and track.get("sub_tracks"):
            for sub in track["sub_tracks"]:
                add(sub)
            continue
        add(track)
    return tracks


def side_of(position: str) -> str | None:
    """Vinyl side from a Discogs position (``"B3"`` → ``"B"``)."""
    match = re.match(r"^([A-Za-z])", position or "")
    return match.group(1).upper() if match else None
