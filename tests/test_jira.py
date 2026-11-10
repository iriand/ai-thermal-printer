import base64
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


ENV = {'JIRA_BASE_URL': 'https://example.atlassian.net/',
       'JIRA_EMAIL': 'owner@example.com', 'JIRA_API_TOKEN': 'fixture-token'}
ISSUE = {'key': 'APP-123', 'fields': {
    'summary': 'Ошибка входа', 'status': {'name': 'В работе'},
    'assignee': {'displayName': 'Андрей'}, 'created': '2026-11-10T12:00:00.000+0200',
    'duedate': '2026-11-15', 'priority': {'name': 'High'}}}


class JiraTests(unittest.TestCase):
    def test_read_request_and_receipt_fields(self):
        response = io.BytesIO(json.dumps(ISSUE).encode())
        with patch.dict(os.environ, ENV, clear=True), patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = response
            result = bot.jira_issue('app-123')
        request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, 'https://example.atlassian.net/rest/api/3/issue/APP-123?fields=summary,status,assignee,created,duedate,priority')
        self.assertEqual(request.get_header('Authorization'), 'Basic ' + base64.b64encode(b'owner@example.com:fixture-token').decode())
        self.assertEqual(result['assignee'], 'Андрей')
        self.assertEqual(result['created'], '10.11.2026')
        self.assertEqual(result['due'], '15.11.2026')
        self.assertEqual(result['url'], 'https://example.atlassian.net/browse/APP-123')

    def test_scoped_token_gateway_and_missing_fields(self):
        issue = {'key': 'APP-123', 'fields': {'summary': 'Test'}}
        with patch.dict(os.environ, dict(ENV, JIRA_CLOUD_ID='cloud-123'), clear=True), patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(json.dumps(issue).encode())
            result = bot.jira_issue('APP-123')
        self.assertTrue(build.return_value.open.call_args.args[0].full_url.startswith('https://api.atlassian.com/ex/jira/cloud-123/'))
        self.assertEqual(result['assignee'], 'Не назначен')
        self.assertEqual(result['due'], 'Не указан')

    def test_invalid_configuration_and_keys_never_request(self):
        for changes, key in [({'JIRA_API_TOKEN': ''}, 'APP-123'),
                             ({'JIRA_BASE_URL': 'http://example.atlassian.net'}, 'APP-123'),
                             ({'JIRA_BASE_URL': 'https://example.atlassian.net.evil.test'}, 'APP-123'),
                             ({'JIRA_CLOUD_ID': '../elsewhere'}, 'APP-123'),
                             ({}, '../../secret')]:
            with self.subTest(changes=changes, key=key), patch.dict(os.environ, dict(ENV, **changes), clear=True), patch.object(bot.urllib.request, 'build_opener') as build:
                with self.assertRaises(ValueError):
                    bot.jira_issue(key)
                build.assert_not_called()

    def test_http_errors_do_not_expose_credentials_or_body(self):
        for code in [401, 403, 404, 429, 500, 302]:
            with self.subTest(code=code), patch.dict(os.environ, ENV, clear=True), patch.object(bot.urllib.request, 'build_opener') as build:
                build.return_value.open.side_effect = urllib.error.HTTPError('url', code, 'fixture-token', {}, None)
                with self.assertRaises(ValueError) as error:
                    bot.jira_issue('APP-123')
                self.assertNotIn('fixture-token', str(error.exception))
        self.assertIsNone(bot.NoJiraRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test'))

    def test_jira_text_voice_preview_and_authorization(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.allowed = {1}
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.say = Mock()
            instance.preview = Mock()
            instance.voice_text = Mock(return_value='Распечатай баг APP-123')
            message = {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}}
            with patch.object(bot, 'jira_issue', return_value={'key': 'APP-123'}) as fetch, patch.object(bot, 'extract') as extract:
                for text in ['/jira app-123', '/jira@mybot APP-123', 'APP-123', 'Распечатай баг APP-123']:
                    instance.handle({'message': dict(message, text=text)})
                instance.handle({'message': dict(message, voice={'file_id': 'voice', 'duration': 5})})
                self.assertEqual(fetch.call_count, 5)
                self.assertEqual(instance.preview.call_count, 5)
                self.assertEqual(instance.store.get('session:1'), {'jira': {'key': 'APP-123'}})
                instance.handle({'message': dict(message, text='/preview')})
                self.assertEqual(fetch.call_count, 5)
                instance.handle({'message': dict(message, text='/jira')})
                instance.handle({'message': dict(message, text='/jira APP-1 APP-2')})
                instance.handle({'message': dict(message, text='/jira APP-123', **{'from': {'id': 2}})})
                self.assertEqual(fetch.call_count, 5)
                extract.assert_not_called()

    def test_snapshot_renders_and_uses_existing_print_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.dry = True
            instance.tg = Mock()
            values = {'key': 'APP-123', 'summary': 'Проверка'}
            instance.preview(1, 1, {'jira': values})
            call = instance.tg.call_args
            self.assertEqual(call.args[0], 'sendPhoto')
            self.assertTrue(call.kwargs['photo'].startswith(b'\x89PNG'))
            callback = call.args[1]['reply_markup']['inline_keyboard'][0][0]['callback_data']
            png = instance.store.claim(callback.split(':')[1], 1)
            self.assertEqual(png, call.kwargs['photo'])

    def test_failed_fetch_keeps_previous_draft_and_buttons(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.allowed = {1}
        instance.store = Mock()
        instance.store.get.return_value = {'template': 'note', 'values': {'text': 'Keep me'}}
        instance.say = Mock()
        instance.preview = Mock()
        with patch.object(bot, 'jira_issue', side_effect=ValueError('Задача недоступна')):
            instance.handle({'message': {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}, 'text': '/jira APP-123'}})
        instance.store.set.assert_not_called()
        instance.store.invalidate.assert_not_called()
        instance.preview.assert_not_called()
        instance.say.assert_called_once_with(1, 'Задача недоступна')


if __name__ == '__main__':
    unittest.main()
