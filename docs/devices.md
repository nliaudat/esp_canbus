# Supported devices & default bus addresses

Reference for the Hoval TopTronic device types the `toptronic:` component can
talk to, and the default CAN bus address of each device.

A `toptronic:` hub is configured once per device — one `device_type` plus one
`device_addr`. On the wire the two are combined into the node id
`device_type | device_addr` (see [`hoval_canbus.md`](hoval_canbus.md) §3.4).

## Device types

| Device type | Description | Default address | Presets |
|---|---|---|---|
| `WEZ` | Heat generator | 1 | sensors + inputs |
| `SOL` | Solar module | 16 | sensors + inputs |
| `PS` | Buffer storage tank | 15 | sensors + inputs |
| `FW` | District heating | 1 | sensors + inputs |
| `HK` | Heating circuit | 9 | sensors + inputs |
| `MWA` | Energy meter module | 13 | sensors |
| `GLT` | Building management system (BMS) | 12 | sensors |
| `HV` | HomeVent ventilation unit | 8 | sensors + inputs + buttons |
| `BM` | Control module (display) | 8 | sensors |
| `GW` | Gateway (Modbus/KNX) | — | sensors |

Notes:

- `BD` is an alias for `BM` — use `BM`.
- `GW` is the gateway node type (`GATEWAY_DEVICE_TYPE = 1153`); the ESP32
  gateway presents itself on the bus as a GW device, so it has no default
  address of its own.
- The default addresses are the standard Hoval installation values; the actual
  address of a device is set in / shown by the room control unit and can differ.

## Default bus addresses (Hoval documentation)

| Unit | Default address |
|---|---|
| WEZ (heat generator) | 1 |
| FW (district heating) | 1 |
| HV (HomeVent ventilation) | 8 |
| HK (heating circuit) | 9 |
| WW (domestic hot water) | 9 |
| DHW (domestic hot water) | 11 |
| GLT (building management system / BMS) | 12 |
| MWA (energy meter module) | 13 |
| PS (buffer storage tank) | 15 |
| SOL (solar module) | 16 |

> `WW` (Warmwasser) and `DHW` are **not** separate hub device types — the
> domestic-hot-water datapoints are bundled into the `WEZ`, `FW` and `HK`
> presets (function group 2, see `presets/<type>/inputs_<lang>.yaml`).

## Presets

All device types ship `sensors_<lang>.yaml` presets; the writable types (`WEZ`,
`SOL`, `PS`, `FW`, `HK`, `HV`) additionally ship `inputs_<lang>.yaml`, and `HV`
also ships `buttons_<lang>.yaml`. Entities are generated automatically from
these files for the hub's `language` (`de`, `en`, `fr`, `it`).

## Example

```yaml
toptronic:
  - id: toptronic_WEZ
    canbus_id: cbus
    device_type: WEZ
    device_addr: 1
    language: en
```

To identify the bus address of a device on a live bus, use the "find can_id
debug" switch — see [`candump.md`](candump.md), step 4.
