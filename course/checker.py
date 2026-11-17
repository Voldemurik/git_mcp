"""SmartClass MCP offline preflight + one optional live agent CI run.

Checks honest, observable prerequisites. It cannot establish that a student's
self-reported audit is impossible to forge: teacher should review source and
raw CI logs for the final grade. Never create or assign cases here.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path
from .assign import ROOT, assign_case, CASE_IDS, SEED

REPORT=ROOT/'llm-mcp-result'
REQUIRED=['manifest.json','summary.json','audit.jsonl','plan.md','review.md','outputs/result.json','outputs/report.md']

class CheckFailure(Exception):pass

def save_json(p:Path,obj:dict):
 p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def check(condition:bool, label:str, results:list, detail:str=''):
 results.append({'name':label,'passed':bool(condition),'detail':detail[:300]})
 return bool(condition)

def safe_json(p):
 try:return json.loads(p.read_text(encoding='utf-8'))
 except (ValueError,OSError) as exc:raise CheckFailure(f'Invalid JSON at {p.name}: {type(exc).__name__}') from None

def preflight(root:Path,results:list)->dict:
 variant_path=root/'variant.json'
 check(variant_path.is_file(),'assigned_variant_exists',results)
 if not variant_path.is_file():raise CheckFailure('No variant.json: create a student/<login> branch and wait for Create workflow')
 v=safe_json(variant_path)
 cid=v.get('case_id')
 check(cid in CASE_IDS,'valid_case_id',results,str(cid))
 check(isinstance(v.get('student_login'),str) and bool(v.get('student_login')),'student_login_present',results)
 check(v.get('catalog_seed')==SEED,'expected_catalog_version',results)
 expected=assign_case(v.get('student_login','')) if v.get('student_login') else ''
 check(cid==expected,'stable_personal_assignment',results)
 check((root/'TASK.md').is_file() and (root/'case/TASK.md').is_file(),'task_files',results)
 cp=root/'case/manifest.json'
 check(cp.is_file(),'case_manifest_exists',results)
 manifest=safe_json(cp) if cp.is_file() else {}
 check(manifest.get('case_id')==cid and manifest.get('ready_mcp')==v.get('ready_mcp'),'case_matches_variant',results)
 hashes=v.get('file_sha256',{})
 check(isinstance(hashes,dict) and len(hashes)>=3,'assignment_has_input_hashes',results)
 valid=True; changed=[]
 for path,sha in hashes.items() if isinstance(hashes,dict) else []:
  target=(root/'case'/path).resolve()
  if not target.is_relative_to((root/'case').resolve()) or not target.is_file():valid=False;changed.append(path);continue
  if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:valid=False;changed.append(path)
 # Also check there are no additional injected input files (excluding normal generated folders).
 actual={x.relative_to(root/'case').as_posix() for x in (root/'case').rglob('*') if x.is_file()}
 extra=actual-set(hashes) if isinstance(hashes,dict) else actual
 if extra:valid=False;changed+=sorted(extra)
 check(valid,'original_case_files_unmodified',results,','.join(changed)[:250])
 check((root/'student/own_server.py').is_file() and (root/'student/agent.py').is_file(),
       'student_code_present',results)
 readme=root/'README.md'
 check(readme.is_file() and len(readme.read_text(encoding='utf-8'))>=100,'readme_present',results)
 # Allow student-specific notes without hard-coded form; key storage is checked separately.
 secrets=[]
 for path in [root/'.env',root/'student/.env',root/'case/.env',root/'credentials.json']:
  if path.is_file():secrets.append(path.relative_to(root).as_posix())
 check(not secrets,'no_common_secret_files',results,','.join(secrets))
 return v

def probe_own_mcp(root:Path,results:list)->list[str]:
 from .protocol import MCPStdio,child_env,content_text
 cmd=[sys.executable,'-u','-m','student.own_server']
 try:
  with MCPStdio(cmd,root,child_env(root),timeout=20) as srv:
   tools=srv.list_tools()
   names=[t.get('name','') for t in tools]
   check('health_check' in names,'own_mcp_health_discovered',results)
   if 'health_check' in names:
    response=srv.call('health_check',{})
    check(not response.get('isError') and 'ready' in content_text(response).lower(),
          'own_mcp_health_called_via_protocol',results)
   n=len([n for n in names if n!='health_check'])
   check(n>=3,'at_least_three_domain_mcp_tools',results,f'{n} domain tools discovered')
   return names
 except Exception as exc:
  check(False,'own_mcp_protocol_connection',results,type(exc).__name__+': '+str(exc)[:150]);return []

def parse_audit(path:Path,results:list)->dict:
 entries=[]
 try:
  for i,line in enumerate(path.read_text(encoding='utf-8').splitlines()):
   if i>=3000:raise ValueError('audit too long')
   if line.strip():entries.append(json.loads(line))
 except (OSError,ValueError) as exc:
  check(False,'audit_jsonl_parses',results,type(exc).__name__);return {'own':0,'ready':0}
 check(bool(entries),'audit_jsonl_parses',results)
 counts={'own':0,'ready':0}
 for entry in entries:
  if not isinstance(entry,dict):continue
  if entry.get('event')!='tool_completed' or entry.get('actor')!='model':continue
  if entry.get('is_error') is True or entry.get('status') in ('denied','failed','error'):continue
  sid=entry.get('server')
  if sid in counts:counts[sid]+=1
 check(counts['own']>0,'model_called_own_mcp',results,str(counts['own']))
 check(counts['ready']>0,'model_called_ready_mcp',results,str(counts['ready']))
 plan_write=any(isinstance(e,dict) and e.get('event')=='tool_completed' and e.get('phase')=='plan' and
                (e.get('operation')=='write' or e.get('write') is True) for e in entries)
 check(not plan_write,'no_successful_plan_writes',results)
 return counts

def verify_live(root:Path,v:dict,results:list)->dict:
 out=root/'llm-mcp-result'
 missing=[p for p in REQUIRED if not (out/p).is_file()]
 check(not missing,'required_report_files',results,','.join(missing))
 if missing:return {'own':0,'ready':0}
 student_manifest=safe_json(out/'manifest.json')
 r=safe_json(out/'outputs/result.json')
 summary=safe_json(out/'summary.json')
 check(student_manifest.get('case_id')==v['case_id'],'manifest_matches_assignment',results)
 check(r.get('case_id')==v['case_id'] and r.get('status')=='completed','result_case_status',results)
 check(isinstance(r.get('sources'),list) and len(r['sources'])>=1,'result_cites_sources',results)
 check(isinstance(r.get('result'),dict) and bool(r['result']),'result_has_subject_data',results)
 check(isinstance(r.get('checks'),dict) and bool(r['checks']),'result_includes_checks',results)
 for name in ['plan.md','review.md','outputs/report.md']:
  check(len((out/name).read_text(encoding='utf-8').strip())>=60,'nonempty_'+name.replace('/','_'),results)
 check(summary.get('backend')=='gigachat','real_gigachat_backend_declared',results)
 counts=parse_audit(out/'audit.jsonl',results)
 # Preserve subject-specific checks; judge personally against teacher key.
 return counts

def write_report(root:Path,mode:str,results:list,variant:dict|None, error:str=''):
 out=root/'llm-mcp-result';out.mkdir(parents=True,exist_ok=True)
 passed=all(r['passed'] for r in results) and not error
 status=('preflight_passed_not_submitted' if passed and mode=='preflight' else 'passed' if passed else 'failed')
 previous={}
 if (out/'summary.json').is_file():
  try:previous=safe_json(out/'summary.json')
  except CheckFailure:pass
 summary={**previous,'case_id':(variant or {}).get('case_id'),'status':status,'checker_mode':mode,
          'checker_checks_passed':passed,'error':error[:500] if error else None}
 save_json(out/'checks.json',{'passed':passed,'checks':results})
 save_json(out/'summary.json',summary)
 if not (out/'manifest.json').is_file():
  save_json(out/'manifest.json',{'case_id':(variant or {}).get('case_id'),'source':'smartclass-checker',
                                  'student_login':(variant or {}).get('student_login'),'branch':(variant or {}).get('branch')})
 print('CHECKER',mode,status,'passed',sum(r['passed'] for r in results),'/',len(results),flush=True)
 for c in results:
  print(('PASS' if c['passed'] else 'FAIL'),c['name'],c['detail'][:100],flush=True)
 if error:print('CHECKER ERROR:',error[:300],file=sys.stderr,flush=True)
 return passed

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['preflight','live'],required=True)
 ap.add_argument('--root',type=Path,default=ROOT);args=ap.parse_args()
 root=args.root.resolve();results=[];v=None;err=''
 try:
  v=preflight(root,results)
  if not all(x['passed'] for x in results):raise CheckFailure('Preflight failed; correct assignment/files first')
  if args.mode=='live':
   # GigaChat credentials are in the student fork only, never in PR checks.
   if not (os.getenv('GIGACHAT_CREDENTIALS') or os.getenv('GIGACHAT_ACCESS_TOKEN')):
    check(False,'gigachat_key_in_fork_secrets',results)
    raise CheckFailure('Add GIGACHAT_CREDENTIALS in your FORK repository secrets, never into a tracked file')
   probe_own_mcp(root,results)
   if not all(x['passed'] for x in results):raise CheckFailure('Own MCP did not pass readiness checks')
   out=root/'llm-mcp-result'
   out.mkdir(parents=True,exist_ok=True)
   try:
    run=subprocess.run([sys.executable,'-m','student.agent','--case-dir','case','--report-dir',str(out)],
                       cwd=root,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=420)
    # No raw stdout/stderr in public artefacts: student code may accidentally print tokens.
    check(run.returncode==0,'student_agent_execution',results,f'exit_code={run.returncode}')
    if run.returncode:
     # Sanitize the provider error, but keep useful HTTP codes for debugging.
     message=run.stderr[-1800:].replace('\r',' ')
     for secret_name in ('GIGACHAT_CREDENTIALS','GIGACHAT_ACCESS_TOKEN','CONTEXT7_API_KEY','MCP_GITVERSE_TOKEN'):
      secret=os.getenv(secret_name,'')
      if len(secret)>5:message=message.replace(secret,'[REDACTED]')
     message=re.sub(r'(?i)(bearer|basic)\s+[A-Za-z0-9._~+/-]{12,}',r'\1 [REDACTED]',message)
     message=re.sub(r'[A-Za-z0-9+/=_-]{80,}','[REDACTED_LONG_VALUE]',message)
     message=re.sub(r'(?i)(password|authorization|token|credential)\s*[:=]\s*\S+',r'\1=[REDACTED]',message)
     raise CheckFailure('Student agent failed (sanitized stderr): '+message[-500:])
   except subprocess.TimeoutExpired:raise CheckFailure('Student agent timed out after 420 seconds') from None
   verify_live(root,v,results)
 except Exception as exc:
  err=f'{type(exc).__name__}: {str(exc)}'
 passed=write_report(root,args.mode,results,v,err)
 raise SystemExit(0 if passed else 1)

if __name__=='__main__':main()
