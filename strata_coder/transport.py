"""OpenAI-compatible inference over direct HTTP or an owned SSH tunnel."""
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


class Transport:
    def __init__(self, config):
        self.config = config
        self.proc = None
        self.lock = threading.Lock()
        self.base = ''
        # No proxy or redirects: credentials must only reach the configured host.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def connect(self):
        with self.lock:
            mode = self.config.get('mode', 'ssh')
            if mode == 'direct':
                base = self.config.get('base_url', 'http://127.0.0.1:18080/v1').rstrip('/')
                u = urllib.parse.urlparse(base)
                if u.username or u.password or u.query or u.fragment or not u.hostname:
                    raise ValueError('Invalid API URL')
                if u.scheme not in ('http', 'https'):
                    raise ValueError('API URL must be HTTP(S)')
                if u.hostname not in ('127.0.0.1', 'localhost', '::1'):
                    if u.scheme != 'https' or not os.environ.get('STRATA_API_KEY'):
                        raise ValueError('Remote direct APIs require HTTPS and STRATA_API_KEY; prefer SSH')
                self.base = base
                return
            if mode != 'ssh':
                raise ValueError('mode must be ssh or direct')
            if self.proc and self.proc.poll() is None:
                return
            host = self.config.get('ssh_host', 'gdx-spark')
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}', host):
                raise ValueError('Use an SSH config alias, not shell arguments')
            remote_port = int(self.config.get('remote_port', 8080))
            if not 1 <= remote_port <= 65535:
                raise ValueError('Invalid remote port')
            # ExitOnForwardFailure handles the allocation race; never reuse another tunnel.
            for _ in range(3):
                with socket.socket() as s:
                    s.bind(('127.0.0.1', 0))
                    port = s.getsockname()[1]
                cmd = ['ssh', '-N', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                       '-o', 'ExitOnForwardFailure=yes', '-o', 'ConnectTimeout=10',
                       '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
                       '-L', f'127.0.0.1:{port}:127.0.0.1:{remote_port}', host]
                self.proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    if self.proc.poll() is not None:
                        break
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=.2):
                            pass
                        self.base = f'http://127.0.0.1:{port}/v1'
                        return
                    except OSError:
                        time.sleep(.1)
                self.close()
            raise RuntimeError('SSH tunnel failed. Verify ssh alias, host key, key/agent authentication and remote API port. For password login, open a tunnel manually and use direct mode.')

    def request(self, path, body=None):
        self.connect()
        headers = {'Content-Type': 'application/json'}
        key = os.environ.get('STRATA_API_KEY')
        if key:
            headers['Authorization'] = 'Bearer ' + key
        req = urllib.request.Request(self.base + path, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req, timeout=min(180, max(1, int(self.config.get('request_timeout', 90))))) as r:
                raw = r.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ValueError('Inference response too large')
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f'Strata HTTP {e.code}; response body omitted') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise RuntimeError('Strata connection failed or timed out; check SSH/API status') from None

    def health(self):
        data = self.request('/models')
        return {'models': [x['id'] for x in data.get('data', []) if isinstance(x.get('id'), str)],
                'mode': self.config.get('mode', 'ssh'), 'reasoning_support': self.config.get('reasoning_support','unverified')}

    def chat(self, messages, tools):
        return self.chat_with_options(messages, tools, {})

    def validate_options(self, options):
        from .depth import resolve
        resolve({}, depth=options.get('reasoning_effort', 'low'), max_output_tokens=options.get('max_output_tokens', self.config.get('max_output_tokens',2048)))
        if self.config.get('reasoning_support') == 'unsupported':
            raise ValueError('Configured model does not support reasoning depth; choose a supported model')

    def chat_with_options(self, messages, tools, options):
        self.validate_options(options)
        model = self.config.get('model')
        if not model:
            models = self.health()['models']
            if len(models) != 1:
                raise ValueError('Configure a model ID; API did not return exactly one model')
            model = models[0]
        return self.request('/chat/completions', {'model': model, 'messages': messages,
            'tools': tools, 'tool_choice': 'auto', 'stream': False, 'temperature': 0.1,
            'reasoning_effort': options.get('reasoning_effort', 'low'), 'max_tokens': min(8192, max(128, int(options.get('max_output_tokens', self.config.get('max_output_tokens', 2048)))))})

    def close(self):
        if self.proc:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
            self.proc = None
