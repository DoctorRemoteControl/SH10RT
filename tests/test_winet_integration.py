"""Local HTTP/WebSocket simulator: actual websocket-client, no inverter access."""
import base64
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import socketserver
import struct
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sh10rt_lan as app
try:
    import websocket
except ImportError:
    websocket = None


@unittest.skipIf(websocket is None, 'Install scripts/requirements.txt for the WiNet integration test.')
class WiNetIntegration(unittest.TestCase):
    def test_real_handshake_authenticated_reads_one_boot_and_keepalive(self):
        serial = 'TEST000001'
        device = {'dev_id': 1, 'dev_code': 3599, 'dev_type': 35, 'dev_sn': serial, 'link_status': 1}
        commands = []
        read_types = []
        state = {'start': 206}
        errors = []

        class HTTP(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                query = parse_qs(urlsplit(self.path).query)
                try:
                    assert query['token'] == ['SESSION_TEST']
                    address, count = int(query['param_addr'][0]), int(query['param_num'][0])
                    read_types.append(query['param_type'][0])
                    if address == 4990:
                        words = list(struct.unpack('>10H', serial.encode().ljust(20, b'\0'))) + [3599, 100, 1]
                    elif address == 13000 and query['param_type'] == ['1']:
                        words = [state['start']]
                    elif address == 13000:
                        words = [0] * count
                        words[0] = 64 if state['start'] == 207 else 16
                        words[34] = 1200 if state['start'] == 207 else 0
                    else:
                        words = [0] * count
                    assert len(words) == count
                    response = {'result_code': 1, 'result_data': {'param_value': ' '.join(f'{w:04X}' for w in words)}}
                    body = json.dumps(response).encode()
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    errors.append(exc)
                    self.send_error(400)

        class WS(socketserver.BaseRequestHandler):
            def handle(self):
                sock = self.request
                sock.settimeout(5)
                try:
                    headers = b''
                    while not headers.endswith(b'\r\n\r\n'):
                        headers += app.recv_exact(sock, 1)
                    key = next(line.split(b':', 1)[1].strip() for line in headers.split(b'\r\n')
                               if line.lower().startswith(b'sec-websocket-key:'))
                    accept = base64.b64encode(hashlib.sha1(key + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest())
                    sock.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
                    while True:
                        first, second = app.recv_exact(sock, 2)
                        length = second & 127
                        if length == 126:
                            length = struct.unpack('>H', app.recv_exact(sock, 2))[0]
                        elif length == 127:
                            length = struct.unpack('>Q', app.recv_exact(sock, 8))[0]
                        mask = app.recv_exact(sock, 4) if second & 128 else b'\0' * 4
                        raw = app.recv_exact(sock, length)
                        raw = bytes(b ^ mask[i % 4] for i, b in enumerate(raw))
                        if first & 15 == 8:
                            sock.sendall(b'\x88\x00')
                            return
                        request = json.loads(raw)
                        service = request['service']
                        if service == 'connect':
                            result = {'token': 'CONNECT_TEST'}
                        elif service == 'login':
                            assert request['username'] == 'admin' and request['passwd'] == 'TEST_PASSWORD'
                            result = {'uid': 3, 'token': 'SESSION_TEST'}
                        else:
                            assert request['token'] == 'SESSION_TEST'
                            if service == 'devicelist':
                                result = {'list': [device]}
                            elif service == 'param':
                                assert request['type'] == '3' and request['list'] == [{'power_switch': '1'}]
                                commands.append(request['list'])
                                state['start'] = 207
                                result = {'list': [{'param_name': 'I18N_COMMON_POWER_ON', 'result': 0}]}
                            elif service == 'ping':
                                result = {}
                                service = 'pong'
                            else:
                                raise AssertionError(service)
                        body = json.dumps({'result_code': 1, 'result_data': {'service': service, **result}}).encode()
                        frame = b'\x81' + (bytes([len(body)]) if len(body) < 126 else b'\x7e' + struct.pack('>H', len(body))) + body
                        sock.sendall(frame)
                except Exception as exc:
                    errors.append(exc)

        http = ThreadingHTTPServer(('127.0.0.1', 0), HTTP)
        ws = socketserver.ThreadingTCPServer(('127.0.0.1', 0), WS)
        threads = [threading.Thread(target=s.serve_forever, daemon=True) for s in [http, ws]]
        for thread in threads:
            thread.start()
        original_connect, original_http = websocket.create_connection, app.http_get
        def connect(url, **kwargs):
            kwargs['http_no_proxy'] = ['127.0.0.1']
            return original_connect(f'ws://127.0.0.1:{ws.server_address[1]}/ws/home/overview', **kwargs)
        def get(host, path, timeout):
            return original_http(f'127.0.0.1:{http.server_address[1]}', path, timeout)
        client = None
        captured = io.StringIO()
        try:
            with patch.object(websocket, 'create_connection', side_effect=connect), patch.object(app, 'http_get', side_effect=get), contextlib.redirect_stdout(captured):
                client = app.WiNet('192.168.1.100', 'admin', 'TEST_PASSWORD')
                values = app.read_values(client, pause=0)
                self.assertEqual(values['serial'], serial)
                self.assertFalse(values['partial'])
                self.assertEqual(set(read_types), {'0'})
                self.assertFalse(commands)
                self.assertEqual(app.start_device(client, serial, execute=True, wait=5, poll=0), 0)
                self.assertEqual(app.start_device(client, serial, execute=True), 0)
                client.close()
                client = None
        finally:
            if client:
                client.close()
            for server in (http, ws):
                server.shutdown()
                server.server_close()
            for thread in threads:
                thread.join(timeout=3)
        self.assertEqual(len(commands), 1)
        self.assertFalse(errors, errors)
        self.assertIn('"generation_verified"', captured.getvalue())
        for secret in ('TEST_PASSWORD', 'SESSION_TEST', 'CONNECT_TEST'):
            self.assertNotIn(secret, captured.getvalue())
