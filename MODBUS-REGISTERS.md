# SH10RT Modbus register reference

[Home](README.md) · [Read-only examples](MODBUS-EXAMPLES.md) · [CLI](NETWORK-SCRIPTS.md) · [Troubleshooting](TROUBLESHOOTING.md)

A practical register list for this project's SH10RT diagnostics and monitoring. It covers **83 register entries/ranges**, the selected fault bits decoded by the `values` command, and a small set of settings useful for interpreting operating limits. It is not a complete Sungrow family protocol or a promise that every listed field works on every firmware.

Download the [typed JSON catalog](reference/modbus-registers.json), [register CSV](reference/modbus-registers.csv), [selected flag CSV](reference/modbus-flags.csv) and [source manifest](reference/modbus-sources.json). The CSV is reference data, not a ready-to-load configuration for a particular third-party integration.

## JSON for scripts

[`reference/modbus-registers.json`](reference/modbus-registers.json) contains the register entries and selected flag definitions together. Addresses, counts, multipliers, function codes, bit positions and masks are JSON numbers. Register space and target remain explicit because an address alone does not identify a value.

| JSON field | Meaning |
| --- | --- |
| `schema_version` | Catalog structure version, currently 1; not a Sungrow protocol version |
| `addressing` | One-based logical vs zero-based PDU addresses, byte/word order and bit numbering |
| `registers` | Array of the 83 register entries/ranges |
| `flags` | Array of the eight selected input-word flag definitions |
| `sources_file` | Relative path to reviewed source metadata; each entry contains matching `source_ids` |

In a register entry, `logical_address` is the start used by this project's helper and `pdu_address` is the start sent on the wire. `register_count` counts 16-bit words. `multiplier` is applied after decoding the declared `data_type`. Types retain the notation used below, including `U16[3]` for three separate values and `U32 bitset` for a combined flag group.

`read_function` is numeric 4 or 3. `access` describes the protocol's register space, **not permission to write**; the catalog executes nothing. `project_use`, `notes` and `source_ids` retain implementation and firmware qualifications. A flag includes both numeric `word_mask` and display string `word_mask_hex`.

The CSV files are the editable source. Regenerate or check the JSON without accessing a device:

```sh
python3 scripts/export_modbus_json.py
python3 scripts/export_modbus_json.py --check
```

## Sources and confidence

Reviewed on **2026-09-12**. Source codes in the tables mean:

| Code | Source | How it is used |
| --- | --- | --- |
| R | [CLI implementation](scripts/sh10rt_lan.py) | What the shipped tools actually query and decode |
| P11 | [Sungrow residential hybrid protocol V1.1.11](https://raw.githubusercontent.com/Gnarfoz/Sungrow-Inverter/main/Modbus%20Information/TI_20251119_Communication%20Protocol%20of%20Residential%20Hybrid%20Inverter_V1.1.11_EN.pdf) | Manufacturer-authored reference, released 2025-11-17; third-party-hosted copy |
| P2 | [Sungrow residential hybrid protocol V1.1.2](https://manuals.plus/m/37ae50dd1fe804a563a1be36a9cf8b0c40ab0ccf8212775111ce8c241c31517a) | Earlier manufacturer-authored encoding comparison; third-party mirror |
| C1 | [Community SBR mapping](https://raw.githubusercontent.com/mkaiser/Sungrow-SHx-Inverter-Modbus-Home-Assistant/main/additional_sensors/modbus_sungrow_SBR_battery.yaml) | Optional battery-side diagnostics; not manufacturer-certified compatibility |

The manifest identifies reviewed files by SHA-256. A protocol revision is not an inverter firmware version. Review the document's model applicability, not just its filename. No manufacturer PDF or installation log is included in this repository.

## Addressing: the most important distinction

Every **logical register** below is one-based, following Sungrow's tables. The Modbus PDU uses **logical address minus one**.

| What is read | Register space / function | Logical address | Zero-based PDU address |
| --- | --- | --- | --- |
| First PV tracker's voltage | Input / FC04 | 5011 | 5010 |
| Inverter operating state | Input / FC04 | 13000 | 12999 |
| Start/Stop setting | Holding / FC03 | 13000 | 12999 |
| Inverter alarm word | Input / FC04 | 13050 | 13049 |
| EMS selection setting | Holding / FC03 | 13050 | 13049 |

**A register number without its register space is incomplete.** Input 13050 is an alarm word; holding 13050 is a control setting. These are not interchangeable. Do not prepend a generic `3xxxx`/`4xxxx` notation and then subtract an offset again.

The project's Python `read(address, count)` already subtracts one. Pass logical **5011**, not 5010. Many other libraries accept the PDU address directly; verify their convention before adapting an example. Details follow Sungrow section 1.2 [P11].

## Transport and access

| Interface | Access used by this project | Limits |
| --- | --- | --- |
| Native inverter Ethernet | Modbus TCP, port 502; configured unit ID | Identity and register support must be checked |
| WiNet Modbus forwarding | Modbus TCP, port 502; separately configured unit | Not equivalent to WiNet web login; optional blocks may fail |
| Authenticated WiNet web interface | CLI HTTP/WebSocket transport | This is not a raw Modbus TCP socket |
| Separate battery diagnostics | FC04 at unit 200 through native Ethernet | Community mapping; reference only, not queried by CLI |

The `values` command permits **FC04 only**. CLI status also reads FC03. Its only supported write is guarded FC06 Start; use the [explicit Start procedure](NETWORK-SCRIPTS.md#4-explicitly-start-the-selected-device-and-observe), not a raw-register write copied from a table.

The tools do not implement serial Modbus RTU. Do not add an extra polling master to an inverter/meter RS485 bus as if it were a separate TCP connection. Modbus unit, inverter serial, host IP and battery unit are distinct identifiers.

## Model identity

P11 appendix 1 distinguishes SH10RT variants:

| Protocol model label | Code (hex) | Decimal | Accepted by current project identity check |
| --- | --- | --- | --- |
| SH10RT | 0x0E03 | 3587 | No |
| SH10RT-20 | 0x0E13 | 3603 | No |
| SH10RT-V112 | 0x0E0F | 3599 | Yes, with nominal power raw 100 |
| SH10RT-V122 | 0x0E0B | 3595 | No |

The repository's general SH10RT name must not be interpreted as automatic support for all variants. Changing the model allowlist requires separate protocol/behavior validation. The current tool labels the accepted device as `SH10RT` in its output. [P11 appendix 1; R]

## Data types, scaling and invalid values

- `U16` / `S16`: unsigned / signed 16-bit integer, high byte first within a word.
- `U32` / `S32`: two registers, **low word first**, each word's high byte first.
- `U16[3]`: three independent 16-bit values, not one 48-bit integer. The same rule applies to eight module slots.
- `UTF8` / `ASCII`: successive bytes from the register words. The project's identity validator accepts a restricted ASCII serial.
- Multiply the decoded raw number by the listed multiplier. The multiplier applies after sign conversion.

For two raw words `lo`, `hi`:

```python
unsigned = lo | (hi << 16)
signed = unsigned - (1 << 32) if unsigned & (1 << 31) else unsigned
```

The protocol's unavailable markers are `0xFFFF` for U16, `0xFFFFFFFF` for U32, `0x7FFF` for S16 and `0x7FFFFFFF` for S32. Under signed encoding, `0xFFFF` can therefore be **-1**, not necessarily unavailable. Check the type before applying sentinel rules. [P11 section 1]

The `values` command masks these markers and missing words as unavailable. The `status` command also masks unavailable power, temperature and voltage readings as JSON `null`; unavailable power cannot verify generation. Status retains raw operating-state, Start/Stop and alarm words so unknown or invalid control data cannot bypass Start checks. Software voltage readings do not establish electrical isolation.

## Reading the tables

`Words` is the number of 16-bit registers. `Project use` distinguishes displayed/decoded values from data only present in a wider raw block and settings not read by the normal `values` command. Source codes show provenance; they do not certify live availability.

All tables through **Optional BMS** are input-register reads (FC04). The final **Holding settings** table uses FC03 for reading; those registers are writable in the protocol, but this table is not an instruction to write them. Ordinary inverter entries use the configured inverter unit. The BMS table uses the separate unit 200.

## Identity

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Serial | 4990–4999 | 4989 | 10 / UTF8 | 1 | — | identity. Project accepts an ASCII letter/digit/hyphen serial, 6–20 characters. [R;P11] |
| Model code | 5000 | 4999 | 1 / U16 | 1 | — | identity. Only 3599 / 0x0E0F is accepted by the current tools. [R;P11] |
| Rated AC power | 5001 | 5000 | 1 / U16 | 0.1 | kW | identity. Raw 100 is the required 10 kW identity check. [R;P11] |
| Output connection type | 5002 | 5001 | 1 / U16 enum | 1 | — | raw identity block. 0 single phase; 1 three-phase four-wire; 2 three-phase three-wire. Affects voltage interpretation. [R;P11] |

## PV and AC

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Internal temperature | 5008 | 5007 | 1 / S16 | 0.1 | degC | CLI;values.  [R;P11] |
| MPPT 1 voltage | 5011 | 5010 | 1 / U16 | 0.1 | V | values.  [R;P11] |
| MPPT 1 current | 5012 | 5011 | 1 / U16 | 0.1 | A | values.  [R;P11] |
| MPPT 2 voltage | 5013 | 5012 | 1 / U16 | 0.1 | V | values.  [R;P11] |
| MPPT 2 current | 5014 | 5013 | 1 / U16 | 0.1 | A | values.  [R;P11] |
| Total PV DC power | 5017–5018 | 5016 | 2 / U32 | 1 | W | values.  [R;P11] |
| AC voltages A/B/C | 5019–5021 | 5018 | 3 / U16[3] | 0.1 | V | CLI;values. Phase/line meaning depends on output type 5002; project displays phase labels. [R;P11] |
| Reactive AC power | 5033–5034 | 5032 | 2 / S32 | 1 | var | values.  [R;P11] |
| Power factor | 5035 | 5034 | 1 / S16 | 0.001 | — | values.  [R;P11] |
| Legacy grid frequency | 5036 | 5035 | 1 / U16 | 0.1 | Hz | CLI;values. Project can infer 0.01 Hz from the raw range; 5242 is preferred. [R;P11] |
| Grid frequency | 5242 | 5241 | 1 / U16 | 0.01 | Hz | CLI;values.  [R;P11] |
| AC currents A/B/C | 13031–13033 | 13030 | 3 / S16[3] | 0.1 | A | values.  [R;P11] |
| Active AC output | 13034–13035 | 13033 | 2 / S32 | 1 | W | CLI;values.  [R;P11] |

## Operating state

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Operating-state word | 13000 | 12999 | 1 / U16 enum | 1 | — | CLI;values. Not the holding Start/Stop word. See state table. [R;P11] |
| Power-flow flags | 13001 | 13000 | 1 / U16 bitset | 1 | — | raw only. Not decoded into flow arrows; do not infer signs from this reference. [R;P11] |

## Energy

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| PV energy today | 13002 | 13001 | 1 / U16 | 0.1 | kWh | values.  [R;P11] |
| PV lifetime energy | 13003–13004 | 13002 | 2 / U32 | 0.1 | kWh | values.  [R;P11] |
| Battery discharge today | 13026 | 13025 | 1 / U16 | 0.1 | kWh | values.  [R;P11] |
| Grid import today | 13036 | 13035 | 1 / U16 | 0.1 | kWh | values.  [R;P11] |
| Battery charge today | 13040 | 13039 | 1 / U16 | 0.1 | kWh | values.  [R;P11] |
| Grid export today | 13045 | 13044 | 1 / U16 | 0.1 | kWh | values.  [R;P11] |

## Meter and load

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Reported load | 13008–13009 | 13007 | 2 / S32 | 1 | W | values. Can describe a shared connection; do not sum duplicate reports. [R;P11] |
| Reported grid exchange | 13010–13011 | 13009 | 2 / S32 | 1 | W | values. Project interprets positive as export; opposite to documented meter-phase signs. [R;P11] |
| Meter phase 1 active power | 5603–5604 | 5602 | 2 / S32 | 1 | W | values. Valid forwarded meter required; P11 says positive import and negative export. CLI values retains the reported sign. [R;P11] |
| Meter phase 2 active power | 5605–5606 | 5604 | 2 / S32 | 1 | W | values. Valid forwarded meter required; P11 says positive import and negative export. CLI values retains the reported sign. [R;P11] |
| Meter phase 3 active power | 5607–5608 | 5606 | 2 / S32 | 1 | W | values. Valid forwarded meter required; P11 says positive import and negative export. CLI values retains the reported sign. [R;P11] |

## Battery

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Battery voltage | 13020 | 13019 | 1 / U16 | 0.1 | V | values.  [R;P11] |
| Legacy battery current | 13021 | 13020 | 1 / U16 | 0.1 | A | raw only. SHRT nominal legacy encoding; signedness differs in other model families. Project uses 5631 instead. [R;P11] |
| Legacy battery power | 13022 | 13021 | 1 / U16 | 1 | W | raw only. Use signed 5214–5215 instead. [R;P11] |
| Battery current | 5631 | 5630 | 1 / S16 | 0.1 | A | values. Preferred signed current. Direction labels are not inferred by the `values` command. [R;P11] |
| Battery power | 5214–5215 | 5213 | 2 / S32 | 1 | W | values. Signed measurement; CLI values does not infer a universal direction label. [R;P11] |
| State of charge | 13023 | 13022 | 1 / U16 | 0.1 | % | values.  [R;P11] |
| State of health | 13024 | 13023 | 1 / U16 | 0.1 | % | values.  [R;P11] |
| Battery temperature | 13025 | 13024 | 1 / S16 | 0.1 | degC | values.  [R;P11] |
| Permitted charge current | 5635 | 5634 | 1 / U16 | 1 | A | values. BMS limit, not actual current and not proof charging is active. [R;P11] |
| Permitted discharge current | 5636 | 5635 | 1 / U16 | 1 | A | values.  [R;P11] |
| Battery capacity | 5639 | 5638 | 1 / U16 | 0.01 | kWh | values. Reported capacity, not directly measured remaining usable energy. [R;P11] |

## Backup

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Backup currents A/B/C | 5720–5722 | 5719 | 3 / S16[3] | 0.1 | A | values.  [R;P11] |
| Total backup power | 5726–5727 | 5725 | 2 / S32 | 1 | W | values. P11 signed; P2 used U32. Decoder follows signed encoding; check firmware compatibility. [R;P11] |
| Backup voltages A/B/C | 5731–5733 | 5730 | 3 / U16[3] | 0.1 | V | values.  [R;P11] |
| Backup frequency | 5734 | 5733 | 1 / U16 | 0.01 | Hz | values.  [R;P11] |

## Fault blocks

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Inverter alarms | 13050–13051 | 13049 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| Grid faults | 13052–13053 | 13051 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| System faults 1 | 13054–13055 | 13053 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| System faults 2 | 13056–13057 | 13055 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| DC faults | 13058–13059 | 13057 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| Permanent faults | 13060–13061 | 13059 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BDC faults | 13062–13063 | 13061 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| Permanent BDC faults | 13064–13065 | 13063 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| Battery faults | 13066–13067 | 13065 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| Battery alarms | 13068–13069 | 13067 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BMS alarms 1 | 13070–13071 | 13069 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BMS protections | 13072–13073 | 13071 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BMS faults 1 | 13074–13075 | 13073 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BMS faults 2 | 13076–13077 | 13075 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |
| BMS alarms 2 | 13078–13079 | 13077 | 2 / U32 bitset | 1 | — | CLI raw;values selected labels. Two words form one bit field. CLI values reports each nonzero word separately. [R;P2;P11] |

## Optional BMS

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| BMS serial | 10711–10720 | 10710 | 10 / ASCII | 1 | — | reference only; not queried by CLI. Verify battery identity before using this separate community map; not queried by CLI. [C1] |
| BMS firmware | 10721–10730 | 10720 | 10 / ASCII | 1 | — | reference only; not queried by CLI. String returned by community mapping. [C1] |
| BMS voltage | 10741 | 10740 | 1 / U16 | 0.1 | V | reference only; not queried by CLI. Separate battery-side measurement. [C1] |
| BMS current | 10742 | 10741 | 1 / S16 | 0.1 | A | reference only; not queried by CLI. Separate battery-side measurement. [C1] |
| BMS temperature | 10743 | 10742 | 1 / U16 | 0.1 | degC | reference only; not queried by CLI. Unsigned in community mapping; negative-temperature interpretation not verified. [C1] |
| BMS state of charge | 10744 | 10743 | 1 / U16 | 0.1 | % | reference only; not queried by CLI. May differ from inverter SOC. [C1] |
| BMS state of health | 10745 | 10744 | 1 / U16 | 1 | % | reference only; not queried by CLI. Scale differs from inverter register 13024. [C1] |
| Maximum-cell position code | 10758 | 10757 | 1 / U16 raw | 1 | — | reference only; not queried by CLI. Position decoding not implemented. [C1] |
| Minimum-cell position code | 10760 | 10759 | 1 / U16 raw | 1 | — | reference only; not queried by CLI. Position decoding not implemented. [C1] |
| Module cell maxima, slots 1–8 | 10765–10772 | 10764 | 8 / U16[8] | 0.0001 | V | reference only; not queried by CLI. Each word is one slot; unused slots may be zero-filled. [C1] |
| Module cell minima, slots 1–8 | 10773–10780 | 10772 | 8 / U16[8] | 0.0001 | V | reference only; not queried by CLI. Each word is one slot; not individual-cell telemetry. [C1] |
| Contactor status code | 10789 | 10788 | 1 / U16 raw | 1 | — | reference only; not queried by CLI. Kept raw; no universal status decoding claimed. [C1] |

## Holding settings

| Field | Logical register(s) | PDU start | Words / type | Multiply by | Unit | Project use / notes |
| --- | --- | --- | --- | --- | --- | --- |
| Start/Stop | 13000 | 12999 | 1 / U16 | 1 | — | CLI read;guarded Start write. 207 / 0x00CF Start; 206 / 0x00CE Stop. Only the guarded CLI can send Start. [P11;R] |
| EMS selection | 13050 | 13049 | 1 / U16 | 1 | — | reference only. P11: 0 self-consumption; 2 forced; 3 external EMS; 4 VPP. Firmware-dependent. [P11] |
| Battery command | 13051 | 13050 | 1 / U16 | 1 | — | reference only. 0xAA charge; 0xBB discharge; 0xCC idle command. Context depends on EMS mode. [P11] |
| Requested battery power | 13052 | 13051 | 1 / U16 | 1 | W | reference only. This is a command setting, not measured battery power. [P11] |
| Maximum SOC setting | 13058 | 13057 | 1 / U16 | 0.1 | % | reference only. A configured bound, not actual SOC. [P11] |
| Minimum SOC setting | 13059 | 13058 | 1 / U16 | 0.1 | % | reference only. A configured bound, not actual SOC. [P11] |
| Feed-in limit value | 13074 | 13073 | 1 / U16 | 1 | W | reference only. P11 encoding; check enable state, firmware and applicable model. [P11] |
| Feed-in limit enable | 13087 | 13086 | 1 / U16 | 1 | — | reference only. 0xAA enabled; 0x55 disabled. Not an installation recommendation. [P11] |
| Feed-in limit ratio | 13088 | 13087 | 1 / U16 | 0.1 | % | reference only. P11 encoding; do not confuse with absolute watts. [P11] |
| Active-power limit enable | 13089 | 13088 | 1 / U16 | 1 | — | reference only. 0xAA enabled; 0x55 disabled. Separate from feed-in limiting. [P11] |
| Active-power limit ratio | 13090 | 13089 | 1 / U16 | 0.1 | % | reference only. P11 encoding; different control from grid export limit. [P11] |

## Operating-state values

This table separates the project's decoder from additional manufacturer-defined values. These are **state values**, not bit positions to OR together. The current Start preflight accepts only confirmed holding Stop and input state 8 or 16; documentation of another state does not extend that permission.

| Input 13000 value | Interpretation | Current decoder |
| --- | --- | --- |
| 0x0000 / 0x0040 | On-grid running | Running |
| 0x0008 | Standby | Standby |
| 0x0010 | Initial standby | Initial Standby |
| 0x0020 | Starting | Startup |
| 0x0100 | Fault | Fault |
| 0x1400 / 0x1200 / 0x1600 / 0x5500 | Manufacturer alternatives for standby / initial standby / starting / fault | Unmapped |
| 0x8000 / 0x0001 | Documented stop state | Unmapped; check holding Start/Stop separately |
| 0x1300 / 0x0002 | Stop via control interface | Unmapped |
| 0x1500 / 0x0004 | Emergency stop | Unmapped |
| 0x0400 | Battery-maintenance operation | Unmapped |
| 0x0800 | Forced energy-management operation | Unmapped |
| 0x1000 | Backup/off-grid operation | Unmapped |
| 0x4000 | External energy-management operation | Unmapped |
| 0x1111 | Initialization incomplete | Unmapped |
| 0x8100 / 0x0080 | Reduced-power operation | Unmapped |

The alternatives are from P11 appendix 2; this is a selected state reference, not every value in that appendix. Unknown values stay unknown in the tools. Use fresh power, alarms and the supported commissioning interface to establish actual behavior.

## Selected fault and alarm bits

The protocol groups input 13050–13079 into **15 two-word bit fields**. The `values` command reports the individual nonzero words and selected labels. Bits are numbered from zero.

| Input word | Word bit | Word mask | U32 base / bit | CLI values label |
| --- | --- | --- | --- | --- |
| 13050 | 5 | 0x0020 | 13050 / 5 | Parallel communication alarm |
| 13051 | 14 | 0x4000 | 13050 / 30 | Meter communication alarm |
| 13066 | 14 | 0x4000 | 13066 / 14 | BMS communication fault |
| 13070 | 5 | 0x0020 | 13070 / 5 | Battery voltage unbalance |
| 13070 | 9 | 0x0200 | 13070 / 9 | Cell voltage imbalance |
| 13072 | 9 | 0x0200 | 13072 / 9 | Pre-charge failed |
| 13072 | 10 | 0x0400 | 13072 / 10 | Abnormal external power-line status |
| 13072 | 13 | 0x2000 | 13072 / 13 | Voltage sampling fault |

Sources: current decoder [R], battery/bit tables [P2], appendix 4 [P11]. These are generic protocol meanings, not an installation diagnosis.

For example, bit 14 in word 13051 becomes bit **30** of the two-word block starting at 13050. A numeric cloud fault code, a raw word and a bit mask are different things. `input 13072 = 0x2000` names one protection flag; it is not “iSolarCloud error 8192”. A matching mask at another register can mean something else.

Multiple flags can be set together. An empty decoded list only means alarm-free data was observed if the entire expected flag block is available and fresh. Unsupported `0xFFFF` words and missing data must not be treated as healthy operation. This reference does not assign meanings to every unused or unknown bit.

## Firmware-dependent details

- **Backup power 5726–5727:** P2 describes U32; P11 describes S32. The `values` command now uses S32, including its unavailable marker. Positive normal-range values agree; negative values must not become multi-gigawatt output.
- **Battery current/power:** prefer signed 5631 and 5214–5215. Do not apply a universal signed/unsigned assumption to legacy 13021/13022.
- **Grid frequency:** prefer 5242 at 0.01 Hz. At 5036 the project's raw-range fallback can infer a 0.01 Hz variant; this is a compatibility inference, not a change to grid protection.
- **Meter signs:** P11 assigns import-positive to meter-phase power, while the project interprets net export-positive at 13010. The `values` command preserves phase signs and does not sum duplicate shared meters.
- **BMS diagnostics:** C1 is an implementation, not a manufacturer specification. Unsupported slots remain unavailable; minima/maxima describe cell extrema per slot, not every cell or a module's total voltage. The community temperature mapping is unsigned, and its negative-temperature behavior is not verified.
- **Partial raw blocks:** the `values` command reads input 13000 through 13046. A field ending at 13047 is not completely captured by that block. A block containing a word does not imply a complete decoded field.

## Polling and read failures

Read only the needed blocks, with sequential requests to each interface. The `values` command reads identity plus these inverter blocks: `5008/29`, `13000/47`, `13050/30`, `5214/2`, `5242/1`, `5631/1`, `5635/5`, `5603/6`, `5720/8`, `5731/4` (logical start / word count).

P11 cautions against frequent holding-register reads/writes forwarded through communication modules. The `values` command therefore keeps input-only access; do not turn the holding-settings reference into a high-frequency poll loop.

The `values` command reads each explicitly selected host once, sequentially, with a 1.1-second pause before each measurement block. It does not query the separate BMS unit-200 map. These are application choices, not a guarantee of a device's maximum polling rate.

Large reads spanning unsupported/reserved addresses may fail even if some included fields exist. A timeout can be a route, unit, firmware, service or load problem; it is not proof the inverter is electrically dead. Modbus exceptions need context ([Modbus application protocol, section 7](https://www.modbus.org/file/secure/modbusprotocolspecification.pdf#page=47)). For standard exception codes, 1 means unsupported function, 2 address error, 3 value error and 4 device failure. Preserve an unknown or malformed exception as an error rather than guessing its cause.

No protocol setting should be changed merely because a reference table lists it. See the [read-only examples](MODBUS-EXAMPLES.md), [CLI guide](NETWORK-SCRIPTS.md) and [troubleshooting guide](TROUBLESHOOTING.md).
