import io
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot
import vocabulary


FEED = {'id': 123, 'english': 'window', 'italian': 'finestrino', 'italian_edit': 'finestra',
        'russian': 'окно', 'italian_sentence': 'Apri la finestra.', 'english_definitions': ['An opening in a wall.']}
CARD = {'valid': True, 'word': 'finestra', 'pronunciation': 'fi·nè·stra', 'translation_ru': 'окно',
        'example': 'Apri la finestra.', 'example_ru': 'Открой окно.'}


def response(card):
    return {'status': 'completed', 'output': [{'content': [{'type': 'output_text', 'text': json.dumps(card)}]}]}


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value


class VocabularyTests(unittest.TestCase):
    def test_language_aliases(self):
        for value, expected in [('it', 'italian'), ('Итальянский', 'italian'), ('english', 'english'),
                                ('EN', 'english'), ('иврит', 'hebrew'), ('he', 'hebrew'), ('עברית', 'hebrew')]:
            self.assertEqual(vocabulary.normalize_language(value), expected)
        with self.assertRaises(ValueError):
            vocabulary.normalize_language('unsupported')

    def test_feed_is_cached_globally_per_hour(self):
        store = MemoryStore()
        with patch.object(vocabulary.urllib.request, 'urlopen', side_effect=[io.BytesIO(json.dumps(FEED).encode()), io.BytesIO(json.dumps(FEED).encode())]) as fetch:
            with patch.object(vocabulary.time, 'time', return_value=7201):
                self.assertEqual(vocabulary.current_word(store), FEED)
                self.assertEqual(vocabulary.current_word(store), FEED)
                self.assertEqual(fetch.call_count, 1)
            with patch.object(vocabulary.time, 'time', return_value=10801):
                vocabulary.current_word(store)
                self.assertEqual(fetch.call_count, 2)

    def test_edited_translation_and_source_example_are_preserved_and_card_cached(self):
        store = MemoryStore()
        api = Mock(return_value=response(CARD))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'dummy'}), patch.object(vocabulary, 'current_word', return_value=FEED):
            first = vocabulary.word_card(store, 'it', '', api)
            self.assertEqual(first, vocabulary.word_card(store, 'italian', '', api))
        api.assert_called_once()
        payload = api.call_args.args[1]
        context = json.loads(payload['input'])
        self.assertEqual(context['word'], 'finestra')
        self.assertEqual(context['example'], 'Apri la finestra.')
        self.assertTrue(payload['text']['format']['strict'])
        self.assertFalse(payload['store'])
        self.assertEqual(first['provider'], 'Word of The Hour')
        self.assertEqual(first['notes'], 'Перевод примера: AI; Произношение: AI')
        self.assertEqual(first['pronunciation'], 'fi·nè·stra')
        self.assertIn('pronunciation', payload['text']['format']['schema']['required'])

    def test_requested_word_bypasses_service_and_marks_ai_content(self):
        api = Mock(return_value=response(CARD))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'dummy'}), patch.object(vocabulary, 'current_word') as feed:
            card = vocabulary.word_card(MemoryStore(), 'it', 'finestra', api)
        feed.assert_not_called()
        self.assertEqual(card['provider'], 'Ваше слово')
        self.assertIn('Перевод: AI', card['notes'])
        self.assertIn('Пример: AI', card['notes'])

    def test_old_cached_card_without_pronunciation_is_regenerated(self):
        store = MemoryStore()
        api = Mock(return_value=response(CARD))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'dummy'}), patch.object(vocabulary, 'current_word', return_value=FEED):
            vocabulary.word_card(MemoryStore(), 'it', '', api)
            payload = api.call_args.args[1]
            old_key = 'woth:card:' + hashlib.sha256(json.dumps([
                json.loads(payload['input']), payload['model']], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            store.set(old_key, {'word': 'finestra', 'translation_ru': 'окно'})
            api.reset_mock()
            card = vocabulary.word_card(store, 'it', '', api)
        api.assert_called_once()
        self.assertEqual(card['pronunciation'], 'fi·nè·stra')

    def test_missing_hebrew_translation_uses_source_english_and_labels_it(self):
        translated = dict(CARD, word='חלון', pronunciation='kha·LON', example='פתח את החלון.')
        api = Mock(return_value=response(translated))
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'dummy'}), patch.object(vocabulary, 'current_word', return_value=FEED):
            card = vocabulary.word_card(MemoryStore(), 'he', '', api)
        context = json.loads(api.call_args.args[1]['input'])
        self.assertEqual(context['word'], '')
        self.assertEqual(context['english_seed'], 'window')
        self.assertEqual(card['word'], 'חלון')
        self.assertIn('AI-перевод', card['notes'])

    def test_model_cannot_change_supplied_word_or_service_data(self):
        for changes in [{'word': 'porta'}, {'translation_ru': 'дверь'}, {'example': 'Changed'}, {'valid': False}, {'example_ru': ''}, {'pronunciation': ''}]:
            with self.subTest(changes=changes), patch.dict(os.environ, {'OPENAI_API_KEY': 'dummy'}), patch.object(vocabulary, 'current_word', return_value=FEED):
                with self.assertRaises(ValueError):
                    vocabulary.word_card(MemoryStore(), 'it', '', Mock(return_value=response(dict(CARD, **changes))))

    def test_service_errors_do_not_cache_bad_feed(self):
        for content in [b'not-json', b'{}', b'[]']:
            store = MemoryStore()
            with self.subTest(content=content), patch.object(vocabulary.urllib.request, 'urlopen', return_value=io.BytesIO(content)):
                with self.assertRaises(ValueError):
                    vocabulary.current_word(store)
            self.assertEqual(store.data, {})

    def test_explicit_commands_bare_language_and_env_default(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.allowed = {1}
        instance.store = MemoryStore()
        instance.catalog = bot.templates()
        instance.say = Mock()
        instance.word_preview = Mock()
        message = {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}}
        for value, language, word in [('/word italian', 'italian', ''), ('итальянский', 'italian', ''),
                                      ('/word it finestra', 'it', 'finestra'), ('/word@mybot en take off', 'en', 'take off')]:
            instance.handle({'message': dict(message, text=value)})
            instance.word_preview.assert_called_with(1, 1, 'word', language, word)
        with patch.dict(os.environ, {'WORD_LANGUAGE': 'he'}):
            instance.handle({'message': dict(message, text='/word')})
        instance.word_preview.assert_called_with(1, 1, 'word', 'he', '')
        instance.word_preview.reset_mock()
        instance.handle({'message': dict(message, text='/word it', **{'from': {'id': 2}})})
        instance.word_preview.assert_not_called()

    def test_ai_can_select_template_and_ask_language(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.allowed = {1}
            instance.catalog = bot.templates()
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.say = Mock()
            instance.word_preview = Mock()
            message = {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}, 'text': 'Дай слово для изучения'}
            with patch.object(bot, 'extract', return_value={'template': 'word', 'values': []}):
                instance.handle({'message': message})
            self.assertEqual(instance.store.get('session:1')['asked_field'], 'language')
            message['text'] = 'Слово finestra на итальянском'
            with patch.object(bot, 'extract', return_value={'template': 'word', 'values': [
                {'field': 'language', 'value': 'italian'}, {'field': 'word', 'value': 'finestra'}]}):
                instance.handle({'message': message})
            instance.word_preview.assert_called_once_with(1, 1, 'word', 'italian', 'finestra')

    def test_failure_preserves_draft_and_snapshot_preview_never_refetches(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.store = Mock()
        instance.say = Mock()
        instance.preview = Mock()
        with patch.object(bot, 'word_card', side_effect=ValueError('Unavailable')):
            instance.word_preview(1, 1, 'word', 'it', '')
        instance.store.set.assert_not_called()
        instance.store.invalidate.assert_not_called()
        instance.preview.assert_not_called()

    def test_word_snapshot_uses_existing_print_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.catalog = bot.templates()
            instance.dry = True
            instance.tg = Mock()
            values = {key: value for key, value in CARD.items() if key != 'valid'}
            values.update(language='Итальянский', provider='Word of The Hour', notes='Пример: AI')
            with patch.object(bot, 'word_card') as fetch:
                instance.preview(1, 1, {'template': 'word', 'word_card': values})
            fetch.assert_not_called()
            call = instance.tg.call_args
            self.assertTrue(call.kwargs['photo'].startswith(b'\x89PNG'))
            job = call.args[1]['reply_markup']['inline_keyboard'][0][0]['callback_data'].split(':')[1]
            self.assertEqual(instance.store.claim(job, 1), call.kwargs['photo'])

    def test_hebrew_uses_bidi_and_right_alignment_with_basic_font_layout(self):
        path = os.getenv('FONT_PATH', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        font = ImageFont.truetype(path, 26, layout_engine=ImageFont.Layout.BASIC)
        with patch.object(bot.ImageFont, 'truetype', return_value=font), \
             patch.object(bot.ImageDraw.ImageDraw, 'text', autospec=True) as draw:
            bot.render({'title': 'Hebrew', 'lines': [{'text': 'חלון'}]}, {}, 384)
        call = draw.call_args_list[-1]
        self.assertEqual(call.args[1][0], 364)
        self.assertEqual(call.args[2], 'ןולח')
        self.assertEqual(call.kwargs['anchor'], 'ra')


if __name__ == '__main__':
    unittest.main()
