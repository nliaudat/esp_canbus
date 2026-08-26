# Capturing a CAN bus dump (candump)

How to capture every CAN frame on the Hoval TopTronic bus to the ESPHome device
log, using the **"candump debug"** switch in Home Assistant (supersedes the old
`on_frame` handler that lived in `esphome/packages/canbus.yaml`).

The resulting log is what the reference captures in
[`candump_base.log`](candump_base.log) and
[`candump_party_mode.log`](candump_party_mode.log) are made of — useful for
reverse-engineering new datapoints, verifying gateway traffic, or understanding
multi-frame reassembly.

---

## Step 1 — Turn on the "candump debug" switch

Flash the firmware, then enable the **"candump debug"** switch (see
`esphome/packages/switch.yaml`) from Home Assistant. While it is ON, every CAN
frame is logged with the `candump` tag — including the GET/SET request frames
the gateway itself sends, so each capture shows the full request → response
exchange — and normal toptronic frame noise is suppressed. The mode resets to
OFF on every reboot and also self-disables automatically after 120 s — the
timeout is checked on every received frame, so it fires even when the candump
flood would otherwise starve the main loop task. The switch is optimistic
(assumed-state) in Home Assistant: you can always turn it back OFF, even after
the auto-disable already cleared the flag.

> Keep the old `on_frame` blocks commented out: they are superseded by the
> switch and would double every candump line if re-enabled.

### Tuning the accompanying toptronic log detail

While candump is ON, normal toptronic frame noise (`[GET]`/`[SET]`/`[RES]`) is
suppressed so the raw frames are easy to read. If you also want toptronic's own
decoded lines interleaved, set `toptronic` to DEBUG **after** turning candump
off:

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

Every CAN frame is printed by the `candump` logger as:

```
[I][candump:026]: 0x1FE04208 : 01 40 32 00 9E EE          <- GET request (sent by the gateway)
[I][candump:026]: 0x1FD047FF : 01 42 32 00 9E EE 1E      <- response (received)
[I][candump:026]: 0x1F5047FF : 19 5F 56 00 00 A2 8D 80   <- multi-frame response start
[I][candump:026]: 0x1E1047FF : 5F 00 00 00 00 00 00 00   <- continuation #1
[I][candump:026]: 0x1D9047FF : 5F 34 10 B3               <- continuation #2 (+CRC)
```

- `0x1FE04208` / `0x1FD047FF` — extended CAN id. `0x1FE04208` is the gateway
  itself (sender `0x4208`) exporting the **frame requested** (its own GET/SET);
  `0x1FD047FF` is a device response (sender `0x47FF`).
- `01 40 32 00 9E EE` / `01 42 32 00 9E EE 1E` — the 8-byte (or fewer) payload,
  space-separated hex (`01 40 …` = GET request, `01 46 …` = SET request,
  `01 42 …` = response, `01 56 …` = extended response).

Request frames are exported because the CAN controller never echoes its own
transmissions back to the receive path — without this a capture would contain
only the device responses and you could not see which datapoint each response
was answering. Multi-frame SET requests are dumped frame by frame, exactly as
they go on the wire.

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

To identify the bus address of a device, turn **candump debug** off and the
**"find can_id debug"** switch on instead (`esphome/packages/switch.yaml`). It
logs only frames carrying a `0x42` (response) or `0x40` (request) command with
the `toptronic` tag at WARN — the results also appear in the **"main logs"**
text sensor. Like candump, this mode resets to OFF on every reboot and
self-disables after 120 s (checked per received frame), and the switch can
always be turned back OFF.

---

## Step 5 — Disable before production

Candump is **debug only**:

1. Turn the **"candump debug"** switch **off** in Home Assistant (the mode
   also resets to OFF automatically on every reboot and after 120 s of
   operation, like find can_id).
2. Remove the `logger:` / `toptronic: DEBUG` override from
   `esphome/packages/debug.yaml` if you enabled it (the file notes this too).
3. No re-flash is required to disable it.

Full-traffic logging adds noticeable loop-latency (the `canbus took a long
time` warning in `candump_base.log` section 8) and should never be left on in
a production build.
