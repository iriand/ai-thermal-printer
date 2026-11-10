import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class IssueIconTests(unittest.TestCase):
    def test_type_names_and_subtask_flag(self):
        for name, expected in [('Bug', 'bug'), ('Баг', 'bug'), (' Ошибка ', 'bug'),
                               ('Epic', 'epic'), ('Эпик', 'epic'), ('Story', 'story'),
                               ('User Story', 'story'), ('Task', 'task'), ('Задача', 'task'),
                               ('Sub-task', 'subtask'), ('Подзадача', 'subtask'),
                               ('Improvement', 'improvement'), ('Test', 'test'),
                               ('Service Request', 'service_request'), ('Problem', 'problem'),
                               ('Change', 'change'), ('Incident', 'incident'),
                               ('Custom request', 'generic'), ('To Do', 'generic')]:
            with self.subTest(name=name):
                self.assertEqual(bot.issue_icon_kind(name), expected)
        self.assertEqual(bot.issue_icon_kind('Custom child', subtask=True), 'subtask')

    def test_each_icon_is_visible_distinct_and_monochrome_at_both_sizes(self):
        for size in (22, 28):
            images = []
            for kind in ('bug', 'epic', 'story', 'task', 'subtask', 'improvement', 'test',
                         'service_request', 'problem', 'change', 'incident', 'generic'):
                image = bot.render_issue_icon(kind, size)
                self.assertEqual(image.size, (size, size))
                self.assertEqual(image.getextrema(), (0, 255))
                images.append(image.tobytes())
            self.assertEqual(len(set(images)), 12)

    def test_icon_precedes_key_and_inverts_with_it(self):
        for width in (384, 512, 576):
            for large, size in [(False, 22), (True, 28)]:
                with self.subTest(width=width, large=large):
                    row = {'field': 'key', 'icon': 'issue_icon', 'large': large}
                    template = {'title': 'JIRA', 'lines': [row]}
                    values = {'key': 'APP-123', 'issue_icon': 'bug'}
                    image = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                    bounds = (20, 78, 20 + size, 78 + size)
                    icon = bot.render_issue_icon('bug', size)
                    self.assertEqual(image.crop(bounds).tobytes(), icon.tobytes())
                    row['invert'] = True
                    inverted = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                    self.assertEqual(inverted.crop(bounds).tobytes(), ImageOps.invert(icon).tobytes())

    def test_wrapped_key_text_stays_to_right_of_icon(self):
        template = {'title': 'JIRA', 'lines': [{'field': 'key', 'icon': 'issue_icon', 'large': True}]}
        with patch.object(bot.ImageDraw.ImageDraw, 'text', autospec=True) as text:
            bot.render(template, {'key': 'APP-' + '1' * 40, 'issue_icon': 'bug'}, 384)
        key_lines = text.call_args_list[1:]
        self.assertGreater(len(key_lines), 1)
        self.assertTrue(all(call.args[1][0] == 56 for call in key_lines))

    def test_invalid_icon_fields_are_rejected(self):
        for row in [{'field': 'key', 'icon': 'unknown'}, {'qr': 'url', 'icon': 'issue_icon'},
                    {'separator': True, 'icon': 'issue_icon'}]:
            data = {'jira': {'source': 'jira', 'fields': {'issue_key': {}}, 'lines': [row]}}
            with self.subTest(row=row), patch.object(Path, 'read_text', return_value=json.dumps(data)):
                with self.assertRaises(ValueError):
                    bot.templates()

    def test_jira_subtask_metadata_is_used_even_with_custom_name(self):
        issue = {'key': 'APP-123', 'fields': {'summary': 'Child', 'issuetype': {'name': 'Custom child', 'subtask': True}}}
        env = {'JIRA_BASE_URL': 'https://example.atlassian.net', 'JIRA_EMAIL': 'owner@example.com', 'JIRA_API_TOKEN': 'fixture'}
        with patch.dict(os.environ, env, clear=True), patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(json.dumps(issue).encode())
            values = bot.jira_issue('APP-123')
        self.assertEqual(values['issue_type'], 'Custom child')
        self.assertEqual(values['issue_icon'], 'subtask')

    def test_custom_type_uses_its_jira_image_via_gateway(self):
        content = io.BytesIO()
        image = Image.new('RGBA', (24, 24), (0, 0, 0, 0))
        image.paste((0, 100, 200, 255), (3, 3, 21, 21))
        image.save(content, 'PNG')
        issue_type = {'name': 'Our custom type', 'avatarId': 12345}
        with patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(content.getvalue())
            stored = bot.jira_type_icon(issue_type, 'https://example.atlassian.net', 'https://api.atlassian.com/ex/jira/cloud-123', 'Basic fixture')
        request = build.return_value.open.call_args.args[0]
        self.assertIn('https://api.atlassian.com/ex/jira/cloud-123/rest/api/3/universal_avatar/view/type/issuetype/avatar/12345', request.full_url)
        self.assertEqual(request.get_header('Authorization'), 'Basic fixture')
        self.assertTrue(stored.startswith('png:'))
        self.assertEqual(bot.render_issue_icon(stored, 28).getextrema(), (0, 255))

    def test_svg_type_icon_is_downloaded_without_token_and_converted(self):
        svg = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#ffcc00" d="M12 1L23 23H1Z"/></svg>'
        issue_type = {'name': 'Custom type', 'iconUrl': 'https://example.atlassian.net/images/icons/issuetypes/custom.svg'}
        with patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(svg)
            stored = bot.jira_type_icon(issue_type, 'https://example.atlassian.net', 'https://example.atlassian.net', 'Basic fixture')
        self.assertIsNone(build.return_value.open.call_args.args[0].get_header('Authorization'))
        self.assertTrue(stored.startswith('png:'))
        self.assertEqual(bot.render_issue_icon(stored, 22).getextrema(), (0, 255))

    def test_failed_icon_download_preserves_fallback_and_rejects_external_hosts(self):
        for url in ('https://example.atlassian.net.evil.test/icon.svg', 'http://example.atlassian.net/icon.png', 'file:///etc/passwd'):
            with self.subTest(url=url), patch.object(bot.urllib.request, 'build_opener') as build:
                result = bot.jira_type_icon({'name': 'Problem', 'iconUrl': url}, 'https://example.atlassian.net', 'https://example.atlassian.net', 'Basic fixture')
                self.assertEqual(result, 'problem')
                build.assert_not_called()
        with patch.object(bot.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = TimeoutError()
            result = bot.jira_type_icon({'name': 'Change', 'avatarId': 123}, 'https://example.atlassian.net', 'https://example.atlassian.net', 'Basic fixture')
        self.assertEqual(result, 'change')

    def test_external_svg_references_and_oversized_content_are_rejected(self):
        for content in [b'<svg xmlns="http://www.w3.org/2000/svg"><image href="file:///etc/passwd"/></svg>',
                        b'<svg xmlns="http://www.w3.org/2000/svg"><path fill="url(https://evil.test/x)"/></svg>',
                        b'x' * (128 * 1024 + 1)]:
            with self.subTest(content=content[:80]), self.assertRaises(ValueError):
                bot.normalize_jira_icon(content)


if __name__ == '__main__':
    unittest.main()
