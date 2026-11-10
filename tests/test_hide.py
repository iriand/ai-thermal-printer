import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class HideTests(unittest.TestCase):
    def test_hide_removes_every_row_type_without_leaving_space(self):
        rows = [
            {'text': 'Hidden text'},
            {'field': 'key', 'large': True},
            {'field': 'key', 'icon': 'issue_icon', 'invert': True},
            {'separator': True, 'width': '2mm'},
            {'qr': 'url'}
        ]
        values = {'key': 'APP-123', 'issue_icon': 'bug', 'url': 'https://example.atlassian.net/browse/APP-123'}
        visible = [{'text': 'Before'}, {'text': 'After'}]
        for row in rows:
            for width in (384, 512, 576):
                with self.subTest(row=row, width=width):
                    template = {'title': 'JIRA', 'lines': [visible[0], dict(row, hide=True), visible[1]]}
                    original = copy.deepcopy(template)
                    self.assertEqual(bot.render(template, values, width), bot.render({'title': 'JIRA', 'lines': visible}, values, width))
                    self.assertEqual(template, original)

    def test_hide_false_preserves_existing_render_for_every_type(self):
        lines = [{'text': 'Text'}, {'field': 'key', 'icon': 'issue_icon', 'invert': True},
                 {'separator': True}, {'qr': 'url'}]
        values = {'key': 'APP-123', 'issue_icon': 'bug', 'url': 'https://example.atlassian.net/browse/APP-123'}
        normal = bot.render({'title': 'JIRA', 'lines': lines}, values)
        explicit = bot.render({'title': 'JIRA', 'lines': [dict(row, hide=False) for row in lines]}, values)
        self.assertEqual(normal, explicit)

    def test_hidden_qr_and_icon_do_not_call_renderers(self):
        template = {'title': 'JIRA', 'lines': [
            {'qr': 'url', 'hide': True}, {'field': 'key', 'icon': 'issue_icon', 'hide': True}]}
        with patch.object(bot, 'render_qr') as qr, patch.object(bot, 'render_issue_icon') as icon:
            bot.render(template, {'url': 'irrelevant', 'key': 'APP-123'})
        qr.assert_not_called()
        icon.assert_not_called()

    def test_hide_requires_boolean_and_hidden_rows_still_validate(self):
        for hide in ('true', 'false', 0, 1, None):
            data = {'note': {'fields': {'value': {}}, 'lines': [{'field': 'value', 'hide': hide}]}}
            with self.subTest(hide=hide), patch.object(Path, 'read_text', return_value=json.dumps(data)):
                with self.assertRaisesRegex(ValueError, 'hide'):
                    bot.templates()
        data = {'note': {'fields': {'value': {}}, 'lines': [{'field': 'unknown', 'hide': True}]}}
        with patch.object(Path, 'read_text', return_value=json.dumps(data)):
            with self.assertRaisesRegex(ValueError, 'Unknown field'):
                bot.templates()


if __name__ == '__main__':
    unittest.main()
