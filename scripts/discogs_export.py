#!/usr/bin/env python3
"""Export your Discogs collection for the HA Vinyl Player.

Writes ``collection.json`` plus a ``covers/`` folder with every cover image.
Point ``--output`` at ``<HA config>/vinyl_player`` and the integration uses it
directly (Settings → Collection, or call ``vinyl_player.sync`` to refresh from
Discogs inside HA instead).

Only the Python standard library is needed:

    python3 scripts/discogs_export.py YOUR_NAME YOUR_TOKEN -o /config/vinyl_player
    python3 scripts/discogs_export.py --username YOUR_NAME --token YOUR_TOKEN
    DISCOGS_TOKEN=... python3 scripts/discogs_export.py -u YOUR_NAME -o /config/vinyl_player

Create the personal access token at https://www.discogs.com/settings/developers
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request

_HERE = Path(__file__).resolve().parent
_MODULE = _HERE.parent / "custom_components" / "vinyl_player" / "discogs.py"

# Load the shared, dependency-free helpers without importing Home Assistant.
_spec = importlib.util.spec_from_file_location("vinyl_discogs", _MODULE)
discogs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(discogs)  # type: ignore[union-attr]

_MIN_INTERVAL = 1.05  # Discogs: 60 authenticated requests / minute
_last_call = 0.0


def _get(url: str, headers: dict[str, str], *, binary: bool = False, retries: int = 4):
    global _last_call
    for attempt in range(retries):
        if not binary:
            wait = _last_call + _MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            _last_call = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as resp:
                payload = resp.read()
                return payload if binary else json.loads(payload)
        except urllib.error.HTTPError as err:
            if err.code in (401, 403):
                sys.exit(f"Discogs rejected the token (HTTP {err.code}). Check --token.")
            if err.code == 404 and not binary:
                sys.exit("Discogs user not found. Check --username.")
            if err.code == 429 or err.code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Giving up on {url}")


def fetch_items(username: str, token: str) -> list[dict]:
    headers = discogs.auth_headers(token)
    items: list[dict] = []
    page, pages = 1, 1
    while page <= pages:
        data = _get(discogs.collection_url(username, page), headers)
        pages = int((data.get("pagination") or {}).get("pages") or 1)
        items.extend(data.get("releases") or [])
        print(f"  page {page}/{pages} – {len(items)} items", file=sys.stderr)
        page += 1
    return items


def download_covers(releases: list[dict], covers_dir: Path) -> int:
    """Cache full covers (centre cover + record label) and thumbnails (side covers)."""
    (covers_dir / "thumbs").mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": discogs.USER_AGENT}

    def fetch(url: str | None, target: Path) -> tuple[bool, int]:
        if not url or url.endswith("spacer.gif"):
            return False, 0
        if target.exists():
            return True, 0
        try:
            payload = _get(url, headers, binary=True, retries=2)
        except Exception as err:  # noqa: BLE001 - keep going on single failures
            print(f"  {target.name}: {err}", file=sys.stderr)
            return False, 0
        tmp = target.with_suffix(target.suffix + ".part")
        tmp.write_bytes(payload)
        tmp.replace(target)
        return True, 1

    def one(release: dict) -> int:
        name = discogs.cover_filename(release["id"], release.get("cover_url"))
        ok, new = fetch(release.get("cover_url"), covers_dir / name)
        release["cover_file"] = f"covers/{name}" if ok else None
        tname = discogs.cover_filename(release["id"], release.get("thumb_url"))
        ok, tnew = fetch(release.get("thumb_url"), covers_dir / "thumbs" / tname)
        release["thumb_file"] = f"covers/thumbs/{tname}" if ok else None
        return new + tnew

    with ThreadPoolExecutor(max_workers=4) as pool:
        return sum(pool.map(one, releases))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("user", nargs="?", help="Discogs username (same as --username)")
    parser.add_argument("key", nargs="?", help="Personal access token (same as --token)")
    parser.add_argument("-u", "--username", help="Discogs username")
    parser.add_argument("-t", "--token", default=os.environ.get("DISCOGS_TOKEN"),
                        help="Personal access token (or set DISCOGS_TOKEN)")
    parser.add_argument("-o", "--output", default="vinyl_player", help="Output folder (default: ./vinyl_player)")
    parser.add_argument("--all-formats", action="store_true", help="Include CDs, cassettes, files …")
    parser.add_argument("--no-covers", action="store_true", help="Skip downloading cover images")
    args = parser.parse_args()
    args.username = args.username or args.user
    args.token = args.key or args.token
    if not args.username:
        parser.error("a Discogs username is required")
    if not args.token:
        parser.error("--token or DISCOGS_TOKEN is required")

    out = Path(args.output).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    print(f"Fetching the collection of {args.username} …", file=sys.stderr)
    items = fetch_items(args.username, args.token)
    releases = discogs.build_releases(items, vinyl_only=not args.all_formats)
    print(f"{len(releases)} records ({len(items)} collection items)", file=sys.stderr)

    if not args.no_covers:
        print("Downloading covers …", file=sys.stderr)
        new = download_covers(releases, out / "covers")
        print(f"  {new} new covers", file=sys.stderr)

    target = out / "collection.json"
    if target.exists():
        # Keep the hand-edited fields (ma_query, tag_id, hidden) of the last export.
        try:
            previous = json.loads(target.read_text(encoding="utf-8")).get("releases")
        except ValueError:
            previous = None
        discogs.merge_user_fields(releases, previous)

    export = discogs.build_export(args.username, releases)
    export["vinyl_only"] = not args.all_formats
    tmp = target.with_suffix(".json.part")
    tmp.write_text(json.dumps(export, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(target)
    print(f"Wrote {target}", file=sys.stderr)


if __name__ == "__main__":
    main()
