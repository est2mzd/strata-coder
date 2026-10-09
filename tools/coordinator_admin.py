"""Operator recovery tools. Reset only after inspecting upstream/repository state."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strata_coder.queue_client import BrokerClient
p=argparse.ArgumentParser()
p.add_argument('--url',default='http://127.0.0.1:8091/v1');p.add_argument('--token-file',required=True)
p.add_argument('action',choices=['status','reset-inference','reset-apply'])
p.add_argument('--confirm-inspected',action='store_true');p.add_argument('--workspace')
a=p.parse_args()
client=BrokerClient({'mode':'direct','coordinator_url':a.url,'coordinator_token_file':a.token_file})
try:
    if a.action=='status':result=client.request('health')
    else:
        if not a.confirm_inspected:p.error('Inspect the affected system first, then supply --confirm-inspected')
        if a.action=='reset-apply' and not a.workspace:p.error('--workspace is required')
        result=client.request(a.action,{'confirmed_idle':True} if a.action=='reset-inference' else {'confirmed_inspected':True,'workspace':a.workspace})
    print(json.dumps(result,indent=2))
finally:client.close()
