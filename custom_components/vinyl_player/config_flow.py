"""Config flow: Discogs credentials + Music Assistant player."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import DiscogsAuthError, DiscogsClient, DiscogsError
from .const import (
    CONF_PLAYER,
    CONF_RUNOUT_MODE,
    CONF_SYNC_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
    CONF_VINYL_ONLY,
    CONF_WEBHOOK_ID,
    DEFAULT_RUNOUT_MODE,
    DEFAULT_SYNC_INTERVAL,
    DEFAULT_VINYL_ONLY,
    DOMAIN,
    MUSIC_ASSISTANT_DOMAIN,
    RUNOUT_MODES,
)

PLAYER_SELECTOR = EntitySelector(
    EntitySelectorConfig(domain="media_player", integration=MUSIC_ASSISTANT_DOMAIN)
)
RUNOUT_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=RUNOUT_MODES, translation_key="runout_mode", mode=SelectSelectorMode.LIST
    )
)
HOURS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=0, max=168, step=1, mode=NumberSelectorMode.BOX,
                         unit_of_measurement="h")
)


async def _validate(hass, username: str, token: str) -> str:
    """Return the canonical username or raise."""
    client = DiscogsClient(async_get_clientsession(hass), username, token)
    identity = await client.identity()
    if identity and identity.casefold() != username.strip().casefold():
        raise DiscogsAuthError("token_user_mismatch")
    return identity or username.strip()


def _ma_players(hass) -> list[str]:
    registry = er.async_get(hass)
    return [
        e.entity_id
        for e in registry.entities.values()
        if e.platform == MUSIC_ASSISTANT_DOMAIN and e.domain == "media_player"
    ]


class VinylPlayerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._creds: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if MUSIC_ASSISTANT_DOMAIN not in self.hass.config.components:
            return self.async_abort(reason="music_assistant_missing")

        errors: dict[str, str] = {}
        if user_input is not None:
            errors, username = await self._check(user_input)
            if not errors:
                self._creds = {CONF_USERNAME: username, CONF_TOKEN: user_input[CONF_TOKEN].strip()}
                await self.async_set_unique_id(username.casefold())
                self._abort_if_unique_id_configured()
                return await self.async_step_player()

        return self.async_show_form(
            step_id="user",
            data_schema=self._creds_schema(user_input or {}),
            errors=errors,
            description_placeholders={"token_url": "https://www.discogs.com/settings/developers"},
        )

    async def async_step_player(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        players = _ma_players(self.hass)
        if not players:
            return self.async_abort(reason="no_players")
        if user_input is not None:
            return self.async_create_entry(
                title=f"Discogs: {self._creds[CONF_USERNAME]}",
                data={**self._creds, CONF_WEBHOOK_ID: webhook.async_generate_id()},
                options={
                    CONF_PLAYER: user_input[CONF_PLAYER],
                    CONF_VINYL_ONLY: user_input[CONF_VINYL_ONLY],
                    CONF_RUNOUT_MODE: user_input[CONF_RUNOUT_MODE],
                    CONF_SYNC_INTERVAL: DEFAULT_SYNC_INTERVAL,
                },
            )
        return self.async_show_form(
            step_id="player",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAYER, default=players[0]): PLAYER_SELECTOR,
                    vol.Required(CONF_VINYL_ONLY, default=DEFAULT_VINYL_ONLY): bool,
                    vol.Required(CONF_RUNOUT_MODE, default=DEFAULT_RUNOUT_MODE): RUNOUT_SELECTOR,
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change Discogs username / token."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, username = await self._check(user_input)
            if not errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_USERNAME: username, CONF_TOKEN: user_input[CONF_TOKEN].strip()},
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._creds_schema(user_input or dict(entry.data)),
            errors=errors,
            description_placeholders={"token_url": "https://www.discogs.com/settings/developers"},
        )

    async def _check(self, user_input: dict[str, Any]) -> tuple[dict[str, str], str]:
        try:
            username = await _validate(
                self.hass, user_input[CONF_USERNAME], user_input[CONF_TOKEN]
            )
        except DiscogsAuthError as err:
            key = "token_user_mismatch" if str(err) == "token_user_mismatch" else "invalid_auth"
            return {"base": key}, ""
        except DiscogsError:
            return {"base": "cannot_connect"}, ""
        return {}, username

    @staticmethod
    def _creds_schema(defaults: dict[str, Any]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=defaults.get(CONF_USERNAME, "")): str,
                vol.Required(CONF_TOKEN, default=defaults.get(CONF_TOKEN, "")): TextSelector(
                    TextSelectorConfig(type=TextSelectorType.PASSWORD)
                ),
            }
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        return VinylPlayerOptionsFlow()


class VinylPlayerOptionsFlow(OptionsFlow):
    """Player, filters and run-out behaviour."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PLAYER, default=opts.get(CONF_PLAYER)): PLAYER_SELECTOR,
                    vol.Required(
                        CONF_VINYL_ONLY, default=opts.get(CONF_VINYL_ONLY, DEFAULT_VINYL_ONLY)
                    ): bool,
                    vol.Required(
                        CONF_RUNOUT_MODE, default=opts.get(CONF_RUNOUT_MODE, DEFAULT_RUNOUT_MODE)
                    ): RUNOUT_SELECTOR,
                    vol.Required(
                        CONF_SYNC_INTERVAL,
                        default=opts.get(CONF_SYNC_INTERVAL, DEFAULT_SYNC_INTERVAL),
                    ): HOURS_SELECTOR,
                }
            ),
        )
