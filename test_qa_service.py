import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

import qa_agent as qa
import service


class FakeFreejira:
    def __init__(self):
        self.task = {'id': 'task-1', 'revision': 3, 'status': 'review'}
        self.comments = []
        self.fail_after_comment = False
        self.writes = []

    def call(self, name, **kwargs):
        if name == 'get_task':
            return {'key': 'DEMO-1', 'task': copy.deepcopy(self.task),
                    'comments': copy.deepcopy(self.comments)}
        if name == 'add_comment':
            self.comments.append({'body': kwargs['body']})
            self.writes.append(name)
            if self.fail_after_comment:
                self.fail_after_comment = False
                raise TimeoutError('Response lost after commit')
        if name == 'update_task':
            assert kwargs['revision'] == self.task['revision']
            self.task.update(status=kwargs['status'], revision=self.task['revision'] + 1)
            self.writes.append(name)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(qa, 'STATE_FILE', Path(self.temp.name) / 'state.json')
        self.patcher.start()
        self.fj = FakeFreejira()
        self.task = self.fj.call('get_task')
        self.state = {}

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def publish(self, target='done'):
        return qa.publish(self.fj, self.task, '3:sha:ci', 'pass', 'QA report', target, self.state)

    def test_lost_response_does_not_duplicate_comment(self):
        self.fj.fail_after_comment = True
        with self.assertRaises(TimeoutError):
            self.publish()
        self.assertTrue(qa.load_state()['DEMO-1']['pending'])
        self.publish()
        self.assertEqual(len(self.fj.comments), 1)
        self.assertEqual(self.fj.task['status'], 'done')
        self.assertNotIn('pending', qa.load_state()['DEMO-1'])

    def test_changed_revision_rejects_stale_result(self):
        self.fj.task['revision'] += 1
        self.assertFalse(self.publish())
        self.assertEqual(self.fj.writes, [])

    def test_moved_task_rejects_result(self):
        self.fj.task['status'] = 'doing'
        self.assertFalse(self.publish())
        self.assertEqual(self.fj.writes, [])

    def test_read_review_again_has_new_marker(self):
        self.assertNotEqual(qa.report_marker('task-1', '3:sha:ci'),
                            qa.report_marker('task-1', '5:sha:ci'))

    def test_unsure_does_not_move_task(self):
        self.publish(target=None)
        self.assertEqual(self.fj.task['status'], 'review')
        self.assertEqual(self.fj.writes, ['add_comment'])

    def test_configured_background_outcomes_never_move_tasks(self):
        self.assertEqual(qa.CONFIG['columns'], {'pass': None, 'fail': None, 'unsure': None})

    def test_report_does_not_claim_a_status_transition(self):
        report = qa.render(None, qa.Evidence(), [],
                           {'summary': 'Test', 'checklist': [], 'problems': [], 'risks': [], 'manual_checks': []},
                           'fail', 'test failed', None)
        self.assertNotIn('возврат в работу', report)
        self.assertNotIn('Колонка:', report)


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.pr = {'state': 'OPEN', 'isDraft': False}
        self.ev = qa.Evidence([qa.Check('unit', True)])
        self.ci = [{'name': 'CI', 'result': 'SUCCESS'}]
        self.v = {'checklist': [{'status': 'covered'}], 'matches_task': 'yes', 'problems': []}

    def verdict(self):
        return qa.decide(self.pr, self.ev, self.ci, self.v)[0]

    def test_pending_ci_is_not_done(self):
        self.ci[0]['result'] = 'PENDING'
        self.assertEqual(self.verdict(), 'unsure')

    def test_unclear_criterion_is_not_done(self):
        self.v['checklist'][0]['status'] = 'unclear'
        self.assertEqual(self.verdict(), 'unsure')

    def test_no_ci_is_not_done(self):
        self.ci = []
        self.assertEqual(self.verdict(), 'unsure')

    def test_all_proven_passes(self):
        self.assertEqual(self.verdict(), 'pass')

    def test_failed_tests_return_to_work(self):
        self.ev.checks[0].ok = False
        self.assertEqual(self.verdict(), 'fail')

    def test_ci_completion_changes_fingerprint(self):
        pr = {'headRefOid': 'sha'}
        old = qa.fingerprint_of(3, pr, self.ci)
        self.ci[0]['result'] = 'PENDING'
        self.assertNotEqual(old, qa.fingerprint_of(3, pr, self.ci))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        service.STOP.clear()

    def test_offline_task_retried_and_other_task_continues(self):
        fj = Mock()
        fj.call.return_value = [{'id': 'a', 'number': 1, 'revision': 3},
                                {'id': 'b', 'number': 2, 'revision': 1}]
        tunnel = Mock()
        project = Mock(key='DEMO', freejira_project_id='project')
        project.repo.is_dir.return_value = True
        with patch.dict(qa.CONFIG, {'projects': {'DEMO': {}}}), \
                patch.object(qa.Project, 'from_config', return_value=project), \
                patch.object(qa, 'load_state', return_value={}), \
                patch.object(qa, 'process', side_effect=[TimeoutError('offline'), None, None]) as process, \
                patch.object(service, 'atomic_json'), patch.object(service, 'health'):
            retries = service.cycle(fj, tunnel, {})
            self.assertEqual(process.call_count, 2)
            self.assertIn('a', retries)
            self.assertNotIn('b', retries)
            service.cycle(fj, tunnel, retries)
            self.assertEqual(process.call_count, 3)  # a ждёт backoff, b доступна

    def test_new_revision_bypasses_previous_backoff(self):
        fj = Mock()
        fj.call.return_value = [{'id': 'a', 'number': 1, 'revision': 4}]
        project = Mock(key='DEMO', freejira_project_id='project')
        project.repo.is_dir.return_value = True
        retries = {'a': {'revision': 3, 'after': 99999999999, 'count': 5}}
        with patch.dict(qa.CONFIG, {'projects': {'DEMO': {}}}), \
                patch.object(qa.Project, 'from_config', return_value=project), \
                patch.object(qa, 'load_state', return_value={}), \
                patch.object(qa, 'process') as process, \
                patch.object(service, 'atomic_json'), patch.object(service, 'health'):
            service.cycle(fj, Mock(), retries)
            process.assert_called_once()


if __name__ == '__main__':
    unittest.main()
