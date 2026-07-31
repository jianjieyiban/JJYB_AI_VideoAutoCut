# -*- coding: utf-8 -*-
"""
API Module
API路由模块
"""

from .project_api import register_project_routes
from .task_api import register_task_routes
from .video_api import register_video_routes
from .ai_api import register_ai_routes
from .commentary_api import register_commentary_routes
from .remix_api import register_remix_routes
from .voiceover_api import register_voiceover_routes
from .local_voice_clone_api import register_local_voice_clone_routes
from .hardware_capability_api import register_hardware_capability_routes
from .notification_api import register_notification_routes
from .cover_api import register_cover_routes

__all__ = [
    'register_project_routes',
    'register_task_routes',
    'register_video_routes',
    'register_ai_routes',
    'register_commentary_routes',
    'register_remix_routes',
    'register_voiceover_routes',
    'register_local_voice_clone_routes',
    'register_hardware_capability_routes',
    'register_notification_routes',
    'register_cover_routes',
]
