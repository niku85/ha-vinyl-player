"""Config flow tests."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.vinyl_player.api import DiscogsAuthError
from custom_components.vinyl_player.const import DOMAIN


async def test_requires_music_assistant(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "music_assistant_missing"


async def test_full_flow(hass: HomeAssistant) -> None:
    hass.config.components.add("music_assistant")
    er.async_get(hass).async_get_or_create("media_player", "music_assistant", "abc", suggested_object_id="kitchen")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["step_id"] == "user"

    with patch(
        "custom_components.vinyl_player.config_flow.DiscogsClient.identity",
        AsyncMock(side_effect=DiscogsAuthError("bad")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "Niku", "token": "bad"}
        )
    assert result["errors"] == {"base": "invalid_auth"}

    with patch(
        "custom_components.vinyl_player.config_flow.DiscogsClient.identity",
        AsyncMock(return_value="niku"),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"username": "Niku", "token": "good"}
        )
    assert result["step_id"] == "player"
    with patch("custom_components.vinyl_player.async_setup_entry", AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"player_entity_id": "media_player.kitchen", "vinyl_only": True, "runout_mode": "speaker"},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["username"] == "niku"
    assert result["data"]["webhook_id"]
    assert result["options"]["player_entity_id"] == "media_player.kitchen"
