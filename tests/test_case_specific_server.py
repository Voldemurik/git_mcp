"""Проверки персональных MCP-заготовок без внешних зависимостей."""
from __future__ import annotations
import json, tempfile, shutil, sys, unittest, zipfile
from pathlib import Path
from course.assign import ROOT, CASE_IDS, assign, assign_case
from course.protocol import MCPStdio, child_env, content_text
from course.checker import preflight


class SpecificServerTests(unittest.TestCase):
    def _assign_case(self, case_id: str, root: Path):
        # Вариант назначается детерминированно по логину: найдём свой.
        actor = next(f"demo_{n}" for n in range(5000) if assign_case(f"demo_{n}")==case_id)
        (root/'course').mkdir(parents=True)
        shutil.copy(ROOT/'course/catalog.zip',root/'course/catalog.zip')
        shutil.copytree(ROOT/'student',root/'student')
        shutil.copy(ROOT/'README.md',root/'README.md')
        result = assign(root, actor, f"student/{actor}")
        self.assertEqual(result['case_id'],case_id)
        return result,actor

    def test_all_24_starters_via_real_mcp_protocol(self):
        for cid in CASE_IDS:
            with self.subTest(case_id=cid),tempfile.TemporaryDirectory() as td:
                root=Path(td)
                result,actor=self._assign_case(cid,root)
                self.assertIn('OWN_SERVER_SPEC.md',result['file_sha256'])
                starter=(root/'student/own_server.py').read_text(encoding='utf-8')
                self.assertIn('NotImplementedError',starter)
                spec=(root/'case/OWN_SERVER_SPEC.md').read_text(encoding='utf-8')
                check_results=[]
                preflight(root,check_results)
                self.assertTrue(all(e['passed'] for e in check_results),str(check_results))
                with MCPStdio([sys.executable,'-u','-m','student.own_server'],root,child_env(root),timeout=10) as server:
                    names=[tool['name'] for tool in server.list_tools()]
                    self.assertEqual(len(names),4,names)
                    self.assertEqual(set(names),set(['health_check','save_result'])|{n[:-2] for n in __import__('re').findall(r'`([a-z_]+\(\))`',spec) if n not in ['save_result()']})
                    health=server.call('health_check',{})
                    self.assertFalse(health.get('isError'),health)
                    read_name=[n for n in names if n not in ['health_check','save_result'] and 'raise NotImplementedError' not in starter.split('def '+n+'(')[1].split('def ')[0]][0]
                    response=server.call(read_name,{})
                    self.assertFalse(response.get('isError'),response)
                    obj=json.loads(content_text(response))
                    self.assertEqual(obj['case_id'],cid)
                    self.assertGreaterEqual(len(obj['sources']),4)
                    save=server.call('save_result',{})
                    self.assertTrue(save.get('isError'),save)
                    self.assertFalse((root/'llm-mcp-result/outputs/result.json').exists())
                # assigning again must preserve the personalized server unchanged
                before=(root/'student/own_server.py').read_bytes()
                assign(root,actor,f"student/{actor}")
                self.assertEqual(before,(root/'student/own_server.py').read_bytes())

if __name__=='__main__':unittest.main()
