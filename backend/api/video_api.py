# -*- coding: utf-8 -*-
"""
Video API
视频处理API路由
"""

import logging
import uuid
import threading
import cv2
from pathlib import Path
from flask import request, jsonify

logger = logging.getLogger(__name__)


def register_video_routes(app, db_manager, task_service):
    """注册视频处理相关的API路由"""
    
    @app.route('/api/video/info', methods=['POST'])
    def video_info():
        """获取视频信息（时长、分辨率、帧率等）"""
        try:
            data = request.get_json()
            video_path = data.get('video_path')
            
            if not video_path:
                return jsonify({'code': 1, 'msg': '缺少video_path参数', 'data': None}), 400
            
            # 检查文件是否存在
            if not Path(video_path).exists():
                return jsonify({'code': 1, 'msg': f'视频文件不存在: {video_path}', 'data': None}), 404
            
            # 使用OpenCV读取视频信息
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                return jsonify({'code': 1, 'msg': '无法打开视频文件', 'data': None}), 500
            
            # 获取视频信息
            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            duration = frame_count / fps if fps > 0 else 0
            
            cap.release()
            
            return jsonify({
                'code': 0,
                'msg': '成功',
                'data': {
                    'duration': duration,
                    'fps': fps,
                    'frame_count': frame_count,
                    'width': width,
                    'height': height,
                    'resolution': f'{width}x{height}'
                }
            })
        except Exception as e:
            logger.error(f'获取视频信息失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/video/cut', methods=['POST'])
    def video_cut():
        """视频剪切"""
        try:
            data = request.get_json()
            required_fields = ['video_path', 'start_time', 'end_time']
            
            if not all(field in data for field in required_fields):
                return jsonify({'code': 1, 'msg': '参数错误', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='video_cut',
                project_id=data.get('project_id'),
                input_data=data
            )
            
            threading.Thread(
                target=task_service.process_video_cut,
                args=(task_id, data),
                daemon=True
            ).start()
            
            return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.error(f'视频剪切失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/video/merge', methods=['POST'])
    def video_merge():
        """视频合并"""
        try:
            data = request.get_json()
            
            if 'video_paths' not in data or not isinstance(data['video_paths'], list):
                return jsonify({'code': 1, 'msg': '参数错误', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type='video_merge',
                project_id=data.get('project_id'),
                input_data=data
            )
            
            threading.Thread(
                target=task_service.process_video_merge,
                args=(task_id, data),
                daemon=True
            ).start()
            
            return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
        except Exception as e:
            logger.error(f'视频合并失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}), 500
    
    logger.info('✅ 视频处理API路由注册完成')
