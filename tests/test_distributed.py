import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from strata_coder.coordinator import Store, InferenceGate, make_server
from strata_coder.queue_client import QueuedManager, BrokerClient
from strata_coder.core import git

TOKEN='local-test-token-not-a-real-secret-12345'


def reply(content=None, name=None, args=None):
    msg={'role':'assistant','content':content}
    if name:msg['tool_calls']=[{'id':'call','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]
    return {'choices':[{'message':msg,'finish_reason':'tool_calls' if name else 'stop'}]}


class FakeModel:
    def __init__(self):self.active=0;self.peak=0;self.lock=threading.Lock()
    def health(self):return {'models':['fixture-model']}
    def chat(self,messages,tools):
        with self.lock:self.active+=1;self.peak=max(self.peak,self.active)
        try:
            time.sleep(.02)
            contract=json.loads(messages[1]['content'])
            if contract['mode']=='research':return reply('Repository fixture reviewed.')
            tool_messages=[m for m in messages if m['role']=='tool']
            if not tool_messages:return reply(name='read_file',args={'path':'a.py'})
            last=json.loads(tool_messages[-1]['content'])
            if 'content' in last:return reply(name='write_file',args={'path':'a.py','content':'value = 2\n','expected_sha256':last['sha256']})
            return reply('Updated a.py. Supervisor must review tests and patch.')
        finally:
            with self.lock:self.active-=1


class DistributedTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.repo=self.root/'repo';self.repo.mkdir()
        subprocess.run(['git','init','-q',str(self.repo)],check=True)
        git(self.repo,'config','user.name','Test');git(self.repo,'config','user.email','test@example.invalid')
        (self.repo/'a.py').write_text('value = 1\n');git(self.repo,'add','.');git(self.repo,'commit','-qm','fixture')
        self.store=Store(self.root/'queue.db',max_workers=3,lease_seconds=10)
        self.model=FakeModel();self.server=make_server(('127.0.0.1',0),self.store,InferenceGate(self.store,self.model,limit=1),TOKEN)
        self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.server_thread.start()
        self.env=patch.dict(os.environ,{'STRATA_COORDINATOR_TOKEN':TOKEN});self.env.start()
        self.config={'mode':'direct','coordinator_url':f'http://127.0.0.1:{self.server.server_port}/v1','worker_concurrency':3,'event_wait_seconds':1,
                     'tests':{'unit':[sys.executable,'-c','import a; assert a.value == 2']}}
        self.m=QueuedManager(self.repo,self.root/'state',self.config)
    def tearDown(self):
        self.m.close()
        for t in self.m.threads:t.join(3)
        self.server.shutdown();self.server.server_close();self.server_thread.join();self.store.close();self.env.stop();self.tmp.cleanup()
    def wait(self,tid,states=('review_ready','needs_supervisor','failed','cancelled','applied')):
        until=time.monotonic()+20
        while time.monotonic()<until:
            result=self.m.summary(tid)
            if result['status'] in states:return result
            time.sleep(.05)
        self.fail('Task did not finish: '+str(result))

    def test_many_agents_share_queue_and_single_inference_slot(self):
        ids=[self.m.submit('Inspect fixture',owner=f'agent-{i}',request_key=f'req-{i}')['task_id'] for i in range(17)]
        self.assertEqual(len(set(ids)),17)
        results=[self.wait(t) for t in ids]
        self.assertTrue(all(r['status']=='review_ready' for r in results),results)
        self.assertEqual(self.model.peak,1)
        self.assertEqual((self.repo/'a.py').read_text(),'value = 1\n')
        self.assertEqual(self.m.submit('Inspect fixture',owner='agent-0',request_key='req-0')['task_id'],ids[0])
        self.assertTrue((self.root/'state/progress.json').exists())

    def test_auto_depth_survives_queue_and_worker(self):
        self.m.config['depth']='auto'
        seen=[]
        def chat_with_options(messages,tools,options):
            seen.append(options)
            return self.model.chat(messages,tools)
        self.model.chat_with_options=chat_with_options
        with self.assertRaisesRegex(ValueError,'auto requires'):
            self.m.submit('Inspect',owner='depth',request_key='missing')
        tid=self.m.submit('Inspect',owner='depth',request_key='auto',reasoning_effort='medium',depth_reason='Multiple related functions',max_output_tokens=4096)['task_id']
        result=self.wait(tid)
        self.assertEqual(result['status'],'review_ready',result)
        self.assertEqual(seen[0]['reasoning_effort'],'medium')
        self.assertEqual(seen[0]['max_output_tokens'],4096)
        self.assertEqual(result['depth_selection']['depth'],'auto')
        self.assertEqual(result['depth_selection']['depth_reason'],'Multiple related functions')
        with self.assertRaises(RuntimeError):
            self.m.submit('Inspect',owner='depth',request_key='auto',reasoning_effort='high',depth_reason='Changed decision')

    def test_edit_evidence_and_queued_apply(self):
        tid=self.m.submit('Fix value',mode='edit',allowed_paths=['a.py'],acceptance=['value 2'],test_ids=['unit'],owner='editor',request_key='edit')['task_id']
        r=self.wait(tid);self.assertEqual(r['status'],'review_ready',r)
        ev=self.m.get_evidence(tid,r['patch_id']);self.assertIn('+value = 2',ev['content_untrusted'])
        self.assertEqual((self.repo/'a.py').read_text(),'value = 1\n')
        self.m.apply(tid,r['patch_sha256'])
        self.assertEqual(self.wait(tid,('applied','needs_supervisor'))['status'],'applied')
        self.assertEqual((self.repo/'a.py').read_text(),'value = 2\n')

    def test_new_base_requires_new_review_even_if_diff_is_same(self):
        tid=self.m.submit('Fix value',mode='edit',allowed_paths=['a.py'],acceptance=['value 2'],test_ids=['unit'],owner='editor',request_key='rebase')['task_id']
        r=self.wait(tid);self.assertEqual(r['status'],'review_ready')
        git(self.repo,'commit','--allow-empty','-qm','new base')
        self.m.apply(tid,r['patch_sha256'])
        updated=self.wait(tid)
        self.assertEqual(updated['status'],'review_ready',updated)
        self.assertNotEqual(updated['patch_sha256'],r['patch_sha256'])
        self.assertEqual((self.repo/'a.py').read_text(),'value = 1\n')
        with self.assertRaises(RuntimeError):self.m.apply(tid,r['patch_sha256'])
        self.m.apply(tid,updated['patch_sha256'])
        self.assertEqual(self.wait(tid,('applied','needs_supervisor'))['status'],'applied')

    def test_auth_and_cross_workspace_access(self):
        tid=self.m.submit('Read',owner='reader',request_key='read')['task_id']
        with self.assertRaises(RuntimeError):self.m.broker.request('summary',{'workspace':'wrong','task_id':tid})
        other=BrokerClient(self.config);other.token='wrong-token'
        with self.assertRaises(RuntimeError):other.request('health')
        other.close();self.wait(tid)

if __name__=='__main__':unittest.main()
