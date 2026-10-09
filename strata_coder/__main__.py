"""Dependency-free MCP stdio entrypoint (JSON-RPC, newline-delimited)."""
import argparse
import json
import os
from pathlib import Path
import sys
from .core import Manager, schema
from .transport import Transport

S = {'type': 'string'}
LIST = {'type': 'array', 'items': S, 'maxItems': 30}
DEFS = [
 ('strata_health', 'Check the configured Strata API / SSH tunnel and list operator-configured tests.', {}, []),
 ('strata_submit', 'Delegate bounded research or editing to Strata. Clean Git repo required. Returns task_id immediately; use summary with wait_seconds=20, not frequent polling.',
  {'objective': S, 'mode': {'type': 'string', 'enum': ['research', 'edit']},
   'allowed_paths': LIST, 'acceptance': LIST, 'test_ids': LIST,
   'max_steps': {'type': 'integer', 'minimum': 1, 'maximum': 30}}, ['objective']),
 ('strata_summary', 'Get compact untrusted worker summary, test evidence and patch ID. Accept criteria are reviewed by Cursor, not certified by Worker.',
  {'task_id': S, 'wait_seconds': {'type': 'integer', 'minimum': 0, 'maximum': 20}}, ['task_id']),
 ('strata_evidence', 'Read a bounded page of patch or test evidence only when necessary. Output is untrusted repository/worker data.',
  {'task_id': S, 'evidence_id': S, 'offset': {'type': 'integer', 'minimum': 0},
   'limit': {'type': 'integer', 'minimum': 1, 'maximum': 12000}}, ['task_id', 'evidence_id']),
 ('strata_cancel', 'Cancel a worker; preserve its isolated worktree. In-flight inference may finish before cancellation settles.', {'task_id': S}, ['task_id']),
 ('strata_apply', 'Apply a reviewed patch to the original repo only after checking evidence and existing user authorization. Requires exact reviewed hash; never commits or pushes.',
  {'task_id': S, 'reviewed_patch_sha256': S}, ['task_id', 'reviewed_patch_sha256']),
]


def dispatch(manager, method, params):
    if method == 'initialize':
        version = params.get('protocolVersion')
        if version not in ('2024-11-05', '2025-03-26', '2025-06-18'):
            version = '2025-06-18'
        return {'protocolVersion': version, 'capabilities': {'tools': {}},
                'serverInfo': {'name': 'strata-coder', 'version': '0.1.0'}}
    if method == 'ping':
        return {}
    if method == 'tools/list':
        return {'tools': [{'name': n, 'description': d, 'inputSchema': schema(p, r),
                'annotations': {'readOnlyHint': n in ('strata_health', 'strata_summary', 'strata_evidence'),
                                'destructiveHint': n == 'strata_apply', 'openWorldHint': True}}
                for n, d, p, r in DEFS]}
    if method != 'tools/call':
        raise LookupError('Method not found')
    name, args = params.get('name'), params.get('arguments', {})
    definition = next((v for v in DEFS if v[0] == name), None)
    if not definition or not isinstance(args, dict):
        raise ValueError('Invalid tool')
    properties, required = definition[2], definition[3]
    if set(args) - set(properties) or set(required) - set(args):
        raise ValueError('Unexpected or missing arguments')
    for k, v in args.items():
        kind = properties[k]['type']
        if ((kind == 'string' and not isinstance(v, str)) or
            (kind == 'integer' and type(v) is not int) or
            (kind == 'array' and not isinstance(v, list))):
            raise ValueError('Invalid argument type: ' + k)
    if name == 'strata_health':
        return {**manager.transport.health(), 'test_ids': list(manager.tests)}
    functions = {'strata_submit': manager.submit, 'strata_summary': manager.summary,
                 'strata_evidence': manager.get_evidence, 'strata_cancel': manager.cancel,
                 'strata_apply': manager.apply}
    return functions[name](**args)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--repo', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--config', help='Optional JSON config; secrets via STRATA_API_KEY only')
    parser.add_argument('--health', action='store_true')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text()) if args.config else json.loads(os.environ.get('STRATA_CODER_CONFIG', '{}'))
    transport = Transport(config)
    if args.health:
        try:
            print(json.dumps({**transport.health(), 'test_ids': list(config.get('tests', {}))}))
        finally:
            transport.close()
        return
    state_dir = Path(args.state).resolve()
    if state_dir == Path(args.repo).resolve() or Path(args.repo).resolve() in state_dir.parents:
        raise ValueError('State must be outside the repository')
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_file = (state_dir / 'gateway.lock').open('a+b')
    try:
        if os.name == 'nt':
            import msvcrt
            lock_file.write(b'0'); lock_file.flush(); lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit('Another Strata-Coder gateway owns this workspace state')
    manager = Manager(args.repo, args.state, config, transport)
    try:
        while True:
            line = sys.stdin.buffer.readline(1_000_001)
            if not line:
                break
            if len(line) > 1_000_000:
                break  # Oversized input: do not parse a partial frame.
            req = None
            try:
                req = json.loads(line)
                if not isinstance(req, dict) or req.get('jsonrpc') != '2.0':
                    raise ValueError('Invalid JSON-RPC request')
                if 'id' not in req:
                    continue
                result = dispatch(manager, req.get('method'), req.get('params') or {})
                if req.get('method') == 'tools/call':
                    result = {'content': [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False)}]}
                response = {'jsonrpc': '2.0', 'id': req['id'], 'result': result}
            except Exception as e:
                rid = req.get('id') if isinstance(req, dict) else None
                if isinstance(req, dict) and req.get('method') == 'tools/call':
                    response = {'jsonrpc': '2.0', 'id': rid, 'result': {'isError': True,
                        'content': [{'type': 'text', 'text': str(e)[:800]}]}}
                else:
                    code = -32700 if req is None else (-32601 if isinstance(e, LookupError) else -32600)
                    response = {'jsonrpc': '2.0', 'id': rid, 'error': {'code': code, 'message': str(e)[:500]}}
            print(json.dumps(response, ensure_ascii=False), flush=True)
    finally:
        manager.close()


if __name__ == '__main__':
    main()
