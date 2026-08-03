# -*- coding: utf-8 -*-
"""通知中心 API。"""

from flask import Blueprint, jsonify, request


def create_notification_blueprint(db_manager):
    """创建使用现有数据库管理器的通知蓝图。"""
    blueprint = Blueprint('notifications', __name__)

    @blueprint.get('/api/notifications')
    def list_notifications():
        try:
            db_manager.sync_task_notifications()
            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'items': db_manager.list_notifications(),
                    'unread_count': db_manager.get_unread_notification_count()
                }
            })
        except Exception as exc:
            return jsonify({'code': 1, 'msg': f'获取失败: {exc}', 'data': None}), 500

    @blueprint.post('/api/notifications/read-all')
    def mark_all_notifications_read():
        try:
            db_manager.mark_all_notifications_read()
            return jsonify({
                'code': 0,
                'msg': '已全部标记为已读',
                'data': {'unread_count': db_manager.get_unread_notification_count()}
            })
        except Exception as exc:
            return jsonify({'code': 1, 'msg': f'标记失败: {exc}', 'data': None}), 500

    @blueprint.post('/api/notifications/read')
    def mark_notification_read():
        """按 source_id 单条标记已读。"""
        try:
            payload = request.get_json(silent=True) or {}
            source_id = payload.get('source_id') or ''
            if not source_id:
                return jsonify({'code': 1, 'msg': '缺少 source_id 参数', 'data': None}), 400
            db_manager.mark_notification_read_by_source(source_id)
            return jsonify({
                'code': 0,
                'msg': '已标记为已读',
                'data': {'unread_count': db_manager.get_unread_notification_count()}
            })
        except Exception as exc:
            return jsonify({'code': 1, 'msg': f'标记失败: {exc}', 'data': None}), 500

    @blueprint.post('/api/notifications/clear')
    def clear_notifications():
        """清空任务通知并阻止当前终态任务事件被同步回弹。"""
        try:
            unread_count = db_manager.clear_task_notifications()
            return jsonify({
                'code': 0,
                'msg': '通知已清空',
                'data': {'unread_count': unread_count}
            })
        except Exception as exc:
            return jsonify({'code': 1, 'msg': f'清空失败: {exc}', 'data': None}), 500

    return blueprint


def register_notification_routes(app, db_manager):
    """注册通知中心路由。"""
    app.register_blueprint(create_notification_blueprint(db_manager))
