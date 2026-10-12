# -*- coding: utf-8 -*-
"""
Commentary API
原创解说剪辑API - 完整实现

注意：/create、/generate-script、/process 三个路由由 commentary_routes_enhanced.py
提供（增强版，使用 CommentaryServiceEnhanced），此处不重复注册以避免路由冲突。
本蓝图仅注册增强版未覆盖的独有路由。
"""

import logging
import os
import threading
import time
import uuid
import json
import cv2
from pathlib import Path
from flask import Blueprint, request, jsonify

from backend.engine.smart_shot_segmenter import SmartShotSegmentationCancelled

logger = logging.getLogger(__name__)

# 通用项目根路径
from backend.config.paths import PROJECT_ROOT  # noqa: E402

# 创建蓝图
commentary_bp = Blueprint('commentary', __name__)

# 全局变量（将在注册时设置）
commentary_service = None
_smart_segment_tasks = {}
_smart_segment_tasks_lock = threading.Lock()


def _resolve_and_validate_video_path(video_path):
    text = str(video_path or '').strip().replace('\\', '/').lstrip('/')
    if not text:
        raise ValueError('参数错误：缺少 video_path')
    raw = Path(text)
    candidate = (raw if raw.is_absolute() else PROJECT_ROOT / raw).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError('视频路径不合法，仅允许项目目录内的视频') from exc
    if not candidate.is_file():
        raise ValueError('视频文件不存在')
    cap = cv2.VideoCapture(str(candidate))
    try:
        if not cap.isOpened():
            raise ValueError('视频无法打开或格式不受支持')
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        ok, frame = cap.read()
        if not ok or frame is None or frame.size == 0 or fps <= 0 or frame_count <= 0:
            raise ValueError('视频无法解码出有效画面或元数据')
    finally:
        cap.release()
    return candidate, candidate.relative_to(PROJECT_ROOT.resolve()).as_posix()


def _is_cancel_requested(task_id):
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        return bool(task and task.get('cancel_requested'))


def _task_payload(task):
    return {key: value for key, value in task.items() if key != 'video_path'}


def _emit_task_event(event, payload):
    socketio = getattr(commentary_service, 'socketio', None)
    if socketio:
        try:
            socketio.emit(event, payload)
        except Exception:
            logger.warning('智能镜头分割 Socket.IO 通知失败')


def _update_smart_segment_task(task_id, **changes):
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        if not task:
            return None
        task.update(changes)
        task['updated_at'] = time.time()
        return dict(task)


def register_commentary_routes(app, db_manager, task_service, commentary_svc):
    """
    注册原创解说剪辑API路由

    Args:
        app: Flask应用实例
        db_manager: 数据库管理器
        task_service: 任务服务
        commentary_svc: 原创解说服务
    """
    global commentary_service
    commentary_service = commentary_svc

    app.register_blueprint(commentary_bp, url_prefix='/api/commentary')
    logger.info('✅ 原创解说API路由注册完成（独有路由，create/generate-script/process 由增强版提供）')


# ================================================================== #
# 升级端点 1：智能镜头分割（剪映专业版风格，分析帧无上限）
# ================================================================== #
@commentary_bp.route('/smart-segment', methods=['POST'])
def smart_segment_shots():
    """启动异步智能镜头分割任务（同视频自动去重，复用正在运行/已完成的任务）。"""
    data = request.get_json() or {}
    try:
        video_file, video_path = _resolve_and_validate_video_path(data.get('video_path'))
    except ValueError as exc:
        return jsonify({'code': 1, 'msg': str(exc), 'data': None}), 400
    force = bool(data.get('force', False))

    # 1) 先查内存：同视频已存在 pending/running/completed 任务则直接复用（未 force 时）
    existing = None
    existing_task_id = None
    with _smart_segment_tasks_lock:
        for tid, t in _smart_segment_tasks.items():
            if t.get('video_path') != video_path:
                continue
            st = t.get('status')
            if st in ('pending', 'running'):
                existing = t
                existing_task_id = tid
                break
            if st == 'completed' and t.get('result'):
                existing = t
                existing_task_id = tid
                break
    if existing and not force:
        logger.info(f'♻️ 复用智能镜头分割任务: video={video_path[:60]}..., task={existing_task_id}, status={existing.get("status")}')
        return jsonify({
            'code': 0,
            'msg': f'复用已有任务（状态：{existing.get("status")}）',
            'data': {
                'task_id': existing_task_id,
                'reused': True,
                'status': existing.get('status'),
                'progress': existing.get('progress', 0),
                'message': existing.get('message', ''),
                'result': existing.get('result'),
            }
        })

    task_id = str(uuid.uuid4())
    task = {
        'task_id': task_id,
        'status': 'pending',
        'progress': 0,
        'message': '智能镜头分割任务已创建',
        'result': None,
        'error': None,
        'cancel_requested': False,
        'video_path': video_path,
        'created_at': time.time(),
        'updated_at': time.time(),
    }
    with _smart_segment_tasks_lock:
        _smart_segment_tasks[task_id] = task
    db_manager = getattr(commentary_service, 'db_manager', None)
    if db_manager:
        try:
            db_manager.create_task(task_id, 'smart_shot_segment', input_data={'video_path': video_path})
        except Exception:
            logger.warning('智能镜头分割任务写入数据库失败，将仅使用内存任务状态')

    def run_task():
        def cancel_callback():
            return _is_cancel_requested(task_id)

        def report(progress, message):
            progress = max(0, min(100, int(progress)))
            with _smart_segment_tasks_lock:
                current = _smart_segment_tasks.get(task_id)
                if not current or current.get('cancel_requested'):
                    return
                current.update(status='running', progress=progress, message=message, updated_at=time.time())
                updated = dict(current)
            if db_manager:
                try:
                    db_manager.update_task_progress(task_id, progress)
                except Exception:
                    pass
            if updated:
                _emit_task_event('task_progress', {
                    'task_id': task_id, 'progress': progress, 'message': message
                })

        try:
            if cancel_callback():
                raise SmartShotSegmentationCancelled('智能镜头分割已取消')
            _update_smart_segment_task(task_id, status='running', message='正在初始化智能镜头分割')
            if cancel_callback():
                raise SmartShotSegmentationCancelled('智能镜头分割已取消')
            if db_manager:
                try:
                    db_manager.update_task_status(task_id, 'running')
                except Exception:
                    pass
            _emit_task_event('task_status', {'task_id': task_id, 'status': 'running'})
            result = commentary_service.smart_segment_shots(
                video_path=video_path,
                threshold=float(data.get('threshold', 0.5)),
                min_scene_len_sec=float(data.get('min_scene_len_sec', 0.4)),
                use_transnetv2=bool(data.get('use_transnetv2', True)),
                export_keyframes=bool(data.get('export_keyframes', True)),
                max_shots=data.get('max_shots'),
                progress_callback=report,
                cancel_callback=cancel_callback,
            )
            if cancel_callback():
                raise SmartShotSegmentationCancelled('智能镜头分割已取消')
            _update_smart_segment_task(
                task_id, status='completed', progress=100, message='智能镜头分割完成', result=result
            )
            if db_manager:
                try:
                    db_manager.update_task_status(task_id, 'completed', output_data=result)
                except Exception:
                    pass
            _emit_task_event('task_status', {'task_id': task_id, 'status': 'completed'})
        except SmartShotSegmentationCancelled:
            message = '智能镜头分割已取消'
            _update_smart_segment_task(
                task_id, status='cancelled', message=message, error=None, result=None
            )
            if db_manager:
                try:
                    db_manager.update_task_status(task_id, 'cancelled', error_message=message)
                except Exception:
                    pass
            _emit_task_event('task_status', {'task_id': task_id, 'status': 'cancelled'})
        except Exception as exc:
            if cancel_callback():
                message = '智能镜头分割已取消'
                _update_smart_segment_task(task_id, status='cancelled', message=message, error=None, result=None)
                if db_manager:
                    try:
                        db_manager.update_task_status(task_id, 'cancelled', error_message=message)
                    except Exception:
                        pass
                _emit_task_event('task_status', {'task_id': task_id, 'status': 'cancelled'})
                return
            logger.exception('智能镜头分割任务失败: %s', task_id)
            message = str(exc) or '智能镜头分割失败'
            _update_smart_segment_task(task_id, status='failed', message=message, error=message)
            if db_manager:
                try:
                    db_manager.update_task_status(task_id, 'failed', error_message=message)
                except Exception:
                    pass
            _emit_task_event('task_status', {'task_id': task_id, 'status': 'failed', 'error': message})

    threading.Thread(target=run_task, name=f'smart-segment-{task_id[:8]}', daemon=True).start()
    return jsonify({'code': 0, 'msg': '智能镜头分割任务已启动', 'data': {'task_id': task_id}})


@commentary_bp.route('/smart-segment/<task_id>/cancel', methods=['POST'])
def cancel_smart_segment_task(task_id):
    """请求取消智能镜头分割任务。"""
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        if not task:
            return jsonify({'code': 1, 'msg': '任务不存在或服务已重启', 'data': None}), 404
        status = task.get('status')
        if status in ('completed', 'failed', 'cancelled'):
            snapshot = dict(task)
        else:
            task['cancel_requested'] = True
            task['status'] = 'cancelled' if status == 'pending' else 'cancelling'
            task['message'] = '智能镜头分割已取消' if status == 'pending' else '正在取消智能镜头分割'
            task['updated_at'] = time.time()
            snapshot = dict(task)
    db_manager = getattr(commentary_service, 'db_manager', None)
    if snapshot.get('status') in ('cancelled', 'cancelling'):
        if db_manager:
            try:
                db_manager.update_task_status(task_id, snapshot['status'])
            except Exception:
                pass
        _emit_task_event('task_status', {'task_id': task_id, 'status': snapshot['status']})
    return jsonify({'code': 0, 'msg': snapshot.get('message') or '取消请求已处理', 'data': _task_payload(snapshot)})


@commentary_bp.route('/smart-segment/<task_id>', methods=['GET'])
def get_smart_segment_task(task_id):
    """查询智能镜头分割任务状态与结果。"""
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        snapshot = dict(task) if task else None
    if not snapshot:
        return jsonify({'code': 1, 'msg': '任务不存在或服务已重启', 'data': None}), 404
    return jsonify({'code': 0, 'msg': '查询成功', 'data': _task_payload(snapshot)})


# ================================================================== #
# 升级端点 2：拟人化字画音画同步剪辑
# ================================================================== #
@commentary_bp.route('/puppet-sync', methods=['POST'])
def puppet_sync_commentary():
    """拟人化字画音画同步剪辑

    请求体:
        - video_path: 源视频路径
        - shots: smart-segment 返回的 shots 列表
        - voices: 配音段列表 [{text, voice_path, duration}, ...]
        - bgm_path: 可选 BGM 路径
        - subtitle_path: 可选 SRT 字幕路径
        - allow_reuse: 是否允许画面重复（默认 false）
        - insert_original_audio: 是否在拟人化时间线中穿插原片原声（默认 false）
        - original_clip_interval/original_clip_duration/original_audio_volume: 旧版间隔参数
        - original_audio_mode/original_audio_ratio/target_duration_seconds: 成片比例规划参数
        - project_id: 可选，成功后合并保存工作台状态
        - render: 是否实际渲染视频（默认 true）
        - output_path: 指定输出路径（可选）
    """
    try:
        data = request.get_json() or {}
        for key in ('video_path', 'shots', 'voices'):
            if key not in data:
                return jsonify({'code': 1, 'msg': f'参数错误：缺少 {key}', 'data': None}), 400

        result = commentary_service.puppet_sync_commentary(
            video_path=data['video_path'],
            shots=data['shots'],
            voices=data['voices'],
            bgm_path=data.get('bgm_path', ''),
            subtitle_path=data.get('subtitle_path', ''),
            allow_reuse=bool(data.get('allow_reuse', False)),
            insert_original_audio=bool(data.get('insert_original_audio', False)),
            original_clip_interval=data.get('original_clip_interval', 3),
            original_clip_duration=data.get('original_clip_duration', 3.0),
            original_audio_volume=data.get('original_audio_volume', 1.0),
            render=bool(data.get('render', True)),
            output_path=data.get('output_path', ''),
            target_duration_seconds=data.get('target_duration_seconds'),
            project_id=data.get('project_id', ''),
            original_audio_mode=data.get('original_audio_mode', 'interval'),
            original_audio_ratio=data.get('original_audio_ratio'),
        )

        return jsonify({
            'code': 0,
            'msg': f'拟人化同步完成，共 {result["clip_count"]} 个片段',
            'data': result
        })
    except Exception as e:
        from backend.engine.storyboard_planner import StoryboardPlanningError
        if isinstance(e, StoryboardPlanningError):
            logger.warning(f'拟人化同步规划无法完成: {e}')
            return jsonify({
                'code': 2,
                'msg': f'同步规划未完成: {str(e)}',
                'data': {'unmatched_segments': e.unmatched_segments},
            }), 422
        logger.error(f'拟人化同步剪辑失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'同步失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 3：从文稿生成配音段
# ================================================================== #
@commentary_bp.route('/generate-voices', methods=['POST'])
def generate_voices():
    """根据文稿段落生成配音段列表

    请求体:
        - script: generate-script 返回的文稿
        - voice_config: 配音配置 {voice_id, engine, rate, ...}
    """
    try:
        data = request.get_json() or {}
        if 'script' not in data and not isinstance(data.get('segments'), list):
            return jsonify({'code': 1, 'msg': '参数错误：缺少 script 或 segments', 'data': None}), 400

        result = commentary_service.generate_voices_from_script(
            script=data.get('script', ''),
            voice_config=data.get('voice_config', {}),
            segments=data.get('segments'),
            with_details=True,
        )
        total_count = result['total_count']
        success_count = result['success_count']

        if total_count == 0:
            return jsonify({'code': 1, 'msg': '未发现可生成配音的有效段落', 'data': result}), 400
        if success_count == 0:
            segments = result.get('segments') or result.get('voices') or []
            first_failed = next((item for item in segments if item.get('status') == 'failed'), {})
            reason = first_failed.get('reason') or first_failed.get('error') or '请检查配音引擎、音色和网络后重试'
            return jsonify({
                'code': 1,
                'msg': f'配音生成失败：0/{total_count} 段成功，首段失败原因：{reason}',
                'data': result,
            }), 422

        fallback_count = int(result.get('fallback_count') or 0)
        if success_count < total_count:
            msg = f'配音段生成完成，成功 {success_count}/{total_count} 段，失败 {result["failed_count"]} 段'
        elif fallback_count:
            msg = f'全部配音已生成（含{fallback_count}段回退）'
        else:
            msg = f'全部配音已生成，共 {total_count} 段'
        return jsonify({'code': 0, 'msg': msg, 'data': result})
    except Exception as e:
        logger.error(f'生成配音段失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'data': None}), 500


# 新增：重新生成单段配音（供前端 regenerateSingleVoice 调用
@commentary_bp.route('/generate-single-voice', methods=['POST'])
def generate_single_voice():
    """按段工作台「重新生成」调用。请求体包含 segment dict + voice_config"""
    try:
        data = request.get_json() or {}
        seg = data.get('segment') or {}
        text = (seg.get('text') or '').strip()
        if not text:
            return jsonify({'code': 1, 'msg': '段落文本为空', 'data': None}), 400
        voice_config = dict(data.get('voice_config') or {})
        engine_key = (data.get('tts_engine') or seg.get('engine') or voice_config.get('engine') or 'edge-tts').strip().lower()
        voice_id = (data.get('voice') or seg.get('voice') or voice_config.get('voice_id') or '').strip()
        if not voice_id:
            from backend.services.voiceover_service import VoiceoverService
            voice_id = VoiceoverService._default_voice_id()
        voice_config.update({
            'voice_id': voice_id, 'voice': voice_id, 'engine': engine_key,
            'rate': voice_config.get('rate', seg.get('rate', 1)),
            'pitch': voice_config.get('pitch', seg.get('pitch', '+0Hz')),
            'volume': voice_config.get('volume', 1),
        })
        result = commentary_service.generate_voices_from_script(
            script='', voice_config=voice_config,
            segments=[{'id': seg.get('id'), 'index': seg.get('index', data.get('index', 0)), 'text': text}],
            with_details=True,
        )
        generated = (result.get('segments') or result.get('voices') or [None])[0]
        if not generated or generated.get('status') != 'ready' or not (generated.get('audio_path') or generated.get('audio_url')):
            message = (generated or {}).get('reason') or (generated or {}).get('error') or 'TTS 合成失败'
            return jsonify({'code': 2, 'msg': message, 'data': result, 'segment': generated}), 422
        fallback_note = '（已由 %s 回退生成，音色可能与 Edge 不同）' % generated.get('engine_used') if generated.get('fallback_used') else ''
        return jsonify({'code': 0, 'msg': f'单段生成完成{fallback_note}', 'data': result, 'segment': generated})
    except Exception as e:
        logger.error(f'重新生成单段配音失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {str(e)}', 'segment': None}), 500


# 新增：配音段ZIP导出（供前端 exportAllVoiceSegments 调用）
@commentary_bp.route('/export-voice-zip', methods=['POST'])
def export_voice_zip():
    try:
        import zipfile
        from datetime import datetime
        data = request.get_json() or {}
        segments = data.get('segments') or []
        items = []
        for i, s in enumerate(segments):
            if not isinstance(s, dict):
                continue
            path = None
            for value in (s.get('audio_path'), s.get('audio_url')):
                value = str(value or '').strip()
                if not value or value.startswith(('http://', 'https://')):
                    continue
                if value.startswith('/api/download/'):
                    value = value[len('/api/download/'):]
                elif value.startswith('/output/'):
                    value = 'output/' + value[len('/output/'):]
                elif value.startswith('file:///'):
                    value = value[8:]
                candidate = Path(value)
                if not candidate.is_absolute():
                    candidate = PROJECT_ROOT / value.lstrip('/\\')
                if candidate.is_file():
                    path = candidate
                    break
            if path:
                items.append((str(path), f"{i+1:03d}_{s.get('index') or (i+1)}_{str(s.get('voice') or 'voice')[:12]}{path.suffix.lower()}"))
        if not items:
            return jsonify({'code': 1, 'msg': '没有可导出的配音段', 'data': None}), 400
        out_dir = PROJECT_ROOT / 'output' / 'voice_zips'
        out_dir.mkdir(parents=True, exist_ok=True)
        zip_name = f"voice_segments_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{abs(hash(str(items)[:50])) % 100000}.zip"
        zip_path = out_dir / zip_name
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for src, name in items:
                zf.write(src, arcname=name)
            # 附带 readme
            try:
                readme = f"语音段导出列表\n\n共 {len(items)} 段\n生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n项目ID: {data.get('project_id') or '-'}\n"
                zf.writestr('README.txt', readme.encode('utf-8'))
            except Exception:
                pass
        url = f"/output/voice_zips/{zip_name}"
        return jsonify({'code': 0, 'msg': f'已打包 {len(items)} 个配音段', 'data': {'zip_path': str(zip_path), 'zip_url': url, 'count': len(items)}})
    except Exception as e:
        logger.error(f'导出配音段ZIP失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 4：检测剪映草稿目录
# ================================================================== #
@commentary_bp.route('/detect-jianying-draft-dir', methods=['GET'])
def detect_jianying_draft_dir():
    """自动检测剪映草稿目录"""
    try:
        from backend.utils.jianying_detector import detect_jianying_draft_info
        info = detect_jianying_draft_info()
        return jsonify({
            'code': 0,
            'msg': '检测成功' if info['detected'] and info['writable'] else info['message'],
            'data': info
        })
    except Exception as e:
        logger.error(f'检测剪映草稿目录失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'检测失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 5：导出剪映草稿包
# ================================================================== #
@commentary_bp.route('/export-jianying-draft', methods=['POST'])
def export_jianying_draft():
    """导出剪映草稿包（四轨道：视频/配音/BGM/字幕）

    请求体:
        - project_id: 项目ID
        - timeline: puppet-sync 返回的 timeline
        - video_path: 源视频路径
        - audio_paths: 配音音频路径列表
        - subtitle_text: 字幕文本
        - draft_dir: 指定草稿目录（可选，默认自动检测）
    """
    try:
        data = request.get_json() or {}
        if 'project_id' not in data:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 project_id', 'data': None}), 400

        result = commentary_service.export_jianying_draft(
            project_id=data['project_id'],
            timeline=data.get('timeline', []),
            video_path=data.get('video_path', ''),
            audio_paths=data.get('audio_paths', []),
            subtitle_text=data.get('subtitle_text', ''),
            draft_dir=data.get('draft_dir', ''),
            bgm_path=data.get('bgm_path', ''),
            project_name=data.get('project_name', ''),
            flower_config=data.get('flower_config'),
        )

        native = bool(result.get('native_jianying_project'))
        return jsonify({
            'code': 0,
            'msg': '剪映原生草稿已导出' if native else '本地原生草稿目录已生成，需放入剪映草稿根目录才会被扫描',
            'data': result
        })
    except ValueError as e:
        logger.warning(f'导出剪映草稿参数/时间线无效: {e}')
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 422
    except Exception as e:
        logger.error(f'导出剪映草稿失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 500
