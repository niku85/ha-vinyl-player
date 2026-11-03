"""End-to-end tests of the integration with a fake Music Assistant player."""

from __future__ import annotations

from datetime import timedelta
import json
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.vinyl_player.const import (
    CONF_PLAYER,
    CONF_RUNOUT_MODE,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_VINYL_ONLY,
    CONF_WEBHOOK_ID,
    DOMAIN,
    EVENT_ALBUM_FINISHED,
)

PLAYER = "media_player.living_room"
TRACKS = [
    {"position": "A1", "title": "Come Together", "duration": 260},
    {"position": "B6", "title": "Her Majesty", "duration": 23},
]
COLLECTION = {
    "version": 1,
    "username": "tester",
    "generated_at": "2026-11-01T00:00:00+00:00",
    "vinyl_only": True,
    "releases": [
        {"id": 1, "artist": "The Beatles", "title": "Abbey Road", "year": 1969, "vinyl": True,
         "cover_file": "covers/1.jpg"},
        {"id": 2, "artist": "Air", "title": "Moon Safari", "year": 1998, "vinyl": True},
        {"id": 3, "artist": "Hidden", "title": "Secret LP", "vinyl": True, "hidden": True,
         "tag_id": "secret-tag", "ma_query": "Hidden - Secret LP (Remastered)"},
    ],
}


@pytest.fixture
async def setup(hass: HomeAssistant, tmp_path):
    """Load the integration with a fake Music Assistant."""
    data_dir = hass.config.path("vinyl_player")
    import os

    os.makedirs(data_dir, exist_ok=True)
    with open(os.path.join(data_dir, "collection.json"), "w", encoding="utf-8") as fh:
        json.dump(COLLECTION, fh)

    calls: list[ServiceCall] = []

    async def record(call: ServiceCall) -> None:
        calls.append(call)

    hass.config.components.add("music_assistant")
    hass.services.async_register("music_assistant", "play_media", record)

    async def search(call: ServiceCall):
        calls.append(call)
        if call.data["name"] == "Abbey Road":
            return {"albums": [{"name": "Abbey Road (Remastered)", "uri": "apple_music://album/1",
                                "artists": [{"name": "The Beatles"}]}]}
        return {"albums": [{"name": "Something Else", "uri": "apple_music://album/9",
                            "artists": [{"name": "Someone"}]}]}

    from homeassistant.core import SupportsResponse

    hass.services.async_register(
        "music_assistant", "search", search, supports_response=SupportsResponse.ONLY
    )

    hass.services.async_register("music_assistant", "transfer_queue", record)
    for svc in ("shuffle_set", "repeat_set", "media_stop", "volume_set", "play_media", "media_play"):
        hass.services.async_register("media_player", svc, record)
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    reg.async_get_or_create("media_player", "music_assistant", "lr", suggested_object_id="living_room")
    reg.async_get_or_create("media_player", "music_assistant", "kt", suggested_object_id="kitchen")
    hass.states.async_set(PLAYER, "idle")

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "tester", CONF_TOKEN: "x", CONF_WEBHOOK_ID: "hook123"},
        options={CONF_PLAYER: PLAYER, CONF_VINYL_ONLY: True, CONF_RUNOUT_MODE: "speaker"},
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, "http", {})
    with patch(
        "custom_components.vinyl_player.api.DiscogsClient.fetch_tracklist",
        AsyncMock(return_value=TRACKS),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, calls


def _playing(hass, title, position, duration):
    hass.states.async_set(
        PLAYER,
        "playing",
        {
            "media_title": title,
            "media_position": position,
            "media_duration": duration,
            "media_position_updated_at": dt_util.utcnow(),
        },
    )


async def test_collection_loaded(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    assert hass.states.get("sensor.vinyl_player_records").state == "2"
    assert hass.states.get("sensor.vinyl_player_turntable").state == "idle"
    assert entry.runtime_data.public_release(entry.runtime_data.release(1))["cover"] == (
        "/vinyl_player_covers/1.jpg"
    )


async def test_play_calls_music_assistant(hass: HomeAssistant, setup) -> None:
    _, calls = setup
    result = await hass.services.async_call(
        DOMAIN, "play", {"release_id": 1}, blocking=True, return_response=True
    )
    assert result["title"] == "Abbey Road"
    ma = [c for c in calls if c.domain == "music_assistant"][0]
    assert ma.data["media_id"] == "Abbey Road"
    assert ma.data["artist"] == "The Beatles"
    assert ma.data["media_type"] == "album"
    assert ma.data["enqueue"] == "replace"
    services = [c.service for c in calls]
    assert "shuffle_set" in services and "repeat_set" in services
    assert hass.states.get("sensor.vinyl_player_turntable").state == "playing"


async def test_override_is_used(hass: HomeAssistant, setup) -> None:
    entry, calls = setup
    await entry.runtime_data.async_set_override(1, "apple_music://album/123")
    await hass.services.async_call(DOMAIN, "play", {"release_id": 1}, blocking=True)
    ma = [c for c in calls if c.domain == "music_assistant"][0]
    assert ma.data["media_id"] == "apple_music://album/123"
    assert "artist" not in ma.data


async def test_album_runs_out(hass: HomeAssistant, setup) -> None:
    entry, calls = setup
    events = async_capture_events(hass, EVENT_ALBUM_FINISHED)
    await hass.services.async_call(DOMAIN, "play", {"release_id": 1}, blocking=True)
    await hass.async_block_till_done()

    later = dt_util.utcnow() + timedelta(seconds=30)
    with patch("homeassistant.util.dt.utcnow", return_value=later):
        _playing(hass, "Her Majesty", 21, 23)
        await hass.async_block_till_done()
        hass.states.async_set(PLAYER, "idle")
        await hass.async_block_till_done()
    async_fire_time_changed(hass, later + timedelta(seconds=10))
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data["title"] == "Abbey Road"
    assert hass.states.get("sensor.vinyl_player_turntable").state == "runout"
    runout = [c for c in calls if c.domain == "media_player" and c.service == "play_media"]
    assert runout and runout[0].data["media_content_id"].endswith("/vinyl_player_static/runout.mp3")


async def test_stopped_mid_album_is_quiet(hass: HomeAssistant, setup) -> None:
    _, calls = setup
    events = async_capture_events(hass, EVENT_ALBUM_FINISHED)
    await hass.services.async_call(DOMAIN, "play", {"release_id": 1}, blocking=True)
    later = dt_util.utcnow() + timedelta(seconds=30)
    with patch("homeassistant.util.dt.utcnow", return_value=later):
        _playing(hass, "Come Together", 60, 260)
        await hass.async_block_till_done()
        hass.states.async_set(PLAYER, "idle")
        await hass.async_block_till_done()
    async_fire_time_changed(hass, later + timedelta(seconds=10))
    await hass.async_block_till_done()
    assert not events
    assert hass.states.get("sensor.vinyl_player_turntable").state == "idle"


async def test_nfc_tag_and_learning(hass: HomeAssistant, setup) -> None:
    entry, calls = setup
    manager = entry.runtime_data
    manager.async_start_learning(2)
    hass.bus.async_fire("tag_scanned", {"tag_id": "abc"})
    await hass.async_block_till_done()
    assert manager.tags["abc"]["release_id"] == 2
    assert not [c for c in calls if c.domain == "music_assistant"]

    hass.bus.async_fire("tag_scanned", {"tag_id": "abc"})
    await hass.async_block_till_done()
    ma = [c for c in calls if c.domain == "music_assistant"]
    assert ma and ma[0].data["media_id"] == "Moon Safari"


async def test_webhook(hass: HomeAssistant, setup, hass_client_no_auth) -> None:
    entry, calls = setup
    await entry.runtime_data.async_set_tag("abbey-road", 1)
    client = await hass_client_no_auth()
    resp = await client.post("/api/webhook/hook123", json={"tag": "abbey-road"})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] and body["title"] == "Abbey Road"
    resp = await client.post("/api/webhook/hook123", json={"tag": "nope"})
    assert resp.status == 404
    resp = await client.post("/api/webhook/hook123", json={"action": "stop"})
    assert (await resp.json())["action"] == "stop"


async def test_websocket(hass: HomeAssistant, setup, hass_ws_client) -> None:
    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "vinyl_player/collection"})
    msg = await ws.receive_json()
    assert msg["success"] and len(msg["result"]["releases"]) == 2
    await ws.send_json({"id": 2, "type": "vinyl_player/release", "release_id": 1})
    msg = await ws.receive_json()
    assert msg["result"]["tracks"][0]["position"] == "A1"
    await ws.send_json({"id": 3, "type": "vinyl_player/subscribe"})
    msg = await ws.receive_json()
    assert msg["success"]
    msg = await ws.receive_json()
    assert msg["event"]["state"]["phase"] == "idle"
    assert msg["event"]["webhook_id"] == "hook123"


def _file(hass):
    with open(hass.config.path("vinyl_player", "collection.json"), encoding="utf-8") as fh:
        return {r["id"]: r for r in json.load(fh)["releases"]}


async def test_hidden_record_and_file_tag(hass: HomeAssistant, setup) -> None:
    """hidden keeps a record off the shelf; its tag_id from the file still plays it."""
    entry, calls = setup
    manager = entry.runtime_data
    assert [r["id"] for r in manager.releases] == [1, 2]
    hass.bus.async_fire("tag_scanned", {"tag_id": "secret-tag"})
    await hass.async_block_till_done()
    ma = [c for c in calls if c.domain == "music_assistant" and c.service == "play_media"]
    assert ma[0].data["media_id"] == "Hidden - Secret LP (Remastered)"


async def test_ui_edits_are_written_to_collection_json(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    manager = entry.runtime_data
    await manager.async_set_tag("abc", 1)
    await manager.async_set_tag("def", 1)
    await manager.async_set_override(2, "Air - Moon Safari (Remastered)")
    await manager.async_set_hidden(2, True)
    data = await hass.async_add_executor_job(_file, hass)
    assert data[1]["tag_id"] == ["abc", "def"]
    assert data[2]["ma_query"] == "Air - Moon Safari (Remastered)" and data[2]["hidden"] is True
    await manager.async_set_tag("abc", None)
    data = await hass.async_add_executor_job(_file, hass)
    assert data[1]["tag_id"] == "def"
    assert manager.tags["def"]["release_id"] == 1 and "abc" not in manager.tags


async def test_sync_keeps_hand_edited_fields(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    manager = entry.runtime_data
    item = {
        "id": 3, "instance_id": 1,
        "basic_information": {"id": 3, "title": "Secret LP", "artists": [{"name": "Hidden"}],
                              "formats": [{"name": "Vinyl"}]},
    }
    with (
        patch("custom_components.vinyl_player.api.DiscogsClient.fetch_collection_items",
              AsyncMock(return_value=[item])),
        patch("custom_components.vinyl_player.api.DiscogsClient.download_covers",
              AsyncMock(return_value=0)),
    ):
        await manager.async_sync()
    data = await hass.async_add_executor_job(_file, hass)
    assert list(data) == [3]
    assert data[3]["tag_id"] == "secret-tag" and data[3]["hidden"] is True
    assert data[3]["ma_query"] == "Hidden - Secret LP (Remastered)"


async def test_check_matches(hass: HomeAssistant, setup) -> None:
    entry, _ = setup
    with patch.object(type(entry.runtime_data), "_music_assistant_entry_id", return_value="ma1"):
        result = await hass.services.async_call(
            DOMAIN, "check_matches", {}, blocking=True, return_response=True
        )
    assert result["checked"] == 2  # hidden records are skipped
    assert [m["title"] for m in result["misses"]] == ["Moon Safari"]
    assert result["misses"][0]["best"]["uri"] == "apple_music://album/9"


async def test_switch_speaker_moves_the_record(hass: HomeAssistant, setup) -> None:
    entry, calls = setup
    manager = entry.runtime_data
    assert manager.players() == ["media_player.kitchen", PLAYER]
    await manager.async_play(1)
    await manager.async_set_player("media_player.kitchen")
    assert manager.player == "media_player.kitchen"
    move = [c for c in calls if c.service == "transfer_queue"][0]
    assert move.data["entity_id"] == "media_player.kitchen" and move.data["source_player"] == PLAYER
    # the old speaker going idle no longer ends the session
    hass.states.async_set(PLAYER, "idle")
    await hass.async_block_till_done()
    assert hass.states.get("sensor.vinyl_player_turntable").state == "playing"
    await manager.async_resume()
    assert [c for c in calls if c.service == "media_play"][0].data["entity_id"] == "media_player.kitchen"
    import pytest as _pytest
    from homeassistant.exceptions import ServiceValidationError

    with _pytest.raises(ServiceValidationError):
        await manager.async_set_player("media_player.not_ma")


async def test_runout_sound_is_served_and_testable(hass: HomeAssistant, setup, hass_client_no_auth) -> None:
    entry, calls = setup
    manager = entry.runtime_data
    client = await hass_client_no_auth()
    resp = await client.get("/vinyl_player_static/runout.mp3")
    assert resp.status == 200
    assert len(await resp.read()) > 50_000  # the real 7 s sound, not an empty file

    res = await manager.async_test_runout()
    assert res["mode"] == "speaker"
    played = [c for c in calls if c.domain == "media_player" and c.service == "play_media"]
    assert played[-1].data["media_content_id"].endswith("/vinyl_player_static/runout.mp3")

    from homeassistant.exceptions import ServiceValidationError

    await manager.async_play(1)
    with pytest.raises(ServiceValidationError):
        await manager.async_test_runout()


async def test_panel_commands_are_registered(hass: HomeAssistant, setup, hass_ws_client) -> None:
    """Every websocket command the panel uses must exist (no 'Unknown command')."""
    import re
    from pathlib import Path

    js = Path(__file__).parents[1] / "custom_components/vinyl_player/frontend/vinyl-player-panel.js"
    used = set(re.findall(r'this\.ws\("([a-z_]+)"', js.read_text(encoding="utf-8")))
    assert {"test_runout", "set_player", "resume", "play", "stop"} <= used
    from homeassistant.components.websocket_api import const as ws_const

    registered = hass.data[ws_const.DOMAIN]
    missing = [c for c in used if f"vinyl_player/{c}" not in registered]
    assert not missing, missing

    ws = await hass_ws_client(hass)
    await ws.send_json({"id": 1, "type": "vinyl_player/test_runout"})
    msg = await ws.receive_json()
    assert msg["success"], msg
    assert msg["result"]["url"].endswith("runout.mp3")
