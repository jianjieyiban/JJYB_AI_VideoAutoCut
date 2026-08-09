# -*- coding: utf-8 -*-
"""
Engine Module
处理引擎模块 - 包含视频、音频、TTS、ASR等处理引擎
"""

from importlib import import_module

__all__ = [
    'VideoProcessor',
    'AudioProcessor',
    'TTSEngine',
    'ASREngine',
    'SceneDetector'
]

_EXPORTS = {
    'VideoProcessor': ('.video_processor', 'VideoProcessor'),
    'AudioProcessor': ('.audio_processor', 'AudioProcessor'),
    'TTSEngine': ('.tts_engine', 'TTSEngine'),
    'ASREngine': ('.asr_engine', 'ASREngine'),
    'SceneDetector': ('.scene_detector', 'SceneDetector'),
}


def __getattr__(name):
    """Load engines only when requested so optional media dependencies stay optional."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}') from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
