import io
import json
from pathlib import Path
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


class Tests(unittest.TestCase):
    def test_followup_merge_and_switch(self):
        catalog = bot.templates()
        first = bot.merge(catalog, {}, {'template': 'food', 'values': [{'field': 'name', 'value': 'Курица'}]})
        self.assertEqual(first['asked_field'], 'prepared')
        second = bot.merge(catalog, first, {'template': 'food', 'values': [{'field': 'prepared', 'value': '07.11.2026'}]})
        self.assertIsNone(second['asked_field'])
        self.assertEqual(second['values']['name'], 'Курица')
        switched = bot.merge(catalog, second, {'template': 'task', 'values': []})
        self.assertEqual(switched['values'], {})
        with self.assertRaises(ValueError):
            bot.merge(catalog, first, {'template': 'food', 'values': [{'field': 'shell', 'value': 'anything'}]})

    def test_raster_roundtrip_all_pixels(self):
        png = bot.render(bot.templates()['note'], {'text': 'Привет, Андрей!\nДлинная строка ' * 15}, 384)
        source = Image.open(io.BytesIO(png)).convert('1')
        data = bot.escpos(png)
        pos, rows = 2, []
        while data[pos:pos+4] == b'\x1dv0\x00':
            width_bytes, height = struct.unpack('<HH', data[pos+4:pos+8])
            pos += 8
            for _ in range(height):
                row = data[pos:pos+width_bytes]
                rows.append([0 if row[x//8] & (0x80 >> (x%8)) else 255 for x in range(source.width)])
                pos += width_bytes
        self.assertEqual(len(rows), source.height)
        self.assertEqual([p for row in rows for p in row], list(source.getdata()))
        self.assertEqual(data[pos:], b'\x1b2\x1bd\x03')
        self.assertTrue(bot.escpos(png, True).endswith(b'\x1dV\x00'))

    def test_job_claim_owner_expiry_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.db'
            store = bot.Store(path)
            job = store.new_job(1, b'png')
            self.assertIsNone(store.claim(job, 2))
            self.assertEqual(store.claim(job, 1), b'png')
            store.db.close()
            store = bot.Store(path)
            self.assertIsNone(store.claim(job, 1))
            job = store.new_job(1, b'png')
            self.assertIsNone(store.claim(job, 1, now=time.time()+1801))
            job = store.new_job(1, b'png')
            store.invalidate(1)
            self.assertIsNone(store.claim(job, 1))

    def test_print_callback_tcp_and_duplicates(self):
        received = []
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        def receive():
            conn, _ = listener.accept()
            with conn:
                chunks = []
                while True:
                    part = conn.recv(4096)
                    if not part:
                        break
                    chunks.append(part)
                received.append(b''.join(chunks))
            listener.close()
        worker = threading.Thread(target=receive, daemon=True)
        worker.start()
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.allowed = {1}
            instance.dry = False
            instance.store = bot.Store(Path(directory) / 'state.db')
            instance.tg = lambda *a, **kw: None
            instance.say = lambda *a: None
            png = bot.render(bot.templates()['note'], {'text': 'Тест'})
            job = instance.store.new_job(1, png)
            update = {'callback_query': {'id': 'callback', 'from': {'id': 1}, 'data': 'print:'+job,
                'message': {'chat': {'id': 1, 'type': 'private'}}}}
            with patch.dict('os.environ', {'PRINTER_HOST': '127.0.0.1', 'PRINTER_PORT': str(listener.getsockname()[1]), 'PRINTER_CUT': 'false', 'PRINTER_FEED_LINES': '5'}):
                instance.handle(update)
                instance.handle(update)
                expected = bot.escpos(png)
            worker.join(3)
            self.assertEqual(received, [expected])
            self.assertEqual(instance.store.db.execute('SELECT status FROM jobs WHERE id=?', (job,)).fetchone()[0], 'sent')

    def test_ai_schema_and_mapping_with_fixture(self):
        result = {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps({
            'template': 'food', 'values': [{'field': 'name', 'value': 'Курица'}]})}]}]}
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'dummy'}), patch.object(bot, 'api', return_value=result) as api:
            parsed = bot.extract(bot.templates(), {}, 'Наклейка для курицы')
        self.assertEqual(parsed['values'][0]['value'], 'Курица')
        payload = api.call_args.args[1]
        self.assertTrue(payload['text']['format']['strict'])
        self.assertFalse(payload['store'])

    def test_authorization_blocks_network_and_print(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.allowed = {1}
        with patch.object(bot, 'extract') as extract:
            instance.handle({'message': {'from': {'id': 2}, 'chat': {'id': 2, 'type': 'private'}, 'text': 'print'}})
            instance.handle({'message': {'from': {'id': 1}, 'chat': {'id': -1, 'type': 'group'}, 'text': 'print'}})
            extract.assert_not_called()


    def test_voice_follows_template_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.allowed = {1}
            instance.store = bot.Store(Path(directory) / 'state.db')
            instance.catalog = bot.templates()
            instance.say = lambda *args: None
            instance.voice_text = lambda voice: 'Заметка: купить молоко'
            instance.preview = lambda *args: None
            update = {'message': {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'},
                      'voice': {'file_id': 'voice', 'duration': 5, 'file_size': 100}}}
            result = {'template': 'note', 'values': [{'field': 'text', 'value': 'Купить молоко'}]}
            with patch.object(bot, 'extract', return_value=result) as extract:
                instance.handle(update)
            self.assertEqual(extract.call_args.args[2], 'Заметка: купить молоко')
            self.assertEqual(instance.store.get('session:1')['values']['text'], 'Купить молоко')

    def test_voice_limits_and_unauthorized_do_not_download(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.allowed = {1}
        instance.say = lambda *args: None
        with patch.object(instance, 'voice_text') as download:
            for user, duration in [(2, 5), (1, 121)]:
                instance.handle({'message': {'from': {'id': user}, 'chat': {'id': user, 'type': 'private'},
                    'voice': {'file_id': 'voice', 'duration': duration}}})
            download.assert_not_called()

    def test_voice_failure_does_not_extract_or_print(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.allowed = {1}
        instance.say = lambda *args: None
        with patch.object(instance, 'voice_text', side_effect=RuntimeError), patch.object(bot, 'extract') as extract:
            instance.handle({'message': {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'},
                'voice': {'file_id': 'voice', 'duration': 5}}})
            extract.assert_not_called()

    def test_transcription_wav_upload(self):
        def convert(args, **kwargs):
            Path(args[-1]).write_bytes(b'RIFF-test-wav')
        with patch.dict('os.environ', {'OPENAI_API_KEY': 'dummy'}), \
             patch.object(bot.subprocess, 'run', side_effect=convert), \
             patch.object(bot, 'api', return_value={'text': 'Купить молоко'}) as api:
            self.assertEqual(bot.transcribe_voice(b'ogg-audio'), 'Купить молоко')
        self.assertEqual(api.call_args.args[0], 'https://api.openai.com/v1/audio/transcriptions')
        self.assertIn(b'RIFF-test-wav', api.call_args.kwargs['body'])
        self.assertIn(b'filename="voice.wav"', api.call_args.kwargs['body'])


if __name__ == '__main__':
    unittest.main()
