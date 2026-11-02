"""Async Discogs client used by the integration (aiohttp based)."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import aiohttp

from . import discogs

_LOGGER = logging.getLogger(__name__)

# Discogs allows 60 authenticated requests per minute.
_MIN_INTERVAL = 1.05
_TIMEOUT = aiohttp.ClientTimeout(total=30)


class DiscogsError(Exception):
    """Generic Discogs failure."""


class DiscogsAuthError(DiscogsError):
    """Invalid token or username."""


class DiscogsClient:
    """Small, rate-limited Discogs API client."""

    def __init__(self, session: aiohttp.ClientSession, username: str, token: str) -> None:
        self._session = session
        self.username = username.strip()
        self._token = token.strip()
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def _get_json(self, url: str) -> dict[str, Any]:
        for attempt in range(4):
            async with self._lock:
                loop = asyncio.get_running_loop()
                wait = self._last_call + _MIN_INTERVAL - loop.time()
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_call = loop.time()
            try:
                async with self._session.get(
                    url, headers=discogs.auth_headers(self._token), timeout=_TIMEOUT
                ) as resp:
                    if resp.status in (401, 403):
                        raise DiscogsAuthError(f"Discogs rejected the token ({resp.status})")
                    if resp.status == 404:
                        raise DiscogsAuthError("Discogs user or resource not found")
                    if resp.status == 429:
                        await asyncio.sleep(10 * (attempt + 1))
                        continue
                    if resp.status >= 400:
                        raise DiscogsError(f"Discogs returned HTTP {resp.status}")
                    return await resp.json()
            except (TimeoutError, aiohttp.ClientError) as err:
                if attempt == 3:
                    raise DiscogsError(f"Cannot reach Discogs: {err}") from err
                await asyncio.sleep(2 * (attempt + 1))
        raise DiscogsError("Discogs rate limit exceeded")

    async def identity(self) -> str:
        """Return the username the token belongs to (validates the token)."""
        data = await self._get_json(f"{discogs.API_BASE}/oauth/identity")
        return data.get("username", "")

    async def fetch_collection_items(self) -> list[dict[str, Any]]:
        """Fetch every item of the user's collection (all pages)."""
        items: list[dict[str, Any]] = []
        page, pages = 1, 1
        while page <= pages:
            data = await self._get_json(discogs.collection_url(self.username, page))
            pages = int((data.get("pagination") or {}).get("pages") or 1)
            items.extend(data.get("releases") or [])
            page += 1
        return items

    async def fetch_tracklist(self, release_id: int) -> list[dict[str, Any]]:
        """Fetch and flatten the tracklist of a release."""
        data = await self._get_json(discogs.release_url(release_id))
        return discogs.parse_tracklist(data)

    async def download_covers(
        self, releases: list[dict[str, Any]], covers_dir: Path, rel_prefix: str
    ) -> int:
        """Download missing covers; sets ``cover_file`` on each release. Returns #new."""
        semaphore = asyncio.Semaphore(4)
        downloaded = 0

        async def fetch(release: dict[str, Any]) -> None:
            nonlocal downloaded
            url = release.get("cover_url")
            if not url or url.endswith("spacer.gif"):
                return
            name = discogs.cover_filename(release["id"], url)
            target = covers_dir / name
            if await asyncio.to_thread(target.exists):
                release["cover_file"] = f"{rel_prefix}/{name}"
                return
            async with semaphore:
                try:
                    async with self._session.get(
                        url, headers={"User-Agent": discogs.USER_AGENT}, timeout=_TIMEOUT
                    ) as resp:
                        if resp.status != 200:
                            _LOGGER.debug("Cover %s: HTTP %s", url, resp.status)
                            return
                        payload = await resp.read()
                except (TimeoutError, aiohttp.ClientError) as err:
                    _LOGGER.debug("Cover %s failed: %s", url, err)
                    return
                await asyncio.to_thread(_write_atomic, target, payload)
                release["cover_file"] = f"{rel_prefix}/{name}"
                downloaded += 1
                await asyncio.sleep(0.2)

        await asyncio.to_thread(covers_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.gather(*(fetch(r) for r in releases))
        return downloaded


def _write_atomic(target: Path, payload: bytes) -> None:
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(payload)
    tmp.replace(target)
