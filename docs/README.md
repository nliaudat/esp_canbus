# Documentation

Reverse-engineering notes, protocol specification, and review references for the
ESP32 CAN bus firmware and the Hoval TopTronic integration.

## Documents

| Document | Purpose |
|---|---|
| [`hoval_canbus.md`](hoval_canbus.md) | **Protocol specification** — CAN identifier layout, single/multi-frame formats, message layout, value types, CRC-16 parameters + validation samples, device-type table, and component behaviour notes. |
| [`catch_crc.md`](catch_crc.md) | **CRC reverse-engineering guide** — step-by-step process used to identify the multi-frame CRC-16 (collect samples with debug logging, analyse with RevEng, implement in `toptronic.cpp`). |
| [`candump.md`](candump.md) | **Candump capture guide** — how to log every CAN frame on the bus using the "candump debug" switch (with "find can_id debug" for addresses), superseding the old `on_frame` handler in `esphome/packages/canbus.yaml`. |
| [`crc_find.py`](crc_find.py) | **CRC search tool** — brute-force Python script that reverse-engineers the polynomial/init/reflection from the captured XOR-difference samples. See `catch_crc.md` for context. |
| [`candump_base.log`](candump_base.log) | **Reference bus capture** — annotated candump + toptronic debug showing single-frame GET/RES, `0x42` and `0x56` multi-frame reassembly (TOTAL frame count), 0x56 extended responses (cleaning/maint. counters), unknown traffic, and loop-latency notes. |
| [`candump_party_mode.log`](candump_party_mode.log) | **Party mode (undocumented)** -- decoded SET frames: duration 0x07DA (hours x 10) + power 0x9F0A (percent). |

## For later review — quick orientation

- **Component source**: `esphome/components/toptronic/`
  - `toptronic.cpp` / `toptronic.h` — hub logic: CAN ID building, GET/SET
    framing, multi-frame reassembly + CRC, `update_all()`, OTA pause/resume,
    and the thread-safe FreeRTOS command bridge (`request_refresh()`,
    `request_pause()`, `request_resume()`).
  - `__init__.py` + platform `*.py` (`sensor`, `text_sensor`, `number`,
    `select`, `button`) — ESPHome config schemas and codegen.
  - `presets/<DEVICE_TYPE>/{sensors,inputs,buttons}_<lang>.yaml` — auto-loaded
    entity definitions per device type and language.
- **Preset / datapoint generation**: `hoval_data_processing/`
- **Main firmware config**: `esphome/config.yaml` (multiple `toptronic:` hubs)
- **README**: [`../README.md`](../README.md) — project overview and the
  "new core version" refactor note (legacy branch link included).

## Key numbers worth remembering

| Constant | Value | Meaning |
|---|---|---|
| Bit rate | 50 kbps | CAN bus speed required by the protocol |
| `GATEWAY_DEVICE_TYPE` | `1153` (GW) | Gateway node id used on outgoing frames |
| `MAX_PENDING_MESSAGES` | 32 | Cap on concurrent multi-frame reassembly buffers |
| `MAX_PENDING_AGE_MS` | 5000 | Stale-fragment expiry in `loop()` |
| `CLEANUP_INTERVAL_MS` | 5000 | Throttle for the stale sweep |
| Poll default | 30 s | Entity `PollingComponent` interval |
| Post-boot refresh | 30 000 ms | One-shot `update_all()` after `setup()` (config `boot_refresh_delay`, `0` = off) |
| Throttled refresh | 50 ms / GET | One GET per `refresh_gap_ms` (default `50ms`); `max_refresh_per_loop` retained as a no-op |
| CRC-16 | poly `0x1021`, init `0xB006`, ref in/out `true`, xorout `0` | Multi-frame checksum (lookup-table form) |
| `0x56` value offset | 7 | Extended RESPONSE value starts at byte 7 (2 extra `0x80 0x00` bytes) |

## Testing

- `tests/toptronic_logic_test.py` — known-answer tests for the protocol logic
  (CRC-16 bit-wise + table form against 14 captured samples, CAN-ID layout,
  request builders, continuation-count semantics). Run with:
  `python tests/toptronic_logic_test.py`
- CI (`.github/workflows/ci.yml`) runs the logic tests, `pre-commit` lint, and
  `esphome compile` for the component test config and `esphome/config.yaml`.
