import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autoelective.environ import Environ
Environ().config_ini = 'config.sample.ini'
from autoelective.course import Course
from autoelective.parser import get_tree
from autoelective.workflow import run_once, validate_captcha
from autoelective.captcha.proxy import RecognitionProxy
from autoelective.exceptions import ElectionSuccess, OperationFailedError, RecognizerError


TARGET = Course('测试课程', 1, '测试院系')


def page(selected=False, state='已选上', available=True):
    headers = '<tr class="datagrid-header extra">' + ''.join(
        '<th><span>%s</span></th>' % x for x in ('课程名', '班号', '开课单位', '限数/已选'))
    cells = '<td><span>测试课程</span></td><td>01</td><td>测试院系</td>'
    plans = (headers + '<th>补选</th></tr><tr class="datagrid-odd extra">' + cells
             + '<td>180 / %d</td><td><a href="electSupplement.do?index=1">补选</a></td></tr>') % (153 if available else 180)
    elected = headers + '<th>选课状态</th></tr>'
    if selected:
        elected += '<tr class="datagrid-even">' + cells + '<td>180/154</td><td>' + state + '</td></tr>'
    # Deliberately reverse the old positional order and add nested header tags.
    return SimpleNamespace(_tree=get_tree('<html><table class="datagrid extra">' + elected
        + '</table><table class="datagrid">' + plans + '</table></html>'))


class WorkflowTests(unittest.TestCase):
    def setup_run(self, pages):
        cfg = SimpleNamespace(courses={'test': TARGET}, iaaa_id='test', iaaa_password='dummy',
            is_dual_degree=False, supply_cancel_page=1, delays={}, check_supply_cancel_page=lambda x: None)
        client, auth = Mock(), Mock()
        auth.oauth_login.return_value.json.return_value = {'token': 'dummy-token'}
        client.get_SupplyCancel.side_effect = pages
        client.get_Validate.return_value.json.return_value = {'valid': '2'}
        recognizer = Mock()
        recognizer.recognize.return_value.code = 'abcd'
        factory = Mock(return_value=recognizer)
        return cfg, client, auth, factory

    def run_flow(self, args, submit=True):
        cfg, client, auth, factory = args
        return run_once(cfg, client=client, auth=auth, recognizer_factory=factory,
                        submit=submit, emit=lambda _: None)

    def test_complete_flow_verifies_enrollment(self):
        args = self.setup_run([page(), page(True)])
        args[1].get_ElectSupplement.side_effect = ElectionSuccess()
        self.assertEqual(self.run_flow(args), 'elected')
        args[1].get_ElectSupplement.assert_called_once_with('electSupplement.do?index=1')
        args[1].get_Validate.assert_called_once_with('test', 'abcd')

    def test_read_only_never_recognizes_or_submits(self):
        args = self.setup_run([page()])
        self.assertEqual(self.run_flow(args, False), 'available')
        args[3].assert_not_called()
        args[1].get_ElectSupplement.assert_not_called()

    def test_already_selected_never_submits(self):
        args = self.setup_run([page(True)])
        self.assertEqual(self.run_flow(args), 'already_elected')
        args[3].assert_not_called()

    def test_full_never_submits(self):
        args = self.setup_run([page(available=False)])
        self.assertEqual(self.run_flow(args), 'full')
        args[3].assert_not_called()

    def test_success_message_without_selected_state_is_failure(self):
        args = self.setup_run([page(), page()])
        args[1].get_ElectSupplement.side_effect = ElectionSuccess()
        with self.assertRaises(OperationFailedError): self.run_flow(args)

    def test_pending_is_not_enrolled(self):
        args = self.setup_run([page(), page(True, '候补中')])
        self.assertEqual(self.run_flow(args), 'pending')

    def test_uncertain_submission_is_reconciled_not_replayed(self):
        args = self.setup_run([page(), page(True)])
        args[1].get_ElectSupplement.side_effect = TimeoutError()
        self.assertEqual(self.run_flow(args), 'elected')
        self.assertEqual(args[1].get_ElectSupplement.call_count, 1)

    def test_failed_captcha_is_bounded(self):
        args = self.setup_run([page()])
        args[1].get_Validate.return_value.json.return_value = {'valid': 0}
        with self.assertRaises(OperationFailedError): self.run_flow(args)
        self.assertEqual(args[1].get_Validate.call_count, 3)
        args[1].get_ElectSupplement.assert_not_called()

    def test_numeric_validation_status(self):
        args = self.setup_run([page(), page(True)])
        args[1].get_Validate.return_value.json.return_value = {'valid': 2}
        self.assertEqual(self.run_flow(args), 'elected')


class RecognizerTests(unittest.TestCase):
    def test_two_images_two_requests_and_fresh_results(self):
        with patch('autoelective.captcha.online.APIConfig') as cfg, \
             patch('autoelective.captcha.online.requests.post') as post, \
             patch.object(RecognitionProxy, 'to_b64', side_effect=['first', 'second']):
            cfg.return_value = SimpleNamespace(uname='dummy', pwd='dummy', typeid=1003, timeout=7)
            post.return_value.json.side_effect = [
                {'success': True, 'data': {'result': 'abcd'}},
                {'success': True, 'data': {'result': 'efgh'}}]
            r = RecognitionProxy()
            self.assertEqual(r.recognize(b'one').code, 'abcd')
            self.assertEqual(r.recognize(b'two').code, 'efgh')
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args.kwargs['timeout'], 7)
            self.assertEqual(post.call_args.kwargs['json']['typeid'], 1003)
            self.assertEqual(post.call_args.kwargs['json']['image'], 'second')

    def test_failed_or_empty_recognition(self):
        with patch('autoelective.captcha.online.APIConfig'), \
             patch('autoelective.captcha.online.requests.post') as post, \
             patch.object(RecognitionProxy, 'to_b64', return_value='image'):
            r = RecognitionProxy()
            for payload in ({'success': False}, {'success': True, 'data': {}}, []):
                post.return_value.json.return_value = payload
                with self.assertRaises(RecognizerError): r.recognize(b'image')


class TransportTests(unittest.TestCase):
    def test_submission_url_and_no_retry(self):
        from autoelective.elective import ElectiveClient
        from autoelective.const import ElectiveURL
        c = ElectiveClient(1)
        url = ElectiveURL.Supplement.rsplit('/', 1)[0] + '/electSupplement.do?index=1'
        self.assertEqual(c._session.get_adapter(url).max_retries.total, 0)
        with patch.object(c, '_get') as get:
            c.get_ElectSupplement('electSupplement.do?index=1')
            self.assertEqual(get.call_args.kwargs['url'], url)
            for bad in ('https://example.org/supplement/electSupplement.do',
                        'javascript:evil()', 'electSupplement.do/other', None):
                with self.assertRaises(RuntimeError): c.get_ElectSupplement(bad)


if __name__ == '__main__':
    unittest.main()
