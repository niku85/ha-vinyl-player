# Changelog

## [0.6.3] – 2026-11-03

- End-of-record sound: no more "cow". The pitched motor hum after the arm lifts is replaced by a dull lift thud, a soft noise-only "shhh" while the arm travels back and a quiet tick when it settles in its rest.

## [0.6.2] – 2026-11-03

- The integration icon now shows in Home Assistant: moved to `custom_components/vinyl_player/brand/` (with dark-mode variants), where Home Assistant looks for it.

## [0.6.1] – 2026-11-03

- If the page and the running integration don't match (HACS updated the files but Home Assistant wasn't restarted yet), the panel now says "Restart Home Assistant to finish the update" instead of failing with "Unknown command" (e.g. on *Test sound*).
- Test that every command the panel uses is registered in the backend.

## [0.6.0] – 2026-11-03

First tagged release – everything built so far.

**Collection**
- Discogs export inside Home Assistant (username + personal token in the setup), re-synced every 24 h; covers and thumbnails cached locally
- Standalone export script `scripts/discogs_export.py` (standard library only)
- Hand-editable `ma_query`, `tag_id` and `hidden` per record in `collection.json`, kept across re-exports
- *Check all records*: lists the albums Music Assistant can't find, with its best guess

**Cover flow & turntable**
- Swipeable cover flow (search, sort, scrubber, preloading for fast swipes)
- The record slides out of its sleeve onto the platter; the tonearm follows the album and shows side/track (e.g. `B2`)
- Technics-style deck: speaker knob with light diode (tap = next speaker, hold = list), rectangular START/STOP, volume fader; no skipping
- Pause stops the platter, START resumes; tap the turntable to put the record back
- State is kept when you leave the panel and come back
- Two looks: dark turntable (sidebar panel) and `look: frame` for the Frame wall dashboard card (`custom:vinyl-player-card`)

**Playback**
- Music Assistant (e.g. Apple Music), shuffle/repeat off; switching speakers moves a playing record over
- End-of-record sound (run-out groove + arm return) on the speaker or in the browser, with *Test sound*

**NFC**
- *Write tag* from the HA app, *Scan tag to link*, ESP32/ESPHome reader, Apple Shortcut webhook
