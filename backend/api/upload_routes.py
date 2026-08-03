"""
文件上传API路由
"""

import logging
import os
import time
import uuid
from pathlib import Path
from flask import request, jsonify
from werkzeug.utils import secure_filename

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger('JJYB_AI智剪')

# 允许的文件扩展名
ALLOWED_VIDEO_EXTENSIONS = {'mp4', 'avi', 'mov', 'mkv', 'flv', 'wmv'}
ALLOWED_AUDIO_EXTENSIONS = {'mp3', 'wav', 'aac', 'm4a', 'flac'}
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp'}

# 上传目录
UPLOAD_DIR = 'uploads'


def allowed_file(filename, allowed_extensions):
    """检查文件扩展名是否允许"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed_extensions


def register_upload_routes(app):
    """注册文件上传路由"""

    # 确保上传目录存在
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, 'videos'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, 'audios'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, 'images'), exist_ok=True)
    # 为不同业务场景预留的子目录（解说/混剪等）
    os.makedirs(os.path.join(UPLOAD_DIR, 'commentary_videos'), exist_ok=True)
    os.makedirs(os.path.join(UPLOAD_DIR, 'remix_videos'), exist_ok=True)

    @app.route('/api/upload/video', methods=['POST'])
    def upload_video():
        """上传视频文件"""
        try:
            if 'video' not in request.files:
                return jsonify({'code': 1, 'msg': '没有文件', 'data': None}), 400

            file = request.files['video']

            if file.filename == '':
                return jsonify({'code': 1, 'msg': '文件名为空', 'data': None}), 400

            if not allowed_file(file.filename, ALLOWED_VIDEO_EXTENSIONS):
                return jsonify({'code': 1, 'msg': '不支持的文件格式', 'data': None}), 400

            # 生成安全文件名。secure_filename 对纯中文名可能只保留扩展名（如
            # "荒野厨房.mp4" -> "mp4"），因此扩展名必须从原始文件名提取，
            # 文件主体为空时使用 video + 时间戳 + uuid，保证扩展名永不丢失。
            original_filename = os.path.basename(file.filename)
            original_ext = os.path.splitext(original_filename)[1].lower()
            safe_fullname = secure_filename(original_filename)
            safe_stem = os.path.splitext(safe_fullname)[0].strip('._-')
            if not safe_stem or safe_stem.lower() == original_ext.lstrip('.'):
                safe_stem = 'video'
            timestamp = int(time.time() * 1000)
            new_filename = f"{safe_stem}_{timestamp}_{uuid.uuid4().hex[:8]}{original_ext}"

            # 根据业务场景选择子目录
            scene = (request.form.get('scene') or '').strip().lower()
            if scene == 'commentary':
                subdir = 'commentary_videos'
            elif scene == 'remix':
                subdir = 'remix_videos'
            else:
                subdir = 'videos'

            # 使用项目根目录落盘，避免服务以不同工作目录启动时读写位置不一致。
            # API 对外统一返回 POSIX 相对路径，前端/数据库不再混入 Windows 反斜杠。
            relative_path = Path(UPLOAD_DIR) / subdir / new_filename
            absolute_path = (PROJECT_ROOT / relative_path).resolve()
            absolute_path.parent.mkdir(parents=True, exist_ok=True)
            file.save(str(absolute_path))

            # 获取文件大小
            file_size = absolute_path.stat().st_size
            api_path = relative_path.as_posix()

            logger.info(f'✅ 视频上传成功: {absolute_path}')

            return jsonify({
                'code': 0,
                'msg': '上传成功',
                'data': {
                    'path': api_path,
                    'filename': new_filename,
                    'original_filename': original_filename,
                    'size': file_size
                }
            })

        except Exception as e:
            logger.error(f'❌ 视频上传失败: {e}')
            return jsonify({'code': 1, 'msg': f'上传失败: {str(e)}', 'data': None}), 500

    @app.route('/api/upload/audio', methods=['POST'])
    def upload_audio():
        """上传音频文件"""
        try:
            if 'audio' not in request.files:
                return jsonify({'code': 1, 'msg': '没有文件', 'data': None}), 400

            file = request.files['audio']

            if file.filename == '':
                return jsonify({'code': 1, 'msg': '文件名为空', 'data': None}), 400

            if not allowed_file(file.filename, ALLOWED_AUDIO_EXTENSIONS):
                return jsonify({'code': 1, 'msg': '不支持的文件格式', 'data': None}), 400

            filename = secure_filename(file.filename)
            timestamp = int(time.time())
            name, ext = os.path.splitext(filename)
            new_filename = f"{name}_{timestamp}{ext}"

            filepath = os.path.join(UPLOAD_DIR, 'audios', new_filename)
            file.save(filepath)

            file_size = os.path.getsize(filepath)

            logger.info(f'✅ 音频上传成功: {filepath}')

            return jsonify({
                'code': 0,
                'msg': '上传成功',
                'data': {
                    'path': filepath,
                    'filename': new_filename,
                    'size': file_size
                }
            })

        except Exception as e:
            logger.error(f'❌ 音频上传失败: {e}')
            return jsonify({'code': 1, 'msg': f'上传失败: {str(e)}', 'data': None}), 500

    @app.route('/api/upload/image', methods=['POST'])
    def upload_image():
        """上传图片文件"""
        try:
            if 'image' not in request.files:
                return jsonify({'code': 1, 'msg': '没有文件', 'data': None}), 400

            file = request.files['image']

            if file.filename == '':
                return jsonify({'code': 1, 'msg': '文件名为空', 'data': None}), 400

            if not allowed_file(file.filename, ALLOWED_IMAGE_EXTENSIONS):
                return jsonify({'code': 1, 'msg': '不支持的文件格式', 'data': None}), 400

            filename = secure_filename(file.filename)
            timestamp = int(time.time())
            name, ext = os.path.splitext(filename)
            new_filename = f"{name}_{timestamp}{ext}"

            filepath = os.path.join(UPLOAD_DIR, 'images', new_filename)
            file.save(filepath)

            file_size = os.path.getsize(filepath)

            logger.info(f'✅ 图片上传成功: {filepath}')

            return jsonify({
                'code': 0,
                'msg': '上传成功',
                'data': {
                    'path': filepath,
                    'filename': new_filename,
                    'size': file_size
                }
            })

        except Exception as e:
            logger.error(f'❌ 图片上传失败: {e}')
            return jsonify({'code': 1, 'msg': f'上传失败: {str(e)}', 'data': None}), 500

    logger.info('✅ 文件上传路由注册完成')
