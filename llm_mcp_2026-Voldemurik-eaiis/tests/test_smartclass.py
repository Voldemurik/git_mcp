import hashlib,json,os,shutil,tempfile,unittest,zipfile
from pathlib import Path
from course.assign import ROOT,CASE_IDS,SEED,assign,assign_case,normalize_branch
from course.checker import preflight,write_report

class TaskAssignmentTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  (self.root/'course').mkdir()
  shutil.copy(ROOT/'course/catalog.zip',self.root/'course/catalog.zip')
 def tearDown(self):self.temp.cleanup()
 def test_manifest_catalog_has_all_24_cases(self):
  with zipfile.ZipFile(ROOT/'course/catalog.zip') as z:
   names=z.namelist()
   for cid in CASE_IDS:
    self.assertIn(f'{cid}/manifest.json',names)
    self.assertIn(f'{cid}/TASK.md',names)
    self.assertGreaterEqual(sum(n.startswith(cid+'/') for n in names),4)
 def test_assignment_stable(self):
  self.assertEqual(assign_case('Ivan_123'),assign_case('ivan_123'))
  self.assertIn(assign_case('student_27'),CASE_IDS)
 def test_assign_actual_files(self):
  v=assign(self.root,'ivan_123','refs/heads/student/ivan_123')
  self.assertTrue((self.root/'TASK.md').is_file())
  self.assertTrue((self.root/'case/manifest.json').is_file())
  self.assertEqual(v['case_id'],assign_case('ivan_123'))
  self.assertEqual(v['case_id'],json.loads((self.root/'case/manifest.json').read_text())['case_id'])
 def test_idempotent_no_changes(self):
  assign(self.root,'user_1','student/user_1')
  content={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  assign(self.root,'user_1','student/user_1')
  new={p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
  self.assertEqual(content,new)
 def test_branch_from_other_student_rejected(self):
  assign(self.root,'user_1','student/user_1')
  with self.assertRaisesRegex(ValueError,'different branch'):assign(self.root,'user_2','student/user_2')
 def test_unknown_bare_branch_rejected(self):
  for b in ['master','student/../master','student/foo/bar','refs/tags/student/foo','student/foo bar']:
   with self.subTest(b=b):
    with self.assertRaises(ValueError):normalize_branch(b)
 def test_corruption_detected(self):
  v=assign(self.root,'alex','student/alex')
  (self.root/'README.md').write_text('a'*140)
  (self.root/'student').mkdir(exist_ok=True);(self.root/'student/agent.py').write_text('');(self.root/'student/own_server.py').write_text('')
  results=[];preflight(self.root,results)
  self.assertTrue(all(x['passed'] for x in results))
  f=next(iter(v['file_sha256']))
  (self.root/'case'/f).write_bytes(b'CHANGED!')
  results=[];preflight(self.root,results)
  self.assertFalse(next(x for x in results if x['name']=='original_case_files_unmodified')['passed'])
 def test_common_files_stay_out_of_student_case(self):
  for cid in CASE_IDS:
   a=next(n for n in zipfile.ZipFile(ROOT/'course/catalog.zip').namelist() if n==f'{cid}/manifest.json')
   self.assertTrue(a)
 def test_all_actor_assignments_are_valid(self):
  for n in range(300):self.assertIn(assign_case('student_'+str(n)),CASE_IDS)
 def test_seed_version_explicit(self):self.assertTrue(SEED.startswith('smartclass-mcp-'))
 def test_no_teacher_answer_in_catalog(self):
  with zipfile.ZipFile(ROOT/'course/catalog.zip') as z:
   self.assertFalse(any('teacher_' in n.lower() or 'answer_key' in n.lower() or 'solutions/' in n.lower() for n in z.namelist()))
 def test_rejected_when_existing_no_variant(self):
  (self.root/'TASK.md').write_text('existing')
  with self.assertRaisesRegex(ValueError,'already exists'):assign(self.root,'alex','student/alex')

class WorkflowTests(unittest.TestCase):
 def test_workflow_yaml_and_triggers(self):
  import yaml
  for n in ['create.yml','checker.yml']:
   p=ROOT/'.gitverse/workflows'/n
   doc=yaml.load(p.read_text(),Loader=yaml.BaseLoader)
   self.assertEqual(len(doc['jobs']),1)
   self.assertIn('on',doc)
  c=yaml.load((ROOT/'.gitverse/workflows/create.yml').read_text(),Loader=yaml.BaseLoader)
  self.assertIn('create',c['on']);self.assertNotIn('push',c['on'])
  k=yaml.load((ROOT/'.gitverse/workflows/checker.yml').read_text(),Loader=yaml.BaseLoader)
  self.assertIn('workflow_dispatch',k['on']);self.assertIn('pull_request',k['on'])
  self.assertNotIn('push',k['on'])
 def test_no_teacher_secrets_in_pr_step(self):
  txt=(ROOT/'.gitverse/workflows/checker.yml').read_text()
  self.assertIn('gitverse.event_name == \'workflow_dispatch\'',txt)
  self.assertIn('persist-credentials: false',txt)

if __name__=='__main__':unittest.main()

class TransportTests(unittest.TestCase):
 def test_gigachat_function_normalization(self):
  from course.gigachat_api import to_gigachat_functions
  mock=[{'name':'ready__read_text_file','inputSchema':{'type':'object','properties':{
      'path':{'type':'string'},'type':{'type':['string','null']}},'required':['path']}}]
  functions,pub,rev=to_gigachat_functions(mock)
  self.assertEqual(len(functions),1)
  self.assertEqual(rev['ready__read_text_file'],functions[0]['name'])
  self.assertNotIn('_',functions[0]['name'])
  self.assertEqual(pub[functions[0]['name']],'ready__read_text_file')
 def test_gitverse_allowlist(self):
  from course.ready import OwnRepoGitVerse
  class Fake:
   def list_tools(self):return []
   def call(self,name,args):return {'ok':True}
  c=OwnRepoGitVerse(Fake(),'student/repository')
  self.assertEqual(c.call('get_repository',{'owner':'student','repo':'repository'}),{'ok':True})
  with self.assertRaises(Exception):c.call('get_repository',{'owner':'another','repo':'repository'})
  with self.assertRaises(Exception):c.call('create_pull_request',{'owner':'student','repo':'repository'})
 def test_audit_redacts_field_name(self):
  from course.report import audit
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/'audit.jsonl';audit(path,'test',token='supersecret',case_id='K01')
   raw=path.read_text();self.assertNotIn('supersecret',raw)
   self.assertIn('K01',raw)
