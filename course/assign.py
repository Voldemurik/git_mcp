"""One-shot deterministic SmartClass task creation on GitVerse branch-create.

Only the *creation* workflow writes TASK.md/variant.json/case/. The checker never
creates or reassigns variants. Python standard library, no pip dependencies.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/'course/catalog.zip'
SEED='smartclass-mcp-2026-v1'
CASE_IDS=[f'K{i:02d}' for i in range(1,13)]+[f'G{i:02d}' for i in range(1,7)]+[f'P{i:02d}' for i in range(1,7)]
BRANCH_RE=re.compile(r'^student/[A-Za-z0-9][A-Za-z0-9._-]{0,63}$')


def normalize_branch(value:str)->str:
    value=value.strip()
    if value.startswith('refs/heads/'):
        value=value[len('refs/heads/'):]
    if not BRANCH_RE.fullmatch(value) or value.endswith('.') or '..' in value:
        raise ValueError('Expected a branch like student/my_login (no tags, spaces, paths or traversal)')
    return value


def assign_case(actor:str)->str:
    actor=actor.strip().lower()
    if not actor or len(actor)>128 or not re.fullmatch(r'[\w.-]+',actor,re.UNICODE):
        raise ValueError('Expected a nonempty GitVerse actor/login')
    raw=hashlib.sha256(f'{SEED}:{actor}'.encode('utf-8')).digest()
    return CASE_IDS[int.from_bytes(raw[:8],'big')%len(CASE_IDS)]


def assign(root:Path,actor:str,branch:str)->dict:
    branch=normalize_branch(branch)
    root=Path(root).resolve()
    existing=root/'variant.json'
    if existing.exists():
        info=json.loads(existing.read_text(encoding='utf-8'))
        if info.get('branch')!=branch:
            raise ValueError('A different branch assignment was copied here. Create from master, not student branch')
        if info.get('student_login','').lower()!=actor.lower() or info.get('case_id')!=assign_case(actor):
            raise ValueError('Existing assignment disagrees with original branch owner; refusing overwrite')
        print('ALREADY ASSIGNED: no file changed; case='+info['case_id'])
        return info
    for name in ['TASK.md','case']:
        if (root/name).exists():
            raise ValueError(f'{name} already exists without variant.json; refusing overwrite')
    cid=assign_case(actor)
    with zipfile.ZipFile(root/'course/catalog.zip') as catalog:
        entries=[i for i in catalog.infolist() if i.filename.startswith(cid+'/') and not i.is_dir()]
        if len(entries)<3:raise ValueError('Missing variant dataset '+cid)
        input_hashes={}
        starter=None
        for entry in entries:
            sub=entry.filename[len(cid)+1:]
            parts=Path(sub).parts
            if not parts or any(p in ('.','..') for p in parts) or Path(sub).is_absolute():
                raise ValueError('Unsafe entry in course catalog')
            content=catalog.read(entry)
            if sub == '_starter/own_server.py':
                starter=content
                continue
            target=(root/'case'/sub).resolve()
            if not target.is_relative_to(root/'case'):
                raise ValueError('Catalog path escaped case/ directory')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(content)
            input_hashes[sub]=hashlib.sha256(content).hexdigest()
    if starter is None:raise ValueError('No personalized MCP starter in course catalog')
    student_server=root/'student/own_server.py'
    student_server.parent.mkdir(parents=True,exist_ok=True)
    student_server.write_bytes(starter)
    manifest=json.loads((root/'case/manifest.json').read_text(encoding='utf-8'))
    if manifest['case_id']!=cid:raise ValueError('Catalog/manifest mismatch')
    info={'schema_version':1,'case_id':cid,'student_login':actor,'branch':branch,
          'ready_mcp':manifest['ready_mcp'],'catalog_seed':SEED,
          'file_sha256':input_hashes}
    (root/'variant.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    task=(root/'case/TASK.md').read_text(encoding='utf-8')
    (root/'TASK.md').write_text('# Персональное задание — '+cid+'\n\n'+task+
        '\n\n---\n**Общие требования:** [COMMON_TASK.md](COMMON_TASK.md). '
        'Данные: `case/`. Не изменяйте входные файлы. '
        'Результаты формируйте в `llm-mcp-result/` во время Checker.\n',encoding='utf-8')
    print('ASSIGNED '+cid+' to '+actor+' in '+branch)
    return info


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--actor',default=os.getenv('GITVERSE_ACTOR',''))
    p.add_argument('--branch',default=os.getenv('GITVERSE_REF',''))
    p.add_argument('--root',type=Path,default=ROOT)
    a=p.parse_args()
    assign(a.root,a.actor,a.branch)

if __name__=='__main__':main()
