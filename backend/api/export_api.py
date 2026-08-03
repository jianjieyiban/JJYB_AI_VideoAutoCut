# -*- coding: utf-8 -*-
"""基于项目时间线的安全视频导出 API。"""
import json
import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file
from werkzeug.utils import secure_filename

logger = logging.getLogger(__name__)
export_bp = Blueprint('export', __name__)
BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOADS_DIR = (BASE_DIR / 'uploads').resolve()
EXPORTS_DIR = BASE_DIR / 'exports'

FILTERS = {
    'grayscale': 'hue=s=0', 'sepia': 'colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131',
    'blur': 'boxblur=5:1', 'sharpen': 'unsharp=5:5:1.0:5:5:0.0', 'brightness': 'eq=brightness=0.2',
    'contrast': 'eq=contrast=1.5', 'saturate': 'eq=saturation=1.5', 'vintage': 'curves=vintage',
    'warm': 'colortemperature=10000', 'cool': 'colortemperature=5000', 'invert': 'negate',
}
CODECS = {'h264': 'libx264', 'h265': 'libx265', 'vp9': 'libvpx-vp9'}
QUALITY = {'low': ('1000k', '28'), 'medium': ('2500k', '23'), 'high': ('5000k', '18'), 'ultra': ('10000k', '15')}


def _object(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value else {}
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            pass
    return {}


def _all_clips(timeline):
    clips = []
    for track in timeline if isinstance(timeline, list) else []:
        for clip in (track or {}).get('clips') or []:
            item = dict(clip or {})
            item.setdefault('type', (track or {}).get('type', ''))
            clips.append(item)
    return clips


def _safe_upload_path(value):
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace('\\', '/').lstrip('/')
    if normalized.startswith('./'):
        normalized = normalized[2:]
    if not normalized.startswith('uploads/'):
        return None
    candidate = (BASE_DIR / normalized).resolve()
    try:
        candidate.relative_to(UPLOADS_DIR)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clip_filters(clip, global_filters):
    filters = []
    effects = clip.get('effects') if isinstance(clip.get('effects'), dict) else {}
    effect = clip.get('effect') or clip.get('filter') or effects.get('filter') or effects.get('effect') or ''
    if effect in FILTERS:
        filters.append(FILTERS[effect])
    if effect == 'speed-up':
        filters.append('setpts=0.5*PTS')
    elif effect == 'slow-motion':
        filters.append('setpts=2.0*PTS')
    elif effect == 'reverse' or clip.get('reverse'):
        filters.append('reverse')

    merged = dict(global_filters or {})
    merged.update({key: effects[key] for key in ('brightness', 'contrast', 'saturation', 'hue') if key in effects})
    brightness = _number(merged.get('brightness')) / 100.0
    contrast = 1 + _number(merged.get('contrast')) / 100.0
    saturation = 1 + _number(merged.get('saturation')) / 100.0
    eq = []
    if abs(brightness) > .001:
        eq.append(f'brightness={max(-1, min(1, brightness)):.3f}')
    if abs(contrast - 1) > .001:
        eq.append(f'contrast={max(0, min(2, contrast)):.3f}')
    if abs(saturation - 1) > .001:
        eq.append(f'saturation={max(0, min(3, saturation)):.3f}')
    if eq:
        filters.append('eq=' + ':'.join(eq))
    hue = _number(merged.get('hue'))
    if abs(hue) > .001:
        filters.append(f'hue=h={max(-180, min(180, hue * 1.8)):.1f}*PI/180')
    return filters


def _drawtext(text_clips):
    filters = []
    for clip in text_clips:
        text = str(clip.get('text') or '')
        if not text:
            continue
        start = max(0, _number(clip.get('start_sec')))
        duration = max(.01, _number(clip.get('duration_sec'), 3))
        escaped = text.replace('\\', r'\\').replace(':', r'\:').replace("'", r"\'").replace('\n', r'\n')
        filters.append("drawtext=text='%s':x=(w-text_w)/2:y=h-(text_h*2)-30:fontcolor=white:fontsize=32:box=1:boxcolor=black@0.45:enable='between(t,%.3f,%.3f)'" % (escaped, start, start + duration))
    return filters


def register_export_routes(app, db_manager):
    @app.route('/api/export/video', methods=['POST'])
    def export_video():
        try:
            data = request.get_json(silent=True) or {}
            project_id = data.get('project_id')
            if not project_id:
                return jsonify({'code': -1, 'msg': '缺少 project_id'}), 400
            project = db_manager.get_project(project_id)
            if not project:
                return jsonify({'code': -1, 'msg': '项目不存在'}), 404

            timeline = data.get('timeline')
            if not isinstance(timeline, list):
                config = _object(project.get('config'))
                timeline = config.get('editor', {}).get('tracks') or config.get('tracks') or []
            all_clips = _all_clips(timeline)
            materials = {str(item.get('id')): item for item in project.get('materials') or []}
            for clip in all_clips:
                material = materials.get(str(clip.get('material_id') or ''))
                if material and not clip.get('source'):
                    clip['source'] = material.get('path')

            visual = sorted((clip for clip in all_clips if clip.get('type') in ('video', 'image')),
                            key=lambda clip: _number(clip.get('start_sec')))
            usable = [(clip, _safe_upload_path(clip.get('source'))) for clip in visual]
            usable = [(clip, path) for clip, path in usable if path]
            if not usable:
                return jsonify({'code': -1, 'msg': '时间线中没有可访问的项目视频或图片素材'}), 400
            source_paths = {str(path) for _, path in usable}
            if len(source_paths) > 1:
                return jsonify({'code': -1, 'msg': '当前导出暂不支持多源合成'}), 400
            if any(clip.get('type') == 'image' for clip, _ in usable) and len(usable) > 1:
                return jsonify({'code': -1, 'msg': '当前导出暂不支持图片与其他片段的多源合成'}), 400

            export_format = str(data.get('format') or 'mp4').lower()
            if export_format not in {'mp4', 'mov', 'mkv', 'avi', 'webm'}:
                return jsonify({'code': -1, 'msg': '不支持的导出格式'}), 400
            resolution = str(data.get('resolution') or '1920x1080')
            if not re.fullmatch(r'\d{2,5}x\d{2,5}', resolution):
                return jsonify({'code': -1, 'msg': '分辨率格式无效'}), 400
            fps = max(1, min(120, int(_number(data.get('fps'), 30))))
            bitrate, crf = QUALITY.get(data.get('quality'), QUALITY['high'])
            hints = data.get('effects_hints') if isinstance(data.get('effects_hints'), dict) else {}
            global_filters = hints.get('filters') if isinstance(hints.get('filters'), dict) else {}
            input_path = usable[0][1]

            command = ['ffmpeg', '-y']
            filter_parts = []
            if usable[0][0].get('type') == 'image':
                clip = usable[0][0]
                duration = max(.1, _number(clip.get('duration_sec'), 5))
                command += ['-loop', '1', '-i', str(input_path), '-t', f'{duration:.3f}']
                filters = _clip_filters(clip, global_filters)
                filters.append(f'scale={resolution}:force_original_aspect_ratio=decrease,pad={resolution}:(ow-iw)/2:(oh-ih)/2')
                filter_parts.append('[0:v]' + ','.join(filters) + '[timeline]')
            else:
                command += ['-i', str(input_path)]
                labels = []
                for index, (clip, _) in enumerate(usable):
                    source_start = max(0, _number(clip.get('clip_source_start', clip.get('source_start', 0))))
                    duration = _number(clip.get('duration_sec'))
                    trim = f'trim=start={source_start:.3f}' + (f':duration={duration:.3f}' if duration > 0 else '')
                    filters = [trim, 'setpts=PTS-STARTPTS'] + _clip_filters(clip, global_filters)
                    filters.append(f'scale={resolution}:force_original_aspect_ratio=decrease,pad={resolution}:(ow-iw)/2:(oh-ih)/2')
                    label = f'clip{index}'
                    filter_parts.append(f'[0:v]{",".join(filters)}[{label}]')
                    labels.append(f'[{label}]')
                if len(labels) == 1:
                    filter_parts.append(f'{labels[0]}null[timeline]')
                else:
                    filter_parts.append(f'{"".join(labels)}concat=n={len(labels)}:v=1:a=0[timeline]')

            text_filters = _drawtext([clip for clip in all_clips if clip.get('type') == 'text'])
            if text_filters:
                filter_parts.append('[timeline]' + ','.join(text_filters) + '[output]')
                output_label = '[output]'
            else:
                output_label = '[timeline]'

            output_dir = EXPORTS_DIR / secure_filename(str(project_id))
            output_dir.mkdir(parents=True, exist_ok=True)
            filename = '%s_%s.%s' % (secure_filename(project.get('name') or 'project'), datetime.now().strftime('%Y%m%d_%H%M%S'), export_format)
            output_path = output_dir / filename
            command += ['-filter_complex', ';'.join(filter_parts), '-map', output_label, '-r', str(fps),
                        '-c:v', CODECS.get(data.get('codec'), 'libx264'), '-b:v', bitrate, '-crf', crf, '-pix_fmt', 'yuv420p', '-an', str(output_path)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=300)
            if result.returncode != 0:
                logger.error('FFmpeg 导出失败: %s', result.stderr)
                return jsonify({'code': -1, 'msg': '视频导出失败: ' + result.stderr[-300:]}), 500
            size = output_path.stat().st_size
            return jsonify({'code': 0, 'msg': '导出成功', 'data': {
                'file_path': str(output_path.relative_to(BASE_DIR).as_posix()), 'file_name': filename,
                'file_size': size, 'file_size_mb': round(size / 1048576, 2), 'format': export_format,
                'quality': data.get('quality', 'high'), 'resolution': resolution, 'fps': fps,
                'download_url': f'/api/export/download/{project_id}/{filename}'
            }})
        except subprocess.TimeoutExpired:
            return jsonify({'code': -1, 'msg': '导出超时，请降低视频质量或分辨率'}), 500
        except FileNotFoundError:
            return jsonify({'code': -1, 'msg': 'FFmpeg 未安装'}), 500
        except Exception as exc:
            logger.error('导出视频失败: %s', exc, exc_info=True)
            return jsonify({'code': -1, 'msg': f'导出失败: {exc}'}), 500

    @app.route('/api/export/download/<project_id>/<filename>', methods=['GET'])
    def download_export(project_id, filename):
        safe_project = secure_filename(project_id)
        safe_name = secure_filename(filename)
        file_path = (EXPORTS_DIR / safe_project / safe_name).resolve()
        try:
            file_path.relative_to(EXPORTS_DIR.resolve())
        except ValueError:
            return jsonify({'code': -1, 'msg': '文件不存在'}), 404
        if not file_path.is_file():
            return jsonify({'code': -1, 'msg': '文件不存在'}), 404
        return send_file(file_path, as_attachment=True, download_name=safe_name)

    @app.route('/api/export/progress/<task_id>', methods=['GET'])
    def get_export_progress(task_id):
        task = db_manager.get_task(task_id)
        if not task:
            return jsonify({'code': -1, 'msg': '任务不存在', 'data': None}), 404
        return jsonify({'code': 0, 'msg': '成功', 'data': {
            'task_id': task_id, 'progress': float(task.get('progress') or 0),
            'status': task.get('status') or 'pending', 'message': task.get('error_message') or ''
        }})

    logger.info('导出 API 路由注册完成')
