# LAN discovery, status checks and an explicit Start command

[Home](README.md) · [Modbus reference](MODBUS-REGISTERS.md) · [Troubleshooting](TROUBLESHOOTING.md)

[Requirements](#requirements) · [Launchers](#linux-windows-and-macos-launchers) · [Scan](#1-discover-interfaces--read-only) · [Status](#2-inspect-one-inverter--read-only) · [Start preview](#3-preview-the-intended-start-action--no-write) · [Explicit Start](#4-explicitly-start-the-selected-device-and-observe) · [Exit codes](#exit-codes-and-output)

The [Python tool](scripts/sh10rt_lan.py) provides four commands: **scan**, **values**, **status** and **start**. It supports the native SH10RT Modbus TCP connection and an authenticated local WiNet interface.

The tool can inspect **software Stop / Initial Standby** states and preview an explicit Start. It does not configure master/slave roles, change export limits, update firmware, reset a device or edit grid protection. Those settings cannot be inferred from discovering an IP address. See [parallel-operation concepts](PARALLEL-OPERATION.md) for monitoring considerations.

## Choose the connection

| Path | Services used | Requirements |
| --- | --- | --- |
| CLI `--transport modbus` | TCP 502; status uses input and holding registers | Correct host/unit; complete status register support |
| CLI `--transport winet` | HTTP 80 and WebSocket 8082 | Local WiNet account, password and `websocket-client`; `--unit` is ignored |

A WiNet web login and WiNet Modbus forwarding are different capabilities. Discovery verifies identity on responding Modbus interfaces but does not test every register needed by `status`. The input-only `values` command may obtain input readings from an interface that does not provide the holding registers required by CLI status.

## Show measurements in the terminal

After discovery, read one inverter:

```sh
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --transport modbus
```

Repeat `--host` to read multiple interfaces once, sequentially:

```sh
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --host 192.168.1.101 --transport modbus
```

The unit and transport apply to all selected hosts. Invoke the command separately when these differ. Compare serials: two interfaces can reach the same inverter; their values must not be added as separate devices.

Output includes PV tracker voltage/current and calculated watts, PV/AC totals, phase values, available meter and battery readings, backup values, and selected fault labels. Metric suffixes identify units (`_w`, `_v`, `_a`, `_hz`, `_pct`, `_kwh`). Phase arrays use A / B / C order. Battery current/power retain their reported signs without assigning universal charge/discharge labels. Meter phase power is import-positive; net exchange `export_w` is export-positive. A meter alarm makes derived import/export unavailable; raw reported load/export fields still require interpretation.

This is a one-shot command: it exits after reading the hosts and creates no server or database. Requests are separated by 1.1 seconds; one device normally takes at least 11 seconds, with failed reads extending this. Values come from separate requests, not an atomic snapshot. The sampling timestamp marks completion. Missing readings are `unavailable` (JSON `null`), with per-block errors and an explicit alarm-data availability flag. Exit code 2 indicates a partial or failed read; other hosts are still attempted.

For authenticated WiNet, use `--transport winet`. For WiNet Modbus forwarding, use `--transport modbus` with the verified interface/unit. This measurement command reads input registers only. It does not require holding-register support or query direct BMS unit 200. The [Modbus reference](MODBUS-REGISTERS.md) includes additional registers that are not queried by this command.

Save JSON Lines privately when needed:

```sh
mkdir -p private
python3 scripts/sh10rt_lan.py values --host 192.168.1.100 --transport modbus --json > private/values.jsonl
```

On Windows, create `private` with PowerShell `New-Item -ItemType Directory -Force private`, then use `py -3` for the Python command. The platform launcher terminal menu also offers **Show inverter measurements**.

## Requirements

- Python 3.10 or later.
- A machine with access to the inverter LAN. Running discovery on an unrelated network will not find these devices.
- Native Modbus TCP: no additional Python packages; port 502 must be reachable.
- WiNet: HTTP port 80 and WebSocket port 8082, valid local credentials and `websocket-client`.

From the repository directory, for WiNet support:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r scripts/requirements.txt
```

If Python reports that `ensurepip` is unavailable, install the distribution's matching Python venv package or use an existing Python environment with pip. Native Modbus access and discovery can still run with `python3` without a virtual environment.

## Linux, Windows and macOS launchers

Download or clone the **whole repository**, extract it to a writable folder and install **Python 3.10 or later**. These are executable launcher scripts, not standalone binaries with Python bundled. No administrator/root account is needed to run them. Keep the launchers alongside the `scripts/` directory.

| Platform | Launcher | How to open |
| --- | --- | --- |
| Linux | [`sh10rt.sh`](sh10rt.sh) | Run `./sh10rt.sh` in a terminal |
| Windows | [`sh10rt.cmd`](sh10rt.cmd) | Double-click, or run `.\sh10rt.cmd` in PowerShell / Command Prompt |
| macOS | [`sh10rt.command`](sh10rt.command) | Double-click in Finder, or run `./sh10rt.command` in Terminal |

On Windows, Python must be accessible through `py -3` or `python`. On Linux/macOS, the launcher looks for `python3` and then `python`. If archive extraction lost the executable permissions on Linux/macOS, run:

```bash
chmod +x sh10rt.sh sh10rt.command
```

With no arguments, an interactive terminal opens a menu for discovery, status, measurements and a **read-only Start preview**. Enter your actual LAN subnet or the target interface address. The menu never starts or stops an inverter. WiNet passwords are requested by the underlying tool without echoing them. In noninteractive use, no arguments prints help instead of waiting for input.

The same launchers accept every argument supported by the Python tool. Examples (replace the subnet/address with your own):

```bash
# Linux
./sh10rt.sh scan --network 192.168.1.0/24
./sh10rt.sh status --host 192.168.1.100 --transport modbus

# macOS
./sh10rt.command status --host 192.168.1.101 --transport winet
```

```powershell
# Windows: PowerShell or Command Prompt
.\sh10rt.cmd scan --network 192.168.1.0/24
.\sh10rt.cmd status --host 192.168.1.101 --transport winet
```

For an explicit Start, replace `python3 scripts/sh10rt_lan.py` in the [Start instructions below](#4-explicitly-start-the-selected-device-and-observe) with your platform's launcher. The exact serial check and `--execute` requirement still apply. Arguments and exit codes are passed through, and no command is retried automatically.

Scan, Modbus, help and input validation need no package download. On the first WiNet call, the launcher reuses `websocket-client` if available; otherwise it creates an ignored `.launcher-venv/` beside the launchers and installs `scripts/requirements.txt` there. This needs internet access, write permission to the repository folder, and Python's `venv`/`pip` support. Installation messages go to stderr so terminal JSON output can still be redirected to a file. The system Python environment is not modified. If setup fails, the operation stops with exit code 2 before contacting the inverter; install the missing Python components and retry. You can also activate your own environment with the dependency installed before launching.

Linux execution and both POSIX wrappers are tested here, including paths containing spaces. The Windows launcher has been reviewed but has not been executed on Windows; Finder behavior has not been tested on macOS.

## 1. Discover interfaces — read only

Replace the example subnet with the actual inverter LAN:

```bash
python3 scripts/sh10rt_lan.py scan --network 192.168.1.0/24
```

Discovery checks the selected Modbus unit ID (default 1) on port 502 and the HTTP page title on port 80. It never sends a write or credentials. A Modbus match includes a verified model code, rated power and serial number. A WiNet page is reported as a **candidate interface**; log in with `status` to verify the attached inverter.

The scan accepts RFC1918 private IPv4 subnets containing at most 1,024 addresses, with bounded concurrency and configurable timeouts:

```bash
python3 scripts/sh10rt_lan.py scan --network 192.168.1.0/24 --workers 8 --timeout 2
```

A native inverter and its WiNet module can have different IP addresses. Multiple interfaces do not necessarily mean multiple inverters. Compare serial numbers before choosing a target.

The `modbus` transport label identifies a responding protocol, not the physical socket or implementation behind it. A WiNet module may also expose Modbus TCP, depending on its firmware and configuration.

If a native Modbus device uses another known unit ID, specify it explicitly with `--unit`. Discovery does not brute-force all Modbus unit IDs. A missing result does not prove that the inverter is off: routing, firewall rules, module state, model support or a disabled Modbus service can prevent detection.

## 2. Inspect one inverter — read only

Native LAN example:

```bash
python3 scripts/sh10rt_lan.py status --host 192.168.1.100 --transport modbus
```

WiNet example, after installing the dependency:

```bash
python scripts/sh10rt_lan.py status --host 192.168.1.101 --transport winet --username admin
```

WiNet prompts for the password without echoing it. For noninteractive use, `SH10RT_PASSWORD` may supply the password from the environment. There is no password command-line flag and no embedded default password. Do not enable WebSocket debug tracing when using real credentials.

Each result is a JSON object on its own line. Status includes:

- Verified serial number and model.
- Input operating state, separately from the holding-register Start/Stop setting.
- AC active power, PV and grid voltages, grid frequency and internal temperature.
- Nonzero current fault/alarm registers, plus the meter and parallel communication alarm flags.

Both documented Running values (`0x0000` and `0x0040`) are recognized. Frequency reads prefer logical input register 5242 (0.01 Hz). If that register is unavailable or invalid, register 5036 is used. The fallback distinguishes a possible 0.01 Hz variant from the documented 0.1 Hz encoding by raw ranges corresponding to 40–70 Hz; it reports the raw value, register, scale and an explicit inference note. These bounds only select an encoding and do not change grid protection. Zero remains zero; other unsupported values produce `null`, not a misleading frequency. This is a compatibility inference, not a universal firmware rule.

A zero voltage reported by the inverter is **not proof of electrical isolation**. See the [troubleshooting guide](TROUBLESHOOTING.md).

## 3. Preview the intended Start action — no write

Check the serial number against the intended physical device. Replace `SERIAL_FROM_STATUS` below with that exact serial:

```bash
python3 scripts/sh10rt_lan.py start \
  --host 192.168.1.100 --transport modbus \
  --serial SERIAL_FROM_STATUS
```

Without `--execute`, this command reads and checks the device but does not send Start. A WiNet preview uses the same syntax with `--transport winet` and the maintenance login.

The tool refuses to start an unsupported model, a mismatched serial, a device with current alarm/fault bits, or a stopped device outside the supported Standby / Initial Standby states. It does not provide a bypass flag for these checks. If Start is already enabled, it reports that fact and sends no command, even if production is currently zero.

## 4. Explicitly start the selected device and observe

Only use this on a device ready to operate, not one deliberately stopped for maintenance or because of a fault:

```bash
python3 scripts/sh10rt_lan.py start \
  --host 192.168.1.100 --transport modbus \
  --serial SERIAL_FROM_STATUS --execute --wait 330
```

For WiNet:

```bash
python scripts/sh10rt_lan.py start \
  --host 192.168.1.101 --transport winet --username admin \
  --serial SERIAL_FROM_STATUS --execute --wait 330
```

Immediately before writing, the script rechecks identity, Start/Stop, operating state and alarms. Its only supported write is:

| Connection | Command |
| --- | --- |
| Native Modbus TCP | FC06, logical holding register 13000, zero-based wire address **12999**, value **207 / Start** |
| Authenticated WiNet | The documented Boot command: `service=param`, `type=3`, `list=[{"power_switch":"1"}]` for the identified device |

The script sends at most one command per invocation. It never retries a write automatically. If an acknowledgment is missing or the read-back fails, it reports an unconfirmed outcome. The command may have reached the inverter; inspect status before considering another manual invocation.

`--wait 330` observes for up to approximately 330 seconds, plus the time spent in individual network requests. It requires two consecutive readings with Running, positive AC active power and no current alarm bits before reporting `generation_verified`. A timeout means generation was not verified in that interval; it does not trigger another Start command.

Without `--wait`, success after a write verifies acknowledgment and the Start setting only, not sustained production. Do not run concurrent Start invocations for the same inverter. This is a commissioning aid, not an unattended restart service.

## Running through an SSH host on the inverter LAN

If only another computer can reach the inverter LAN, run the tool there. The example SSH alias `inverter-host` must already provide access to your server; configure its address and authentication locally. The tool does not create tunnels or modify SSH settings.

Example deployment to a temporary directory:

```bash
ssh inverter-host 'mkdir -p /tmp/sh10rt-tools'
scp scripts/sh10rt_lan.py scripts/requirements.txt inverter-host:/tmp/sh10rt-tools/
ssh inverter-host 'python3 /tmp/sh10rt-tools/sh10rt_lan.py scan --network 192.168.1.0/24'
```

For interactive WiNet login, open an interactive SSH session, create a virtual environment in `/tmp/sh10rt-tools`, install its `requirements.txt`, and run `status` there. Credentials should not be placed in an SSH command string or committed to the repository.

If SSH times out before authentication, verify VPN reachability and the server's SSH service first. An SSH timeout is not an inverter diagnosis.

## Command options

Run `python3 scripts/sh10rt_lan.py scan --help`, `status --help` or `start --help` for the corresponding parser output.

| Scope | Option | Default / accepted values |
| --- | --- | --- |
| `scan` | `--network` | Required private IPv4 CIDR, at most 1,024 addresses |
| `scan` | `--workers` | 16; range 1–32 |
| `scan` | `--timeout` | 1 second; range 1–10 |
| All commands | `--unit` | 1; range 1–247; ignored by authenticated WiNet |
| `status`, `start`, `values` | `--host`, `--transport` | Required; private IPv4 and `modbus` or `winet` |
| `status`, `start`, `values` | `--timeout` | 5 seconds; range 1–30 |
| `status`, `start`, `values` | `--username` | `admin`; local WiNet account only |
| `values` | `--host` | Repeat to read multiple hosts sequentially; same transport/unit/account |
| `values` | `--json` | Off; JSON Lines instead of a terminal report |
| `start` | `--serial` | Required exact inverter serial |
| `start` | `--execute` | Off; permits the single guarded write |
| `start` | `--wait` | 0; observation duration 0–1,200 seconds |

Timeouts apply to individual network operations; a complete scan or status read can take longer. `SH10RT_PASSWORD` is an optional environment variable for noninteractive WiNet login. A `.env` file is not loaded automatically.

## Exit codes and output

| Code | Meaning |
| --- | --- |
| 0 | Requested scan/status/values/preview completed, Start already enabled, Start setting verified, or generation verified; inspect the event name for the exact result |
| 2 | Invalid command-line input, refused precondition, connection/read failure, partial `values` result or another checked error |
| 3 | Observation ended without confirming generation |
| 4 | Discovery found no supported interface |
| 5 | A write was attempted but its outcome or read-back is unconfirmed; no automatic retry |
| 130 | Interrupted; an already transmitted command may still take effect |

Logs contain real local IP addresses and inverter serial numbers. Store captured output under the ignored `private/` directory and keep installation captures outside the public repository. Passwords and session tokens are not included in the tool's events.

### Interpret the event, not just exit code zero

| JSON event | Meaning |
| --- | --- |
| `discovered` / `scan_complete` | Interface discovery result / completion; not electrical verification |
| `status` | One read-only device snapshot |
| `values` | One decoded measurement report with `--json`; terminal output is the default |
| `preflight` / `dry_run` | Checked state / proposed Start without a write |
| `no_change` | Start was already enabled; no command sent |
| `start_acknowledged` / `read_back` | Acknowledgment / read-back after the single requested command |
| `generation_verified` | Two consecutive healthy Running samples with positive AC power |
| `not_yet_generating` | Observation interval ended without that confirmation |
| `write_outcome_unconfirmed` | A write may have reached the inverter; inspect before another invocation |
| `error` / `interrupted` | Failure or user interruption |

Scan, status, Start and `values --json` emit one JSON object per line. Plain `values` prints a terminal report. Keep captured output under `private/`. Exit code zero from discovery, status or a preview does not imply that power generation was verified.

## Validation and known limits

Run the offline tests:

```bash
python3 -m unittest discover -s tests -v
```

With `websocket-client` installed, this includes a local WiNet HTTP/WebSocket simulator using the actual client library. Without it, that integration test is skipped. The remaining tests cover native Modbus request/response framing, separate input/holding register spaces, identity checks, dry-run behavior, alarm handling, single-write behavior and generation verification.

The implementation currently accepts only device code **3599** with a nominal rating of **10 kW**. The reviewed manufacturer table calls this variant SH10RT-V112; see [model identity](MODBUS-REGISTERS.md#model-identity). The automated write path is tested against simulators.

WiNet support targets the local HTTP/WebSocket API implemented by the client. Other module/firmware versions may differ. A logger with multiple attached device entries is deliberately refused rather than selecting an arbitrary target. No complete electrical installation check, export-limit verification or universal Sungrow compatibility claim is implied by a successful status read.
