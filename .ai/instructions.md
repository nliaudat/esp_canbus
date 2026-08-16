# ESP32 CANBus (Hoval TopTronic) — AI Collaboration Guide

**Repository:** https://github.com/nliaudat/esp_canbus
**Primary Goal:** ESP32 CAN bus shield bridging Hoval TopTronic devices (HomeVent/HV, Heat Generator/WEZ, Control Module/BM) to ESPHome and Home Assistant
**License:** Creative Commons CC-BY-NC-SA 4.0 (non-commercial, share-alike)
**Target Board:** ESP32-WROOM-32D / ESP32-WROOM-32U (classic ESP32, `az-delivery-devkit-v4`)
**Framework:** ESPHome `external_components` + ESP-IDF (`esp32_can` platform)
**ESPHome Version:** 2026.7.0+
**CAN Bus:** 50 kbps, 29-bit extended identifiers

**⚠️ When this file changes, `.ai/instructions.yaml` MUST be regenerated.**
The YAML file is the token-optimized machine-readable derivative used by AI tooling.

---

## 📋 TABLE OF CONTENTS

1. [Project Overview](#1-project-overview)
2. [Repository Architecture](#2-repository-architecture)
3. [TopTronic CAN Protocol (CRITICAL)](#3-toptronic-can-protocol-critical)
4. [Component Rules](#4-component-rules)
5. [C++ Standards & Style](#5-c-standards--style)
6. [Python Component & Codegen Rules](#6-python-component--codegen-rules)
7. [Configuration Schema Patterns](#7-configuration-schema-patterns)
8. [YAML Config & Presets](#8-yaml-config--presets)
9. [Memory & Performance](#9-memory--performance)
10. [Security & Protocol Safety](#10-security--protocol-safety)
11. [Testing Requirements](#11-testing-requirements)
12. [Common Anti-Patterns (REJECT)](#12-common-anti-patterns-reject)
13. [Review Priorities](#13-review-priorities)
14. [AI-Specific Instructions](#14-ai-specific-instructions)

---

## 1. PROJECT OVERVIEW

This project is a hardware + firmware project:

- **PCB shield** (`pcb/`) for ESP32 devkits (1000/900 mil) with an SN65HVD230 CAN transceiver, powered from the CAN 12V bus.
- **ESPHome component** (`esphome/components/toptronic/`) implementing the Hoval **TopTronic** CAN protocol (GET/SET/response datapoints over 50 kbps CAN).
- **Preset generation tooling** (`hoval_data_processing/`) that derives entity YAML from the Hoval `TTE-GW-Modbus-datapoints.xlsx` workbook.
- **Example firmware** (`esphome/config.yaml` + `esphome/src/*.yaml`) using ESPHome packages, OTA, API, web server and a weekly reboot.

**Key Characteristics:**

- **Single-board classic ESP32** — NOT ESP32-S3. No TFLite, no camera, no PSRAM requirements.
- **ESP-IDF only** (`framework: type: esp-idf` in `board.yaml`).
- **Dual constraint:** the firmware is both a *component library* (for other users' configs) and a *concrete device* config.
- **Non-commercial license:** CC BY-NC-SA 4.0 — derivatives must stay BY-NC-SA.
- **Protocol knowledge is the core asset** — the TopTronic message layout, CRC-16, and multi-frame framing (§3) are reverse-engineered and MUST NOT be changed casually.

**This file is the SINGLE SOURCE OF TRUTH for all code reviews.**
Generic ESPHome/C++ advice is OVERRIDDEN by the rules below.

---

## 2. REPOSITORY ARCHITECTURE

```
esp_canbus/
├── esphome/
│   ├── config.yaml                    # Main entrypoint: toptronic hubs + packages
│   ├── src/                           # ESPHome packages (wifi/board/time/canbus/...)
│   │   ├── board.yaml                 # esp32: esp-idf, sdkconfig, logger, api, ota
│   │   ├── canbus.yaml                # esp32_can platform, 50kbps
│   │   ├── wifi.yaml / time.yaml / sensors_others.yaml / switch.yaml / debug.yaml
│   └── components/toptronic/          # External ESPHome component (AUTO_LOAD'd platforms)
│       ├── __init__.py                # Hub schema, preset loading, entity generation
│       ├── toptronic.h / toptronic.cpp# Hub + entity classes, CAN protocol
│       ├── sensor.py / number.py / select.py / text_sensor.py
│       └── presets/{WEZ,HV,BM}/       # Generated entity YAML per language (de/en/fr/it)
├── hoval_data_processing/             # Preset generator (NOT shipped as component)
│   ├── generate_presets.py            # CLI: preset definitions + patch hooks
│   ├── xls_parser.py                  # xlsx → Datapoint → entity YAML
│   └── TTE-GW-Modbus-datapoints.xlsx  # Hoval datapoint workbook (source of truth)
├── pcb/                               # KiCad schematics, 3D view, wiring photo
├── tests/components/toptronic/        # ESPHome build tests (common.yaml + platform yaml)
├── .clang-format .clang-tidy .flake8 .yamllint .pre-commit-config.yaml
├── README.md                          # User-facing firmware guide
└── licence.md                         # CC BY-NC-SA 4.0
```

### 2.1 Dataflow

```
xlsx workbook ──xls_parser.py──▶ Datapoint list ──generate_presets.py──▶ presets/{WEZ,HV,BM}/*.yaml
presets/*.yaml ──toptronic/__init__.py (_load_entities)──▶ entity schemas (sensor/number/select/text_sensor)
user YAML (toptronic: hub blocks) + entity schemas ──codegen──▶ generated C++ (TopTronic + entities)
CAN bus (50kbps) ──esphome esp32_can──▶ TopTronic::parse_frame() ──reassembly/CRC──▶ publish_state()
```

### 2.2 Key Files & Ownership

| Path | Role | Notes |
|------|------|-------|
| `esphome/components/toptronic/__init__.py` | Hub schema + codegen | `MULTI_CONF = True`, `DEPENDENCIES = ["canbus"]`, `AUTO_LOAD = ["sensor","number","select","text_sensor"]` |
| `toptronic.h/.cpp` | C++ protocol engine | single `TopTronic` hub, `TopTronicBase` entities, CRC, multi-frame |
| `sensor.py`/`text_sensor.py` | Read-only entities | schema extends `CONFIG_SCHEMA_BASE` |
| `number.py`/`select.py` | Writable entities | SET requests, multiplier / option mapping |
| `presets/` | Generated files | **Do not hand-edit** — regenerate via `generate_presets.py` |
| `hoval_data_processing/` | Source-of-truth tooling | Python `openpyxl` + yaml dump with LF endings |
| `tests/components/toptronic/` | Build tests | `common.yaml` + `test.esp32-idf.yaml` |

---

## 3. TOPTRONIC CAN PROTOCOL (CRITICAL)

The TopTronic protocol is reverse-engineered and the codebase's core value. Do not change framing, addressing, or CRC without explicit human approval and bus-capture evidence.

### 3.1 Bus Parameters

- Bit rate: **50 kbps** (`bit_rate: 50kbps` in `canbus.yaml`). Do not change.
- **29-bit extended CAN IDs** (`use_extended_id: true` style framing; `send_data(can_id, true, ...)`).
- Half-duplex: one gateway node issues GET/SET; devices respond with RESPONSE frames.

### 3.2 Extended CAN ID Layout

```
bits 28-22 : 0x7F fixed priority/type marker (msg_id)
bits 21-11 : sender node ID
bits 10-0  : receiver node ID (or broadcast mask)

build_can_id(sender_id, receiver_mask) = (0x7F << 22) | (sender_id << 11) | receiver_mask
```

- `msg_id = can_id >> 24` — used to distinguish start-of-message (`0x1f`) from continuation frames.
- `device_id = (can_id >> 11) & 0x7FF`.
- Outgoing requests use `build_can_id(GATEWAY_DEVICE_TYPE | device_addr_, get_device_id())`.

### 3.3 Command Bytes & Message Layout

| Byte | Value | Meaning |
|------|-------|---------|
| cmd  | `0x40` | GET request (read a datapoint) |
| cmd  | `0x46` | SET request (write a datapoint) |
| cmd  | `0x42` | RESPONSE (device answering a GET/SET) |

Message layout **after** CAN framing bytes are stripped:

```
[0] cmd            [1] function_group   [2] function_number
[3] datapoint high [4] datapoint low    [5..] value payload (big-endian)
```

- Sensor lookup key: `id = function_group + (function_number << 8) + (datapoint << 16)`.
- Long SET payloads may exceed 8 bytes (U32/S32 = 10, S64 = 14) and MUST be split into multiple frames.

### 3.4 Device Types & Addressing

| Name | ID | Meaning | Default addr |
|------|-----|---------|-------------|
| WEZ  | 0    | Heat generator | 1 |
| SOL  | 64   | Solar module | — |
| PS   | 128  | Buffer storage tank | — |
| FW   | 192  | District heating | — |
| HK   | 256  | Heating circuit | — |
| MWA  | 384  | Energy meter module | — |
| GLT  | 448  | Building mgmt system (BMS) | — |
| HV   | 512  | HomeVent ventilation | 8 |
| BM/BD | 1024 | Control module (display) — **BD is an alias; use BM** | 8 |
| GW   | 1153 | Gateway (Modbus/KNX) — also used for this ESP32 node on the bus | — |

`get_device_id() = device_type | device_addr` (e.g. HV addr 8 → 520).

### 3.5 Multi-Frame Reassembly

- **Single-frame:** first byte of frame payload is `0x01` (length/flags). `num_remaining = data[0] >> 3 == 0` → interpret immediately, skipping byte 0.
- **Start frame** (`msg_id == 0x1f`): `[frame_count<<3 | 0x01, msg_header, payload[0..5]]` — up to 6 payload bytes. `frame_count` (upper 5 bits of byte 0) = number of continuation frames expected. Reassembly key = `(device_id << 8) | msg_header`.
- **Continuation frames** (any other `msg_id`, i.e. bits 28-22 cleared): `[msg_header, payload[6..12], ...]` — up to 7 payload bytes per frame.
- **Bounded buffer:** `MAX_PENDING_MESSAGES = 16`. When full and a *new* start frame arrives, the whole pending map is cleared (stale-fragment heuristics).
- **Stale expiry:** pending entries older than `MAX_PENDING_AGE_MS = 2000` ms are evicted by a throttled sweep in `loop()` (`CLEANUP_INTERVAL_MS = 2000`).
- **Completion:** when `remaining_frames` hits 0, the last 2 bytes of the reassembled payload are the CRC-16 (big-endian).

### 3.6 CRC-16

```
Class: CRC-16/ARC family (non-standard init)
poly  = 0x1021
init  = 0xB006
refin = true   refout = true   xorout = 0x0000
```

- Computed over the reassembled message payload **excluding** the trailing 2 CRC bytes.
- On receive, mismatch → drop message, log `"CRC check failed!"`, do NOT dispatch.
- Parameters were identified by brute-force search against captured bus traffic — do not change.

### 3.7 GET / SET Flow

- **GET:** `build_get_request(fg, fn, dp)` = `{0x01, 0x40, fg, fn, dp_hi, dp_lo}`. Sent on each entity's polling interval (`polling_component_schema("30s")` per-entity) from `update()` callbacks.
- **SET (number/select):** `control()` builds `build_set_request(fg, fn, dp, value_bytes)` = `{0x01, 0x46, fg, fn, dp_hi, dp_lo, ...value}` and dispatches via `set_callback_`. `send_can_frames()` splits payloads > 8 bytes.
- **Response:** device answers with RESPONSE `0x42`; `interpret_message()` matches `rx_device_id` + reconstructed key to a registered entity and calls `publish_state()`.
- Self-echoed GET/SET frames (from the bus) are logged and ignored (never dispatched).

---

## 4. COMPONENT RULES

### 4.1 Hub — `TopTronic` (root component)

**✅ REQUIRED:**
- Own the device map with `std::unique_ptr<TopTronicDevice>` (no raw owning pointers, no leaks).
- Register CAN callback exactly once in `setup()`.
- Cache per-entity GET request payloads once at setup (`cache_request_data()`) — never rebuild per poll.
- Use `unordered_map` for `devices_`/`pending_messages_` (O(1) lookup on every received frame).
- Wire input→sensor linking in `setup()` via `link_inputs()` before registering callbacks.
- Keep the stale-pending sweep in `loop()` throttled; do not scan the map every loop iteration.

**❌ BLOCKER:**
- No `new`/`delete` in entity registration paths (use containers + `unique_ptr`).
- No per-frame heap allocation in `parse_frame()` (the hot path).
- No blocking calls inside the CAN callback.
- No RTTI: downcasts MUST use the `SensorType` discriminator + `static_cast`.

### 4.2 Entities — `TopTronicBase` + subtypes

**✅ REQUIRED:**
- `function_group_`, `function_number_`, `datapoint_` validated at schema level (`cv.uint8_t`/`cv.uint16_t`).
- `get_id()` MUST use the canonical packing `fg + (fn << 8) + (dp << 16)` — this IS the map key.
- Read-only entities (`TopTronicSensor`, `TopTronicTextSensor`) implement `parse_value()`; writable entities (`TopTronicNumber`, `TopTronicSelect`) implement `control()`.
- Value↔text option maps (`to_text_`/`to_value_`) MUST stay mirrored — register both directions in ONE place (`add_option()`).
- `TopTronicNumber::control()` applies `multiplier_` (10^decimal) BEFORE encoding to raw bytes.
- `link_inputs()` uses `sensor->add_on_raw_state_callback()` to keep writable entities in sync with the boiler's actual value.

**❌ BLOCKER:**
- Avoid duplicating the inverted value↔text mapping anywhere else in the codebase.
- No hardcoded entity address/type overrides inside entity logic — addressing is owned by the hub.

### 4.3 Shared / helper code

- `bytes_to_number<T>()` accumulates into `uint64_t` to avoid signed-shift UB for `int64_t` — keep this pattern.
- `hex_str()` must stay allocation-friendly (plain `std::string`, SSO, `reserve()`) — it is called on the CAN hot path under DEBUG logging.
- `send_can_frames()` MUST keep the `msg_counter` skip-zero behavior and the `cont_id = can_id & 0x003FFFFF` continuation addressing.

---

## 5. C++ STANDARDS & STYLE

### 5.1 Language Version

Follow the ESPHome toolchain default (gnu++20 on current ESPHome). Do NOT flag modern C++ features as "too modern" — but match what the codebase actually uses (`std::vector`, `std::map`, lambdas, `std::function` callbacks).

### 5.2 Member Access — MANDATORY

**✅ REQUIRED: Prefix ALL class member access with `this->`**

```cpp
// CORRECT
void set_type(TypeName type) { this->type_ = type; }

// WRONG
void set_type(TypeName type) { type_ = type; }
```

### 5.3 Naming Conventions

| Item | Convention | Example |
|------|------------|---------|
| Classes/Structs/Enums | `UpperCamelCase` | `TopTronic`, `TypeName` |
| Enum constants | `UPPER_SNAKE_CASE` | `U8`, `S16` |
| Functions/Methods | `lower_snake_case` | `parse_frame()`, `get_id()` |
| Variables | `lower_snake_case` | `can_id`, `datapoint` |
| Top-level constants | `UPPER_SNAKE_CASE` | `MAX_PENDING_MESSAGES` |
| File-local constants | `lower_snake_case` | `constexpr size_t min_message_len` |
| Members | `lower_snake_case_` (trailing underscore) | `function_group_`, `request_data_` |

### 5.4 Constants

**✅ Use `static constexpr` (or `enum`) for constants — NOT `#define`.**

```cpp
// CORRECT
static constexpr size_t MAX_PENDING_MESSAGES = 16;
static constexpr uint32_t MAX_PENDING_AGE_MS = 2000;

// WRONG
#define MAX_PENDING_MESSAGES 16
```

`#define` is acceptable ONLY for conditional compilation flags (`USE_SENSOR`, `USE_TEXT_SENSOR`, `USE_NUMBER`, `USE_SELECT`).

### 5.5 Feature Guards

**✅ REQUIRED — all entity classes/headers MUST be wrapped in their platform guard:**

```cpp
#ifdef USE_SENSOR
class TopTronicSensor : public sensor::Sensor, public TopTronicBase { ... };
#endif
```

`toptronic.h` includes the ESPHome component headers (`sensor/sensor.h`, etc.) only inside the matching `#ifdef`. Keep this pattern — it keeps the binary small when platforms are disabled.

### 5.6 Casts

This project's `.clang-tidy` deliberately disables `cppcoreguidelines-pro-type-cstyle-cast`,
`modernize-avoid-c-style-cast`, and `google-readability-casting`, and `.clang-format` sets
`SpaceAfterCStyleCast: true`. C-style casts are therefore **accepted in existing code** and must
NOT be mass-rewritten. In NEW code, prefer `static_cast<>` for clarity.

**❌ BLOCKER (unchanged regardless of style):**
- `reinterpret_cast`/C-style casts that break aliasing rules on the CAN payload.
- Any cast that silently truncates a value type (e.g. `(uint8_t)` on a 16-bit datapoint).

### 5.7 Formatting & Lint Infrastructure

Checks are enforced via pre-commit hooks (`.pre-commit-config.yaml`):

| Tool | Scope | Config |
|------|-------|--------|
| **clang-format** | C/C++ under `esphome/components/` (Google-based: 2-space indent, 120 col, pointer right) | `.clang-format` |
| **flake8** | Python under `esphome/components/` (max-line-length 120) | `.flake8` |
| **yamllint** | YAML under `esphome/` (2-space indent, no document-start marker) | `.yamllint` |

**⚠️ NOTE:** This project has NO `script/ci-custom.py`, NO `script/run_lint.py`, NO `pyproject.toml`, and NO `.editorconfig`. Do not invent or reference them. The only CI-adjacent gates are the pre-commit hooks above and the build tests in `tests/`.

Run:

```bash
pre-commit run --all-files
```

### 5.8 File Encoding & Whitespace

- **LF line endings only** — the repo is shared across Windows/macOS/Linux; preserve `\n`.
- **No trailing whitespace.**
- **EOF: exactly one trailing newline.**
- **Non-ASCII is PERMITTED in this repo** (e.g. `°C` units in preset YAML, French/Italian preset labels, license text). There is NO ASCII-only lint here — unlike some other ESPHome projects. Use UTF-8.
- Preset YAML generated by `xls_parser.py` already uses `newline="\n"` + `encoding="utf-8"`.

---

## 6. PYTHON COMPONENT & CODEGEN RULES

### 6.1 Hub `__init__.py`

```python
from esphome.components.canbus import CanbusComponent
from esphome.core import CORE, ID

CODEOWNERS = ["@nliaudat"]
DEPENDENCIES = ["canbus"]
AUTO_LOAD = ["sensor", "number", "select", "text_sensor"]
MULTI_CONF = True

toptronic = cg.esphome_ns.namespace("toptronic")
TopTronicComponent = toptronic.class_("TopTronic", cg.Component)
TopTronicBase = toptronic.class_("TopTronicBase", cg.PollingComponent)
```

**✅ REQUIRED:**
- Keep `MULTI_CONF = True` — one hub per device on the same bus.
- Device type enum (`DeviceType`) values ARE the wire protocol values — never reorder/reassign without bus-capture evidence.
- `get_device_type()` MUST raise `ValueError` for unknown types and `_validate_preset()` MUST raise `cv.Invalid` for missing preset dirs.
- Resolve preset paths relative to `__file__` (`PRESETS_DIR = pathlib.Path(__file__).parent / "presets"`), NEVER relative to cwd.
- Do NOT filter directory lists by `exists()` at import time — defer existence checks to runtime/validation.
- Entity IDs synthesized from presets bypass the global ID pass — keep `_resolve_ids()` so they get unique IDs and register `Component` declarations in `CORE.component_ids`.

### 6.2 Entity Generation

- `_generate_entities()` loads `presets/<device>/sensors_<lang>.yaml` and `inputs_<lang>.yaml`, strips `platform`/`device_type`/`device_addr`, injects the hub reference, and runs each platform's own schema + codegen.
- All predefined `CONF_*` constants live in `__init__.py` (shared by the four platform files) — do not scatter new constants into `sensor.py`/`number.py`/`select.py`/`text_sensor.py`.
- Platform files import shared pieces (`CONFIG_SCHEMA_BASE`, `CONF_TT_ID`, `CONF_FUNCTION_GROUP`, `CONF_FUNCTION_NUMBER`, `CONF_DATAPOINT`, `TT_TYPE_OPTIONS`) from the package — keep this DRY.

### 6.3 Type Mappings

- `TT_TYPE_OPTIONS` (U8/U16/U32/S8/S16/S32/S64 → `TypeName`) is the ONLY place mapping YAML `type:` to the C++ enum. Do not duplicate inverted mappings elsewhere.

---

## 7. CONFIGURATION SCHEMA PATTERNS

### 7.1 Hub schema

```python
CONFIG_SCHEMA = cv.All(
    cv.Schema({
        cv.GenerateID(): cv.declare_id(TopTronicComponent),
        cv.GenerateID(CONF_CANBUS_ID): cv.use_id(CanbusComponent),
        cv.Required(CONF_DEVICE_TYPE): cv.one_of(*[t.name for t in DeviceType], upper=True),
        cv.Required(CONF_DEVICE_ADDR): cv.uint8_t,
        cv.Optional(CONF_LANGUAGE, default="en"): cv.one_of(*LANGS, lower=True),
    }).extend(cv.COMPONENT_SCHEMA),
    _validate_preset,
)
```

### 7.2 Shared entity base schema

```python
CONFIG_SCHEMA_BASE = cv.Schema({
    cv.Required(CONF_FUNCTION_GROUP): cv.uint8_t,
    cv.Required(CONF_FUNCTION_NUMBER): cv.uint8_t,
    cv.Required(CONF_DATAPOINT): cv.uint16_t,
}).extend(cv.polling_component_schema("30s"))
```

### 7.3 Platform schema rules

**✅ REQUIRED:**
- Bounds-check ALL user inputs: `cv.uint8_t` / `cv.uint16_t` for protocol fields, `cv.float_range(min=0)` for `decimal`, `cv.positive_float` for `step`.
- `number`: `min_value`/`max_value`/`step` required and converted with the `decimal` divider BEFORE `register_number()`.
- `select`/`text_sensor`: `options` (`cv.ensure_list(cv.string_strict)` + `cv.Length(min=1)`) and `values` (`cv.ensure_list(cv.int_)` + `cv.Length(min=1)`) MUST have matching lengths — validate at schema level.
- Report errors by **raising** `cv.Invalid` (never return it).
- Prefer built-in validators (`cv.one_of`, `cv.float_range`, `cv.All`) over custom lambdas.

---

## 8. YAML CONFIG & PRESETS

### 8.1 Hub usage (user config)

```yaml
toptronic:
  - id: tt_HV
    canbus_id: cbus
    device_type: HV   # WEZ, HV, BM (BD alias → use BM)
    device_addr: 8    # defaults: HV=8, BM=8, WEZ=1
    language: en      # de, en, fr, it
```

- The CAN bus `bit_rate` MUST stay 50 kbps (`bit_rate: 50kbps`).
- `secrets.yaml` is gitignored — never commit it.

### 8.2 Presets are generated artifacts

**❌ NEVER hand-edit `presets/**/*.yaml`.** They are generated from `hoval_data_processing` via:

```bash
python hoval_data_processing/generate_presets.py ../esphome/components/toptronic/presets
```

**Workflow for adding/adjusting datapoints:**
1. Edit the preset definition in `generate_presets.py` (or the patch hooks) — NOT the generated YAML.
2. Regenerate with the command above.
3. Verify the diff in `presets/` is exactly the intended entity changes.

**✅ Generated-file rules:**
- Preset YAML uses `newline="\n"`, `encoding="utf-8"`, `sort_keys=False`, custom `_IndentDumper` (indented sequences) — preserve this output style if touching `xls_parser.py`.
- Entity `id` convention: `<DEVICE>_<fg>_<fn>_<dp>` for read-only, `_set` suffix for writable (e.g. `HV_50_0_40651`, `HV_50_0_40651_set`).
- Writable presets become `internal: true` sensors; read+write pairs are linked by the hub (`link_inputs()`).

### 8.3 src/ packages

- `board.yaml`: ESP-IDF framework, `CONFIG_COMPILER_OPTIMIZATION_PERF`, `CONFIG_TASK_WDT*`, `logger` log-level map, `tt: INFO` (use `tt: DEBUG` only for CAN/CRC reverse-engineering via `debug.yaml`).
- **⚠️ canbus log level:** setting the canbus log level BELOW `INFO` may crash (`esphome/issues#4051`) — keep `canbus: ERROR`/`INFO`.
- `debug.yaml` contains test buttons that inject synthetic frames via `id(tt_HV).parse_frame(x, can_id, false)` — useful for entity wiring checks without hardware changes. Keep it opt-in (commented out in `config.yaml`).

---

## 9. MEMORY & PERFORMANCE

**✅ REQUIRED (matches the actual implementation):**

- Allocate/reuse in `setup()`; allocate NOTHING per frame in `parse_frame()` beyond the immutable `PendingMessage` insert (`reserve()` is done once at start-frame time, worst case 16 × 7 × 16 bytes).
- Cache GET request bytes once (`cache_request_data()`), return by `const &` (`get_request_data()`).
- Reuse the pending-message `last_update_ms` timestamp for stale expiry — no extra map.
- Keep the cleanup sweep off the per-loop hot path (throttle to 2 s).
- `hex_str()` stays allocation-free for short messages (SSO) — it runs on the receive hot path at DEBUG level.
- Use `std::map` for option strings (not `unordered_map`) — tiny maps, string hashing not worth it (documented in `toptronic.h`).

**⚠️ AVOID:**
- `std::stringstream` (use plain `std::string` + `push_back`).
- `std::to_string()` + `strtol()` round-trips in the frame path.
- Per-frame `std::vector` `resize()`/`reserve()` churn.

**❌ NEVER:**
- `delay()`/blocking calls in `loop()` or the CAN callback.
- `new`/`delete` in the receive path.
- Unbounded containers sized by untrusted frame data.

---

## 10. SECURITY & PROTOCOL SAFETY

**✅ REQUIRED:**
- Validate `len >= MIN_MESSAGE_LEN (5)` before reading `cmd/fg/fn/dp` bytes in `interpret_message()`.
- Validate frame payload lengths before indexing (`data.size() < 2` checks in `parse_frame()`).
- Verify CRC-16 before dispatching any multi-frame message (single-frame messages carry no CRC).
- Cap the pending-message map at `MAX_PENDING_MESSAGES` and evict stale entries (memory-exhaustion / stale-fragment protection).
- Reject continuation frames for unknown/expired reassembly keys.
- Ignore messages from devices with no registered entities (device-map lookup miss).
- Ignore self-echoed GET/SET frames.
- Treat `datapoint` reconstruction as untrusted input — it is derived from bus data; the map lookup naturally rejects unknown combinations.

**❌ BLOCKER (CVE-class patterns):**
- No `ptr + N` before checking `N` fits in the remaining length.
- No multiplication overflow in buffer-size math (frame math is simple, but keep `field_length > (end - ptr)` style guards).
- No format-string vulnerabilities — always `ESP_LOGD(TAG, "%s", value.c_str())`, never `ESP_LOGD(TAG, value.c_str())`.

---

## 11. TESTING REQUIREMENTS

### 11.1 Build tests

- `tests/components/toptronic/common.yaml` defines the canbus + `toptronic:` hubs (HV + WEZ) with no top-level `esphome:`/`esp32:` blocks.
- `test.esp32-idf.yaml` includes the shared UART package and merges `common.yaml` via `<<: !include common.yaml`.
- Any change to `toptronic/*.py`, `toptronic.h/.cpp`, or `presets/` MUST keep this test compiling:
  ```bash
  esphome compile tests/components/toptronic/test.esp32-idf.yaml
  ```

### 11.2 Lint

- `pre-commit run --all-files` (clang-format, flake8, yamllint) — must pass.
- Flake8 ignores docstring rules (D100–D401) per `.flake8`; do not add new ignores to silence lint findings.

### 11.3 Runtime verification

- On hardware, watch `tt: INFO` logs for `[GET]`/`[SET]`/`[RES]` frames to confirm the entity is polled and decoded.
- For CRC work: enable `tt: DEBUG` + `debug.yaml`, capture ~10 samples, run `reveng -w 16 -s ...` to validate any CRC assumptions before touching `compute_crc16()`.

---

## 12. COMMON ANTI-PATTERNS (REJECT)

### ❌ Missing `this->`

```cpp
// WRONG
void control(float value) { multiplier_ * value; }

// CORRECT
float v = this->multiplier_ * value;
```

### ❌ `#define` Constants

```cpp
// WRONG
#define MAX_PENDING_MESSAGES 16

// CORRECT
static constexpr size_t MAX_PENDING_MESSAGES = 16;
```

### ❌ `delay()` / Blocking in Loop or CAN Callback

```cpp
// WRONG
void loop() override { delay(100); }

// CORRECT — throttled, non-blocking sweep
if (now - this->last_cleanup_ms_ >= CLEANUP_INTERVAL_MS) { ... }
```

### ❌ Per-Frame Heap Allocation

```cpp
// WRONG — rebuilds request bytes on every poll
void update() { auto data = build_get_request(...); canbus_->send_data(can_id, true, data); }

// CORRECT — cached once at setup
const auto &data = sensor->get_request_data();
canbus_->send_data(can_id, true, data);
```

### ❌ Ignoring CRC Before Dispatch

```cpp
// WRONG — dispatches possibly corrupted multi-frame data
if (received_crc == computed_crc) { this->interpret_message(...); }

// CORRECT — drop on mismatch (see §3.6)
if (received_crc != computed_crc) { log + erase; return; }
```

### ❌ Unbounded Reassembly

```cpp
// WRONG — unbounded map growth from bus noise
pending_messages_[header_key] = pending;

// CORRECT — cap + eviction (§3.5)
if (pending_messages_.size() >= MAX_PENDING_MESSAGES && not existing) clear();
```

### ❌ Duplicated Inverted Option Mapping

```cpp
// WRONG — two sources of truth for text↔value
value = {to_text_.at(...)};  // elsewhere: text_to_value_.at(...)

// CORRECT — single add_option() registers both directions
void add_option(uint8_t value, const std::string &text);
```

### ❌ Hand-Editing Generated Presets

```yaml
# WRONG — manual change to presets/HV/sensors_en.yaml
```

Regenerate via `generate_presets.py` (§8.2) instead.

### ❌ Hardcoding Protocol Values in Tests/Helpers

```cpp
// WRONG
uint8_t cmd = 0x42;  // magic number

// CORRECT
static const uint8_t RESPONSE = 0x42;
```

### ❌ Trailing Whitespace / CRLF / Missing EOF Newline

Any of these will fail pre-commit hooks. Keep LF-only, no trailing spaces, exactly one `\n` at EOF.

---

## 13. REVIEW PRIORITIES

### 🔴 BLOCKER (Must fix before merge)

- Missing `this->` on member access
- `#define` constants (non-conditional)
- Memory leaks / manual `new`/`delete` in receive path
- Per-frame heap allocation in `parse_frame()` / `update()`
- CRC or multi-frame regressions (protocol correctness)
- Unvalidated frame lengths before indexing (overflow/CVE pattern)
- Blocking calls in `loop()` or CAN callback
- Format-string vulnerabilities in logging
- Hand-edited `presets/` or schema bypass
- CRLF / trailing whitespace / missing EOF newline

### 🟠 WARNING (Should fix before merge)

- Magic numbers for protocol values (add named constants)
- Rebuild of GET requests per poll instead of `cache_request_data()`
- Reintroducing `std::regex` / `std::stringstream` on the hot path
- Missing schema bounds on user inputs
- Unbounded option maps (should stay bounded per entity)

### 🟡 INFO (Nice to fix)

- Const correctness / include-what-you-use
- Dead or commented-out code
- Naming consistency with §5.3

---

## 14. AI-SPECIFIC INSTRUCTIONS

### 14.1 Mandatory Pre-Read

**BEFORE any analysis or code generation, read this entire file.**
**BEFORE any suggestion, verify no rule is violated.**

### 14.2 License

**CC BY-NC-SA 4.0 — non-commercial, share-alike.**
- No commercial use.
- Derivative work MUST be licensed under the same terms (attribution required).
- Do not introduce code that imposes a different/additional license without human approval.

### 14.3 Preset Regeneration

Never "fix" a generated preset by hand. If a datapoint is wrong, update `generate_presets.py` / `xls_parser.py` and regenerate, then include the regenerated files in the change.

### 14.4 Protocol Sensitivity

The TopTronic framing, CRC, and device-type tables were reverse-engineered. Any proposed change to §3 MUST be backed by captured bus evidence and explicitly approved by a human.

### 14.5 When Uncertain

- **STATE the specific rule being considered**
- **ASK the user to confirm**
- **REFERENCE the section number**

### 14.6 No Unauthorized Commits

**NEVER commit changes without explicit human approval.** Present changes as proposals first.

### 14.7 Communication Style

Output only findings and fixes. Do NOT end with open questions in code comments.

### 14.8 File Output Validation

**BEFORE writing ANY file content, pre-validate the output:**
1. **LF-only line endings** — NO `\r` characters.
2. **No trailing whitespace** — strip trailing spaces/tabs from every line.
3. **No tab characters** — 2-space indentation only.
4. **Exactly one trailing newline at EOF** — ends with `\n`, not `\n\n`.
5. **UTF-8** — non-ASCII content is allowed here (unlike ASCII-only repos), but MUST be valid UTF-8.

This applies to ALL write operations. Violations break pre-commit/CI gates.

### 14.9 Maintenance

When this file changes, `.ai/instructions.yaml` MUST be regenerated (token-optimized derivative).

---

## 📌 SUMMARY: NON-NEGOTIABLE RULES (Cheat Sheet)

| Rule | Standard | Exception |
|------|----------|-----------|
| **Member access** | `this->` prefix | None |
| **Constants** | `constexpr` / `enum` | `#define` only for conditional compilation |
| **Casts** | `static_cast<>` preferred in new code | Existing C-style casts tolerated (clang-tidy disables the checks) |
| **Memory** | RAII / containers | Never `new`/`delete` in receive path |
| **Protocol** | TopTronic framing + CRC-16 (§3) | Never change without bus evidence |
| **Reassembly** | Bounded (16) + stale eviction | Never unbounded |
| **Presets** | Generated via `hoval_data_processing` | Never hand-edited |
| **Blocking** | Throttled non-blocking `loop()` | Never `delay()` in `loop()`/callback |
| **File encoding** | LF, UTF-8, no trailing WS, EOF newline | Non-ASCII allowed (UTF-8) |
| **License** | CC BY-NC-SA 4.0 (non-commercial) | Derivative work must stay BY-NC-SA |

---

**END OF AI COLLABORATION GUIDE**

*This document is the authoritative standard for the esp_canbus repository.*
*Last updated: August 2026*

**⚠️ Maintenance:** When editing this file, also sync `.ai/instructions.yaml`
(token-optimized derivative for AI tooling consumption).
