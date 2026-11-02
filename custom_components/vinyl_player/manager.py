"""Core logic: collection, playback session, NFC tags, run-out detection."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import json
import logging
from pathlib import Path
import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import STATE_PAUSED, STATE_PLAYING
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import discogs
from .api import DiscogsClient, DiscogsError
from .const import (
    COLLECTION_FILE,
    CONF_PLAYER,
    CONF_RUNOUT_MODE,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_VINYL_ONLY,
    COVERS_DIR,
    COVERS_URL,
    DATA_DIR,
    DEFAULT_RUNOUT_MODE,
    DEFAULT_SYNC_INTERVAL,
    DEFAULT_VINYL_ONLY,
    DOMAIN,
    EVENT_ALBUM_FINISHED,
    EVENT_ALBUM_STARTED,
    EVENT_TAG_LEARNED,
    EVENT_UNKNOWN_TAG,
    MUSIC_ASSISTANT_DOMAIN,
    PHASE_IDLE,
    PHASE_PLAYING,
    PHASE_RUNOUT,
    RUNOUT_BROWSER,
    RUNOUT_SOUND_FILE,
    RUNOUT_SPEAKER,
    SIGNAL_COLLECTION,
    SIGNAL_STATE,
    STATIC_URL,
    STORAGE_KEY,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

# Ignore the player going idle right after we started an album (queue swap).
_START_GRACE = timedelta(seconds=15)
# How long the player has to stay stopped before we decide.
_STOP_DEBOUNCE = 4.0
# If less than this many seconds were left on the track, the album "ran out".
_END_TOLERANCE = 25.0
# Safety net: always return to idle after the run-out phase.
_RUNOUT_MAX = 30.0
_LEARN_TIMEOUT = timedelta(seconds=90)


def _norm(text: str | None) -> str:
    text = (text or "").casefold()
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text)
    return re.sub(r"[\W_]+", "", text)


class VinylManager:
    """Everything the panel, services, sensors and NFC handling talk to."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.data_dir = Path(hass.config.path(DATA_DIR))
        self.covers_dir = self.data_dir / COVERS_DIR
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._all: list[dict[str, Any]] = []  # everything in collection.json
        self.releases: list[dict[str, Any]] = []  # what the cover flow shows
        self._by_id: dict[int, dict[str, Any]] = {}
        self.export_meta: dict[str, Any] = {}
        self.tags: dict[str, dict[str, Any]] = {}  # derived from each record's tag_id
        self.match_report: dict[str, Any] = {}
        self._file_lock = asyncio.Lock()
        self._match_task: asyncio.Task | None = None
        self.tracklists: dict[str, list[dict[str, Any]]] = {}
        self.syncing = False
        self.sync_error: str | None = None
        self.session: dict[str, Any] = {"phase": PHASE_IDLE}
        self._learn: dict[str, Any] | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._player_unsub: CALLBACK_TYPE | None = None
        self._pending_check: CALLBACK_TYPE | None = None
        self._runout_timer: CALLBACK_TYPE | None = None
        self._last_playing: dict[str, Any] | None = None
        self._seen_playing = False
        self._stop_requested = False
        self._sync_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ setup
    @property
    def options(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def player(self) -> str:
        return self.options[CONF_PLAYER]

    @property
    def runout_mode(self) -> str:
        return self.options.get(CONF_RUNOUT_MODE, DEFAULT_RUNOUT_MODE)

    def client(self) -> DiscogsClient:
        return DiscogsClient(
            async_get_clientsession(self.hass),
            self.entry.data[CONF_USERNAME],
            self.entry.data[CONF_TOKEN],
        )

    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self.tracklists = stored.get("tracklists", {})
        self.match_report = stored.get("match_report", {})
        self.match_report.pop("running", None)
        await self.async_load_export()

        self._unsubs.append(self.hass.bus.async_listen("tag_scanned", self._on_tag_scanned))
        self._track_player()

        hours = float(self.options.get(CONF_SYNC_INTERVAL, DEFAULT_SYNC_INTERVAL))
        if hours > 0:
            self._unsubs.append(
                async_track_time_interval(
                    self.hass, self._scheduled_sync, timedelta(hours=hours)
                )
            )
        wants_all = not self.options.get(CONF_VINYL_ONLY, DEFAULT_VINYL_ONLY)
        if not self.releases or (wants_all and self.export_meta.get("vinyl_only")):
            self.start_sync()

    async def async_unload(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._player_unsub:
            self._player_unsub()
        self._cancel_timers()
        for task in (self._sync_task, self._match_task):
            if task and not task.done():
                task.cancel()

    def _cancel_timers(self) -> None:
        for attr in ("_pending_check", "_runout_timer"):
            if (cancel := getattr(self, attr)) is not None:
                cancel()
                setattr(self, attr, None)

    def _track_player(self) -> None:
        if self._player_unsub:
            self._player_unsub()
        self._player_unsub = async_track_state_change_event(
            self.hass, [self.player], self._on_player_state
        )

    @callback
    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {"tracklists": self.tracklists, "match_report": self.match_report},
            2,
        )

    # ------------------------------------------------------------- collection
    async def async_load_export(self) -> None:
        """(Re)load collection.json – written by sync or the export script."""
        path = self.data_dir / COLLECTION_FILE

        def _read() -> dict[str, Any] | None:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))

        try:
            data = await self.hass.async_add_executor_job(_read)
        except (OSError, ValueError) as err:
            _LOGGER.error("Cannot read %s: %s", path, err)
            return
        if not data:
            return
        self._all = data.get("releases") or []
        self.export_meta = {k: v for k, v in data.items() if k != "releases"}
        self._reindex()
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)

    @callback
    def _reindex(self) -> None:
        """Rebuild the shelf, the id index and the tag map from ``self._all``."""
        playable = self._all
        if self.options.get(CONF_VINYL_ONLY, DEFAULT_VINYL_ONLY):
            playable = [r for r in playable if r.get("vinyl", True)]
        # hidden records stay playable (e.g. via NFC) but are not on the shelf
        self._by_id = {int(r["id"]): r for r in playable}
        self.releases = [r for r in playable if not r.get("hidden")]
        tags: dict[str, dict[str, Any]] = {}
        for release in playable:
            for tag in discogs.tag_ids(release):
                tags[tag] = {
                    "release_id": release["id"],
                    "name": f"{release['artist']} – {release['title']}",
                }
        self.tags = tags

    async def _async_write_export(self) -> None:
        """Persist ``self._all`` (incl. hand-edited fields) to collection.json."""
        export = {**self.export_meta, "count": len(self._all), "releases": self._all}
        path = self.data_dir / COLLECTION_FILE

        def _write() -> None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.part")
            tmp.write_text(json.dumps(export, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(path)

        async with self._file_lock:
            await self.hass.async_add_executor_job(_write)

    @callback
    def _scheduled_sync(self, _now: datetime) -> None:
        self.start_sync()

    @callback
    def start_sync(self) -> asyncio.Task | None:
        if self.syncing:
            return self._sync_task
        self._sync_task = self.entry.async_create_background_task(
            self.hass, self.async_sync(), f"{DOMAIN}_sync"
        )
        return self._sync_task

    async def async_sync(self) -> None:
        """Export the Discogs collection to collection.json and cache covers."""
        if self.syncing:
            return
        self.syncing = True
        self.sync_error = None
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)
        try:
            client = self.client()
            items = await client.fetch_collection_items()
            releases = discogs.build_releases(
                items, vinyl_only=self.options.get(CONF_VINYL_ONLY, DEFAULT_VINYL_ONLY)
            )
            new = await client.download_covers(releases, self.covers_dir, COVERS_DIR)
            # Keep ma_query / tag_id / hidden from the previous export.
            discogs.merge_user_fields(releases, self._all)
            export = discogs.build_export(client.username, releases)
            export["vinyl_only"] = self.options.get(CONF_VINYL_ONLY, DEFAULT_VINYL_ONLY)
            self.export_meta = {k: v for k, v in export.items() if k != "releases"}
            self._all = releases
            await self._async_write_export()
            _LOGGER.info("Synced %s records from Discogs (%s new covers)", len(releases), new)
        except DiscogsError as err:
            self.sync_error = str(err)
            _LOGGER.error("Discogs sync failed: %s", err)
        finally:
            self.syncing = False
        await self.async_load_export()

    def release(self, release_id: int | str) -> dict[str, Any]:
        try:
            return self._by_id[int(release_id)]
        except (KeyError, ValueError, TypeError) as err:
            raise ServiceValidationError(f"Record {release_id} is not in the collection") from err

    @staticmethod
    def _local_url(rel: str | None) -> str | None:
        if not rel:
            return None
        rel = rel.replace("\\", "/")
        rel = rel[len(COVERS_DIR) + 1 :] if rel.startswith(f"{COVERS_DIR}/") else Path(rel).name
        return f"{COVERS_URL}/{rel}"

    @classmethod
    def cover_url(cls, release: dict[str, Any]) -> str | None:
        return (
            cls._local_url(release.get("cover_file"))
            or release.get("cover_url")
            or release.get("thumb_url")
        )

    @classmethod
    def thumb_url(cls, release: dict[str, Any]) -> str | None:
        return (
            cls._local_url(release.get("thumb_file"))
            or cls._local_url(release.get("cover_file"))
            or release.get("thumb_url")
            or release.get("cover_url")
        )

    @property
    def overrides(self) -> dict[str, str]:
        return {str(r["id"]): r["ma_query"] for r in self._all if r.get("ma_query")}

    def public_release(self, release: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": release["id"],
            "artist": release.get("artist"),
            "title": release.get("title"),
            "year": release.get("year"),
            "format": release.get("format_text"),
            "genres": release.get("genres") or [],
            "styles": release.get("styles") or [],
            "label": ", ".join(release.get("labels") or []),
            "cover": self.cover_url(release),
            "thumb": self.thumb_url(release),
            "added": release.get("date_added"),
            "override": release.get("ma_query"),
            "tags": discogs.tag_ids(release),
        }

    async def async_tracklist(self, release_id: int) -> list[dict[str, Any]]:
        key = str(release_id)
        if key not in self.tracklists:
            try:
                self.tracklists[key] = await self.client().fetch_tracklist(int(release_id))
            except DiscogsError as err:
                _LOGGER.warning("Tracklist for %s unavailable: %s", release_id, err)
                return []
            self._save()
        return self.tracklists[key]

    # ---------------------------------------------------------------- playback
    def state_payload(self) -> dict[str, Any]:
        payload = dict(self.session)
        payload["learning"] = (
            {"release_id": self._learn["release_id"]} if self._learn else None
        )
        return payload

    @callback
    def _set_session(self, **values: Any) -> None:
        self.session = values
        async_dispatcher_send(self.hass, SIGNAL_STATE)

    async def async_play(self, release_id: int | str, source: str = "panel") -> dict[str, Any]:
        release = self.release(release_id)
        if MUSIC_ASSISTANT_DOMAIN not in self.hass.config.components:
            raise HomeAssistantError("Music Assistant is not set up")

        self._cancel_timers()
        self._stop_requested = False
        self._seen_playing = False
        self._last_playing = None
        player = self.player
        override = (release.get("ma_query") or "").strip()

        # Vinyl rules: no shuffle, no repeat.
        for service, data in (
            ("shuffle_set", {"shuffle": False}),
            ("repeat_set", {"repeat": "off"}),
        ):
            try:
                await self.hass.services.async_call(
                    "media_player", service, {"entity_id": player, **data}, blocking=True
                )
            except (HomeAssistantError, ValueError) as err:
                _LOGGER.debug("%s not supported by %s: %s", service, player, err)

        service_data: dict[str, Any] = {
            "entity_id": player,
            "media_type": "album",
            "enqueue": "replace",
        }
        if override:
            service_data["media_id"] = override
        else:
            service_data["media_id"] = release["title"]
            service_data["artist"] = release["artist"]

        self._set_session(
            phase=PHASE_PLAYING,
            release_id=release["id"],
            artist=release["artist"],
            title=release["title"],
            cover=self.cover_url(release),
            source=source,
            started_at=dt_util.utcnow().isoformat(),
        )
        try:
            await self.hass.services.async_call(
                MUSIC_ASSISTANT_DOMAIN, "play_media", service_data, blocking=True
            )
        except Exception:
            self._set_session(phase=PHASE_IDLE)
            raise
        self.hass.bus.async_fire(
            EVENT_ALBUM_STARTED,
            {"release_id": release["id"], "artist": release["artist"],
             "title": release["title"], "source": source},
        )
        # Pre-fetch the tracklist so the tonearm can follow the album.
        self.entry.async_create_background_task(
            self.hass, self.async_tracklist(release["id"]), f"{DOMAIN}_tracklist"
        )
        return self.public_release(release)

    async def async_stop(self) -> None:
        self._stop_requested = True
        self._cancel_timers()
        if self.session.get("phase") != PHASE_IDLE:
            self._set_session(phase=PHASE_IDLE)
        await self.hass.services.async_call(
            "media_player", "media_stop", {"entity_id": self.player}, blocking=True
        )

    async def async_set_volume(self, volume: float) -> None:
        await self.hass.services.async_call(
            "media_player",
            "volume_set",
            {"entity_id": self.player, "volume_level": max(0.0, min(1.0, volume))},
            blocking=True,
        )

    # ------------------------------------------------------ run-out detection
    @callback
    def _on_player_state(self, event: Event) -> None:
        new = event.data.get("new_state")
        if new is None:
            return
        phase = self.session.get("phase")

        if phase == PHASE_RUNOUT:
            if new.state == STATE_PLAYING:
                self._seen_playing = True
            elif self._seen_playing and self.runout_mode == RUNOUT_SPEAKER:
                self._finish_runout()
            return

        if phase != PHASE_PLAYING:
            return

        started = dt_util.parse_datetime(self.session.get("started_at", "")) or dt_util.utcnow()
        if new.state == STATE_PLAYING:
            if dt_util.utcnow() - started > timedelta(seconds=1):
                self._seen_playing = True
            self._last_playing = {
                "position": new.attributes.get("media_position"),
                "updated": new.attributes.get("media_position_updated_at"),
                "duration": new.attributes.get("media_duration"),
                "title": new.attributes.get("media_title"),
                "album": new.attributes.get("media_album_name"),
            }
            if self._pending_check:
                self._pending_check()
                self._pending_check = None
            return

        if new.state == STATE_PAUSED or self._stop_requested:
            return
        if not self._seen_playing or dt_util.utcnow() - started < _START_GRACE:
            return
        left_at = dt_util.utcnow()
        if self._pending_check:
            self._pending_check()

        @callback
        def _check(_now: datetime) -> None:
            self._decide_stop(left_at)

        self._pending_check = async_call_later(self.hass, _STOP_DEBOUNCE, _check)

    @callback
    def _decide_stop(self, left_at: datetime) -> None:
        self._pending_check = None
        state = self.hass.states.get(self.player)
        if state is None or state.state in (STATE_PLAYING, STATE_PAUSED):
            return
        if self.session.get("phase") != PHASE_PLAYING:
            return
        if self._album_ran_out(left_at):
            self._start_runout()
        else:
            _LOGGER.debug("Playback stopped elsewhere – quietly ending the session")
            self._set_session(phase=PHASE_IDLE)

    def _album_ran_out(self, left_at: datetime) -> bool:
        last = self._last_playing
        if not last:
            return False
        position, duration, updated = last["position"], last["duration"], last["updated"]
        if isinstance(updated, str):
            updated = dt_util.parse_datetime(updated)
        if position is None or not duration:
            return True  # can't tell – assume it ran out (it stopped by itself)
        if isinstance(updated, datetime):
            position += max(0.0, (left_at - updated).total_seconds())
        if duration - position > _END_TOLERANCE:
            return False
        tracks = self.tracklists.get(str(self.session.get("release_id")))
        if tracks and last.get("title"):
            titles = [_norm(t["title"]) for t in tracks]
            current = _norm(last["title"])
            if current in titles and titles.index(current) < len(titles) - 1:
                # Ended mid-album (e.g. streaming version differs) – still a stop,
                # but only call it a run-out when we're on the final track.
                return False
        return True

    @callback
    def _start_runout(self) -> None:
        finished = dict(self.session)
        self.hass.bus.async_fire(
            EVENT_ALBUM_FINISHED,
            {k: finished.get(k) for k in ("release_id", "artist", "title", "source")},
        )
        mode = self.runout_mode
        if mode not in (RUNOUT_SPEAKER, RUNOUT_BROWSER):
            self._set_session(phase=PHASE_IDLE, last_release_id=finished.get("release_id"))
            return
        self._seen_playing = False
        self._set_session(**{**finished, "phase": PHASE_RUNOUT, "runout_mode": mode})

        @callback
        def _timeout(_now: datetime) -> None:
            self._finish_runout()

        self._runout_timer = async_call_later(
            self.hass, _RUNOUT_MAX if mode == RUNOUT_SPEAKER else 12, _timeout
        )
        if mode == RUNOUT_SPEAKER:
            self.entry.async_create_background_task(
                self.hass, self._play_runout_on_speaker(), f"{DOMAIN}_runout"
            )

    async def _play_runout_on_speaker(self) -> None:
        try:
            base = get_url(self.hass, prefer_external=False, allow_cloud=False)
        except NoURLAvailableError:
            _LOGGER.warning("No internal URL configured – cannot play the run-out sound")
            self._finish_runout()
            return
        try:
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self.player,
                    "media_content_id": f"{base}{STATIC_URL}/{RUNOUT_SOUND_FILE}",
                    "media_content_type": "music",
                },
                blocking=True,
            )
        except HomeAssistantError as err:
            _LOGGER.warning("Run-out sound failed: %s", err)
            self._finish_runout()

    @callback
    def _finish_runout(self) -> None:
        if self._runout_timer:
            self._runout_timer()
            self._runout_timer = None
        if self.session.get("phase") == PHASE_RUNOUT:
            self._set_session(phase=PHASE_IDLE, last_release_id=self.session.get("release_id"))

    # --------------------------------------------------------------- NFC tags
    async def _on_tag_scanned(self, event: Event) -> None:
        tag_id = event.data.get("tag_id")
        if tag_id:
            await self.async_handle_tag(str(tag_id), source="nfc")

    async def async_handle_tag(self, tag_id: str, source: str = "nfc") -> dict[str, Any] | None:
        tag_id = tag_id.strip()
        if self._learn and dt_util.utcnow() < self._learn["expires"]:
            release_id = self._learn["release_id"]
            self._learn = None
            await self.async_set_tag(tag_id, release_id)
            self.hass.bus.async_fire(EVENT_TAG_LEARNED, {"tag_id": tag_id, "release_id": release_id})
            async_dispatcher_send(self.hass, SIGNAL_STATE)
            return {"learned": True, "tag_id": tag_id, "release_id": release_id}
        self._learn = None

        mapping = self.tags.get(tag_id)
        if not mapping:
            self.hass.bus.async_fire(EVENT_UNKNOWN_TAG, {"tag_id": tag_id})
            return None
        if mapping.get("release_id") is None:
            return None
        return await self.async_play(mapping["release_id"], source=source)

    @callback
    def async_start_learning(self, release_id: int) -> None:
        self.release(release_id)
        self._learn = {"release_id": int(release_id), "expires": dt_util.utcnow() + _LEARN_TIMEOUT}
        async_dispatcher_send(self.hass, SIGNAL_STATE)

    @callback
    def async_cancel_learning(self) -> None:
        self._learn = None
        async_dispatcher_send(self.hass, SIGNAL_STATE)

    async def async_set_tag(
        self, tag_id: str, release_id: int | None, name: str | None = None
    ) -> None:
        """Link (or with ``release_id=None`` unlink) a tag; stored as ``tag_id``."""
        tag_id = tag_id.strip()
        if not tag_id:
            raise ServiceValidationError("Tag id must not be empty")
        target = self.release(release_id) if release_id is not None else None
        for release in self._all:
            tags = [t for t in discogs.tag_ids(release) if t != tag_id]
            if target is not None and release["id"] == target["id"]:
                tags.append(tag_id)
            release["tag_id"] = (tags[0] if len(tags) == 1 else tags) or None
        self._reindex()
        await self._async_write_export()
        async_dispatcher_send(self.hass, SIGNAL_STATE)

    async def async_set_override(self, release_id: int, media_id: str | None) -> None:
        """Set the Music Assistant search text / URI (``ma_query``) of a record."""
        release = self.release(release_id)
        release["ma_query"] = media_id.strip() if media_id and media_id.strip() else None
        if self.match_report.get("misses"):
            self.match_report["misses"] = [
                m for m in self.match_report["misses"] if m["id"] != release["id"]
            ]
        await self._async_write_export()
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)

    async def async_set_hidden(self, release_id: int, hidden: bool) -> None:
        release = self.release(release_id)
        release["hidden"] = bool(hidden)
        self._reindex()
        await self._async_write_export()
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)

    # ------------------------------------------------- Music Assistant matching
    @callback
    def start_match_check(self) -> asyncio.Task | None:
        if self._match_task and not self._match_task.done():
            return self._match_task
        self._match_task = self.entry.async_create_background_task(
            self.hass, self.async_check_matches(), f"{DOMAIN}_match_check"
        )
        return self._match_task

    def _music_assistant_entry_id(self) -> str:
        for entry in self.hass.config_entries.async_entries(MUSIC_ASSISTANT_DOMAIN):
            if entry.state is ConfigEntryState.LOADED:
                return entry.entry_id
        raise HomeAssistantError("Music Assistant is not loaded")

    async def async_check_matches(self) -> dict[str, Any]:
        """Search every record in Music Assistant and list the ones it can't find."""
        ma_entry_id = self._music_assistant_entry_id()
        records = list(self.releases)
        report: dict[str, Any] = {"running": True, "checked": 0, "total": len(records), "misses": []}
        self.match_report = report
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)
        last_push = 0.0
        for release in records:
            query = (release.get("ma_query") or "").strip()
            if "://" in query:  # an exact URI – nothing to search
                report["checked"] += 1
                continue
            data: dict[str, Any] = {
                "config_entry_id": ma_entry_id,
                "name": query or release["title"],
                "media_type": ["album"],
                "limit": 5,
            }
            if not query:
                data["artist"] = release["artist"]
            try:
                result = await self.hass.services.async_call(
                    MUSIC_ASSISTANT_DOMAIN, "search", data, blocking=True, return_response=True
                )
                albums = (result or {}).get("albums") or []
            except HomeAssistantError as err:
                _LOGGER.debug("Search for %s failed: %s", release["title"], err)
                albums = []
            probe = {**release, "title": query or release["title"]} if query else release
            if not any(discogs.album_matches(probe, album) for album in albums):
                best = albums[0] if albums else None
                report["misses"].append(
                    {
                        "id": release["id"],
                        "artist": release["artist"],
                        "title": release["title"],
                        "query": query or f"{release['artist']} - {release['title']}",
                        "best": (
                            {
                                "name": best.get("name"),
                                "artist": ", ".join(a.get("name", "") for a in best.get("artists") or []),
                                "uri": best.get("uri"),
                            }
                            if best
                            else None
                        ),
                    }
                )
            report["checked"] += 1
            loop_time = asyncio.get_running_loop().time()
            if loop_time - last_push > 1:
                last_push = loop_time
                async_dispatcher_send(self.hass, SIGNAL_COLLECTION)
            await asyncio.sleep(0.25)
        report["running"] = False
        report["finished_at"] = dt_util.utcnow().isoformat()
        self._save()
        async_dispatcher_send(self.hass, SIGNAL_COLLECTION)
        return report
