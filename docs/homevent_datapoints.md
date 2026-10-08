# HomeVent (HV) — datapoints beyond the official Modbus list

Findings from a Hoval **HomeVent ER300** (sold/spare parts also as "FR") with a **BG02 E** operating
terminal, read through this component on an ESP32-S3 (Waveshare ESP32-S3-RS485-CAN), October 2026.

Everything below was obtained with **read-only GET requests** unless a write test is explicitly
mentioned. Datapoints are written as `function_group-function_number-datapoint`. Node `0x208`
(HV, address 8).

## How the datapoints were found

1. GET scan of these ranges (10 requests/s, ~20 min, no effect on the unit):
   `50-0-0…999`, `50-0-36000…43999`, `0-0-20000…21999`, `0-0-29000…29099`, `0-0-41500…41799`.
   Answers for datapoints without an entity are visible in the `[DROP] No sensor for key …` debug log,
   which now includes the payload.
2. ~110 datapoints answered. Candidates were then read before/while/after turning the BG02 E knobs
   (air volume 50 → 100 → 50 %, humidity set value 49 → 35 → 49 %).

The ESPHome snippets used for the scan, for on-demand reads and for setting the clock are at the end
of this page.

## Confirmed

| Datapoint | Type | Meaning | Evidence |
|---|---|---|---|
| `50-0-38601` | U8 % | **Supply air fan set value** (twin of 38600 *Fan exhaust air set*) | Follows the air volume knob: 43 → 71 → 52 → 46. Also broadcast unsolicited every few seconds |
| `0-0-41600` / `0-0-41601` | U8 % | Copies of exhaust / supply fan set values | Change together with 38600 / 38601 |
| `50-0-39606` | U8 % | **Supply fan calibration** (95 on the test unit) | Fixed during tests. Exhaust/supply fan ratio constant at every air volume (37/43, 45/52, 61/71 ≈ 0.86) = 82/95 |
| `50-0-39605` | U8 % | **Exhaust fan calibration** (82 on the test unit) | See above |
| `50-0-39612` / `50-0-39613` | U8 % | **Humidity set value limits** (35 / 65) | BG02 E humidity knob minimum = 35 % |
| `0-0-2070` | U16 | **Date**, days since 1900-01-01 (1900-01-01 = 1) | Format from the wladwnt CAN-Gateway manual §10.3.6. Written and read back |
| `0-0-2072` | U16 | **Time**, minutes since midnight | Written and read back |
| `0-0-2073` | U8 | Day of week (0 = Monday), computed by the unit | 3 after writing a Thursday |
| `0-0-20124` | U32 | **Unit clock**, seconds since 1970 **in local time**; broadcast every second | 2016-01-01 00:xx after power-up, current local time after writing 2070/2072 |
| `0-0-20000` | U32 | Date (same encoding as 2070) | 0x0000a581 = 2016-01-01 before the clock was set |
| `0-0-20001` | ASCII | Serial number | `00000000028180480` |
| `0-0-20002` | ASCII | Device type | `HV` |
| `0-0-20004` | 4 bytes | Software version (likely) | `02 0b 00 06` |
| `0-0-20005` | ASCII | CPU id | `CPU-ID:A3CC0CE1` |
| `50-0-503` / `50-0-505` | U8 / ASCII | Active operating mode, code / text | `4` / `Costante` (= 40650) |
| `0-0-29042…29046` | 16 bytes | Active errors 1–5 (structure per official list) | All `ff 00 ff…` = no error |
| `50-0-37606…37614` | U8/U16 | CO2 / VOC values | `ff` / `ffff` = sensor not installed |

### The HomeVent clock is not battery-backed

Without a TopTronic E touch display the unit restarts at **2016-01-01 00:00 on every power-up**
(only the BG02 E is connected and it has no clock). Week programs (`40650` = 1 / 2) therefore run on a
wrong time. Writing `0-0-2070` and `0-0-2072` sets it; an ESP powered from the same bus can do it after
each boot and nightly (example below).

### 0x56 records look like descriptors

Several datapoints answer with a 0x42 record (value) **and** a 0x56 record whose content matches the
datapoint's limits, not its value:

| Datapoint | 0x42 value | 0x56 payload | Interpretation |
|---|---|---|---|
| `50-0-40719` | 70 | `b3 0f 64` | 15..100 |
| `50-0-40715` | 500 | `b3 01f4 c350` | 500..50000 |
| `0-0-21102` | 0x8000 | `f3 ff9c 0064` | -100..100 |
| `0-0-20037` | 26 | `80 … 34` | max 52 (official list: max 52) |

This also fits the values listed in [`toptronic_internals.md`](toptronic_internals.md) §2.4: the
`80 00` records of the operating-week counters carry 52 (= the counters' maximum in the official
list) and the `70 00` records of the fan-speed registers carry 100 (= their maximum, %). In other
words the 0x56 record seems to describe the datapoint (type tag + limits), not report its value.

This is why the maintenance / cleaning counters toggled between 52 and the real value (26 / 14 weeks
on the test unit). The new `ignore_extended: true` option makes an entity use only 0x42 records; the
HV presets set it on `0-0-20037` and `0-0-41613`.

## Writes (verified)

* SET requests from the component's sender id (`0x481 | addr`) **are accepted** by the HomeVent
  (date/time and `50-0-39613`). HoxPi reports that the HomeVent ignores writes from other sender ids;
  this was not the case here.
* `50-0-39613` 65 → 64: accepted, still 64 after 2 minutes (then restored). Installer parameters in the
  396xx range are writable and the BG02 E does **not** overwrite them.
* `50-0-40651` (normal ventilation modulation) 52 → 77: set back to 52 by the BG02 E within the same
  second. **With a BG02 E connected, air volume / humidity set value / party mode cannot be controlled
  over CAN** — the BG02 E resends its knob positions about every second (same behaviour as described in
  the wladwnt CAN-Gateway manual, chapter 30). The BG02 E itself is seen on the bus as node `0x000`
  (Can-IDs `0x1F4007FF` / `0x1E8007FF`).

## Strong candidates (user-supplied, consistent with Hoval documentation, not yet verified)

Hoval training material ("Ventilazione meccanica controllata", Jan 2020, slide 64) gives the automatic
CoolVent activation as *outside temperature > 27 °C and outside temperature > extract air temperature + 3 K*.

| Datapoint | Value | Candidate meaning |
|---|---|---|
| `50-0-39617` | 1 | CoolVent enabled (0/1) |
| `50-0-40688` | 250 (S16, 0.1) | CoolVent temperature threshold, 25.0 °C (installer-adjusted from 27?) |
| `50-0-39601` | 3 | CoolVent temperature differential, K |

Expected confirmation: `Status vent. regulation` (39652) switching to 5 (CoolVent active) in summer,
compared with outside and extract air temperatures.

## Unknown (answering, meaning not established)

`50-0-500` (ff), `504` (ff), `502` ("NUOVO"), `37601`, `37603`, `37605`, `38602…38605`, `38607…38612`
(38604 = 40, 38609 = 14, 38611 = 40, others 0, none changed during the knob tests),
`39600` (air quality control, official), `39602` = 90, `39603` = 1, `39604` = 1, `39607` = 13,
`39608` = 0, `39609` = 20, `39610` = 2 (model/size code?), `39611` = 170 (17.0 °C?), `39614` = 0,
`39615` = 100 / `39619` = 15 (modulation max/min?), `39616` = 30, `39618` = 0, `39620` = 4,
`40689` = 0, `40690…40713` = 24 × 0/1 (hourly program?), `40714` = 100, `40715…40718` = 500 / 2000 / 3000 / 6000,
`40719` = 70, `0-0-20003` = 1234, `0-0-20020/20021/20022/20027/20034`, `0-0-20126/20127`, `0-0-20200…20204`,
`0-0-21054`, `0-0-21058` (0x7fffffd6), `0-0-21101/21102` (0x8000), `0-0-41604/41605/41610/41611/41612`.

The rotary heat exchanger (enthalpy wheel) speed was **not** found in the scanned ranges.

## Powering the ESP from the HomeVent bus

Measured on the test unit's RJ45 (T568B colours): pin 1 CAN-H (white/orange), pin 2 CAN-L (orange),
pins 3 and 7 GND (white/green, white/brown), pin 8 +12.1 V (brown); CAN-H / CAN-L idle at 2.47 V.
CAN-H to CAN-L measured 62.5 Ω (≈ two 120 Ω terminators in parallel), i.e. the bus is already
terminated, so no extra 120 Ω terminator was added on the ESP side.

The ESP can therefore be powered from the unit. ESP and HomeVent then start together; the test setup uses
`boot_refresh_delay: 120s` so the post-boot refresh does not reach the controller while it is still
starting.

## Example ESPHome snippets

On-demand read of any datapoint (GET only), callable from Home Assistant or `aioesphomeapi`:

```yaml
api:
  actions:
    - action: read_datapoint
      variables:
        fg: int
        fn: int
        dp: int
      then:
        - lambda: |-
            std::vector<uint8_t> req = {0x01, 0x40, (uint8_t) fg, (uint8_t) fn,
                                        (uint8_t) ((dp >> 8) & 0xFF), (uint8_t) (dp & 0xFF)};
            // sender: gateway (0x481 | 8), receiver: HV node 0x208
            const uint32_t can_id = (0x7FUL << 22) | ((uint32_t) (0x481 | 8) << 11) | 0x208;
            id(cbus).send_data(can_id, true, req);
```

Set the HomeVent clock after boot and nightly:

```yaml
time:
  - platform: sntp
    id: sntp_time
    on_time_sync:
      - delay: 150s            # let the unit's controller boot (ESP powered from the same bus)
      - script.execute: set_hv_clock
    on_time:
      - seconds: 5
        minutes: 5
        hours: 3               # nightly, also covers DST changes
        then:
          - script.execute: set_hv_clock

script:
  - id: set_hv_clock
    then:
      - lambda: |-
          auto now = id(sntp_time).now();
          if (!now.is_valid()) return;
          auto dfc = [](int y, unsigned m, unsigned d) -> long {  // days_from_civil
            y -= m <= 2; const long era = (y >= 0 ? y : y - 399) / 400;
            const unsigned yoe = (unsigned) (y - era * 400);
            const unsigned doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
            const unsigned doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
            return era * 146097 + (long) doe - 719468; };
          const uint16_t date = (uint16_t) (dfc(now.year, now.month, now.day_of_month) - dfc(1900, 1, 1) + 1);
          const uint16_t mins = (uint16_t) (now.hour * 60 + now.minute);
          const uint32_t can_id = (0x7FUL << 22) | ((uint32_t) (0x481 | 8) << 11) | 0x208;
          // SET 0-0-2070 (0x0816) date, then SET 0-0-2072 (0x0818) time
          std::vector<uint8_t> d = {0x01, 0x46, 0x00, 0x00, 0x08, 0x16, (uint8_t) (date >> 8), (uint8_t) (date & 0xFF)};
          id(cbus).send_data(can_id, true, d);
          std::vector<uint8_t> t = {0x01, 0x46, 0x00, 0x00, 0x08, 0x18, (uint8_t) (mins >> 8), (uint8_t) (mins & 0xFF)};
          id(cbus).send_data(can_id, true, t);
```

To show the unit clock in Home Assistant, convert the local-time seconds of `0-0-20124` to UTC:

```yaml
sensor:
  - platform: toptronic
    toptronic_id: toptronic_HV
    name: "Unit clock"
    function_group: 0
    function_number: 0
    datapoint: 20124
    type: U32
    device_class: timestamp
    entity_category: diagnostic
    filters:
      - throttle: 300s
      - lambda: |-
          auto now = id(sntp_time).now();
          if (!now.is_valid()) return {};
          return x - now.timezone_offset();
```

Read-only datapoint scan (GET only, 10 requests/s). Answers show up in the `[DROP] No sensor for key …`
log lines (tag `toptronic`, level DEBUG):

```yaml
switch:
  - platform: template
    name: "Datapoint scan"
    id: scan_active
    entity_category: diagnostic
    optimistic: true
    restore_mode: ALWAYS_OFF
    on_turn_on:
      - lambda: |-
          id(scan_range) = 0;
          id(scan_dp) = -1;

globals:
  - id: scan_range
    type: int
    initial_value: "0"
  - id: scan_dp
    type: int
    initial_value: "-1"

interval:
  - interval: 100ms
    then:
      - lambda: |-
          if (!id(scan_active).state) return;
          // {function_group, function_number, dp_start, dp_end}
          static const uint16_t R[][4] = {
            {50, 0, 0, 999},
            {50, 0, 36000, 43999},
            {0, 0, 20000, 21999},
            {0, 0, 29000, 29099},
            {0, 0, 41500, 41799},
          };
          static const int NR = sizeof(R) / sizeof(R[0]);
          if (id(scan_range) >= NR) {
            ESP_LOGI("scan", "Scan completed");
            id(scan_active).turn_off();
            return;
          }
          if (id(scan_dp) < 0) id(scan_dp) = R[id(scan_range)][2];
          const uint8_t fg = R[id(scan_range)][0], fn = R[id(scan_range)][1];
          const uint16_t dp = (uint16_t) id(scan_dp);
          std::vector<uint8_t> req = {0x01, 0x40, fg, fn, (uint8_t) (dp >> 8), (uint8_t) (dp & 0xFF)};
          const uint32_t can_id = (0x7FUL << 22) | ((uint32_t) (0x481 | 8) << 11) | 0x208;
          id(cbus).send_data(can_id, true, req);
          if (dp >= R[id(scan_range)][3]) { id(scan_range)++; id(scan_dp) = -1; }
          else id(scan_dp)++;
```

Additional read-only entities (example):

```yaml
sensor:
  - platform: toptronic
    toptronic_id: toptronic_HV
    name: "Supply air fan set"
    function_group: 50
    function_number: 0
    datapoint: 38601
    type: U8
    unit_of_measurement: "%"
  - platform: toptronic
    toptronic_id: toptronic_HV
    name: "Supply fan calibration"
    function_group: 50
    function_number: 0
    datapoint: 39606
    type: U8
    unit_of_measurement: "%"
    entity_category: diagnostic
    update_interval: 1h
```
