# Hoval TopTronic CAN bus protocol

Reverse-engineered specification of the CAN protocol spoken by Hoval TopTronic
heating / ventilation devices, as implemented by the `toptronic:` component
(`esphome/components/toptronic/`).

> **Scope** — this document describes the wire format and framing used between
> the ESP32 gateway and the boiler devices (HV / BM / WEZ / ...) at 50 kbps.
> It is maintained for future review and for anyone extending the component or
> the [`hoval_data_processing`](../hoval_data_processing/) preset generator.

---

## 1. Physical layer

| Parameter | Value |
|---|---|
| Bus | CAN 2.0B (extended 29-bit identifiers) |
| Bit rate | **50 kbps** |
| Transceiver | SN65HVD230 (3.3 V) on the ESP32 shield |
| Connectors | Standard CAN-H / CAN-L with 120 Ohm termination |

---

## 2. CAN identifier layout

The gateway builds outgoing IDs with `build_can_id(sender_id, receiver_mask)`:

```
bits 28-22  = 0x7F        priority / type marker
bits 21-11  = sender_id   node id of the source (device type | address)
bits 10-0   = receiver_mask  node id of the destination (or broadcast mask)
```

On receive, the two fields used by `parse_frame()` are:

```
msg_id    = can_id >> 24         -> selects start-of-message vs continuation
device_id = (can_id >> 11) & 0x7FF  -> source device (0x7FF would be broadcast)
```

### Start-of-message vs continuation

| Condition | Meaning |
|---|---|
| `msg_id == 0x1F` | **Start-of-message frame** (first frame of a message) |
| `msg_id != 0x1F` | **Continuation frame** (fragment of an in-progress multi-frame message) |

The sender clears bits 28-22 when transmitting continuation frames
(`cont_id = can_id & 0x003FFFFF`) so the receiver can tell them apart.

---

## 3. Frame formats

A standard CAN data frame carries at most **8 bytes** of payload.

### 3.1 Single-frame message (`num_remaining == 0`)

```
byte 0          : 0x00 << 3 | flags   (upper 5 bits = 0 -> single frame)
byte 1 .. n     : message payload
```

The receiver strips byte 0 and dispatches the rest as a complete message.

### 3.2 Multi-frame message

Payloads larger than 6 bytes (after the two header bytes) are split:

```
First frame  (msg_id = 0x1F):
  byte 0          : total << 3 | 0x01      -> TOTAL frame count (first + continuations)
  byte 1          : msg_header             -> reassembly key (shared by all frames)
  bytes 2 .. 7    : payload[0..5]          -> up to 6 payload bytes

Continuation frames (msg_id != 0x1F):
  byte 0          : msg_header             -> reassembly key
  bytes 1 .. 7    : payload[6..12], [13..19], ...  -> up to 7 bytes per frame
```

> **Important (frame counting).** The value in the first-frame header is the
> **TOTAL frame count** (first frame + continuations). Verified against captured
> bus traffic: a 3-frame response carries 0x19, a 2-frame response carries 0x11.
> The reassembler therefore waits for `total - 1` continuation frames before
> CRC-checking and dispatching.

The reassembly key stored in `pending_messages_` is:

```
header_key = (device_id << 8) | msg_header
```

so the same 8-bit `msg_header` used by two different CAN devices cannot collide.

### 3.3 Message payload layout (after framing is stripped)

```
[0]  command byte      0x40 = GET request
                       0x46 = SET request
                       0x42 = RESPONSE
[1]  function_group
[2]  function_number
[3]  datapoint high byte
[4]  datapoint low byte
[5..] value payload     (big-endian, width depends on the datapoint type)
```

The last **two bytes of the reassembled multi-frame payload** are the CRC-16
checksum (big-endian) over all preceding payload bytes.

---

## 4. Value types

Datapoint values use big-endian unsigned/signed integers:

| Type | Width | Encoding |
|---|---|---|
| U8 | 1 byte | unsigned 8-bit |
| U16 | 2 bytes | unsigned 16-bit |
| U32 | 4 bytes | unsigned 32-bit |
| S8 | 1 byte | signed 8-bit |
| S16 | 2 bytes | signed 16-bit |
| S32 | 4 bytes | signed 32-bit |
| S64 | 8 bytes | signed 64-bit |

`bytes_to_number()` accumulates into `uint64_t` first to avoid signed-overflow
UB when decoding `S64`, then casts to the target type.

---

## 5. CRC-16 (multi-frame checksum)

Identified by brute-force search (see [`catch_crc.md`](catch_crc.md) for the
methodology and [`crc_find.py`](crc_find.py) for the search tool):

| Parameter | Value |
|---|---|
| Width | 16 |
| Poly | `0x1021` |
| Init | `0xB006` |
| RefIn | `true` |
| RefOut | `true` |
| XorOut | `0x0000` |

This is the CRC-16/ARC family with a non-standard initial value.

The component's `compute_crc16()` uses a 256-entry lookup table (MSB-first, over
pre-reflected bytes) initialized once on first use — faster than a per-bit loop
and validated against the captured samples in both forms.

### Known samples (for validation)

| Message (hex) | CRC-16 |
|---|---|
| `7400ff00000000ffff` | `0x71E5` |
| `7401ff00000000ffff` | `0xF05A` |
| `7402ff00000000ffff` | `0x7A8A` |
| `7403ff00000000ffff` | `0xFB35` |
| `7404ff00000000ffff` | `0x673B` |
| `740008000000003200` | `0x5406` |
| `420000a28d0000000e` | `0x3481` |
| `4200004e4500000000` | `0x7F4F` |
| `56320092e8700064` | `0x00A4` |
| `56320092eb700064` | `0x2569` |
| `42320001f9436f6e7374616e74` | `0x7BD2` |
| `560000a28d800000000000000034` | `0x10B3` |
| `5600004e45800000000000000034` | `0xD57C` |
| `42000071720800ff01080232000000e06300000000` | `0x279B` |

---

## 6. Device types

| Type | Value | Description |
|---|---|---|
| WEZ | 0 | Heat generator |
| SOL | 64 | Solar module |
| PS | 128 | Buffer storage tank |
| FW | 192 | District heating |
| HK | 256 | Heating circuit |
| MWA | 384 | Energy meter module |
| GLT | 448 | Building management system (BMS) |
| HV | 512 | HomeVent ventilation |
| BM | 1024 | Control module (display) — `BD` is an alias for `BM`, use `BM` |
| GW | 1153 | Gateway (Modbus/KNX) |

Typical bus addresses: `HV=8`, `BM=8`, `WEZ=1`.

The gateway presents itself on the bus as a **GW** device
(`GATEWAY_DEVICE_TYPE = 1153`) and addresses devices per configured hub.

---

## 7. Component behaviour (implementation notes)

- **GET** — sent on each entity poll (default `30s`) using the cached
  `build_get_request()` payload; responses are matched to entities by
  `(function_group, function_number, datapoint)` within the receiving device.
- **SET** — `send_can_frames()` splits payloads > 8 bytes:
  strips the leading `0x01` flag byte, appends the CRC, and emits
  `1 + num_cont` frames with the first-frame count in the upper 5 bits.
- **Reassembly robustness**:
  - `MAX_PENDING_MESSAGES = 32` guard; on a full buffer the single oldest entry
    is evicted (LRU) instead of clearing all in-progress reassemblies.
  - Stale entries expired after `MAX_PENDING_AGE_MS = 5000` ms in `loop()`.
  - Start frames claiming an implausible frame count (> 8) are rejected outright.
  - Duplicate / extra continuation frames are discarded.
- **OTA safety** — `pause()` / `resume()` drop frames during OTA updates.
- **Post-boot refresh** — a one-shot `update_all()` fires after
  `boot_refresh_delay` (default 30 s, `0` disables it).
- **Throttled refresh** — `update_all()` queues sensors and `loop()` releases
  one GET per `refresh_gap_ms` (default 50 ms) to keep the 50 kbps bus and the
  main loop responsive; `MAX_REFRESH_PER_LOOP` is now a compatibility no-op.
- **Thread safety** — `request_refresh() / request_pause() / request_resume()`
  enqueue commands on a FreeRTOS queue drained by `loop()` on the main task
  (duplicate commands are coalesced and queue overflow is logged).

---

## 7bis. Party mode (undocumented HV feature)

Party mode is an undocumented HomeVent (HV) feature that forces the ventilation
to a fixed power level for a limited time. Activating it sends **two consecutive
SET requests** from the gateway (CAN id `0x1FE04208`) to the HV device
(`0x47FF`):

```
Frame 1 - DURATION : 01 46 32 00 07 DA 00 <value>
Frame 2 - POWER    : 01 46 32 00 9F 0A <value>
```

| Field | Meaning | Encoding |
|---|---|---|
| `0x46` | SET_REQUEST command | — |
| `0x32 0x00` | function group / number | — |
| `0x07DA` + value | duration | **hours x 10** (0.1 h per unit, U8). `0x0A`=1 h, `0x14`=2 h, `0x1E`=3 h, `0x50`=8 h, `0x5A`=9 h, `0x64`=10 h |
| `0x9F0A` + value | power | **percent** (U8). `0x64`=100 %, `0x63`=99 %, `0x32`=50 %, `0x14`=20 % |
| duration `0x00` | normal operation | turns party mode off (back to week schedule) |

The device confirms each write by echoing a `0x42` RESPONSE with the same
datapoint/value; the gateway also emits `0x44` acknowledge frames.

Both values are single bytes behind the header — "concatenated" simply means two
separate SET frames (duration then power) are sent per action.

See [`candump_party_mode.log`](candump_party_mode.log) for the full captured
samples and the cross-check table.

## 8. References

- [`catch_crc.md`](catch_crc.md) — step-by-step CRC reverse-engineering guide.
- [`crc_find.py`](crc_find.py) — XOR-difference based CRC search tool.
- Component source: `esphome/components/toptronic/`
  (`toptronic.cpp`, `toptronic.h`, `__init__.py`, platform `*.py` files).
- Preset / datapoint generation: `hoval_data_processing/`.