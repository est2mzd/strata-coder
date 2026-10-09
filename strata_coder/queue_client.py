from .depth import resolve as resolve_depth
"""Workspace workers for the shared coordinator. No Cursor model calls for polling."""
import hashlib
import json
import os
from pathlib import Path
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from .core import Manager, git
from .transport import Transport


class BrokerClient:
    def __init__(self, config):
        self.config = config
        token = os.environ.get('STRATA_COORDINATOR_TOKEN', '')
        if not token and config.get('coordinator_token_file'):
            token = Path(config['coordinator_token_file']).expanduser().read_text().strip()
        if len(token) < 24:
            raise ValueError('Configure the shared coordinator token (SecretStorage or token file)')
        self.token = token
        self.tunnel = Transport({**config, 'remote_port': config.get('coordinator_port',8091)})
        self.base = ''

    def request(self, route, data=None, timeout=35):
        if self.config.get('mode','ssh') == 'ssh':
            self.tunnel.connect();base=self.tunnel.base
        else:
            base=self.config.get('coordinator_url','http://127.0.0.1:18091/v1').rstrip('/')
            u=urllib.parse.urlparse(base)
            if u.username or u.password or u.query or u.fragment or not u.hostname or u.scheme not in ('http','https'):
                raise ValueError('Invalid coordinator URL')
            if u.scheme=='http' and u.hostname not in ('127.0.0.1','localhost','::1'):
                raise ValueError('Use an SSH loopback tunnel or HTTPS for the coordinator')
        req=urllib.request.Request(base+'/'+route,data=json.dumps(data or {}).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+self.token})
        try:
            with self.tunnel.opener.open(req,timeout=timeout) as r:
                raw=r.read(2_000_001)
                if len(raw)>2_000_000:raise ValueError('Coordinator response too large')
                return json.loads(raw)['result']
        except urllib.error.HTTPError as e:
            if e.code==401:raise RuntimeError('Coordinator authentication failed') from None
            try:message=json.loads(e.read(2000)).get('error','Coordinator rejected request')
            except Exception:message='Coordinator rejected request'
            raise RuntimeError(message) from None
        except (urllib.error.URLError,TimeoutError,OSError):
            raise RuntimeError('Coordinator connection lost; no automatic side-effect retry') from None

    def close(self):self.tunnel.close()


class InferenceClient:
    def __init__(self, broker, workspace, task_id, lease):
        self.broker,self.workspace,self.task_id,self.lease=broker,workspace,task_id,lease
    def health(self):return self.broker.request('models')
    def chat(self,messages,tools):
        return self.broker.request('infer',dict(workspace=self.workspace,task_id=self.task_id,
            lease=self.lease,messages=messages,tools=tools),timeout=720)
    def chat_with_options(self,messages,tools,options):
        # The coordinator reads the immutable contract, never caller-supplied overrides.
        return self.chat(messages,tools)
    def close(self):pass  # Tunnel is owned by the gateway, not a single task.


class QueueHealth:
    def __init__(self,broker):self.broker=broker
    def health(self):return {**self.broker.request('health'),**self.broker.request('models'),'execution_mode':'queued'}
    def close(self):pass


class QueuedManager:
    def __init__(self, repo, state, config, broker=None):
        self.repo,self.state=Path(repo).resolve(),Path(state).resolve()
        if self.repo==self.state or self.repo in self.state.parents:
            raise ValueError('State must be outside repo')
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.config=config;self.tests=config.get('tests',{})
        self.broker=broker or BrokerClient(config)
        self.transport=QueueHealth(self.broker)
        self.workspace=hashlib.sha256((socket.gethostname()+':'+str(self.repo)).encode()).hexdigest()
        self.stop=threading.Event();self.lock=threading.RLock();self.managers={};self.threads=[]
        self.instance=uuid.uuid4().hex
        self.worker_count=int(config.get('worker_concurrency',2))
        if not 1<=self.worker_count<=64:raise ValueError('worker_concurrency must be 1..64; unrelated to agent count')
        self.test_slots=threading.BoundedSemaphore(max(1,min(64,int(config.get('test_concurrency',1)))))
        self.git_lock=threading.RLock()
        for i in range(self.worker_count):self.start_thread(self.work_loop,(f'{self.instance}:{i}','work'))
        self.start_thread(self.work_loop,(f'{self.instance}:apply','apply'))
        self.start_thread(self.monitor,())

    def start_thread(self,func,args):
        t=threading.Thread(target=func,args=args,daemon=True);self.threads.append(t);t.start()

    def checker(self):
        # No worker or model is started by this object.
        return Manager(self.repo,self.state/'validation',self.config,self.transport)

    def submit(self,objective,mode='research',allowed_paths=None,acceptance=None,test_ids=None,max_steps=12,owner='default',request_key=None,depth=None,reasoning_effort=None,depth_reason='',max_output_tokens=None):
        if not request_key:
            raise ValueError('queued mode requires request_key; reuse it only for retries of the same task')
        contract=dict(objective=objective,mode=mode,allowed_paths=allowed_paths or [],acceptance=acceptance or [],test_ids=test_ids or [],max_steps=max_steps,**resolve_depth(self.config,depth,reasoning_effort,depth_reason,max_output_tokens))
        checker=self.checker()
        checker.validate_contract(**contract)
        checker.clean()
        base=git(self.repo,'rev-parse','HEAD')
        return self.broker.request('submit',dict(workspace=self.workspace,owner=owner,request_key=request_key,contract=contract,base=base))

    def local(self,tid):
        if len(tid)!=32 or any(c not in '0123456789abcdef' for c in tid):raise ValueError('Invalid task ID')
        with self.lock:
            if tid in self.managers:return self.managers[tid]
            folder=self.state/'jobs'/tid
            if not folder.exists():raise ValueError('No local evidence for this task on this workspace host')
            m=Manager(self.repo,folder,self.config,self.transport)
            if len(m.tasks)!=1:raise ValueError('Local task state is unavailable')
            self.managers[tid]=m
            return m

    def summary(self,task_id,wait_seconds=0):
        return self.broker.request('summary',dict(workspace=self.workspace,task_id=task_id,wait_seconds=min(25,max(0,wait_seconds))))

    def get_evidence(self,task_id,evidence_id,offset=0,limit=4000):
        self.summary(task_id)  # Ensure task belongs to this workspace.
        m=self.local(task_id)
        return m.get_evidence(next(iter(m.tasks)),evidence_id,offset,limit)

    def cancel(self,task_id):return self.broker.request('cancel',dict(workspace=self.workspace,task_id=task_id))
    def apply(self,task_id,reviewed_patch_sha256):
        return self.broker.request('apply',dict(workspace=self.workspace,task_id=task_id,reviewed_patch_sha256=reviewed_patch_sha256))

    def beat_loop(self,job,done,mref,lost):
        interval=max(.2,min(5,job['lease_seconds']/3))
        while not done.is_set():
            try:
                status=self.broker.request('heartbeat',dict(workspace=self.workspace,task_id=job['id'],lease=job['lease']),timeout=10)
                if status['cancel']:
                    if mref: mref[0].cancel(next(iter(mref[0].tasks)))
            except Exception:
                lost.set()
                if mref:
                    for t in mref[0].tasks.values():t['cancel'].set()
                return
            if done.wait(interval):return

    def work_loop(self,worker,kind):
        backoff=.25
        while not self.stop.is_set():
            try:
                job=self.broker.request('claim',dict(workspace=self.workspace,worker=worker,kind=kind),timeout=10)
                if not job:
                    self.stop.wait(backoff);backoff=min(2,backoff*1.5);continue
                backoff=.25
                self.perform(job,kind)
            except Exception as e:
                self.write_health(str(e)[:300])
                self.stop.wait(2)

    def perform(self,job,kind):
        done,lost=threading.Event(),threading.Event();mref=[]
        heartbeat=threading.Thread(target=self.beat_loop,args=(job,done,mref,lost),daemon=True);heartbeat.start()
        status,result='failed',{}
        try:
            if kind=='work':
                with self.git_lock:
                    if git(self.repo,'rev-parse','HEAD')!=job['base']:
                        raise ValueError('Repository base changed while queued; supervisor must resubmit')
                    m=Manager(self.repo,self.state/'jobs'/job['id'],self.config,
                        InferenceClient(self.broker,self.workspace,job['id'],job['lease']))
                    m.test_slots=self.test_slots
                    with self.lock:self.managers[job['id']]=m
                    local_id=m.submit(**job['contract'],expected_base=job['base'])['task_id']
                    mref.append(m)
                while m.thread.is_alive():
                    if self.stop.is_set() or lost.is_set():m.cancel(local_id)
                    m.thread.join(.2)
                result=m.summary(local_id)
                status=result['status']
                if status not in ('review_ready','cancelled','failed','needs_supervisor'):
                    status='needs_supervisor'
            else:
                m=self.local(job['id']);mref.append(m);local_id=next(iter(m.tasks))
                with self.git_lock:
                    self.broker.request('heartbeat',dict(workspace=self.workspace,task_id=job['id'],lease=job['lease']))
                    if lost.is_set():raise RuntimeError('Lease lost before apply')
                    if git(self.repo,'rev-parse','HEAD')!=m.get(local_id)['base']:
                        result=m.rebase_for_review(local_id)
                        status=result['status']
                        result['integration_note']='Base changed: a new worktree was prepared and tested. Review the new patch hash before applying.'
                    else:
                        m.apply(local_id,job['approved_hash'])
                        result=m.summary(local_id);status='applied'
            if not lost.is_set():
                self.broker.request('finish',dict(workspace=self.workspace,task_id=job['id'],lease=job['lease'],status=status,result=result))
        except Exception as e:
            if not lost.is_set():
                try:self.broker.request('finish',dict(workspace=self.workspace,task_id=job['id'],lease=job['lease'],
                    status='needs_supervisor',result={'reason':str(e)[:600]}))
                except Exception:pass
        finally:
            done.set();heartbeat.join(11)

    def write_health(self,error):
        # Status UI only; never automatically sent to the Cursor model.
        with self.lock:
            if self.stop.is_set():return
            p=self.state/'connection.json';tmp=p.with_suffix('.tmp')
            tmp.write_text(json.dumps({'error':error,'at':time.time()}));tmp.replace(p)

    def monitor(self):
        cursor=0
        recent={}
        progress=self.state/'progress.json'
        if progress.exists():
            try:
                saved=json.loads(progress.read_text());cursor=saved.get('cursor',0)
                recent={e['task_id']:e for e in saved.get('events',[])}
            except (ValueError,OSError,KeyError):pass
        while not self.stop.is_set():
            try:
                data=self.broker.request('events',dict(workspace=self.workspace,after=cursor,wait_seconds=self.config.get('event_wait_seconds',10)),timeout=15)
                if self.stop.is_set():break
                if data['events']:
                    cursor=data['cursor']
                    for e in data['events']:recent[e['task_id']]=e
                    values=sorted(recent.values(),key=lambda e:e['seq'])[-500:]
                    recent={e['task_id']:e for e in values}
                    tmp=progress.with_suffix('.tmp')
                    tmp.write_text(json.dumps({'cursor':cursor,'events':values}));tmp.replace(progress)
                self.write_health('')
            except Exception as e:
                self.write_health(str(e)[:300]);self.stop.wait(2)

    def close(self):
        self.stop.set()
        with self.lock:
            for m in self.managers.values():
                for t in m.tasks.values():t['cancel'].set()
        # Do not kill other processes or replay work. Leases fence unfinished tasks.
        for t in self.threads:t.join(.2)
        self.broker.close()
