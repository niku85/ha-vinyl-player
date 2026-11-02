# NFC tags & the Apple Shortcut

Put an NFC sticker (NTAG213/215) on each record's sleeve. When you touch it with your iPhone, the record
starts playing and every open Vinyl Player panel animates it onto the turntable.

There are two ways to set this up. Both use the same **list of tag → album links**, which you
manage in the panel under ⚙ → **NFC tags**.

| | Option A: HA Companion tags | Option B: Apple Shortcut |
|---|---|---|
| Setup per record | write the tag + "Scan tag to link" | one iOS automation per tag |
| Works when the phone is locked | ✔ (background tag reading, iPhone XS+) | ✔ (iOS asks for confirmation unless "Run Immediately") |
| Opens the panel | optional | ✔ |
| Needs the external HA URL | no (HA app) | yes (or be on your home Wi-Fi) |

Option A is less work. Option B is useful when your tags are already in use, or when you want the
Shortcut to also open the panel.

---

## ESP32 reader next to the turntable

The integration listens for HA's `tag_scanned` event, so any reader that sends it works. This is an
ESP32 with a **PN532** module over I²C (more reliable than the RC522) running ESPHome:

```yaml
esphome:
  name: vinyl-nfc

esp32:
  board: esp32dev

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

api:
logger:

i2c:
  sda: GPIO21
  scl: GPIO22
  scan: true

pn532_i2c:
  update_interval: 500ms
  on_tag:
    then:
      - homeassistant.tag_scanned: !lambda 'return x;'
```

To pair a record: in the panel, swipe to it, then ⚙ → *NFC tags* → **Scan tag to link**, and lay the
record on the reader. The tag's UID is stored as that record's `tag_id`.

## Option A: Home Assistant Companion app tags (recommended)

1. **Write the tag:** in the HA iPhone app, go to *Settings → Companion App → … → Tags*, or in the HA
   web UI to *Settings → Tags → + Add tag → Write*. Hold the iPhone to the sticker. The tag now
   contains `https://www.home-assistant.io/tag/<uuid>`.
2. **Link it to the album:** open **Vinyl Player**, swipe to the album, then ⚙ → **NFC tags** →
   **Scan tag to link** and scan the tag. The next scan within 90 s is linked to the album in the
   centre instead of playing anything.
3. Done. Each scan fires HA's `tag_scanned` event, and the integration plays the linked record.

Tags that aren't linked fire `vinyl_player_unknown_tag` with the `tag_id`, which you can use in your
own automations.

## Option B: Apple Shortcut

### 1. Get the webhook URL
In the panel: ⚙ → **iPhone Shortcut** shows the URL, for example
`https://your-ha.example.com/api/webhook/8f1c…`. Treat it like a password.

The webhook accepts:

| Body (JSON) | Effect |
|---|---|
| `{"tag": "abbey-road"}` | play the record linked to `abbey-road` |
| `{"release_id": 249504}` | play that Discogs release directly |
| `{"action": "stop"}` | stop |

The reply is JSON, for example `{"ok": true, "artist": "The Beatles", "title": "Abbey Road", …}`.
For an unknown tag it returns HTTP 404 with `{"ok": false}`.

### 2. Create the shortcut "Play Vinyl" (once)

Shortcuts app → **+**:

1. Tap the *ⓘ / Details* → enable **Show in Share Sheet** off, and set **Receive** to **Text** from
   **Shortcuts** (so other automations can pass in the tag name).
2. Action **Get Contents of URL**
   * URL: *your webhook URL*
   * Method: **POST**
   * Request Body: **JSON** → add field `tag` (Text) = **Shortcut Input**
3. Action **Get Dictionary Value** → `ok` from *Contents of URL*. *(optional)*
4. Action **If** *Dictionary Value* is *false* → **Show Notification** "Unknown record". *(optional)*
5. Action **Open URLs** → `homeassistant://navigate/vinyl-player`
   (this opens the panel in the HA app, and you watch the record drop onto the platter).
6. Name it **Play Vinyl**.

### 3. One automation per record

Shortcuts app → **Automation → + → NFC → Scan** → hold the iPhone to the sticker and give it a
name, for example `abbey-road`.

* **Run Immediately** (no confirmation prompt)
* Action **Run Shortcut** → *Play Vinyl*, with input **Text** `abbey-road`

### 4. Link the name to the album
In the panel, swipe to the album, then ⚙ → **NFC tags**, type `abbey-road` into the tag field and
press **Link**. You can also use a service call:

```yaml
action: vinyl_player.link_tag
data:
  tag_id: abbey-road
  release_id: 249504
```

### Test without a phone

```bash
curl -X POST -H 'Content-Type: application/json' \
     -d '{"tag":"abbey-road"}' https://your-ha.example.com/api/webhook/<id>
```

## Tips

* Put the sticker on the *inner* sleeve or the back cover. Metal-backed covers (rare) need on-metal tags.
* NTAG213 stickers are cheap and plenty big. Each one only needs to store a short URL.
* Stick the tags on the outer protective sleeve rather than the cover, so they're easy to replace
  and don't damage the artwork.
* You can manage the full list in the panel. Each link is stored as the record's `tag_id` in
  `<config>/vinyl_player/collection.json` (a string, or a list for several tags). You can also edit
  it there by hand.
