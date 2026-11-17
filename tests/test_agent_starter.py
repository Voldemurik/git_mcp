"""Локальные проверки инфраструктуры агента (без сети и GigaChat API)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import student.agent as agent


class _FakeContext:
    def __init__(self, obj):
        self.obj = obj
    def __enter__(self):
        return self.obj
    def __exit__(self, *args):
        return False


class AgentStarterTests(unittest.TestCase):
    def test_todos_are_not_completed_for_student(self):
        # Не должны случайно выдать работающий предметный агент.
        for phase, args in (
            (agent.plan_phase, (None, None, None, Path('audit.jsonl'))),
            (agent.build_phase, (None, None, None, Path('audit.jsonl'), 'plan')),
            (agent.review_phase, (None, None, None, Path('audit.jsonl'), {})),
        ):
            with self.subTest(phase=phase.__name__):
                with self.assertRaises(NotImplementedError):
                    phase(*args)

    def test_main_wires_clients_and_writes_only_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'case').mkdir()
            (root / 'variant.json').write_text(json.dumps({
                'case_id': 'K10', 'student_login': 'sample_login', 'ready_mcp': 'context7'
            }), encoding='utf-8')
            (root / 'case/manifest.json').write_text(json.dumps({
                'case_id': 'K10', 'ready_mcp': 'context7'
            }), encoding='utf-8')
            own_client = object()
            ready_client = object()
            giga = object()
            phases = []

            def fake_plan(g, r, o, audit_path):
                phases.append('plan')
                self.assertIs(g, giga)
                self.assertIs(r, ready_client)
                self.assertIs(o, own_client)
                self.assertEqual(audit_path, root / 'llm-mcp-result/audit.jsonl')
                return 'Пример плана для тестирования каркаса.'

            def fake_build(g, r, o, audit_path, plan):
                phases.append('build')
                self.assertIn('Пример плана', plan)
                return {'subject': 'only from student implementation'}

            def fake_review(g, r, o, audit_path, outcome):
                phases.append('review')
                self.assertIn('subject', outcome)
                return 'Пример проверки для тестирования каркаса.'

            with (patch.object(agent, 'ROOT', root),
                  patch.object(agent, 'MCPStdio', return_value=_FakeContext(own_client)) as own_factory,
                  patch.object(agent, 'connect_ready', return_value=_FakeContext(ready_client)) as ready_factory,
                  patch.object(agent, 'GigaChatAPI', return_value=giga),
                  patch.object(agent, 'plan_phase', side_effect=fake_plan),
                  patch.object(agent, 'build_phase', side_effect=fake_build),
                  patch.object(agent, 'review_phase', side_effect=fake_review),
                  patch.object(sys, 'argv', ['agent.py', '--case-dir', str(root / 'case'),
                                             '--report-dir', str(root / 'llm-mcp-result')])):
                agent.main()
            self.assertEqual(phases, ['plan', 'build', 'review'])
            self.assertEqual(ready_factory.call_args.args[1], 'context7')
            self.assertIn('student.own_server', own_factory.call_args.args[0])
            out = root / 'llm-mcp-result'
            self.assertTrue((out / 'plan.md').is_file())
            self.assertTrue((out / 'review.md').is_file())
            self.assertEqual(json.loads((out / 'manifest.json').read_text())['case_id'], 'K10')
            self.assertEqual(json.loads((out / 'summary.json').read_text())['backend'], 'gigachat')
            self.assertFalse((out / 'token_usage.json').exists(),
                             'The student must implement token accounting independently')
            self.assertFalse((out / 'outputs/result.json').exists(),
                             'The student must generate domain results independently')

    def test_wrong_case_dir_is_rejected_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'case').mkdir()
            (root / 'other').mkdir()
            with (patch.object(agent, 'ROOT', root),
                  patch.object(sys, 'argv', ['agent.py', '--case-dir', str(root / 'other'),
                                             '--report-dir', str(root / 'llm-mcp-result')]),
                  patch.object(agent, 'MCPStdio') as sdk):
                with self.assertRaisesRegex(ValueError, 'case/'):
                    agent.main()
                sdk.assert_not_called()


if __name__ == '__main__':
    unittest.main()
