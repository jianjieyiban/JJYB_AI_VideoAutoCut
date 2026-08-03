# -*- coding: utf-8 -*-
"""
Remix API
混剪模式API - 完整实现
"""

import hashlib
import logging
import math
import json
import threading
import time
import uuid
from pathlib import Path
from flask import Blueprint, request, jsonify

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

remix_bp = Blueprint('remix', __name__)
remix_service = None
_db_manager = None
_smart_segment_tasks = {}
_smart_segment_tasks_lock = threading.Lock()


def _normalize_segment_path(video_path):
    path = Path(str(video_path))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _resolve_existing_media_path(value):
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    try:
        path = path.resolve()
    except OSError:
        path = path.absolute()
    return path if path.is_file() else None


def _validate_export_timeline(timeline):
    if not isinstance(timeline, list) or not timeline:
        raise ValueError('参数错误：必须提供非空有效时间线')
    normalized = []
    for index, item in enumerate(timeline, 1):
        if not isinstance(item, dict):
            raise ValueError(f'参数错误：时间线第 {index} 段无效')
        source = item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path') or item.get('path')
        source_path = _resolve_existing_media_path(source)
        if not source_path:
            raise ValueError(f'参数错误：时间线第 {index} 段来源视频不存在')
        try:
            start = float(item.get('source_start', item.get('shot_start')))
            end = float(item.get('source_end', item.get('shot_end')))
        except (TypeError, ValueError):
            raise ValueError(f'参数错误：时间线第 {index} 段缺少有效起止时间')
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError(f'参数错误：时间线第 {index} 段范围无效')
        clip = dict(item)
        clip.update({'source_video': str(source_path), 'source_start': start, 'source_end': end})
        normalized.append(clip)
    return normalized


def _segment_request_signature(video_paths):
    normalized_paths = [_normalize_segment_path(path) for path in video_paths]
    return hashlib.sha256(json.dumps(normalized_paths, ensure_ascii=False).encode('utf-8')).hexdigest()


def _emit_smart_segment_event(event, payload):
    socketio = getattr(remix_service, 'socketio', None)
    if socketio:
        try:
            socketio.emit(event, payload)
        except Exception:
            logger.warning('混剪智能镜头分割 Socket.IO 通知失败')


def _update_smart_segment_task(task_id, **changes):
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        if not task:
            return None
        task.update(changes)
        task['updated_at'] = time.time()
        return dict(task)


def _smart_segment_task_payload(task):
    return {key: value for key, value in task.items() if key != 'signature'}


def register_remix_routes(app, db_manager, task_service, remix_svc):
    """注册混剪模式API路由"""
    global remix_service, _db_manager
    remix_service = remix_svc
    _db_manager = db_manager
    app.register_blueprint(remix_bp, url_prefix='/api/remix')
    logger.info('✅ 混剪模式API路由注册完成')


@remix_bp.route('/create', methods=['POST'])
def create_remix_project():
    """创建混剪项目"""
    try:
        data = request.get_json()
        result = remix_service.create_remix_project(data)
        return jsonify({'code': 0, 'msg': '项目创建成功', 'data': result})
    except Exception as e:
        logger.error(f'创建混剪项目失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/analyze', methods=['POST'])
def analyze_videos():
    """批量分析视频"""
    try:
        data = request.get_json() or {}
        video_paths = data.get('video_paths', [])
        scene_segmentation = data.get('scene_segmentation') or 'smart_shot'
        results = remix_service.batch_analyze_videos(
            video_paths,
            scene_segmentation=scene_segmentation,
            smart_shot_split=bool(data.get('smart_shot_split', scene_segmentation == 'smart_shot')),
            vision_model=data.get('vision_model') or data.get('visionModel'),
        )
        return jsonify({'code': 0, 'msg': '分析完成', 'data': results})
    except Exception as e:
        logger.error(f'分析视频失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'分析失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/highlights', methods=['POST'])
def detect_highlights():
    """识别精彩片段"""
    try:
        data = request.get_json()
        video_path = data.get('video_path')
        highlights = remix_service.detect_highlights(video_path)
        return jsonify({'code': 0, 'msg': '识别完成', 'data': highlights})
    except Exception as e:
        logger.error(f'识别精彩片段失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'识别失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/create-plan', methods=['POST'])
def create_plan():
    """创建混剪方案"""
    try:
        data = request.get_json()
        plan = remix_service.create_remix_plan(data['analyses'], data['config'])
        return jsonify({'code': 0, 'msg': '方案创建成功', 'data': plan})
    except Exception as e:
        logger.error(f'创建方案失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/process', methods=['POST'])
def process_remix():
    """执行混剪"""
    try:
        data = request.get_json()
        task_id = remix_service.process_remix(data['project_id'], data['plan'])
        return jsonify({'code': 0, 'msg': '任务已创建', 'data': {'task_id': task_id}})
    except Exception as e:
        logger.error(f'执行混剪失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'执行失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/generate', methods=['POST'])
def generate_remix():
    """统一的混剪生成入口

    前端 remix.html 中的 startRemix() 会调用此接口并传入：
        - name: 项目名称
        - video_paths: 源视频路径列表（上传后后端返回的路径或文件名）
        - style: 混剪风格（dynamic/calm/exciting/...）
        - target_duration: 目标时长
        - auto_highlight / auto_transition / auto_bgm: 若干自动选项
        - bgm_file / music_path: 背景音乐路径（音乐卡点模式）
        - transition_style: 转场风格

    此接口会：
        1）创建混剪项目；
        2）构造混剪 plan（包含视频列表、模式、BGM 等配置）；
        3）调用 RemixService.process_remix 启动后台任务；
        4）返回 project_id 与 task_id，供前端轮询进度。
    """
    try:
        if remix_service is None:
            return jsonify({'code': 1, 'msg': '混剪服务未初始化', 'data': None}), 500

        data = request.get_json() or {}

        name = data.get('name') or '混剪项目'
        video_paths = data.get('video_paths') or []
        if not isinstance(video_paths, list) or not video_paths:
            return jsonify({'code': 1, 'msg': '缺少视频素材 video_paths', 'data': None}), 400

        style = data.get('style') or 'dynamic'
        duration_mode = data.get('duration_mode')
        target_duration = data.get('target_duration_seconds', data.get('target_duration'))
        try:
            target_duration = float(target_duration)
        except (TypeError, ValueError):
            return jsonify({'code': 1, 'msg': '必须显式提供 target_duration_seconds', 'data': None}), 400
        if not math.isfinite(target_duration) or target_duration <= 0:
            return jsonify({'code': 1, 'msg': 'target_duration_seconds 必须为大于 0 的有限数值', 'data': None}), 400
        transition_style = data.get('transition_style') or data.get('transition') or 'auto'
        template = data.get('template') or 'vlog'
        quality = data.get('quality') or data.get('video_resolution') or '1080p'

        # 模板定义的是剪辑手法默认值：高光取舍、节拍密度、慢放与转场。
        # 前端已经联动时会传入具体参数，此处只为 API 调用或缺失字段补齐默认策略。
        template_defaults = {
            'highlight': {'style': 'exciting', 'mode': 'music', 'auto_highlight': True, 'beat_sensitivity': 'high', 'fast_keyframe': 'beat', 'slow_keyframe': 'climax', 'speed_curve': 'sharp', 'beat_transition': 'flash', 'rhythm_match': 'intense', 'sync_precision': 'frame'},
            'travel': {'style': 'calm', 'auto_highlight': True, 'beat_sensitivity': 'low', 'fast_keyframe': 'strong', 'slow_keyframe': 'transition', 'speed_curve': 'smooth', 'beat_transition': 'fade', 'rhythm_match': 'calm'},
            'food': {'style': 'calm', 'auto_highlight': True, 'beat_sensitivity': 'medium', 'fast_keyframe': 'strong', 'slow_keyframe': 'climax', 'speed_curve': 'smooth', 'beat_transition': 'fade', 'rhythm_match': 'calm'},
            'pet': {'style': 'dynamic', 'auto_highlight': True, 'beat_sensitivity': 'medium', 'fast_keyframe': 'beat', 'slow_keyframe': 'climax', 'speed_curve': 'smooth', 'beat_transition': 'zoom', 'rhythm_match': 'contrast'},
        }
        template_config = template_defaults.get(template, {})
        if not data.get('style') and template_config.get('style'):
            style = template_config['style']
        if not data.get('remix_mode') and template_config.get('mode'):
            data['remix_mode'] = template_config['mode']

        # 混剪模式（general / music），前端目前使用 selectedRemixMode
        remix_mode = (data.get('remix_mode')
                      or data.get('mode')
                      or data.get('selected_mode')
                      or 'general')

        # 视觉模型（前端 selectedVisionModel；默认 custom_vision 复用自定义 API）
        vision_model = data.get('vision_model') or data.get('visionModel') or 'custom_vision'

        # 高级节奏风格是用户明确应用的覆盖项：映射到实际剪辑风格，
        # 使普通混剪和音乐卡点引擎都能消费这一配置，而非只保存展示状态。
        advanced_style = data.get('advanced_style') or ''
        advanced_style_map = {
            # Mixed-cut rhythm packs used by frontend/templates/remix.html.
            'standard_mix': 'dynamic',
            'beat_flash': 'exciting',
            'trailer_punch': 'exciting',
            'story_arc': 'dynamic',
            'game_highlight': 'exciting',
            'vlog_flow': 'calm',
            'product_show': 'calm',
            'knowledge_cut': 'dynamic',
            'travel_montage': 'calm',
            'food_closeup': 'calm',
            'pet_reaction': 'dynamic',
            'calm_montage': 'calm',
            # Legacy aliases kept for old localStorage/project payloads.
            'highlight_mix': 'exciting',
            'cute_funny': 'dynamic',
            'live_sell': 'exciting',
            'slow_pace': 'calm',
            'deep_analysis': 'calm',
            'film_review': 'calm',
            'default': 'dynamic',
        }
        if advanced_style in advanced_style_map:
            style = advanced_style_map[advanced_style]

        # 1. 创建项目及素材
        project_result = remix_service.create_remix_project({
            'name': name,
            'video_paths': video_paths,
            'video_names': data.get('video_names') or [],
            'template': template,
            'quality': quality,
            'style': style,
            'duration_mode': duration_mode,
            'target_duration_seconds': target_duration,
            'transition': transition_style,
            'music_style': data.get('music_style', 'auto'),
            'auto_highlight': data.get('auto_highlight', True),
            'auto_bgm': data.get('auto_bgm', True),
            'shot_detection': data.get('shot_detection', 'cnn'),
            'scene_segmentation': data.get('scene_segmentation', 'smart_shot'),
            'smart_shot_split': bool(data.get('smart_shot_split', True)),
            'vision_model': vision_model
        })

        project_id = project_result.get('project_id') or project_result.get('project', {}).get('id')
        if not project_id:
            return jsonify({'code': 1, 'msg': '创建混剪项目失败：未获得项目ID', 'data': None}), 500

        # 2. 构造混剪 plan（先以 TaskService 基础实现为主）
        # 显式确定 auto_highlight：music 模式默认关闭，其他模式默认开启
        auto_highlight = data.get('auto_highlight')
        if auto_highlight is None:
            auto_highlight = template_config.get('auto_highlight', remix_mode != 'music')

        def template_value(field, *keys):
            for key in keys:
                value = data.get(key)
                if value is not None and value != '':
                    return value
            return template_config.get(field)

        plan = {
            'video_paths': video_paths,
            'template': template,
            'quality': quality,
            'video_resolution': data.get('video_resolution') or quality,
            'video_codec': data.get('video_codec') or 'h264',
            'bitrate_control': data.get('bitrate_control') or 'auto',
            'duration_mode': duration_mode,
            'target_duration_seconds': target_duration,
            'target_duration': target_duration,
            'style': style,
            'transition_style': transition_style,
            'auto_transition': bool(data.get('auto_transition', True)),
            'mode': remix_mode,
            'remix_mode': remix_mode,
            'auto_bgm': data.get('auto_bgm', True),
            'auto_voiceover': bool(data.get('auto_voiceover', False)),
            'auto_highlight': bool(auto_highlight),
            'segment_data': data.get('segment_data') if isinstance(data.get('segment_data'), dict) else None,
            'shot_detection': data.get('shot_detection', 'cnn'),
            'scene_segmentation': data.get('scene_segmentation', 'smart_shot'),
            'smart_shot_split': bool(data.get('smart_shot_split', True)),
            # 已应用的高级配置必须进入后台任务计划，避免“界面已应用”与实际成片不一致。
            'preferred_highlights': data.get('preferred_highlights') or [],
            'advanced_style': advanced_style,
            'dedup_plans': data.get('dedup_plans') or [],
            # BGM / 音乐卡点相关
            'bgm_file': data.get('bgm_file'),
            'music_path': data.get('music_path'),
            # 预留音乐卡点高级配置（若前端传入则一并保存，方便今后 BeatRemixEngine 使用）
            'beat_detection': template_value('beat_detection', 'beat_detection', 'beatDetection'),
            'beat_sensitivity': template_value('beat_sensitivity', 'beat_sensitivity', 'beatSensitivity'),
            'fast_keyframe': template_value('fast_keyframe', 'fast_keyframe', 'fastKeyframe'),
            'slow_keyframe': template_value('slow_keyframe', 'slow_keyframe', 'slowKeyframe'),
            'speed_curve': template_value('speed_curve', 'speed_curve', 'speedCurve'),
            'beat_transition': template_value('beat_transition', 'beat_transition', 'beatTransition'),
            'rhythm_match': template_value('rhythm_match', 'rhythm_match', 'rhythmMatch'),
            'sync_precision': template_value('sync_precision', 'sync_precision', 'syncPrecision'),
            # 视觉模型：混剪片段筛选时若启用云视觉增强，按此调用
            'vision_model': vision_model,
            # TTS 引擎与音色（普通模式生成配音时使用）
            'tts_engine': data.get('tts_engine'),
            'voice': data.get('voice'),
            # IndexTTS2 克隆语音参数
            'reference_audio': data.get('reference_audio') or '',
            'consent': bool(data.get('consent', False)),
            # 为调试保留原始配置
            'raw_config': data
        }

        # 音乐卡点模式 BGM 字段统一：若 music_path 为空但 bgm_file 有值，则回填 music_path，
        # 避免后端 BeatRemixEngine 等链路优先读 music_path 时丢失 BGM。
        if not plan.get('music_path') and plan.get('bgm_file'):
            plan['music_path'] = plan['bgm_file']

        # 3. 启动混剪任务
        task_id = remix_service.process_remix(project_id, plan)

        return jsonify({
            'code': 0,
            'msg': '混剪任务已创建',
            'data': {
                'project_id': project_id,
                'task_id': task_id,
                'plan': {
                    'mode': remix_mode,
                    'style': style,
                    'target_duration': target_duration,
                    'video_count': len(video_paths)
                }
            }
        })
    except Exception as e:
        logger.error(f'混剪生成失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'混剪生成失败: {str(e)}', 'data': None}), 500


@remix_bp.route('/progress/<task_id>', methods=['GET'])
def remix_progress(task_id):
    """查询混剪任务进度与结果

    前端 monitorRemixProgress(taskId) 轮询此接口，期望字段：
        - progress: 0-100
        - status: pending/running/completed/failed
        - video_url / output_file / duration / video_count 等（任务完成时）
    """
    try:
        if _db_manager is None:
            return jsonify({'code': 1, 'msg': '数据库管理器未初始化', 'data': None}), 500

        task = _db_manager.get_task(task_id)
        if not task:
            return jsonify({'code': 1, 'msg': '任务不存在', 'data': None}), 404

        # 解析 JSON 字段
        for key in ('input_data', 'output_data'):
            val = task.get(key)
            if isinstance(val, str) and val:
                try:
                    task[key] = json.loads(val)
                except Exception:
                    task[key] = {}

        output_data = task.get('output_data') or {}
        if not isinstance(output_data, dict):
            output_data = {}

        resp_data = {
            'task_id': task.get('id'),
            'project_id': output_data.get('project_id') or task.get('project_id'),
            'status': task.get('status'),
            'progress': task.get('progress') or 0,
            'error': task.get('error_message')
        }

        # 将输出结果关键字段扁平化，方便前端 showRemixResult 使用
        resp_data.update({
            'video_url': output_data.get('video_url'),
            'video_path': output_data.get('video_path') or output_data.get('output_path') or output_data.get('output_file'),
            'output_path': output_data.get('output_path') or output_data.get('output_file'),
            'output_file': output_data.get('output_file'),
            'duration': output_data.get('duration'),
            'target_duration_seconds': output_data.get('target_duration_seconds'),
            'actual_duration_seconds': output_data.get('actual_duration_seconds'),
            'duration_delta_seconds': output_data.get('duration_delta_seconds'),
            'duration_within_tolerance': output_data.get('duration_within_tolerance'),
            'duration_tolerance_seconds': output_data.get('duration_tolerance_seconds'),
            'duration_status': output_data.get('duration_status'),
            'duration_warnings': output_data.get('duration_warnings') or [],
            'duration_mode': output_data.get('duration_mode'),
            'video_count': output_data.get('video_count'),
            'mode': output_data.get('mode'),
            # 真实编辑模式标识，前端据此显示"智能混剪/基础合并/卡点混剪"
            'editing_mode': output_data.get('editing_mode'),
            'auto_highlight_used': output_data.get('auto_highlight_used'),
            'auto_highlight_requested': output_data.get('auto_highlight_requested'),
            'beat_remix_used': output_data.get('beat_remix_used'),
            'beat_remix_failure': output_data.get('beat_remix_failure'),
            'timeline': output_data.get('timeline') or [],
            'audio_paths': output_data.get('audio_paths') or [],
            'subtitle_text': output_data.get('subtitle_text') or '',
            'voiceover_error': output_data.get('voiceover_error'),
            'auto_voiceover_requested': bool(output_data.get('auto_voiceover_requested', False)),
        })

        return jsonify({'code': 0, 'msg': '获取成功', 'data': resp_data})
    except Exception as e:
        logger.error(f'获取混剪任务进度失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 1：智能镜头分割（剪映专业版风格，分析帧无上限）
# ================================================================== #
@remix_bp.route('/smart-segment', methods=['POST'])
def smart_segment_remix():
    """启动可轮询的混剪多素材智能镜头分割任务。"""
    if remix_service is None:
        return jsonify({'code': 1, 'msg': '混剪服务未初始化', 'data': None}), 500

    data = request.get_json() or {}
    video_paths = data.get('video_paths') or []
    if not isinstance(video_paths, list) or not video_paths:
        return jsonify({'code': 1, 'msg': '参数错误：缺少 video_paths', 'data': None}), 400

    normalized_paths = [_normalize_segment_path(path) for path in video_paths]
    signature = _segment_request_signature(video_paths)
    with _smart_segment_tasks_lock:
        for task in _smart_segment_tasks.values():
            if task.get('signature') == signature and task.get('status') in ('pending', 'running'):
                return jsonify({'code': 0, 'msg': '智能分割任务已在运行', 'data': {
                    'task_id': task['task_id'], 'reused': True, 'status': task['status']
                }})
        task_id = str(uuid.uuid4())
        _smart_segment_tasks[task_id] = {
            'task_id': task_id,
            'status': 'pending',
            'progress': 0,
            'message': '混剪智能镜头分割任务已创建',
            'result': None,
            'error': None,
            'signature': signature,
            'video_paths': normalized_paths,
            'created_at': time.time(),
            'updated_at': time.time(),
        }

    if _db_manager:
        try:
            _db_manager.create_task(
                task_id,
                'remix_smart_shot_segment',
                None,
                input_data={'video_paths': normalized_paths},
            )
        except Exception:
            logger.warning('混剪智能镜头分割任务写入数据库失败，将仅使用内存状态')

    def run_task():
        def report(progress, message, detail):
            progress = max(0, min(100, int(progress)))
            with _smart_segment_tasks_lock:
                task = _smart_segment_tasks.get(task_id)
                if task:
                    material_states = task.setdefault('material_states', {})
                    source_index = detail.get('source_index') if isinstance(detail, dict) else None
                    if source_index is not None and detail.get('status') in ('completed', 'skipped', 'failed'):
                        material_states[str(source_index)] = detail.get('status')
                    completed_count = sum(state == 'completed' for state in material_states.values())
                    skipped_count = sum(state in ('skipped', 'failed') for state in material_states.values())
                else:
                    completed_count = skipped_count = 0
            _update_smart_segment_task(task_id, status='running', progress=progress, message=message,
                                       current=detail, processed_video_count=completed_count,
                                       skipped_video_count=skipped_count)
            if _db_manager:
                try:
                    _db_manager.update_task_progress(task_id, progress)
                except Exception:
                    pass
            _emit_smart_segment_event('task_progress', {
                'task_id': task_id, 'progress': progress, 'message': message, 'current': detail
            })

        try:
            _update_smart_segment_task(task_id, status='running', message='正在初始化混剪智能镜头分割')
            if _db_manager:
                try:
                    _db_manager.update_task_status(task_id, 'running')
                except Exception:
                    pass
            _emit_smart_segment_event('task_status', {'task_id': task_id, 'status': 'running'})
            result = remix_service.smart_segment_remix_shots(
                video_paths=video_paths,
                threshold=float(data.get('threshold', 0.5)),
                use_transnetv2=bool(data.get('use_transnetv2', True)),
                max_shots_per_video=data.get('max_shots_per_video'),
                export_keyframes=bool(data.get('export_keyframes', True)),
                progress_callback=report,
            )
            _update_smart_segment_task(task_id, status='completed', progress=100,
                                       message='混剪智能镜头分割完成', result=result)
            if _db_manager:
                try:
                    _db_manager.update_task_status(task_id, 'completed', output_data=result)
                except Exception:
                    pass
            _emit_smart_segment_event('task_status', {'task_id': task_id, 'status': 'completed', 'result': result})
        except Exception as exc:
            message = str(exc) or '混剪智能镜头分割失败'
            logger.exception('混剪智能镜头分割任务失败: %s', task_id)
            _update_smart_segment_task(task_id, status='failed', message=message, error=message)
            if _db_manager:
                try:
                    _db_manager.update_task_status(task_id, 'failed', error_message=message)
                except Exception:
                    pass
            _emit_smart_segment_event('task_status', {'task_id': task_id, 'status': 'failed', 'error': message})

    threading.Thread(target=run_task, name=f'remix-smart-segment-{task_id[:8]}', daemon=True).start()
    return jsonify({'code': 0, 'msg': '混剪智能分割任务已启动', 'data': {'task_id': task_id, 'reused': False}})


@remix_bp.route('/smart-segment/<task_id>', methods=['GET'])
def get_smart_segment_remix_task(task_id):
    """查询混剪智能镜头分割内存任务状态与结果。"""
    with _smart_segment_tasks_lock:
        task = _smart_segment_tasks.get(task_id)
        snapshot = dict(task) if task else None
    if not snapshot:
        return jsonify({'code': 1, 'msg': '任务不存在或服务已重启', 'data': None}), 404
    return jsonify({'code': 0, 'msg': '查询成功', 'data': _smart_segment_task_payload(snapshot)})

# ================================================================== #
# 升级端点 2：普通模式混剪（高光 + 台词，一个画面一段配音）
# ================================================================== #
@remix_bp.route('/general-mode', methods=['POST'])
def general_mode_remix():
    """普通模式混剪

    请求体:
        - video_paths: 视频路径列表
        - voices: 配音段列表（可选）
        - target_duration: 目标时长（默认 60）
        - style: 风格 dynamic/calm/exciting
        - render: 是否渲染视频（默认 true）
        - output_path: 指定输出路径（可选）
    """
    try:
        if remix_service is None:
            return jsonify({'code': 1, 'msg': '混剪服务未初始化', 'data': None}), 500

        data = request.get_json() or {}
        video_paths = data.get('video_paths') or []
        if not isinstance(video_paths, list) or not video_paths:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 video_paths', 'data': None}), 400

        target_duration = data.get('target_duration_seconds', data.get('target_duration'))
        try:
            target_duration = float(target_duration)
        except (TypeError, ValueError):
            return jsonify({'code': 1, 'msg': '必须显式提供 target_duration_seconds', 'data': None}), 400
        if not math.isfinite(target_duration) or target_duration <= 0:
            return jsonify({'code': 1, 'msg': 'target_duration_seconds 必须为大于 0 的有限数值', 'data': None}), 400

        result = remix_service.general_mode_remix(
            video_paths=video_paths,
            voices=data.get('voices'),
            target_duration=target_duration,
            duration_mode=data.get('duration_mode'),
            style=data.get('style', 'dynamic'),
            preferred_highlights=data.get('preferred_highlights') or [],
            advanced_style=data.get('advanced_style', ''),
            dedup_plans=data.get('dedup_plans') or [],
            render=bool(data.get('render', True)),
            output_path=data.get('output_path', ''),
        )

        return jsonify({
            'code': 0,
            'msg': f'普通模式混剪完成，共 {result["clip_count"]} 个片段',
            'data': result
        })
    except Exception as e:
        logger.error(f'普通模式混剪失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'混剪失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 3：音乐卡点模式混剪（剪映智能卡点二风格）
# ================================================================== #
@remix_bp.route('/music-beat', methods=['POST'])
def music_beat_remix():
    """音乐卡点模式混剪

    请求体:
        - video_paths: 视频路径列表
        - music_path: BGM 路径
        - target_duration: 目标时长（默认 60）
        - beat_density: 卡点密度 dense/medium/sparse（默认 dense）
        - slow_motion_at_climax: 高潮段是否慢放（默认 true）
        - render: 是否渲染（默认 true）
        - output_path: 指定输出路径（可选）
    """
    try:
        if remix_service is None:
            return jsonify({'code': 1, 'msg': '混剪服务未初始化', 'data': None}), 500

        data = request.get_json() or {}
        video_paths = data.get('video_paths') or []
        music_path = data.get('music_path') or data.get('bgm_path')
        if not isinstance(video_paths, list) or not video_paths:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 video_paths', 'data': None}), 400
        if not music_path:
            return jsonify({'code': 1, 'msg': '参数错误：缺少 music_path', 'data': None}), 400

        target_duration = data.get('target_duration_seconds', data.get('target_duration'))
        try:
            target_duration = float(target_duration)
        except (TypeError, ValueError):
            return jsonify({'code': 1, 'msg': '必须显式提供 target_duration_seconds', 'data': None}), 400
        if not math.isfinite(target_duration) or target_duration <= 0:
            return jsonify({'code': 1, 'msg': 'target_duration_seconds 必须为大于 0 的有限数值', 'data': None}), 400

        result = remix_service.music_beat_remix(
            video_paths=video_paths,
            music_path=music_path,
            target_duration=target_duration,
            duration_mode=data.get('duration_mode'),
            beat_density=data.get('beat_density', 'dense'),
            slow_motion_at_climax=bool(data.get('slow_motion_at_climax', True)),
            preferred_highlights=data.get('preferred_highlights') or [],
            advanced_style=data.get('advanced_style', ''),
            dedup_plans=data.get('dedup_plans') or [],
            render=bool(data.get('render', True)),
            output_path=data.get('output_path', ''),
        )

        return jsonify({
            'code': 0,
            'msg': f'音乐卡点混剪完成，共 {result["clip_count"]} 个片段 / {result["beat_count"]} 个卡点',
            'data': result
        })
    except Exception as e:
        logger.error(f'音乐卡点混剪失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'卡点混剪失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 4：检测剪映草稿目录
# ================================================================== #
@remix_bp.route('/detect-jianying-draft-dir', methods=['GET'])
def detect_jianying_draft_dir():
    """自动检测剪映草稿目录"""
    try:
        from backend.utils.jianying_detector import detect_jianying_draft_info
        info = detect_jianying_draft_info()
        return jsonify({
            'code': 0,
            'msg': '检测成功' if info['detected'] and info['writable'] else info['message'],
            'data': info,
            # Compatibility for older remix-page helpers which read the
            # detector payload directly instead of from the data wrapper.
            'draft_dir': info['draft_dir'],
            'detected': info['detected'],
            'writable': info['writable'],
            'message': info['message'],
        })
    except Exception as e:
        logger.error(f'检测剪映草稿目录失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'检测失败: {str(e)}', 'data': None}), 500


# ================================================================== #
# 升级端点 5：导出剪映草稿包
# ================================================================== #
@remix_bp.route('/export-jianying-draft', methods=['POST'])
def export_jianying_draft():
    """从真实源素材时间线导出可编辑剪映草稿；成片路径仅作可选参考。"""
    try:
        data = request.get_json() or {}
        if not data.get('project_id'):
            return jsonify({'code': 1, 'msg': '参数错误：缺少 project_id', 'data': None}), 400
        try:
            timeline = _validate_export_timeline(data.get('timeline'))
        except ValueError as exc:
            return jsonify({'code': 1, 'msg': str(exc), 'data': None}), 400
        final_path = _resolve_existing_media_path(data.get('final_video_path') or data.get('video_path'))

        result = remix_service.export_jianying_draft(
            project_id=data['project_id'],
            timeline=timeline,
            final_video_path=str(final_path) if final_path else '',
            audio_paths=data.get('audio_paths', []),
            bgm_path=data.get('bgm_path', ''),
            subtitle_text=data.get('subtitle_text', ''),
            draft_dir=data.get('draft_dir', ''),
            export_basis=data.get('export_basis', 'remix_timeline'),
        )

        native = bool(result.get('native_jianying_project'))
        return jsonify({
            'code': 0,
            'msg': '剪映原生草稿已导出' if native else '本地草稿包已生成，需放入剪映草稿根目录才会被扫描',
            'data': result
        })
    except Exception as e:
        logger.error(f'混剪草稿导出失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'导出失败: {str(e)}', 'data': None}), 500
