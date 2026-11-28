# TopTronic component reference

The `toptronic:` component talks to Hoval TopTronic heating / ventilation devices
over the CAN bus (50 kbps). It is configured once **per device** (device type +
address) and auto-generates all its entities from the bundled presets.

> **Component source:** `config.yaml` loads the component from
> [ESPHome PR #20900](https://github.com/esphome/esphome/pull/20900), and this page
> describes that version. The copy in `esphome/components/toptronic/` is not used,
> and parts of [`docs`](../docs/) still describe it. The PR needs an ESPHome
> development version dated 2026-10-24 or later.
>
> ```yaml
> external_components:
>   - source: github://pr#20900
>     components: [toptronic]
>     refresh: always  # re-fetch on every build; use 1d once validated
> ```

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
| `packages/debug.yaml` | Opt-in raw GET request test button | Only for reverse-engineering |

> The component pauses CAN traffic during OTA updates by itself and generates the
> "Refresh all" button, so there is no per-hub list to maintain.

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
| `id` | no | generated | Hub id. Set it to reference the hub from `toptronic_id` (switches, manual entities). |
| `canbus_id` | no | the only `canbus:` | Id of the `canbus:` component. Must run at **50 kbps**. |
| `device_type` | yes | — | One of `WEZ`, `SOL`, `PS`, `FW`, `HK`, `MWA`, `GLT`, `HV`, `BM`, `GW` (`BD` is accepted as an alias for `BM`). |
| `device_addr` | yes | — | Bus address, `0`–`63` (typical defaults: `HV=8`, `BM=8`, `WEZ=1` — find it on the room control unit). |
| `language` | no | `en` | Preset language: `de`, `en`, `fr`, `it`. |
| `boot_refresh_delay` | no | `30s` | One-shot full refresh after boot; `0s` disables it. |
| `max_pending_messages` | no | `2` | Multi-frame messages reassembled at the same time (per hub), `1`–`16`. |
| `max_pending_age` | no | `5000ms` | A pending message with no continuation frame this long is considered lost. |
| `max_frames_per_message` | no | `8` | Max total frames a start frame may claim, `3`–`31`; larger counts are dropped as corrupted headers. |
| `refresh_interval` | no | `50ms` | Spacing between two GETs of a refresh burst, at least `16ms`. |
| `max_refresh_retries` | no | `1` | Re-sends of an unanswered GET during a refresh burst, `0`–`10`. The regular poll still covers sensors that never answer. |
| `refresh_retry_interval` | no | `200ms` | Delay before an unanswered GET in a burst is re-sent. |
| `write_min_interval` | no | `2s` | Write safety: minimum time between two writes to the **same datapoint**. An earlier write is **rejected** with a warning, not queued. `0s` disables the limit. |
| `reject_writes_before_read` | no | `true` | Write safety: reject a write until its datapoint has answered a read since boot. Datapoints with no read entity are exempt. |

`update_interval` (default `30s`) is not a hub option. It is set on each read-only
entity (`sensor`/`text_sensor`) in the preset files; write entities never poll.

Declare as many hubs as you have devices.

> **Multiple devices:** preset entity names are only unique within one device
> type. When more than one hub is configured, every generated name is prefixed
> with the device type and address (`HV 8: Outside air temp.`). A single hub keeps
> the bare names. The prefix is not configurable.
>
> Two read entities, or two write entities, on the same datapoint of one hub are
> rejected at validation.

---

## Presets

Entities are generated from the YAML files that ship with the component, in
`esphome/components/toptronic/presets/<DEVICE_TYPE>/` of the
[PR](https://github.com/esphome/esphome/pull/20900):

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

`sensors_<lang>.yaml` holds the read-only entities, `inputs_<lang>.yaml` the
writable ones (`number`, `select` and the `text_sensor` a select reads from), and
`buttons_<lang>.yaml` the buttons. A text sensor that only feeds a select is hidden
from Home Assistant. The hub configuration sets the device type and address of
every generated entity.

[`hoval_data_processing`](../hoval_data_processing/readme.md) regenerates the
presets of the **local** component copy:

```bash
python hoval_data_processing/generate_presets.py esphome/components/toptronic/presets
```

The build does not use that copy while `external_components` points at the PR.

### Manual entities

You can also declare entities manually with the `toptronic` platform of `sensor`,
`text_sensor`, `number`, `select` or `button`. Each takes `toptronic_id`,
`function_group`, `function_number` and `datapoint`, plus the platform-specific
options (such as `type`). Read-only entities accept the standard `update_interval`
key (default `30s`).

```yaml
sensor:
  - platform: toptronic
    toptronic_id: toptronic_HV
    name: My datapoint
    function_group: 50
    function_number: 0
    datapoint: 40652
    type: U16
```

---

## Runtime behaviour

- **Polling** — read-only entities (`sensor`/`text_sensor`) extend `PollingComponent`
  and poll at `update_interval` (default `30s`); each poll sends a `GET_REQUEST`
  frame for its datapoint. Write entities (`number`/`select`/`button`) never poll
  — they only send SET_REQUEST frames on user action (and mirror their linked
  read sensor), so they carry no scheduler tick.
- **Post-boot refresh** — `boot_refresh_delay` (default `30s`) after setup, every
  hub that did not disable it is refreshed once.
- **Throttled refresh** — a refresh sends one GET every `refresh_interval`
  (default 50 ms) and retries unanswered ones, so large presets do not saturate the
  50 kbps bus. Each burst logs how many sensors were queued, answered and dropped.
  A burst that makes no progress for about 5 s is abandoned.
- **Multi-frame reassembly** — long responses are reassembled in fixed slots and
  checked with CRC-16. A stale slot is reused when a new message needs it.
- **OTA** — every hub pauses polling, writes and frame processing while an OTA
  update runs, then resumes. No YAML is needed.
- **Refresh button** — the component generates one "Refresh all" button. It
  refreshes every hub, 15 s apart.
- **Debug switches** — `switch.yaml` declares the `candump` and `find_can_id`
  switches of the `toptronic` switch platform. **candump** logs CAN frames (tag
  `candump`), including the gateway's own GET/SET requests; received frames are
  rate limited and the skipped ones counted. **find_can_id** logs the sender of
  received single-frame 0x40/0x42 messages (tag `toptronic`, warning level, also
  routed to the `main_logs` text sensor). Both turn off after two minutes and are
  off after a reboot.

---

## Migration from `legacy`

| Aspect | `legacy` branch | New core |
|---|---|---|
| Device addressing | Per entity (`device_type` + `device_addr` on each sensor/input) | On the hub, once per `toptronic:` block |
| Config | One `toptronic:` block, entities hand-written | Multiple `toptronic:` blocks; entities auto-generated from presets |
| Language | Code only | Presets per language (`de`/`en`/`fr`/`it`) |
| Sender CAN id | Based on `device_type` | Always `GW` (0x481) + `device_addr` — matches gateway behaviour |
| Button support | Not available | `button` platform with `value`/`type` |
| Update trigger | Template button only | Polling + post-boot refresh + generated "Refresh all" button |