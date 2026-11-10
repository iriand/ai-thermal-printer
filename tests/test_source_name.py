import copy
import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class SourceNameTests(unittest.TestCase):
    def test_template_title_is_printed_by_default_and_can_be_disabled_for_any_template(self):
        for name, template in bot.templates().items():
            with self.subTest(template=name):
                original = copy.deepcopy(template)
                with patch.dict(os.environ), patch.object(bot.ImageDraw.ImageDraw, 'text', autospec=True) as text:
                    os.environ.pop('PRINT_SOURCE_NAME', None)
                    bot.render(template, {}, 576)
                self.assertEqual(text.call_args_list[0].args[2], template['title'])
                with patch.dict(os.environ, {'PRINT_SOURCE_NAME': 'false'}), patch.object(bot.ImageDraw.ImageDraw, 'text', autospec=True) as text:
                    bot.render(template, {}, 576)
                printed = ''.join(call.args[2] for call in text.call_args_list)
                self.assertNotIn(template['title'], printed)
                self.assertEqual(template, original)

    def test_hidden_header_leaves_no_blank_gap_and_preserves_receipt_content(self):
        template = {'title': 'JIRA', 'lines': [
            {'separator': True, 'width': '0.5mm'},
            {'field': 'key', 'icon': 'issue_icon', 'invert': True, 'large': True},
            {'qr': 'url'}]}
        values = {'key': 'APP-123', 'issue_icon': 'bug', 'url': 'https://example.atlassian.net/browse/APP-123'}
        for width in (384, 512, 576):
            with self.subTest(width=width):
                with patch.dict(os.environ, {'PRINT_SOURCE_NAME': 'true'}):
                    shown = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                with patch.dict(os.environ, {'PRINT_SOURCE_NAME': 'false'}):
                    hidden = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                self.assertEqual(shown.height - hidden.height, 52)
                self.assertEqual(shown.crop((0, 72, width, shown.height)).tobytes(), hidden.crop((0, 20, width, hidden.height)).tobytes())

    def test_boolean_settings_accept_case_and_surrounding_whitespace(self):
        template = {'title': 'JIRA', 'lines': []}
        with patch.dict(os.environ, {'PRINT_SOURCE_NAME': ' false '}):
            hidden = bot.render(template, {})
        with patch.dict(os.environ, {'PRINT_SOURCE_NAME': 'FALSE'}):
            self.assertEqual(hidden, bot.render(template, {}))
        with patch.dict(os.environ, {'PRINT_SOURCE_NAME': ' TRUE '}):
            self.assertNotEqual(hidden, bot.render(template, {}))
        with patch.dict(os.environ, {'PRINT_SOURCE_NAME': 'typo'}), self.assertRaisesRegex(ValueError, 'PRINT_SOURCE_NAME'):
            bot.render(template, {})


if __name__ == '__main__':
    unittest.main()
