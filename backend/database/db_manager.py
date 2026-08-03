# -*- coding: utf-8 -*-
"""
Database Manager
数据库管理器 - 完整版
负责所有数据库操作：项目管理、素材管理、任务管理
"""

import sqlite3
import json
import uuid
import logging
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """数据库管理器 - 完整版"""

    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径；默认从 config/config.yaml 的 database.path 读取
        """
        # 获取项目根目录
        self.base_dir = Path(__file__).parent.parent.parent
        # 1) 参数优先
        resolved = None
        if db_path:
            resolved = str((self.base_dir / db_path)) if not Path(db_path).is_absolute() else db_path
        else:
            # 2) 环境变量
            env_db = os.getenv('DB_PATH') or os.getenv('DATABASE_PATH')
            if env_db:
                resolved = str((self.base_dir / env_db)) if not Path(env_db).is_absolute() else env_db
            else:
                # 3) 配置文件 config/config.yaml
                try:
                    import yaml
                    cfg_path = self.base_dir / 'config' / 'config.yaml'
                    if cfg_path.exists():
                        with open(cfg_path, 'r', encoding='utf-8') as f:
                            cfg = yaml.safe_load(f) or {}
                        db_rel = (cfg.get('database') or {}).get('path')
                        if db_rel:
                            resolved = str(self.base_dir / db_rel)
                except Exception:
                    pass
        # 4) 回退默认
        self.db_path = resolved or str(self.base_dir / 'database' / 'jjyb_ai.db')

        # 确保数据库目录存在
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        # 初始化数据库
        self.app_start_time = time.time()
        self.init_database()

    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """初始化数据库表结构"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 创建项目表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'draft',
                    config TEXT,
                    thumbnail TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            # 确保 projects 表包含 result 字段（用于存储处理结果JSON）
            try:
                cursor.execute("PRAGMA table_info(projects)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'result' not in columns:
                    cursor.execute("ALTER TABLE projects ADD COLUMN result TEXT")
                    logger.info('✅ 已为 projects 表添加 result 字段')
                # 封面 URL：复用老的 thumbnail 字段，同时新增 cover_url 字段做语义化存储，二者双写
                if 'cover_url' not in columns:
                    try:
                        cursor.execute("ALTER TABLE projects ADD COLUMN cover_url TEXT")
                        logger.info('✅ 已为 projects 表添加 cover_url 字段')
                    except Exception as ex:
                        logger.warning(f'⚠️ 添加 projects.cover_url 字段失败（可能已存在）: {ex}')
                if 'thumbnail' not in columns:
                    try:
                        cursor.execute("ALTER TABLE projects ADD COLUMN thumbnail TEXT")
                        logger.info('✅ 已为 projects 表添加 thumbnail 字段')
                    except Exception as ex2:
                        logger.warning(f'⚠️ 添加 projects.thumbnail 字段失败（可能已存在）: {ex2}')
            except Exception as e:
                logger.warning(f'⚠️ 检查/添加 projects 兼容字段失败: {e}')

            # 创建素材表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    duration REAL,
                    metadata TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
            ''')

            # 创建任务表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    type TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    progress REAL DEFAULT 0,
                    input_data TEXT,
                    output_data TEXT,
                    error_message TEXT,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
                )
            ''')

            # 创建设置表（用于保存API配置等键值对）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建通知表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notifications (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT,
                    source_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    read_at TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_source_id
                ON notifications(source_id)
                WHERE source_id IS NOT NULL
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_notifications_created_at
                ON notifications(created_at DESC)
            ''')
            # 记录用户明确清空的任务事件，避免通知同步再次重建它们。
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notification_dismissals (
                    source_id TEXT PRIMARY KEY,
                    dismissed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_notification_dismissals_dismissed_at
                ON notification_dismissals(dismissed_at DESC)
            ''')
            # 旧版本可能写入展示性通知（source_id 为空或不属于任务）；
            # 只清理这类历史脏数据，真实任务事件通知一律长期保留，避免启动后
            # 已读/未读状态被重置导致红点反复出现。
            cursor.execute("DELETE FROM notifications WHERE source_id IS NULL OR source_id NOT LIKE 'task:%'")
            # 注意：不再执行 DELETE FROM notifications / DELETE FROM tasks(completed/failed)
            # 这些操作会造成"全部已读白标丢失、项目历史任务数据消失、用户真实统计被清空，
            # 与"数据真实、实时同步软件真实数据"目标相违背，故删除。

            conn.commit()
            logger.info('✅ 数据库初始化完成')

        except Exception as e:
            logger.error(f'❗ 数据库初始化失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 项目管理 ====================

    def create_project(self, name: str, project_type: str, description: str = '', template: str = None) -> Dict:
        """
        创建项目

        Args:
            name: 项目名称
            project_type: 项目类型（audio/commentary/mixed）
            description: 项目描述
            template: 模板名称

        Returns:
            创建的项目信息
        """
        project_id = str(uuid.uuid4())
        config = json.dumps({
            'template': template,
            'output_format': 'mp4',
            'quality': 'high'
        }, ensure_ascii=False)

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'INSERT INTO projects (id, name, type, description, config) VALUES (?, ?, ?, ?, ?)',
                (project_id, name, project_type, description, config)
            )
            conn.commit()
            logger.info(f'✅ 项目创建成功: {project_id}')

            return {
                'id': project_id,
                'name': name,
                'type': project_type,
                'description': description,
                'status': 'draft',
                'config': config
            }
        except Exception as e:
            logger.error(f'❗ 项目创建失败: {e}')
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_all_projects(self, project_type: str = None) -> List[Dict]:
        """
        获取所有项目

        Args:
            project_type: 可选，按类型筛选

        Returns:
            项目列表
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if project_type:
                cursor.execute(
                    'SELECT * FROM projects WHERE type = ? ORDER BY created_at DESC',
                    (project_type,)
                )
            else:
                cursor.execute('SELECT * FROM projects ORDER BY created_at DESC')

            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_project(self, project_id: str) -> Optional[Dict]:
        """
        获取项目详情

        Args:
            project_id: 项目ID

        Returns:
            项目信息（包含素材列表）
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT * FROM projects WHERE id = ?', (project_id,))
            row = cursor.fetchone()

            if row:
                project = dict(row)
                # 获取项目的素材
                cursor.execute('SELECT * FROM materials WHERE project_id = ?', (project_id,))
                project['materials'] = [dict(r) for r in cursor.fetchall()]
                return project
            return None
        finally:
            conn.close()

    def update_project(self, project_id: str, data: Dict) -> Optional[Dict]:
        """
        更新项目

        Args:
            project_id: 项目ID
            data: 要更新的数据

        Returns:
            更新后的项目信息
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            updates = []
            params = []

            for key in ['name', 'description', 'status', 'thumbnail', 'cover_url']:
                if key in data:
                    updates.append(f'{key} = ?')
                    params.append(data[key])
            # 双写兼容：如果只传了 cover_url 就同步写入 thumbnail；反之亦然，保证旧代码也能读到封面
            if 'cover_url' in data and 'thumbnail' not in data:
                updates.append('thumbnail = ?')
                params.append(data['cover_url'])
            if 'thumbnail' in data and 'cover_url' not in data:
                updates.append('cover_url = ?')
                params.append(data['thumbnail'])

            if 'config' in data:
                updates.append('config = ?')
                params.append(json.dumps(data['config'], ensure_ascii=False))
            if 'result' in data:
                updates.append('result = ?')
                params.append(json.dumps(data['result'], ensure_ascii=False))

            if updates:
                updates.append('updated_at = CURRENT_TIMESTAMP')
                params.append(project_id)
                cursor.execute(
                    f'UPDATE projects SET {", ".join(updates)} WHERE id = ?',
                    params
                )
                conn.commit()

            return self.get_project(project_id)
        finally:
            conn.close()

    def delete_project(self, project_id: str):
        """
        删除项目

        Args:
            project_id: 项目ID
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
            cursor.execute('DELETE FROM materials WHERE project_id = ?', (project_id,))
            conn.commit()
            logger.info(f'✅ 项目删除成功: {project_id}')
        finally:
            conn.close()

    # ==================== 素材管理 ====================

    def create_material(self, project_id: str, material_type: str, name: str,
                       path: str, size: int = 0, duration: float = 0,
                       metadata: Dict = None) -> Dict:
        """
        创建素材

        Args:
            project_id: 项目ID
            material_type: 素材类型（video/audio/image）
            name: 素材名称
            path: 文件路径
            size: 文件大小（字节）
            duration: 时长（秒）
            metadata: 元数据

        Returns:
            创建的素材信息
        """
        material_id = str(uuid.uuid4())
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''INSERT INTO materials (id, project_id, type, name, path, size, duration, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (material_id, project_id, material_type, name, path, size, duration,
                 json.dumps(metadata or {}, ensure_ascii=False))
            )
            conn.commit()

            return {
                'id': material_id,
                'project_id': project_id,
                'type': material_type,
                'name': name,
                'path': path,
                'size': size,
                'duration': duration
            }
        finally:
            conn.close()

    def get_materials(self, project_id: str = None, material_type: str = None) -> List[Dict]:
        """
        获取素材列表

        Args:
            project_id: 可选，按项目筛选
            material_type: 可选，按素材类型筛选

        Returns:
            素材列表
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if project_id and material_type:
                cursor.execute(
                    'SELECT * FROM materials WHERE project_id = ? AND type = ? ORDER BY created_at DESC',
                    (project_id, material_type)
                )
            elif project_id:
                cursor.execute(
                    'SELECT * FROM materials WHERE project_id = ? ORDER BY created_at DESC',
                    (project_id,)
                )
            elif material_type:
                cursor.execute(
                    'SELECT * FROM materials WHERE type = ? ORDER BY created_at DESC',
                    (material_type,)
                )
            else:
                cursor.execute('SELECT * FROM materials ORDER BY created_at DESC')

            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_project_material_stats(self, project_id: str) -> Dict:
        """
        获取项目素材统计信息（总大小、总时长）

        Args:
            project_id: 项目ID

        Returns:
            包含 total_size 和 total_duration 的字典
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'SELECT COALESCE(SUM(size), 0) as total_size, COALESCE(SUM(duration), 0) as total_duration FROM materials WHERE project_id = ?',
                (project_id,)
            )
            row = cursor.fetchone()
            return {
                'total_size': row['total_size'] or 0,
                'total_duration': row['total_duration'] or 0
            }
        finally:
            conn.close()

    # ==================== 任务管理 ====================

    def create_task(self, task_id: str, task_type: str, project_id: str = None,
                   input_data: Dict = None):
        """
        创建任务

        Args:
            task_id: 任务ID
            task_type: 任务类型
            project_id: 项目ID
            input_data: 输入数据
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'INSERT INTO tasks (id, project_id, type, input_data) VALUES (?, ?, ?, ?)',
                (task_id, project_id, task_type, json.dumps(input_data or {}, ensure_ascii=False))
            )
            conn.commit()
            logger.info(f'✅ 任务创建成功: {task_id}')
        finally:
            conn.close()

    def update_task_status(self, task_id: str, status: str,
                          output_data: Dict = None, error_message: str = None):
        """
        更新任务状态

        Args:
            task_id: 任务ID
            status: 状态（pending/running/completed/failed/cancelled）
            output_data: 输出数据
            error_message: 错误信息
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            updates = ['status = ?', 'updated_at = CURRENT_TIMESTAMP']
            params = [status]

            if status == 'running':
                updates.append('started_at = CURRENT_TIMESTAMP')
            elif status in ['completed', 'failed', 'cancelled']:
                updates.append('completed_at = CURRENT_TIMESTAMP')

            if output_data:
                updates.append('output_data = ?')
                params.append(json.dumps(output_data, ensure_ascii=False))

            if error_message:
                updates.append('error_message = ?')
                params.append(error_message)

            params.append(task_id)
            cursor.execute(
                f'UPDATE tasks SET {", ".join(updates)} WHERE id = ?',
                params
            )
            conn.commit()
        finally:
            conn.close()

    def update_task_progress(self, task_id: str, progress: float):
        """
        更新任务进度

        Args:
            task_id: 任务ID
            progress: 进度（0-100）
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'UPDATE tasks SET progress = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                (progress, task_id)
            )
            conn.commit()
        finally:
            conn.close()

    def get_tasks(self, project_id: str = None, status: str = None) -> List[Dict]:
        """
        获取任务列表

        Args:
            project_id: 可选，按项目筛选
            status: 可选，按状态筛选

        Returns:
            任务列表
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            query = 'SELECT * FROM tasks WHERE 1=1'
            params = []

            if project_id:
                query += ' AND project_id = ?'
                params.append(project_id)
            if status:
                query += ' AND status = ?'
                params.append(status)

            query += ' ORDER BY created_at DESC'
            cursor.execute(query, params)

            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict]:
        """
        获取任务详情

        Args:
            task_id: 任务ID

        Returns:
            任务信息
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    # ==================== 通知管理 ====================

    def add_notification(self, notification_type: str, title: str, content: str = '',
                         source_id: str = None, created_at: str = None) -> Optional[Dict]:
        """新增通知；source_id 存在时按其去重。"""
        notification_id = str(uuid.uuid4())
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            if source_id:
                cursor.execute('SELECT * FROM notifications WHERE source_id = ?', (source_id,))
                row = cursor.fetchone()
                if row:
                    return dict(row)

            if created_at:
                cursor.execute(
                    '''INSERT INTO notifications (id, type, title, content, source_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (notification_id, notification_type, title, content, source_id, created_at)
                )
            else:
                cursor.execute(
                    '''INSERT INTO notifications (id, type, title, content, source_id)
                       VALUES (?, ?, ?, ?, ?)''',
                    (notification_id, notification_type, title, content, source_id)
                )
            conn.commit()
            cursor.execute('SELECT * FROM notifications WHERE id = ?', (notification_id,))
            return dict(cursor.fetchone())
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_notifications(self, limit: int = 30) -> List[Dict]:
        """获取最近通知。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                '''SELECT * FROM notifications
                   WHERE source_id LIKE 'task:%'
                   ORDER BY created_at DESC, id DESC LIMIT ?''',
                (max(1, int(limit)),)
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def get_unread_notification_count(self) -> int:
        """获取未读通知数量。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM notifications WHERE read_at IS NULL AND source_id LIKE 'task:%'"
            )
            return cursor.fetchone()[0]
        finally:
            conn.close()

    def mark_all_notifications_read(self) -> None:
        """将所有未读任务通知标记为已读。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE notifications SET read_at = CURRENT_TIMESTAMP "
                "WHERE read_at IS NULL AND source_id LIKE 'task:%'"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_task_notifications(self) -> int:
        """清空任务通知，并持久记录当前终态任务事件以避免同步回弹。"""
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN')
            cursor.execute(
                "INSERT OR IGNORE INTO notification_dismissals (source_id) "
                "SELECT source_id FROM notifications WHERE source_id LIKE 'task:%'"
            )
            cursor.execute(
                '''INSERT OR IGNORE INTO notification_dismissals (source_id)
                   SELECT 'task:' || id || ':' || LOWER(status)
                   FROM tasks
                   WHERE LOWER(status) IN ('completed', 'failed', 'cancelled')'''
            )
            cursor.execute("DELETE FROM notifications WHERE source_id LIKE 'task:%'")
            cursor.execute(
                "SELECT COUNT(*) FROM notifications "
                "WHERE read_at IS NULL AND source_id LIKE 'task:%'"
            )
            unread_count = cursor.fetchone()[0]
            conn.commit()
            return unread_count
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_notification_read_by_source(self, source_id: str) -> None:
        """按任务 source_id 单条标记已读。"""
        if not source_id or not source_id.startswith('task:'):
            return
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE notifications SET read_at = CURRENT_TIMESTAMP "
                "WHERE source_id = ? AND source_id LIKE 'task:%' AND read_at IS NULL",
                (source_id,)
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def sync_task_notifications(self, limit: int = 30) -> None:
        """把最近已完成/失败/取消的真实任务事件同步为通知。

        与旧版 SQL 字符串切分不同，本实现在 Python 层解析 source_id 前缀，
        避免 task_id 本身包含冒号或空串导致的删除范围错判，确保"数据真实"。
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            # 1. 拿到当前所有 task 通知的 source_id
            cursor.execute(
                "SELECT id, source_id FROM notifications WHERE source_id LIKE 'task:%'"
            )
            existing = [dict(r) for r in cursor.fetchall()]

            # 2. 解析每个 source_id 对应的 task_id，并过滤掉 tasks 表中已经不存在的
            #    source_id 格式：task:<task_id>:<status>
            task_ids_alive: set = set()
            cursor.execute('SELECT id FROM tasks')
            for r in cursor.fetchall():
                d = dict(r)
                if d and d.get('id'):
                    task_ids_alive.add(str(d['id']))

            for row in existing:
                sid = row.get('source_id') or ''
                # task:<task_id>:<status> -> 去掉 task:，然后从右侧再按冒号切一次
                rest = sid[len('task:'):] if sid.startswith('task:') else ''
                # 从右往左找最后一个冒号，这样 task_id 本身即使带冒号也不会出错
                colon_idx = rest.rfind(':')
                task_id = rest[:colon_idx] if colon_idx >= 0 else rest
                if task_id and task_id not in task_ids_alive:
                    cursor.execute('DELETE FROM notifications WHERE id = ?', (row['id'],))

            # 3. 把最近的终态任务同步进来（completed/failed/cancelled）
            cursor.execute(
                '''SELECT id, project_id, type, status, output_data, error_message,
                          completed_at, updated_at, created_at
                   FROM tasks
                   WHERE LOWER(status) IN ('completed', 'failed', 'cancelled')
                   ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
                   LIMIT ?''',
                (max(1, int(limit)),)
            )
            tasks = [dict(row) for row in cursor.fetchall()]
            for task in tasks:
                status = str(task['status'] or '').lower() or 'task'
                task_id = str(task['id'] or '')
                if not task_id:
                    continue
                source_id = f'task:{task_id}:{status}'
                # 已清空的历史任务事件不应因同步而重新出现。
                cursor.execute(
                    'SELECT 1 FROM notification_dismissals WHERE source_id = ? LIMIT 1',
                    (source_id,)
                )
                if cursor.fetchone():
                    continue
                # 幂等：已存在就不 INSERT，保证已读标记不被覆盖
                cursor.execute('SELECT 1 FROM notifications WHERE source_id = ? LIMIT 1', (source_id,))
                if cursor.fetchone():
                    continue

                output_data = task.get('output_data')
                if isinstance(output_data, str):
                    try:
                        output_data = json.loads(output_data)
                    except (TypeError, ValueError):
                        output_data = None
                title = None
                if isinstance(output_data, dict):
                    title = output_data.get('title') or output_data.get('name') or output_data.get('task_name')
                title = title or task.get('type') or '任务通知'
                content = task.get('error_message') or ''
                created_at = task.get('completed_at') or task.get('updated_at') or task.get('created_at')

                cursor.execute(
                    '''INSERT INTO notifications
                       (id, type, title, content, source_id, created_at)
                       VALUES (?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))''',
                    (str(uuid.uuid4()), status, title, content, source_id, created_at)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 设置管理 ====================

    def save_settings(self, settings: Dict) -> bool:
        """
        保存设置

        Args:
            settings: 设置字典

        Returns:
            是否成功
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            for key, value in settings.items():
                # 将值转换为JSON字符串存储
                value_json = json.dumps(value) if not isinstance(value, str) else value

                cursor.execute('''
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                ''', (key, value_json))

            conn.commit()
            logger.info(f'✅ 保存设置成功: {len(settings)}项')
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f'❌ 保存设置失败: {e}')
            return False
        finally:
            conn.close()

    def get_settings(self) -> Dict:
        """
        获取所有设置

        Returns:
            设置字典
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT key, value FROM settings')
            settings = {}

            for row in cursor.fetchall():
                key = row['key']
                value = row['value']

                # 尝试解析JSON
                try:
                    settings[key] = json.loads(value)
                except:
                    settings[key] = value

            return settings
        finally:
            conn.close()

    def get_setting(self, key: str) -> Optional[any]:
        """
        获取单个设置项

        Args:
            key: 设置键

        Returns:
            设置值
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
            row = cursor.fetchone()

            if row:
                value = row['value']
                try:
                    return json.loads(value)
                except:
                    return value
            return None
        finally:
            conn.close()

    def update_setting(self, key: str, value: any) -> bool:
        """
        更新单个设置项

        Args:
            key: 设置键
            value: 设置值

        Returns:
            是否成功
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            value_json = json.dumps(value) if not isinstance(value, str) else value

            cursor.execute('''
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            ''', (key, value_json))

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f'❌ 更新设置失败: {e}')
            return False
        finally:
            conn.close()

    def save_api_config(self, config: Dict) -> bool:
        """
        保存API配置（敏感数据）

        Args:
            config: API配置字典

        Returns:
            是否成功
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            for key, value in config.items():
                # API配置以 api_ 前缀存储
                setting_key = f'api_{key}' if not key.startswith('api_') else key
                value_json = json.dumps(value) if not isinstance(value, str) else value

                cursor.execute('''
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = CURRENT_TIMESTAMP
                ''', (setting_key, value_json))

            conn.commit()
            logger.info(f'🔑 保存API配置成功: {len(config)}项')
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f'❌ 保存API配置失败: {e}')
            return False
        finally:
            conn.close()

    def get_api_config(self) -> Dict:
        """
        获取API配置

        Returns:
            API配置字典
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT key, value FROM settings WHERE key LIKE 'api_%'")
            config = {}

            for row in cursor.fetchall():
                key = row['key'].replace('api_', '', 1)  # 移除 api_ 前缀
                value = row['value']

                try:
                    config[key] = json.loads(value)
                except:
                    config[key] = value

            return config
        finally:
            conn.close()
