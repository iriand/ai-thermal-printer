import io
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class SeparatorTests(unittest.TestCase):
    def test_default_two_mm_line_and_margins_at_supported_paper_widths(self):
        for width in (384, 512, 576):
            with self.subTest(width=width), patch.dict(os.environ, {'PRINTER_DPI': '203'}):
                png = bot.render({'title': 'Test', 'lines': [{'separator': True}]}, {}, width)
                image = Image.open(io.BytesIO(png)).convert('L')
                self.assertEqual(image.crop((20, 80, width - 20, 96)).getextrema(), (0, 0))
                self.assertEqual(image.crop((0, 72, 20, 104)).getextrema(), (255, 255))
                self.assertEqual(image.crop((width - 20, 72, width, 104)).getextrema(), (255, 255))
                self.assertEqual(image.crop((20, 72, width - 20, 80)).getextrema(), (255, 255))
                self.assertEqual(image.crop((20, 96, width - 20, 104)).getextrema(), (255, 255))

    def test_custom_thickness_uses_configured_dpi(self):
        for dpi, width_mm, expected in [(203, 0.3, 2), (300, 2, 24), (203, 0.01, 1)]:
            with self.subTest(dpi=dpi, width_mm=width_mm), patch.dict(os.environ, {'PRINTER_DPI': str(dpi)}):
                image = Image.open(io.BytesIO(bot.render({'title': 'Test', 'lines': [
                    {'separator': True, 'width_mm': width_mm}]}, {}, 384))).convert('L')
                self.assertEqual(image.getpixel((20, 79)), 255)
                self.assertEqual(image.crop((20, 80, 364, 80 + expected)).getextrema(), (0, 0))
                self.assertEqual(image.getpixel((20, 80 + expected)), 255)

    def test_separators_can_appear_between_text_and_qr_rows(self):
        values = {'url': 'https://example.atlassian.net/browse/APP-123'}
        lines = [{'separator': True}, {'text': 'Task'}, {'separator': True, 'width_mm': 0.3}, {'qr': 'url'}, {'separator': True}]
        png = bot.render({'title': 'JIRA', 'lines': lines}, values, 384)
        image = Image.open(io.BytesIO(png)).convert('L')
        bands = []
        for y in range(image.height):
            if image.crop((20, y, 364, y + 1)).getextrema() == (0, 0):
                if not bands or bands[-1][-1] != y - 1:
                    bands.append([])
                bands[-1].append(y)
        self.assertEqual([len(band) for band in bands], [16, 2, 16])

    def test_invalid_separator_definitions_are_rejected(self):
        for row in [{'separator': False}, {'separator': True, 'text': 'mixed'},
                    {'separator': True, 'qr': 'value'}, {'separator': True, 'field': 'value'},
                    *[{'separator': True, 'width_mm': v} for v in (0, -1, True, '2', None, float('nan'), float('inf'))]]:
            with self.subTest(row=row), patch.object(Path, 'read_text', return_value=json.dumps({
                'note': {'fields': {'value': {}}, 'lines': [row]}})):
                with self.assertRaises(ValueError):
                    bot.templates()

    def test_separator_cannot_overflow_receipt(self):
        for lines in [[{'separator': True, 'width_mm': 2000}], [{'separator': True}] * 1000]:
            with self.subTest(count=len(lines)), self.assertRaises(ValueError):
                bot.render({'title': 'Test', 'lines': lines}, {})


if __name__ == '__main__':
    unittest.main()
