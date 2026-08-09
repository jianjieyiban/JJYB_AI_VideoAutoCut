# -*- coding: utf-8 -*-
"""
Services Module
业务服务模块
"""

from importlib import import_module

__all__ = [
    'TaskService',
    'CommentaryService',
    'RemixService',
    'VoiceoverService'
]

_EXPORTS = {
    'TaskService': ('.task_service', 'TaskService'),
    'CommentaryService': ('.commentary_service', 'CommentaryService'),
    'RemixService': ('.remix_service', 'RemixService'),
    'VoiceoverService': ('.voiceover_service', 'VoiceoverService'),
}


def __getattr__(name):
    """Load each service on demand instead of importing the full media stack."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}') from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value
