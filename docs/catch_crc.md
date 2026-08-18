# CRC Reverse Engineering Guide

## Goal
Identify the CRC-16 algorithm used in TopTronic multi-frame CAN responses,
so the `send_can_frames()` function can send correct checksums for SET commands
with large data types (U32 / S32 / S64).

---

## Step 1 — Enable CRC logging

`esphome/packages/debug.yaml` already contains:

```yaml
logger:
  logs:
    toptronic: DEBUG
```

Flash it alongside your main config. This activates `[CRC]` log lines in `toptronic.cpp`
for every reassembled multi-frame message received from the boiler.

---

## Step 2 — Collect samples

Open the ESPHome **device logs** (OTA log or USB serial).  
Wait for the boiler to send multi-frame responses (typically starts at boot or on state changes).

Look for lines like:

```
[D][toptronic:395]: [CRC] len=9 crc=0xA1B2 payload=0x420102000BEA0100FF
```

Copy at least **5–10 different lines** — more is better. You need:
- `payload` hex string (everything after `payload=0x`)
- `crc` hex string (the 4 hex digits after `crc=0x`)

---

## Step 3 — Analyse with RevEng online

Open **[RevEng online](https://reveng.sourceforge.io/crc-catalogue/all.htm)** — or use the
web-based tool at **https://crccalc.com** for quick validation of known algorithms.

### Option A — RevEng online interface
Go to: **https://www.sysnet.ucsd.edu/~pal/cgi-bin/wotd-gen.pl**  
*(or search "RevEng online CRC finder")*

Enter each sample as: `payload_hex crc_hex`, one per line. Set width to **16**.

### Option B — RevEng command line (WSL / Linux)
```bash
sudo apt install reveng

# Syntax: -w <width> -s <payload1_hex> <crc1_hex> [<payload2_hex> <crc2_hex> ...]
reveng -w 16 -s \
  420102000BEA0100FF A1B2 \
  42010200XXYYZZ1122 CCDD \
  42010200AABBCC3344 EEFF
```

A successful match outputs something like:
```
width=16  poly=0x8005  init=0xFFFF  refin=true  refout=true  xorout=0x0000  name="CRC-16/MODBUS"
```

### Option C — Quick sanity check with Python
```python
import crcmod

# Replace 'modbus' with the algorithm name RevEng found
crc_fn = crcmod.predefined.mkCrcFun('modbus')
payload = bytes.fromhex("420102000BEA0100FF")
print(hex(crc_fn(payload)))   # should match your captured crc value
```

---

## Step 4 — Implement the CRC

Once you have a confirmed algorithm, update `send_can_frames()` in `toptronic.cpp`:

```cpp
// Replace the two 0x00 placeholder lines:
msg.push_back(0x00);  // CRC byte 1 (placeholder)
msg.push_back(0x00);  // CRC byte 2 (placeholder)

// With the real CRC (example for CRC-16/MODBUS):
uint16_t crc = crc16_modbus(msg.data(), msg.size());
msg.push_back(static_cast<uint8_t>(crc >> 8));   // CRC high byte
msg.push_back(static_cast<uint8_t>(crc & 0xFF)); // CRC low byte
```

You will also need to add a `crc16_modbus()` helper — most CRC-16 variants can be
implemented as a simple lookup table or polynomial loop.

---

## Cleanup

Once the CRC is identified and implemented, remove the `logger:` block from
`esphome/packages/debug.yaml` to stop verbose `[CRC]` output.
