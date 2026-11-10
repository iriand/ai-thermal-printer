import io
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class FeedTests(unittest.TestCase):
    def setUp(self):
        buffer = io.BytesIO()
        Image.new('1', (8, 1), 0).save(buffer, 'PNG')
        self.png = buffer.getvalue()
        self.raster = b'\x1b@\x1dv0\x00\x01\x00\x01\x00\xff'

    def test_default_uses_explicit_paper_feed(self):
        with patch.dict(os.environ):
            os.environ.pop('PRINTER_FEED_LINES', None)
            self.assertEqual(bot.escpos(self.png), self.raster + b'\x1b2\x1bd\x03')

    def test_configured_feed_precedes_cut_and_zero_omits_extra_feed(self):
        for count in (0, 1, 5, 255):
            for cut in (False, True):
                with self.subTest(count=count, cut=cut), patch.dict(os.environ, {'PRINTER_FEED_LINES': str(count)}):
                    footer = b'\x1b2\x1bd' + bytes([count]) if count else b''
                    if cut:
                        footer += b'\x1dV\x00'
                    self.assertEqual(bot.escpos(self.png, cut), self.raster + footer)

    def test_invalid_values_fail_before_creating_or_sending_print_data(self):
        for value in ('-1', '256', '1.5', '', 'true', 'lots'):
            with self.subTest(value=value), patch.dict(os.environ, {'PRINTER_FEED_LINES': value}):
                with self.assertRaisesRegex(ValueError, 'PRINTER_FEED_LINES'):
                    bot.escpos(self.png)
                with patch.object(bot, 'Store') as store, patch.dict(os.environ, {
                    'TELEGRAM_BOT_TOKEN': 'dummy', 'OPENAI_API_KEY': 'dummy', 'ALLOWED_USER_IDS': '1', 'DRY_RUN': 'true'}):
                    with self.assertRaisesRegex(ValueError, 'PRINTER_FEED_LINES'):
                        bot.Bot()
                    store.assert_not_called()


if __name__ == '__main__':
    unittest.main()
