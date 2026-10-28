import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

import qa_agent as qa
import qa_config
import service


class ConfigurationTests(unittest.TestCase):
    def test_example_is_valid_and_does_not_execute_repository_code(self):
        config = qa_config.load_config(Path(__file__).with_name('config.example.json'))
        self.assertFalse(config['projects']['DEMO']['trusted'])
        self.assertEqual(config['columns'], {'pass': None, 'fail': None, 'unsure': None})

    def test_missing_private_file_is_actionable(self):
        with self.assertRaisesRegex(SystemExit, 'config.example.json'):
            qa_config.load_config('/nonexistent/freejira-config.json')

    def test_rejects_invalid_project_keys_and_string_trust(self):
        config = qa_config.load_config(Path(__file__).with_name('config.example.json'))
        bad = copy.deepcopy(config)
        bad['projects']['../escape'] = bad['projects'].pop('DEMO')
        with self.assertRaises(ValueError):
            qa_config.validate(bad)
        config['projects']['DEMO']['trusted'] = 'false'
        with self.assertRaises(ValueError):
            qa_config.validate(config)

    def test_help_does_not_require_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-m', 'qa_agent', '--help'],
                                    env={'PATH': '/usr/bin:/bin', 'HOME': directory},
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class TrustTests(unittest.TestCase):
    def setUp(self):
        self.project = Mock(key='DEMO')

    def test_untrusted_repository_never_executes(self):
        with patch.dict(qa.CONFIG, {'projects': {'DEMO': {'trusted': False}}}), \
                patch.object(qa, 'run_local_checks') as checks:
            ev = qa.checks_for_pr(self.project, {'isCrossRepository': False}, [])
        checks.assert_not_called()
        self.assertIsNone(ev.checks[0].ok)

    def test_fork_is_blocked_even_for_trusted_repository(self):
        with patch.dict(qa.CONFIG, {'projects': {'DEMO': {'trusted': True}}}), \
                patch.object(qa, 'run_local_checks') as checks:
            qa.checks_for_pr(self.project, {'isCrossRepository': True}, [])
        checks.assert_not_called()

    def test_same_repository_trusted_pr_runs_and_cleans_up(self):
        with patch.dict(qa.CONFIG, {'projects': {'DEMO': {'trusted': True}}, 'keep_worktree': False}), \
                patch.object(qa, 'run_local_checks', return_value=qa.Evidence()) as checks, \
                patch.object(qa, 'cleanup_worktree') as cleanup:
            qa.checks_for_pr(self.project, {'isCrossRepository': False}, [])
        checks.assert_called_once()
        cleanup.assert_called_once()


class ConnectionTests(unittest.TestCase):
    def test_local_model_never_starts_ssh(self):
        service.STOP.clear()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{"models":[{"name":"example:latest"}]}'
        with patch.dict(qa.CONFIG, {'model': 'example', 'ssh_tunnel': None}), \
                patch.object(service.subprocess, 'Popen') as proc, \
                patch.object(service.urllib.request, 'urlopen', return_value=response):
            service.Tunnel().ensure()
        proc.assert_not_called()

    def test_stdio_negotiates_and_skips_notifications(self):
        source = '''import json, sys
initialized = False
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'notifications/initialized':
        initialized = True
        continue
    if request['method'] == 'initialize':
        result = {'protocolVersion':'2025-03-26', 'capabilities':{}, 'serverInfo':{'name':'fixture','version':'1'}}
    else:
        assert initialized
        result = {'content':[{'type':'text','text':json.dumps([{'id':'example'}])}]}
    print(json.dumps({'jsonrpc':'2.0','method':'notifications/message','params':{}}), flush=True)
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}), flush=True)
'''
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'fake.py'
            fake.write_text(source)
            with patch.dict(qa.CONFIG, {'mcp': {'command': [sys.executable, str(fake)]}}):
                client = qa.Freejira()
                try:
                    self.assertEqual(client.call('list_projects'), [{'id': 'example'}])
                finally:
                    client.close()

    def test_test_commands_do_not_inherit_tokens(self):
        with patch.dict(qa.os.environ, {'FREEJIRA_TOKEN': 'private-value'}):
            code, output = qa.run("printenv FREEJIRA_TOKEN")
        self.assertNotEqual(code, 0)
        self.assertNotIn('private-value', output)

    def test_timeout_ends_command(self):
        code, output = qa.run([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.05)
        self.assertEqual(code, 124)
        self.assertIn('таймаут', output)


if __name__ == '__main__':
    unittest.main()
