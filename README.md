# HA Vinyl Player

Browse your **Discogs** record collection in Home Assistant with an Apple-style
**cover flow**. Tap the record in the centre: it slides out of its sleeve, drops
onto an animated **turntable**, the tonearm swings in, and the album plays
through **Music Assistant** (e.g. via Apple Music).

Like real vinyl you can't skip tracks. You get volume and stop, and that's it.
When the album is over, the needle sits in the run-out groove for a few
revolutions *(crackle… thump… crackle…)* and then the arm returns to its rest.

```
┌──────────────────────────────────────────────┐
│   ▯▯▯▯ ▯▯▯ [  ALBUM  ] ▯▯▯ ▯▯▯▯              │  ← swipe left / right
│              Artist – Album                   │
│  ┌────────────────────────────────────────┐  │
│  │   ╭──────────╮                    ◉    │  │
│  │  │  ◎ label   │               ╲  │  ▮  │  │  ← tonearm follows the
│  │   ╰──────────╯                  ╲│  ▮  │  │     album progress
│  │ [STOP]                            ▣  ▮  │  │  ← volume fader
│  └────────────────────────────────────────┘  │
└──────────────────────────────────────────────┘
```

## What's in the repo

| Part | Where | What it does |
|---|---|---|
| **1. Export script** | [`scripts/discogs_export.py`](scripts/discogs_export.py) | Exports your Discogs collection to `collection.json` and downloads all covers. Standard library only. |
| **2. Cover flow app** | [`custom_components/vinyl_player/frontend`](custom_components/vinyl_player/frontend/vinyl-player-panel.js) | A sidebar panel in HA: cover flow (swipe, drag, mouse wheel, arrow keys, search, sort, scrubber) plus the sleeve → platter animation. |
| **3. Turntable** | same panel | Spinning platter (33⅓ rpm), a tonearm that follows the album, START/STOP, a volume fader, the current side/track (e.g. `B2 · Here Comes the Sun`). No skip buttons. |
| **4. Playback** | [`custom_components/vinyl_player`](custom_components/vinyl_player) | A Home Assistant integration that plays the album via `music_assistant.play_media`. It turns off shuffle and repeat, detects when the album ends and plays the run-out sound. |
| NFC | integration + [docs](docs/nfc-and-shortcuts.md) | A list of tag → album links, a "scan to link" mode, HA Companion tags, and a webhook for an **Apple Shortcut**. |
| Run-out sound | `frontend/runout.mp3`, made by [`tools/generate_runout_sound.py`](tools/generate_runout_sound.py) | A locked groove, the arm lifting, the auto-return motor and the arm clicking into its rest. |

## Requirements

* Home Assistant **2024.12** or newer
* **Music Assistant** installed **and** added to HA (Settings → Devices & services → Music Assistant),
  with a streaming provider such as Apple Music and at least one player
* A Discogs account and a **personal access token**:
  [discogs.com/settings/developers](https://www.discogs.com/settings/developers) → *Generate new token*

## Installation

### HACS (custom repository)
1. HACS → ⋮ → *Custom repositories* → `https://github.com/niku85/ha-vinyl-player`, type **Integration**.
2. Install **Vinyl Player** and restart Home Assistant.

### Manual
Copy `custom_components/vinyl_player` to `<config>/custom_components/vinyl_player` and restart.

## Setup

1. Settings → Devices & services → **Add integration** → *Vinyl Player*.
2. Enter your **Discogs username** and **personal access token**. The token is checked against Discogs.
   If Music Assistant isn't set up, the setup stops and tells you so.
3. Pick the **Music Assistant player**, choose whether to show **vinyl only**, and pick where the
   **end-of-record sound** plays (speaker / browser / off).
4. Open **Vinyl Player** in the sidebar. The first sync exports your collection and caches every cover
   in `<config>/vinyl_player/covers/`. Later visits load from that local cache, so they're fast.

You can change the speaker, filter, sound and sync interval later under *Configure*.
To change the Discogs credentials, use *Reconfigure*.

## Using it

* **Swipe** or drag the covers, or use the scroll wheel or the ← → keys. The slider underneath jumps through big collections.
* **Tap the centre cover** (or press Enter) to put the record on the turntable.
* **STOP** lifts the arm and stops playback. **START** drops the needle on the same record again.
* **Volume**: the fader on the right of the plinth.
* Tap the record on the platter to scroll the shelf back to it.
* ⚙ → *This album*: if Music Assistant picks the wrong version (e.g. a deluxe edition), paste a
  Music Assistant URI such as `apple_music://album/1441164426`, or a better search text.
* Deep link: `/vinyl-player?release=<discogs release id>` opens the panel on that record.

If playback starts anywhere else (an NFC tag, the Shortcut, an automation, another tablet), every open
panel scrolls to the record and plays the same sleeve → platter animation.

## The export script

```bash
python3 scripts/discogs_export.py --username YOUR_NAME --token YOUR_TOKEN --output ./vinyl_player
# or: DISCOGS_TOKEN=... python3 scripts/discogs_export.py -u YOUR_NAME -o /config/vinyl_player
#   --all-formats   include CDs, cassettes, …
#   --no-covers     skip downloading covers
```

The integration's own sync writes exactly the same format to `<config>/vinyl_player/`. So you can run
the script on another machine and copy the folder over, and the integration will pick it up.

<details><summary><code>collection.json</code> format</summary>

```json
{
  "version": 1, "source": "discogs", "username": "niku85",
  "generated_at": "2026-11-02T12:00:00+00:00", "count": 1, "vinyl_only": true,
  "releases": [{
    "id": 249504, "instance_id": 123, "master_id": 24047,
    "artist": "The Beatles", "artists": ["The Beatles"], "title": "Abbey Road", "year": 1969,
    "formats": ["Album", "LP", "Vinyl"], "format_text": "Vinyl, LP, Album", "vinyl": true,
    "genres": ["Rock"], "styles": ["Pop Rock"], "labels": ["Apple Records"], "catno": "PCS 7088",
    "cover_url": "https://i.discogs.com/…", "thumb_url": "https://i.discogs.com/…",
    "cover_file": "covers/249504.jpg", "date_added": "2024-01-01T10:00:00-08:00", "rating": 0
  }]
}
```
</details>

## NFC tags & Apple Shortcut

See **[docs/nfc-and-shortcuts.md](docs/nfc-and-shortcuts.md)**. In short:

* **Option A (no Shortcut):** write tags with the HA Companion app, then in the panel open
  ⚙ → *NFC tags* → **Scan tag to link** and scan the tag. After that, touching the tag starts the record.
* **Option B (Apple Shortcut):** an iOS NFC automation runs the *Play Vinyl* shortcut. The shortcut
  POSTs `{"tag": "<name>"}` to the integration's webhook and opens the panel. The panel shows the
  exact webhook URL.

The links are stored as a list of *tag → album* in HA. You can manage them in the panel or with the
`vinyl_player.link_tag` service.

## Services, events, entities

| Service | Data |
|---|---|
| `vinyl_player.play` | `release_id` **or** `tag_id` (returns the record) |
| `vinyl_player.stop` | – |
| `vinyl_player.sync` | – re-export from Discogs and cache any new covers |
| `vinyl_player.link_tag` | `tag_id`, `release_id` (leave it out to unlink), `name` |

Events: `vinyl_player_album_started`, `vinyl_player_album_finished`, `vinyl_player_tag_learned`,
`vinyl_player_unknown_tag`.

Entities: `sensor.vinyl_player_turntable` (`idle` / `playing` / `runout`, with the cover as its picture)
and `sensor.vinyl_player_records` (collection size, last sync).

Example: switch the amplifier off 5 minutes after a record ends.

```yaml
automation:
  - alias: Amp off after the record
    triggers: [{ trigger: event, event_type: vinyl_player_album_finished }]
    actions:
      - delay: "00:05:00"
      - action: switch.turn_off
        target: { entity_id: switch.amplifier }
```

## How "end of album" is detected

When Music Assistant's player goes from *playing* to *idle* by itself, the integration checks two
things: was the last track within ~25 s of its end, and was it the last track of the Discogs
tracklist? If both are true, the album ran out. It then fires `vinyl_player_album_finished` and plays
`runout.mp3`, either on the speaker (Music Assistant fetches it from HA's internal URL) or in the
browser. If someone stops playback mid-album from another app, the session just ends quietly.

## Development

```bash
python3 -m pytest tests            # helper + integration tests (needs pytest-homeassistant-custom-component)
python3 tools/generate_runout_sound.py   # re-create the run-out sound
```
