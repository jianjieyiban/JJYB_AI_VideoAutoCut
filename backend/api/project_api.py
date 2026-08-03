# -*- coding: utf-8 -*-
"""
Project API
项目管理API路由
"""

import logging
import os
import shutil
import time
import json
from flask import request, jsonify
from werkzeug.utils import secure_filename
from pathlib import Path
import uuid

from backend.config.paths import TEMP_DIR, PROJECT_ROOT
from backend.engine.video_processor import VideoProcessor

logger = logging.getLogger(__name__)
_video_processor = None


def _json_object(value):
    """将数据库 JSON 字段规范化为对象，损坏数据按空对象处理。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _normalize_project(project):
    if not project:
        return project
    project['config'] = _json_object(project.get('config'))
    if 'result' in project:
        project['result'] = _json_object(project.get('result'))
    for material in project.get('materials') or []:
        _normalize_material(material)
    # 封面字段兼容：thumbnail/cover_url 双字段，保证旧代码和新代码都能读到
    t = project.get('thumbnail')
    c = project.get('cover_url')
    if not c and t:
        project['cover_url'] = t
    if not t and c:
        project['thumbnail'] = c
    # 关键修复：校验 config.video_path / config.videoPath 对应文件是否真的存在，
    # 不存在则打标 video_exists=False，前端可据此过滤「手动删了文件但 DB 还存着」的幽灵引用
    cfg = project.setdefault('config', {}) or {}
    raw_vpath = (cfg.get('video_path') if isinstance(cfg, dict) else None) or \
                (cfg.get('videoPath') if isinstance(cfg, dict) else None)
    project['video_path'] = raw_vpath if isinstance(raw_vpath, str) else None
    project['video_exists'] = False
    if isinstance(raw_vpath, str) and raw_vpath.strip():
        try:
            normalized_path = raw_vpath.strip().replace('\\', '/')
            candidate = Path(normalized_path)
            if not candidate.is_absolute():
                candidate = PROJECT_ROOT / normalized_path.lstrip('/')
            candidate = candidate.resolve()
            project['video_exists'] = bool(candidate.exists() and candidate.is_file())
            # API 路径统一为正斜杠，绝对路径仅供诊断
            project['video_path'] = normalized_path
            project['video_path_abs'] = str(candidate)
        except Exception:
            project['video_exists'] = False
    return project


def _get_video_processor():
    global _video_processor
    if _video_processor is None:
        _video_processor = VideoProcessor()
    return _video_processor


def _resolve_material_path(value):
    raw = str(value or '').strip().replace('\\', '/')
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def _normalize_material(material):
    material['metadata'] = _json_object(material.get('metadata'))
    path = _resolve_material_path(material.get('path'))
    exists = bool(path and path.is_file())
    material['exists'] = exists
    material['absolute_path'] = str(path) if path else ''
    if exists:
        if not material.get('name') or str(material.get('name')).startswith('素材视频'):
            material['name'] = path.name
        if int(material.get('size') or 0) <= 0:
            try:
                material['size'] = path.stat().st_size
            except OSError:
                material['size'] = 0
        if str(material.get('type') or '').lower() == 'video' and float(material.get('duration') or 0) <= 0:
            try:
                info = _get_video_processor().get_video_info(str(path)) or {}
                material['duration'] = float(info.get('duration') or 0)
                material['metadata'].update({
                    'width': info.get('width', 0),
                    'height': info.get('height', 0),
                    'fps': info.get('fps', 0),
                    'codec': info.get('codec', ''),
                    'has_audio': bool(info.get('has_audio', False)),
                })
            except Exception as exc:
                logger.warning('补全素材视频信息失败 %s: %s', path, exc)
    return material


def register_project_routes(app, db_manager):
    """
    注册项目管理相关的API路由

    Args:
        app: Flask应用实例
        db_manager: 数据库管理器实例
    """

    @app.route('/api/projects', methods=['GET'])
    def get_projects():
        """获取所有项目"""
        try:
            # 获取查询参数
            project_type = request.args.get('type')
            limit = request.args.get('limit', type=int)
            sort = request.args.get('sort', 'updated_at')
            order = request.args.get('order', 'desc')

            # 获取项目列表
            projects = db_manager.get_all_projects(project_type)
            projects = [_normalize_project(project) for project in (projects or [])]

            # 如果没有项目，返回空列表
            if not projects:
                projects = []

            # 先保存总数量（在排序、限制之前）
            total_count = len(projects) if isinstance(projects, list) else 0

            # 排序
            if sort and isinstance(projects, list):
                reverse = (order == 'desc')
                try:
                    projects.sort(key=lambda x: x.get(sort, ''), reverse=reverse)
                except:
                    pass

            # 限制数量
            if limit and isinstance(projects, list):
                projects = projects[:limit]

            # 返回符合前端期望的格式
            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'projects': projects,
                    'total': total_count
                }
            })
        except Exception as e:
            logger.error(f'获取项目列表失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': {'projects': [], 'total': 0}
            }), 500

    @app.route('/api/projects/<project_id>', methods=['GET'])
    def get_project(project_id):
        """获取项目详情"""
        try:
            project = _normalize_project(db_manager.get_project(project_id))
            if project:
                return jsonify({'code': 0, 'msg': '获取成功', 'data': project})
            else:
                return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404
        except Exception as e:
            logger.error(f'获取项目详情失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500

    @app.route('/api/projects', methods=['POST'])
    def create_project():
        """创建项目"""
        try:
            data = request.get_json()
            if not data or 'name' not in data or 'type' not in data:
                return jsonify({'code': 1, 'msg': '参数错误：缺少name或type', 'data': None}), 400

            project = db_manager.create_project(
                name=data.get('name'),
                project_type=data.get('type'),
                description=data.get('description', ''),
                template=data.get('template')
            )
            updates = {key: data[key] for key in ('config', 'result') if isinstance(data.get(key), dict)}
            if updates:
                project = db_manager.update_project(project['id'], updates)
            return jsonify({'code': 0, 'msg': '创建成功', 'data': _normalize_project(project)})
        except Exception as e:
            logger.error(f'创建项目失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500

    @app.route('/api/projects/<project_id>', methods=['PUT'])
    def update_project(project_id):
        """更新项目"""
        try:
            data = request.get_json() or {}
            existing = _normalize_project(db_manager.get_project(project_id))
            if not existing:
                return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404
            for key in ('config', 'result'):
                if isinstance(data.get(key), dict):
                    merged = _json_object(existing.get(key))
                    merged.update(data[key])
                    data[key] = merged
            project = db_manager.update_project(project_id, data)
            if project:
                return jsonify({'code': 0, 'msg': '更新成功', 'data': _normalize_project(project)})
            return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404
        except Exception as e:
            logger.error(f'更新项目失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'更新失败: {str(e)}', 'data': None}), 500

    @app.route('/api/projects/<project_id>', methods=['DELETE'])
    def delete_project(project_id):
        """删除项目"""
        try:
            db_manager.delete_project(project_id)
            return jsonify({'code': 0, 'msg': '删除成功', 'data': None})
        except Exception as e:
            logger.error(f'删除项目失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'删除失败: {str(e)}', 'data': None}), 500

    @app.route('/api/projects/<project_id>/clear-video-path', methods=['POST'])
    def clear_project_video_path(project_id):
        """仅清除项目配置中保存的 video_path/videoPath 引用，不删除项目也不删磁盘文件。
        用于：用户已经手动删除了源视频，但项目配置里还存着旧路径，导致列表里出现幽灵条目。
        清除后该项目将不再出现在素材选择器中。"""
        try:
            existing = _normalize_project(db_manager.get_project(project_id))
            if not existing:
                return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404
            merged = _json_object(existing.get('config'))
            before = bool(merged.get('video_path') or merged.get('videoPath'))
            merged.pop('video_path', None)
            merged.pop('videoPath', None)
            after = bool(merged.get('video_path') or merged.get('videoPath'))
            updated = db_manager.update_project(project_id, {'config': merged})
            cleared = before and not after
            logger.info(f'🧹 项目 {project_id} video_path 清除: before_video={before}, after_video={after}')
            return jsonify({
                'code': 0,
                'msg': '清除成功' if cleared else '项目中本来就没有 video_path',
                'data': {'cleared': cleared, 'project': _normalize_project(updated)}
            })
        except Exception as e:
            logger.error(f'清除项目 video_path 失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'清除失败: {str(e)}', 'data': None}), 500

    @app.route('/api/materials', methods=['GET'])
    def get_materials():
        """获取素材列表"""
        try:
            project_id = request.args.get('project_id')
            materials = [_normalize_material(material) for material in (db_manager.get_materials(project_id) or [])]
            return jsonify({'code': 0, 'msg': '获取成功', 'data': materials})
        except Exception as e:
            logger.error(f'获取素材列表失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500

    @app.route('/api/materials', methods=['POST'])
    def create_material():
        """创建素材"""
        try:
            data = request.get_json()
            material = db_manager.create_material(
                project_id=data.get('project_id'),
                material_type=data.get('type'),
                name=data.get('name'),
                path=data.get('path'),
                size=data.get('size', 0),
                duration=data.get('duration', 0),
                metadata=data.get('metadata')
            )
            return jsonify({'code': 0, 'msg': '创建成功', 'data': material})
        except Exception as e:
            logger.error(f'创建素材失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500

    @app.route('/api/upload', methods=['POST'])
    def upload_file():
        """上传文件"""
        try:
            if 'file' not in request.files:
                return jsonify({'code': 1, 'msg': '没有文件', 'data': None}), 400

            file = request.files['file']
            if file.filename == '':
                return jsonify({'code': 1, 'msg': '文件名为空', 'data': None}), 400

            filename = secure_filename(file.filename)
            file_id = str(uuid.uuid4())
            file_ext = Path(filename).suffix
            save_filename = f"{file_id}{file_ext}"

            file_type = request.form.get('type', 'other')
            upload_dir = Path(app.config['UPLOAD_FOLDER']) / file_type
            upload_dir.mkdir(parents=True, exist_ok=True)

            save_path = upload_dir / save_filename
            file.save(str(save_path))

            file_size = save_path.stat().st_size
            upload_root = Path(app.config['UPLOAD_FOLDER']).resolve()
            relative_path = save_path.resolve().relative_to(upload_root.parent).as_posix()

            return jsonify({
                'code': 0,
                'msg': '上传成功',
                'data': {
                    'file_id': file_id,
                    'filename': filename,
                    'path': relative_path,
                    'size': file_size,
                    'type': file_type
                }
            })
        except Exception as e:
            logger.error(f'文件上传失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'上传失败: {str(e)}', 'data': None}), 500

    @app.route('/api/project/stats', methods=['GET'])
    def get_project_stats():
        """获取项目统计信息"""
        try:
            # 获取所有项目
            projects = db_manager.get_all_projects()

            # 统计数据
            total = len(projects)
            processing = sum(1 for p in projects if p.get('status') == 'processing')
            completed = sum(1 for p in projects if p.get('status') == 'completed')
            failed = sum(1 for p in projects if p.get('status') == 'failed')

            stats = {
                'total': total,
                'processing': processing,
                'completed': completed,
                'failed': failed,
                'success_rate': f'{(completed / total * 100):.1f}%' if total > 0 else '0%'
            }

            logger.info(f'📊 项目统计: 总计{total}, 处理中{processing}, 已完成{completed}')

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': stats
            })

        except Exception as e:
            logger.error(f'❌ 获取项目统计失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/activity/timeline', methods=['GET'])
    def get_activity_timeline():
        """获取活动时间线"""
        try:
            limit = int(request.args.get('limit', 20))

            # 获取最近的项目活动
            projects = db_manager.get_all_projects()

            # 构建活动时间线
            activities = []
            for project in projects[:limit]:
                activity = {
                    'id': project.get('id'),
                    'type': 'project',
                    'action': project.get('status', 'created'),
                    'title': project.get('name', '未命名项目'),
                    'description': f"项目{project.get('status', '创建')}",
                    'timestamp': project.get('created_at', project.get('updated_at')),
                    'user': 'System'
                }
                activities.append(activity)

            # 按时间倒序排序
            activities.sort(key=lambda x: x.get('timestamp', 0), reverse=True)

            logger.info(f'📅 获取活动时间线: {len(activities)}条记录')

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {'activities': activities[:limit]}
            })

        except Exception as e:
            logger.error(f'❌ 获取活动时间线失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/activity/<activity_id>', methods=['DELETE'])
    def delete_activity(activity_id):
        """删除活动记录"""
        try:
            # 这里删除活动实际上是删除对应的项目
            # 因为活动是基于项目生成的
            result = db_manager.delete_project(activity_id)

            if result:
                logger.info(f'🗑️ 删除活动记录成功: {activity_id}')
                return jsonify({
                    'code': 0,
                    'msg': '删除成功',
                    'data': {'id': activity_id}
                })
            else:
                return jsonify({
                    'code': 1,
                    'msg': '活动记录不存在',
                    'data': None
                }), 404

        except Exception as e:
            logger.error(f'❌ 删除活动记录失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'删除失败: {str(e)}',
                'data': None
            }), 500

    @app.route('/api/projects/batch-delete', methods=['POST'])
    def batch_delete_projects():
        """批量删除项目"""
        try:
            data = request.get_json()
            project_ids = data.get('project_ids', [])

            if not project_ids:
                return jsonify({
                    'code': 1,
                    'msg': '请选择要删除的项目',
                    'data': None
                }), 400

            # 删除所有指定的项目
            deleted_count = 0
            for project_id in project_ids:
                if db_manager.delete_project(project_id):
                    deleted_count += 1

            logger.info(f'🗑️ 批量删除项目成功: {deleted_count}/{len(project_ids)}')

            return jsonify({
                'code': 0,
                'msg': f'成功删除{deleted_count}个项目',
                'data': {
                    'deleted_count': deleted_count,
                    'total': len(project_ids)
                }
            })

        except Exception as e:
            logger.error(f'❌ 批量删除项目失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'批量删除失败: {str(e)}',
                'data': None
            }), 500

    def _get_gpu_info():
        """获取GPU信息（尝试多种方式）"""
        # 方式1: 通过wmi（Windows）
        try:
            import wmi
            c = wmi.WMI()
            gpus = []
            for gpu in c.Win32_VideoController():
                gpus.append(gpu.Name)
            if gpus:
                return ' / '.join(gpus[:2])
        except Exception:
            pass

        # 方式2: 通过nvidia-smi
        try:
            import shutil
            from subprocess import check_output
            nvidia_smi = shutil.which('nvidia-smi')
            if nvidia_smi:
                out = check_output([nvidia_smi, '-L'], timeout=5).decode('utf-8', errors='ignore')
                import re
                gpu_names = re.findall(r'GPU \d+: (.+?)\s*\(', out)
                if gpu_names:
                    return ' / '.join(gpu_names[:2])
        except Exception:
            pass

        # 方式3: 通过platform.processor（不太准确，作为兜底）
        try:
            import platform
            proc = platform.processor()
            if proc and 'graphic' in proc.lower():
                return proc
        except Exception:
            pass

        return '检测中...'

    @app.route('/api/system/metrics', methods=['GET'])
    def get_system_metrics():
        """获取系统实时指标（用于设置页动态展示）"""
        try:
            base_dir = Path(__file__).parent.parent.parent

            def dir_size(path: Path) -> int:
                total = 0
                try:
                    if path.exists():
                        for root, dirs, files in os.walk(str(path)):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    total += os.path.getsize(fp)
                                except Exception:
                                    pass
                except Exception:
                    pass
                return total

            # 存储统计
            uploads_dir = base_dir / 'uploads'
            output_dir = base_dir / 'output'
            database_file = Path(getattr(db_manager, 'db_path', base_dir / 'database' / 'jjyb_ai.db'))

            app_used = dir_size(uploads_dir) + dir_size(output_dir)
            try:
                app_used += database_file.stat().st_size if database_file.exists() else 0
            except Exception:
                pass

            du = shutil.disk_usage(str(base_dir))
            storage = {
                'disk_total': du.total,
                'disk_used': du.total - du.free,
                'disk_free': du.free,
                'app_used': app_used,
                'uploads': dir_size(uploads_dir),
                'output': dir_size(output_dir),
                'cache': dir_size(TEMP_DIR),
                'database': (database_file.stat().st_size if database_file.exists() else 0)
            }

            # 项目统计
            projects = db_manager.get_all_projects()
            total = len(projects or [])
            processing = sum(1 for p in (projects or []) if str(p.get('status', '')).lower() in ('processing', 'running'))
            completed = sum(1 for p in (projects or []) if str(p.get('status', '')).lower() == 'completed')
            proj_stats = {
                'total': total,
                'processing': processing,
                'completed': completed
            }

            # API配置状态
            tts_default = ''
            try:
                from backend.config.ai_config import get_config_manager
                cfg = get_config_manager()
                keys = [
                    # LLM
                    getattr(cfg.llm_config, 'openai_api_key', ''),
                    (getattr(cfg.llm_config, 'claude_api_key', '') or getattr(cfg.llm_config, 'anthropic_api_key', '')),
                    getattr(cfg.llm_config, 'gemini_api_key', ''),
                    (getattr(cfg.llm_config, 'qwen_api_key', '') or getattr(cfg.llm_config, 'tongyi_api_key', '')),
                    (getattr(cfg.llm_config, 'ernie_api_key', '') or getattr(cfg.llm_config, 'wenxin_api_key', '')),
                    getattr(cfg.llm_config, 'chatglm_api_key', ''),
                    getattr(cfg.llm_config, 'deepseek_api_key', ''),
                    getattr(cfg.llm_config, 'kimi_api_key', ''),
                    getattr(cfg.llm_config, 'custom_openai_api_key', ''),
                    # Vision
                    (getattr(cfg.vision_config, 'qwen_vl_api_key', '') or getattr(cfg.vision_config, 'tongyi_vl_api_key', '')),
                    getattr(cfg.vision_config, 'baidu_vision_api_key', ''),
                    getattr(cfg.vision_config, 'gemini_vision_api_key', ''),
                    (getattr(cfg.vision_config, 'gpt4v_api_key', '') or getattr(cfg.vision_config, 'openai_vision_api_key', '')),
                    # TTS
                    (getattr(cfg.tts_model_config, 'azure_tts_key', '') or getattr(cfg.tts_model_config, 'azure_subscription_key', '')),
                ]
                api_configured = sum(1 for v in keys if v)
                # 默认TTS引擎
                tts_default = getattr(cfg.tts_model_config, 'default_tts', '')
            except Exception:
                api_configured = 0

            # 引擎状态
            engines_count = 0
            try:
                from backend.core.global_state import get_global_state
                gs = get_global_state()
                eng = gs.get_system_status().get('engines_loaded', {})
                engines_count = sum(1 for v in eng.values() if v)
                system_state = gs.get_system_status()
            except Exception:
                system_state = {}

            # 运行时长（秒）
            try:
                app_start = getattr(db_manager, 'app_start_time', None)
                uptime_seconds = max(0, int(time.time() - app_start)) if app_start else 0
            except Exception:
                uptime_seconds = 0

            # 系统详细信息
            system_info = {}
            try:
                import platform
                system_info['os'] = f"{platform.system()} {platform.release()} ({platform.version()})"
                system_info['python'] = platform.python_version()

                # CPU信息
                try:
                    import psutil
                    system_info['cpu'] = f"{psutil.cpu_count(logical=True)}核 {platform.processor() or 'CPU'}"
                    mem = psutil.virtual_memory()
                    system_info['memory'] = f"{round(mem.total / (1024**3), 1)} GB"
                except Exception:
                    system_info['cpu'] = f"{os.cpu_count() or '?'}核 {platform.processor() or 'CPU'}"
                    system_info['memory'] = '检测中...'

                # GPU信息（尝试通过各种方式获取）
                try:
                    gpu_info = _get_gpu_info()
                    system_info['gpu'] = gpu_info
                except Exception:
                    system_info['gpu'] = '检测中...'

                # FFmpeg版本
                try:
                    from subprocess import check_output
                    ffmpeg_path = shutil.which('ffmpeg')
                    if ffmpeg_path:
                        try:
                            out = check_output([ffmpeg_path, '-version'], timeout=5).decode('utf-8', errors='ignore')
                            import re
                            match = re.search(r'ffmpeg version (\S+)', out)
                            if match:
                                system_info['ffmpeg'] = match.group(1)
                            else:
                                system_info['ffmpeg'] = '已安装'
                        except Exception:
                            system_info['ffmpeg'] = '已安装'
                    else:
                        system_info['ffmpeg'] = '未检测到'
                except Exception:
                    system_info['ffmpeg'] = '检测中...'

            except Exception as e:
                logger.warning(f'获取系统信息失败: {e}')
                system_info = {
                    'os': '检测中',
                    'cpu': '检测中',
                    'memory': '检测中',
                    'gpu': '检测中',
                    'python': '检测中',
                    'ffmpeg': '检测中'
                }

            try:
                from backend import __version__ as app_version
                system_info['version'] = str(app_version)
            except Exception:
                system_info['version'] = '3.0.0'
            try:
                config_file = base_dir / 'config' / 'config.yaml'
                system_info['updated_date'] = (
                    time.strftime('%Y-%m-%d', time.localtime(config_file.stat().st_mtime))
                    if config_file.exists() else '本地构建'
                )
            except Exception:
                system_info['updated_date'] = '本地构建'

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'storage': storage,
                    'projects': proj_stats,
                    'api': {
                        'configured_count': api_configured
                    },
                    'system': {
                        'engines_loaded_count': engines_count,
                        'status': system_state,
                        'uptime_seconds': uptime_seconds,
                        'tts_default': tts_default,
                        'os': system_info.get('os', ''),
                        'cpu': system_info.get('cpu', ''),
                        'memory': system_info.get('memory', ''),
                        'gpu': system_info.get('gpu', ''),
                        'python': system_info.get('python', ''),
                        'ffmpeg': system_info.get('ffmpeg', ''),
                        'version': system_info.get('version', '3.0.0'),
                        'updated_date': system_info.get('updated_date', '本地构建')
                    }
                }
            })
        except Exception as e:
            logger.error(f'❌ 获取系统指标失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/status-bar', methods=['GET'])
    def get_status_bar():
        """获取底部状态栏数据"""
        try:
            base_dir = Path(__file__).parent.parent.parent

            def dir_size(path: Path) -> int:
                total = 0
                try:
                    if path.exists():
                        for root, dirs, files in os.walk(str(path)):
                            for f in files:
                                fp = os.path.join(root, f)
                                try:
                                    total += os.path.getsize(fp)
                                except Exception:
                                    pass
                except Exception:
                    pass
                return total

            def human_size(n: int) -> str:
                if n < 1024:
                    return f"{n} B"
                elif n < 1048576:
                    return f"{n / 1024:.1f} KB"
                elif n < 1073741824:
                    return f"{n / 1048576:.1f} MB"
                else:
                    return f"{n / 1073741824:.2f} GB"

            def human_duration(seconds: float) -> str:
                s = int(seconds)
                h = s // 3600
                m = (s % 3600) // 60
                sec = s % 60
                return f"{h:02d}:{m:02d}:{sec:02d}"

            uploads_dir = base_dir / 'uploads'
            output_dir = base_dir / 'output'
            database_file = Path(getattr(db_manager, 'db_path', base_dir / 'database' / 'jjyb_ai.db'))

            app_used = dir_size(uploads_dir) + dir_size(output_dir)
            try:
                app_used += database_file.stat().st_size if database_file.exists() else 0
            except Exception:
                pass

            project_id = request.args.get('project_id')
            project_info = None
            project_size = 0
            project_duration = 0

            if project_id:
                project = db_manager.get_project(project_id)
                if project:
                    project_info = {
                        'id': project.get('id'),
                        'name': project.get('name'),
                        'status': project.get('status')
                    }
                    stats = db_manager.get_project_material_stats(project_id)
                    project_size = stats.get('total_size', 0)
                    project_duration = stats.get('total_duration', 0)

            storage = {
                'app_used': app_used,
                'app_used_human': human_size(app_used),
                'project_size': project_size,
                'project_size_human': human_size(project_size) if project_size > 0 else '',
                'project_duration': project_duration,
                'project_duration_human': human_duration(project_duration) if project_duration > 0 else ''
            }

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'project': project_info,
                    'storage': storage,
                    'version': 'v3.1.0'
                }
            })
        except Exception as e:
            logger.error(f'❌ 获取状态栏数据失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/projects/<project_id>/tracks', methods=['GET'])
    def get_project_tracks(project_id):
        """获取项目统一时间线 tracks"""
        try:
            project = db_manager.get_project(project_id)
            if not project:
                return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404

            import json as _json
            raw_config = project.get('config')
            if isinstance(raw_config, str):
                try:
                    config = _json.loads(raw_config) if raw_config else {}
                except Exception:
                    config = {}
            elif isinstance(raw_config, dict):
                config = raw_config
            else:
                config = {}

            tracks = config.get('tracks') or []
            return jsonify({'code': 0, 'msg': '获取成功', 'data': {'tracks': tracks}})
        except Exception as e:
            logger.error(f'❌ 获取项目tracks失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    @app.route('/api/projects/<project_id>/tracks', methods=['PUT'])
    def update_project_tracks(project_id):
        """保存编辑器时间线 tracks 到项目 config（合并模式，不覆盖其他配置字段）"""
        try:
            project = db_manager.get_project(project_id)
            if not project:
                return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404

            import json as _json
            data = request.get_json() or {}
            new_tracks = data.get('tracks')
            if not isinstance(new_tracks, list):
                return jsonify({'code': 1, 'msg': 'tracks 必须是数组', 'data': None}), 400

            raw_config = project.get('config')
            if isinstance(raw_config, str):
                try:
                    config = _json.loads(raw_config) if raw_config else {}
                except Exception:
                    config = {}
            elif isinstance(raw_config, dict):
                config = raw_config
            else:
                config = {}

            config['tracks'] = new_tracks
            db_manager.update_project(project_id, {'config': config})
            return jsonify({'code': 0, 'msg': '保存成功', 'data': {'tracks': new_tracks}})
        except Exception as e:
            logger.error(f'❌ 保存项目tracks失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500

    logger.info('✅ 项目管理API路由注册完成')
