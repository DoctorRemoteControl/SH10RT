#!/usr/bin/env python3
"""Discover SH10RT interfaces, show terminal measurements, inspect state and preview Start."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import getpass
import ipaddress
import json
import os
import re
import socket
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MODEL_CODE = 3599
STOP, START = 206, 207
RUNNING_STATES = (0, 64)
STATES = {0: "Running", 8: "Standby", 16: "Initial Standby", 32: "Startup", 64: "Running", 256: "Fault"}
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(n) for n in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


class DeviceError(Exception):
    """A failed check or device operation; messages must never contain credentials."""


class UnknownWriteOutcome(DeviceError):
    """A command may have arrived. Never resend it automatically."""


def emit(event, **fields):
    print(json.dumps({"time": datetime.now(timezone.utc).isoformat(),
                      "event": event, **fields}), flush=True)


def lan_ip(value):
    try:
        address = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError:
        raise argparse.ArgumentTypeError("Use a numeric private IPv4 address.") from None
    if not any(address in network for network in PRIVATE_NETWORKS):
        raise argparse.ArgumentTypeError("Only RFC1918 private LAN addresses are accepted.")
    return str(address)


def scan_network(value):
    try:
        network = ipaddress.IPv4Network(value, strict=True)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Use a network CIDR, for example 192.168.1.0/24.") from None
    if network.num_addresses > 1024 or not any(network.subnet_of(n) for n in PRIVATE_NETWORKS):
        raise argparse.ArgumentTypeError("Select a private LAN subnet of /22 or smaller (at most 1024 addresses).")
    return network


def integer(lo, hi):
    def parse(value):
        try:
            result = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("Expected an integer.") from None
        if not lo <= result <= hi:
            raise argparse.ArgumentTypeError(f"Expected {lo} through {hi}.")
        return result
    return parse


def recv_exact(sock, size):
    data = bytearray()
    while len(data) < size:
        part = sock.recv(size - len(data))
        if not part:
            raise DeviceError("Connection closed before a complete Modbus response.")
        data.extend(part)
    return bytes(data)


class Modbus:
    transport = "modbus"

    def __init__(self, host, unit=1, timeout=3, port=502):
        self.host, self.unit, self.timeout, self.port = host, unit, timeout, port
        self.transaction = 0

    def exchange(self, pdu):
        self.transaction = self.transaction % 65535 + 1
        packet = struct.pack(">HHHB", self.transaction, 0, len(pdu) + 1, self.unit) + pdu
        with socket.create_connection((self.host, self.port), self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(packet)
            tid, protocol, length, unit = struct.unpack(">HHHB", recv_exact(sock, 7))
            if tid != self.transaction or protocol != 0 or unit != self.unit or not 2 <= length <= 254:
                raise DeviceError("Invalid Modbus response header.")
            body = recv_exact(sock, length - 1)
        if body[0] == (pdu[0] | 0x80):
            raise DeviceError(f"Modbus exception {body[1] if len(body) > 1 else 'missing code'}.")
        if body[0] != pdu[0]:
            raise DeviceError("Unexpected Modbus function code.")
        return body

    def read(self, address, count, holding=False):
        if not 1 <= count <= 125 or not 1 <= address <= 65536 - count + 1:
            raise DeviceError("Invalid register range.")
        try:
            body = self.exchange(struct.pack(">BHH", 3 if holding else 4, address - 1, count))
        except OSError:
            raise DeviceError("Modbus connection or read timed out/failed.") from None
        if len(body) != 2 + count * 2 or body[1] != count * 2:
            raise DeviceError("Invalid Modbus register response length.")
        return list(struct.unpack(">" + "H" * count, body[2:]))

    def identity(self):
        words = self.read(4990, 13)
        try:
            serial = struct.pack(">10H", *words[:10]).rstrip(b"\0 ").decode("ascii")
        except (UnicodeError, struct.error):
            raise DeviceError("Invalid inverter serial number.") from None
        if not re.fullmatch(r"[A-Za-z0-9-]{6,20}", serial):
            raise DeviceError("Missing or invalid inverter serial number.")
        if words[10] != MODEL_CODE or words[11] != 100:
            raise DeviceError("Device is not the supported SH10RT (code 3599, rated 10 kW).")
        return serial

    def start_once(self):
        # The only Modbus write supported: logical holding 13000, wire 12999, Start 207.
        request = struct.pack(">BHH", 6, 12999, START)
        try:
            response = self.exchange(request)
            if response != request:
                raise DeviceError("Start acknowledgment does not match the command.")
        except (DeviceError, OSError):
            raise UnknownWriteOutcome("Start outcome unconfirmed. Read status before any manual retry; command was not resent.") from None

    def close(self):
        pass


class ReadOnlyModbus(Modbus):
    def __init__(self, *args, pause=0, stop=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.pause, self.stop, self.last_request = pause, stop, None

    def exchange(self, pdu):
        if not pdu or pdu[0] != 4:
            raise DeviceError("Values permits input-register reads only.")
        if self.last_request is not None:
            delay = max(0, self.pause - (time.monotonic() - self.last_request))
            if self.stop is not None:
                if self.stop.wait(delay):
                    raise DeviceError("Polling stopped.")
            elif delay:
                time.sleep(delay)
        if self.stop is not None and self.stop.is_set():
            raise DeviceError("Polling stopped.")
        try:
            return super().exchange(pdu)
        finally:
            self.last_request = time.monotonic()


def number(words, address, scale=1, signed=False, wide=False):
    """Decode documented sentinels before scaling; retain raw words separately."""
    value = words.get(address)
    if value is None:
        return None
    bits = 32 if wide else 16
    if wide:
        high = words.get(address + 1)
        if high is None:
            return None
        value |= high << 16
    if value == (2 ** (bits - 1) - 1 if signed else 2**bits - 1):
        return None
    if signed and value >= 2 ** (bits - 1):
        value -= 2**bits
    return round(value * scale, 4)


def decode(words):
    def n(a, scale=1, signed=False, wide=False):
        return number(words, a, scale, signed, wide)
    mppts = []
    for i in range(2):
        voltage, current = n(5011 + 2*i, .1), n(5012 + 2*i, .1)
        mppts.append({"name": f"MPPT {i+1}", "voltage_v": voltage,
                      "current_a": current, "power_w": round(voltage*current, 1)
                      if voltage is not None and current is not None else None})
    flags = [{"register": a, "raw": words[a], "bits": [i for i in range(16) if words[a] & 1 << i]}
             for a in range(13050, 13080) if a in words and words[a] not in (0, 65535)]
    labels = {(13066, 14): "BMS communication fault", (13070, 5): "Battery voltage unbalance",
              (13070, 9): "Cell voltage imbalance", (13072, 9): "Pre-charge failed",
              (13072, 10): "Abnormal external power-line status",
              (13072, 13): "Voltage sampling fault", (13051, 14): "Meter communication alarm",
              (13050, 5): "Parallel communication alarm"}
    for flag in flags:
        flag["labels"] = [labels.get((flag["register"], bit), f"Unmapped bit {bit}") for bit in flag["bits"]]
    meter_phases = [n(a, signed=True, wide=True) for a in (5603, 5605, 5607)]
    meter_alarm = words.get(13051)
    meter_available = (meter_alarm is not None and meter_alarm != 65535
                       and not meter_alarm & (1 << 14)
                       and all(v is not None for v in meter_phases))
    net_export = n(13010, signed=True, wide=True) if meter_available else None
    comm_status = words.get(13066)
    bat_valid = (comm_status is not None and comm_status != 65535
                 and not comm_status & (1 << 14)
                 and n(13023, .1) is not None and 0 <= n(13023, .1) <= 100)
    def bat(a, scale=1, signed=False):
        return n(a, scale, signed) if bat_valid else None
    frequency = n(5242, .01)
    freq_source = "5242 · 0.01 Hz"
    if frequency is None or (frequency != 0 and not 40 <= frequency <= 70):
        raw = words.get(5036)
        scale = .1 if raw is not None and (raw == 0 or 400 <= raw <= 700) else (
            .01 if raw is not None and 4000 <= raw <= 7000 else None)
        frequency = round(raw*scale, 2) if scale else None
        freq_source = "5036 · legacy scale inferred from value" if scale == .01 else "5036 · legacy 0.1 Hz"
    metrics = {
        "pv_w": n(5017, wide=True), "ac_w": n(13034, signed=True, wide=True),
        "temperature_c": n(5008, .1, True), "frequency_hz": frequency,
        "frequency_source": freq_source, "pv_today_kwh": n(13002, .1),
        "pv_total_kwh": n(13003, .1, wide=True), "load_w": n(13008, signed=True, wide=True),
        "export_w": n(13010, signed=True, wide=True),
        "phase_voltage_v": [n(a, .1) for a in (5019, 5020, 5021)],
        "phase_current_a": [n(a, .1, True) for a in (13031, 13032, 13033)],
        "meter_phase_w": meter_phases if meter_available else [None, None, None],
        "meter_phase_sum_w": sum(meter_phases) if meter_available else None,
        "meter_grid_import_w": max(0, -net_export) if net_export is not None else None,
        "meter_grid_export_w": max(0, net_export) if net_export is not None else None,
        "reactive_var": n(5033, signed=True, wide=True), "power_factor": n(5035, .001, True),
        "import_today_kwh": n(13036, .1), "export_today_kwh": n(13045, .1),
        "battery_voltage_v": bat(13020, .1), "battery_current_a": n(5631, .1, True) if bat_valid else None,
        "battery_current_source": "5631 · signed 0.1 A",
        "battery_power_w": n(5214, signed=True, wide=True) if bat_valid else None,
        "battery_soc_pct": bat(13023, .1), "battery_soh_pct": bat(13024, .1),
        "battery_temperature_c": bat(13025, .1, True),
        "allowed_charge_a": n(5635) if bat_valid else None,
        "allowed_discharge_a": n(5636) if bat_valid else None,
        "battery_capacity_kwh": n(5639, .01) if bat_valid else None,
        "charge_today_kwh": n(13040, .1), "discharge_today_kwh": n(13026, .1),
        "backup_w": n(5726, signed=True, wide=True), "backup_voltage_v": [n(a, .1) for a in (5731, 5732, 5733)],
        "backup_current_a": [n(a, .1, True) for a in (5720, 5721, 5722)],
        "backup_frequency_hz": n(5734, .01),
    }
    return {"state": STATES.get(words.get(13000), f"Unknown ({words.get(13000, 'unavailable')})"),
            "metrics": metrics, "mppts": mppts, "flags": flags,
            "meter_available": meter_available,
            "battery_available": bat_valid,
            "faults_available": all(a in words and words[a] != 65535 for a in range(13050, 13080))}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DeviceError("HTTP redirect refused; verify the device address.")


def http_get(host, path, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(f"http://{host}{path}", timeout=timeout) as response:
            data = response.read(1024 * 1024 + 1)
    except (OSError, urllib.error.URLError):
        # urllib exceptions can include a query string containing a session token.
        raise DeviceError("Device HTTP request failed.") from None
    if len(data) > 1024 * 1024:
        raise DeviceError("Device HTTP response exceeds size limit.")
    return data


class WiNet(Modbus):
    transport = "winet"

    def __init__(self, host, username, password, timeout=5):
        self.host, self.timeout = host, timeout
        self.ws = None
        self.token, self.device = "", None
        self.admin = False
        try:
            import websocket
        except ImportError:
            raise DeviceError("WiNet needs websocket-client: install scripts/requirements.txt.") from None
        try:
            self.ws = websocket.create_connection(
                f"ws://{host}:8082/ws/home/overview", timeout=timeout,
                origin=f"http://{host}", http_no_proxy=[host], redirect_limit=0)
            connected = self.request({"service": "connect"})
            self.token = connected.get("token", "")
            if not self.token:
                raise DeviceError("WiNet returned no connection token.")
            login = self.request({"service": "login", "username": username, "passwd": password})
            self.token = login.get("token", "")
            self.admin = str(login.get("uid")) == "3"
            if not self.token:
                raise DeviceError("WiNet returned no authenticated token.")
        except Exception as exc:
            self.close()
            if isinstance(exc, DeviceError):
                raise
            raise DeviceError("WiNet connection or login failed.") from None

    def request(self, payload):
        try:
            self.ws.send(json.dumps({"lang": "en_us", "token": self.token, **payload}))
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                self.ws.settimeout(max(0.1, deadline - time.monotonic()))
                raw = self.ws.recv()
                if not raw or len(raw) > 1024 * 1024:
                    raise DeviceError("WiNet connection closed or response too large.")
                data = json.loads(raw)
                result = data.get("result_data") or {}
                service = result.get("service")
                if service == payload["service"] or (not service and data.get("result_code") != 1):
                    if data.get("result_code") != 1:
                        raise DeviceError(f"WiNet rejected {payload['service']} request.")
                    return result
        except DeviceError:
            raise
        except Exception:
            raise DeviceError(f"WiNet {payload['service']} response failed or timed out.") from None
        raise DeviceError("WiNet response timed out.")

    def identity(self):
        listing = self.request({"service": "devicelist", "type": "0", "is_check_token": "0"})
        # Refuse ambiguous loggers instead of guessing which attached inverter to start.
        devices = listing.get("list", [])
        if not isinstance(devices, list) or len(devices) != 1:
            raise DeviceError("Expected exactly one attached device on this WiNet; inspect this logger manually.")
        device = devices[0]
        if (not isinstance(device, dict) or not device.get("dev_id")
                or str(device.get("dev_code")) != str(MODEL_CODE)
                or str(device.get("dev_type")) != "35" or str(device.get("link_status")) != "1"):
            raise DeviceError("WiNet has no single online supported SH10RT.")
        self.device = device
        serial = super().identity()
        if serial != device.get("dev_sn"):
            raise DeviceError("WiNet device list and inverter serial register disagree.")
        return serial

    def read(self, address, count, holding=False):
        if self.device is None:
            raise DeviceError("Identify the WiNet device before reading registers.")
        query = urllib.parse.urlencode({"lang": "en_us", "token": self.token,
            "dev_id": self.device["dev_id"], "dev_type": self.device["dev_type"],
            "dev_code": self.device["dev_code"], "type": "3", "param_addr": address,
            "param_num": count, "param_type": "1" if holding else "0"})
        try:
            result = json.loads(http_get(self.host, "/device/getParam?" + query, self.timeout))
            if result.get("result_code") != 1:
                raise DeviceError("WiNet register read rejected.")
            raw = re.sub(r"\s", "", result["result_data"]["param_value"])
            if len(raw) != count * 4 or not re.fullmatch(r"[0-9A-Fa-f]+", raw):
                raise DeviceError("WiNet returned invalid register data.")
            return [int(raw[i:i + 4], 16) for i in range(0, len(raw), 4)]
        except (ValueError, KeyError, TypeError, AttributeError):
            raise DeviceError("Invalid WiNet register response.") from None

    def start_once(self):
        if not self.admin:
            raise DeviceError("WiNet Start requires a confirmed maintenance/admin session.")
        try:
            result = self.request({"service": "param", "dev_code": str(self.device["dev_code"]),
                "dev_type": str(self.device["dev_type"]), "devid_array": [str(self.device["dev_id"])],
                "type": "3", "count": "1", "list": [{"power_switch": "1"}]})
            rows = result.get("list") if isinstance(result, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise DeviceError("Malformed WiNet Boot acknowledgment.")
            children = [row for row in rows
                        if row.get("param_name") == "I18N_COMMON_POWER_ON"]
            if not children or any(row.get("result") != 0 for row in children):
                raise DeviceError("WiNet Boot not acknowledged.")
        except DeviceError:
            raise UnknownWriteOutcome("Boot outcome unconfirmed. Read status before any manual retry; command was not resent.") from None

    def close(self):
        if self.ws is not None:
            try:
                self.ws.close(timeout=1)
            except Exception:
                pass
            self.ws = None


def grid_frequency(client, legacy_raw):
    """Prefer documented 0.01 Hz data; expose the observed legacy scale inference."""
    try:
        raw = client.read(5242, 1)[0]
    except DeviceError:
        raw = None
    if raw == 0 or (raw is not None and 4000 <= raw <= 7000):
        return {"grid_frequency_Hz": raw / 100, "grid_frequency_register": 5242,
                "grid_frequency_raw": raw, "grid_frequency_scale": 0.01,
                "grid_frequency_note": "Documented high-precision register."}
    # Firmware/interface variants may encode this legacy field at different scales.
    # These bounds disambiguate encodings; they are NOT grid protection settings.
    scale = 0.1 if legacy_raw == 0 or 400 <= legacy_raw <= 700 else (
        0.01 if 4000 <= legacy_raw <= 7000 else None)
    return {"grid_frequency_Hz": legacy_raw / (100 if scale == 0.01 else 10) if scale is not None else None,
            "grid_frequency_register": 5036, "grid_frequency_raw": legacy_raw,
            "grid_frequency_scale": scale,
            "grid_frequency_note": (
                "High-precision data unavailable; documented 0.1 Hz legacy scale." if scale == 0.1 else
                "High-precision data unavailable; 0.01 Hz legacy variant inferred from raw range." if scale == 0.01 else
                "Frequency unavailable: unsupported or invalid legacy encoding.")}


VALUE_BLOCKS = ((5008, 29), (13000, 47), (13050, 30), (5214, 2), (5242, 1),
                (5631, 1), (5635, 5), (5603, 6), (5720, 8), (5731, 4))


def read_values(client, pause=1.1):
    """Read one identified inverter, with partial failures kept explicit. No holdings or writes."""
    serial = client.identity()
    words, errors = {}, []
    last_keepalive = time.monotonic()
    for address, count in VALUE_BLOCKS:
        if pause:
            time.sleep(pause)
        if isinstance(client, WiNet) and time.monotonic() - last_keepalive >= 10:
            try:
                client.ws.send(json.dumps({"service": "ping", "lang": "en_us", "token": client.token}))
            except Exception:
                raise DeviceError("WiNet keepalive failed during measurement read.") from None
            last_keepalive = time.monotonic()
        try:
            raw = client.read(address, count)
            if len(raw) != count:
                raise DeviceError("Incomplete register block.")
            words.update(zip(range(address, address + count), raw))
        except DeviceError as exc:
            errors.append({"register": address, "count": count, "message": str(exc)})
    if not words:
        raise DeviceError("Identity verified, but all measurement blocks failed.")
    return {"host": client.host, "transport": client.transport, "serial": serial,
            "model": "SH10RT", "sampled_at": datetime.now(timezone.utc).isoformat(),
            "partial": bool(errors), "errors": errors, **decode(words)}


def print_values(sample):
    def formatted(value):
        if value is None:
            return "unavailable"
        if isinstance(value, list):
            return " / ".join(formatted(item) for item in value)
        return f"{value:g}" if isinstance(value, (int, float)) else str(value)
    print(f"\n{sample['model']} {sample['serial']} @ {sample['host']} ({sample['transport']})")
    print(f"Sample: {sample['sampled_at']} | State: {sample['state']}"
          + (" | Partial read" if sample['partial'] else ""))
    print("\nPV tracker     Voltage (V)    Current (A)    Calculated power (W)")
    for tracker in sample['mppts']:
        print(f"{tracker['name']:<14} {formatted(tracker['voltage_v']):<14}"
              f" {formatted(tracker['current_a']):<14} {formatted(tracker['power_w'])}")
    print("\nMeasurements (phase arrays: A / B / C):")
    for key, value in sample['metrics'].items():
        print(f"  {key:<28} {formatted(value)}")
    print(f"\nBattery telemetry available: {sample['battery_available']}"
          f" | Meter available: {sample['meter_available']}")
    print("Fault/alarm words" + (":" if sample['faults_available'] else " (incomplete/unavailable):"))
    for flag in sample['flags']:
        print(f"  Input {flag['register']} = 0x{flag['raw']:04X}: " + "; ".join(flag['labels']))
    if not sample['flags']:
        print("  None set." if sample['faults_available'] else "  No reliable all-clear reading.")
    for error in sample['errors']:
        print(f"  Read error {error['register']}/{error['count']}: {error['message']}")


def values_command(args):
    """Inspect each explicitly selected host once; a failure does not hide other devices."""
    failed = False
    password = None
    if args.transport == "winet":
        password = os.environ.get("SH10RT_PASSWORD")
        if password is None:
            if not sys.stdin.isatty():
                raise DeviceError("WiNet password required: use an interactive terminal or SH10RT_PASSWORD.")
            password = getpass.getpass("WiNet password: ")
    for host in dict.fromkeys(args.host):
        client = None
        try:
            client = (ReadOnlyModbus(host, args.unit, args.timeout) if args.transport == "modbus"
                      else WiNet(host, args.username, password, args.timeout))
            sample = read_values(client)
            failed = failed or sample['partial']
            if args.json:
                emit("values", **sample)
            else:
                print_values(sample)
        except DeviceError as exc:
            failed = True
            if args.json:
                emit("error", host=host, message=str(exc))
            else:
                print(f"{host}: {exc}", file=sys.stderr)
        finally:
            if client is not None:
                client.close()
    return 2 if failed else 0


def snapshot(client):
    serial = client.identity()
    state = client.read(13000, 37)
    start_stop = client.read(13000, 1, holding=True)[0]
    alarms = client.read(13050, 30)
    measurements = client.read(5008, 29)
    words = dict(zip(range(5008, 5037), measurements))
    words.update(zip(range(13000, 13037), state))
    return {"host": client.host, "transport": client.transport, "serial": serial,
        "model": "SH10RT", "state": state[0], "state_name": STATES.get(state[0], "Unknown"),
        "start_stop": start_stop, "start_stop_name": {STOP: "Stop", START: "Start"}.get(start_stop, "Unknown"),
        "active_power_W": number(words, 13034, signed=True, wide=True),
        "pv_voltage_V": [number(words, address, .1) for address in (5011, 5013)],
        "grid_voltage_V": [number(words, address, .1) for address in (5019, 5020, 5021)],
        **grid_frequency(client, measurements[28]),
        "temperature_C": number(words, 5008, .1, signed=True),
        "alarms": [{"register": 13050 + i, "value": value} for i, value in enumerate(alarms) if value],
        "meter_communication_alarm": bool(alarms[1] & 0x4000),
        "parallel_communication_alarm": bool(alarms[0] & 0x20)}


def start_device(client, expected_serial, execute=False, wait=0, poll=10):
    before = snapshot(client)
    emit("preflight", **before)
    if before["serial"] != expected_serial:
        raise DeviceError("Serial mismatch: no command sent.")
    if before["alarms"]:
        raise DeviceError("Current fault/alarm bits are set. Resolve them before using automated Start.")
    if before["start_stop"] == START:
        emit("no_change", reason="Start is already enabled; no command sent.")
        if wait:
            return observe(client, expected_serial, wait, poll)
        return 0
    if before["start_stop"] != STOP or before["state"] not in (8, 16):
        raise DeviceError("Start is supported only for confirmed Stop with Standby or Initial Standby.")
    if not execute:
        emit("dry_run", serial=expected_serial, action="Start once", execute=False)
        return 0
    # Re-read all preconditions, including identity, immediately before the only write.
    final = snapshot(client)
    if (final["serial"] != expected_serial or final["start_stop"] != STOP
            or final["state"] not in (8, 16) or final["alarms"]):
        raise DeviceError("Device identity or start conditions changed; no command sent.")
    client.start_once()
    emit("start_acknowledged", serial=expected_serial, commands_sent=1)
    # Verify once. A failure here must never cause another write.
    try:
        after = snapshot(client)
        if after["serial"] != expected_serial or after["start_stop"] != START:
            raise DeviceError("Start read-back mismatch.")
    except DeviceError:
        raise UnknownWriteOutcome("Command acknowledged, but read-back unconfirmed. Inspect status; do not automatically resend.") from None
    emit("read_back", **after)
    if wait:
        return observe(client, expected_serial, wait, poll)
    emit("verification_limit", message="Start setting verified; sustained generation has not been verified. Use --wait 330.")
    return 0


def observe(client, serial, wait, poll):
    deadline = time.monotonic() + wait
    consecutive = 0
    while True:
        state = snapshot(client)
        if state["serial"] != serial:
            raise DeviceError("Device identity changed during observation.")
        emit("observation", **state)
        healthy = (state["state"] in RUNNING_STATES and state["active_power_W"] is not None
                   and state["active_power_W"] > 0 and not state["alarms"])
        consecutive = consecutive + 1 if healthy else 0
        if consecutive >= 2:
            emit("generation_verified", serial=serial, consecutive_samples=consecutive)
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            emit("not_yet_generating", message="Observation ended without two healthy generating samples; no command repeated.")
            return 3
        # Keep a WiNet session alive while waiting without requiring a background thread.
        time.sleep(min(poll, remaining, 10))
        if isinstance(client, WiNet):
            try:
                client.ws.send(json.dumps({"service": "ping", "lang": "en_us", "token": client.token}))
            except Exception:
                raise DeviceError("WiNet keepalive failed; inspect status before retrying.") from None


def discover_host(host, unit, timeout):
    found = []
    native = Modbus(host, unit, timeout)
    try:
        serial = native.identity()
        found.append({"host": host, "transport": "modbus", "serial": serial, "model": "SH10RT", "unit": unit})
    except DeviceError:
        pass
    try:
        page = http_get(host, "/", timeout).decode("utf-8", errors="replace")
        if re.search(r"<title[^>]*>[^<]*WiNet[^<]*</title>", page, re.I):
            found.append({"host": host, "transport": "winet", "identity_verified": False,
                          "next_step": "Use status with maintenance login to identify the attached inverter."})
    except DeviceError:
        pass
    return found


def make_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    scan = subs.add_parser("scan", help="Read-only discovery; WiNet detection does not send credentials.")
    scan.add_argument("--network", type=scan_network, required=True)
    scan.add_argument("--workers", type=integer(1, 32), default=16)
    scan.add_argument("--timeout", type=integer(1, 10), default=1)
    scan.add_argument("--unit", type=integer(1, 247), default=1)
    for command in ("status", "start", "values"):
        sub = subs.add_parser(command)
        sub.add_argument("--host", type=lan_ip, required=True,
                         **({"action": "append", "help": "Repeat for multiple inverter interfaces."}
                            if command == "values" else {}))
        sub.add_argument("--transport", choices=("modbus", "winet"), required=True)
        sub.add_argument("--unit", type=integer(1, 247), default=1, help="Native Modbus unit ID; ignored for WiNet.")
        sub.add_argument("--username", default="admin", help="WiNet account; password is prompted, or read from SH10RT_PASSWORD.")
        sub.add_argument("--timeout", type=integer(1, 30), default=5)
        if command == "values":
            sub.add_argument("--json", action="store_true", help="Emit JSON Lines instead of a terminal report.")
        if command == "start":
            sub.add_argument("--serial", required=True, help="Exact serial number, independently checked against the intended device.")
            sub.add_argument("--execute", action="store_true", help="Actually send one Start command. Without this flag: read-only preview.")
            sub.add_argument("--wait", type=integer(0, 1200), default=0, metavar="SECONDS")
    return parser


def main(argv=None):
    args = make_parser().parse_args(argv)
    client = None
    try:
        if args.command == "scan":
            matches = []
            with ThreadPoolExecutor(max_workers=args.workers) as pool:
                jobs = [pool.submit(discover_host, str(ip), args.unit, args.timeout) for ip in args.network.hosts()]
                for job in as_completed(jobs):
                    for row in job.result():
                        matches.append(row)
                        emit("discovered", **row)
            emit("scan_complete", interfaces=len(matches), network=str(args.network),
                 note="No writes or login attempts. Unreachable or unsupported devices may not be found.")
            return 0 if matches else 4
        if args.command == "values":
            return values_command(args)
        if args.transport == "modbus":
            client = Modbus(args.host, args.unit, args.timeout)
        else:
            password = os.environ.get("SH10RT_PASSWORD")
            if password is None:
                if not sys.stdin.isatty():
                    raise DeviceError("WiNet password required: use an interactive terminal or SH10RT_PASSWORD.")
                password = getpass.getpass("WiNet password: ")
            client = WiNet(args.host, args.username, password, args.timeout)
        if args.command == "status":
            emit("status", **snapshot(client))
            return 0
        return start_device(client, args.serial, args.execute, args.wait)
    except UnknownWriteOutcome as exc:
        emit("write_outcome_unconfirmed", message=str(exc))
        return 5
    except (DeviceError, OSError) as exc:
        emit("error", message=str(exc) if isinstance(exc, DeviceError) else "Local/network I/O failed.")
        return 2
    except KeyboardInterrupt:
        emit("interrupted", message="No automatic retry. A previously sent command may still take effect; inspect status.")
        return 130
    finally:
        if client is not None:
            client.close()


if __name__ == "__main__":
    sys.exit(main())
