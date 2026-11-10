import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bot


LOCATION = {'results': [{'name': 'Хайфа', 'admin1': 'Хайфский округ', 'country_code': 'IL',
                         'latitude': 32.82, 'longitude': 34.99}]}
DAYS = ['2026-11-10', '2026-11-11', '2026-11-12']
FORECAST = {
    'timezone': 'Asia/Jerusalem',
    'daily': {'time': DAYS, 'temperature_2m_max': [25, 24, 23], 'temperature_2m_min': [18, 17, 16],
              'precipitation_probability_max': [10, 80, None], 'weather_code': [0, 61, 3]},
    'hourly': {'time': [f'{day}T{hour:02}:00' for day in DAYS for hour in range(24)],
               'temperature_2m': [20] * 24 + [21] * 24 + [None] * 24,
               'precipitation_probability': [0] * 24 + [80] * 24 + [None] * 24}}
ENV = {'WEATHER_CITY': 'Haifa', 'WEATHER_COUNTRY_CODE': 'il'}


class WeatherTests(unittest.TestCase):
    def test_city_and_forecast_requests_use_env_and_local_time(self):
        with patch.dict(os.environ, ENV), patch.object(bot, 'weather_json', side_effect=[LOCATION, FORECAST]) as api:
            values = bot.weather_forecast()
        self.assertEqual(api.call_args_list[0].args[1]['name'], 'Haifa')
        self.assertEqual(api.call_args_list[0].args[1]['countryCode'], 'IL')
        self.assertEqual(api.call_args_list[1].args[1]['timezone'], 'auto')
        self.assertEqual(api.call_args_list[1].args[1]['forecast_days'], 7)
        self.assertEqual(values['date'], '10.11.2026')
        self.assertEqual(values['temperature_max'], '25°C')
        self.assertEqual(values['temperature_min'], '18°C')
        self.assertEqual(values['precipitation_probability'], '10%')
        self.assertEqual(values['conditions'], 'Ясно')
        self.assertEqual(len(values['hourly'].splitlines()), 24)
        self.assertTrue(values['hourly'].startswith('00:00  20°C  0%'))
        self.assertEqual(values['timezone'], 'Asia/Jerusalem')

    def test_date_selection_and_missing_values(self):
        for day, date in [('tomorrow', '11.11.2026'), ('завтра', '11.11.2026'),
                          ('2026-11-11', '11.11.2026'), ('day_after_tomorrow', '12.11.2026')]:
            with self.subTest(day=day), patch.dict(os.environ, ENV), patch.object(bot, 'weather_json', side_effect=[LOCATION, FORECAST]):
                values = bot.weather_forecast(day)
                self.assertEqual(values['date'], date)
                if date == '12.11.2026':
                    self.assertEqual(values['precipitation_probability'], 'н/д')
                    self.assertIn('н/д', values['hourly'])
                    self.assertNotIn('0%', values['hourly'])

    def test_dates_outside_forecast_and_bad_configuration_fail(self):
        with patch.dict(os.environ, ENV), patch.object(bot, 'weather_json', side_effect=[LOCATION, FORECAST]):
            with self.assertRaisesRegex(ValueError, 'Дата вне прогноза'):
                bot.weather_forecast('2026-12-01')
        for env, day in [({'WEATHER_CITY': ''}, 'today'), (dict(ENV, WEATHER_COUNTRY_CODE='Israel'), 'today'),
                         (ENV, 'yesterday')]:
            with self.subTest(env=env, day=day), patch.dict(os.environ, env, clear=True), patch.object(bot, 'weather_json') as api:
                with self.assertRaises(ValueError):
                    bot.weather_forecast(day)
                api.assert_not_called()

    def test_unknown_city_and_incomplete_hourly_data_fail(self):
        broken = copy.deepcopy(FORECAST)
        broken['hourly']['temperature_2m'].pop()
        for responses in [[{}, FORECAST], [LOCATION, broken]]:
            with self.subTest(responses=len(responses)), patch.dict(os.environ, ENV), patch.object(bot, 'weather_json', side_effect=responses):
                with self.assertRaises(ValueError):
                    bot.weather_forecast()

    def test_http_request_encodes_city_and_uses_get(self):
        with patch.object(bot.urllib.request, 'urlopen', return_value=io.BytesIO(b'{"results": []}')) as request:
            bot.weather_json('https://geocoding-api.open-meteo.com/v1/search', {'name': 'Хайфа & test'})
        req = request.call_args.args[0]
        self.assertEqual(req.get_method(), 'GET')
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(req.full_url).query)['name'], ['Хайфа & test'])
        self.assertIsNone(req.get_header('Authorization'))

    def test_command_ai_voice_and_preview_use_existing_confirmation_flow(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.allowed = {1}
            instance.catalog = bot.templates()
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.say = Mock()
            instance.preview = Mock()
            instance.voice_text = Mock(return_value='Распечатай погоду на завтра')
            message = {'from': {'id': 1}, 'chat': {'id': 1, 'type': 'private'}}
            with patch.object(bot, 'weather_forecast', return_value={'date': '11.11.2026'}) as fetch, patch.object(bot, 'extract') as extract:
                instance.handle({'message': dict(message, text='/weather tomorrow')})
                fetch.assert_called_once_with('tomorrow')
                extract.assert_not_called()
                self.assertEqual(instance.store.get('session:1'), {'template': 'weather', 'weather': {'date': '11.11.2026'}})
                instance.handle({'message': dict(message, text='/preview')})
                self.assertEqual(fetch.call_count, 1)
                extract.return_value = {'template': 'weather', 'values': [{'field': 'date', 'value': 'tomorrow'}]}
                instance.handle({'message': dict(message, voice={'file_id': 'voice', 'duration': 5})})
                self.assertEqual(extract.call_args.args[1], {})
                self.assertEqual(fetch.call_count, 2)
                instance.handle({'message': dict(message, text='/weather', **{'from': {'id': 2}})})
                self.assertEqual(fetch.call_count, 2)

    def test_failed_fetch_keeps_previous_draft_and_buttons(self):
        instance = bot.Bot.__new__(bot.Bot)
        instance.store = Mock()
        instance.say = Mock()
        instance.preview = Mock()
        with patch.object(bot, 'weather_forecast', side_effect=ValueError('Unavailable')):
            instance.weather_preview(1, 1, 'weather', 'today')
        instance.store.invalidate.assert_not_called()
        instance.store.set.assert_not_called()
        instance.preview.assert_not_called()

    def test_template_is_available_to_ai_without_allowing_invented_temperatures(self):
        catalog = bot.templates()
        merged = bot.merge(catalog, {}, {'template': 'weather', 'values': []})
        self.assertIsNone(merged['asked_field'])
        with self.assertRaises(ValueError):
            bot.merge(catalog, {}, {'template': 'weather', 'values': [{'field': 'temperature_max', 'value': '30'}]})

    def test_weather_snapshot_renders_and_has_print_confirmation(self):
        with patch.dict(os.environ, ENV), patch.object(bot, 'weather_json', side_effect=[LOCATION, FORECAST]):
            values = bot.weather_forecast('tomorrow')
        with tempfile.TemporaryDirectory() as directory:
            instance = bot.Bot.__new__(bot.Bot)
            instance.catalog = bot.templates()
            instance.dry = True
            instance.store = bot.Store(Path(directory) / 'state.db')
            self.addCleanup(instance.store.db.close)
            instance.tg = Mock()
            instance.preview(1, 1, {'template': 'weather', 'weather': values})
            call = instance.tg.call_args
            self.assertTrue(call.kwargs['photo'].startswith(b'\x89PNG'))
            job = call.args[1]['reply_markup']['inline_keyboard'][0][0]['callback_data'].split(':')[1]
            self.assertEqual(instance.store.claim(job, 1), call.kwargs['photo'])


if __name__ == '__main__':
    unittest.main()
