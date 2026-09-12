# Parallel operation and monitoring

Parallel configuration depends on the precise inverter models, firmware, meter topology and applicable commissioning requirements. Use the manufacturer's matching installation manual for supported wiring and parameters. This guide covers how the tools represent such systems; it is not a wiring or parameter prescription.

## Identify each inverter

Select each physical inverter by its interface address and verify its serial number. A native Ethernet interface and a WiNet module can reach the same device. Do not create two logical inverters merely because two IP addresses respond. Modbus unit IDs are interface-specific; do not infer the WiNet unit from a native-LAN slave address.

The CLI does not assign master/slave roles. Role assignments, RS485 communication, meter settings and export control must be verified through the supported commissioning interface.

## Shared measurements

- Inverter PV and AC power are per-device measurements. Combined totals require fresh readings from every selected inverter.
- Grid/load values may describe a common connection point. Do not add duplicate shared readings together.
- A shared meter may be available through only one inverter. The `values` command checks meter communication and phase-data availability before reporting derived grid import/export.
- Battery SOC is displayed per inverter. A simple average of SOC percentages is not a valid combined energy estimate when usable capacities differ.

## Configuration changes

The `values` command is input-only. The network CLI's explicit Start command does not establish parallel roles, repair RS485 communication, set an export limit or configure storage.

Discovering devices is insufficient to determine a permitted export setting. Keep the actual topology, commissioning parameters and verification records in your private installation documentation, outside the public repository.
