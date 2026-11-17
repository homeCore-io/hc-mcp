# The shared device vocabulary

Read this before you name an attribute or a command. It is generated from
`crates/hc-types/src/device_vocabulary.rs` (`TERMS`) in the homeCore
repository. That file is the source of truth: if it disagrees with this page,
the file wins.

## The five rules

1. **Use a name from the table when the idea matches**, in its unit and range.
   Your own idea gets your own name, never one of these with another meaning.
   A WLED preset is `preset_id`; a raw 0 to 255 level is not `brightness`.
2. **Convert at the edge.** Publish in the table's unit and convert back when
   commanding. Temperatures are °C, rain mm (named `..._mm`), pressure hPa,
   wind m/s, whatever the device reports. Showing °F is the app's job, from
   the person's setting, so a plugin has no unit setting. Core converts a
   temperature that still arrives in °F or K as a backstop, and reports it.
3. **Units in names.** A number names its unit as a suffix (`_pct`, `_ms`,
   `_secs`, `_w`, `_kwh`, `_a`, `_mm`) unless it is a term whose unit this
   table sets (`temperature`, `humidity`, `volume`, `position`, ...). Fades
   are `_ms`; timers keep `_secs`.
4. **Two command shapes.** A write to a writable attribute, `{"on": true}`,
   or a declared action, `{"action": "start", "duration_secs": 600}`.
   `{"command": ...}` is retired. Read `action`, never `command`.
5. **`{"on": true}` restores the last level** where the device can. `0` %
   brightness means off, and a light that is on never reports `0` %.

## The table

Kind is the schema's `kind` (`bool`, `integer`, `float`, `string`, `enum`,
`color_xy`, `color_rgb`, `color_temp`). Unit is what the schema's `unit`
should say.

### Power and light

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `on` | bool | | | On or off. `true` with no level restores the last one. | |
| `brightness_pct` | float | `%` | 0 to 100 | Light level. 0 is off; a light that is on never reports 0. | `brightness`, `level` (scale was ambiguous) |
| `color_temp` | color_temp | `K` | | White warmth in kelvin. | `color_temp_mirek` (1,000,000 / v), `color_temp_k` |
| `color_xy` | color_xy | | | Colour as a CIE 1931 xy point, `{x, y}`. | |
| `color_rgb` | color_rgb | | | Colour as sRGB, `{r, g, b}` 0 to 255. | |
| `transition_ms` | integer | `ms` | 0 and up | Fade time for the change it is sent with. | `transition`, `duration_ms`, `fade_secs` (x1000) |

### Covers, locks, fans

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `position` | float | `%` | 0 to 100 | How open a cover is; 100 is fully open. | |
| `tilt_pct` | float | `%` | 0 to 100 | Slat tilt; 100 is fully open. | |
| `locked` | bool | | | Whether the lock is locked. | |
| `speed_pct` | float | `%` | 0 to 100 | Fan speed; 0 is off. | |

### Sensors

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `open` | bool | | | A door, window or contact: `true` when open. | `contact_open`, `door_open` |
| `motion` | bool | | | Motion seen now. | |
| `person_detected` | bool | | | A camera sees a person now. | |
| `vehicle_detected` | bool | | | A camera sees a vehicle now. | |
| `animal_detected` | bool | | | A camera sees an animal now. | |
| `package_detected` | bool | | | A camera sees a package left now. | |
| `occupied` | bool | | | Someone is in the area. | `occupancy` |
| `water_detected` | bool | | | A leak sensor is wet. | |
| `tampered` | bool | | | The device's cover or mounting was disturbed. | `tamper` |
| `temperature` | float | `°C` | | The temperature here, in °C. | `current_temperature` (thermostats) |
| `humidity` | float | `%` | 0 to 100 | Relative humidity. | `humidity_pct` |
| `illuminance` | float | `lux` | 0 and up | Light level in lux. | `illuminance_lux` |
| `pressure` | float | `hPa` | | Air pressure. | |
| `wind_speed` | float | `m/s` | | Wind speed. | |
| `co2` | float | `ppm` | | Carbon dioxide. | |

### Climate

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `setpoint` | float | `°C` | | The one target temperature, in °C. | |
| `heat_setpoint` | float | `°C` | | Heat below this, in °C. | `target_temp`, `target_temp_heat` (thermostats) |
| `cool_setpoint` | float | `°C` | | Cool above this, in °C. | `target_temp_cool` (thermostats) |
| `hvac_mode` | enum | | `off`, `heat`, `cool`, `auto`, `fan_only`, `dry` | What the thermostat is set to do. | `mode` (thermostats) |
| `hvac_action` | enum | | `idle`, `heating`, `cooling`, `fan`, `drying`, `off` | What it is doing now. | `call_for`, `state` (thermostats) |
| `fan_mode` | string | | | The thermostat's fan setting. | |

### Energy and batteries

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `power_w` | float | `W` | | Power drawn now. | |
| `energy_kwh` | float | `kWh` | | Energy used, counting up. | |
| `voltage` | float | `V` | | Supply voltage. | |
| `current_a` | float | `A` | | Current drawn now. | |
| `battery_pct` | float | `%` | 0 to 100 | Battery left. | `battery`, `battery_level` |
| `battery_low` | bool | | | The battery needs replacing soon. | |

### Media

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `volume` | float | `%` | 0 to 100 | Volume. | |
| `muted` | bool | | | Sound is muted. | |
| `state` | enum | | `playing`, `paused`, `stopped`, `idle`, `buffering` | A media player's playback. | |
| `source` | string | | | The input or app playing. | |
| `media_title` | string | | | What is playing. | `title` (media players) |
| `media_artist` | string | | | Its artist. | `artist` (media players) |
| `media_album` | string | | | Its album. | `album` (media players) |
| `media_position` | integer | `s` | | How far into it. | `position_secs` (media players) |
| `media_duration` | integer | `s` | | How long it is. | `duration_secs` (media players) |

### Scenes

| Name | Kind | Unit | Range | Meaning | Replaces |
|---|---|---|---|---|---|
| `active` | bool | | | A scene is what its devices show now. | |

"Replaces" lists old spellings. Core's automation rewrite and the vocabulary
check read them; never publish one. "(thermostats)" and "(media players)" mean
the old spelling meant this term only on that `device_type`.

## Converting at the edge

Write each conversion as a function and test both ends of the scale:

- A dimmer's lowest step must not read as 0 % (that means off).
- 100 % must reach the device's maximum: 99 on Z-Wave, 254 on Zigbee and
  Matter, 255 on WLED.
- Every whole percent should survive the round trip.

The Rust template does this with `pct_from_level` and `level_from_pct`
(0 to 255 device scale):

```rust
fn pct_from_level(level: u8) -> u8 {
    if level == 0 {
        return 0;
    }
    ((f64::from(level) * 100.0 / 255.0).round() as u8).max(1)
}

fn level_from_pct(pct: f64) -> u8 {
    if pct <= 0.0 {
        return 0;
    }
    ((pct.min(100.0) * 255.0 / 100.0).round() as u8).max(1)
}
```

Mireds to kelvin is `1_000_000 / v` both ways.

## Temperatures in Rust

Declare a temperature reading with `AttributeSchema::temperature()` (read
only, °C) and a writable setpoint with `.celsius()`. Test it with
`plugin_sdk_rs::conformance::check_temperatures(&schema)` and
`check_state_temperatures(&schema, &state)`: a temperature with no unit
fails.

## Device types

`device_type` says what a device is, never the protocol it speaks. Clients
choose cards and controls by it. Common values: `light`, `switch`, `sensor`,
`thermostat`, `lock`, `cover`, `media_player`, `scene`, `pico` (button-only
remote), `timer`. Ask the bridge what the device is; if you can't tell, omit
`device_type` and send it on a later registration, which leaves what core
stored alone until then.

## Schema reminders

- Every boolean names both of its states (`states`, with `when_true` and
  `when_false`), so automations can say "when it turns off".
- Housekeeping readings (battery, signal, firmware) are
  `category: "diagnostic"`.
- An integer that is really a choice gets `options`
  (`[{"value": "14", "label": "Halloween 1"}]`) and is named in every picker
  and automation sentence. Republish the schema when the options change.
- Read and write the same name. A value readable as `brightness` and
  writable as `level` is a control that silently does nothing.
- Never publish a value that changes by itself on every refresh (uptime, a
  clock). Every publish is a state-changed event.
- Publish `null` rather than dropping a key you sometimes cannot read.

More: [Declaring a device](https://homecore.io/docs/plugins/developing-plugins#declaring-a-device)
and [Names and units](https://homecore.io/docs/plugins/developing-plugins#names-and-units).
