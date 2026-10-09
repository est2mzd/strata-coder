"""Synthetic queue/admission load test. Never calls Cursor or a real Strata model."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from strata_coder.coordinator import Store, InferenceGate


def run(agents,workers,inference,tasks_per_agent):
    total=agents*tasks_per_agent
    with tempfile.TemporaryDirectory(prefix='strata-load-') as tmp:
        store=Store(Path(tmp)/'queue.db',max_workers=workers,capacity=total+1,per_owner=tasks_per_agent+1,lease_seconds=60)
        lock=threading.Lock();stats={'completed':0,'active_inference':0,'peak_inference':0,'errors':[]}
        class Model:
            def chat(self,*args):
                with lock:
                    stats['active_inference']+=1
                    stats['peak_inference']=max(stats['peak_inference'],stats['active_inference'])
                time.sleep(.01)
                with lock:stats['active_inference']-=1
                return {'fixture':True}
        gate=InferenceGate(store,Model(),limit=inference)
        start=time.monotonic()
        def submit(i):
            return store.submit('fixture',f'agent-{i//tasks_per_agent}',f'job-{i}',{'objective':'synthetic'},'base')
        with ThreadPoolExecutor(max_workers=min(32,agents)) as pool:list(pool.map(submit,range(total)))
        deadline=time.monotonic()+120
        def work(i):
            while time.monotonic()<deadline:
                with lock:
                    if stats['completed']>=total or stats['errors']:return
                job=store.claim('fixture',f'worker-{i}')
                if not job:time.sleep(.005);continue
                try:
                    gate.run('fixture',job['id'],job['lease'],[],[])
                    store.finish('fixture',job['id'],job['lease'],'review_ready',{'fixture':True})
                    with lock:stats['completed']+=1
                except Exception as e:
                    with lock:stats['errors'].append(str(e))
                    return
        with ThreadPoolExecutor(max_workers=workers) as pool:list(pool.map(work,range(workers)))
        result={'kind':'synthetic-not-a-model-benchmark','agents':agents,'tasks':total,'worker_limit':workers,
                'inference_limit':inference,'completed':stats['completed'],'peak_inference':stats['peak_inference'],
                'elapsed_s':round(time.monotonic()-start,3),'cursor_tokens':None,'errors':stats['errors']}
        store.close()
        if result['completed']!=total or result['peak_inference']>inference or result['errors']:
            raise RuntimeError(json.dumps(result))
        return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--agents',type=int,default=7);p.add_argument('--workers',type=int,default=4)
    p.add_argument('--inference',type=int,default=1);p.add_argument('--tasks-per-agent',type=int,default=2)
    a=p.parse_args()
    if not (1<=a.agents<=1000 and 1<=a.workers<=64 and 1<=a.inference<=64 and 1<=a.tasks_per_agent<=100):
        p.error('agents: 1..1000; workers/inference: 1..64; tasks-per-agent: 1..100')
    print(json.dumps(run(a.agents,a.workers,a.inference,a.tasks_per_agent),indent=2))
