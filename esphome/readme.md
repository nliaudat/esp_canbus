# TopTronic component reference

The `toptronic:` component talks to Hoval TopTronic heating / ventilation devices
over the CAN bus (50 kbps). It is configured once **per device** (device type +
address) and auto-generates all its entities from the bundled presets.

> **Note for users of the `legacy` branch** — the core was refactored:
> device addressing moved from each entity to the hub, presets moved into the
> component, and you can now declare multiple `toptronic:` blocks in `config.yaml`.
> See the migration section at the bottom.

---

## Before you start — user-editable files

The firmware is organized as ESPHome packages. Before flashing, customize these
files in the `esphome/` folder (full checklist in the root
[`README.md`](../README.md)):

| File | Purpose | Usually edited? |
|---|---|---|
| `secrets.yaml` | WiFi credentials + fallback AP password (**gitignored**, create it) | **Always** |
| `config.yaml` | `substitutions:` (`name`, `can_tx_pin`, `can_rx_pin`, `board_type`, `TZ`, `toptronic_hubs`) + `toptronic:` hub blocks | **Always** |
| `packages/wifi.yaml` | WiFi network list (`!secret` references) | Almost always |
| `packages/board.yaml` | ESP-IDF, watchdog/sdkconfig, API/OTA | Rarely |
| `packages/canbus.yaml` | 50 kbps `esp32_can` bus + debug candump `on_frame` | Rarely (debug only) |
| `packages/debug.yaml` | Opt-in synthetic-frame test buttons + CRC logging | Only for reverse-engineering |

> ⚠️ Every hub id listed under `toptronic_hubs` must match an `id:` in a
> `toptronic:` block — `board.yaml` OTA pause/resume and `button.yaml`
> refresh-all iterate over that list.

---

## Hub configuration

```yaml
  ### toptronic hubs — used by board.yaml OTA pause/resume and button.yaml refresh all
substitutions:
  name: canbus
  friendly_name: "CanBus Controller"

  ### canbus
  can_tx_pin: "GPIO22"  # GPIO5
  can_rx_pin: "GPIO21"  # GPIO4

  ### board
  board_type: az-delivery-devkit-v4 #nodemcu-32s #esp-wrover-kit

  ### time
  TZ: "Europe/Zurich"  # timezone

  ### toptronic hubs — used by board.yaml OTA pause/resume and button.yaml refresh all
  toptronic_hubs:
    - toptronic_HV
    # - toptronic_BM

toptronic:
  - id: toptronic_HV  # HomeVent
    canbus_id: cbus  # the canbus bit_rate must be 50kbps. do not change name as it used in canbus.yaml
    device_type: HV  # WEZ, HV, BM (BD is an alias for BM and BM must be used)
    device_addr: 8  # defaults are : HV=8, BM=8, WEZ=1
    language: en  # de, en, fr, it

  # - id: toptronic_BM  # display
    # canbus_id: cbus  # the canbus bit_rate must be 50kbps
    # device_type: BM
    # device_addr: 8
    # language: en
```

| Option | Required | Default | Description |
|---|---|---|---|
| `id` | yes | — | Unique hub id (used by `board.yaml` OTA pause/resume and `button.yaml` refresh-all). |
| `canbus_id` | yes | — | Id of the `canbus:` component. Must run at **50 kbps**. |
| `device_type` | yes | — | One of `WEZ`, `SOL`, `PS`, `FW`, `HK`, `MWA`, `GLT`, `HV`, `BM`, `GW` (`BD` is an alias for `BM`; use `BM`). |
| `device_addr` | yes | — | Bus address (typical defaults: `HV=8`, `BM=8`, `WEZ=1` — find it on the room control unit). |
| `language` | no | `en` | Preset language: `de`, `en`, `fr`, `it`. |
| `boot_refresh_delay` | no | `30s` | One-shot full refresh after boot; `0` disables it. |
| `max_pending_messages` | no | `32` | Max concurrently reassembled multi-frame messages (per hub). Raise on a large multi-hub bus. |
| `max_pending_age` | no | `5000ms` | A pending message with no continuation frame this long is considered lost. |
| `cleanup_interval` | no | `5000ms` | Interval between stale-fragment sweeps in `loop()`. |
| `max_refresh_per_loop` | no | `8` | Max sensors refreshed per `loop()` tick in a throttled `update_all()` burst. |
| `max_frames_per_message` | no | `8` | Max total frames a start frame may claim; larger counts are rejected as corrupted headers. |

`MULTI_CONF = true` — declare as many hubs as you have devices.

---

## Presets

Entities are generated from YAML files in
`esphome/components/toptronic/presets/<DEVICE_TYPE>/`:

```
presets/
├── HV/
│   ├── sensors_<lang>.yaml
│   ├── inputs_<lang>.yaml
│   └── buttons_<lang>.yaml
├── BM/
│   └── sensors_<lang>.yaml
└── WEZ/
    ├── sensors_<lang>.yaml
    └── inputs_<lang>.yaml
```

Each file defines the entities of one platform (`sensor`, `text_sensor`, `number`,
`select`, `button`). The `_load_entities()` codegen strips `platform`,
`device_type`, and `device_addr` from each entry — the hub config is authoritative.

To regenerate or extend presets, see
[`hoval_data_processing`](../hoval_data_processing/readme.md):

```bash
python hoval_data_processing/generate_presets.py esphome/components/toptronic/presets
```

### Manual entities

You can also declare entities manually instead of relying on a preset, using the
same keys as the preset files (`function_group`, `function_number`, `datapoint`,
plus the platform-specific options).

---

## Runtime behaviour

- **Polling** — every entity extends `PollingComponent` (default `30s`); each poll
  sends a `GET_REQUEST` frame for its datapoint.
- **Post-boot refresh** — `boot_refresh_delay` (default `30s`) after setup the hub
  fires a one-shot `update_all()` to catch values that changed while the CAN
  gateway was settling; `0` disables it.
- **Throttled refresh** — `update_all()` enqueues sensors and `loop()` releases at
  most `max_refresh_per_loop` (default 8) per tick, so large presets do not
  saturate the 50 kbps bus with a burst.
- **Multi-frame reassembly** — long responses (U32/S32/S64) are reassembled with
  CRC-16 validation (lookup-table accelerated); stale fragments are evicted after
  `max_pending_age` (default 5 s) by the throttled `loop()` sweep.
- **OTA** — `board.yaml` calls `pause()` / `resume()` on every hub during OTA so
  frame processing does not starve the update path.
- **Refresh button** — `button.yaml` provides a "Refresh all" button that calls
  `update_all()` on every hub.
- **Thread-safe command bridge** — `request_refresh()`, `request_pause()`,
  `request_resume()` may be called from any FreeRTOS task; they enqueue a command
  that the main loop task executes (no blocking, no data races).

---

## Migration from `legacy`

| Aspect | `legacy` branch | New core |
|---|---|---|
| Device addressing | Per entity (`device_type` + `device_addr` on each sensor/input) | On the hub, once per `toptronic:` block |
| Config | One `toptronic:` block, entities hand-written | Multiple `toptronic:` blocks; entities auto-generated from presets |
| Language | Code only | Presets per language (`de`/`en`/`fr`/`it`) |
| Sender CAN id | Based on `device_type` | Always `GW` (0x481) + `device_addr` — matches gateway behaviour |
| Button support | Not available | `button` platform with `value`/`type` |
| Update trigger | Template button only | `update_all()` + 30 s post-boot `set_timeout` + thread-safe `request_*()` bridge |