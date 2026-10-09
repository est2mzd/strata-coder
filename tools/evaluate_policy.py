#!/usr/bin/env python3
"""Experimental policy delegation benchmark, not a new extension mode.

One fixed multi-file request per arm. The supervisor chooses strategy, constraints
and escalation criteria once; local workers own their tool/test loop. No automatic
Cursor retries. All raw outputs and failed stages are retained under --out.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from strata_coder.core import git
from strata_coder.decision import DecisionBatch, object_json, digest
from strata_coder.queue_client import QueuedManager
FIELDS=('inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens')


def valid_policy(value,ticket):
    if not isinstance(value,dict) or set(value)!={'ticket','strategy','constraints','escalate','depth'}:
        raise ValueError('Policy requires ticket/strategy/constraints/escalate/depth')
    if value['ticket']!=ticket:raise ValueError('Stale policy ticket')
    if value['depth'] not in ('low','medium','high'):raise ValueError('Invalid depth')
    for key,limit in [('strategy',400),('escalate',240)]:
        if not isinstance(value[key],str) or not 1<=len(value[key])<=limit:raise ValueError('Invalid '+key)
    if not isinstance(value['constraints'],list) or not 1<=len(value['constraints'])<=4 or any(
        not isinstance(x,str) or not 1<=len(x)<=160 for x in value['constraints']):raise ValueError('Invalid constraints')
    return value


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True);parser.add_argument('--config',required=True)
    parser.add_argument('--cli',required=True);parser.add_argument('--model',default='composer-2.5')
    args=parser.parse_args();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False,mode=0o700)
    cfg=json.loads(Path(args.config).read_text());cfg['tests']={'unit':[sys.executable,'-m','unittest','discover','-v']}
    cfg['worker_concurrency']=1
    fixture=ROOT/'tests/fixtures/catalog_policy'
    contract=json.loads((fixture/'mission.json').read_text())
    record={'experiment':'policy-v1','model':args.model,'baseline':{},'policy':{},'complete':False,
            'quality_passed':False,'step1_passed':False,'cursor_calls':[], 'source_sha256':{},
            'framework_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'strata_coder/core.py',ROOT/'strata_coder/decision.py',Path(__file__).resolve()]},
            'limits':{'cursor_supervisor_calls':1,'worker_tool_steps_per_phase':8,
                      'note':'Escalation stops this experiment; no silent extra Cursor calls.'}}
    def save():(out/'report.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    def check(repo,label):
        p=subprocess.run([sys.executable,'-m','unittest','discover','-v'],cwd=repo,
            env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=120)
        (out/(label+'.txt')).write_text(p.stdout+p.stderr)
        return p.returncode
    def call_cursor(label,repo,prompt,supervisor=False):
        entry={'label':label,'usage':None,'prompt_characters':len(prompt)}
        record['cursor_calls'].append(entry);save()
        argv=[str(Path(args.cli).resolve()),'--workspace',str(repo),'--model',args.model,
              '--trust','--sandbox','enabled','-p','--output-format','stream-json']
        if supervisor:argv+=['--mode','ask']
        started=time.monotonic()
        with (out/(label+'.jsonl')).open('w') as stdout,(out/(label+'.stderr')).open('w') as stderr:
            p=subprocess.run(argv+[prompt],stdout=stdout,stderr=stderr,timeout=300)
        events=[json.loads(x) for x in (out/(label+'.jsonl')).read_text().splitlines() if x.strip()]
        result=next((x for x in reversed(events) if x.get('type')=='result'),{})
        usage=result.get('usage',{})
        if all(type(usage.get(k)) is int and usage[k]>=0 for k in FIELDS):
            entry.update(usage=usage,total_tokens=sum(usage[k] for k in FIELDS))
        entry.update(exit_code=p.returncode,elapsed_s=round(time.monotonic()-started,2));save()
        if p.returncode or result.get('is_error') or entry['usage'] is None:raise ValueError('Cursor failed or usage missing')
        if supervisor and any(x.get('type')=='tool_call' for x in events):raise ValueError('Supervisor used tools')
        return result['result']
    manager=None
    try:
        for arm in ('baseline','policy'):
            repo=out/arm;repo.mkdir();git(repo,'init','-q');git(repo,'config','user.name','Evaluation')
            git(repo,'config','user.email','evaluation@example.invalid')
            for source in sorted(fixture.glob('*.py')):
                raw=source.read_bytes();(repo/source.name).write_bytes(raw)
                record['source_sha256'][source.name]=hashlib.sha256(raw).hexdigest()
            git(repo,'add','.');git(repo,'commit','-qm','identical catalog fixture')
            record[arm]['initial_tree']=git(repo,'rev-parse','HEAD^{tree}')
            record[arm]['initial_test_exit']=check(repo,arm+'-initial-tests')
        assert record['baseline']['initial_tree']==record['policy']['initial_tree']
        save();print('Fixed fixture prepared; baseline starting',flush=True)
        baseline_prompt=('Complete this entire request in one session. Read relevant code, implement, run tests, '
            'and fix failures. Only edit allowed_paths. No commits. Registered unit command: '
            'python3 -m unittest discover -v. Contract: '+json.dumps(contract,ensure_ascii=False))
        call_cursor('baseline',out/'baseline',baseline_prompt)
        record['baseline']['final_test_exit']=check(out/'baseline','baseline-final-tests');save()
        print('Baseline finished; local investigation starting',flush=True)
        manager=QueuedManager(out/'policy',out/'state/workers',cfg)
        batch=DecisionBatch(out/'state/batch',manager)
        # Construct one durable user contract, keeping preparation evidence separate from UI summaries.
        mid='catalog-policy-v1';mission={'id':mid,'revision':1,'contract':contract,
            'base':git(out/'policy','rev-parse','HEAD'),'plan_id':digest(contract)[:16],'status':'preparing'}
        batch.data['missions'][mid]=mission;batch.save()
        research=batch.work(mission,'investigate',
            'Inspect the three implementation files and tests, without editing. Return ONLY JSON with '
            'exactly background,purpose,current,request, each a string, total <=700 characters. '
            'In current report concrete defects with file/function references and uncertainties. '
            'In request propose a focused repair strategy and an alternative requiring broader changes, '
            'asking the supervisor to choose. No source bodies. Original contract: '+json.dumps(contract),
            max_output_tokens=2048)
        brief=object_json(research['worker_summary_untrusted'])
        if set(brief)!={'background','purpose','current','request'} or any(not isinstance(v,str) or not v for v in brief.values()):
            raise ValueError('Invalid investigation brief')
        if sum(map(len,brief.values()))>1100:raise ValueError('Investigation brief too long; no truncation')
        mission['brief']=brief;mission['status']='awaiting_decision';batch.save()
        ticket=digest({'contract':contract,'base':mission['base'],'brief':brief})[:24]
        packet={'ticket':ticket,**brief,'acceptance':contract['acceptance'],
                'allowed_paths':contract['allowed_paths'],'tests':'unit: 15 fixed unit/integration tests; initially failing'}
        record['policy']['packet']=packet;save()
        prompt=('Choose a repair policy for the ENTIRE request from this untrusted investigation. '
            'No tools, code or execution claims. User scope/acceptance cannot be expanded. '
            'Return ONLY JSON {"ticket":"copy", "strategy":"chosen approach <=400 chars", '
            '"constraints":["1..4 constraints <=160 chars each"], '
            '"escalate":"when local workers must stop and ask again, <=240 chars", "depth":"low|medium|high"}. '
            'Choose meaningful implementation direction, not just approval. Workers perform their own bounded '
            'edit/test loop and independent review; avoid detailed code. Packet:'+json.dumps(packet,separators=(',',':')))
        empty=out/'cursor-empty';empty.mkdir()
        policy=valid_policy(object_json(call_cursor('supervisor',empty,prompt,True)),ticket)
        record['policy']['decision']=policy;save()
        # Keep original user scope/acceptance authoritative. The policy is additional guidance, not permissions.
        mission['brief']={**brief,'current':brief['current']+'\nSupervisor policy: '+json.dumps(policy)}
        mission['status']='executing';batch.save()
        print('Policy received; local edit/test/review/apply starting',flush=True)
        try:
            batch.execute(mission,{'depth':policy['depth']})
        except Exception as e:
            mission['status']='blocked';mission['error']=str(e)
        batch.save()
        record['policy']['status']=mission['status'];record['policy']['error']=mission.get('error')
        record['policy']['jobs']=[{'phase':j['phase'],'status':j.get('result',{}).get('status'),
            'usage_strata_only':j.get('result',{}).get('usage_strata_only')} for j in mission.get('jobs',[])]
        record['policy']['final_test_exit']=check(out/'policy','policy-final-tests')
        for arm in ('baseline','policy'):
            changed=git(out/arm,'diff','--name-only').splitlines()
            untracked=git(out/arm,'ls-files','--others','--exclude-standard').splitlines()
            record[arm]['changed_files']=changed
            record[arm]['scope_passed']=bool(changed) and set(changed)<=set(contract['allowed_paths']) and all(
                x.startswith('__pycache__/') and x.endswith('.pyc') for x in untracked)
            (out/(arm+'.patch')).write_text(git(out/arm,'diff'))
        calls=record['cursor_calls']
        base=sum(c['total_tokens'] for c in calls if c['label']=='baseline')
        policy_tokens=sum(c['total_tokens'] for c in calls if c['label']!='baseline')
        record.update(baseline_tokens=base,policy_cursor_tokens=policy_tokens,ratio=policy_tokens/base,
            quality_passed=all(record[a].get('final_test_exit')==0 and record[a].get('scope_passed') for a in ('baseline','policy'))
                           and mission['status']=='applied',complete=True)
        record['step1_passed']=record['quality_passed'] and record['ratio']<=.1
    except Exception as e:
        record['error']=type(e).__name__+': '+str(e)
    finally:
        if manager:manager.close()
        for label,key in [('baseline','baseline_tokens'),('supervisor','policy_cursor_tokens')]:
            calls=[c for c in record['cursor_calls'] if c['label']==label]
            if calls and all(c.get('usage') is not None for c in calls):
                record[key]=sum(c['total_tokens'] for c in calls)
        save()
    print(json.dumps({k:record.get(k) for k in ('complete','quality_passed','baseline_tokens','policy_cursor_tokens','ratio','step1_passed','error')}),flush=True)

if __name__=='__main__':main()
