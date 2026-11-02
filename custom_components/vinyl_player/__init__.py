"""Vinyl Player – browse your Discogs records in a cover flow and play them via Music Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend, panel_custom, webhook
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_WEBHOOK_ID,
    COVERS_URL,
    DOMAIN,
    MUSIC_ASSISTANT_DOMAIN,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_TITLE,
    PANEL_URL_PATH,
    STATIC_URL,
    VERSION,
)
from .manager import VinylManager
from .websocket import async_register_websocket

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type VinylConfigEntry = ConfigEntry[VinylManager]

FRONTEND_DIR = Path(__file__).parent / "frontend"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register things that live for the whole HA run (static files, ws, services)."""
    await hass.http.async_register_static_paths(
        [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
    )
    async_register_websocket(hass)
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: VinylConfigEntry) -> bool:
    """Set up Vinyl Player from a config entry."""
    if MUSIC_ASSISTANT_DOMAIN not in hass.config.components:
        raise ConfigEntryNotReady("Waiting for Music Assistant to be set up")

    manager = VinylManager(hass, entry)
    await manager.async_setup()
    entry.runtime_data = manager

    covers_dir = manager.covers_dir
    await hass.async_add_executor_job(lambda: covers_dir.mkdir(parents=True, exist_ok=True))
    if not hass.data.get(f"{DOMAIN}_covers_registered"):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(COVERS_URL, str(covers_dir), cache_headers=True)]
        )
        hass.data[f"{DOMAIN}_covers_registered"] = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{STATIC_URL}/vinyl-player-panel.js?v={VERSION}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=False,
        embed_iframe=False,
        config={"entry_id": entry.entry_id},
    )

    webhook.async_register(
        hass,
        DOMAIN,
        "Vinyl Player (NFC / Apple Shortcuts)",
        entry.data[CONF_WEBHOOK_ID],
        _handle_webhook,
        allowed_methods=["POST", "GET"],
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: VinylConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        webhook.async_unregister(hass, entry.data[CONF_WEBHOOK_ID])
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
        await entry.runtime_data.async_unload()
    return unloaded


async def _async_update_listener(hass: HomeAssistant, entry: VinylConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def get_manager(hass: HomeAssistant) -> VinylManager:
    """Return the manager of the (single) loaded entry."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is ConfigEntryState.LOADED:
            return entry.runtime_data
    raise HomeAssistantError("Vinyl Player is not set up")


async def _handle_webhook(
    hass: HomeAssistant, webhook_id: str, request: web.Request
) -> web.Response:
    """Webhook used by the Apple Shortcut (or anything else that can do HTTP).

    Accepted (JSON body or query string):
      {"tag": "<tag id>"}      play the record mapped to this tag
      {"release_id": 1234}     play a record directly
      {"action": "stop"}       stop playback
    """
    payload: dict = dict(request.query)
    if request.method == "POST" and request.body_exists:
        try:
            body = await request.json()
            if isinstance(body, dict):
                payload.update(body)
        except ValueError:
            text = (await request.text()).strip()
            if text:
                payload.setdefault("tag", text)

    try:
        manager = get_manager(hass)
        if payload.get("action") == "stop":
            await manager.async_stop()
            return web.json_response({"ok": True, "action": "stop"})
        if payload.get("release_id"):
            result = await manager.async_play(payload["release_id"], source="webhook")
        elif payload.get("tag"):
            result = await manager.async_handle_tag(str(payload["tag"]), source="shortcut")
            if result is None:
                return web.json_response(
                    {"ok": False, "error": f"Unknown tag {payload['tag']}"}, status=404
                )
        else:
            return web.json_response({"ok": False, "error": "Send tag or release_id"}, status=400)
    except HomeAssistantError as err:
        return web.json_response({"ok": False, "error": str(err)}, status=400)
    return web.json_response(
        {"ok": True, "panel": f"homeassistant://navigate/{PANEL_URL_PATH}", **result}
    )


def _register_services(hass: HomeAssistant) -> None:
    async def play(call: ServiceCall) -> ServiceResponse:
        manager = get_manager(hass)
        if tag := call.data.get("tag_id"):
            result = await manager.async_handle_tag(tag, source="service")
            if result is None:
                raise HomeAssistantError(f"Tag {tag} is not linked to a record")
            return result
        if "release_id" not in call.data:
            raise HomeAssistantError("Provide release_id or tag_id")
        return await manager.async_play(call.data["release_id"], source="service")

    async def stop(call: ServiceCall) -> None:
        await get_manager(hass).async_stop()

    async def sync(call: ServiceCall) -> None:
        manager = get_manager(hass)
        task = manager.start_sync()
        if task:
            await task

    async def link_tag(call: ServiceCall) -> None:
        get_manager(hass).async_set_tag(
            call.data["tag_id"], call.data.get("release_id"), call.data.get("name")
        )

    hass.services.async_register(
        DOMAIN,
        "play",
        play,
        schema=vol.Schema(
            {vol.Optional("release_id"): vol.Coerce(int), vol.Optional("tag_id"): cv.string}
        ),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, "stop", stop)
    hass.services.async_register(DOMAIN, "sync", sync)
    hass.services.async_register(
        DOMAIN,
        "link_tag",
        link_tag,
        schema=vol.Schema(
            {
                vol.Required("tag_id"): cv.string,
                vol.Optional("release_id"): vol.Any(None, vol.Coerce(int)),
                vol.Optional("name"): cv.string,
            }
        ),
    )
