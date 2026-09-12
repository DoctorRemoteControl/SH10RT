"""Offline checks for identity guards, single-write behavior and wire protocol."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import socket
import struct
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sh10rt_lan as app

SERIAL = "TEST000001"


class FakeDevice:
    host = "192.168.1.100"
    transport = "test"

    def __init__(self, serial=SERIAL, state=16, start_stop=206, alarms=None):
        self.serial, self.state, self.start_stop = serial, state, start_stop
        self.alarms = alarms or [0] * 30
        self.writes = 0
        self.identifications = 0
        self.power = 0

    def identity(self):
        self.identifications += 1
        return self.serial

    def read(self, address, count, holding=False):
        if address == 13000 and holding:
            return [self.start_stop]
        if address == 13000:
            values = [0] * 37
            values[0] = self.state
            values[34] = self.power
            return values
        if address == 13050:
            return self.alarms
        if address == 5242:
            raise app.DeviceError("High-precision register unsupported in this fixture.")
        if address == 5008:
            values = [0] * 29
            values[0], values[3], values[5] = 246, 3423, 5124
            values[11:14] = [2360, 2370, 2380]
            values[28] = 500
            return values
        raise AssertionError((address, count, holding))

    def start_once(self):
        self.writes += 1
        self.start_stop = 207


class StartTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()

    def tearDown(self):
        self.redirect.__exit__(None, None, None)

    def test_preview_does_not_write(self):
        device = FakeDevice()
        self.assertEqual(app.start_device(device, SERIAL), 0)
        self.assertEqual(device.writes, 0)
        self.assertIn('"dry_run"', self.output.getvalue())

    def test_exactly_one_start_and_read_back(self):
        device = FakeDevice()
        self.assertEqual(app.start_device(device, SERIAL, execute=True), 0)
        self.assertEqual(device.writes, 1)
        self.assertEqual(device.identifications, 3)
        self.assertNotIn('"generation_verified"', self.output.getvalue())

    def test_wrong_serial_refuses_write(self):
        device = FakeDevice()
        with self.assertRaisesRegex(app.DeviceError, "Serial mismatch"):
            app.start_device(device, "WRONG000001", execute=True)
        self.assertEqual(device.writes, 0)

    def test_alarm_blocks_start_including_meter_alarm(self):
        for index, value in [(0, 32), (1, 16384), (8, 1)]:
            device = FakeDevice()
            device.alarms[index] = value
            with self.assertRaisesRegex(app.DeviceError, "fault/alarm"):
                app.start_device(device, SERIAL, execute=True)
            self.assertEqual(device.writes, 0)

    def test_already_started_never_repeats_command(self):
        for state in (0, 8, 16, 32, 64):
            device = FakeDevice(state=state, start_stop=207)
            app.start_device(device, SERIAL, execute=True)
            self.assertEqual(device.writes, 0)

    def test_fault_or_unknown_state_refuses_write(self):
        for state in (256, 65535, 64):
            device = FakeDevice(state=state)
            with self.assertRaises(app.DeviceError):
                app.start_device(device, SERIAL, execute=True)
            self.assertEqual(device.writes, 0)

    def test_identity_changes_before_write(self):
        device = FakeDevice()
        device.identity = Mock(side_effect=[SERIAL, "OTHER00001"])
        with self.assertRaisesRegex(app.DeviceError, "changed"):
            app.start_device(device, SERIAL, execute=True)
        self.assertEqual(device.writes, 0)

    def test_alarm_appears_before_write(self):
        device = FakeDevice()
        original = device.identity
        def identity():
            result = original()
            if device.identifications == 2:
                device.alarms[0] = 1
            return result
        device.identity = identity
        with self.assertRaisesRegex(app.DeviceError, "changed"):
            app.start_device(device, SERIAL, execute=True)
        self.assertEqual(device.writes, 0)

    def test_lost_write_response_never_retried(self):
        device = FakeDevice()
        device.start_once = Mock(side_effect=app.UnknownWriteOutcome("lost reply"))
        with self.assertRaises(app.UnknownWriteOutcome):
            app.start_device(device, SERIAL, execute=True)
        device.start_once.assert_called_once()

    def test_acknowledged_but_unchanged_setting_is_not_success(self):
        device = FakeDevice()
        device.start_once = Mock()  # An ACK alone is insufficient.
        with self.assertRaises(app.UnknownWriteOutcome):
            app.start_device(device, SERIAL, execute=True)
        device.start_once.assert_called_once()

    def test_zero_power_is_not_successful_generation(self):
        for state in (0, 64):
            device = FakeDevice(state=state, start_stop=207)
            self.assertEqual(app.observe(device, SERIAL, wait=0, poll=10), 3)

    def test_requires_two_healthy_observations(self):
        for state in (0, 64):
            device = FakeDevice(state=state, start_stop=207)
            device.power = 1200
            self.assertEqual(app.snapshot(device)["state_name"], "Running")
            with patch.object(app.time, "sleep"):
                self.assertEqual(app.observe(device, SERIAL, wait=5, poll=1), 0)
            self.assertEqual(device.identifications, 3)

    def test_measurement_offsets(self):
        state = app.snapshot(FakeDevice())
        self.assertEqual(state["pv_voltage_V"], [342.3, 512.4])
        self.assertEqual(state["grid_voltage_V"], [236, 237, 238])
        self.assertEqual(state["grid_frequency_Hz"], 50)
        self.assertEqual(state["temperature_C"], 24.6)

    def test_unavailable_status_measurements_cannot_verify_generation(self):
        device = FakeDevice(state=64, start_stop=207)
        original = device.read
        def read(address, count, holding=False):
            words = original(address, count, holding)
            if address == 13000 and not holding:
                words[34:36] = [0xFFFF, 0x7FFF]
            if address == 5008:
                words[0], words[3], words[11] = 0x7FFF, 0xFFFF, 0xFFFF
            return words
        device.read = read
        result = app.snapshot(device)
        self.assertIsNone(result['active_power_W'])
        self.assertIsNone(result['pv_voltage_V'][0])
        self.assertIsNone(result['grid_voltage_V'][0])
        self.assertIsNone(result['temperature_C'])
        self.assertEqual(app.observe(device, SERIAL, wait=0, poll=10), 3)
        self.assertNotIn('"generation_verified"', self.output.getvalue())


class FrequencyTests(unittest.TestCase):
    def test_documented_high_precision_preferred(self):
        device = Mock()
        device.read.return_value = [5002]
        result = app.grid_frequency(device, 500)
        self.assertEqual(result["grid_frequency_Hz"], 50.02)
        self.assertEqual(result["grid_frequency_register"], 5242)
        device.read.assert_called_once_with(5242, 1)

    def test_live_legacy_variants_when_high_precision_unavailable(self):
        device = Mock()
        device.read.side_effect = app.DeviceError("Unsupported")
        for raw, scale in ((500, 0.1), (5000, 0.01), (0, 0.1)):
            result = app.grid_frequency(device, raw)
            self.assertEqual(result["grid_frequency_Hz"], 0 if raw == 0 else 50)
            self.assertEqual(result["grid_frequency_raw"], raw)
            self.assertEqual(result["grid_frequency_scale"], scale)
            if scale == 0.01:
                self.assertIn("inferred", result["grid_frequency_note"])
        self.assertEqual(app.grid_frequency(device, 5005)["grid_frequency_Hz"], 50.05)

    def test_invalid_data_is_missing_instead_of_bogus_frequency(self):
        device = Mock()
        device.read.return_value = [65535]
        for raw in (65535, 2000, 1):
            result = app.grid_frequency(device, raw)
            self.assertIsNone(result["grid_frequency_Hz"])
            self.assertIsNone(result["grid_frequency_scale"])
        self.assertEqual(app.grid_frequency(device, 500)["grid_frequency_Hz"], 50)


class WireTests(unittest.TestCase):
    def exchange_with_server(self, operation, reply):
        errors, received = [], []
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(3)
        port = server.getsockname()[1]
        def serve():
            try:
                with server:
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(3)
                        header = app.recv_exact(conn, 7)
                        tid, protocol, length, unit = struct.unpack(">HHHB", header)
                        pdu = app.recv_exact(conn, length - 1)
                        received.append(pdu)
                        response = reply(tid, unit, pdu)
                        # Deliberately fragment the header/PDU to exercise exact reads.
                        for byte in response:
                            conn.sendall(bytes([byte]))
            except (BrokenPipeError, ConnectionResetError):
                pass  # The client may reject the header before reading the remaining PDU.
            except Exception as exc:
                errors.append(exc)
        thread = threading.Thread(target=serve)
        thread.start()
        try:
            return operation(app.Modbus("127.0.0.1", port=port)), received
        finally:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors, errors)

    @staticmethod
    def response(tid, unit, pdu):
        return struct.pack(">HHHB", tid, 0, len(pdu) + 1, unit) + pdu

    def test_native_start_exact_wire_address_and_value(self):
        _, received = self.exchange_with_server(lambda c: c.start_once(), self.response)
        self.assertEqual(received, [struct.pack(">BHH", 6, 12999, 207)])

    def test_input_read_uses_fc04_and_subtracts_one(self):
        value, received = self.exchange_with_server(
            lambda c: c.read(13000, 1),
            lambda tid, unit, pdu: self.response(tid, unit, b'\x04\x02\x00\x10'))
        self.assertEqual(received, [struct.pack(">BHH", 4, 12999, 1)])
        self.assertEqual(value, [16])

    def test_holding_read_is_separate_from_input_state(self):
        value, received = self.exchange_with_server(
            lambda c: c.read(13000, 1, holding=True),
            lambda tid, unit, pdu: self.response(tid, unit, b'\x03\x02\x00\xce'))
        self.assertEqual(received, [struct.pack(">BHH", 3, 12999, 1)])
        self.assertEqual(value, [206])

    def test_mismatched_transaction_rejected(self):
        with self.assertRaisesRegex(app.DeviceError, "header"):
            self.exchange_with_server(lambda c: c.read(13000, 1),
                lambda tid, unit, pdu: self.response(tid + 1, unit, b'\x04\x02\x00\x10'))

    def test_write_echo_mismatch_is_uncertain(self):
        with self.assertRaises(app.UnknownWriteOutcome):
            self.exchange_with_server(lambda c: c.start_once(),
                lambda tid, unit, pdu: self.response(tid, unit, struct.pack(">BHH", 6, 12999, 206)))

    def test_exception_response_rejected(self):
        with self.assertRaisesRegex(app.DeviceError, "exception 2"):
            self.exchange_with_server(lambda c: c.read(13000, 1),
                lambda tid, unit, pdu: self.response(tid, unit, b'\x84\x02'))

    def test_exception_without_code_is_reported_without_inventing_a_code(self):
        with self.assertRaisesRegex(app.DeviceError, 'exception missing code'):
            self.exchange_with_server(lambda c: c.read(5214, 2),
                lambda tid, unit, pdu: self.response(tid, unit, b'\x84'))

    def test_unknown_model_cannot_pass_identity(self):
        c = app.Modbus("192.168.1.100")
        words = list(struct.unpack(">10H", SERIAL.encode().ljust(20, b'\0')))
        c.read = Mock(return_value=words + [1234, 100, 1])
        with self.assertRaisesRegex(app.DeviceError, "not the supported"):
            c.identity()


class WiNetTests(unittest.TestCase):
    def client(self):
        client = app.WiNet.__new__(app.WiNet)
        client.device = {"dev_code": 3599, "dev_type": 35, "dev_id": 1}
        client.admin = True
        return client

    def test_exact_boot_command(self):
        c = self.client()
        c.request = Mock(return_value={"list": [
            {"param_name": "SH10RT(COM1-001)", "result": -1},
            {"param_name": "I18N_COMMON_POWER_ON", "result": 0}]})
        c.start_once()
        c.request.assert_called_once_with({"service": "param", "dev_code": "3599", "dev_type": "35",
            "devid_array": ["1"], "type": "3", "count": "1", "list": [{"power_switch": "1"}]})

    def test_admin_required(self):
        c = self.client()
        c.admin = False
        c.request = Mock()
        with self.assertRaises(app.DeviceError):
            c.start_once()
        c.request.assert_not_called()

    def test_success_envelope_without_power_on_result_is_insufficient(self):
        c = self.client()
        c.request = Mock(return_value={"list": []})
        with self.assertRaises(app.UnknownWriteOutcome):
            c.start_once()
        c.request.assert_called_once()

    def test_malformed_boot_reply_is_uncertain_without_retry(self):
        for reply in ({'list': None}, {'list': [None]}, {'list': 'invalid'}, None):
            with self.subTest(reply=reply):
                c = self.client()
                c.request = Mock(return_value=reply)
                with self.assertRaises(app.UnknownWriteOutcome):
                    c.start_once()
                c.request.assert_called_once()

    def test_multiple_devices_refused(self):
        c = self.client()
        c.request = Mock(return_value={"list": [c.device, c.device]})
        with self.assertRaisesRegex(app.DeviceError, "exactly one"):
            c.identity()

    def test_winet_read_keeps_logical_address(self):
        c = self.client()
        c.host, c.timeout, c.token = "192.168.1.100", 5, "TEST_TOKEN"
        with patch.object(app, "http_get", return_value=b'{"result_code":1,"result_data":{"param_value":"00 CE "}}') as get:
            self.assertEqual(c.read(13000, 1, holding=True), [206])
        url = get.call_args.args[1]
        self.assertIn('param_addr=13000', url)
        self.assertIn('param_type=1', url)

    def test_http_redirect_refused(self):
        with self.assertRaises(app.DeviceError):
            app.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com/')


class ArgumentTests(unittest.TestCase):
    def test_limited_network_scope(self):
        for value in ('0.0.0.0/0', '192.168.0.0/16', '8.8.8.0/24', '192.168.1.1/24'):
            with self.assertRaises(argparse.ArgumentTypeError):
                app.scan_network(value)
        self.assertEqual(str(app.scan_network('192.168.1.0/24')), '192.168.1.0/24')

    def test_requires_numeric_private_host(self):
        for host in ('example.com', '8.8.8.8', '192.168.1.1/path', '127.0.0.1'):
            with self.assertRaises(argparse.ArgumentTypeError):
                app.lan_ip(host)

    def test_execute_defaults_to_false_and_serial_is_required(self):
        parser = app.make_parser()
        args = parser.parse_args(['start', '--host', '192.168.1.100', '--transport', 'modbus', '--serial', SERIAL])
        self.assertFalse(args.execute)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(['start', '--host', '192.168.1.100', '--transport', 'modbus'])


if __name__ == '__main__':
    unittest.main()
