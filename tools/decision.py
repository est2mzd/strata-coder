#!/usr/bin/env python3
"""Prepare briefs, obtain one tool-free Cursor batch decision, execute locally."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from strata_coder.decision import DecisionBatch
from strata_coder.decision_protocol import prompt as decision_prompt, expand
from strata_coder.locking import exclusive_lock
from strata_coder.queue_client import QueuedManager

FIELDS=('inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens')

def cursor_decide(batch,args):
    packets=batch.briefs()
    if not packets:raise ValueError('No pending briefs')
    previous=batch.data['cursor_usage']
    if any(r.get('usage') is None for r in previous):raise ValueError('Missing usage from prior run; further Cursor calls blocked')
    used=sum(sum(r['usage'][k] for k in FIELDS) for r in previous)
    step=getattr(args,'step',1)
    divisor={1:10,2:50,3:100}[step]
    cap=args.baseline_tokens//divisor
    if not args.measure_over_budget and used+args.reserve_tokens>cap:
        raise ValueError(f'Step {step} budget insufficient: spent={used}, reserve={args.reserve_tokens}, cap={cap}. No Cursor call made.')
    if len(previous)>=2:raise ValueError('At most two Cursor decision calls per batch')
    prompt=decision_prompt(batch)
    workspace=batch.state/'cursor-empty-workspace';workspace.mkdir(exist_ok=True)
    index=len(previous)+1
    log=batch.state/f'cursor-{index}.jsonl';err=batch.state/f'cursor-{index}.stderr'
    record={'protocol':'compact-v1','prompt_characters':len(prompt),'status':'started','usage':None,'baseline_tokens':args.baseline_tokens,'step':step,'target_ratio':1/divisor,'evaluation_override':args.measure_over_budget}
    previous.append(record);batch.save()
    started=time.monotonic()
    with log.open('w') as out,err.open('w') as error:
        try:
            p=subprocess.run([args.cli,'--workspace',str(workspace),'--model',args.model,'--trust','--mode','ask','--sandbox','enabled',
                              '-p','--output-format','stream-json',prompt],stdout=out,stderr=error,timeout=180)
        except subprocess.TimeoutExpired:
            record['status']='timeout';batch.save();raise ValueError('Cursor timed out; usage unknown, no replay')
    events=[json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    result=next((x for x in reversed(events) if x.get('type')=='result'),{})
    usage=result.get('usage')
    record.update(status='returned',elapsed_s=round(time.monotonic()-started,2),usage=usage if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in FIELDS) else None)
    if record['usage'] is not None:
        record['total_tokens']=sum(record['usage'][k] for k in FIELDS)
        record['within_budget']=used+record['total_tokens']<=cap
    batch.save()
    if p.returncode or result.get('is_error') or record['usage'] is None:raise ValueError('Cursor failed or usage missing; inspect local evidence')
    if any(x.get('type')=='tool_call' for x in events):raise ValueError('Supervisor used tools; decision rejected')
    text=result.get('result','').strip()
    if text.startswith('```'):text='\n'.join(text.splitlines()[1:-1])
    wire=json.loads(text)
    decisions=expand(batch,wire)
    record['wire_response']=wire
    if {d['id'] for d in decisions}!={p['id'] for p in packets}:raise ValueError('Cursor must address every pending brief')
    batch.data['proposed_decisions']=decisions;batch.save()
    (batch.state/'decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+'\n')
    return {'decisions':decisions,'usage':record['usage'],'within_budget':record['within_budget'],
            'note':'Measured limit; Cursor CLI cannot guarantee a hard total-token ceiling before generation.'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['prepare','briefs','prompt','cursor','execute','status'])
    p.add_argument('--state',required=True);p.add_argument('--repo');p.add_argument('--config');p.add_argument('--missions');p.add_argument('--decisions')
    p.add_argument('--cli');p.add_argument('--model',default='composer-2.5');p.add_argument('--baseline-tokens',type=int,default=0)
    p.add_argument('--step',type=int,choices=[1,2,3],default=1,help='1: <=10%, 2: <=2%, 3: <=1% of baseline')
    p.add_argument('--reserve-tokens',type=int,default=16000)
    p.add_argument('--measure-over-budget',action='store_true',help='Evaluation only: measure even if reserve exceeds target; never mark as passing')
    a=p.parse_args();state=Path(a.state).resolve();state.mkdir(parents=True,exist_ok=True,mode=0o700)
    lock=exclusive_lock(state/'decision.lock');manager=None
    try:
        if a.action in ('prepare','execute'):
            if not a.repo:raise ValueError('--repo required')
            cfg=json.loads(Path(a.config).read_text()) if a.config else json.loads(os.environ.get('STRATA_CODER_CONFIG','{}'))
            manager=QueuedManager(a.repo,state/'workers',cfg)
        b=DecisionBatch(state,manager)
        if a.action=='prepare':
            if not a.missions:raise ValueError('--missions required')
            result=b.prepare(json.loads(Path(a.missions).read_text()))
        elif a.action=='execute':
            if not a.decisions:raise ValueError('--decisions required')
            if any(r.get('within_budget') is not True and not r.get('evaluation_override') for r in b.data['cursor_usage']):
                raise ValueError('Cursor budget exceeded or usage unknown; execution blocked')
            value=json.loads(Path(a.decisions).read_text())
            result=b.decide(expand(b,value) if isinstance(value,dict) else value)
        elif a.action=='cursor':
            if not a.cli or a.baseline_tokens<=0 or a.reserve_tokens<1:raise ValueError('--cli and positive --baseline-tokens/--reserve-tokens required')
            result=cursor_decide(b,a)
        elif a.action=='briefs':result=b.briefs()
        elif a.action=='prompt':
            print(decision_prompt(b));return
        else:result={'missions':b.status(),'cursor_usage':b.data['cursor_usage']}
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        if manager:manager.close()
        lock.close()

if __name__=='__main__':main()
