#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
素材管理API路由
处理素材的上传、下载、列表等功能
"""

from flask import jsonify, request, send_file
from loguru import logger
import os
from pathlib import Path
from werkzeug.utils import secure_filename
from backend.config.paths import PROJECT_ROOT
import time


def register_material_routes(app, db_manager):
    """
    注册素材管理API路由

    Args:
        app: Flask应用实例
        db_manager: 数据库管理器实例
    """

    # 素材存储目录
    # Always use the project-root upload directory.  Relative paths depended on
    # the process working directory and made the material library report files
    # that the preview/download route could not subsequently resolve.
    MATERIALS_DIR = PROJECT_ROOT / 'uploads' / 'materials'
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)

    # 素材扫描目录（列表/下载/删除共用）
    BASE_UPLOADS = PROJECT_ROOT / 'uploads'
    SCAN_DIRS = [
        MATERIALS_DIR,
        BASE_UPLOADS / 'videos',
        BASE_UPLOADS / 'audios',
        BASE_UPLOADS / 'images',
        BASE_UPLOADS / 'commentary_videos',
        BASE_UPLOADS / 'remix_videos'
    ]

    def _resolve_managed_path(value):
        """统一解析前端传入的视频路径。

        接受 Windows/URL 两种分隔符；相对路径固定相对项目根目录，避免 Flask
        进程工作目录变化导致“刚上传就不存在”的误判。
        """
        text = str(value or '').strip().replace('\\', '/').lstrip('/')
        if not text:
            raise ValueError('路径为空')
        raw = Path(text)
        candidate = (raw if raw.is_absolute() else (PROJECT_ROOT / raw)).resolve()
        candidate.relative_to(PROJECT_ROOT.resolve())
        return candidate, text

    def _find_material_file(material_id):
        """在所有素材目录中精确匹配 file_path.stem == material_id 的文件"""
        for d in SCAN_DIRS:
            try:
                if not d.exists():
                    continue
                for fp in d.glob('*'):
                    if fp.is_file() and fp.stem == material_id:
                        return fp
            except Exception:
                continue
        return None

    # 允许的文件类型
    ALLOWED_EXTENSIONS = {
        'video': {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'},
        'audio': {'mp3', 'wav', 'aac', 'm4a', 'ogg', 'flac'},
        'image': {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'},
        'subtitle': {'srt', 'ass', 'vtt'}
    }

    def allowed_file(filename, file_type='video'):
        """检查文件类型是否允许"""
        if '.' not in filename:
            return False
        ext = filename.rsplit('.', 1)[1].lower()
        return ext in ALLOWED_EXTENSIONS.get(file_type, set())


    @app.route('/api/upload/material', methods=['POST'])
    def upload_material():
        """上传素材文件"""
        try:
            # 检查是否有文件
            if 'file' not in request.files:
                return jsonify({
                    'code': 1,
                    'msg': '没有文件被上传',
                    'data': None
                }), 400

            file = request.files['file']

            if file.filename == '':
                return jsonify({
                    'code': 1,
                    'msg': '文件名为空',
                    'data': None
                }), 400

            # 获取文件类型
            file_type = request.form.get('type', 'video')

            # 验证文件类型
            if not allowed_file(file.filename, file_type):
                return jsonify({
                    'code': 1,
                    'msg': f'不支持的文件类型',
                    'data': None
                }), 400

            # 安全的文件名
            filename = secure_filename(file.filename)
            timestamp = int(time.time() * 1000)
            safe_filename = f"{timestamp}_{filename}"

            # 保存文件
            file_path = MATERIALS_DIR / safe_filename
            file.save(str(file_path))

            # 获取文件信息
            file_size = os.path.getsize(file_path)

            # 记录到数据库（如果需要）
            material_data = {
                'id': file_path.stem,
                'filename': filename,
                'safe_filename': safe_filename,
                'file_type': file_type,
                'file_size': file_size,
                'file_path': str(file_path),
                'upload_time': timestamp
            }

            logger.info(f'✅ 素材上传成功: {filename} ({file_size/1024/1024:.2f}MB)')

            return jsonify({
                'code': 0,
                'msg': '上传成功',
                'data': material_data
            })

        except Exception as e:
            logger.error(f'❌ 素材上传失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'上传失败: {str(e)}',
                'data': None
            }), 500


    @app.route('/api/material/download/<material_id>', methods=['GET'])
    def download_material(material_id):
        """下载素材文件"""
        try:
            material_file = _find_material_file(material_id)

            if not material_file or not material_file.exists():
                return jsonify({
                    'code': 1,
                    'msg': '素材文件不存在',
                    'data': None
                }), 404

            logger.info(f'📥 下载素材: {material_file.name}')

            return send_file(
                str(material_file),
                as_attachment=True,
                download_name=material_file.name
            )

        except Exception as e:
            logger.error(f'❌ 素材下载失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'下载失败: {str(e)}',
                'data': None
            }), 500


    @app.route('/api/materials/list', methods=['GET'])
    def list_materials():
        """获取素材列表"""
        try:
            file_type = request.args.get('type', 'all')
            search = (request.args.get('search') or '').strip().lower()
            sort_by = request.args.get('sort_by', 'newest')
            # Query strings are user-controlled.  A malformed page value should
            # not turn the entire material library into a 500 response.
            try:
                page = max(1, int(request.args.get('page', 1)))
            except (TypeError, ValueError):
                page = 1
            try:
                per_page = min(100, max(1, int(request.args.get('per_page', 20))))
            except (TypeError, ValueError):
                per_page = 20

            # 扩展名到类别的映射，便于根据 ?type=video/audio/image/subtitle 过滤
            ext_to_category = {}
            for cat, exts in ALLOWED_EXTENSIONS.items():
                for ext in exts:
                    ext_to_category[ext] = cat

            def match_type(ext: str) -> bool:
                """根据查询参数 file_type 判断是否保留该扩展名的文件"""
                if not ext:
                    return False
                if file_type == 'all':
                    return True
                cat = ext_to_category.get(ext)
                return cat == file_type

            # 收集所有素材文件
            materials_list = []
            seen = set()
            for d in SCAN_DIRS:
                try:
                    if not d.exists():
                        continue
                    for file_path in d.glob('*'):
                        try:
                            if not file_path.is_file():
                                continue
                            real = file_path.resolve()
                            if real in seen:
                                continue
                            seen.add(real)

                            ext = file_path.suffix[1:].lower()
                            if not match_type(ext):
                                continue
                            if search and search not in file_path.name.lower():
                                continue

                            stat = file_path.stat()
                            try:
                                rel_path = file_path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
                            except ValueError:
                                # A scanned path outside the managed project is
                                # never exposed to the browser.
                                continue
                            file_info = {
                                'id': file_path.stem,
                                'filename': file_path.name,
                                'size': stat.st_size,
                                'modified_time': stat.st_mtime,
                                'type': ext,
                                'relative_path': rel_path,
                                'url': '/' + rel_path
                            }
                            materials_list.append(file_info)
                        except Exception as ie:
                            logger.warning(f'⚠️ 扫描素材文件失败: {file_path}: {ie}')
                except Exception as de:
                    logger.warning(f'⚠️ 扫描素材目录失败: {d}: {de}')

            # 排序
            if sort_by == 'name':
                materials_list.sort(key=lambda x: x['filename'].lower())
            elif sort_by == 'size':
                materials_list.sort(key=lambda x: x['size'], reverse=True)
            elif sort_by == 'type':
                materials_list.sort(key=lambda x: (x['type'], x['filename'].lower()))
            else:
                materials_list.sort(key=lambda x: x['modified_time'], reverse=True)

            # 分页
            total = len(materials_list)
            start = (page - 1) * per_page
            end = start + per_page
            materials_page = materials_list[start:end]

            logger.info(f'📋 获取素材列表: 第{page}页, 共{total}个')

            return jsonify({
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'materials': materials_page,
                    'total': total,
                    'page': page,
                    'per_page': per_page,
                    'total_pages': (total + per_page - 1) // per_page
                }
            })

        except Exception as e:
            logger.error(f'❌ 获取素材列表失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'获取失败: {str(e)}',
                'data': None
            }), 500


    @app.route('/api/material/delete/<material_id>', methods=['DELETE'])
    def delete_material(material_id):
        """删除素材文件"""
        try:
            material_file = _find_material_file(material_id)

            if not material_file or not material_file.exists():
                return jsonify({
                    'code': 1,
                    'msg': '素材文件不存在',
                    'data': None
                }), 404

            # 删除文件
            material_file.unlink()

            logger.info(f'🗑️ 删除素材: {material_file.name}')

            return jsonify({
                'code': 0,
                'msg': '删除成功',
                'data': None
            })

        except Exception as e:
            logger.error(f'❌ 删除素材失败: {e}', exc_info=True)
            return jsonify({
                'code': 1,
                'msg': f'删除失败: {str(e)}',
                'data': None
            }), 500


    @app.route('/api/material/delete-by-path', methods=['POST'])
    def delete_material_by_path():
        """按相对路径精确删除素材/上传视频文件（比按 material_id=stem 匹配更稳，不怕重名）。
        请求体 JSON: { "relative_path": "uploads/commentary_videos/xxx.mp4" }
        同时也支持 JSON 字段名 path / file_path，三者任选其一。
        """
        try:
            data = request.get_json(silent=True) or {}
            rel = (data.get('relative_path') or data.get('path') or data.get('file_path') or '').strip()
            if not rel:
                return jsonify({'code': 1, 'msg': '参数错误：缺少 relative_path / path / file_path', 'data': None}), 400

            # —— 白名单校验：只允许删除 SCAN_DIRS 这些受管目录下的真实文件，绝不允许删别处！ ——
            try:
                abs_candidate, normalized_rel = _resolve_managed_path(rel)
            except Exception as e:
                return jsonify({'code': 1, 'msg': f'路径非法或越界: {e}', 'data': None}), 400

            # 必须正好落在 SCAN_DIRS 子目录中
            try:
                in_allowed = False
                for sd in SCAN_DIRS:
                    try:
                        abs_candidate.relative_to((PROJECT_ROOT / sd).resolve())
                        in_allowed = True
                        break
                    except Exception:
                        continue
                if not in_allowed:
                    return jsonify({
                        'code': 1,
                        'msg': f'只允许删除受管目录（uploads/materials、uploads/videos、uploads/commentary_videos、uploads/remix_videos、uploads/audios、uploads/images）下的文件',
                        'data': None
                    }), 403
            except Exception as e:
                return jsonify({'code': 1, 'msg': f'路径校验失败: {e}', 'data': None}), 400

            if not abs_candidate.exists() or not abs_candidate.is_file():
                return jsonify({'code': 1, 'msg': '文件不存在或已被删除', 'data': None}), 404

            abs_candidate.unlink()
            logger.info(f'🗑️ 按路径删除素材成功: {rel} → {abs_candidate}')
            return jsonify({'code': 0, 'msg': '删除成功', 'data': {'deleted_path': rel}})

        except Exception as e:
            logger.error(f'❌ 按路径删除素材失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'删除失败: {str(e)}', 'data': None}), 500


    @app.route('/api/material/exists', methods=['GET'])
    def check_material_exists():
        """前端用于快速校验：给定路径文件是否真的存在于磁盘。
        参数字段名：path / relative_path / file_path 任选其一。
        """
        try:
            rel = (request.args.get('path') or request.args.get('relative_path')
                   or request.args.get('file_path') or '').strip()
            if not rel:
                return jsonify({'code': 0, 'msg': 'ok', 'data': {'exists': False, 'path': '', 'size': 0}})
            try:
                abs_candidate, normalized_rel = _resolve_managed_path(rel)
                # 限制在项目 uploads/ 目录下查询，避免泄露
                try:
                    abs_candidate.relative_to((PROJECT_ROOT / 'uploads').resolve())
                except Exception:
                    return jsonify({'code': 1, 'msg': '只允许查询 uploads/ 下的文件', 'data': None}), 403
                exists = abs_candidate.exists() and abs_candidate.is_file()
                sz = 0
                if exists:
                    try: sz = abs_candidate.stat().st_size
                    except Exception: pass
                return jsonify({'code': 0, 'msg': 'ok',
                                'data': {'exists': exists, 'path': normalized_rel,
                                         'size': sz, 'absolute_path': str(abs_candidate)}})
            except Exception as e:
                return jsonify({'code': 1, 'msg': str(e),
                                'data': {'exists': False, 'path': rel, 'size': 0}}), 400
        except Exception as e:
            logger.error(f'❌ 查询素材存在性失败: {e}', exc_info=True)
            return jsonify({'code': 1, 'msg': f'查询失败: {str(e)}',
                            'data': {'exists': False, 'path': '', 'size': 0}}), 500


    logger.info('✅ 素材管理路由注册完成 (7个)')
