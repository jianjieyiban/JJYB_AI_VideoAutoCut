# -*- coding: utf-8 -*-
"""
AI API
AI功能API路由
"""

import logging
import uuid
import threading
from flask import request, jsonify

logger = logging.getLogger(__name__)


def register_ai_routes(app, db_manager, task_service):
    """注册AI功能相关的API路由"""
    
    @app.route('/api/ai/tts', methods=['POST'])
    def ai_tts():
        """AI语音合成"""
        try:
            data = request.get_json()
            
            if 'text' not in data:
                return jsonify({'code': 1, 'msg': '参数错误：缺少text', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='tts',
                project_id=data.get('project_id'),
                input_data=data
            )
            
            threading.Thread(
                target=task_service.process_tts,
                args=(task_id, data),
                daemon=True
            ).start()
            
            return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.error(f'TTS处理失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/ai/asr', methods=['POST'])
    def ai_asr():
        """AI语音识别"""
        try:
            data = request.get_json()
            
            if 'audio_path' not in data:
                return jsonify({'code': 1, 'msg': '参数错误：缺少audio_path', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='asr',
                project_id=data.get('project_id'),
                input_data=data
            )
            
            threading.Thread(
                target=task_service.process_asr,
                args=(task_id, data),
                daemon=True
            ).start()
            
            return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.error(f'ASR处理失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/ai/scene_detect', methods=['POST'])
    def ai_scene_detect():
        """AI场景检测"""
        try:
            data = request.get_json()
            
            if 'video_path' not in data:
                return jsonify({'code': 1, 'msg': '参数错误：缺少video_path', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='scene_detect',
                project_id=data.get('project_id'),
                input_data=data
            )
            
            threading.Thread(
                target=task_service.process_scene_detect,
                args=(task_id, data),
                daemon=True
            ).start()
            
            return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.error(f'场景检测失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    logger.info('✅ AI功能API路由注册完成')
