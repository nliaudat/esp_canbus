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
| `config.yaml` | `substitutions:` (`name`, `can_tx_pin`, `can_rx_pin`, `board_type`, `TZ`) + `toptronic:` hub blocks | **Always** |
| `packages/wifi.yaml` | WiFi network list (`!secret` references) | Almost always |
| `packages/board.yaml` | ESP-IDF, watchdog/sdkconfig, API/OTA | Rarely |
| `packages/canbus.yaml` | 50 kbps `esp32_can` bus | Rarely |
| `packages/debug.yaml` | Opt-in synthetic-frame test buttons + CRC logging | Only for reverse-engineering |

> The refresh button and the OTA pause/resume lambdas call fan-out methods
> (`refresh_all()` / `request_pause_all()` / `request_resume_all()`), so they
> work with any hub id and any number of hubs — no per-hub list to maintain.

---

## Hub configuration

```yaml
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

toptronic:
  - id: toptronic_HV  # HomeVent
    canbus_id: cbus  # the canbus bit_rate must be 50kbps. do not change name as it used in canbus.yaml
    device_type: HV  # WEZ, SOL, PS, FW, HK, MWA, GLT, HV, BM, GW (BD is an alias for BM and BM must be used)
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
| `id` | yes | — | Unique hub id (used by `board.yaml` OTA pause/resume and the auto-generated refresh-all button). |
| `canbus_id` | yes | — | Id of the `canbus:` component. Must run at **50 kbps**. |
| `device_type` | yes | — | One of `WEZ`, `SOL`, `PS`, `FW`, `HK`, `MWA`, `GLT`, `HV`, `BM`, `GW` (`BD` is an alias for `BM`; use `BM`). |
| `device_addr` | yes | — | Bus address (typical defaults: `HV=8`, `BM=8`, `WEZ=1` — find it on the room control unit). |
| `language` | no | `en` | Preset language: `de`, `en`, `fr`, `it`. |
| `boot_refresh_delay` | no | `30s` | One-shot full refresh after boot; `0` disables it. |
| `max_pending_messages` | no | `32` | Max concurrently reassembled multi-frame messages (per hub). Raise on a large multi-hub bus. |
| `max_pending_age` | no | `5000ms` | A pending message with no continuation frame this long is considered lost. |
| `cleanup_interval` | no | `5000ms` | Interval between stale-fragment sweeps in `loop()`. |
| `max_refresh_per_loop` | no | `8` | GET burst budget per `refresh_gap_ms` window. Combined with `refresh_gap_ms` it sets the effective per-GET spacing (`refresh_gap_ms / max_refresh_per_loop`). |
| `max_frames_per_message` | no | `8` | Max total frames a start frame may claim; larger counts are rejected as corrupted headers. |
| `refresh_gap_ms` | no | `50ms` | Refresh window length. The burst budget (`max_refresh_per_loop`) GETs are spread across it; effective spacing = `refresh_gap_ms / max_refresh_per_loop` (default 6.25 ms), keeping responses interleaved so the main loop is not swamped. |
| `max_refresh_retries` | no | `0` | Re-sends of an unanswered GET during a refresh burst (`0` = single-pass, no retries; the normal 30 s poll is the backstop). |
| `refresh_retry_interval_ms` | no | `200ms` | Wall-clock delay before an unanswered GET in a burst is re-sent (only used when `max_refresh_retries` > 0). |
| `write_min_interval` | no | `2s` | Write-safety: minimum spacing between two SET requests to the **same datapoint**; faster writes are ignored and logged at WARN. `0` disables the rate limit. |
| `reject_writes_before_read` | no | `true` | Write-safety (cold-cache guard): reject a SET until that datapoint has delivered at least one RESPONSE since boot, so the gateway never writes blind. Datapoints with no read sensor (e.g. the filter-maintenance button) are exempt. |
| `update_interval` | no | `30s` | Polling interval for the read-only entities (`sensor`/`text_sensor`) generated from this hub's presets; each poll sends a GET_REQUEST. Entity-level key (configured in the preset files), not a hub configuration key — write entities never poll. |

`MULTI_CONF = true` — declare as many hubs as you have devices.

---

## Presets

Entities are generated from YAML files in
`esphome/components/toptronic/presets/<DEVICE_TYPE>/`:

```
presets/
├── WEZ/
│   ├── sensors_<lang>.yaml
│   └── inputs_<lang>.yaml
├── SOL/
│   ├── sensors_<lang>.yaml
│   └── inputs_<lang>.yaml
├── PS/
│   ├── sensors_<lang>.yaml
│   └── inputs_<lang>.yaml
├── FW/
│   ├── sensors_<lang>.yaml
│   └── inputs_<lang>.yaml
├── HK/
│   ├── sensors_<lang>.yaml
│   └── inputs_<lang>.yaml
├── MWA/
│   └── sensors_<lang>.yaml
├── GLT/
│   └── sensors_<lang>.yaml
├── HV/
│   ├── sensors_<lang>.yaml
│   ├── inputs_<lang>.yaml
│   └── buttons_<lang>.yaml
├── BM/
│   └── sensors_<lang>.yaml
└── GW/
    └── sensors_<lang>.yaml
```

Supported device types: `WEZ` heat generator, `SOL` solar module, `PS` buffer storage tank,
`FW` district heating, `HK` heating circuit, `MWA` energy meter module, `GLT` building
management system (BMS), `HV` HomeVent ventilation, `BM` control module / display (`BD` is
an alias for `BM`), and `GW` Modbus/KNX gateway. `BM`, `GLT`, `GW` and `MWA` presets are
read-only (sensors only); the others also expose writable inputs, and `HV` additionally
exposes buttons.

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
plus the platform-specific options). Read-only entities accept the standard
`update_interval` key (default `30s`); write entities ignore it.

---

## Runtime behaviour

- **Polling** — read-only entities (`sensor`/`text_sensor`) extend `PollingComponent`
  and poll at `update_interval` (default `30s`); each poll sends a `GET_REQUEST`
  frame for its datapoint. Write entities (`number`/`select`/`button`) never poll
  — they only send SET_REQUEST frames on user action (and mirror their linked
  read sensor), so they carry no scheduler tick.
- **Post-boot refresh** — `boot_refresh_delay` (default `30s`) after setup the hub
  fires a one-shot `update_all()` to catch values that changed while the CAN
  gateway was settling; `0` disables it.
- **Throttled refresh** — `update_all()` enqueues sensors and `loop()` spreads
  `max_refresh_per_loop` GETs (default 8) across each `refresh_gap_ms` window
  (default 50 ms), so the effective per-GET spacing is
  `refresh_gap_ms / max_refresh_per_loop` (default 6.25 ms). Large presets do
  not saturate the 50 kbps bus and the boiler's responses come back interleaved
  instead of as a single main-loop-stalling avalanche. Both knobs drive the
  refresh throughput.
- **Refresh-burst monitoring** - every `update_all()` burst logs a completion
  summary (`N queued, A answered, D dropped`). If a burst ever stops making
  progress for > 5 s (no GETs sent, no responses), `loop()` aborts it so the
  next refresh can start fresh instead of wedging the queue.
- **Multi-frame reassembly** — long responses (U32/S32/S64) are reassembled with
  CRC-16 validation (lookup-table accelerated); stale fragments are evicted after
  `max_pending_age` (default 5 s) by the throttled `loop()` sweep.
- **OTA** — `board.yaml` calls `pause()` / `resume()` on every hub during OTA so
  frame processing does not starve the update path.
- **Refresh button** — the component auto-generates one "Refresh all" button
  (`TopTronicRefreshButton`). Pressing it calls `refresh_all()`, which fans out
  to every hub and staggers each hub's batch by 15 s.
- **Debug switches** — `switch.yaml` provides two on/off toggles: **"candump
  debug"** logs every CAN frame (tag `candump`, including the gateway's own
  GET/SET request frames) and **"find can_id debug"** logs
  only 0x42/0x40 frames (tag `toptronic` WARN, also routed to the `main_logs`
  text sensor). Both reset to OFF on reboot and must not be left on permanently;
  they supersede the old commented `on_frame` blocks in `canbus.yaml`.
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