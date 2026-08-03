#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : auto_clip_routes.py
@Author : AI Assistant
@Date   : 2025-11-10
@Desc   : 视频自动剪辑API路由
          提供视频自动剪辑的HTTP API接口
"""

import os
import uuid
import asyncio
import threading
from flask import Blueprint, request, jsonify
from loguru import logger
from typing import Dict, Any

# 导入核心引擎
from backend.engine.auto_clip_controller import AutoClipController, auto_clip_video


# 创建蓝图
auto_clip_bp = Blueprint('auto_clip', __name__, url_prefix='/api/auto-clip')


# 全局任务状态存储（生产环境应使用Redis等）
task_status = {}


@auto_clip_bp.route('/start', methods=['POST'])
def start_auto_clip():
    """
    启动视频自动剪辑任务

    请求体：
    {
        "video_path": "uploads/video.mp4",
        "bgm_path": "bgm/music.mp3",  // 可选
        "config": {
            "llm_api_key": "sk-xxx",
            "llm_model": "gpt-4-vision-preview",
            "tts_provider": "edge-tts",
            "tts_voice": "zh-CN-XiaoxiaoNeural",
            "frame_interval": 3.0,
            "voice_volume": 1.0,
            "bgm_volume": 0.3,
            "subtitle_enabled": true
        }
    }

    返回：
    {
        "code": 0,
        "task_id": "task_xxx",
        "message": "自动剪辑任务已创建"
    }
    """
    try:
        data = request.get_json()

        # 验证必需参数
        if not data or 'video_path' not in data:
            return jsonify({
                'code': 1,
                'message': '缺少必需参数: video_path'
            }), 400

        video_path = data['video_path']
        bgm_path = data.get('bgm_path')
        config = data.get('config', {})

        # 验证视频文件存在
        if not os.path.exists(video_path):
            return jsonify({
                'code': 1,
                'message': f'视频文件不存在: {video_path}'
            }), 404

        # 生成任务ID
        task_id = f"auto_clip_{uuid.uuid4().hex[:12]}"

        # 初始化任务状态
        task_status[task_id] = {
            'status': 'pending',
            'progress': 0,
            'current_step': 0,
            'total_steps': 5,
            'message': '任务已创建，等待执行...',
            'video_path': video_path,
            'output_path': None,
            'error': None
        }

        # 启动后台任务（在后台线程中运行事件循环）
        def _runner():
            try:
                asyncio.run(process_auto_clip_task(task_id, video_path, bgm_path, config))
            except Exception as e:
                logger.error(f"后台任务执行失败: {e}")
        threading.Thread(target=_runner, daemon=True).start()

        logger.info(f"✅ 自动剪辑任务已创建: {task_id}")

        return jsonify({
            'code': 0,
            'task_id': task_id,
            'message': '自动剪辑任务已创建'
        })

    except Exception as e:
        logger.error(f"❌ 创建自动剪辑任务失败: {e}")
        return jsonify({
            'code': 1,
            'message': f'创建任务失败: {str(e)}'
        }), 500


@auto_clip_bp.route('/status/<task_id>', methods=['GET'])
def get_task_status(task_id: str):
    """
    获取任务状态

    返回：
    {
        "code": 0,
        "task_id": "task_xxx",
        "status": "running",  // pending/running/completed/failed
        "progress": 60,
        "current_step": 3,
        "total_steps": 5,
        "message": "正在智能剪辑视频...",
        "output_path": null,  // 完成后才有值
        "error": null
    }
    """
    try:
        if task_id not in task_status:
            return jsonify({
                'code': 1,
                'message': f'任务不存在: {task_id}'
            }), 404

        status = task_status[task_id]

        return jsonify({
            'code': 0,
            'task_id': task_id,
            **status
        })

    except Exception as e:
        logger.error(f"❌ 获取任务状态失败: {e}")
        return jsonify({
            'code': 1,
            'message': f'获取状态失败: {str(e)}'
        }), 500


@auto_clip_bp.route('/list', methods=['GET'])
def list_tasks():
    """
    列出所有任务

    返回：
    {
        "code": 0,
        "tasks": [
            {
                "task_id": "task_xxx",
                "status": "completed",
                "progress": 100,
                "video_path": "...",
                "output_path": "..."
            }
        ]
    }
    """
    try:
        tasks = []
        for task_id, status in task_status.items():
            tasks.append({
                'task_id': task_id,
                **status
            })

        # 按创建时间倒序排列
        tasks.reverse()

        return jsonify({
            'code': 0,
            'tasks': tasks
        })

    except Exception as e:
        logger.error(f"❌ 列出任务失败: {e}")
        return jsonify({
            'code': 1,
            'message': f'列出任务失败: {str(e)}'
        }), 500


@auto_clip_bp.route('/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id: str):
    """
    取消任务

    返回：
    {
        "code": 0,
        "message": "任务已取消"
    }
    """
    try:
        if task_id not in task_status:
            return jsonify({
                'code': 1,
                'message': f'任务不存在: {task_id}'
            }), 404

        status = task_status[task_id]

        if status['status'] in ['completed', 'failed']:
            return jsonify({
                'code': 1,
                'message': '任务已结束，无法取消'
            }), 400

        # 更新状态为已取消
        status['status'] = 'cancelled'
        status['message'] = '任务已被用户取消'

        logger.info(f"⚠️ 任务已取消: {task_id}")

        return jsonify({
            'code': 0,
            'message': '任务已取消'
        })

    except Exception as e:
        logger.error(f"❌ 取消任务失败: {e}")
        return jsonify({
            'code': 1,
            'message': f'取消失败: {str(e)}'
        }), 500


async def process_auto_clip_task(
    task_id: str,
    video_path: str,
    bgm_path: str,
    config: Dict[str, Any]
):
    """
    处理自动剪辑任务（异步后台任务）

    Args:
        task_id: 任务ID
        video_path: 视频路径
        bgm_path: BGM路径
        config: 配置字典
    """
    try:
        logger.info(f"🎬 开始处理自动剪辑任务: {task_id}")

        # 更新状态为运行中
        task_status[task_id]['status'] = 'running'
        task_status[task_id]['message'] = '开始自动剪辑...'

        # 进度回调函数
        def progress_callback(step: int, total: int, message: str):
            task_status[task_id].update({
                'current_step': step,
                'total_steps': total,
                'progress': int((step / total) * 100),
                'message': message
            })
            logger.info(f"[{task_id}] [{step}/{total}] {message}")

        # 执行自动剪辑工作流
        output_path = await auto_clip_video(
            video_path=video_path,
            config=config,
            bgm_path=bgm_path,
            progress_callback=progress_callback
        )

        # 更新状态为完成
        task_status[task_id].update({
            'status': 'completed',
            'progress': 100,
            'current_step': 5,
            'message': '自动剪辑完成！',
            'output_path': output_path
        })

        logger.success(f"✅ 自动剪辑任务完成: {task_id} -> {output_path}")

    except Exception as e:
        logger.error(f"❌ 自动剪辑任务失败: {task_id} - {e}")

        # 更新状态为失败
        task_status[task_id].update({
            'status': 'failed',
            'message': '自动剪辑失败',
            'error': str(e)
        })


def register_auto_clip_routes(app):
    """
    注册自动剪辑路由到Flask应用

    Args:
        app: Flask应用实例
    """
    app.register_blueprint(auto_clip_bp)
    logger.info("✅ 自动剪辑API路由已注册")


# 用于直接导入使用
__all__ = [
    'auto_clip_bp',
    'register_auto_clip_routes',
    'start_auto_clip',
    'get_task_status',
    'list_tasks',
    'cancel_task'
]
