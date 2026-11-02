"""Websocket API used by the Vinyl Player panel."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.network import NoURLAvailableError, get_url

from .const import (
    CONF_WEBHOOK_ID,
    DOMAIN,
    PANEL_URL_PATH,
    RUNOUT_SOUND_FILE,
    SIGNAL_COLLECTION,
    SIGNAL_STATE,
    STATIC_URL,
    VERSION,
)


def _manager(hass: HomeAssistant):
    from . import get_manager  # late import to avoid a cycle

    return get_manager(hass)


def _wrap(handler):
    """Turn HomeAssistantErrors into websocket errors."""

    async def wrapper(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
        try:
            await handler(hass, connection, msg)
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "vinyl_player_error", str(err))

    return wrapper


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    for command in (
        ws_info,
        ws_collection,
        ws_release,
        ws_subscribe,
        ws_play,
        ws_stop,
        ws_volume,
        ws_sync,
        ws_set_tag,
        ws_learn,
        ws_set_override,
    ):
        websocket_api.async_register_command(hass, command)


def _info(hass: HomeAssistant) -> dict[str, Any]:
    manager = _manager(hass)
    webhook_id = manager.entry.data[CONF_WEBHOOK_ID]
    try:
        external = get_url(hass, prefer_external=True)
    except NoURLAvailableError:
        external = None
    return {
        "version": VERSION,
        "username": manager.entry.data.get("username"),
        "player": manager.player,
        "runout_mode": manager.runout_mode,
        "runout_sound": f"{STATIC_URL}/{RUNOUT_SOUND_FILE}",
        "webhook_id": webhook_id,
        "webhook_url": f"{external}/api/webhook/{webhook_id}" if external else None,
        "panel_deeplink": f"homeassistant://navigate/{PANEL_URL_PATH}",
        "tags": manager.tags,
        "syncing": manager.syncing,
        "sync_error": manager.sync_error,
        "last_sync": manager.export_meta.get("generated_at"),
        "count": len(manager.releases),
        "state": manager.state_payload(),
    }


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/info"})
@websocket_api.async_response
@_wrap
async def ws_info(hass, connection, msg):
    connection.send_result(msg["id"], _info(hass))


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/collection"})
@websocket_api.async_response
@_wrap
async def ws_collection(hass, connection, msg):
    manager = _manager(hass)
    connection.send_result(
        msg["id"],
        {
            "releases": [manager.public_release(r) for r in manager.releases],
            "last_sync": manager.export_meta.get("generated_at"),
        },
    )


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/release", vol.Required("release_id"): vol.Coerce(int)}
)
@websocket_api.async_response
@_wrap
async def ws_release(hass, connection, msg):
    manager = _manager(hass)
    release = manager.release(msg["release_id"])
    connection.send_result(
        msg["id"],
        {
            **manager.public_release(release),
            "tracks": await manager.async_tracklist(release["id"]),
        },
    )


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/subscribe"})
@websocket_api.async_response
@_wrap
async def ws_subscribe(hass, connection, msg):
    """Push session state + info changes to the panel."""

    @callback
    def push_state() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], {"kind": "info", **_info(hass)})
        )

    @callback
    def push_collection() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], {"kind": "collection", **_info(hass)})
        )

    unsubs = [
        async_dispatcher_connect(hass, SIGNAL_STATE, push_state),
        async_dispatcher_connect(hass, SIGNAL_COLLECTION, push_collection),
    ]

    @callback
    def unsubscribe() -> None:
        for unsub in unsubs:
            unsub()

    connection.subscriptions[msg["id"]] = unsubscribe
    connection.send_result(msg["id"])
    push_state()


@websocket_api.websocket_command(
    {vol.Required("type"): f"{DOMAIN}/play", vol.Required("release_id"): vol.Coerce(int)}
)
@websocket_api.async_response
@_wrap
async def ws_play(hass, connection, msg):
    result = await _manager(hass).async_play(msg["release_id"], source="panel")
    connection.send_result(msg["id"], result)


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/stop"})
@websocket_api.async_response
@_wrap
async def ws_stop(hass, connection, msg):
    await _manager(hass).async_stop()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/volume",
        vol.Required("volume"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
    }
)
@websocket_api.async_response
@_wrap
async def ws_volume(hass, connection, msg):
    await _manager(hass).async_set_volume(msg["volume"])
    connection.send_result(msg["id"])


@websocket_api.websocket_command({vol.Required("type"): f"{DOMAIN}/sync"})
@websocket_api.require_admin
@websocket_api.async_response
@_wrap
async def ws_sync(hass, connection, msg):
    _manager(hass).start_sync()
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_tag",
        vol.Required("tag_id"): str,
        vol.Optional("release_id"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("name"): vol.Any(None, str),
    }
)
@websocket_api.async_response
@_wrap
async def ws_set_tag(hass, connection, msg):
    _manager(hass).async_set_tag(msg["tag_id"], msg.get("release_id"), msg.get("name"))
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/learn_tag",
        vol.Optional("release_id"): vol.Any(None, vol.Coerce(int)),
    }
)
@websocket_api.async_response
@_wrap
async def ws_learn(hass, connection, msg):
    manager = _manager(hass)
    if msg.get("release_id") is None:
        manager.async_cancel_learning()
    else:
        manager.async_start_learning(msg["release_id"])
    connection.send_result(msg["id"])


@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/set_override",
        vol.Required("release_id"): vol.Coerce(int),
        vol.Optional("media_id"): vol.Any(None, str),
    }
)
@websocket_api.async_response
@_wrap
async def ws_set_override(hass, connection, msg):
    _manager(hass).async_set_override(msg["release_id"], msg.get("media_id"))
    connection.send_result(msg["id"])
