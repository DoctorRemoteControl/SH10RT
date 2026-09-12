# SH10RT command-line tools

Find Sungrow SH10RT inverters on your network and inspect their measurements in the terminal. This independent community project provides command-line tools, troubleshooting guidance and a Modbus register reference.

**Start here:** [quick start](#quick-start) · [CLI guide](NETWORK-SCRIPTS.md) · [Modbus JSON](reference/modbus-registers.json) · [troubleshooting](TROUBLESHOOTING.md)

Python **3.10 or later** is required. Device identity checks currently accept code **3599** (SH10RT-V112 in the reviewed protocol), rated **10 kW**. Other SH10RT variant codes require separate validation; see [model identity](MODBUS-REGISTERS.md#model-identity).

## Commands

| Command | Purpose | Device access |
| --- | --- | --- |
| `scan` | Find interfaces on an explicitly selected private subnet | Read-only discovery; no login attempts |
| `values` | Show PV tracker power, AC/grid, battery and other supported measurements | Input registers only; terminal report or JSON Lines |
| `status` | Inspect identity, state, Start/Stop and alarm words | Input and holding-register reads |
| `start` | Preview an explicit Start for one stopped device | Preview by default; exact serial and `--execute` required for a write |

## Quick start

Download or clone the whole repository and open a terminal in its directory. The executing computer must be able to reach the inverter network. Replace all example IP addresses with your actual private network addresses.

Find interfaces:

```sh
python3 scripts/sh10rt_lan.py scan --network 192.168.1.0/24
```

Read measurements:

```sh
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --transport modbus
```

Read two interfaces, or request machine-readable output:

```sh
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --host 192.168.1.101 --transport modbus
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --transport modbus --json
```

Each host is read once and the command exits. Requests are paced; allow at least 11 seconds per inverter, longer for unsupported or timed-out blocks. Multiple hosts share the supplied unit and transport. Compare serials before treating two addresses as separate inverters.

Inspect the software operating state and Start/Stop setting:

```sh
python3 scripts/sh10rt_lan.py status --host 192.168.1.100 --transport modbus --unit 1
```

On Windows, replace `python3` with `py -3`. Modbus TCP requires no extra packages. Authenticated WiNet HTTP/WebSocket access uses `--transport winet` and the optional dependency in `scripts/requirements.txt`; see [requirements](NETWORK-SCRIPTS.md#requirements).

### Platform launchers

| Platform | Terminal launcher |
| --- | --- |
| Linux | `./sh10rt.sh` |
| Windows | `sh10rt.cmd` |
| macOS | `./sh10rt.command` |

Launchers accept the same command arguments. Without arguments in an interactive terminal, they offer a text menu for scan, status, measurements and Start preview. They require Python and do not bundle an executable runtime. Windows and macOS native execution still need validation on those operating systems.

## Understanding measurements

- PV tracker power is calculated as voltage × current. Physical strings sharing one tracker cannot be measured separately through these fields.
- PV DC and AC output are separate measurements, sampled through separate requests.
- Missing or invalid readings appear as `unavailable`, or `null` in JSON. Partial block failures are reported and return exit code 2.
- Battery telemetry and meter-derived values are gated by available communication-status data. A reported SOC alone does not prove charging.
- Shared grid/load readings must not be summed across inverters. Battery power/current retain their reported signs; confirm direction against the relevant firmware documentation.
- Fault labels refer to register bits, not numeric iSolarCloud fault codes. Missing alarm data is not an all-clear result.
- Direct BMS unit-200 entries are included as reference material; the CLI does not query them.

The CLI does not configure grid protection, export limits, battery charging, parallel roles or firmware. Its guarded Start procedure is documented separately in the [CLI guide](NETWORK-SCRIPTS.md).

## Documentation

| Guide | Contents |
| --- | --- |
| [Network scripts](NETWORK-SCRIPTS.md) | Discovery, terminal measurements, WiNet, launchers, status, guarded Start and exit codes |
| [Modbus registers](MODBUS-REGISTERS.md) | Addresses, types, scaling, status/flag meanings, model and firmware caveats |
| [Modbus examples](MODBUS-EXAMPLES.md) | Input-only reads, TCP frames, word order, signed values, JSON and CSV usage |
| [Register JSON](reference/modbus-registers.json) | 83 typed register entries/ranges and eight selected fault bits |
| [Troubleshooting](TROUBLESHOOTING.md) | Connection failures, partial measurements, startup and low production |
| [Manual startup references](MANUAL-STARTUP-CLARIFICATION.md) | Manufacturer documentation of software startup |
| [Parallel operation](PARALLEL-OPERATION.md) | Device identity, shared measurements and configuration boundaries |
| [Contributing](CONTRIBUTING.md) | Development checks and public repository scope |

All public examples and tests use synthetic data. Store real credentials, identities, network addresses, telemetry and service records under the ignored `private/` directory or outside this checkout. Contributions should contain generic SH10RT help and reusable CLI functionality.
