# Write safety

The `toptronic:` component can write to the boiler via **number** / **select**
entities (CAN SET requests). Two write-safety mechanisms protect the boiler
controller and the 50 kbps bus from bad or over-eager writes:

| Option | Default | Meaning |
|---|---|---|
| `write_min_interval` | `2s` | Minimum spacing between two SET requests to the **same datapoint**. Writes arriving faster are ignored and logged at WARN. `0` disables the rate limit. |
| `reject_writes_before_read` | `true` | **Cold-cache guard**: a SET is rejected (WARN log) until that datapoint has delivered at least one RESPONSE to a GET since boot, so the gateway never writes blind. Datapoints with **no registered read sensor** (e.g. the HV *Acknowledge filter maintenance* button) are exempt — there is nothing to have read. |

Both are per-hub options:

```yaml
toptronic:
  - id: toptronic_WEZ
    canbus_id: cbus
    device_type: WEZ
    device_addr: 1
    write_min_interval: 2s
    reject_writes_before_read: true
```

Implementation: the rate limit lives in `TopTronic::register_input_callbacks()`
(per-datapoint `last_write_ms_` map); the cold-cache state (`read_ok_ids_`) is
updated in `interpret_message_()` every time a sensor publishes a value.

## Verified-writable datapoints

Register numbers below are from the **official Hoval Modbus datapoint list**
(the same column used by the preset generator). Ranges are the raw xlsx
`Min./Max.` values; where `decimal` is set, the HA-facing value is the raw
value divided by `10^decimal`.

| Register | Datapoint `(fg, fn, dp)` | Meaning | Type / decimal | Range (raw) | Notes |
|---|---|---|---|---|---|
| 1478 | (1, 0, 3050) | Betriebswahl Heizung HK1 | LIST | — | also written back by the Hoval display (see below) |
| 1479 | (1, 1, 3050) | Betriebswahl Heizung HK2 | LIST | — | |
| 1481 | (1, 0, 3051) | Normal-Raumtemperatur HK1 | S16 / 1 | 100…300 | 10.0…30.0 °C |
| 1482 | (1, 0, 3053) | Spar-Raumtemperatur HK1 | S16 / 1 | 50…200 | 5.0…20.0 °C |
| 1496 | (2, 0, 5050) | Betriebswahl Warmwasser | LIST | — | |
| 1497 | (2, 0, 5051) | Normal-Warmwassertemperatur | S16 / 1 | 100…700 | 10…70 °C |
| 1498 | (2, 0, 5086) | Spar-Warmwassertemperatur | U8 | 10…70 | |
| 1561 | (10, 1, 9075) | Betriebswahl Wärmeerzeuger | LIST | — | 0=Aus, 1=Automatik, 4=Man. Heizen, 5=Man. Kühlen |
| 1510/1511/1512 | (1, 0/1/2, 1) | Raum-Ist (extern einspeisbar) HK1-3 | S16 / 1 | — | xlsx range 0…0; feed a real measured value |
| 19482 | (1, 0, 7047) | Vorlauf-Soll Konstantanf. Kühlen HK1 | S16 / 1 | — | 0 = off |
| 23755 | (1, 1, 7047) | dito HK2 | S16 / 1 | — | 0 = off |
| 27509 | (2, 0, 5077) | SG-Offset Warmwasser-Soll | S16 / 1 | 0…800 | 0…80 K |
| 27528/27529/27530 | (1, 0/1/2, 7031) | SG-Offset Raum-Soll Heizen HK1-3 | S16 / 1 | 0…120 | 0…12 K |
| 27531/27532 | (1, 0/1, 7046) | SG-Offset Raum-Soll Kühlen HK1-2 | S16 / 1 | −600…0 | −60…0 K |
| 27545 | (0, 0, 38012) | Smart Grid über Systembus | U8 | 0…3 | 0=Normal 1=Vorzug 2=Gesperrt 3=Abnahmezwang |
| 27546 | (0, 0, 38013) | Auslöser Smart Grid Funktion | U8 | 0…3 | 0=Aus 1=Eingangskontakte 2=Systembus 3=Leistung gedämpft |
| 28839 | (21, 0, 6050) | SG-Offset Heizpuffer (PS module) | S16 / 1 | — | only effective when a PS module is attached |

## Write-back behaviour (externally overwritten registers)

Measured with a live system (HoxPi, systematic write-and-reread): these
registers are **overwritten by other writers**, so a value you set may revert.
Do not fight them with automations — treat them as "best effort".

| Register | Writer | Behaviour |
|---|---|---|
| 1478 | Hoval control panel | Betriebswahl HK1 rewritten after ~6–8 s |
| 23622 | Hoval control panel | Betriebswahl Lüftung |
| 23626 | Hoval control panel | Feuchte-Sollwert |
| 1510 | Loxone (cyclic) | Raumtemperatur-Einspeisung HK1 |
| 27509 | Loxone (cyclic) | SG-Offset Warmwasser |
| 27528 | Loxone (cyclic) | SG-Offset Raum Heizen HK1 |
| 27531 | Loxone (cyclic) | SG-Offset Raum Kühlen KK1 |
| 29435/29436 | Loxone (cyclic) | Vorlaufminimaltemp. Kühlen |
| 23623 | Loxone (cyclic) | Lüftungsmodulation |

*(23622/23626/23623 are HomeVent registers — register numbers from the same
official datapoint list; the ESP32 component addresses them with
`device_type: HV`, see `hoval_canbus.md`.)*
