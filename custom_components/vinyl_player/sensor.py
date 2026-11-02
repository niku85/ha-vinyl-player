"""Sensors: what's on the turntable, and how many records are on the shelf."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PHASE_IDLE, PHASE_PLAYING, PHASE_RUNOUT, SIGNAL_COLLECTION, SIGNAL_STATE, VERSION
from .manager import VinylManager


async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities: AddEntitiesCallback) -> None:
    manager: VinylManager = entry.runtime_data
    async_add_entities([TurntableSensor(manager), CollectionSensor(manager)])


class _Base(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _signal: str

    def __init__(self, manager: VinylManager) -> None:
        self.manager = manager
        self._attr_unique_id = f"{manager.entry.entry_id}_{self._key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, manager.entry.entry_id)},
            name="Vinyl Player",
            manufacturer="Discogs × Music Assistant",
            model="Turntable",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, self._signal, self._update))

    @callback
    def _update(self) -> None:
        self.async_write_ha_state()


class TurntableSensor(_Base):
    _key = "turntable"
    _signal = SIGNAL_STATE
    _attr_translation_key = "turntable"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [PHASE_IDLE, PHASE_PLAYING, PHASE_RUNOUT]
    _attr_icon = "mdi:record-player"

    @property
    def native_value(self) -> str:
        return self.manager.session.get("phase", PHASE_IDLE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self.manager.session
        return {
            k: s.get(k)
            for k in ("release_id", "artist", "title", "cover", "source", "started_at")
            if s.get(k) is not None
        }

    @property
    def entity_picture(self) -> str | None:
        return self.manager.session.get("cover")


class CollectionSensor(_Base):
    _key = "records"
    _signal = SIGNAL_COLLECTION
    _attr_translation_key = "records"
    _attr_icon = "mdi:album"
    _attr_native_unit_of_measurement = "records"

    @property
    def native_value(self) -> int:
        return len(self.manager.releases)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "last_sync": self.manager.export_meta.get("generated_at"),
            "syncing": self.manager.syncing,
            "sync_error": self.manager.sync_error,
            "username": self.manager.export_meta.get("username"),
        }
