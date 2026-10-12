import unittest
from unittest.mock import patch

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


if __name__ == '__main__':
    unittest.main()
