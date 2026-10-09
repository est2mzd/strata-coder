"""Summarize Cursor terminal usage counters without substituting estimates."""
import argparse,json
from pathlib import Path

FIELDS=('inputTokens','outputTokens','cacheReadTokens','cacheWriteTokens')
def summarize(rows,step=1):
 ratio={1:0.1,2:0.02,3:0.01}[step]
 groups={}
 for arm in ('cursor-only','strata'):
  rs=[r for r in rows if r['arm']==arm]
  complete=all(isinstance(r.get('cursor_usage'),dict) and all(type(r['cursor_usage'].get(k)) is int for k in FIELDS) for r in rs)
  counts={k:sum(r['cursor_usage'][k] for r in rs) for k in FIELDS} if complete and rs else None
  groups[arm]={'runs':len(rs),'passed':sum(r.get('checks_passed') is True and r.get('exit_code')==0 for r in rs),'usage':counts,'total_tokens':sum(counts.values()) if counts else None,'elapsed_s':round(sum(r.get('elapsed_s',0) for r in rs),2)}
 baseline=groups['cursor-only']['total_tokens'];delegated=groups['strata']['total_tokens']
 pairs={(r['task'],r['repeat']) for r in rows}
 balanced=all(sum((r['task'],r['repeat'])==pair and r['arm']==arm for r in rows)==1 for pair in pairs for arm in groups)
 quality_ok=all(g['runs']>0 and g['passed']==g['runs'] for g in groups.values())
 passed=bool(balanced and quality_ok and baseline and delegated is not None and delegated <= baseline*ratio)
 return {'step':step,'target_ratio':ratio,'quality_gate_passed':quality_ok,'token_gate_passed':passed,'groups':groups,'balanced_pairs':balanced,'token_reduction_percent':round(100*(1-delegated/baseline),2) if balanced and baseline and delegated is not None else None,'formula':'inputTokens + outputTokens + cacheReadTokens + cacheWriteTokens; reasoning is already part of output','cost_measured':False}

def main():
 p=argparse.ArgumentParser();p.add_argument('results');p.add_argument('--step',type=int,choices=[1,2,3],default=1);args=p.parse_args()
 print(json.dumps(summarize(json.loads(Path(args.results).read_text()),args.step),indent=2))
if __name__=='__main__':main()
