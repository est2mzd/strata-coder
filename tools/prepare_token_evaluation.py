"""Prepare identical, isolated Cursor-only/delegated fixtures; does not run models."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

TASKS = {
 'pagination': {
  'source': 'def pages(items, size):\n    return [items[i:i+size] for i in range(0, len(items)-size, size)]\n',
  'prompt': 'Fix pages(items, size): preserve all items in order, return chunks of at most size, return [] for empty input, and raise ValueError for size <= 0. Only modify subject.py.',
  'checks': 'assert f.pages([1,2,3,4,5],2)==[[1,2],[3,4],[5]]\nassert f.pages([1,2,3,4],2)==[[1,2],[3,4]]\nassert f.pages([],2)==[]\nfor n in (0,-1):\n try: f.pages([1],n)\n except ValueError: pass\n else: raise AssertionError("nonpositive size")\n'},
 'intervals': {
  'source': 'def merge(intervals):\n    out=[]\n    for start,end in intervals:\n        if out and start < out[-1][1]:\n            out[-1][1]=end\n        else:\n            out.append([start,end])\n    return out\n',
  'prompt': 'Fix merge(intervals): accept unsorted valid closed intervals, merge overlaps and touching endpoints, preserve nested interval ends, return sorted list-of-lists, and never mutate the input. Only modify subject.py.',
  'checks': 'x=[[8,10],[1,5],[2,3],[5,7]]\nassert f.merge(x)==[[1,7],[8,10]]\nassert x==[[8,10],[1,5],[2,3],[5,7]]\nassert f.merge([])==[]\nassert f.merge([[1,9],[3,4]])==[[1,9]]\n'},
 'cache': {
  'source': 'class Cache:\n    def __init__(self): self.entries={}\n    def put(self,key,value,ttl,now): self.entries[key]=(value,ttl)\n    def get(self,key,now,default=None):\n        if key not in self.entries: return default\n        value,expires=self.entries[key]\n        return value if now <= expires else default\n',
  'prompt': 'Fix Cache: put stores an expiry of now+ttl; entries expire at now >= expiry and are removed on expired reads. Stored None remains a valid value. Missing keys return default. Only modify subject.py.',
  'checks': 'c=f.Cache()\nc.put("a",None,5,100)\nassert c.get("a",104,"missing") is None\nassert c.get("a",105,"missing")=="missing"\nassert "a" not in c.entries\nassert c.get("absent",0,42)==42\n'}
}

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--repeats',type=int,default=2);a=p.parse_args()
 root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=True)
 if any(root.iterdir()):raise SystemExit('Output must be empty; existing runs are never overwritten')
 rows=[]
 for repeat in range(a.repeats):
  for name,task in TASKS.items():
   order=('cursor-only','strata') if repeat%2==0 else ('strata','cursor-only')
   for arm in order:
    path=root/f'{name}-{repeat+1}-{arm}';path.mkdir()
    (path/'subject.py').write_text(task['source'])
    # Both arms see the same tests. Extra checks are run by the evaluator outside the workspace.
    (path/'test_subject.py').write_text('import unittest\nimport subject\n\nclass Smoke(unittest.TestCase):\n    def test_import(self):\n        self.assertIsNotNone(subject)\n')
    for args in (('init','-q'),('config','user.name','Evaluation'),('config','user.email','evaluation@example.invalid'),('add','.'),('commit','-qm','Identical fixture')):
     subprocess.run(['git','-C',str(path),*args],check=True)
    (path/'.git/info/exclude').write_text('.cursor/\n__pycache__/\n')
    base=subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    prompt=task['prompt']+' Run tests and report evidence. Do not commit, push, access the network, or use unrelated MCP servers.'
    if arm=='strata':prompt+=' Use Strata-Coder for investigation/edit/testing. You supervise: select auto depth with reasoning_effort and reason, review the complete patch and final test evidence, then apply the reviewed hash and verify applied. At most two delegations and 30 total max_steps. Include failure recovery in this session.'
    else:prompt+=' Perform the work yourself without Strata-Coder.'
    rows.append(dict(task=name,repeat=repeat+1,arm=arm,workspace=str(path),base=base,prompt=prompt,source_sha256=hashlib.sha256(task['source'].encode()).hexdigest(),cursor_usage=None,status='not_run'))
 (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
 (root/'checks.json').write_text(json.dumps({k:v['checks'] for k,v in TASKS.items()},indent=2)+'\n')
 print(f'Prepared {len(rows)} runs; no models invoked, no token measurements yet.')

if __name__=='__main__':main()
