# TopTronic component reference

The `toptronic:` component talks to Hoval TopTronic heating / ventilation devices
over the CAN bus (50 kbps). It is configured once **per device** (device type +
address) and auto-generates all its entities from the bundled presets.

> **Note for users of the `legacy` branch** — the core was refactored:
> device addressing moved from each entity to the hub, presets moved into the
> component, and you can now declare multiple `toptronic:` blocks in `config.yaml`.
> See the migration section at the bottom.

---

## Hub configuration

```yaml
toptronic:
  - id: toptronic_HV             # unique id, referenced by lambdas / substitutions
    canbus_id: cbus              # the canbus component id (bit_rate: 50kbps)
    device_type: HV              # WEZ, SOL, PS, FW, HK, MWA, GLT, HV, BM, GW
    device_addr: 8               # bus address of the device
    language: en                 # preset language: de, en, fr, it
    use_canbus_callback: true    # true → internal canbus callback; false → route via canbus on_frame
```

| Option | Required | Default | Description |
|---|---|---|---|
| `id` | yes | — | Unique hub id (used by `board.yaml` OTA pause/resume and `button.yaml` refresh-all). |
| `canbus_id` | yes | — | Id of the `canbus:` component. Must run at **50 kbps**. |
| `device_type` | yes | — | One of `WEZ`, `SOL`, `PS`, `FW`, `HK`, `MWA`, `GLT`, `HV`, `BM`, `GW` (`BD` is an alias for `BM`; use `BM`). |
| `device_addr` | yes | — | Bus address (typical defaults: `HV=8`, `BM=8`, `WEZ=1` — find it on the room control unit). |
| `language` | no | `en` | Preset language: `de`, `en`, `fr`, `it`. |
| `use_canbus_callback` | no | `true` | When `false`, frames are routed through the canbus `on_frame` trigger instead of the internal callback. |

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
- **Post-boot refresh** — 30 s after setup the hub fires a one-shot `update_all()`
  to catch values that changed while the CAN gateway was settling.
- **Multi-frame reassembly** — long responses (U32/S32/S64) are reassembled with
  CRC-16 validation; stale fragments are evicted after 2 s by the throttled
  `loop()` sweep.
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