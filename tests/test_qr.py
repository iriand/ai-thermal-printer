import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


URL = 'https://example.atlassian.net/browse/APP-123'


class QrTests(unittest.TestCase):
    def test_jira_template_uses_qr_instead_of_url_text(self):
        lines = bot.templates()['jira']['lines']
        self.assertIn({'qr': 'url'}, lines)
        self.assertNotIn({'field': 'url'}, lines)

    def test_qr_fits_supported_paper_widths_and_has_white_quiet_zone(self):
        for width in (384, 512, 576):
            with self.subTest(width=width):
                image = bot.render_qr(URL, width - 40)
                self.assertLessEqual(image.width, width - 40)
                self.assertEqual(image.width, image.height)
                self.assertEqual({value for _, value in image.getcolors()}, {0, 255})
                # Four-module border at up to six pixels per module.
                self.assertEqual(image.crop((0, 0, image.width, 24)).getextrema(), (255, 255))
                self.assertEqual(image.crop((0, image.height - 24, image.width, image.height)).getextrema(), (255, 255))

    def test_receipt_embeds_qr_without_rendering_url_as_text(self):
        template = {'title': 'JIRA', 'lines': [{'qr': 'url'}]}
        with patch.object(bot.ImageDraw.ImageDraw, 'text', autospec=True) as text:
            png = bot.render(template, {'url': URL}, 384)
        self.assertEqual([call.args[2] for call in text.call_args_list], ['JIRA'])
        image = Image.open(io.BytesIO(png)).convert('L')
        code = bot.render_qr(URL, 344)
        x, y = (384 - code.width) // 2, 72
        self.assertEqual(image.crop((x, y, x + code.width, y + code.height)).tobytes(), code.tobytes())

    def test_missing_optional_qr_value_is_omitted(self):
        empty = bot.render({'title': 'JIRA', 'lines': []}, {}, 384)
        missing = bot.render({'title': 'JIRA', 'lines': [{'qr': 'url'}]}, {}, 384)
        self.assertEqual(empty, missing)

    def test_invalid_qr_field_and_mixed_text_rows_are_rejected(self):
        for row in [{'qr': 'unknown'}, {'qr': 'url', 'field': 'key'}, {'qr': 'url', 'text': 'label'}]:
            data = {'jira': {'source': 'jira', 'fields': {'issue_key': {}}, 'lines': [row]}}
            with self.subTest(row=row), patch.object(Path, 'read_text', return_value=json.dumps(data)):
                with self.assertRaises(ValueError):
                    bot.templates()

    def test_oversized_qr_is_rejected_instead_of_shrunk_until_unreadable(self):
        with self.assertRaises(ValueError):
            bot.render_qr('https://example.test/' + 'a' * 2000, 344)


if __name__ == '__main__':
    unittest.main()
