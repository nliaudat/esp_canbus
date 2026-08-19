# Capturing a CAN bus dump (candump)

How to capture every CAN frame on the Hoval TopTronic bus to the ESPHome device
log, using the debug `on_frame` handler in `esphome/packages/canbus.yaml`.

The resulting log is what the reference captures in
[`candump_base.log`](candump_base.log) and
[`candump_party_mode.log`](candump_party_mode.log) are made of — useful for
reverse-engineering new datapoints, verifying gateway traffic, or understanding
multi-frame reassembly.

---

## Step 1 — Enable the candump `on_frame` handler

Open `esphome/packages/canbus.yaml`. The candump block is commented out under
`############ in debug mode only ##################`:

```yaml
    # on_frame:
      # # CANDUMP (debug only) - remove or disable before production use.
      # # Size-safe: iterates x.size() so short frames (< 8 bytes) are handled.
      # - can_id: 0
        # can_id_mask: 0
        # use_extended_id: true
        # then:
          # - lambda: |-
              # std::string line = "";
              # for (size_t i = 0; i < x.size(); i++) {
                # char tmp[4];
                # snprintf(tmp, sizeof(tmp), "%02X ", static_cast<unsigned int>(x[i]));
                # line += tmp;
              # }
              # ESP_LOGI("candump", "0x%08X : %s", can_id, line.c_str());
```

Uncomment it so it looks like:

```yaml
    on_frame:
      # CANDUMP (debug only) - remove or disable before production use.
      # Size-safe: iterates x.size() so short frames (< 8 bytes) are handled.
      - can_id: 0
        can_id_mask: 0
        use_extended_id: true
        then:
          - lambda: |-
              std::string line = "";
              for (size_t i = 0; i < x.size(); i++) {
                char tmp[4];
                snprintf(tmp, sizeof(tmp), "%02X ", static_cast<unsigned int>(x[i]));
                line += tmp;
              }
              ESP_LOGI("candump", "0x%08X : %s", can_id, line.c_str());
```

Notes:

- `can_id: 0` + `can_id_mask: 0` means **listen to all messages** on the bus.
- `use_extended_id: true` is required — the protocol uses CAN 2.0B extended
  29-bit identifiers.
- The loop iterates `x.size()` instead of hard-coding 8, so short frames
  (< 8 bytes) are printed correctly.

Optionally, enable `toptronic` DEBUG logging in `esphome/packages/debug.yaml`
to interleave `[GET]` / `[RES]` / `[CRC]` lines with the raw frames:

```yaml
logger:
  logs:
    toptronic: DEBUG
```

---

## Step 2 — Flash the firmware

Compile and flash as usual (from the `esphome/` directory):

```bash
esphome run config.yaml
```

or use the ESPHome dashboard.

---

## Step 3 — Watch / capture the log

With the device running, open the device log:

- **USB serial** — the same terminal that flashed it (or `esphome logs
  config.yaml`).
- **OTA logs** — through the ESPHome dashboard / API if the device is on WiFi.

Each received frame is printed by the `candump` logger as:

```
[I][candump:026]: 0x1FD047FF : 01 42 32 00 9E EE 1E
[I][candump:026]: 0x1F5047FF : 19 5F 56 00 00 A2 8D 80
[I][candump:026]: 0x1E1047FF : 5F 00 00 00 00 00 00 00
[I][candump:026]: 0x1D9047FF : 5F 34 10 B3
```

- `0x1FD047FF` — extended CAN id (from a device with id `0x47FF`).
- `01 42 32 00 9E EE 1E` — the 8-byte (or fewer) payload, space-separated hex.

Trigger the traffic you want to study (e.g. press buttons, wait for a poll
cycle, toggle party mode) and let it capture for a representative period.

### Saving the log to a file

To commit a capture under `docs/`, redirect the log output to a file, for
example from a terminal on the device's serial port:

```bash
# Unix / WSL — capture serial output until Ctrl+C
screen /dev/ttyUSB0 115200 | tee candump_capture.log
```

or with ESPHome:

```bash
esphome logs config.yaml > candump_capture.log
```

Stop it after enough traffic, then trim/annotate the file like the existing
`candump_base.log` reference captures.

> `[W][component:473]: canbus took a long time for an operation (192 ms)` —
> this warning appears under full-traffic candump logging and is expected.
> It is caused by the per-frame string build on the loop task — see section
> "Step 5 — disable before production".

---

## Step 4 — (Optional) Find a device CAN id

`canbus.yaml` also contains a second commented block that only logs frames
carrying a `0x42` (response) or `0x40` (request) command, to identify the
device address:

```yaml
    # Find can_id
    # - can_id: 0  # listen to all messages
    #   can_id_mask: 0
    #   use_extended_id: true
    #   then:
    #     - lambda: |-
    #         if(x[1] == 0x42) { // response frame
    #             ESP_LOGI("can_id_find", "Response frame : hoval_homevent_can_Addr is probably : %x", can_id);
    #         }else if(x[1] == 0x40) { // request frame
    #             ESP_LOGI("can_id_find", "Request frame : hoval_toptronic_can_Addr is probably : %x", can_id);
    #         }
```

If you don't know the bus address of a device, replace the candump block with
this one and watch the `can_id_find` lines.

---

## Step 5 — Disable before production

Candump is **debug only**:

1. Re-comment the `on_frame:` block in `esphome/packages/canbus.yaml`
   (or replace it with the "Find can_id" block if still needed).
2. Remove the `logger:` / `toptronic: DEBUG` override from
   `esphome/packages/debug.yaml` (the file notes this too).
3. Re-flash the normal firmware.

Full-traffic logging adds noticeable loop-latency (the `canbus took a long
time` warning in `candump_base.log` section 8) and should never ship in a
production build.