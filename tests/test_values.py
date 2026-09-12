"""Offline CLI measurements: decoding, input-only access and partial failures."""
import contextlib
import io
import json
from pathlib import Path
import struct
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sh10rt_lan as app


class MeasurementDevice:
    host = '192.168.1.100'
    transport = 'test'

    def __init__(self, failures=()):
        self.failures = failures
        self.words = {a: 0 for start, count in app.VALUE_BLOCKS for a in range(start, start + count)}
        self.words.update({5011: 3500, 5012: 40, 5013: 3000, 5014: 20,
                           5017: 2000, 13034: 1900, 13023: 650, 5242: 5000,
                           13020: 2500, 5603: 100, 5605: 200, 5607: 300})

    def identity(self):
        return 'TEST000001'

    def read(self, address, count, holding=False):
        assert not holding, 'Measurements must never read holding registers'
        if address in self.failures:
            raise app.DeviceError('Synthetic unsupported block')
        return [self.words[a] for a in range(address, address + count)]

    def close(self):
        pass


class ValuesCommandTests(unittest.TestCase):
    def test_report_and_json_contain_measurements(self):
        for extra in ([], ['--json']):
            output = io.StringIO()
            with patch.object(app, 'ReadOnlyModbus', return_value=MeasurementDevice()), \
                    patch.object(app.time, 'sleep'), contextlib.redirect_stdout(output):
                result = app.main(['values', '--host', '192.168.1.100', '--transport', 'modbus', *extra])
            self.assertEqual(result, 0)
            if extra:
                sample = json.loads(output.getvalue())
                self.assertEqual(sample['event'], 'values')
                self.assertEqual(sample['mppts'][0]['power_w'], 1400)
                self.assertEqual(sample['mppts'][1]['power_w'], 600)
                self.assertEqual(sample['metrics']['battery_soc_pct'], 65)
            else:
                self.assertIn('MPPT 1', output.getvalue())
                self.assertIn('1400', output.getvalue())
                self.assertIn('State: Running', output.getvalue())

    def test_partial_fault_block_does_not_report_all_clear_or_battery(self):
        sample = app.read_values(MeasurementDevice(failures=(13050,)), pause=0)
        self.assertTrue(sample['partial'])
        self.assertFalse(sample['faults_available'])
        self.assertIsNone(sample['metrics']['battery_soc_pct'])
        self.assertIsNone(sample['metrics']['meter_grid_export_w'])
        self.assertEqual(sample['mppts'][0]['power_w'], 1400)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            app.print_values(sample)
        self.assertIn('No reliable all-clear', output.getvalue())
        self.assertIn('Read error 13050/30', output.getvalue())

    def test_all_failed_blocks_fail_after_identity(self):
        with self.assertRaisesRegex(app.DeviceError, 'all measurement blocks failed'):
            app.read_values(MeasurementDevice(failures=tuple(a for a, _ in app.VALUE_BLOCKS)), pause=0)

    def test_partial_read_returns_error_exit(self):
        with patch.object(app, 'ReadOnlyModbus', return_value=MeasurementDevice(failures=(5214,))), \
                patch.object(app.time, 'sleep'), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(app.main(['values', '--host', '192.168.1.100', '--transport', 'modbus']), 2)

    def test_identity_failure_does_not_read_and_other_host_is_attempted(self):
        bad = Mock()
        bad.identity.side_effect = app.DeviceError('Unsupported model')
        good = MeasurementDevice()
        output = io.StringIO()
        with patch.object(app, 'ReadOnlyModbus', side_effect=[bad, good]) as factory, \
                patch.object(app.time, 'sleep'), contextlib.redirect_stdout(output):
            result = app.main(['values', '--host', '192.168.1.101', '--host', good.host,
                               '--transport', 'modbus', '--json'])
        self.assertEqual(result, 2)
        self.assertEqual(factory.call_count, 2)
        bad.read.assert_not_called()
        bad.close.assert_called_once()
        events = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual([event['event'] for event in events], ['error', 'values'])

    def test_values_rejects_execute_flag(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            app.make_parser().parse_args(['values', '--host', '192.168.1.100',
                                          '--transport', 'modbus', '--execute'])

    def test_meter_alarm_hides_derived_readings(self):
        device = MeasurementDevice()
        device.words[13051] = 0x4000
        sample = app.read_values(device, pause=0)
        self.assertFalse(sample['meter_available'])
        self.assertIsNone(sample['metrics']['meter_phase_sum_w'])
        self.assertEqual(sample['flags'][0]['labels'], ['Meter communication alarm'])


class ValuesDecoderTests(unittest.TestCase):

    def test_input_only_even_inherited_start(self):
        c = app.ReadOnlyModbus('192.168.1.100')
        with patch.object(app.Modbus, 'exchange') as transport:
            for function in (3, 6, 16):
                with self.assertRaises(app.DeviceError):
                    c.exchange(struct.pack('>BHH', function, 12999, 207))
            transport.assert_not_called()

    def test_mppt_power_signed_and_invalid(self):
        w = {5011: 4000, 5012: 50, 5013: 65535, 5014: 0,
             13034: 65536-1200, 13035: 65535, 13023: 65535, 13020: 0,
             5036: 5000, 5242: 65535}
        d = app.decode(w)
        self.assertEqual(d['mppts'][0]['power_w'], 2000)
        self.assertIsNone(d['mppts'][1]['power_w'])
        self.assertEqual(d['metrics']['ac_w'], -1200)
        self.assertEqual(d['metrics']['frequency_hz'], 50)
        self.assertIsNone(d['metrics']['battery_voltage_v'])
        self.assertFalse(d['faults_available'])
        self.assertIsNone(app.number({1: 65535, 2: 32767}, 1, signed=True, wide=True))
        self.assertIsNone(app.number({1: 65535, 2: 65535}, 1, wide=True))
        self.assertEqual(app.number({1: 65535}, 1, signed=True), -1)

    def test_battery_current_uses_signed_register_not_legacy(self):
        words = {13023: 10, 13021: 65242, 5631: 65242, 13066: 0}
        self.assertEqual(app.decode(words)['metrics']['battery_current_a'], -29.4)
        words[5631] = 150
        self.assertEqual(app.decode(words)['metrics']['battery_current_a'], 15)
        words[5631] = 32767
        self.assertIsNone(app.decode(words)['metrics']['battery_current_a'])
        del words[5631]
        self.assertIsNone(app.decode(words)['metrics']['battery_current_a'])
        words.update({5631: 65242, 13066: 16384})
        self.assertIsNone(app.decode(words)['metrics']['battery_current_a'])

    def test_offline_battery_masks_stale_soc(self):
        d = app.decode({13023: 500, 13020: 2500, 13066: 16384, 5635: 30})
        self.assertFalse(d['battery_available'])
        self.assertIsNone(d['metrics']['allowed_charge_a'])
        self.assertEqual(d['flags'][0]['labels'], ['BMS communication fault'])

    def test_missing_battery_alarm_block_is_not_a_healthy_battery(self):
        for words in ({13023: 500}, {13023: 500, 13066: 65535}):
            self.assertFalse(app.decode(words)['battery_available'])

    def test_backup_power_is_signed_and_masks_signed_sentinel(self):
        self.assertEqual(app.decode({5726: 65536-250, 5727: 65535})['metrics']['backup_w'], -250)
        self.assertEqual(app.decode({5726: 250, 5727: 0})['metrics']['backup_w'], 250)
        self.assertIsNone(app.decode({5726: 65535, 5727: 32767})['metrics']['backup_w'])

    def test_winet_pacing_and_write_guard(self):
        stop = threading.Event()
        client = app.ReadOnlyModbus('192.168.1.100', pause=1.1, stop=stop)
        with patch.object(app.Modbus, 'exchange', return_value=b'reply') as transport, \
                patch.object(app.time, 'monotonic', return_value=100), \
                patch.object(stop, 'wait', return_value=False) as wait:
            client.exchange(b'\x04')
            client.exchange(b'\x04')
            wait.assert_called_once_with(1.1)
            with self.assertRaises(app.DeviceError):
                client.exchange(b'\x06')
            self.assertEqual(transport.call_count, 2)
