import io
from pathlib import Path
import sys
import unittest

from PIL import Image, ImageChops, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class InvertTests(unittest.TestCase):
    def test_only_selected_row_is_inverted_at_each_paper_width_and_font_size(self):
        for width in (384, 512, 576):
            for large in (False, True):
                with self.subTest(width=width, large=large):
                    row = {'field': 'key', 'large': large}
                    template = {'title': 'JIRA', 'lines': [row, {'text': 'Normal next row'}]}
                    values = {'key': 'APP-123'}
                    normal = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                    row['invert'] = True
                    inverted = Image.open(io.BytesIO(bot.render(template, values, width))).convert('L')
                    height = 44 if large else 36
                    bounds = (20, 72, width - 20, 72 + height)
                    self.assertEqual(ImageChops.difference(normal, inverted).getbbox(), bounds)
                    self.assertEqual(inverted.crop(bounds).tobytes(), ImageOps.invert(normal.crop(bounds)).tobytes())

    def test_wrapped_paragraphs_invert_together_but_leave_qr_unchanged(self):
        values = {'text': 'Длинная строка с переносами ' * 6 + '\nВторая строка',
                  'url': 'https://example.atlassian.net/browse/APP-123'}
        row = {'field': 'text', 'label': 'Текст: ', 'large': True}
        template = {'title': 'JIRA', 'lines': [row, {'qr': 'url'}]}
        normal = Image.open(io.BytesIO(bot.render(template, values, 384))).convert('L')
        row['invert'] = True
        inverted = Image.open(io.BytesIO(bot.render(template, values, 384))).convert('L')
        self.assertEqual(normal.size, inverted.size)
        bounds = ImageChops.difference(normal, inverted).getbbox()
        self.assertEqual(bounds[:3], (20, 72, 364))
        self.assertGreater(bounds[3] - bounds[1], 44)
        self.assertEqual(inverted.crop(bounds).tobytes(), ImageOps.invert(normal.crop(bounds)).tobytes())
        bottom = (0, bounds[3], 384, normal.height)
        self.assertEqual(normal.crop(bottom).tobytes(), inverted.crop(bottom).tobytes())

    def test_explicit_false_preserves_existing_render(self):
        row = {'text': 'Regular row'}
        template = {'title': 'JIRA', 'lines': [row]}
        normal = bot.render(template, {})
        row['invert'] = False
        self.assertEqual(normal, bot.render(template, {}))


if __name__ == '__main__':
    unittest.main()
