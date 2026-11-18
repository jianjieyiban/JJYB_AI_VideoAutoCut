import json
import os
import tempfile
import unittest
import wave
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from backend.api import voiceover_api
from backend.services import voiceover_service
from backend.utils import file_utils

from backend.engine.asr_engine import ASREngine
from backend.services.voiceover_service import VoiceoverService
from backend.services.commentary_service import CommentaryService
from backend.engine.tts_engine import TTSEngine
from backend.engine.tts_provider import TTSRequest


class LanguageSettingsTests(unittest.TestCase):
    def test_asr_uses_global_language_when_not_explicitly_provided(self):
        state = type('State', (), {'user_settings': {'language': {'asr': 'en-US'}}})()
        engine = ASREngine.__new__(ASREngine)

        with patch('backend.core.global_state.get_global_state', return_value=state):
            self.assertEqual('en', engine._resolve_language(None))
            self.assertEqual('ja', engine._resolve_language('ja-JP'))

    def test_voiceover_uses_global_tts_language_for_default_voice(self):
        state = type('State', (), {'user_settings': {'language': {'tts': 'en-US'}}})()
        service = VoiceoverService.__new__(VoiceoverService)

        with patch('backend.core.global_state.get_global_state', return_value=state):
            self.assertEqual('en-US-JennyNeural', service._default_voice_id())
            self.assertEqual('zh-CN-XiaoxiaoNeural', service._default_voice_id('zh-CN'))

    def test_commentary_service_resolves_global_tts_voice(self):
        state = type('State', (), {'user_settings': {'language': {'tts': 'en-US'}}})()
        service = CommentaryService.__new__(CommentaryService)

        with patch('backend.core.global_state.get_global_state', return_value=state):
            self.assertEqual('en-US-JennyNeural', service._default_voice_id())

    def test_tts_engine_resolves_global_voice_when_voice_is_missing(self):
        state = type('State', (), {'user_settings': {'language': {'tts': 'en-US'}}})()
        engine = TTSEngine.__new__(TTSEngine)

        with patch('backend.core.global_state.get_global_state', return_value=state):
            self.assertEqual('en-US-JennyNeural', engine._resolve_voice(None))

    def test_tts_request_uses_global_language_when_not_explicit(self):
        state = type('State', (), {'user_settings': {'language': {'tts': 'en-US'}}})()

        with patch('backend.core.global_state.get_global_state', return_value=state):
            self.assertEqual('en-US', TTSRequest('hello', 'out.mp3').language)


class VoiceoverRegressionTests(unittest.TestCase):
    voice_id = 'zh-CN-XiaoxiaoNeural'

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        stack.enter_context(patch.object(voiceover_service, 'PROJECT_ROOT', self.root))
        stack.enter_context(patch.object(voiceover_api, 'PROJECT_ROOT', self.root))
        stack.enter_context(patch.object(voiceover_api, 'voiceover_service', None))
        engine = SimpleNamespace(available_engines=['edge-tts'], default_engine='edge-tts',
                                 synthesize=self.write_audio)
        stack.enter_context(patch.object(VoiceoverService, 'tts_engine', engine))
        self.service = VoiceoverService(None, Mock())
        app = Flask(__name__)
        voiceover_api.register_voiceover_routes(app, None, self.service)
        self.client = app.test_client()

    @staticmethod
    def write_audio(text, output_path, **kwargs):
        if text == 'fail':
            return False
        Path(output_path).write_bytes(text.encode())
        return True

    def write_wav(self):
        source = self.root / 'clone.wav'
        with wave.open(str(source), 'wb') as wav:
            wav.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            wav.writeframes(b'\x01\x00' * 4000)
        return source

    def test_batch_same_second_keeps_each_successful_file_and_failed_position(self):
        with patch.object(voiceover_service, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 1, 1)
            response = self.client.post('/api/voiceover/batch-generate', json={
                'texts': ['first', 'fail', 'last'], 'voice_config': {'voice_id': self.voice_id},
            })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['code'], 0)
        data = response.json['data']
        first, failed, last = data['audio_paths']
        self.assertIsNone(failed)
        self.assertEqual(data['audio_urls'], ['/' + first, None, '/' + last])
        self.assertEqual([entry and entry['engine_used'] for entry in data['syntheses']],
                         ['edge-tts', None, 'edge-tts'])
        self.assertNotEqual(first, last)
        self.assertEqual((self.root / first).read_bytes(), b'first')
        self.assertEqual((self.root / last).read_bytes(), b'last')

    def test_previews_for_same_voice_do_not_overwrite(self):
        first = self.service.preview_voice(self.voice_id, 'first')
        second = self.service.preview_voice(self.voice_id, 'second')
        self.assertNotEqual(first, second)
        self.assertEqual(Path(first).read_bytes(), b'first')
        self.assertEqual(Path(second).read_bytes(), b'second')

    def test_indextts2_generation_registers_the_actual_wav(self):
        source = self.write_wav()
        clone = SimpleNamespace(resolve_upload_audio=Mock(return_value=source),
                                generate=Mock(return_value={'output_path': source.name}))
        with patch('backend.services.local_voice_clone_service.local_voice_clone_service', clone), \
                patch.object(self.service, '_register_audio_to_project') as register:
            result = self.service.generate_voiceover('sample', {
                'voice_id': self.voice_id, 'engine': 'indextts2', 'reference_audio': 'ref.wav',
            }, project_id='project')
        path = Path(result)
        self.assertEqual(path.parent, self.root / 'output' / 'audios')
        self.assertEqual(path.suffix, '.wav')
        self.assertEqual(path.read_bytes(), source.read_bytes())
        register.assert_called_once_with('project', path, result.metadata)
        self.assertEqual(result.metadata['engine_used'], 'indextts2')

    def test_indextts2_clone_copies_to_distinct_paths_in_the_same_second(self):
        source = self.write_wav()
        clone = SimpleNamespace(resolve_upload_audio=Mock(return_value=source),
                                generate=Mock(return_value={'output_path': source.name}))
        with patch('backend.services.local_voice_clone_service.local_voice_clone_service', clone), \
                patch.object(voiceover_service, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 1, 1)
            first = self.service.generate_clone_voiceover('first', 'ref.wav', output_dir='copies')
            second = self.service.generate_clone_voiceover('second', 'ref.wav', output_dir='copies')
        self.assertNotEqual(first['audio_path'], second['audio_path'])

    def test_indextts2_preview_reports_wav_duration(self):
        source = self.write_wav()
        clone = SimpleNamespace(resolve_upload_audio=Mock(return_value=source),
                                generate=Mock(return_value={'output_path': source.name}))
        with patch('backend.services.local_voice_clone_service.local_voice_clone_service', clone):
            response = self.client.post('/api/voiceover/preview', json={
                'voice_id': self.voice_id, 'engine': 'indextts2', 'extra': {'reference_audio': 'ref.wav'},
            })
        self.assertEqual(response.status_code, 200)
        data = response.json['data']
        self.assertTrue(data['audio_path'].endswith('.wav'))
        self.assertEqual(data['duration_ms'], 500)
        self.assertEqual((self.root / data['audio_path']).read_bytes(), source.read_bytes())

    def test_preview_measures_duration_of_existing_wav(self):
        source = self.write_wav()
        with patch.object(self.service, 'preview_voice', return_value=str(source)):
            response = self.client.post('/api/voiceover/preview', json={'voice_id': self.voice_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['data']['duration_ms'], 500)

    def test_wav_previews_are_cleaned_when_expired(self):
        previews = self.root / 'output' / 'previews'
        previews.mkdir(parents=True)
        expired = previews / 'preview_expired.wav'
        expired.write_bytes(b'old')
        os.utime(expired, (100, 100))
        self.assertEqual(self.service.cleanup_preview_cache(), 1)
        self.assertFalse(expired.exists())

    def test_batch_progress_failure_does_not_add_a_result_slot(self):
        self.service.socketio.emit.side_effect = RuntimeError('progress unavailable')
        results = self.service.batch_generate_voiceovers(['first', 'last'], {'voice_id': self.voice_id})
        self.assertEqual(len(results), 2)
        self.assertEqual([Path(path).read_bytes() for path in results], [b'first', b'last'])

    def test_batch_all_failed_returns_error(self):
        response = self.client.post('/api/voiceover/batch-generate', json={
            'texts': ['fail', 'fail'], 'voice_config': {'voice_id': self.voice_id},
        })
        self.assertEqual(response.status_code, 500)
        self.assertNotEqual(response.json['code'], 0)
        self.assertEqual(response.json['data'], {
            'audio_paths': [None, None],
            'audio_urls': [None, None],
            'syntheses': [None, None],
        })

    def test_audio_duration_only_accepts_finite_positive_audio_stream_duration(self):
        source = self.write_wav()
        for streams, expected in [([], 0.0), ([{'duration': '0.5'}], 0.5),
                                  ([{'duration': 'nan'}, {'duration': 'inf'},
                                    {'duration': '-1'}, {'duration': '0'}], 0.0)]:
            with self.subTest(streams=streams), patch('subprocess.run') as probe:
                probe.return_value = SimpleNamespace(returncode=0, stdout=json.dumps({
                    'streams': streams, 'format': {'duration': '30'},
                }))
                self.assertEqual(file_utils.get_audio_duration_safe(str(source)), expected)
                self.assertIn('a', probe.call_args.args[0])

    def test_coqui_dispatch_passes_model_but_not_unsupported_voice_controls(self):
        engine = TTSEngine.__new__(TTSEngine)
        engine.available_engines = ['coqui']
        config = {'emotion_type': 'neutral'}
        calls = []

        def fake_coqui(text, output_path, model_name, advanced_config):
            calls.append((text, output_path, model_name, advanced_config))
            return True

        engine.synthesize_coqui = fake_coqui
        engine._set_last_error = Mock()
        engine._apply_post_processing = Mock(return_value=True)
        output = str(self.root / 'coqui.wav')
        self.assertTrue(engine.synthesize('sample', output, engine='coqui', voice=self.voice_id,
                                          rate='+10%', volume='+20%', pitch=2,
                                          model_name='local-model', advanced_config=config))
        self.assertEqual(calls, [('sample', output, 'local-model', config)])


if __name__ == '__main__':
    unittest.main()
