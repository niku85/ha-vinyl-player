"""Constants for the Vinyl Player integration."""

from __future__ import annotations

DOMAIN = "vinyl_player"
VERSION = "0.6.0"

CONF_USERNAME = "username"
CONF_TOKEN = "token"
CONF_PLAYER = "player_entity_id"
CONF_VINYL_ONLY = "vinyl_only"
CONF_RUNOUT_MODE = "runout_mode"
CONF_SYNC_INTERVAL = "sync_interval_hours"
CONF_WEBHOOK_ID = "webhook_id"

RUNOUT_SPEAKER = "speaker"
RUNOUT_BROWSER = "browser"
RUNOUT_OFF = "off"
RUNOUT_MODES = [RUNOUT_SPEAKER, RUNOUT_BROWSER, RUNOUT_OFF]

DEFAULT_VINYL_ONLY = True
DEFAULT_RUNOUT_MODE = RUNOUT_SPEAKER
DEFAULT_SYNC_INTERVAL = 24

MUSIC_ASSISTANT_DOMAIN = "music_assistant"

# Where the export (collection.json + covers/) lives inside the HA config dir.
DATA_DIR = "vinyl_player"
COLLECTION_FILE = "collection.json"
COVERS_DIR = "covers"

PANEL_URL_PATH = "vinyl-player"
PANEL_TITLE = "Vinyl Player"
PANEL_ICON = "mdi:record-player"
PANEL_ELEMENT = "vinyl-player-panel"

STATIC_URL = "/vinyl_player_static"
COVERS_URL = "/vinyl_player_covers"

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.data"

SIGNAL_STATE = f"{DOMAIN}_state"
SIGNAL_COLLECTION = f"{DOMAIN}_collection"

EVENT_ALBUM_STARTED = f"{DOMAIN}_album_started"
EVENT_ALBUM_FINISHED = f"{DOMAIN}_album_finished"
EVENT_TAG_LEARNED = f"{DOMAIN}_tag_learned"
EVENT_UNKNOWN_TAG = f"{DOMAIN}_unknown_tag"

# Session phases (also the state of the turntable sensor)
PHASE_IDLE = "idle"
PHASE_PLAYING = "playing"
PHASE_RUNOUT = "runout"

RUNOUT_SOUND_FILE = "runout.mp3"
