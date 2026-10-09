import json
import tempfile
import unittest
from pathlib import Path
from strata_coder.depth import resolve
from strata_coder.transport import Transport
from strata_coder.coordinator import Store, InferenceGate

class DepthTests(unittest.TestCase):
    def test_auto_requires_decision_and_reason(self):
        for kwargs in ({}, {'reasoning_effort':'high'}, {'reasoning_effort':'invalid','depth_reason':'hard'}):
            with self.assertRaises(ValueError):resolve({'depth':'auto'},**kwargs)
        self.assertEqual(resolve({'depth':'auto'},reasoning_effort='medium',depth_reason='multiple files')['reasoning_effort'],'medium')

    def test_explicit_override_and_conflict(self):
        self.assertEqual(resolve({'depth':'high'},depth='low')['reasoning_effort'],'low')
        with self.assertRaises(ValueError):resolve({'depth':'low'},reasoning_effort='high')
        for tokens in (0,8193,True,'2048'):
            with self.assertRaises(ValueError):resolve({},max_output_tokens=tokens)

    def test_transport_payload_and_unsupported(self):
        t=Transport({'model':'fixture','max_output_tokens':1024})
        t.request=lambda route, body=None: body
        for effort in ('low','medium','high'):
            response=t.chat_with_options([],[],dict(reasoning_effort=effort,max_output_tokens=4096))
            self.assertEqual(response['reasoning_effort'],effort)
            self.assertEqual(response['max_tokens'],4096)
        t.config['reasoning_support']='unsupported'
        with self.assertRaisesRegex(ValueError,'does not support'):t.chat_with_options([],[],{'reasoning_effort':'high'})

    def test_coordinator_uses_immutable_contract_and_isolates_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(Path(tmp)/'queue.db',max_workers=2)
            upstream=Transport({'model':'fixture'})
            upstream.request=lambda route, body=None:body
            gate=InferenceGate(store,upstream,limit=1)
            for i,effort in enumerate(('high','low')):
                contract={'objective':'inspect',**resolve({},depth='auto',reasoning_effort=effort,depth_reason='fixture',max_output_tokens=3000+i)}
                tid=store.submit('ws','owner',str(i),contract,'base')['task_id']
                job=store.claim('ws','worker','work')
                result=gate.run('ws',tid,job['lease'],[],[])
                self.assertEqual(result['reasoning_effort'],effort)
                self.assertEqual(result['max_tokens'],3000+i)
                self.assertEqual(store.summary('ws',tid)['depth_selection']['depth'],'auto')
                self.assertEqual(store.events('ws')['events'][-1]['depth_selection']['reasoning_effort'],effort)
                store.finish('ws',tid,job['lease'],'review_ready',{})
            upstream.config['reasoning_support']='unsupported'
            tid=store.submit('ws','owner','blocked',{'objective':'inspect',**resolve({},depth='high')},'base')['task_id']
            job=store.claim('ws','worker','work')
            with self.assertRaisesRegex(ValueError,'does not support'):gate.run('ws',tid,job['lease'],[],[])
            self.assertFalse(store.get_meta('inference_blocked'))
