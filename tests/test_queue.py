import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from strata_coder.coordinator import Store, Conflict, InferenceGate


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'q.db'
        self.s=Store(self.path,max_workers=3,capacity=200,per_owner=150,lease_seconds=20)
    def tearDown(self):self.s.close();self.tmp.cleanup()
    def submit(self,key,owner='a',ws='w'):
        return self.s.submit(ws,owner,key,{'objective':key},'base')['task_id']
    def finish(self,job,status='review_ready',result=None):
        self.s.finish(job['workspace'],job['id'],job['lease'],status,result or {})

    def test_variable_agent_counts_and_capacity(self):
        for count in (1,7,30,73):
            ids=[]
            with ThreadPoolExecutor(max_workers=12) as ex:
                ids=list(ex.map(lambda i:self.submit(f'{count}-{i}',owner=f'agent-{i}'),range(count)))
            self.assertEqual(len(set(ids)),count)
            jobs=[self.s.claim('w',f'worker-{i}') for i in range(4)]
            self.assertEqual(sum(j is not None for j in jobs),min(count,3))
            for j in jobs:
                if j:self.finish(j)
            for tid in ids:
                if self.s.summary('w',tid)['status']=='queued':self.s.cancel('w',tid)

    def test_atomic_idempotency_and_conflicting_retry(self):
        with ThreadPoolExecutor(max_workers=12) as ex:
            ids=list(ex.map(lambda _:self.submit('same'),range(40)))
        self.assertEqual(len(set(ids)),1)
        with self.assertRaises(Conflict):self.s.submit('w','a','same',{'objective':'different'},'base')

    def test_fair_owner_rotation(self):
        for i in range(5):self.submit(str(i),'a')
        b=self.submit('b','b');c=self.submit('c','c')
        jobs=[self.s.claim('w',f'worker-{i}') for i in range(3)]
        self.assertEqual([j['owner'] for j in jobs],['a','b','c'])

    def test_cancel_queued_and_fence_expired_worker(self):
        tid=self.submit('a');self.s.cancel('w',tid)
        self.assertIsNone(self.s.claim('w','worker'))
        tid=self.submit('b');j=self.s.claim('w','worker')
        self.s.db.execute('UPDATE tasks SET expires=0 WHERE id=?',(tid,))
        self.assertEqual(self.s.summary('w',tid)['status'],'interrupted')
        with self.assertRaises(Conflict):self.finish(j)
        self.assertIsNone(self.s.claim('w','other'))

    def test_restart_preserves_queue_and_interrupts_running(self):
        a=self.submit('a');b=self.submit('b');j=self.s.claim('w','worker')
        self.s.set_meta('inference_active','1');self.s.close()
        self.s=Store(self.path)
        self.assertEqual(self.s.summary('w',j['id'])['status'],'interrupted')
        self.assertEqual(self.s.summary('w',b)['status'],'queued')
        self.assertTrue(self.s.health()['inference_blocked'])

    def test_apply_queue_serialization_and_hash(self):
        for i in range(2):
            tid=self.submit(str(i));j=self.s.claim('w','worker')
            self.finish(j,result={'changed_files':['a.py'],'patch_sha256':str(i)})
            with self.assertRaises(Conflict):self.s.apply('w',tid,'wrong')
            self.s.apply('w',tid,str(i))
        a=self.s.claim('w','apply','apply')
        self.assertIsNone(self.s.claim('w','other','apply'))
        self.finish(a,'applied')
        self.assertIsNotNone(self.s.claim('w','other','apply'))

    def test_apply_fifo_uses_approval_order_not_task_age(self):
        ids=[]
        for i in range(2):
            tid=self.submit(str(i));j=self.s.claim('w','worker')
            self.finish(j,result={'changed_files':['a.py'],'patch_sha256':str(i)})
            ids.append(tid)
        self.s.apply('w',ids[1],'1');self.s.apply('w',ids[0],'0')
        self.assertEqual(self.s.claim('w','apply','apply')['id'],ids[1])

    def test_uncertain_apply_quarantines_workspace(self):
        tid=self.submit('a');j=self.s.claim('w','worker')
        self.finish(j,result={'changed_files':['a.py'],'patch_sha256':'hash'})
        self.s.apply('w',tid,'hash');j=self.s.claim('w','apply','apply')
        self.s.db.execute('UPDATE tasks SET expires=0 WHERE id=?',(tid,));self.s.expire()
        self.assertTrue(self.s.db.execute('SELECT 1 FROM blocked_apply WHERE workspace="w"').fetchone())

    def test_global_fairness_for_available_workspaces(self):
        self.s.claim('one','one-worker');self.s.claim('two','two-worker')
        self.submit('1','owner1','one');self.submit('2','owner2','two');self.submit('3','owner1','one')
        j=self.s.claim('one','one-worker');self.finish(j)
        self.assertIsNone(self.s.claim('one','one-worker'))
        self.assertEqual(self.s.claim('two','two-worker')['owner'],'owner2')

    def test_inference_concurrency_separate_from_workers(self):
        active=0;peak=0;lock=threading.Lock()
        class Upstream:
            def chat(self,messages,tools):
                nonlocal active,peak
                with lock:active+=1;peak=max(peak,active)
                time.sleep(.04)
                with lock:active-=1
                return {'ok':True}
        gate=InferenceGate(self.s,Upstream(),limit=1)
        jobs=[]
        for i in range(3):self.submit(str(i),str(i));jobs.append(self.s.claim('w',str(i)))
        with ThreadPoolExecutor(max_workers=3) as ex:
            results=list(ex.map(lambda j:gate.run('w',j['id'],j['lease'],[],[]),jobs))
        self.assertEqual(peak,1);self.assertEqual(len(results),3)
        self.assertEqual(self.s.get_meta('inference_active'),'0')

    def test_unknown_inference_outcome_pauses_admission(self):
        class Broken:
            def chat(self,*a):raise TimeoutError()
        self.submit('a');j=self.s.claim('w','worker');g=InferenceGate(self.s,Broken())
        with self.assertRaises(RuntimeError):g.run('w',j['id'],j['lease'],[],[])
        self.assertTrue(self.s.health()['inference_blocked'])
        with self.assertRaises(Conflict):g.run('w',j['id'],j['lease'],[],[])

    def test_queue_limit_backpressure(self):
        self.s.capacity=1;self.submit('a')
        with self.assertRaises(Conflict):self.submit('b')
        self.assertTrue(self.s.submit('w','a','a',{'objective':'a'},'base')['deduplicated'])

    def test_event_cursor_does_not_repeat(self):
        self.submit('a');batch=self.s.events('w')
        self.assertEqual(len(batch['events']),1)
        self.assertEqual(self.s.events('w',batch['cursor'])['events'],[])

if __name__=='__main__':unittest.main()
