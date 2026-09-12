# SH10RT troubleshooting

[Home](README.md) · [Register and flag reference](MODBUS-REGISTERS.md) · [CLI guide](NETWORK-SCRIPTS.md)

Collect identity, operating state, Start/Stop setting, current alarms and fresh measurements before deciding what action is appropriate. Save device output under `private/`; it contains installation data.

## Start with the symptom

| Symptom | First check | Interpretation / next step |
| --- | --- | --- |
| No discovery results | Subnet, route, port, unit and interface | Scan a network the executing computer can actually reach; one failed scan does not prove a dead inverter |
| WiNet web login works, Modbus does not | Modbus TCP port 502 and forwarding support | HTTP/WebSocket access does not establish Modbus support |
| Modbus identity is found, CLI `status` fails | Required holding/input register support | The input-only `values` command may still work; inspect the precise read failure |
| `Inverter identity mismatch` | Expected serial and actual device at that host/unit | Correct the endpoint after verifying the physical device; do not suppress identity checks |
| Module values are absent | CLI scope | The CLI reads inverter-reported battery values; the separate BMS map is reference only |
| A value shows `unavailable` or a read is partial | Per-block error and freshness | It is unavailable, not a confirmed zero; do not fill it with an old sample |
| Low or zero PV while interface responds | Operating state, Start/Stop, alarms and irradiation | Continue with the checks below before attributing a hardware cause |

## Detected but not producing

A responding communication module establishes network reachability. It does not establish that the inverter is running or that electrical inputs are suitable.

1. Verify the inverter serial and model using `status`. A native interface and a WiNet module may belong to the same device.
2. Check the reported input operating state separately from the holding-register Start/Stop setting. These are different register spaces even when a logical address is the same.
3. Read current fault and alarm flags. Do not equate register bit masks with numeric iSolarCloud fault codes.
4. Check timestamps and whether the measurements were actually available. Missing, stale or unsupported readings are not zero power or zero voltage.
5. Follow the commissioning and troubleshooting procedure for the exact inverter and firmware. A stopped device should only receive Start when its operating conditions permit it.

The [CLI guide](NETWORK-SCRIPTS.md) explains a read-only Start preview and the explicitly requested command. A successful acknowledgment proves neither completed startup nor sustained production. A timeout after a write leaves its outcome uncertain; inspect status before another invocation.

## Zero and unavailable readings

Zero-valued PV voltage, AC voltage, temperature or power in software cannot identify a failed component by itself. Device state, unsupported registers, invalid sentinels and communication failures can affect the displayed data. Software voltage readings must not be used to establish electrical isolation.

The `values` command masks known unavailable battery/meter data. An empty alarm list is only meaningful when the alarm block was successfully read; the snapshot includes `faults_available`. Unknown states and flag bits remain explicitly unknown.

## Low power

Compare both PV trackers' voltage, current and calculated power with total PV and AC readings. Tracker power is calculated from separately sampled voltage and current; multiple physical strings on one tracker cannot be separated by these registers. Irradiance, shading, operating state and configured controls must be assessed independently. A low reading alone does not establish an export limit or hardware fault.

The tools do not automatically change grid protection, export limits, battery controls or parallel roles. Confirm the relevant configuration in the manufacturer's commissioning interface.

## Battery and meter communication

Distinguish inverter-reported battery telemetry from optional direct BMS diagnostics. An interface may expose inverter SOC while not forwarding the separate BMS register map. Unsupported module values must remain unavailable. Communication faults and protection flags require interpretation against the exact manufacturer's documentation.

For a shared grid meter, confirm the supported topology and avoid counting a shared load/grid reading more than once. See [parallel operation](PARALLEL-OPERATION.md).

## Connection failures

Check the selected subnet, route, interface address, Modbus unit and supported protocol. WiNet HTTP/WebSocket and Modbus TCP are separate services. A missing response on one does not prove the inverter is off. Network and SSH failures should be resolved separately from electrical diagnosis.

## Collect a useful private diagnostic record

Record the software version, chosen interface type, operating state, relevant per-block errors and measurement times. Save CLI `status` or `values --json` output under `private/`.

Separate what was directly measured from what was inferred. A register mask such as `0x2000` must be accompanied by its register address and input/holding space; it is not a numeric cloud fault code. Do not post a complete network inventory, credentials, consumption history or installation report to this public repository. Describe a reproducible generic software issue using synthetic values instead.
