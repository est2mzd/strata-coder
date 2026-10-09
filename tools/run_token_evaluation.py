"""Run a prepared paired pilot through authenticated Cursor CLI and a running coordinator.
Raw transcripts can contain private context: keep output local and publish only audited results.
"""
import argparse,json,os,signal,subprocess,sys,time
from pathlib import Path

def git(repo,*args):
 return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()

def main():
 p=argparse.ArgumentParser();p.add_argument('--fixtures',required=True);p.add_argument('--output',required=True);p.add_argument('--cli',required=True);p.add_argument('--coordinator-url',required=True);p.add_argument('--token-file',required=True);p.add_argument('--model',default='composer-2.5');args=p.parse_args()
 root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=True)
 if any(root.iterdir()):raise SystemExit('Output must be empty')
 fixtures=Path(args.fixtures).resolve();secret=Path(args.token_file).resolve()
 rows=json.loads((fixtures/'runs.json').read_text());results=[]
 cli=Path(args.cli).resolve();gateway=Path(__file__).resolve().parent/'gateway.py'
 for i,row in enumerate(rows):
  repo=Path(row['workspace']);label=repo.name
  # Remove exploratory hooks; usage is supplied by Cursor's terminal result event.
  (repo/'.cursor/hooks.json').unlink(missing_ok=True)
  if row['arm']=='strata':
   cfg={'execution_mode':'queued','depth':'auto','mode':'direct','coordinator_url':args.coordinator_url,'coordinator_token_file':str(secret),'worker_concurrency':1,'max_output_tokens':4096,'tests':{'unit':['python3','-m','unittest','discover','-v']}}
   (repo/'.cursor/mcp.json').write_text(json.dumps({'mcpServers':{'strata-coder-eval':{'command':'python3','args':[str(gateway),'--repo',str(repo),'--state',str(root/'states'/label)],'env':{'STRATA_CODER_CONFIG':json.dumps(cfg)}}}}))
  prompt=row['prompt']+' Do not spawn subagents. Do not edit test files or .cursor configuration. Use only this workspace; do not inspect parent directories or evaluation files. Keep your final report concise.'
  if row['arm']=='strata':prompt+=' The authorized Strata-Coder MCP connection is allowed. Use owner="evaluation", a unique request_key, allowed_paths=["subject.py"], test_ids=["unit"]. Fetch full patch and final test evidence before apply. Await the task with bounded summary waits; do not finish the session before applying and verifying. Model classification requires no separate tool call.'
  print(f'RUN {i+1}/{len(rows)} {label}',flush=True)
  started=time.monotonic()
  with (root/f'{label}.jsonl').open('w') as out,(root/f'{label}.stderr').open('w') as err:
   proc=subprocess.Popen([str(cli),'--workspace',str(repo),'--model',args.model,'--trust','--sandbox','enabled','--force','--approve-mcps','-p','--output-format','stream-json',prompt],stdout=out,stderr=err,start_new_session=True)
   try:exitcode=proc.wait(timeout=300)
   except subprocess.TimeoutExpired:
    import signal
    os.killpg(proc.pid,signal.SIGTERM);proc.wait(timeout=10);exitcode=124
  events=[]
  for line in (root/f'{label}.jsonl').read_text().splitlines():
   try:events.append(json.loads(line))
   except ValueError:pass
  terminal=next((x for x in reversed(events) if x.get('type')=='result'),{})
  check=json.loads((fixtures/'checks.json').read_text())[row['task']]
  tested=subprocess.run([sys.executable,'-c','import subject as f\n'+check],cwd=repo,capture_output=True,text=True)
  changes=git(repo,'diff','--name-only').splitlines()
  scope_ok=all(name=='subject.py' for name in changes)
  record={**row,'scope_ok':scope_ok,'status':'completed' if exitcode==0 else 'execution_failed','exit_code':exitcode,'cursor_usage':terminal.get('usage'),'session_id':terminal.get('session_id'),'elapsed_s':round(time.monotonic()-started,2),'checks_passed':tested.returncode==0,'check_error':tested.stderr[-800:],'changed_files':changes,'model':args.model,'result':terminal.get('result','')}
  results.append(record);(root/'results.json').write_text(json.dumps(results,indent=2)+'\n')
  print(json.dumps({k:record[k] for k in ('task','repeat','arm','cursor_usage','checks_passed','exit_code','elapsed_s')}),flush=True)

if __name__=="__main__":main()
