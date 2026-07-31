# -*- coding: utf-8 -*-
"""
Task API
任务管理API路由
"""

import logging
import uuid
import threading
from flask import request, jsonify

logger = logging.getLogger(__name__)


def register_task_routes(app, db_manager, task_service):
    """
    注册任务管理相关的API路由
    
    Args:
        app: Flask应用实例
        db_manager: 数据库管理器实例
        task_service: 任务服务实例
    """
    
    @app.route('/api/tasks', methods=['GET'])
    def get_tasks():
        """获取任务列表"""
        try:
            project_id = request.args.get('project_id')
            status = request.args.get('status')
            tasks = db_manager.get_tasks(project_id, status)
            return jsonify({'code': 0, 'msg': '获取成功', 'data': tasks})
        except Exception as e:
            logger.error(f'获取任务列表失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/tasks/<task_id>', methods=['GET'])
    def get_task(task_id):
        """获取任务详情"""
        try:
            task = db_manager.get_task(task_id)
            if task:
                return jsonify({'code': 0, 'msg': '获取成功', 'data': task})
            else:
                return jsonify({'code': 1, 'msg': '任务不存在', 'data': None}), 404
        except Exception as e:
            logger.error(f'获取任务详情失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/tasks', methods=['POST'])
    def create_task():
        """创建任务"""
        try:
            data = request.get_json()
            if not data or 'type' not in data:
                return jsonify({'code': 1, 'msg': '参数错误：缺少type', 'data': None}), 400
            
            task_id = str(uuid.uuid4())
            db_manager.create_task(
                task_id=task_id,
                task_type=data.get('type'),
                project_id=data.get('project_id'),
                input_data=data.get('input_data')
            )
            
            # 启动任务处理（异步）
            threading.Thread(
                target=task_service.process_task,
                args=(task_id, data.get('type'), data.get('input_data', {})),
                daemon=True
            ).start()
            
            return jsonify({
                'code': 0,
                'msg': '任务创建成功',
                'data': {'task_id': task_id}
            })
        except Exception as e:
            logger.error(f'创建任务失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500
    
    @app.route('/api/tasks/<task_id>/cancel', methods=['POST'])
    def cancel_task(task_id):
        """取消任务"""
        try:
            db_manager.update_task_status(task_id, 'cancelled')
            return jsonify({'code': 0, 'msg': '任务已取消', 'data': None})
        except Exception as e:
            logger.error(f'取消任务失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'取消失败: {str(e)}', 'data': None}), 500
    
    logger.info('✅ 任务管理API路由注册完成')
