# TopTronic component internals — recent major changes

This document covers the parts of the `toptronic:` component that changed
significantly and are **not** described by the wire-protocol spec. It is aimed at
maintainers and at users running **multi-device** builds.

Companion documents:

| Topic | Document |
|---|---|
| CAN wire protocol (framing, CRC, value layout) | [`hoval_canbus.md`](hoval_canbus.md) |
| Supported devices & default bus addresses | [`devices.md`](devices.md) |
| Capturing a bus dump / replaying it offline | [`candump.md`](candump.md) |

Contents:

1. [Multi-hub entity identity](#1-multi-hub-entity-identity)
2. [CAN receive path: reassembly & start-frame filtering](#2-can-receive-path-reassembly--start-frame-filtering)
3. [Offline diagnostics: candump replay](#3-offline-diagnostics-candump-replay)
4. [Testing & CI coverage](#4-testing--ci-coverage)
5. [Cross-references](#5-cross-references)

---

## 1. Multi-hub entity identity

`MULTI_CONF = true`: declare one `toptronic:` hub per physical device. Each hub
loads the presets of its `device_type` and generates all of that device's
entities. Nothing in this section changes single-hub builds.

### 1.1 Node addressing

A hub is identified by the triple `(canbus_id, device_type, device_addr)`; on the
wire the node id is `device_type | device_addr` (see [`devices.md`](devices.md)):

| Hub | Node id |
|---|---|
| `WEZ` address 1 | `1` |
| `HV` address 8 | `520` (`512 \| 8`) |
| `BM` address 8 | `1032` (`1024 \| 8`) |

### 1.2 Why prefixes exist

Preset entity names are unique **only within one device type** — `FW` and `WEZ`
both expose `AF1 - outdoor sensor 1`, and every `HV` hub loads the same
`HV_50_0_40651` id. ESPHome validates entity names *and* declared ids
build-wide, so two hubs whose presets collide would otherwise fail to compile.
The component therefore rewrites both the **name** and the **id**.

### 1.3 Automatic name prefix — resolution order

The first matching rule wins:

| Build | Prefix | Example entity name |
|---|---|---|
| one hub | *(none)* | `AF1 - Aussenfühler 1` |
| explicit `name_prefix` | that value | `Floor 1 AF1 - Aussenfühler 1` |
| >1 hub, unique device type | `<TYPE>` | `WEZ AF1 - Aussenfühler 1` |
| >1 hub, repeated device type | `<TYPE> <addr>` | `HV 8 Temperatur Abluft` / `HV 9 …` |
| repeated type+addr, different buses | `<TYPE> <addr> <canbus_id>` | `HV 8 cbus2 Temperatur Abluft` |

Implemented by `_resolve_hub_prefix()` in
`esphome/components/toptronic/__init__.py`.

### 1.4 Name sanitization

ESPHome reserves `/` as a URL path separator (warning in 2026.x, error from
2027.7). `_sanitize_entity_name()` rewrites every `/` to `_` and runs on the
**composed** name — prefix included — so an explicit `name_prefix: "Floor/1"`
becomes `Floor_1 …`.

`_` (not `-`) is used because ESPHome's `sanitize()` maps both `/` and `_` to
`_`, so the computed `object_id` — and therefore the existing Home Assistant
entity — is unchanged.

### 1.5 Unique entity ids for same-type hubs

Presets carry hard-coded ids (e.g. `HV_50_0_40651`). The **first** hub of a type
keeps them verbatim; only an actual collision — i.e. a second same-type hub — is
qualified with the hub's type and address:

```text
first  HV hub (addr 8):  HV_50_0_40651
second HV hub (addr 9):  HV_9_HV_50_0_40651
```

This keeps existing `id(...)` references in your lambdas working for the original
hub while letting same-type hubs compile at all (before this they failed with
`ERROR ID HV_50_0_40651 is already registered`).

When two hubs share both the type **and** the address (only possible on
different CAN buses — the same-bus case is rejected below), the CAN bus id is
appended to the qualifier too, so three or more such hubs still get distinct ids:

```text
HV 8 on cbus_a:  HV_8_cbus_a_HV_50_0_40651
HV 8 on cbus_b:  HV_8_cbus_b_HV_50_0_40651
HV 8 on cbus_c:  HV_8_cbus_c_HV_50_0_40651
```

### 1.6 Validation rules

Two hubs may **not** poll the same device on the same bus. A duplicate
`(canbus_id, device_type, device_addr)` is rejected at config time by
`_validate_hub_uniqueness()`:

```text
Duplicate toptronic hub for HV address 8 on CAN bus 'cbus': each device must be
polled by exactly one hub. Use a distinct device_addr, or name_prefix if the two
buses really differ.
```

Both the single-block (mapping) and list forms of `toptronic:` are accepted.

### 1.7 Worked examples

Single hub — names are left untouched (and object_ids unchanged):

```yaml
toptronic:
  id: tt_wez
  canbus_id: cbus
  device_type: WEZ
  device_addr: 1
  language: en
```

Three hubs of different types → `<TYPE>` prefix:

```yaml
toptronic:
  - {id: tt_wez, canbus_id: cbus, device_type: WEZ, device_addr: 1, language: en}
  - {id: tt_hv,  canbus_id: cbus, device_type: HV,  device_addr: 8, language: en}
  - {id: tt_bm,  canbus_id: cbus, device_type: BM,  device_addr: 8, language: en}
# -> "WEZ …", "HV …", "BM …"
```

Two hubs of the same type → `<TYPE> <addr>` prefix + qualified ids:

```yaml
toptronic:
  - {id: tt_hv_a, canbus_id: cbus, device_type: HV, device_addr: 8, language: en}
  - {id: tt_hv_b, canbus_id: cbus, device_type: HV, device_addr: 9, language: en}
# -> "HV 8 …" / "HV 9 …"  and  ids HV_50_0_40651 / HV_9_HV_50_0_40651
```

Same type+addr on two buses → the bus id is appended automatically
(`"HV 8 cbus_b …"`). A classic ESP32 has a single TWAI controller, so two buses
need hardware that supports it (or an external CAN controller).

Explicit override (sanitized):

```yaml
toptronic:
  - id: tt_sol
    canbus_id: cbus
    device_type: SOL
    device_addr: 16
    language: en
    name_prefix: "Floor/1"      # -> "Floor_1 …"
```

### 1.8 Stability & migration

- A single-hub build is a **no-op**: entity names and object_ids are unchanged.
- Names change only where the build was previously broken (a colliding hub).
- The `/` -> `_` rewrite is object_id-neutral, so HA entities are preserved.

### 1.9 Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ERROR ID <ID> is already registered` | two hubs of the same type (pre-fix) | update the component; ids are qualified automatically |
| `Entity name … already used` / duplicate names | two hubs with colliding preset names | update the component (auto prefix) or set `name_prefix` |
| `Duplicate toptronic hub for … on CAN bus …` | same `(canbus_id, device_type, device_addr)` twice | use a distinct `device_addr`, or `name_prefix` if the buses differ |
| warning about `/` in an entity name | a prefix/name containing `/` | update the component; sanitization covers the prefix |

---

## 2. CAN receive path: reassembly & start-frame filtering

### 2.1 Framing recap

Frames are reassembled exactly as described in
[`hoval_canbus.md`](hoval_canbus.md) §3.5: the first-frame header holds the
**TOTAL** frame count, continuations repeat the message header, the reassembly
key is `(device_id << 8) | msg_header`, the pending map is capped at
`max_pending_messages` (default 32) with LRU eviction, and the trailing two bytes
of a completed message are the CRC-16, validated before dispatch.

### 2.2 Start-frame command filter (`is_toptronic_command()`)

A multi-frame message's first payload byte is its command byte. Besides the
TopTronic commands (`0x40` GET, `0x42` RESPONSE, `0x46` SET, `0x56` extended
RESPONSE) the boiler also emits periodic **register-block** broadcasts that use
the same `0x1F` start-frame form but never send the continuations the reassembler
waits for, e.g.:

```text
0x1F400FFF : 11 40 70 A1 00 01 52 08     <- 0x70 register block
0x1F400FFF : 11 5C 74 04 FF 00 00 00     <- 0x74 register block
```

In the issue-#41 capture (2 minutes of traffic) there were ~79 such frames. Each
one used to occupy a slot in `pending_messages_` until the stale sweep and could
evict a real in-progress datapoint response before its continuation arrived.
`parse_frame()` now rejects a start frame whose first payload byte is not a
TopTronic command (`is_toptronic_command()`), so only genuine datapoint responses
enter the reassembler.

### 2.3 Known limitation (continuation header)

Some devices answer datapoints with **extended (`0x56`) multi-frame responses**
(e.g. `11 2D 56 00 00 00 00 F0` for the outdoor sensor). In the captured traffic
those responses' continuation frames carry a header one higher than the start
frame's, so they never complete with the exact-header rule and the datapoint
keeps its previous value (the "wrong value 0 most of the time" symptom of issue
#41).

Pinning this down needs a **`toptronic: DEBUG`** capture (candump off) rather
than raw frames, so the component's own `[RES]` / `[DROP]` / truncation / CRC
lines are visible — see [`candump.md`](candump.md) Step 5 and Part 3 below.

### 2.4 Frame accounting — proving a capture is complete

Every received frame is now **logged** in candump mode (`CANDUMP_MIN_LOG_GAP_MS
= 0`; it is still a tunable constant) and **accounted for** whether or not it is
parsed. Logging *and* accounting are active **only while candump is ON** — every
counter increment is guarded, and with both debug modes off `debug_log_frame()`
returns immediately, so normal operation pays nothing per frame. The counters are
**reset each time candump is enabled**, so `rx` means "frames during this
capture", not since boot. A `[STATS]` record is emitted every 10 s while candump
is ON, and once when it turns OFF:

```text
[STATS] candump running: rx=532 logged=532 throttled=0 | parsed=532 unowned=0 paused=0
[STATS] candump off: rx=721 logged=721 throttled=0 | parsed=700 unowned=18 paused=3 | capture=OK parse=OK
```

Two invariants must hold:

| Check | Invariant | Meaning |
|---|---|---|
| capture | `rx == logged + throttled` | no frame was dropped from the log; `throttled` counts any rate-limited frames |
| parsing | `parsed + unowned + paused == rx` | every frame was parsed, skipped because no hub owns its node, or skipped while paused (OTA) |

The **`candump off`** record is the authoritative one and carries the verdict
inline (`capture=OK` / `capture=LOSSY`, `parse=OK` / `parse=GAP`). `rx`, `logged`
and `throttled` all come from the RX logging callback, so running records are
exact for them; only `parsed` is counted in the receive callback, so a mid-frame
snapshot can differ by one. `throttled` counts frames received while candump was
ON but not written to the log — a rate-limited frame, or the frame that ended the
capture.

`[SKIP] ...` DEBUG lines name the frames that were **not** parsed and why (sender
node owned by no hub; hub paused for OTA), and `tests/replay_candump.py` reads
the `[STATS]` record back — preferring the `candump off` verdict — and flags a
lossy or unaccounted capture.

---

## 3. Offline diagnostics: candump replay

`tests/replay_candump.py` feeds a saved candump through the same framing, CRC and
value-decoding logic as `toptronic.cpp` and prints the parser's view of the
capture — the missing half of a raw-frame log.

```bash
python tests/replay_candump.py my_capture.log --hubs WEZ:1,HV:8,BM:8
```

`--hubs` takes `<device_type>:<device_addr>` pairs and resolves each to the node
id seen on the wire (`device_type | device_addr`, e.g. `HV:8` -> `520`). Aliases
`HKW`->`HK` and `BD`->`BM` are accepted. Options: `--language de|en|fr|it`
(default `de`) and `--timeline` (print every dispatch in capture order).

An unknown device type, a missing preset directory, or two entries resolving to
the same node id is reported as an **error and a non-zero exit** — the tool
refuses to produce diagnostics from a hub map that would silently drop traffic.

Output sections:

| Section | Meaning |
|---|---|
| capture completeness | the firmware `[STATS]` record — `rx == logged + throttled` (capture not truncated) and `parsed + unowned + paused == rx` (every frame accounted for) |
| decoded datapoints | per **(hub node id, fg, fn, dp)** — value, dispatch count, last timestamp |
| drops | `truncated`, `crc_fail`, `no_sensor`, `non_toptronic_start`, `bad_start`, … |
| started but never completed | multi-frame messages still waiting for continuations, with an exact-header / `header+1` hint |
| registered datapoints that NEVER decoded | per-hub issue-#41 shortlist — entities that received no value during the capture, so they keep their previous (usually `0`) value |

Every section is keyed by the hub's **node id**, so two hubs of the same device
type at different addresses are reported separately — one hub's value can never
mask a datapoint that never decoded on the other.

Caveats:

- `multiply` filters are applied, but `lambda`/`clamp` filters are **not** — e.g.
  the device's `0x8000` "invalid" sentinel shows as `-3276.8`, whereas the
  presets map it to `NAN` on-device.
- It mirrors the firmware logic; it is not the firmware. For the firmware's own
  decisions, use a `toptronic: DEBUG` capture.

---

## 4. Testing & CI coverage

| Test | Covers |
|---|---|
| `tests/toptronic_logic_test.py` | CRC-16 (bit-wise + table, 14 captured samples), CAN-ID layout, request builders, continuation-count semantics, and the issue-#41 cases: register-block start-frame rejection, and "a continuation must repeat the start-frame header". |
| `tests/components/toptronic/common.yaml` | Compile-time coverage of the identity rules: `HV` at address 8 **and** 9 (auto prefix + qualified ids), `WEZ`/`HK`/`BM`/`GW`, and `SOL` with `name_prefix: "Floor/1"` (composed-name sanitization). |

Run:

```bash
python tests/toptronic_logic_test.py
esphome compile tests/components/toptronic/test.esp32-idf.yaml
```

CI (`.github/workflows/ci.yml`) runs both plus `pre-commit` lint.

---

## 5. Cross-references

- [`hoval_canbus.md`](hoval_canbus.md) — CAN protocol spec (§3.4 node addressing, §3.5 multi-frame reassembly, §3.6 CRC-16, §7 component behaviour).
- [`devices.md`](devices.md) — device types and default bus addresses.
- [`candump.md`](candump.md) — capture guide, including Step 4b (offline replay).
- [`write_safety.md`](write_safety.md) — SET rate limit and cold-cache guard.
- [`.ai/instructions.md`](../.ai/instructions.md) — single source of truth for code review (component rules, naming).
- Component source: `esphome/components/toptronic/` (`__init__.py`, `toptronic.cpp`), tests in `tests/`.
