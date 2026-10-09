import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
from strata_coder.transport import Transport


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        records = self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                records.append((self.path, dict(self.headers)))
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"data":[{"id":"fake-model"}]}')
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                records.append((self.path, body))
                self.send_response(200); self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def test_direct_health_model_discovery_and_chat(self):
        t = Transport({'mode': 'direct', 'base_url': f'http://127.0.0.1:{self.server.server_port}/v1'})
        with patch.dict(os.environ, {'STRATA_API_KEY': 'unit-secret'}):
            self.assertEqual(t.health()['models'], ['fake-model'])
            result = t.chat([{'role': 'user', 'content': 'hi'}], [])
        self.assertEqual(result['choices'][0]['message']['content'], 'ok')
        self.assertEqual(self.requests[0][1]['Authorization'], 'Bearer unit-secret')
        self.assertEqual(self.requests[-1][1]['model'], 'fake-model')

    def test_ssh_command_and_owned_process_cleanup(self):
        process = Mock()
        process.poll.return_value = None
        with patch('strata_coder.transport.subprocess.Popen', return_value=process) as launch, patch('strata_coder.transport.socket.create_connection'):
            t = Transport({'ssh_host': 'gdx-spark', 'remote_port': 8080})
            t.connect()
            argv = launch.call_args.args[0]
            self.assertIn('BatchMode=yes', argv)
            self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('ExitOnForwardFailure=yes', argv)
            forward = argv[argv.index('-L') + 1]
            self.assertTrue(forward.startswith('127.0.0.1:'))
            self.assertTrue(forward.endswith(':127.0.0.1:8080'))
            self.assertEqual(argv[-1], 'gdx-spark')
            t.close()
            process.terminate.assert_called_once()

    def test_api_url_credentials_rejected(self):
        with self.assertRaises(ValueError):
            Transport({'mode': 'direct', 'base_url': 'http://user:secret@localhost/v1'}).connect()
