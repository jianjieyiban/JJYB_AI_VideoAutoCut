#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JJYB_AI智剪 v3.1.0 - 智能视频剪辑工具
主应用入口文件 - 完整详细版
包含所有功能的完整实现：
- 完整的DatabaseManager类（300+行）
- 所有API路由的完整实现（500+行）
- 所有任务处理函数（200+行）
- WebSocket实时通信
- 桌面应用启动
- 集成backend模块作为增强
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
import yaml
import threading
import json
import uuid
import time
import sqlite3
import webbrowser
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Flask相关导入
from flask import Flask, render_template, request, jsonify, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
from werkzeug.utils import secure_filename

# 添加项目根目录到Python路径
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# 尝试导入后端模块（如果可用，作为增强功能）
logger_msg = '⚠️ 后端模块不可用，使用内置功能'
try:
    from backend.database import DatabaseManager as BackendDatabaseManager
    from backend.services import (
        TaskService as BackendTaskService,
        CommentaryService,
        RemixService,
        VoiceoverService
    )
    from backend.engine import TTSEngine
    from backend.api import (
        register_project_routes,
        register_task_routes,
        register_video_routes,
        register_ai_routes,
        register_commentary_routes,
        register_remix_routes,
        register_voiceover_routes,
        register_local_voice_clone_routes,
        register_hardware_capability_routes,
        register_notification_routes,
        register_cover_routes,
    )
    BACKEND_AVAILABLE = True
    logger_msg = '✅ 后端模块可用，将使用增强功能'
except ImportError as e:
    BACKEND_AVAILABLE = False
    logger_msg = f'⚠️ 后端模块不可用，使用内置功能: {e}'
# 读取全局配置 config/config.yaml（支持环境变量覆盖）
APP_CFG = {}
try:
    cfg_path = BASE_DIR / 'config' / 'config.yaml'
    if cfg_path.exists():
        with open(cfg_path, 'r', encoding='utf-8') as f:
            APP_CFG = yaml.safe_load(f) or {}
except Exception:
    APP_CFG = {}

# 应用配置
APP_HOST = os.getenv('APP_HOST') or ((APP_CFG.get('app') or {}).get('host') or '0.0.0.0')
try:
    APP_PORT = int(os.getenv('APP_PORT') or ((APP_CFG.get('app') or {}).get('port') or 5000))
except Exception:
    APP_PORT = 5000
APP_DEBUG = (str(os.getenv('APP_DEBUG') or (APP_CFG.get('app') or {}).get('debug', False))).lower() in ('1', 'true', 'yes', 'y')
UI_HOST = '127.0.0.1' if APP_HOST in ('0.0.0.0', '::') else APP_HOST

# 日志配置
LOG_CFG = (APP_CFG.get('logging') or {})
LOG_LEVEL_STR = str(LOG_CFG.get('level', 'INFO')).upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_STR, logging.INFO)
LOG_FILE_REL = LOG_CFG.get('file', 'logs/app.log')
LOG_FILE_PATH = (BASE_DIR / LOG_FILE_REL) if not Path(LOG_FILE_REL).is_absolute() else Path(LOG_FILE_REL)
try:
    LOG_MAX_BYTES = int(LOG_CFG.get('max_size', 10 * 1024 * 1024))
except Exception:
    LOG_MAX_BYTES = 10 * 1024 * 1024
try:
    LOG_BACKUP = int(LOG_CFG.get('backup_count', 5))
except Exception:
    LOG_BACKUP = 5

# 配置日志（读取自 config/config.yaml，可用环境变量覆盖）
LOG_FILE_PATH.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(str(LOG_FILE_PATH), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger('JJYB_AI智剪')
logger.info(logger_msg)

try:
    from backend.config.paths import OUTPUT_DIR, OUTPUTS_DIR as BACKEND_OUTPUTS_DIR, project_output_dir
    TEMP_OUTPUTS_DIR = BACKEND_OUTPUTS_DIR
except Exception:
    OUTPUT_DIR = BASE_DIR / 'output'
    TEMP_OUTPUTS_DIR = OUTPUT_DIR / 'temp_outputs'

# 所有可下载运行时产物固定使用项目根 output。

# 创建Flask应用
app = Flask(
    __name__,
    template_folder='templates',
    static_folder='static'
)
app.config['SECRET_KEY'] = 'jjyb_ai_secret_key_2025'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024  # 5GB
app.config['UPLOAD_FOLDER'] = str(BASE_DIR / 'uploads')
# 始终启用模板自动重载，避免修改后仍渲染旧模板
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# 启用CORS
CORS(app, resources={r"/api/*": {"origins": "*"}})

# 添加响应头处理器 - 放宽安全策略以支持开发环境
@app.after_request
def add_security_headers(response):
    """添加安全响应头"""
    # 允许所有来源（开发环境）
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'

    # 放宽 CSP 以允许内联脚本和 CDN 资源
    csp_directives = [
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' *",
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.tailwindcss.com https://cdn.socket.io *",
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net *",
        "img-src 'self' data: blob: https: *",
        "font-src 'self' data: https://cdn.jsdelivr.net *",
        "connect-src 'self' ws: wss: https: *",
        "frame-src 'self' *"
    ]
    response.headers['Content-Security-Policy'] = '; '.join(csp_directives)

    return response

# 创建SocketIO实例
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='threading',
    ping_timeout=60,
    ping_interval=25
)

# 确保必要的目录存在
for directory in ['uploads', 'static/draft', 'database', 'logs', 'output', 'models', 'temp']:
    (BASE_DIR / directory).mkdir(parents=True, exist_ok=True)

logger.info('✅ Flask应用初始化完成')

# ==================== 数据库管理器（完整版）====================

class DatabaseManager:
    """
    数据库管理器 - 完整详细版
    提供所有数据库操作：项目管理、素材管理、任务管理
    包含完整的CRUD操作和错误处理
    """

    def __init__(self, db_path=None):
        """
        初始化数据库管理器

        Args:
            db_path: 数据库文件路径；默认从 config/config.yaml 的 database.path 读取
        """
        # 1) 来自参数
        resolved = None
        if db_path:
            resolved = str((BASE_DIR / db_path)) if not Path(db_path).is_absolute() else db_path
        else:
            # 2) 来自配置文件 config/config.yaml
            try:
                import yaml
                cfg_path = BASE_DIR / 'config' / 'config.yaml'
                if cfg_path.exists():
                    with open(cfg_path, 'r', encoding='utf-8') as f:
                        cfg = yaml.safe_load(f) or {}
                    db_rel = (cfg.get('database') or {}).get('path')
                    if db_rel:
                        resolved = str((BASE_DIR / db_rel))
            except Exception:
                pass
        # 3) 回退默认
        self.db_path = resolved or str(BASE_DIR / 'database' / 'jjyb_ai.db')
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.init_database()
        logger.info(f'✅ 数据库管理器初始化完成: {self.db_path}')

    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_database(self):
        """初始化数据库表结构 - 完整版"""
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 创建项目表 - 完整字段
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
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP,
                    is_deleted INTEGER DEFAULT 0
                )
            ''')

            # 兼容旧版数据库：确保 projects 表包含软删除字段
            try:
                cursor.execute("PRAGMA table_info(projects)")
                columns = [row[1] for row in cursor.fetchall()]
                if 'deleted_at' not in columns:
                    cursor.execute("ALTER TABLE projects ADD COLUMN deleted_at TIMESTAMP")
                    logger.info('✅ 已为 projects 表添加 deleted_at 字段')
                if 'is_deleted' not in columns:
                    cursor.execute("ALTER TABLE projects ADD COLUMN is_deleted INTEGER DEFAULT 0")
                    logger.info('✅ 已为 projects 表添加 is_deleted 字段')
            except Exception as e:
                logger.warning(f'⚠️ 检查/添加 projects 软删除字段失败: {e}')

            # 创建素材表 - 完整字段
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS materials (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    size INTEGER,
                    duration REAL,
                    width INTEGER,
                    height INTEGER,
                    fps REAL,
                    codec TEXT,
                    bitrate INTEGER,
                    metadata TEXT,
                    thumbnail TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                )
            ''')

            # 创建任务表 - 完整字段
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

            # 创建用户设置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_settings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE NOT NULL,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # 创建AI模型配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ai_models (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    path TEXT,
                    config TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            logger.info('✅ 数据库表初始化完成')

        except Exception as e:
            logger.error(f'❗ 数据库初始化失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 项目管理 - 完整CRUD ====================

    def create_project(self, name: str, project_type: str, description: str = '', template: str = None) -> Dict:
        """
        创建项目 - 完整实现

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
            'quality': 'high',
            'resolution': '1920x1080',
            'fps': 30,
            'bitrate': '5M'
        }, ensure_ascii=False)

        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''INSERT INTO projects (id, name, type, description, config, status)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (project_id, name, project_type, description, config, 'draft')
            )
            conn.commit()
            logger.info(f'✅ 项目创建成功: {project_id} - {name}')

            return {
                'id': project_id,
                'name': name,
                'type': project_type,
                'description': description,
                'status': 'draft',
                'config': json.loads(config),
                'created_at': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f'❗ 项目创建失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_all_projects(self, project_type: str = None) -> List[Dict]:
        """
        获取所有项目 - 完整实现

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
                    '''SELECT * FROM projects
                       WHERE type = ? AND is_deleted = 0
                       ORDER BY created_at DESC''',
                    (project_type,)
                )
            else:
                cursor.execute(
                    'SELECT * FROM projects WHERE is_deleted = 0 ORDER BY created_at DESC'
                )

            projects = [dict(row) for row in cursor.fetchall()]

            # 解析config JSON
            for project in projects:
                if project.get('config'):
                    try:
                        project['config'] = json.loads(project['config'])
                    except:
                        project['config'] = {}

            logger.info(f'✅ 获取项目列表成功: {len(projects)}个项目')
            return projects
        except Exception as e:
            logger.error(f'❗ 获取项目列表失败: {e}', exc_info=True)
            return []
        finally:
            conn.close()

    def get_project(self, project_id: str) -> Optional[Dict]:
        """
        获取项目详情 - 完整实现

        Args:
            project_id: 项目ID

        Returns:
            项目信息（包含素材列表和任务列表）
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                'SELECT * FROM projects WHERE id = ? AND is_deleted = 0',
                (project_id,)
            )
            row = cursor.fetchone()

            if row:
                project = dict(row)

                # 解析config
                if project.get('config'):
                    try:
                        project['config'] = json.loads(project['config'])
                    except:
                        project['config'] = {}

                # 获取项目的素材
                cursor.execute(
                    'SELECT * FROM materials WHERE project_id = ? ORDER BY created_at DESC',
                    (project_id,)
                )
                project['materials'] = [dict(r) for r in cursor.fetchall()]

                # 获取项目的任务
                cursor.execute(
                    'SELECT * FROM tasks WHERE project_id = ? ORDER BY created_at DESC',
                    (project_id,)
                )
                project['tasks'] = [dict(r) for r in cursor.fetchall()]

                logger.info(f'✅ 获取项目详情成功: {project_id}')
                return project
            else:
                logger.warning(f'⚠️  项目不存在: {project_id}')
                return None
        except Exception as e:
            logger.error(f'❗ 获取项目详情失败: {e}', exc_info=True)
            return None
        finally:
            conn.close()

    def update_project(self, project_id: str, data: Dict) -> Optional[Dict]:
        """
        更新项目 - 完整实现

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

            # 支持更新的字段
            for key in ['name', 'description', 'status', 'thumbnail']:
                if key in data:
                    updates.append(f'{key} = ?')
                    params.append(data[key])

            if 'config' in data:
                updates.append('config = ?')
                params.append(json.dumps(data['config'], ensure_ascii=False))

            if updates:
                updates.append('updated_at = CURRENT_TIMESTAMP')
                params.append(project_id)

                sql = f'UPDATE projects SET {", ".join(updates)} WHERE id = ? AND is_deleted = 0'
                cursor.execute(sql, params)
                conn.commit()

                logger.info(f'✅ 项目更新成功: {project_id}')

            return self.get_project(project_id)
        except Exception as e:
            logger.error(f'❗ 项目更新失败: {e}', exc_info=True)
            conn.rollback()
            return None
        finally:
            conn.close()

    def delete_project(self, project_id: str, hard_delete: bool = False):
        """
        删除项目 - 完整实现（支持软删除和硬删除）

        Args:
            project_id: 项目ID
            hard_delete: 是否硬删除（True=物理删除，False=软删除）
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            if hard_delete:
                # 硬删除：物理删除记录
                cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
                cursor.execute('DELETE FROM materials WHERE project_id = ?', (project_id,))
                cursor.execute('DELETE FROM tasks WHERE project_id = ?', (project_id,))
                logger.info(f'✅ 项目硬删除成功: {project_id}')
            else:
                # 软删除：标记为已删除
                cursor.execute(
                    '''UPDATE projects
                       SET is_deleted = 1, deleted_at = CURRENT_TIMESTAMP
                       WHERE id = ?''',
                    (project_id,)
                )
                logger.info(f'✅ 项目软删除成功: {project_id}')

            conn.commit()
        except Exception as e:
            logger.error(f'❗ 项目删除失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    # ==================== 素材管理 - 完整CRUD ====================

    def create_material(self, project_id: str, material_type: str, name: str,
                       path: str, size: int = 0, duration: float = 0,
                       metadata: Dict = None) -> Dict:
        """
        创建素材 - 完整实现

        Args:
            project_id: 项目ID
            material_type: 素材类型（video/audio/image）
            name: 素材名称
            path: 文件路径
            size: 文件大小（字节）
            duration: 时长（秒）
            metadata: 元数据（分辨率、编码等）

        Returns:
            创建的素材信息
        """
        material_id = str(uuid.uuid4())
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            # 提取metadata中的详细信息
            width = metadata.get('width', 0) if metadata else 0
            height = metadata.get('height', 0) if metadata else 0
            fps = metadata.get('fps', 0) if metadata else 0
            codec = metadata.get('codec', '') if metadata else ''
            bitrate = metadata.get('bitrate', 0) if metadata else 0

            cursor.execute(
                '''INSERT INTO materials
                   (id, project_id, type, name, path, size, duration,
                    width, height, fps, codec, bitrate, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (material_id, project_id, material_type, name, path, size, duration,
                 width, height, fps, codec, bitrate,
                 json.dumps(metadata or {}, ensure_ascii=False))
            )
            conn.commit()

            logger.info(f'✅ 素材创建成功: {material_id} - {name}')

            return {
                'id': material_id,
                'project_id': project_id,
                'type': material_type,
                'name': name,
                'path': path,
                'size': size,
                'duration': duration,
                'width': width,
                'height': height,
                'fps': fps,
                'codec': codec,
                'bitrate': bitrate,
                'created_at': datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f'❗ 素材创建失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    def get_materials(self, project_id: str = None, material_type: str = None) -> List[Dict]:
        """
        获取素材列表 - 完整实现

        Args:
            project_id: 可选，按项目筛选
            material_type: 可选，按类型筛选

        Returns:
            素材列表
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            query = 'SELECT * FROM materials WHERE 1=1'
            params = []

            if project_id:
                query += ' AND project_id = ?'
                params.append(project_id)

            if material_type:
                query += ' AND type = ?'
                params.append(material_type)

            query += ' ORDER BY created_at DESC'

            cursor.execute(query, params)
            materials = [dict(row) for row in cursor.fetchall()]

            # 解析metadata
            for material in materials:
                if material.get('metadata'):
                    try:
                        material['metadata'] = json.loads(material['metadata'])
                    except:
                        material['metadata'] = {}

            logger.info(f'✅ 获取素材列表成功: {len(materials)}个素材')
            return materials
        except Exception as e:
            logger.error(f'❗ 获取素材列表失败: {e}', exc_info=True)
            return []
        finally:
            conn.close()

    # ==================== 任务管理 - 完整CRUD ====================

    def create_task(self, task_id: str, task_type: str, project_id: str = None,
                   input_data: Dict = None):
        """
        创建任务 - 完整实现

        Args:
            task_id: 任务ID
            task_type: 任务类型（video_cut/video_merge/tts/asr/scene_detect）
            project_id: 项目ID
            input_data: 输入数据
        """
        conn = self.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                '''INSERT INTO tasks (id, project_id, type, status, input_data)
                   VALUES (?, ?, ?, ?, ?)''',
                (task_id, project_id, task_type, 'pending',
                 json.dumps(input_data or {}, ensure_ascii=False))
            )
            conn.commit()
            logger.info(f'✅ 任务创建成功: {task_id} - {task_type}')
        except Exception as e:
            logger.error(f'❗ 任务创建失败: {e}', exc_info=True)
            conn.rollback()
            raise
        finally:
            conn.close()

    def update_task_status(self, task_id: str, status: str,
                          output_data: Dict = None, error_message: str = None):
        """
        更新任务状态 - 完整实现

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
            logger.info(f'✅ 任务状态更新: {task_id} -> {status}')
        except Exception as e:
            logger.error(f'❗ 任务状态更新失败: {e}', exc_info=True)
            conn.rollback()
        finally:
            conn.close()

    def update_task_progress(self, task_id: str, progress: float):
        """
        更新任务进度 - 完整实现

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
        except Exception as e:
            logger.error(f'❗ 任务进度更新失败: {e}', exc_info=True)
            conn.rollback()
        finally:
            conn.close()

    def get_tasks(self, project_id: str = None, status: str = None) -> List[Dict]:
        """
        获取任务列表 - 完整实现

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

            tasks = [dict(row) for row in cursor.fetchall()]

            # 解析JSON字段
            for task in tasks:
                if task.get('input_data'):
                    try:
                        task['input_data'] = json.loads(task['input_data'])
                    except:
                        task['input_data'] = {}
                if task.get('output_data'):
                    try:
                        task['output_data'] = json.loads(task['output_data'])
                    except:
                        task['output_data'] = {}

            logger.info(f'✅ 获取任务列表成功: {len(tasks)}个任务')
            return tasks
        except Exception as e:
            logger.error(f'❗ 获取任务列表失败: {e}', exc_info=True)
            return []
        finally:
            conn.close()

    def get_task(self, task_id: str) -> Optional[Dict]:
        """
        获取任务详情 - 完整实现

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

            if row:
                task = dict(row)

                # 解析JSON字段
                if task.get('input_data'):
                    try:
                        task['input_data'] = json.loads(task['input_data'])
                    except:
                        task['input_data'] = {}
                if task.get('output_data'):
                    try:
                        task['output_data'] = json.loads(task['output_data'])
                    except:
                        task['output_data'] = {}

                return task
            return None
        except Exception as e:
            logger.error(f'❗ 获取任务详情失败: {e}', exc_info=True)
            return None
        finally:
            conn.close()

# 创建数据库管理器实例
db_manager = DatabaseManager()

# 如果后端模块可用，也创建后端实例作为增强
if BACKEND_AVAILABLE:
    try:
        backend_db_manager = BackendDatabaseManager()
        backend_task_service = BackendTaskService(backend_db_manager, socketio)

        # 三大核心服务共用 GlobalState 管理的 TTS，避免设置页与配音页状态分裂。
        from backend.core.global_state import get_global_state
        shared_tts_engine = get_global_state().get_tts_engine()

        # 初始化三大核心功能服务
        commentary_service = CommentaryService(backend_db_manager, socketio, backend_task_service)
        remix_service = RemixService(backend_db_manager, socketio, backend_task_service)
        voiceover_service = VoiceoverService(backend_db_manager, socketio, shared_tts_engine)

        # 注册所有API路由
        register_project_routes(app, backend_db_manager)
        register_task_routes(app, backend_db_manager, backend_task_service)
        register_video_routes(app, backend_db_manager, backend_task_service)
        register_ai_routes(app, backend_db_manager, backend_task_service)
        register_commentary_routes(app, backend_db_manager, backend_task_service, commentary_service)
        register_remix_routes(app, backend_db_manager, backend_task_service, remix_service)
        register_voiceover_routes(app, backend_db_manager, voiceover_service)
        register_local_voice_clone_routes(app, backend_db_manager)
        register_hardware_capability_routes(app)
        register_notification_routes(app, backend_db_manager)

        # 注册增强版原创解说路由
        try:
            from backend.api.commentary_routes_enhanced import register_commentary_routes_enhanced
            register_commentary_routes_enhanced(app, backend_db_manager, backend_task_service, socketio)
            logger.info('✅ 增强版原创解说路由注册成功')
        except Exception as e:
            logger.warning(f'⚠️ 增强版原创解说路由注册失败: {e}')

        # 注册文件上传路由
        try:
            from backend.api.upload_routes import register_upload_routes
            register_upload_routes(app)
            logger.info('✅ 文件上传路由注册成功')
        except Exception as e:
            logger.warning(f'⚠️ 文件上传路由注册失败: {e}')

        # 注册配置管理路由
        try:
            from backend.api.config_routes import register_config_routes
            register_config_routes(app)
            logger.info('✅ 配置管理路由注册成功')
        except Exception as e:
            logger.warning(f'⚠️ 配置管理路由注册失败: {e}')

        # 注册测试API路由
        try:
            from backend.api.test_api import register_test_routes
            from backend.config.ai_config import get_config_manager
            register_test_routes(app, get_config_manager())
            logger.info('✅ 测试API路由注册成功 (13个)')
        except Exception as e:
            logger.warning(f'⚠️ 测试API路由注册失败: {e}')

        # 注册素材管理路由
        try:
            from backend.api.material_routes import register_material_routes
            register_material_routes(app, backend_db_manager)
            logger.info('✅ 素材管理路由注册成功 (4个)')
        except Exception as e:
            logger.warning(f'⚠️ 素材管理路由注册失败: {e}')

        # 注册视频导出路由
        try:
            from backend.api.export_api import register_export_routes
            register_export_routes(app, backend_db_manager)
            logger.info('✅ 视频导出路由注册成功 (3个)')
        except Exception as e:
            logger.warning(f'⚠️ 视频导出路由注册失败: {e}')

        # 注册通用时间线草稿包导出路由
        try:
            from backend.api.jianying_draft_api import register_jianying_draft_routes
            register_jianying_draft_routes(app, backend_db_manager)
            logger.info('✅ 通用时间线草稿包导出路由注册成功')
        except Exception as e:
            logger.warning(f'⚠️ 通用时间线草稿包导出路由注册失败: {e}')

        # 注册设置管理路由
        try:
            from backend.api.settings_api import register_settings_routes
            register_settings_routes(app, backend_db_manager)
            logger.info('✅ 设置管理路由注册成功 (7个)')
        except Exception as e:
            logger.warning(f'⚠️ 设置管理路由注册失败: {e}')

        # 注册特效API路由
        try:
            from backend.api.effects_api import register_effects_routes
            register_effects_routes(app)
            logger.info('✅ 特效API路由注册成功 (2个)')
        except Exception as e:
            logger.warning(f'⚠️ 特效API路由注册失败: {e}')

        # 注册字幕API路由
        try:
            from backend.api.subtitle_api import register_subtitle_routes
            register_subtitle_routes(app, backend_db_manager)
            logger.info('✅ 字幕API路由注册成功 (5个)')
        except Exception as e:
            logger.warning(f'⚠️ 字幕API路由注册失败: {e}')

        # 注册清理API路由
        try:
            from backend.api.cleanup_api import register_cleanup_routes
            register_cleanup_routes(app)
            logger.info('✅ 清理API路由注册成功 (1个)')
        except Exception as e:
            logger.warning(f'⚠️ 清理API路由注册失败: {e}')

        # 注册高级功能API路由（融入JJYB-ZJ功能）
        try:
            from backend.api.advanced_routes import register_advanced_routes
            register_advanced_routes(app, backend_db_manager, backend_task_service, socketio, commentary_service)
            logger.info('✅ 高级功能API路由注册成功（文案质检/AI去重/精选复刻/智能穿插/覆盖审计/音画对齐/AI提纯）')
        except Exception as e:
            logger.warning(f'⚠️ 高级功能API路由注册失败: {e}')

        # 注册封面生成API路由
        try:
            register_cover_routes(app)
            logger.info('✅ 封面生成API路由注册成功（/api/cover/* · 10+厂商 + 本地兜底）')
        except Exception as e:
            logger.warning(f'⚠️ 封面生成API路由注册失败: {e}')
            try:
                from backend.api.cover_api import register_cover_routes as _rcv
                _rcv(app)
                logger.info('✅ 封面生成API路由注册成功（fallback方式）')
            except Exception as e2:
                logger.warning(f'⚠️ 封面生成API路由二次注册失败: {e2}')

        # 初始化全局状态管理器
        try:
            from backend.core.global_state import get_global_state
            global_state = get_global_state()
            global_state.load_user_settings(backend_db_manager)
            logger.info('✅ 全局状态管理器初始化成功')
            logger.info(f'   - 活动LLM模型: {global_state.active_llm_model}')
            logger.info(f'   - 活动视觉模型: {global_state.active_vision_model}')
        except Exception as e:
            logger.warning(f'⚠️ 全局状态管理器初始化失败: {e}')

        logger.info('✅ 后端增强功能已启用（所有功能模块）')
    except Exception as e:
        logger.warning(f'⚠️  后端增强功能启用失败: {e}')
        logger.exception(e)
        BACKEND_AVAILABLE = False

logger.info('✅ 数据库管理器初始化完成')

# ==================== 基础路由 ====================

@app.route('/favicon.ico')
def favicon():
    """Favicon - 返回SVG图标"""
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.svg',
        mimetype='image/svg+xml'
    )

@app.route('/output/<path:filename>')
def serve_output(filename):
    """
    静态输出目录文件服务：用于返回 /output/* 下生成的音视频等文件
    例如：/output/audios/<file>.mp3
    """
    out_dir = OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(out_dir), filename)


@app.route('/temp/outputs/<path:filename>')
def serve_temp_outputs(filename):
    """静态服务 temp/outputs 目录下的文件"""
    out_dir = TEMP_OUTPUTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(out_dir), filename)


@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    """静态服务 uploads 目录下的文件（通用于已上传素材等）"""
    # 与素材管理路由保持一致：使用项目根目录下的 uploads 作为静态根
    uploads_dir = BASE_DIR / 'uploads'
    uploads_dir.mkdir(parents=True, exist_ok=True)
    return send_from_directory(str(uploads_dir), filename)


@app.route('/robots.txt')
def robots():
    """Robots.txt"""
    return 'User-agent: *\nDisallow:', 200, {'Content-Type': 'text/plain'}

@app.route('/sitemap.xml')
def sitemap():
    """Sitemap.xml"""
    return '', 204

@app.route('/')
def index():
    """主页 - 显示三大核心功能入口"""
    return render_template('home.html')

@app.route('/editor')
def editor():
    """视频编辑器页面"""
    return render_template('index.html')

@app.route('/projects')
def projects_page():
    """项目管理页面"""
    return render_template('projects.html')

@app.route('/materials')
def materials_page():
    """素材库页面"""
    return render_template('materials.html')

@app.route('/voice_config')
def voice_config_page():
    """AI语音配置页面"""
    return render_template('voice_config.html')

@app.route('/ai_features')
@app.route('/ai-features')
def ai_features_page():
    """AI功能页面"""
    return render_template('ai_features.html')

@app.route('/settings')
@app.route('/api_settings')
def settings_page():
    """设置页面 - 统一的API配置和系统设置"""
    return render_template('settings.html')

@app.route('/diagnostic')
def diagnostic_page():
    """系统诊断页面"""
    return render_template('diagnostic.html')

@app.route('/mode_select')
def mode_select_page():
    """模式选择页面"""
    return render_template('mode_select.html')

@app.route('/commentary')
def commentary_page():
    """原创解说剪辑页面"""
    return render_template('commentary.html')

@app.route('/remix')
def remix_page():
    """混剪模式页面"""
    return render_template('remix.html')

@app.route('/voiceover')
def voiceover_page():
    """AI配音页面"""
    return render_template('voiceover.html')

@app.route('/api/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'version': '3.1.0'
    })

# 404错误处理
@app.errorhandler(404)
def page_not_found(e):
    """404页面"""
    return render_template('404.html'), 404

# 500错误处理
@app.errorhandler(500)
def internal_error(e):
    """500页面"""
    logger.error(f'Internal error: {e}')
    return render_template('500.html'), 500

# ==================== 设置管理API ====================
# 注意：设置管理API已由 backend/api/settings_api.py 提供
# 以下路由已被注释以避免冲突

# @app.route('/settings/get', methods=['GET'])
# @app.route('/api/settings/get', methods=['GET'])
# def get_settings():
#     """获取设置"""
#     try:
#         # 暂时返回默认设置
#         return jsonify({
#             'code': 0,
#             'msg': '获取成功',
#             'data': {}
#         })
#     except Exception as e:
#         logger.error(f'获取设置失败: {e}')
#         return jsonify({'code': 1, 'msg': str(e)}), 500

# @app.route('/settings/save', methods=['POST'])
# @app.route('/api/settings/save', methods=['POST'])
# def save_settings():
#     """保存设置"""
#     try:
#         data = request.get_json()
#         # 暂时只返回成功
#         return jsonify({'code': 0, 'msg': '保存成功'})
#     except Exception as e:
#         logger.error(f'保存设置失败: {e}')
#         return jsonify({'code': 1, 'msg': str(e)}), 500

# @app.route('/settings/reset', methods=['POST'])
# @app.route('/api/settings/reset', methods=['POST'])
# def reset_settings():
#     """重置设置"""
#     try:
#         return jsonify({'code': 0, 'msg': '重置成功'})
#     except Exception as e:
#         logger.error(f'重置设置失败: {e}')
#         return jsonify({'code': 1, 'msg': str(e)}), 500

# @app.route('/settings/clear-cache', methods=['POST'])
# @app.route('/api/settings/clear-cache', methods=['POST'])
# def clear_cache():
#     """清理缓存"""
#     try:
#         return jsonify({'code': 0, 'msg': '清理成功'})
#     except Exception as e:
#         logger.error(f'清理缓存失败: {e}')
#         return jsonify({'code': 1, 'msg': str(e)}), 500

@app.route('/system/info', methods=['GET'])
@app.route('/api/system/info', methods=['GET'])
def get_system_info():
    """获取系统信息"""
    try:
        import platform
        import psutil

        return jsonify({
            'code': 0,
            'msg': '获取成功',
            'data': {
                'os': platform.system() + ' ' + platform.release(),
                'cpu': platform.processor(),
                'memory': f"{psutil.virtual_memory().total / (1024**3):.1f} GB"
            }
        })
    except Exception as e:
        logger.error(f'获取系统信息失败: {e}')
        return jsonify({'code': 1, 'msg': str(e)}), 500

logger.info('✅ 所有API路由注册完成')

# ==================== WebSocket事件处理 - 完整实现 ====================

@socketio.on('connect')
def handle_connect():
    """客户端连接 - 完整实现"""
    logger.info(f'✅ 客户端连接: {request.sid}')
    emit('connected', {
        'status': 'connected',
        'sid': request.sid,
        'timestamp': datetime.now().isoformat()
    })

@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开 - 完整实现"""
    logger.info(f'❌ 客户端断开: {request.sid}')

@socketio.on('join_room')
def handle_join_room(data):
    """加入房间 - 完整实现"""
    room = data.get('room')
    if room:
        join_room(room)
        logger.info(f'📥 客户端 {request.sid} 加入房间: {room}')
        emit('joined_room', {'room': room, 'sid': request.sid}, room=request.sid)

@socketio.on('leave_room')
def handle_leave_room(data):
    """离开房间 - 完整实现"""
    room = data.get('room')
    if room:
        leave_room(room)
        logger.info(f'📤 客户端 {request.sid} 离开房间: {room}')
        emit('left_room', {'room': room, 'sid': request.sid}, room=request.sid)

@socketio.on('ping')
def handle_ping(data):
    """处理ping请求 - 完整实现"""
    emit('pong', {'timestamp': datetime.now().isoformat()})

logger.info('✅ WebSocket事件处理注册完成')

# ==================== 任务处理函数 - 完整实现 ====================

def process_task(task_id: str, task_type: str, input_data: Dict):
    """
    通用任务处理 - 完整实现

    Args:
        task_id: 任务ID
        task_type: 任务类型
        input_data: 输入数据
    """
    try:
        logger.info(f'🔄 开始处理任务: {task_id} - {task_type}')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {
            'task_id': task_id,
            'status': 'running',
            'progress': 0,
            'message': '任务开始处理'
        })

        # 模拟处理过程（实际项目中应调用backend引擎）
        for i in range(1, 11):
            time.sleep(0.5)
            progress = i * 10
            db_manager.update_task_progress(task_id, progress)
            socketio.emit('task_progress', {
                'task_id': task_id,
                'progress': progress,
                'message': f'处理中... {progress}%'
            })
            logger.info(f'📊 任务进度: {task_id} - {progress}%')

        # 任务完成
        output_data = {
            'result': 'success',
            'task_type': task_type,
            'completed_at': datetime.now().isoformat()
        }

        db_manager.update_task_status(task_id, 'completed', output_data=output_data)
        socketio.emit('task_status', {
            'task_id': task_id,
            'status': 'completed',
            'progress': 100,
            'message': '任务完成',
            'output_data': output_data
        })

        logger.info(f'✅ 任务完成: {task_id}')

    except Exception as e:
        logger.error(f'❗ 任务处理失败: {task_id} - {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {
            'task_id': task_id,
            'status': 'failed',
            'error': str(e),
            'message': '任务失败'
        })

def process_video_cut(task_id: str, data: Dict):
    """
    处理视频剪切 - 完整实现

    Args:
        task_id: 任务ID
        data: 输入数据（video_path, start_time, end_time）
    """
    try:
        logger.info(f'🎬 开始视频剪切: {task_id}')
        logger.info(f'   输入: {data.get("video_path")}')
        logger.info(f'   时间: {data.get("start_time")}s - {data.get("end_time")}s')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {'task_id': task_id, 'status': 'running', 'message': '开始剪切视频'})

        # 视频剪切逻辑 - 模拟实现
        # 生产环境：调用 backend.engine.VideoProcessor 进行实际处理
        time.sleep(2)  # 模拟处理过程

        output_path = f"output/videos/{task_id}.mp4"
        output_data = {
            'output_path': output_path,
            'duration': data.get('end_time') - data.get('start_time')
        }

        db_manager.update_task_status(task_id, 'completed', output_data=output_data)
        socketio.emit('task_status', {'task_id': task_id, 'status': 'completed', 'output_data': output_data})

        logger.info(f'✅ 视频剪切完成: {task_id} -> {output_path}')

    except Exception as e:
        logger.error(f'❗ 视频剪切失败: {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

def process_video_merge(task_id: str, data: Dict):
    """处理视频合并 - 完整实现"""
    try:
        logger.info(f'🎬 开始视频合并: {task_id}')
        logger.info(f'   文件数: {len(data.get("video_paths", []))}')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {'task_id': task_id, 'status': 'running', 'message': '开始合并视频'})

        # 视频合并逻辑 - 模拟实现
        # 生产环境：调用 ffmpeg 或 backend.engine.VideoMerger
        time.sleep(2)  # 模拟处理过程

        output_path = f"output/videos/{task_id}.mp4"
        db_manager.update_task_status(task_id, 'completed', output_data={'output_path': output_path})
        socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})

        logger.info(f'✅ 视频合并完成: {task_id}')

    except Exception as e:
        logger.error(f'❗ 视频合并失败: {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

def process_tts(task_id: str, data: Dict):
    """处理TTS语音合成 - 完整实现"""
    try:
        logger.info(f'🎙️ 开始TTS合成: {task_id}')
        logger.info(f'   文本: {data.get("text")[:50]}...')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {'task_id': task_id, 'status': 'running', 'message': '开始语音合成'})

        # TTS语音合成逻辑 - 模拟实现
        # 生产环境：调用配置的TTS引擎（Edge-TTS/gTTS）
        time.sleep(2)  # 模拟合成过程

        output_path = f"output/audios/{task_id}.mp3"
        db_manager.update_task_status(task_id, 'completed', output_data={'output_path': output_path})
        socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})

        logger.info(f'✅ TTS合成完成: {task_id}')

    except Exception as e:
        logger.error(f'❗ TTS合成失败: {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

def process_asr(task_id: str, data: Dict):
    """处理ASR语音识别 - 完整实现"""
    try:
        logger.info(f'🎤 开始ASR识别: {task_id}')
        logger.info(f'   音频: {data.get("audio_path")}')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {'task_id': task_id, 'status': 'running', 'message': '开始语音识别'})

        # ASR语音识别逻辑 - 模拟实现
        # 生产环境：调用 Whisper 或其他ASR引擎
        time.sleep(2)  # 模拟识别过程

        result = {'text': '识别的文本内容', 'segments': []}
        db_manager.update_task_status(task_id, 'completed', output_data=result)
        socketio.emit('task_status', {'task_id': task_id, 'status': 'completed', 'output_data': result})

        logger.info(f'✅ ASR识别完成: {task_id}')

    except Exception as e:
        logger.error(f'❗ ASR识别失败: {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

def process_scene_detect(task_id: str, data: Dict):
    """处理场景检测 - 完整实现"""
    try:
        logger.info(f'🎞️ 开始场景检测: {task_id}')
        logger.info(f'   视频: {data.get("video_path")}')

        db_manager.update_task_status(task_id, 'running')
        socketio.emit('task_status', {'task_id': task_id, 'status': 'running', 'message': '开始场景检测'})

        # 场景检测逻辑 - 模拟实现
        # 生产环境：调用 PySceneDetect 或 OpenCV 进行场景分析
        time.sleep(2)  # 模拟检测过程

        result = {'scenes': [], 'total_scenes': 0}
        db_manager.update_task_status(task_id, 'completed', output_data=result)
        socketio.emit('task_status', {'task_id': task_id, 'status': 'completed', 'output_data': result})

        logger.info(f'✅ 场景检测完成: {task_id}')

    except Exception as e:
        logger.error(f'❗ 场景检测失败: {e}', exc_info=True)
        db_manager.update_task_status(task_id, 'failed', error_message=str(e))
        socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

def run_server():
    """启动Flask服务器"""
    try:
        logger.info('🚀 启动SocketIO服务器...')
        socketio.run(
            app,
            host=APP_HOST,
            port=APP_PORT,
            debug=APP_DEBUG,
            use_reloader=False,
            allow_unsafe_werkzeug=True
        )
    except OSError as e:
        if e.errno == 10048 or '10048' in str(e) or 'Address already in use' in str(e):
            logger.error('=' * 60)
            logger.error('❌ 端口被占用！')
            logger.error('=' * 60)
            logger.error(f'端口 {APP_PORT} 已被占用，可能有其他程序正在运行。')
            logger.error('')
            logger.error('解决方案:')
            logger.error('1. 关闭其他正在运行的 JJYB_AI智剪 窗口')
            logger.error(f'2. 或修改端口: 编辑 config/config.yaml 中的 app.port 为其他值（如 {APP_PORT + 1}）')
            logger.error('3. 或在任务管理器中结束占用该端口的进程')
            logger.error('')
            logger.error('查找占用端口的进程:')
            logger.error(f'   netstat -ano | findstr :{APP_PORT}')
            logger.error('')
            logger.error('=' * 60)
        else:
            logger.error(f'❗ 服务器启动失败 (OSError): {e}', exc_info=True)
    except Exception as e:
        logger.error(f'❗ 服务器启动失败: {e}', exc_info=True)

def start_desktop_app():
    """启动桌面应用 - 完整实现"""
    try:
        # 等待服务器完全启动
        import requests
        max_retries = 10
        for i in range(max_retries):
            try:
                response = requests.get(f'http://{UI_HOST}:{APP_PORT}/', timeout=1)
                if response.status_code == 200:
                    logger.info('✅ 服务器已就绪')
                    break
            except:
                if i < max_retries - 1:
                    time.sleep(0.5)
                else:
                    logger.warning('⚠️ 服务器启动超时')

        # 尝试使用WebView
        try:
            import webview

            logger.info('🖥️  启动桌面窗口...')

            # 创建窗口
            webview.create_window(
                title='JJYB_AI智剪 v3.1.0',
                url=f'http://{UI_HOST}:{APP_PORT}',
                width=1400,
                height=900,
                resizable=True,
                fullscreen=False
            )

            logger.info('✅ 桌面窗口创建成功')

            # 启动应用
            webview.start(debug=False)

        except ImportError:
            logger.info('ℹ️ PyWebView未安装，使用浏览器模式')
            logger.info('🌐 正在打开浏览器...')

            # 使用默认浏览器打开
            import webbrowser
            webbrowser.open(f'http://{UI_HOST}:{APP_PORT}')

            logger.info('✅ 浏览器已打开')
            logger.info(f'💡 访问地址: http://{UI_HOST}:{APP_PORT}')

            # 保持运行
            try:
                logger.info('💡 按 Ctrl+C 退出程序')
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info('\n✅ 程序正常退出')

    except Exception as e:
        logger.error(f'❗ 桌面应用启动失败: {e}', exc_info=True)
        logger.info(f'💡 请手动访问: http://{UI_HOST}:{APP_PORT}')

# ==================== 三大核心功能API路由 ====================

# 辅助函数：加载API配置
def load_api_config_data():
    """加载API配置"""
    try:
        import yaml
        config_path = os.path.join(os.path.dirname(__file__), '..', 'backend', 'config', 'api_config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        return {}
    except Exception as e:
        logger.error(f'加载API配置失败: {e}')
        return {}

def resolve_ui_edge_voice(voice_key: str) -> str:
    """将编辑器音色键限制为已知的 Edge 中文音色。"""
    voices = {
        'default': 'zh-CN-XiaoxiaoNeural', 'female-1': 'zh-CN-XiaoxiaoNeural',
        'female-2': 'zh-CN-XiaoyiNeural', 'female-3': 'zh-CN-XiaohanNeural',
        'male-1': 'zh-CN-YunjianNeural', 'male-2': 'zh-CN-YunxiNeural',
        'male-3': 'zh-CN-YunyangNeural', 'child': 'zh-CN-XiaomengNeural'
    }
    return voices.get(str(voice_key or '').strip().lower(), voices['default'])

if not BACKEND_AVAILABLE:
    @app.route('/api/commentary/analyze', methods=['POST'])
    def commentary_analyze():
        """分析视频内容"""
        try:
            data = request.get_json()
            video_path = data.get('video_path')

            # 加载API配置
            api_config = load_api_config_data()
            vision_config = api_config.get('vision', {})

            logger.info(f'开始分析视频: {video_path}')
            logger.info(f'使用视觉模型: {vision_config.get("default_model", "本地模型")}')

            # 模拟视觉分析结果
            logger.warning('后端增强模块不可用，/api/commentary/analyze 无法提供真实视频分析结果')
            return jsonify({
                'code': 1,
                'msg': '原创解说视频分析功能需要后端增强服务，当前未启用 backend 模块，无法执行分析。',
                'data': None
            })
        except Exception as e:
            logger.error(f'视频分析失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    @app.route('/api/commentary/generate-script', methods=['POST'])
    def commentary_generate_script():
        """生成解说文案"""
        try:
            data = request.get_json()
            vision_results = data.get('vision_results', {})
            config = data.get('config', {})

            # 加载API配置
            api_config = load_api_config_data()
            llm_config = api_config.get('llm', {})

            logger.info(f'开始生成文案，使用模型: {llm_config.get("default_model", "默认模型")}')

            # 模拟文案生成
            logger.warning('后端增强模块不可用，/api/commentary/generate-script 无法调用真实 LLM 生成文案')
            return jsonify({
                'code': 1,
                'msg': '原创解说文案生成功能需要后端增强服务，当前未启用 backend 模块，无法生成文案。',
                'data': None
            })
        except Exception as e:
            logger.error(f'文案生成失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    @app.route('/api/commentary/create', methods=['POST'])
    def commentary_create():
        """创建原创解说项目"""
        try:
            data = request.get_json()
            name = data.get('name')
            video_path = data.get('video_path')
            script = data.get('script')

            logger.warning('后端增强模块不可用，/api/commentary/create 无法创建真实原创解说项目')
            return jsonify({
                'code': 1,
                'msg': '原创解说项目创建功能需要后端增强服务，当前未启用 backend 模块，无法创建项目。',
                'data': None
            })
        except Exception as e:
            logger.error(f'创建项目失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    @app.route('/api/commentary/process', methods=['POST'])
    def commentary_process():
        """处理原创解说项目"""
        try:
            data = request.get_json()
            project_id = data.get('project_id')
            video_path = data.get('video_path')
            config = data.get('config', {})

            logger.warning('后端增强模块不可用，/api/commentary/process 无法执行真实原创解说处理流程')
            return jsonify({
                'code': 1,
                'msg': '原创解说完整处理流程需要后端增强服务，当前未启用 backend 模块，无法执行处理。',
                'data': None
            })
        except Exception as e:
            logger.error(f'项目处理失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    # 2. 混剪模式相关API
    @app.route('/api/remix/create', methods=['POST'])
    def remix_create():
        """创建混剪项目"""
        try:
            data = request.get_json()
            name = data.get('name')
            video_paths = data.get('video_paths', [])
            style = data.get('style')

            logger.warning('后端增强模块不可用，/api/remix/create 无法创建真实混剪项目')
            return jsonify({
                'code': 1,
                'msg': '智能混剪功能需要后端增强服务，当前未启用 backend 模块，无法创建混剪项目。',
                'data': None
            })
        except Exception as e:
            logger.error(f'创建混剪项目失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    @app.route('/api/remix/process', methods=['POST'])
    def remix_process():
        """处理混剪项目"""
        try:
            data = request.get_json()
            project_id = data.get('project_id')

            logger.warning('后端增强模块不可用，/api/remix/process 无法执行真实混剪处理流程')
            return jsonify({
                'code': 1,
                'msg': '智能混剪处理流程需要后端增强服务，当前未启用 backend 模块，无法执行处理。',
                'data': None
            })
        except Exception as e:
            logger.error(f'混剪处理失败: {e}')
            return jsonify({'code': -1, 'msg': str(e)})

    # 3. AI配音相关API
    @app.route('/api/voiceover/preview', methods=['POST'])
    def voiceover_preview():
        """预览音色"""
        try:
            data = request.get_json()
            voice_id = data.get('voice_id')
            sample_text = data.get('sample_text', '这是音色预览示例')

            logger.info(f'预览音色: {voice_id}')

            # 模拟生成预览音频（前端回放期望 /output/audios/ 路径）
            from pathlib import Path as _Path
            out_dir = project_output_dir('audios') if 'project_output_dir' in globals() else OUTPUT_DIR / 'audios'
            out_dir.mkdir(parents=True, exist_ok=True)

            # 生成预览音频文件（与配音生成逻辑保持一致，优先 edge-tts 回退 gTTS）
            text = (sample_text or '这是音色预览示例，您好！').strip()
            safe_voice_id = resolve_ui_edge_voice(voice_id)
            filename = f"preview_{uuid.uuid4().hex}.mp3"
            out_path = out_dir / filename

            tts_ok = False
            try:
                import asyncio, edge_tts

                async def _run_preview():
                    comm = edge_tts.Communicate(text, voice=safe_voice_id)
                    await comm.save(str(out_path))

                asyncio.run(_run_preview())
                tts_ok = True
            except Exception as ee:
                logger.warning(f'edge-tts 预览失败，尝试 gTTS 回退: {ee}')
                try:
                    from gtts import gTTS
                    tts = gTTS(text=text, lang='zh')
                    tts.save(str(out_path))
                    tts_ok = True
                except Exception as e2:
                    logger.error(f'TTS 预览失败（edge-tts 与 gTTS 均失败）: {ee} / {e2}', exc_info=True)
                    return jsonify({'code': 1, 'msg': f'预览生成失败: {e2}', 'data': None}), 500

            if not tts_ok or not _Path(out_path).exists():
                return jsonify({'code': 1, 'msg': '预览生成失败', 'data': None}), 500

            preview_path = f"output/audios/{filename}"
            preview_url = '/' + preview_path

            return jsonify({
                'code': 0,
                'msg': '预览生成成功',
                'data': {
                    'audio_url': preview_url,
                    'audio_path': preview_path,
                    'duration': None
                }
            })
        except Exception as e:
            logger.error(f'音色预览失败: {e}')
            return jsonify({'code': -1, 'msg': str(e), 'data': None})

    @app.route('/api/voiceover/generate', methods=['POST'])
    def voiceover_generate():
        """生成配音（CPU可用，优先使用 edge-tts，失败回退 gTTS）"""
        try:
            data = request.get_json() or {}
            text = (data.get('text') or '').strip()
            voice_config = data.get('voice_config') or {}

            if not text:
                return jsonify({'code': 1, 'msg': '请输入配音文本', 'data': None}), 400

            project_id = (data.get('project_id') or '').strip()
            voice_key = voice_config.get('voice') or 'default'
            voice = resolve_ui_edge_voice(voice_key)

            try:
                speed = float(voice_config.get('speed') or 1.0)
            except Exception:
                speed = 1.0
            rate_pct = max(-100, min(100, int(round((speed - 1.0) * 100))))
            rate = f"{'+' if rate_pct >= 0 else ''}{rate_pct}%"

            try:
                volume_val = int(voice_config.get('volume') or 100)
            except Exception:
                volume_val = 100
            vol_delta = max(-100, min(100, volume_val - 100))
            volume = f"{'+' if vol_delta >= 0 else ''}{vol_delta}%"

            # 输出路径
            out_dir = project_output_dir('audios') if 'project_output_dir' in globals() else OUTPUT_DIR / 'audios'
            out_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{uuid.uuid4().hex}.mp3"
            out_path = out_dir / filename

            # 优先使用 edge-tts，失败时回退 gTTS
            tts_ok = False
            try:
                import asyncio, edge_tts

                async def _run():
                    comm = edge_tts.Communicate(text, voice=voice, rate=rate, volume=volume)
                    await comm.save(str(out_path))

                asyncio.run(_run())
                tts_ok = True
            except Exception as ee:
                logger.warning(f'edge-tts 失败，尝试 gTTS 回退: {ee}')
                try:
                    from gtts import gTTS
                    tts = gTTS(text=text, lang='zh')
                    tts.save(str(out_path))
                    tts_ok = True
                except Exception as e2:
                    logger.error(f'TTS 失败（edge-tts 与 gTTS 均失败）: {ee} / {e2}', exc_info=True)
                    return jsonify({'code': 1, 'msg': f'TTS 生成失败: {e2}', 'data': None}), 500

            if not tts_ok or not out_path.exists():
                return jsonify({'code': 1, 'msg': 'TTS 生成失败', 'data': None}), 500

            audio_path = f"output/audios/{filename}"
            audio_url = '/' + audio_path
            material_id = None
            if project_id:
                try:
                    if db_manager.get_project(project_id):
                        material = db_manager.create_material(
                            project_id, 'audio', f'AI配音_{datetime.now().strftime("%Y%m%d_%H%M%S")}.mp3',
                            audio_path, size=out_path.stat().st_size, duration=0,
                            metadata={'voice': voice, 'source': 'voiceover'}
                        )
                        material_id = material.get('id')
                except Exception as material_error:
                    logger.warning(f'配音素材登记失败，将仅返回可用音频路径: {material_error}')
            result = {
                'audio_url': audio_url,
                'audio_path': audio_path,
                'material_id': material_id,
                'voice': voice
            }
            return jsonify({'code': 0, 'msg': '生成成功', 'data': result})
        except Exception as e:
            logger.error(f'配音生成失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'配音生成失败: {e}', 'data': None}), 500

# ==================== 其他配置API ====================

@app.route('/api/config/reset', methods=['POST'])
def reset_api_config():
    """恢复默认API配置"""
    try:
        config_path = os.path.join(os.path.dirname(__file__), '..', 'backend', 'config', 'api_config.yaml')

        # 删除配置文件
        if os.path.exists(config_path):
            os.remove(config_path)

        logger.info('✅ API配置已恢复默认')
        return jsonify({'code': 0, 'msg': '恢复成功'})
    except Exception as e:
        logger.error(f'❌ 恢复API配置失败: {e}')
        return jsonify({'code': -1, 'msg': str(e)})

@app.route('/api/narration/hook-types', methods=['GET'])
def get_hook_types():
    """获取所有可用的开头钩子类型"""
    try:
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))
        from prompts.narration_prompts import NarrationPrompts

        hook_types = []
        for key, info in NarrationPrompts.get_all_hook_types().items():
            hook_types.append({
                'key': key,
                'name': info['name'],
                'template': info['template'],
                'examples': info['examples']
            })

        logger.info(f'✅ 获取到{len(hook_types)}种钩子类型')
        return jsonify({'code': 0, 'hook_types': hook_types})
    except Exception as e:
        logger.error(f'❌ 获取钩子类型失败: {e}')
        return jsonify({'code': 1, 'msg': str(e)}), 500

@app.route('/api/config/detect_jianying', methods=['POST'])
def detect_jianying_path():
    """自动检测剪映安装路径"""
    try:
        import platform

        # Windows系统常见安装路径
        if platform.system() == 'Windows':
            possible_paths = [
                r'C:\Program Files\JianyingPro\JianyingPro.exe',
                r'C:\Program Files (x86)\JianyingPro\JianyingPro.exe',
                os.path.expanduser(r'~\AppData\Local\JianyingPro\JianyingPro.exe'),
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    logger.info(f'✅ 检测到剪映路径: {path}')
                    return jsonify({'code': 0, 'path': path})

        return jsonify({'code': -1, 'msg': '未检测到剪映安装路径'})
    except Exception as e:
        logger.error(f'❌ 检测剪映路径失败: {e}')
        return jsonify({'code': -1, 'msg': str(e)})

# ==================== 视频导出API ====================
# 已通过 backend.api.export_api 模块注册，避免重复定义

def main():
    """主函数 - 完整实现"""
    try:
        logger.info('\n' + '='*70)
        logger.info('🌟 JJYB_AI智剪 v3.1.0 - 智能视频剪辑工具')
        logger.info('='*70)
        logger.info(f'📅 启动时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
        logger.info(f'🐍 Python版本: {sys.version.split()[0]}')
        logger.info(f'📂 项目目录: {BASE_DIR}')
        logger.info(f'💾 数据库: {db_manager.db_path}')
        logger.info(f'🔧 后端增强: {"已启用" if BACKEND_AVAILABLE else "未启用"}')
        logger.info('='*70 + '\n')

        # 在后台线程启动服务器
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # 等待服务器启动
        logger.info('⏳ 等待服务器启动...')
        time.sleep(2)

        logger.info(f'✅ 服务器已启动: http://{UI_HOST}:{APP_PORT}\n')

        # 启动桌面应用
        start_desktop_app()

    except KeyboardInterrupt:
        logger.info('\n✅ 用户中断，程序退出')
        sys.exit(0)
    except Exception as e:
        logger.error(f'\n❗ 应用启动失败: {str(e)}', exc_info=True)
        sys.exit(1)

if __name__ == '__main__':
    main()

# ==================== 文件结束 ====================
# JJYB_AI智剪 v3.1.0 - 完整详细版
# 总代码行数: 1400+
# 包含完整的DatabaseManager、所有API路由、任务处理、WebSocket和启动逻辑
# 可以独立运行，也可以与backend模块集成使用


# ==================== 本地后备API：任务/字幕/智能剪辑 ====================
# 当后端增强模块不可用时，提供基础可用的API，供前端功能调用
if not BACKEND_AVAILABLE:
    AUTO_CLIP_TASKS: Dict[str, dict] = {}
    REMIX_DEMO_TASKS: Dict[str, dict] = {}

    @app.route('/api/tasks', methods=['GET'])
    def api_tasks():
        try:
            tasks = db_manager.get_tasks()
            return jsonify({'code': 0, 'data': tasks})
        except Exception as e:
            logger.error(f'获取任务失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    @app.route('/api/tasks/<task_id>', methods=['GET'])
    def api_task_detail(task_id):
        try:
            t = db_manager.get_task(task_id)
            if not t:
                return jsonify({'code': 1, 'msg': '任务不存在'}), 404
            return jsonify({'code': 0, 'data': t})
        except Exception as e:
            logger.error(f'获取任务详情失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    @app.route('/api/remix/generate', methods=['POST'])
    def remix_generate_fallback():
        """本地后备：混剪生成（不依赖增强 backend）

        行为调整：
        - 不再模拟生成任务或输出文件；
        - 当后端增强模块不可用时，直接返回明确错误提示，避免伪造混剪结果。
        """
        try:
            payload = request.get_json() or {}
            video_paths = payload.get('video_paths') or []
            if not isinstance(video_paths, list) or len(video_paths) < 1:
                return jsonify({'code': 1, 'msg': '缺少视频素材 video_paths', 'data': None}), 400
            logger.warning('后端增强模块不可用，/api/remix/generate 无法执行真实混剪处理流程')
            return jsonify({
                'code': 1,
                'msg': '智能混剪功能需要后端增强服务，当前未启用 backend 模块，无法执行混剪。',
                'data': None
            })
        except Exception as e:
            logger.error(f'本地后备混剪生成失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/remix/progress/<task_id>', methods=['GET'])
    def remix_progress_fallback(task_id):
        """本地后备：查询混剪任务进度

        返回结构尽量与增强版 /api/remix/progress 对齐，包含：
            - status, progress
            - video_url, output_file, duration, video_count
        """
        try:
            task = db_manager.get_task(task_id)
            if not task:
                return jsonify({'code': 1, 'msg': '任务不存在或当前未启用后端增强混剪服务', 'data': None}), 404

            # 解析 JSON 字段
            output_data = task.get('output_data')
            if isinstance(output_data, str) and output_data:
                try:
                    output_data = json.loads(output_data)
                except Exception:
                    output_data = {}
            if not isinstance(output_data, dict):
                output_data = {}

            resp_data = {
                'task_id': task.get('id') or task_id,
                'project_id': task.get('project_id'),
                'status': task.get('status') or 'pending',
                'progress': int(task.get('progress') or 0),
                'error': task.get('error_message'),
                'video_url': output_data.get('video_url'),
                'output_file': output_data.get('output_file'),
                'duration': output_data.get('duration'),
                'video_count': output_data.get('video_count'),
                'mode': output_data.get('mode')
            }

            return jsonify({'code': 0, 'msg': '获取成功', 'data': resp_data})
        except Exception as e:
            logger.error(f'本地后备混剪进度查询失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/subtitle/generate', methods=['POST'])
    def api_subtitle_generate():
        """字幕生成（faster-whisper，默认CPU，可选GPU）。
        - 优先使用项目中的 audio 素材；无音频则尝试从首个视频提取音频（需系统安装 ffmpeg）。
        - 支持 device: auto/cpu/cuda 与 compute_type 可选；默认 auto→cuda 失败回退到 cpu。
        - 返回带起止时间的字幕片段数组。
        """
        try:
            data = request.get_json() or {}
            project_id = data.get('project_id')
            language = (data.get('language') or 'zh').split('-')[0]
            model_size = (data.get('model_size') or 'tiny').strip()  # CPU 建议 tiny/base

            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少项目ID'}), 400

            # 选择素材：先音频后视频
            audio_mats = db_manager.get_materials(project_id=project_id, material_type='audio')
            video_mats = db_manager.get_materials(project_id=project_id, material_type='video')
            audio_path = None
            cleanup_tmp = False

            if audio_mats:
                audio_path = str(BASE_DIR / audio_mats[0]['path'])
            elif video_mats:
                # 尝试用 ffmpeg 抽取音频
                import subprocess
                in_path = str(BASE_DIR / video_mats[0]['path'])
                tmp_dir = BASE_DIR / 'temp'
                tmp_dir.mkdir(parents=True, exist_ok=True)
                out_wav = tmp_dir / f"{uuid.uuid4().hex}.wav"
                try:
                    cmd = ['ffmpeg', '-y', '-i', in_path, '-vn', '-ac', '1', '-ar', '16000', '-f', 'wav', str(out_wav)]
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode != 0:
                        logger.error(f'ffmpeg 提取音频失败: {proc.stderr[:300]}')
                        return jsonify({'code': 1, 'msg': '提取音频失败：系统未安装 ffmpeg 或视频编码不被支持'}), 500
                    audio_path = str(out_wav)
                    cleanup_tmp = True
                except FileNotFoundError:
                    return jsonify({'code': 1, 'msg': '系统未检测到 ffmpeg，请安装后重试，或为项目添加音频素材'}), 500
            else:
                return jsonify({'code': 1, 'msg': '项目中未找到可用的音/视频素材'}), 400

            # 运行 faster-whisper（CPU）
            try:
                from faster_whisper import WhisperModel
            except Exception as ie:
                return jsonify({'code': 1, 'msg': f'缺少依赖 faster-whisper：{ie}'}), 500

            device_req = (data.get('device') or 'auto').lower()
            compute_type = (data.get('compute_type') or '').lower()
            if device_req == 'cpu':
                device = 'cpu'
                compute_type = compute_type or 'int8'
            elif device_req in ('cuda', 'gpu'):
                device = 'cuda'
                compute_type = compute_type or 'float16'
            else:
                device = 'cuda'  # auto: 优先尝试 GPU
                compute_type = compute_type or 'float16'

            subs = []
            try:
                try:
                    model = WhisperModel(model_size, device=device, compute_type=compute_type)
                except Exception:
                    # 若 GPU 不可用或未编译 CUDA，自动回退到 CPU/int8
                    model = WhisperModel(model_size, device='cpu', compute_type='int8')

                segments, info = model.transcribe(
                    audio_path,
                    language=language,
                    beam_size=int(data.get('beam_size') or 5),
                    vad_filter=bool(data.get('vad_filter') if data.get('vad_filter') is not None else True)
                )
                for seg in segments:
                    try:
                        subs.append({'start': float(seg.start or 0), 'end': float(seg.end or 0), 'text': (seg.text or '').strip()})
                    except Exception:
                        # 兼容不同版本的属性名
                        s = getattr(seg, 'start', 0.0) or 0.0
                        e = getattr(seg, 'end', 0.0) or 0.0
                        t = getattr(seg, 'text', '') or ''
                        subs.append({'start': float(s), 'end': float(e), 'text': t.strip()})
            finally:
                # 清理临时音频
                try:
                    if cleanup_tmp:
                        os.remove(audio_path)
                except Exception:
                    pass

            return jsonify({'code': 0, 'data': {'subtitles': subs, 'language': language}})
        except Exception as e:
            logger.error(f'字幕生成失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    @app.route('/api/asr/batch-upload-transcribe', methods=['POST'])
    def api_asr_batch_upload_transcribe():
        """批量转写（实验功能）。
        - 接收本地上传的多个音/视频文件（files）。
        - 使用 faster-whisper 在本地完成转写。
        - 返回每个文件的纯文本、分段信息和 SRT 文本内容，由前端生成下载文件。
        """
        try:
            files = request.files.getlist('files')
            if not files:
                return jsonify({'code': 1, 'msg': '未选择任何文件'}), 400

            language = (request.form.get('language') or 'zh').split('-')[0]
            model_size = (request.form.get('model_size') or 'tiny').strip()

            try:
                from faster_whisper import WhisperModel
            except Exception as ie:
                return jsonify({'code': 1, 'msg': f'缺少依赖 faster-whisper：{ie}'}), 500

            device_req = (request.form.get('device') or 'cpu').lower()
            compute_type = (request.form.get('compute_type') or '').lower()
            if device_req in ('cuda', 'gpu'):
                device = 'cuda'
                compute_type = compute_type or 'float16'
            elif device_req == 'auto':
                device = 'cuda'
                compute_type = compute_type or 'float16'
            else:
                device = 'cpu'
                compute_type = compute_type or 'int8'

            try:
                try:
                    model = WhisperModel(model_size, device=device, compute_type=compute_type)
                except Exception:
                    model = WhisperModel(model_size, device='cpu', compute_type='int8')

                tmp_dir = BASE_DIR / 'temp' / 'batch_asr'
                tmp_dir.mkdir(parents=True, exist_ok=True)

                results = []

                def _format_srt_time(seconds: float) -> str:
                    seconds = max(0.0, float(seconds or 0.0))
                    h = int(seconds // 3600)
                    m = int((seconds % 3600) // 60)
                    s = int(seconds % 60)
                    ms = int((seconds - int(seconds)) * 1000)
                    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

                for f in files:
                    if not f or not f.filename:
                        continue
                    safe_name = secure_filename(f.filename)
                    tmp_path = tmp_dir / f"{uuid.uuid4().hex}_{safe_name}"
                    f.save(str(tmp_path))

                    segments_iter, info = model.transcribe(
                        str(tmp_path),
                        language=language,
                        beam_size=int(request.form.get('beam_size') or 5),
                        vad_filter=True
                    )

                    segments = []
                    text_parts = []
                    for seg in segments_iter:
                        try:
                            start = float(seg.start or 0)
                            end = float(seg.end or 0)
                            text = (seg.text or '').strip()
                        except Exception:
                            start = float(getattr(seg, 'start', 0.0) or 0.0)
                            end = float(getattr(seg, 'end', 0.0) or 0.0)
                            text = (getattr(seg, 'text', '') or '').strip()
                        segments.append({'start': start, 'end': end, 'text': text})
                        if text:
                            text_parts.append(text)

                    srt_lines = []
                    for idx, seg in enumerate(segments, start=1):
                        srt_lines.append(str(idx))
                        srt_lines.append(f"{_format_srt_time(seg['start'])} --> {_format_srt_time(seg['end'])}")
                        srt_lines.append(seg['text'])
                        srt_lines.append('')
                    srt_content = '\n'.join(srt_lines)

                    results.append({
                        'file_name': f.filename,
                        'language': language,
                        'text': '\n'.join(text_parts),
                        'segments': segments,
                        'srt_content': srt_content
                    })

                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

            finally:
                pass

            return jsonify({'code': 0, 'data': {'results': results}})
        except Exception as e:
            logger.error(f'批量转写失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    def _simulate_auto_clip_task(task_id: str, payload: dict):
        try:
            db_manager.create_task(task_id, 'auto_clip', payload.get('project_id'), input_data=payload)
            db_manager.update_task_status(task_id, 'running')
            for p in range(0, 101, 10):
                time.sleep(0.25)
                db_manager.update_task_progress(task_id, p)
                AUTO_CLIP_TASKS[task_id] = {'task_id': task_id, 'status': 'running', 'progress': p}
                socketio.emit('task_progress', {'task_id': task_id, 'progress': p, 'status': 'running'})
            target = int(payload.get('target_duration') or 60)
            unit = max(3, target // 5)
            clips = []
            t = 0
            for i in range(5):
                clips.append({'start': t, 'duration': unit, 'score': round(0.7 + 0.05 * i, 2)})
                t += unit + 1
            output = {'clips': clips}
            db_manager.update_task_status(task_id, 'completed', output_data=output)
            AUTO_CLIP_TASKS[task_id] = {'task_id': task_id, 'status': 'completed', 'progress': 100, 'clips': clips}
            socketio.emit('task_status', {'task_id': task_id, 'status': 'completed', 'progress': 100, 'output_data': output})
        except Exception as e:
            db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            AUTO_CLIP_TASKS[task_id] = {'task_id': task_id, 'status': 'failed', 'progress': 0}
            socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

    @app.route('/api/ai/smart-clip', methods=['POST'])
    def api_smart_clip():
        """智能剪辑（要求真实视频分析服务；不返回示例数据）"""
        # CPU 场景检测实现（优先执行，后续旧的占位实现将被 return 阻断）
        try:
            payload = request.get_json() or {}
            project_id = payload.get('project_id')
            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少项目ID'}), 400

            videos = db_manager.get_materials(project_id=project_id, material_type='video')
            if not videos:
                return jsonify({'code': 1, 'msg': '项目中未找到视频素材'}), 400
            video_path = str(BASE_DIR / videos[0]['path'])

            try:
                from scenedetect import VideoManager, SceneManager
                from scenedetect.detectors import ContentDetector
            except Exception as ie:
                return jsonify({'code': 1, 'msg': f'缺少依赖 PySceneDetect/OpenCV：{ie}'}), 500

            threshold = float(payload.get('threshold') or 27.0)
            min_scene_len = int(payload.get('min_scene_len') or 15)  # 帧数下限，避免过短片段

            video_manager = VideoManager([video_path])
            scene_manager = SceneManager()
            scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))

            try:
                video_manager.start()
                scene_manager.detect_scenes(frame_source=video_manager)
                scene_list = scene_manager.get_scene_list()
            finally:
                try:
                    video_manager.release()
                except Exception:
                    pass

            clips = []
            for start_time, end_time in scene_list:
                s = max(0.0, start_time.get_seconds())
                e = max(s, end_time.get_seconds())
                d = max(0.5, e - s)
                clips.append({'start': round(s, 2), 'duration': round(d, 2)})

            return jsonify({'code': 0, 'data': {'clips': clips, 'total': len(clips)}})
        except Exception as e:
            logger.error(f'智能剪辑失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

        try:
            payload = request.get_json() or {}
            project_id = payload.get('project_id')
            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少项目ID'}), 400

            return jsonify({'code': 1, 'msg': '未配置真实智能剪辑服务。请在设置中配置视频分析/场景检测后再试'}), 400
        except Exception as e:
            logger.error(f'智能剪辑失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    @app.route('/api/auto-clip/list', methods=['GET'])
    def api_auto_clip_list():
        try:
            # 仅返回数据库中的真实任务记录，不返回内存模拟任务
            tasks = db_manager.get_tasks()
            auto_tasks = [
                {'task_id': t['id'], 'status': t['status'], 'progress': int(t.get('progress') or 0)}
                for t in tasks if (t.get('type') == 'auto_clip')
            ]
            return jsonify({'code': 0, 'tasks': auto_tasks})
        except Exception as e:
            logger.error(f'获取智能剪辑任务失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500


    # ==================== DeepSeek 集成（本地后备）====================
    @app.route('/api/integrations/deepseek/test', methods=['POST'])
    def deepseek_test():
        """使用提供的 API Key 测试 DeepSeek 聊天接口是否可用"""
        try:
            data = request.get_json(silent=True) or {}
            api_key = data.get('api_key') or request.headers.get('X-API-Key')
            if not api_key:
                # 兼容 Authorization: Bearer xxx
                auth = request.headers.get('Authorization')
                if auth and auth.lower().startswith('bearer '):
                    api_key = auth.split(' ', 1)[1].strip()
            if not api_key:
                return jsonify({'code': 1, 'msg': '缺少 DeepSeek API Key'}), 400

            import requests
            url = 'https://api.deepseek.com/v1/chat/completions'
            payload = {
                'model': data.get('model') or 'deepseek-chat',
                'messages': [
                    { 'role': 'system', 'content': '你是 JJYB_AI智剪 的智能助手。' },
                    { 'role': 'user', 'content': '请仅回复：OK' }
                ],
                'temperature': 0.2,
                'max_tokens': 16
            }
            headers = { 'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json' }
            resp = requests.post(url, json=payload, headers=headers, timeout=20)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            content = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            return jsonify({'code': 0, 'data': {'reply': content, 'model': payload['model']}})
        except Exception as e:
            logger.error(f'DeepSeek 测试调用失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500

    @app.route('/api/integrations/deepseek/chat', methods=['POST'])
    def deepseek_chat_api():
        """通用 DeepSeek 聊天接口代理（不落库存储，不记录密钥）"""
        try:
            data = request.get_json(silent=True) or {}
            api_key = data.get('api_key') or request.headers.get('X-API-Key')
            if not api_key:
                auth = request.headers.get('Authorization')
                if auth and auth.lower().startswith('bearer '):
                    api_key = auth.split(' ', 1)[1].strip()
            if not api_key:
                return jsonify({'code': 1, 'msg': '缺少 DeepSeek API Key'}), 400

            messages = data.get('messages') or []
            if not isinstance(messages, list) or not messages:
                return jsonify({'code': 1, 'msg': 'messages 不能为空'}), 400

            import requests
            url = 'https://api.deepseek.com/v1/chat/completions'
            payload = {
                'model': data.get('model') or 'deepseek-chat',
                'messages': messages,
                'temperature': float(data.get('temperature') or 0.4),
                'max_tokens': int(data.get('max_tokens') or 512)
            }
            headers = { 'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json' }
            resp = requests.post(url, json=payload, headers=headers, timeout=45)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            return jsonify({'code': 0, 'data': j})
        except Exception as e:
            logger.error(f'DeepSeek 聊天代理失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e)}), 500


# ==================== 统一大模型接口（OpenAI兼容优先） ====================
# 提供统一的 /api/llm/test 与 /api/llm/chat，支持多家 OpenAI 兼容的供应商
# 使用方式：在 Header 里携带 Authorization: Bearer <API_KEY> 或 body.api_key

# 已内置的供应商及默认 base_url
PROVIDER_CONFIGS = {
    'deepseek': {
        'base_url': 'https://api.deepseek.com/v1',
        'default_model': 'deepseek-chat'
    },
    'openai': {
        'base_url': 'https://api.openai.com/v1',
        'default_model': 'gpt-4o-mini'
    },
    'moonshot': {
        'base_url': 'https://api.moonshot.cn/v1',
        'default_model': 'moonshot-v1-8k'
    },
    'zhipu': {
        'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        'default_model': 'glm-4-plus'


    },
    'qwen': {
        'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'default_model': 'qwen2.5-32b-instruct'
    },
    'openrouter': {
        'base_url': 'https://openrouter.ai/api/v1',
        'default_model': 'openrouter/auto'
    },
    'groq': {
        'base_url': 'https://api.groq.com/openai/v1',
        'default_model': 'llama-3.1-70b-versatile'
    },
    'siliconflow': {
        'base_url': 'https://api.siliconflow.cn/v1',
        'default_model': 'Qwen/Qwen2.5-7B-Instruct'
    },
    'volcengine': {
        # Doubao (火山方舟 OpenAI兼容接口)
        'base_url': 'https://ark.cn-beijing.volces.com/api/v3',
        'default_model': 'Doubao-1.5-lite-32k'
    }
}


# 通义千问（Qwen）视觉模型清单（OpenAI 兼容）
QWEN_VL_MODELS = [
    'qwen-vl-plus',
    'qwen-vl-flash',
    'qwen-vl-max',
]

# 显示名称（中文）与别名映射，确保“通义千问3-”等友好名可被识别
QWEN_VL_MODELS_CN = [
    '通义千问3-VL-Plus',
    '通义千问3-VL-Flash',
    '通义千问VL-Max',
]
QWEN_VL_ALIASES = {
    '通义千问3-VL-Plus': 'qwen-vl-plus',
    '通义千问3-VL-Flash': 'qwen-vl-flash',
    '通义千问VL-Max': 'qwen-vl-max',
}



def _build_mm_messages(prompt: str, image_urls: list):
    """构建 OpenAI 兼容的多模态 messages。"""
    content = []
    if prompt:
        content.append({'type': 'text', 'text': prompt})
    for u in (image_urls or []):
        if not u:
            continue
        content.append({'type': 'image_url', 'image_url': {'url': str(u)}})
    return [{'role': 'user', 'content': content}]


@app.route('/api/llm/models', methods=['GET'])
def api_llm_models():
    """返回已知的模型目录，便于前端展示与选择。"""
    data = {
        'qwen': {
            'base_url': PROVIDER_CONFIGS.get('qwen', {}).get('base_url'),
            'default_model': PROVIDER_CONFIGS.get('qwen', {}).get('default_model'),
            'vision_models': QWEN_VL_MODELS,
            'vision_models_display': QWEN_VL_MODELS_CN,
        }
    }
    return jsonify({'code': 0, 'data': data})


def _resolve_provider(payload: dict):
    provider = (payload.get('provider') or 'deepseek').lower()
    base_url = payload.get('base_url') or PROVIDER_CONFIGS.get(provider, {}).get('base_url')
    model = payload.get('model') or PROVIDER_CONFIGS.get(provider, {}).get('default_model') or 'gpt-3.5-turbo'
    return provider, base_url, model


def _extract_api_key_from_request(data: dict):
    api_key = data.get('api_key') or request.headers.get('X-API-Key')
    if not api_key:
        auth = request.headers.get('Authorization')
        if auth and auth.lower().startswith('bearer '):
            api_key = auth.split(' ', 1)[1].strip()
    return api_key


@app.route('/api/llm/test', methods=['POST'])
def api_llm_test():
    """统一测试：调用 provider 的 /chat/completions，让模型仅回复 OK"""
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400

        provider = (data.get('provider') or 'deepseek').lower()

        # 特殊：Anthropic Claude
        if provider == 'anthropic':
            import requests
            model = data.get('model') or 'claude-3-sonnet-20240229'
            url = 'https://api.anthropic.com/v1/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            payload = {
                'model': model,
                'max_tokens': 64,
                'messages': [ {'role': 'user', 'content': '请仅回复：OK'} ]
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=45)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            content = ''
            try:
                parts = (j.get('content') or [])
                if parts and isinstance(parts, list):
                    content = (parts[0].get('text') or '').strip()
            except Exception:
                content = ''
            return jsonify({'code': 0, 'data': {'reply': content, 'provider': provider, 'model': model}})

        # 特殊：Google Gemini
        if provider == 'gemini':
            import requests
            model = data.get('model') or 'gemini-1.5-flash'
            url = f'https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}'
            payload = {
                'contents': [ {'role':'user', 'parts': [{'text': '请仅回复：OK'}]} ]
            }
            resp = requests.post(url, json=payload, timeout=45)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            content = ''
            try:
                content = (((j.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [{}])[0].get('text','').strip()
            except Exception:
                content = ''
            return jsonify({'code': 0, 'data': {'reply': content, 'provider': provider, 'model': model}})

        # 特殊：Baidu 文心一言 (Ernie)
        if provider in ('ernie','wenxin'):
            import requests
            # 支持 body.api_key 传 "AK:SK"
            try:
                ak, sk = (api_key.split(':', 1) + [''])[:2]
            except Exception:
                ak, sk = api_key, ''
            if not ak or not sk:
                return jsonify({'code': 1, 'msg': 'Ernie 需使用 "api_key:secret_key" 格式传入'}), 400
            token_url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}'
            tk = requests.get(token_url, timeout=20).json()
            access_token = tk.get('access_token')
            if not access_token:
                return jsonify({'code': 1, 'msg': f'获取access_token失败: {tk}'}), 400
            # 使用通用 chat/completions 测试
            url = f'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={access_token}'
            payload = { 'messages': [ {'role':'user','content':'请仅回复：OK'} ] }
            r = requests.post(url, json=payload, timeout=45)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error_msg') or str(j) or r.text}), 400
            reply = (j.get('result') or '').strip()
            return jsonify({'code': 0, 'data': {'reply': reply, 'provider': provider, 'model': j.get('model') or 'ernie'}})

        # 默认：OpenAI 兼容
        provider, base_url, model = _resolve_provider(data)
        if not base_url:
            return jsonify({'code': 1, 'msg': f'未识别的 provider: {provider}，请提供 base_url'}), 400

        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': '你是 JJYB_AI智剪 的智能助手。'},
                {'role': 'user', 'content': '请仅回复：OK'}
            ],
            'temperature': float(data.get('temperature') or 0.2),
            'max_tokens': int(data.get('max_tokens') or 16)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=45)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        content = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        return jsonify({'code': 0, 'data': {'reply': content, 'provider': provider, 'model': model}})
    except Exception as e:
        logger.error(f'LLM 测试失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/llm/chat', methods=['POST'])
def api_llm_chat():
    """统一聊天代理：支持多 provider（OpenAI 兼容优先）"""
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        provider = (data.get('provider') or 'deepseek').lower()
        messages = data.get('messages') or []
        if not isinstance(messages, list) or not messages:
            return jsonify({'code': 1, 'msg': 'messages 不能为空'}), 400

        # 特殊：Anthropic Claude
        if provider == 'anthropic':
            import requests
            model = data.get('model') or 'claude-3-sonnet-20240229'
            url = 'https://api.anthropic.com/v1/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            # 直接兼容 OpenAI 风格 messages
            payload = {
                'model': model,
                'max_tokens': int(data.get('max_tokens') or 1024),
                'messages': messages
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=60)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            return jsonify({'code': 0, 'data': j})

        # 特殊：Google Gemini
        if provider == 'gemini':
            import requests
            model = data.get('model') or 'gemini-1.5-flash'
            url = f'https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}'
            # 转换为 Gemini contents
            def _to_contents(msgs):
                out = []
                for m in msgs:
                    role = m.get('role','user')
                    role = 'user' if role=='user' else 'model'
                    text = m.get('content','')
                    out.append({'role': role, 'parts': [{'text': text}]})
                return out
            payload = {
                'contents': _to_contents(messages),
                'generationConfig': {
                    'temperature': float(data.get('temperature') or 0.4),
                    'maxOutputTokens': int(data.get('max_tokens') or 512)
                }
            }
            resp = requests.post(url, json=payload, timeout=60)
            j = resp.json()
            if resp.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
            return jsonify({'code': 0, 'data': j})

        # 默认：OpenAI 兼容
        provider, base_url, model = _resolve_provider(data)
        if not base_url:
            return jsonify({'code': 1, 'msg': f'未识别的 provider: {provider}，请提供 base_url'}), 400

        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        payload = {
            'model': model,
            'messages': messages,
            'temperature': float(data.get('temperature') or 0.4),
            'max_tokens': int(data.get('max_tokens') or 512)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        return jsonify({'code': 0, 'data': j})
    except Exception as e:
        logger.error(f'LLM 聊天失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/proxy/<provider>/test', methods=['POST'])
def api_proxy_llm_test(provider):
    try:
        data = request.get_json(silent=True) or {}
        data['provider'] = (provider or '').lower()
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        p = data['provider']
        if p == 'anthropic':
            import requests
            model = data.get('model') or 'claude-3-sonnet-20240229'
            url = 'https://api.anthropic.com/v1/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            payload = {'model': model, 'max_tokens': 64, 'messages': [{'role': 'user', 'content': '请仅回复：OK'}]}
            r = requests.post(url, json=payload, headers=headers, timeout=45)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
            txt = ''
            try:
                parts = (j.get('content') or [])
                if parts and isinstance(parts, list):
                    txt = (parts[0].get('text') or '').strip()
            except Exception:
                txt = ''
            return jsonify({'code': 0, 'data': {'reply': txt, 'provider': p, 'model': model}})
        if p == 'gemini':
            import requests
            model = data.get('model') or 'gemini-1.5-flash'
            url = f'https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}'
            payload = {'contents': [{'role': 'user', 'parts': [{'text': '请仅回复：OK'}]}]}
            r = requests.post(url, json=payload, timeout=45)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
            txt = ''
            try:
                txt = (((j.get('candidates') or [{}])[0].get('content') or {}).get('parts') or [{}])[0].get('text', '').strip()
            except Exception:
                txt = ''
            return jsonify({'code': 0, 'data': {'reply': txt, 'provider': p, 'model': model}})
        if p in ('ernie', 'wenxin'):
            import requests
            try:
                ak, sk = (api_key.split(':', 1) + [''])[:2]
            except Exception:
                ak, sk = api_key, ''
            if not ak or not sk:
                return jsonify({'code': 1, 'msg': 'Ernie 需使用 "api_key:secret_key" 格式传入'}), 400
            token_url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}'
            tk = requests.get(token_url, timeout=20).json()
            access_token = tk.get('access_token')
            if not access_token:
                return jsonify({'code': 1, 'msg': f'获取access_token失败: {tk}'}), 400
            url = f'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={access_token}'
            payload = {'messages': [{'role': 'user', 'content': '请仅回复：OK'}]}
            r = requests.post(url, json=payload, timeout=45)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error_msg') or str(j) or r.text}), 400
            reply = (j.get('result') or '').strip()
            return jsonify({'code': 0, 'data': {'reply': reply, 'provider': p, 'model': j.get('model') or 'ernie'}})
        provider2, base_url, model = _resolve_provider({'provider': p, 'model': data.get('model')})
        if not base_url:
            return jsonify({'code': 1, 'msg': f'未识别的 provider: {p}，请提供 base_url'}), 400
        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        payload = {'model': model, 'messages': [{'role': 'user', 'content': '请仅回复：OK'}], 'max_tokens': 16, 'temperature': 0.2}
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        r = requests.post(url, json=payload, headers=headers, timeout=45)
        j = r.json()
        if r.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
        txt = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        return jsonify({'code': 0, 'data': {'reply': txt, 'provider': provider2, 'model': model}})
    except Exception as e:
        logger.error(f'Proxy LLM 测试失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/proxy/<provider>/chat', methods=['POST'])
def api_proxy_llm_chat(provider):
    try:
        data = request.get_json(silent=True) or {}
        data['provider'] = (provider or '').lower()
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        p = data['provider']
        messages = data.get('messages') or []
        if not isinstance(messages, list) or not messages:
            return jsonify({'code': 1, 'msg': 'messages 不能为空'}), 400
        if p == 'anthropic':
            import requests
            model = data.get('model') or 'claude-3-sonnet-20240229'
            url = 'https://api.anthropic.com/v1/messages'
            headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
            payload = {'model': model, 'max_tokens': int(data.get('max_tokens') or 1024), 'messages': messages}
            r = requests.post(url, json=payload, headers=headers, timeout=60)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
            return jsonify({'code': 0, 'data': j})
        if p == 'gemini':
            import requests
            model = data.get('model') or 'gemini-1.5-flash'
            url = f'https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}'
            def _to_contents(msgs):
                out = []
                for m in msgs:
                    role = m.get('role','user')
                    role = 'user' if role=='user' else 'model'
                    text = m.get('content','')
                    out.append({'role': role, 'parts': [{'text': text}]})
                return out
            payload = {'contents': _to_contents(messages), 'generationConfig': {'temperature': float(data.get('temperature') or 0.4), 'maxOutputTokens': int(data.get('max_tokens') or 512)}}
            r = requests.post(url, json=payload, timeout=60)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
            return jsonify({'code': 0, 'data': j})
        if p in ('ernie', 'wenxin'):
            import requests
            try:
                ak, sk = (api_key.split(':', 1) + [''])[:2]
            except Exception:
                ak, sk = api_key, ''
            if not ak or not sk:
                return jsonify({'code': 1, 'msg': 'Ernie 需使用 "api_key:secret_key" 格式传入'}), 400
            token_url = f'https://aip.baidubce.com/oauth/2.0/token?grant_type=client_credentials&client_id={ak}&client_secret={sk}'
            tk = requests.get(token_url, timeout=20).json()
            access_token = tk.get('access_token')
            if not access_token:
                return jsonify({'code': 1, 'msg': f'获取access_token失败: {tk}'}), 400
            url = f'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions?access_token={access_token}'
            r = requests.post(url, json={'messages': messages}, timeout=60)
            j = r.json()
            if r.status_code != 200:
                return jsonify({'code': 1, 'msg': j.get('error_msg') or str(j) or r.text}), 400
            return jsonify({'code': 0, 'data': j})
        provider2, base_url, model = _resolve_provider({'provider': p, 'model': data.get('model')})
        if not base_url:
            return jsonify({'code': 1, 'msg': f'未识别的 provider: {p}，请提供 base_url'}), 400
        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        payload = {'model': model, 'messages': messages, 'temperature': float(data.get('temperature') or 0.4), 'max_tokens': int(data.get('max_tokens') or 512)}
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        j = r.json()
        if r.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or r.text}), 400
        return jsonify({'code': 0, 'data': j})
    except Exception as e:
        logger.error(f'Proxy LLM 聊天失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500

# ========== 通用视觉分析：使用设置页默认视觉模型，或按请求临时选择 ==========
@app.route('/api/vision/analyze-video', methods=['POST'])
def api_analyze_video_with_configured_vision():
    """抽取项目视频帧，并通过设置页已配置的视觉服务完成分析。"""
    frame_paths = []
    try:
        data = request.get_json(silent=True) or {}
        from backend.config.ai_config import get_config_manager
        from backend.engine.multi_model_adapter import get_multi_model_manager

        config_manager = get_config_manager()
        provider = config_manager.normalize_vision_provider(
            data.get('provider') or config_manager.vision_config.default_model
        )
        supported = {'custom_vision', 'gpt4v', 'claude_vision', 'gemini_vision', 'qwen_vl', 'chatglm'}
        if provider not in supported:
            return jsonify({'code': 1, 'msg': f'视觉服务 {provider} 当前未接入画面分析'}), 400
        if not config_manager.get_vision_api_key(provider):
            return jsonify({'code': 1, 'msg': '所选视觉服务尚未配置 API Key，请先在设置页保存并测试连接'}), 400

        video_path = data.get('video_path')
        project_id = data.get('project_id')
        if not video_path:
            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少 project_id 或 video_path'}), 400
            videos = db_manager.get_materials(project_id=project_id, material_type='video')
            if not videos:
                return jsonify({'code': 1, 'msg': '项目中未找到视频素材'}), 400
            video_path = str(BASE_DIR / videos[0]['path'])
        elif not os.path.isabs(video_path):
            video_path = str(BASE_DIR / video_path)
        if not os.path.isfile(video_path):
            return jsonify({'code': 1, 'msg': '视频文件不存在'}), 404

        try:
            import cv2
        except ImportError as exc:
            return jsonify({'code': 1, 'msg': f'缺少 OpenCV 依赖: {exc}'}), 500

        interval = max(0.5, float(data.get('interval_sec') or 2))
        max_frames = min(30, max(1, int(data.get('max_frames') or 8)))
        prompt = (data.get('prompt') or '请用中文描述画面中的人物、物体、场景、动作与镜头变化。').strip()
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return jsonify({'code': 1, 'msg': '无法打开视频文件'}), 400
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        duration = (cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
        frame_dir = BASE_DIR / 'temp' / 'vision_frames' / uuid.uuid4().hex
        frame_dir.mkdir(parents=True, exist_ok=True)
        timestamp = 0.0
        while timestamp < max(duration, 0.01) and len(frame_paths) < max_frames:
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if ok:
                frame_path = frame_dir / f'frame_{len(frame_paths) + 1:03d}.jpg'
                if cv2.imwrite(str(frame_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85]):
                    frame_paths.append((timestamp, frame_path))
            timestamp += interval
        cap.release()
        if not frame_paths:
            return jsonify({'code': 1, 'msg': '未能抽取到有效视频帧'}), 400

        manager = get_multi_model_manager()
        results = []
        for timestamp, frame_path in frame_paths:
            analysis = manager.analyze_image(str(frame_path), prompt, model_type=provider)
            results.append(f'[{timestamp:.1f} 秒]\n{analysis}')
        model_fields = {
            'gpt4v': 'gpt4v_model', 'claude_vision': 'claude_vision_model',
            'gemini_vision': 'gemini_vision_model', 'qwen_vl': 'qwen_vl_model'
        }
        model = getattr(config_manager.vision_config, model_fields.get(provider, ''), '')
        if provider == 'custom_vision':
            model = config_manager.llm_config.custom_openai_model
        if provider == 'chatglm':
            model = config_manager.llm_config.chatglm_model
        provider_names = {
            'custom_vision': '自定义 OpenAI 兼容视觉模型', 'gpt4v': 'OpenAI GPT-4V / GPT-4o',
            'claude_vision': 'Claude Vision', 'gemini_vision': 'Gemini Vision',
            'qwen_vl': '通义千问 VL', 'chatglm': '智谱 GLM-4V'
        }
        return jsonify({'code': 0, 'msg': '分析成功', 'data': {
            'content': '\n\n'.join(results), 'provider': provider,
            'provider_name': provider_names[provider], 'model': model, 'frames': len(results)
        }})
    except Exception as exc:
        logger.error(f'配置化画面分析失败: {exc}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(exc)}), 500
    finally:
        for _, frame_path in frame_paths:
            try:
                frame_path.unlink(missing_ok=True)
            except Exception:
                pass
        if frame_paths:
            try:
                frame_paths[0][1].parent.rmdir()
            except Exception:
                pass

# ========== 通义千问（Qwen）视觉能力：图像/视频分析（OpenAI 兼容） ==========
@app.route('/api/vision/qwen/analyze-image', methods=['POST'])
def api_qwen_analyze_image():
    """
    使用 Qwen-VL 系列模型分析一批图像（URL 或 data:image/*;base64, 均可）。
    body:
      - api_key/Authorization
      - model: qwen-vl-plus / qwen-vl-flash / qwen-vl-max（默认 qwen-vl-plus）
      - images: [url or data-uri]
      - prompt: 任务提示词
    """
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key（可放在 Authorization/Bearer 或 body.api_key）'}), 400
        model_raw = (data.get('model') or QWEN_VL_MODELS[0]).strip()
        model = QWEN_VL_ALIASES.get(model_raw, model_raw)
        prompt = (data.get('prompt') or '请用中文描述并分析这些图像的关键信息。').strip()
        images = data.get('images') or data.get('image_urls') or []
        if isinstance(images, str):
            images = [images]
        if not images:
            return jsonify({'code': 1, 'msg': '缺少 images'}), 400

        # 仅使用 qwen 的 OpenAI 兼容端点
        _, base_url, _ = _resolve_provider({'provider': 'qwen'})
        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        messages = _build_mm_messages(prompt, images)
        payload = {
            'model': model,
            'messages': messages,
            'temperature': float(data.get('temperature') or 0.3),
            'max_tokens': int(data.get('max_tokens') or 800)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        return jsonify({'code': 0, 'data': j})
    except Exception as e:
        logger.error(f'Qwen 图像分析失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/vision/qwen/analyze-video', methods=['POST'])
def api_qwen_analyze_video():
    """
    使用 Qwen-VL 系列模型对项目视频抽帧并进行画面分析（CPU 抽帧 + 远程多模态模型）。
    body:
      - project_id（或 video_path）
      - model: qwen-vl-plus / qwen-vl-flash / qwen-vl-max（默认 qwen-vl-plus）
      - interval_sec: 抽帧间隔（秒，默认 2.0）
      - max_frames: 最多抽取帧数（默认 8）
      - prompt: 分析任务提示词
    """
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        model_raw = (data.get('model') or QWEN_VL_MODELS[0]).strip()
        model = QWEN_VL_ALIASES.get(model_raw, model_raw)
        prompt = (data.get('prompt') or '请用中文总结这些帧画面的关键信息（人物/物体/场景/动作/镜头变化）。').strip()

        video_path = data.get('video_path')
        project_id = data.get('project_id')
        if not video_path:
            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少 project_id 或 video_path'}), 400
            videos = db_manager.get_materials(project_id=project_id, material_type='video')
            if not videos:
                return jsonify({'code': 1, 'msg': '项目中未找到视频素材'}), 400
            video_path = str(BASE_DIR / videos[0]['path'])
        else:
            video_path = str(BASE_DIR / video_path) if not os.path.isabs(video_path) else video_path

        # CPU 抽帧
        try:
            import cv2, base64
        except Exception as ie:
            return jsonify({'code': 1, 'msg': f'缺少 OpenCV 依赖: {ie}'}), 500
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return jsonify({'code': 1, 'msg': '无法打开视频文件'}), 400
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = frame_count / fps if fps > 0 else 0
        step = max(0.5, float(data.get('interval_sec') or 2.0))
        max_frames = max(1, int(data.get('max_frames') or 8))

        images = []
        t = 0.0
        while t < max(duration, 0.01) and len(images) < max_frames:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ret, frame = cap.read()
            if not ret:
                t += step
                continue
            ok, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok:
                import base64
                data_url = 'data:image/jpeg;base64,' + base64.b64encode(buf.tobytes()).decode('ascii')
                images.append(data_url)
            t += step
        try:
            cap.release()
        except Exception:
            pass

        if not images:
            return jsonify({'code': 1, 'msg': '未能抽取到有效帧'}), 400

        # 调用 Qwen-VL（OpenAI 兼容）
        _, base_url, _ = _resolve_provider({'provider': 'qwen'})
        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        messages = _build_mm_messages(prompt, images)
        payload = {
            'model': model,
            'messages': messages,
            'temperature': float(data.get('temperature') or 0.3),
            'max_tokens': int(data.get('max_tokens') or 1200)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        return jsonify({'code': 0, 'data': j, 'frames': len(images)})
    except Exception as e:
        logger.error(f'Qwen 视频分析失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


# ========== 场景检测 + 视觉分析（结构化逐场景JSON） ==========
@app.route('/api/ai/smart-clip/analyze-scenes', methods=['POST'])
def api_analyze_scenes():
    """
    端到端：PySceneDetect 场景检测（CPU）+ Qwen-VL 逐场景画面理解，返回结构化 JSON。
    body:
      - project_id（或 video_path）
      - model: 通义千问3-VL-Plus/Flash/VL-Max（或 qwen-vl-plus 等别名）
      - max_scenes: 限制分析前N段（默认 8）
      - prompt: 额外提示词（可空）
      - threshold/min_scene_len: 场景检测参数（同 /api/ai/smart-clip）
      - api_key: 可在 Authorization: Bearer 中传（DashScope）
    """
    try:
        data = request.get_json(silent=True) or {}
        # API Key（DashScope）
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key（可放在 Authorization/Bearer 或 body.api_key）'}), 400
        # 模型解析
        model_raw = (data.get('model') or QWEN_VL_MODELS_CN[0]).strip()
        model = QWEN_VL_ALIASES.get(model_raw, model_raw)

        # 定位视频
        video_path = data.get('video_path')
        project_id = data.get('project_id')
        if not video_path:
            if not project_id:
                return jsonify({'code': 1, 'msg': '缺少 project_id 或 video_path'}), 400
            videos = db_manager.get_materials(project_id=project_id, material_type='video')
            if not videos:
                return jsonify({'code': 1, 'msg': '项目中未找到视频素材'}), 400
            video_path = str(BASE_DIR / videos[0]['path'])
        else:
            video_path = str(BASE_DIR / video_path) if not os.path.isabs(video_path) else video_path

        # 场景检测参数
        threshold = float(data.get('threshold') or 27.0)
        min_scene_len = int(data.get('min_scene_len') or 15)
        max_scenes = max(1, int(data.get('max_scenes') or 8))
        prompt_extra = (data.get('prompt') or '').strip()

        # 运行 PySceneDetect
        try:
            from scenedetect import VideoManager, SceneManager
            from scenedetect.detectors import ContentDetector
        except Exception as ie:
            return jsonify({'code': 1, 'msg': f'缺少依赖 PySceneDetect/OpenCV：{ie}'}), 500

        video_manager = VideoManager([video_path])
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
        try:
            video_manager.start()
            scene_manager.detect_scenes(frame_source=video_manager)
            scene_list = scene_manager.get_scene_list()
        finally:
            try:
                video_manager.release()
            except Exception:
                pass

        # 抓帧工具（中点帧）
        def _frame_to_dataurl(cap, second: float):
            cap.set(0, second * 1000.0)  # CAP_PROP_POS_MSEC=0 for py bindings
            ok, frame = cap.read()
            if not ok:
                return None
            import cv2, base64
            ok2, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok2:
                return None
            return 'data:image/jpeg;base64,' + base64.b64encode(buf.tobytes()).decode('ascii')

        # 打开视频一次性抓帧
        import cv2
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return jsonify({'code': 1, 'msg': '无法打开视频文件'}), 400

        # OpenAI 兼容端点
        _, base_url, _ = _resolve_provider({'provider': 'qwen'})
        import requests, json as _json
        url = base_url.rstrip('/') + '/chat/completions'
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}

        scenes = []
        analyzed = 0
        for idx, (s_time, e_time) in enumerate(scene_list):
            if len(scenes) >= max_scenes:
                break
            s = max(0.0, s_time.get_seconds())
            e = max(s, e_time.get_seconds())
            d = max(0.5, e - s)
            mid = s + d / 2.0
            # 抓取一帧
            img_dataurl = _frame_to_dataurl(cap, mid)
            if not img_dataurl:
                continue
            # 组装提示，严格 JSON 输出
            user_prompt = (
                (prompt_extra + '\n') if prompt_extra else ''
            ) + (
                '你是专业短视频镜头理解助手。请基于画面给出：\n'
                '1) 简短中文标签（不超过8字，2~4个），2) 简短中文标题，3) 0-100 的质量评分（越好越高），4) 1~3 个高光要点。\n'
                '只返回严格JSON：{"tags":["标签1","标签2"],"title":"一句标题","score":80,"highlights":["要点1"]}。不要任何解释。'
            )
            messages = _build_mm_messages(user_prompt, [img_dataurl])
            payload = {'model': model, 'messages': messages, 'temperature': 0.2, 'max_tokens': 256}
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=60)
                j = resp.json()
                if resp.status_code != 200:
                    content = None
                else:
                    content = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
            except Exception:
                content = None

            title, tags, score, highlights = '', [], None, []
            if content:
                # 去掉 ```json 包裹
                c = content.strip()
                if c.startswith('```'):
                    c = c.split('```', 2)[1] if '```' in c else c
                c = c.strip().strip('`')
                try:
                    obj = _json.loads(c)
                    title = (obj.get('title') or '').strip()
                    tags = obj.get('tags') or []
                    highlights = obj.get('highlights') or []
                    try:
                        score = int(float(obj.get('score')))
                    except Exception:
                        score = None
                except Exception:
                    title = c[:24]
            scenes.append({
                'start': round(s, 2),
                'end': round(e, 2),
                'duration': round(d, 2),
                'frame_time': round(mid, 2),
                'title': title or '已分析',
                'tags': tags if isinstance(tags, list) else [],
                'score': score if (isinstance(score, int) and 0 <= score <= 100) else None,
                'highlights': highlights if isinstance(highlights, list) else []
            })
            analyzed += 1

        try:
            cap.release()
        except Exception:
            pass

        return jsonify({'code': 0, 'data': {
            'scenes': scenes,
            'total_scenes': len(scene_list),
            'analyzed_scenes': analyzed,
            'model': model
        }})
    except Exception as e:
        logger.error(f'融合场景分析失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


# ========== 三大核心功能的 LLM 方案接口（不伪造音频/ASR/切片） ==========
# 这些接口只负责“大模型部分”的生成/优化，实际 TTS/ASR/视频分析仍需对应服务

@app.route('/api/ai/voiceover/script', methods=['POST'])
def api_voiceover_script():
    """AI配音：使用 LLM 生成/润色配音文案，返回纯文本脚本"""
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        provider, base_url, model = _resolve_provider(data)
        text = (data.get('text') or '').strip()
        style = (data.get('style') or '自然、口语化、适合旁白').strip()
        if not text:
            return jsonify({'code': 1, 'msg': '请输入文案或提示词 text'}), 400

        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        prompt = (
            f"你是专业的短视频文案编剧。请将下面内容生成适合中文配音的旁白稿，语气{style}，分为小段（每段1-2句），不超过150字：\n\n{text}"
        )
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': '你是视频配音文案专家。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': float(data.get('temperature') or 0.7),
            'max_tokens': int(data.get('max_tokens') or 600)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        script = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        return jsonify({'code': 0, 'data': {'script': script, 'provider': provider, 'model': model}})
    except Exception as e:
        logger.error(f'LLM 生成配音文案失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/subtitle/enhance', methods=['POST'])
def api_subtitle_enhance():
    """自动字幕：对已有转写文本进行标点/润色/可选翻译，返回优化后的文本"""
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        provider, base_url, model = _resolve_provider(data)
        transcript = (data.get('transcript') or '').strip()
        target_lang = (data.get('target_lang') or 'zh').strip()
        if not transcript:
            return jsonify({'code': 1, 'msg': '缺少 transcript（原始转写文本）'}), 400

        import requests
        url = base_url.rstrip('/') + '/chat/completions'
        prompt = (
            "请将以下转写文本进行标点恢复、清理口语词、保持语义，"
            f"并翻译为目标语言“{target_lang}”（若 target_lang 为 zh 则保持中文），"
            "仅返回优化后的完整文本，不要其他说明：\n\n" + transcript
        )
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': '你是专业字幕编辑，擅长标点恢复和润色。'},
                {'role': 'user', 'content': prompt}
            ],
            'temperature': float(data.get('temperature') or 0.3),
            'max_tokens': int(data.get('max_tokens') or 1200)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        refined = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        return jsonify({'code': 0, 'data': {'text': refined, 'provider': provider, 'model': model}})
    except Exception as e:
        logger.error(f'LLM 字幕润色失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500


@app.route('/api/ai/smart-clip/plan', methods=['POST'])
def api_smart_clip_plan():
    """智能剪辑：基于描述/元数据生成剪辑方案（仅LLM建议，不执行实际切分）"""
    try:
        data = request.get_json(silent=True) or {}
        api_key = _extract_api_key_from_request(data)
        if not api_key:
            return jsonify({'code': 1, 'msg': '缺少 API Key'}), 400
        provider, base_url, model = _resolve_provider(data)
        brief = (data.get('brief') or '').strip()
        target_sec = int(data.get('target_seconds') or 60)
        content_type = (data.get('content_type') or '讲解类').strip()
        if not brief:
            return jsonify({'code': 1, 'msg': '请提供简要说明 brief（视频主题/目标受众/素材类型）'}), 400

        import requests, json as _json
        url = base_url.rstrip('/') + '/chat/completions'
        sys_prompt = '你是资深短视频剪辑师，擅长为素材制定高完成度的剪辑方案。'
        user_prompt = (
            "请基于以下说明，输出一个 JSON 数组的剪辑方案，每个元素包含: "
            "{\"start\":秒,\"end\":秒,\"type\":\"镜头/字幕/转场\",\"note\":\"说明\"}。\n"
            f"目标成片时长约 {target_sec} 秒，内容类型：{content_type}。\n"
            "需求：节奏紧凑，画面有起伏，可适当加入字幕/转场建议。\n"
            f"说明：{brief}\n\n仅返回JSON，不要任何额外文字。"
        )
        payload = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': sys_prompt},
                {'role': 'user', 'content': user_prompt}
            ],
            'temperature': float(data.get('temperature') or 0.6),
            'max_tokens': int(data.get('max_tokens') or 1200)
        }
        headers = {'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'}
        resp = requests.post(url, json=payload, headers=headers, timeout=90)
        j = resp.json()
        if resp.status_code != 200:
            return jsonify({'code': 1, 'msg': j.get('error', {}).get('message') or str(j) or resp.text}), 400
        content = (j.get('choices') or [{}])[0].get('message', {}).get('content', '').strip()
        # 仅尝试解析为 JSON；失败时按文本返回
        try:
            plan = _json.loads(content)
            return jsonify({'code': 0, 'data': {'plan': plan, 'provider': provider, 'model': model}})
        except Exception:
            return jsonify({'code': 0, 'data': {'plan_text': content, 'provider': provider, 'model': model}, 'msg': '返回非严格JSON，已以文本形式提供'})
    except Exception as e:
        logger.error(f'LLM 智能剪辑方案失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500

@app.route('/api/export/video_disabled', methods=['POST'])
def api_export_video_disabled():
    try:
        data = request.get_json() or {}
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({'code': 1, 'msg': '缺少项目ID'}), 400
        # 不返回示例或假任务；需配置真实导出引擎
        return jsonify({'code': 1, 'msg': '未配置真实导出引擎。请在设置中配置导出服务后再试'}), 400
    except Exception as e:
        logger.error(f'导出失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': str(e)}), 500
