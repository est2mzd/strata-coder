#!/usr/bin/env python3
"""Reproduce a matched Cursor-only / Strata decision smoke, preserving failures.

Uses an existing coordinator configuration. Does not start services or handle SSH
passwords. Each invocation requires a new output directory. Real runs consume
Cursor tokens; --prepare-only creates the repositories without model calls.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from strata_coder.core import git
from decision import FIELDS


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', required=True)
    p.add_argument('--cli')
    p.add_argument('--config', help='queued config; unit test ID is set by this evaluator')
    p.add_argument('--model', default='composer-2.5')
    p.add_argument('--prepare-only', action='store_true')
    a = p.parse_args()
    if not a.prepare_only and (not a.cli or not a.config):
        p.error('--cli and --config are required for a real evaluation')
    out = Path(a.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixture = ROOT/'tests/fixtures/pagination'
    report = {'fixture':'pagination', 'model':a.model, 'complete':False,
              'quality_passed':False, 'initial_sha256':{}, 'runs':[]}
    def save():
        (out/'report.json').write_text(json.dumps(report, indent=2) + '\n')
    def run(label, argv, cwd=out):
        with (out/(label+'.stdout')).open('w') as stdout, (out/(label+'.stderr')).open('w') as stderr:
            try:
                rc = subprocess.run(argv, cwd=cwd, stdout=stdout, stderr=stderr,
                                    timeout=1800).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        report['runs'].append({'label':label, 'exit_code':rc});save()
        return rc
    for arm in ('cursor-only', 'strata'):
        repo = out/arm;repo.mkdir();git(repo,'init','-q')
        git(repo,'config','user.name','Evaluation');git(repo,'config','user.email','evaluation@example.invalid')
        for name in ('subject.py','test_subject.py'):
            raw = (fixture/name).read_bytes();(repo/name).write_bytes(raw)
            report['initial_sha256'][name] = hashlib.sha256(raw).hexdigest()
        git(repo,'add','.');git(repo,'commit','-qm','fixed evaluation fixture')
    save()
    if a.prepare_only:
        print(str(out/'report.json'));return
    cli = str(Path(a.cli).resolve())
    config = json.loads(Path(a.config).read_text())
    config['tests'] = {'unit':[sys.executable,'-m','unittest','discover','-v']}
    (out/'config.json').write_text(json.dumps(config));os.chmod(out/'config.json',0o600)
    contracts = json.loads((fixture/'missions.json').read_text())
    (out/'missions.json').write_text(json.dumps(contracts))
    objective = contracts[0]['objective']
    baseline_rc = run('baseline', [cli,'--workspace',str(out/'cursor-only'),'--model',a.model,
        '--trust','--sandbox','enabled','-p','--output-format','stream-json',
        objective+' Only modify subject.py. Run python3 -m unittest discover -v. Do not commit.'])
    events = [json.loads(line) for line in (out/'baseline.stdout').read_text().splitlines() if line.strip()]
    result = next((e for e in reversed(events) if e.get('type')=='result'), {})
    usage = result.get('usage', {})
    if not all(type(usage.get(k)) is int and usage[k]>=0 for k in FIELDS):
        report['error']='Baseline usage missing; comparison blocked';save();return
    report['baseline_usage'] = usage
    report['baseline_tokens'] = sum(usage[k] for k in FIELDS)
    if report['baseline_tokens'] <= 0:
        report['error']='Baseline has no measurable usage';save();return
    baseline_test = run('baseline-tests',[sys.executable,'-m','unittest','discover','-v'],out/'cursor-only')
    state = out/'batch'
    common = ['--state',str(state),'--repo',str(out/'strata'),'--config',str(out/'config.json')]
    rc = 0
    for phase, extra in [('prepare',['--missions',str(out/'missions.json')]),
                         ('cursor',['--cli',cli,'--model',a.model,'--baseline-tokens',str(report['baseline_tokens']),
                                    '--step','1','--measure-over-budget']),
                         ('execute',['--decisions',str(state/'decisions.json')])]:
        rc = run(phase,[sys.executable,str(ROOT/'tools/decision.py'),phase,*common,*extra])
        if rc:break
    strata_test = run('strata-tests',[sys.executable,'-m','unittest','discover','-v'],out/'strata')
    if (state/'batch.json').exists():
        batch = json.loads((state/'batch.json').read_text())
        report['cursor_usage'] = batch['cursor_usage']
        report['mission_states'] = [m['status'] for m in batch['missions'].values()]
        records = batch['cursor_usage']
        if records and all(r.get('usage') is not None for r in records):
            total = sum(sum(r['usage'][k] for k in FIELDS) for r in records)
            report['strata_cursor_tokens'] = total
            report['ratio'] = total/report['baseline_tokens']
    scope_ok = all(set(git(out/arm,'diff','--name-only').splitlines())=={'subject.py'} and
                   all(name.startswith('__pycache__/') and name.endswith('.pyc')
                       for name in git(out/arm,'ls-files','--others','--exclude-standard').splitlines())
                   for arm in ('cursor-only','strata'))
    report['quality_passed'] = (baseline_rc==baseline_test==rc==strata_test==0 and not result.get('is_error')
                               and report.get('mission_states')==['applied'] and scope_ok)
    report['complete'] = True
    report['step1_passed'] = report['quality_passed'] and report.get('ratio',1)<=.1
    save();print(str(out/'report.json'))

if __name__=='__main__':main()
