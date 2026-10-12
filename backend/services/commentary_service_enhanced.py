"""
原创解说剪辑服务 - 完整AI流程实现
视频画面分析 → 文案生成 → 智能配音 → 三同步
"""

import logging
import os
import json
import time
import uuid
import re
import numpy as np
import hashlib
import cv2
import subprocess
from typing import Dict, Any, Optional
from pathlib import Path

from backend.config.ai_config import AIConfigurationError, AIRequestError, AIResponseError
from backend.config.paths import PROJECT_ROOT, AUDIO_DIR, TEMP_DIR, project_output_dir
from backend.engine import VideoProcessor
from backend.engine.video_composer import VideoComposer
from backend.engine.subtitle_generator import SubtitleGenerator

logger = logging.getLogger('JJYB_AI智剪')


class CommentaryServiceEnhanced:
    """原创解说剪辑服务 - 完整AI流程"""

    def __init__(self, db_manager, socketio, task_service):
        self.db_manager = db_manager
        self.socketio = socketio
        self.task_service = task_service

        # 初始化AI引擎
        self._init_ai_engines()

        logger.info('✅ 原创解说剪辑服务（增强版）初始化完成')

    @staticmethod
    def _project_media_url(path_value: str) -> str:
        """Return a browser URL only for media safely inside this project."""
        if not path_value:
            return ''
        try:
            path = Path(path_value)
            path = path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()
            return '/' + path.relative_to(PROJECT_ROOT.resolve()).as_posix()
        except (OSError, ValueError):
            logger.warning('无法将项目外媒体路径公开为浏览器地址: %s', path_value)
            return ''

    def _init_ai_engines(self):
        """初始化所有AI引擎 - 使用全局状态管理器"""
        try:
            # 获取全局状态管理器
            from backend.core.global_state import get_global_state
            self.global_state = get_global_state()

            # 从全局状态获取引擎实例
            self.vision_analyzer = self.global_state.get_vision_analyzer()
            logger.info('✅ 视觉分析引擎加载成功（全局）')
        except Exception as e:
            logger.warning(f'⚠️ 视觉分析引擎加载失败: {e}')
            self.vision_analyzer = None
            self.global_state = None

        # 从全局状态获取所有引擎
        if self.global_state:
            self.script_generator = self.global_state.get_script_generator()
            self.sync_engine = self.global_state.get_sync_engine()
            self.tts_engine = self.global_state.get_tts_engine()
            self.multi_model = self.global_state.get_multi_model_manager()
            self.config_manager = self.global_state.config_manager
            logger.info('✅ 所有AI引擎从全局状态加载完成')
        else:
            self.script_generator = None
            self.sync_engine = None
            self.tts_engine = None
            self.multi_model = None
            self.config_manager = None

    def create_project(self, data: Dict) -> Dict:
        """创建原创解说项目"""
        try:
            logger.info('🎬 创建原创解说项目...')

            project = self.db_manager.create_project(
                name=data.get('name', '原创解说项目'),
                project_type='commentary',
                description='AI原创解说剪辑',
                template='commentary'
            )

            project_id = project['id']

            # 保存配置
            config = {
                'video_path': data.get('video_path', ''),
                'source_duration_seconds': data.get('source_duration_seconds'),
                'target_duration_seconds': data.get('target_duration_seconds'),
                'script': data.get('script', ''),
                'voice': data.get('voice') or self._default_voice_id(),
                # 默认使用本地 pyttsx3，避免在无网络环境下频繁触发云TTS失败
                'tts_engine': data.get('tts_engine') or data.get('ttsEngine') or 'pyttsx3',
                'auto_subtitle': data.get('auto_subtitle', True),
                'auto_bgm': data.get('auto_bgm', True),
                'style': data.get('style', 'professional'),
                # 字幕样式相关配置：允许前端覆盖默认大号样式和位置/字号
                'subtitle_style': data.get('subtitle_style') or data.get('subtitleStyle') or 'large',
                'subtitle_position': data.get('subtitle_position') or data.get('subtitlePosition') or 'bottom',
                'subtitle_font_size': data.get('subtitle_font_size') or data.get('subtitleFontSize') or None,
                # 高级字幕样式：字体 / 颜色 / 描边 / 背景
                'subtitle_font': data.get('subtitle_font') or data.get('subtitleFont') or None,
                'subtitle_color': data.get('subtitle_color') or data.get('subtitleColor') or None,
                'subtitle_bg_color': data.get('subtitle_bg_color') or data.get('subtitleBgColor') or None,
                'subtitle_stroke_color': data.get('subtitle_stroke_color') or data.get('subtitleStrokeColor') or None,
                'subtitle_stroke_width': data.get('subtitle_stroke_width') or data.get('subtitleStrokeWidth') or None,
            }

            # 保存音量控制配置
            voice_volume = data.get('voice_volume')
            bgm_volume = data.get('bgm_volume')
            original_audio_volume = data.get('original_audio_volume')
            if voice_volume is not None:
                config['voice_volume'] = float(voice_volume)
            if bgm_volume is not None:
                config['bgm_volume'] = float(bgm_volume)
            if original_audio_volume is not None:
                config['original_audio_volume'] = float(original_audio_volume)
            if 'keep_original_audio' in data:
                config['keep_original_audio'] = bool(data.get('keep_original_audio'))
            else:
                config['keep_original_audio'] = float(config.get('original_audio_volume', 0) or 0) > 0
            for key in ('llm', 'vision_model', 'template', 'sceneAccuracy', 'emotionAnalysis', 'emotionTone',
                        'narrationMode', 'scriptStructure', 'targetAudience', 'scriptLength', 'creativityLevel',
                        'custom_prompt', 'video_resolution', 'target_platform'):
                if key in data:
                    config[key] = data.get(key)
            config['original_audio_plan'] = data.get('original_audio_plan') or {
                'enabled': bool(data.get('insert_original_audio', False)),
                'mode': data.get('original_audio_mode', 'ratio'),
                'target_ratio': data.get('original_audio_ratio'),
                'legacy_interval': data.get('original_clip_interval', 3),
                'legacy_clip_duration': data.get('original_clip_duration', 3.0),
                'volume': config.get('original_audio_volume'),
            }
            config['workbench'] = {
                'voice_segments': data.get('voice_segments') or [],
                'shot_segmentation': data.get('shot_segmentation') or {},
                'puppet_sync': data.get('puppet_sync') or {},
            }
            if isinstance(data.get('ui_state'), dict):
                config['ui_state'] = data['ui_state']

            self.db_manager.update_project(project_id, {'config': config})

            logger.info(f'✅ 项目创建成功: {project_id}')

            return {
                'code': 0,
                'msg': '项目创建成功',
                'data': {
                    'project_id': project_id,
                    'project': project,
                    'config': config
                }
            }

        except Exception as e:
            logger.error(f'❌ 创建项目失败: {e}', exc_info=True)
            return {'code': 1, 'msg': f'创建失败: {str(e)}', 'data': None}

    def process_video(self, project_id: str, video_path: str, config: Dict, task_id: Optional[str] = None) -> Dict:
        """
        完整处理流程：分析 → 生成 → 配音 → 同步
        """
        task_id = task_id or str(uuid.uuid4())
        try:
            logger.info(f'🚀 开始处理项目: {project_id}')

            # 允许断点恢复复用原任务，但绝不重复插入同一 task_id。
            existing_task = self.db_manager.get_task(task_id)
            if existing_task:
                self.db_manager.update_task_status(task_id, 'running')
            else:
                self.db_manager.create_task(
                    task_id=task_id,
                    task_type='commentary_process',
                    project_id=project_id,
                    input_data={'video_path': video_path, 'config': config}
                )
                self.db_manager.update_task_status(task_id, 'running')

            from backend.services.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()
            if checkpoint_service.get_checkpoint(task_id) is None:
                checkpoint_service.create_checkpoint(task_id, project_id, 'commentary')
            checkpoint = checkpoint_service.update_checkpoint(
                task_id, stage='upload', stage_progress=100,
                stage_data={'video_path': video_path, 'config': config}, status='running',
                metadata={'video_path': video_path, 'config': config}
            )
            if checkpoint is None:
                raise RuntimeError(f'无法写入任务检查点: {task_id}')
            checkpoint_service.mark_stage_completed(task_id, 'upload')

            # 发送进度
            self._emit_progress(task_id, 0, '开始处理...')

            # 步骤1: 视频分析 (0-30%)
            self._emit_progress(task_id, 5, '正在分析视频画面...')
            vision_results = self._analyze_video(video_path, task_id, config)

            if not vision_results:
                raise Exception('视频分析失败')

            self._emit_progress(task_id, 30, '视频分析完成')
            checkpoint_service.mark_stage_completed(
                task_id, 'analyze', {'vision_results': vision_results}
            )

            # 步骤2: 生成或采用用户确认的文案 (30-50%)
            provided_script = config.get('script')
            use_provided_script = bool(config.get('use_provided_script'))
            if use_provided_script and provided_script:
                self._emit_progress(task_id, 35, '正在采用已应用的高级文案...')
                if isinstance(provided_script, dict):
                    script = provided_script
                else:
                    script_text = str(provided_script).strip()
                    script = {
                        'title': '',
                        'opening': '',
                        'segments': [{'text': script_text}],
                        'closing': ''
                    }
                logger.info('✅ 已采用前端确认的高级/手动文案作为本次成片脚本')
            else:
                self._emit_progress(task_id, 35, '正在生成解说文案...')
                script = self._generate_script(vision_results, config, task_id)

            if not script:
                raise Exception('文案生成失败')

            self._emit_progress(task_id, 50, '文案生成完成')
            checkpoint_service.mark_stage_completed(task_id, 'script_generate', {'script': script})

            # 步骤3: 智能配音（优先复用前端已逐段生成的配音）
            voice_segments = config.get('voice_segments') or []
            reusable_segment_records = self._validated_voice_segment_records(voice_segments)
            reusable_segments = [Path(item['voice_path']) for item in reusable_segment_records]
            if reusable_segments:
                self._emit_progress(task_id, 55, f'正在复用 {len(reusable_segments)} 段已生成配音...')
                audio_path = self._concat_existing_voice_segments(reusable_segments, task_id)
            else:
                self._emit_progress(task_id, 55, '正在生成配音...')
                audio_path = self._generate_voiceover(script, config, task_id)

            if not audio_path:
                raise Exception('配音生成失败')
            if (config.get('voice_segments') or config.get('precomputed_shots')
                    or (config.get('shot_segmentation') or {}).get('shots')) and not reusable_segment_records:
                raise RuntimeError('工作台请求包含分镜/配音数据，但没有可复用的逐段配音；已停止整段配音降级，避免音画字幕失去一一对应')

            self._emit_progress(task_id, 70, '配音生成完成')
            checkpoint_service.mark_stage_completed(task_id, 'tts_generate', {'audio_path': audio_path})

            # The regular "complete processing" entry must not discard a
            # user-created segment voice track and then trim the source from 0s.
            # Build the exact same storyboard used by the workbench renderer.
            storyboard_timeline = self._build_workbench_storyboard(
                config=config, voices=reusable_segment_records, video_path=video_path, vision_results=vision_results,
            )
            has_workbench_inputs = bool(
                config.get('voice_segments')
                or config.get('precomputed_shots')
                or (config.get('shot_segmentation') or {}).get('shots')
            )
            if has_workbench_inputs and not storyboard_timeline:
                raise RuntimeError(
                    '原创解说未建立逐段故事板时间线，已停止旧版普通合成，'
                    '请先完成智能分镜和全部逐段配音后再生成成片'
                )
            if storyboard_timeline:
                config['_storyboard_timeline'] = storyboard_timeline
                self._emit_progress(task_id, 75, '已建立逐段音画故事板时间线')
            else:
                logger.warning(
                    '本次快速预览未提供工作台镜头池和逐段配音，将使用旧预览链路；'
                    '该结果不应视为智能精剪成片'
                )

            # 步骤4: 三同步处理 (70-90%)
            self._emit_progress(task_id, 75, '正在执行三同步...')
            if storyboard_timeline:
                subtitle_segments = [
                    {
                        'start': item['timeline_start'], 'end': item['timeline_end'],
                        'start_time': item['timeline_start'], 'end_time': item['timeline_end'],
                        'text': item.get('subtitle_text', ''),
                    }
                    for item in storyboard_timeline if item.get('subtitle_text')
                ]
                sync_results = {
                    'storyboard_timeline': storyboard_timeline,
                    'audio_video_sync': {'aligned_segments': storyboard_timeline, 'method': 'storyboard'},
                    'audio_text_sync': {'subtitle_segments': subtitle_segments, 'method': 'storyboard'},
                    'text_video_sync': {'aligned_segments': storyboard_timeline, 'method': 'storyboard'},
                    'sync_quality': 1.0,
                }
            else:
                sync_results = self._sync_all(video_path, audio_path, script, vision_results, task_id, config)
            if not isinstance(sync_results, dict):
                # 同步引擎失败（返回 None 或异常吞掉），使用保底估算结果，保证后续合成/字幕/剪映草稿不中断
                logger.warning('⚠️ 三同步引擎返回空，已按音频时长顺序估算字幕，并生成基础对齐结构')
                _audio_path_obj = Path(audio_path)
                if not _audio_path_obj.is_absolute():
                    _audio_path_obj = PROJECT_ROOT / _audio_path_obj
                fallback_script = self._estimate_subtitle_script(script, _audio_path_obj) or {'narrations': []}
                fallback_segments = []
                for n in fallback_script.get('narrations', []):
                    try:
                        ts = str(n.get('time_range', '0s-0s'))
                        if 's-' in ts:
                            a, b = ts.split('s-', 1)
                            st = max(0.0, float(a.replace('s', '')))
                            et = max(st, float(b.replace('s', '')))
                        else:
                            st, et = 0.0, 0.0
                        fallback_segments.append({'start': st, 'start_time': st, 'end': et, 'end_time': et, 'text': str(n.get('text', '')).strip()})
                    except Exception:
                        continue
                sync_results = {
                    'audio_video_sync': {'aligned_segments': [], 'beats': [], 'tempo': 0.0},
                    'audio_text_sync': {
                        'subtitle_segments': fallback_segments,
                        'narrations': fallback_script.get('narrations', []),
                        'fallback': True,
                    },
                    'text_video_sync': {'aligned_segments': []},
                    'sync_quality': 0.1,
                }

            self._emit_progress(task_id, 90, '三同步完成')
            checkpoint_service.mark_stage_completed(task_id, 'subtitle_align', {'sync_results': sync_results})

            # 步骤5: 生成最终视频 (90-100%)
            self._emit_progress(task_id, 95, '正在生成最终视频...')
            output_path = self._compose_final_video(
                video_path, audio_path, script, sync_results, config, task_id
            )

            if not output_path:
                raise Exception('视频合成失败，未生成输出文件')
            # 合成器已通过 FFprobe 校验流与时长；这里保留文件大小校验以防路径转换异常。
            _out_path_check = Path(output_path)
            if not _out_path_check.is_absolute():
                _out_path_check = PROJECT_ROOT / _out_path_check
            if (not _out_path_check.exists()) or (not _out_path_check.is_file()) or (_out_path_check.stat().st_size < 1024):
                raise Exception(f'视频合成输出异常，文件不存在或过小: {_out_path_check}')

            self._emit_progress(task_id, 100, '处理完成！')
            output_url = self._project_media_url(output_path)
            if not output_url:
                raise Exception(f'成片不在项目可访问目录中: {output_path}')
            checkpoint_service.mark_stage_completed(task_id, 'video_compose', {'output_path': output_path, 'output_url': output_url})
            checkpoint_service.mark_stage_completed(task_id, 'export', {'output_path': output_path, 'output_url': output_url})
            checkpoint_service.update_checkpoint(task_id, status='completed')

            # 更新任务状态
            # 任务完成
            self.db_manager.update_task_progress(task_id, 100)
            self.db_manager.update_task_status(task_id, 'completed')

            # 保存结果
            result_data = {
                'vision_analysis': vision_results,
                'script': script,
                'audio_path': audio_path,
                'sync_results': sync_results,
                'output_path': output_path,
                'output_url': output_url
            }
            # 将结果转换为 JSON 安全结构，避免 numpy.ndarray 等对象导致序列化失败
            safe_result_data = result_data
            try:
                safe_result_data = json.loads(
                    json.dumps(result_data, ensure_ascii=False, default=lambda o: None)
                )
            except Exception as e:
                logger.warning(f'⚠️ 项目结果JSON序列化失败，将使用精简结果结构: {e}')
                try:
                    va = result_data.get('vision_analysis') or {}
                except Exception:
                    va = {}
                safe_result_data = {
                    'vision_analysis': {
                        'scenes': va.get('scenes'),
                        'descriptions': va.get('descriptions'),
                        'summary': va.get('summary')
                    },
                    'script': result_data.get('script'),
                    'audio_path': result_data.get('audio_path'),
                    'sync_results': result_data.get('sync_results'),
                    'output_path': result_data.get('output_path'),
                    'output_url': result_data.get('output_url')
                }

            # 保存到项目
            self.db_manager.update_task_status(task_id, 'completed', output_data=safe_result_data)
            self.db_manager.update_project(project_id, {
                'result': safe_result_data,
                'status': 'completed'
            })

            # 将原视频、配音、字幕、成片登记为素材，并写入统一 tracks
            try:
                self._register_project_artifacts(
                    project_id, video_path, audio_path,
                    sync_results, output_path, config
                )
            except Exception as aerr:
                logger.warning(f'⚠️ 写入项目素材/tracks 失败（不影响主流程）: {aerr}')

            logger.info(f'✅ 项目处理完成: {project_id}')

            return {
                'code': 0,
                'msg': '处理完成',
                'data': {
                    'task_id': task_id,
                    'output_path': output_path,
                    'output_url': output_url,
                    'result': safe_result_data
                }
            }

        except Exception as e:
            logger.error(f'❌ 处理失败: {e}', exc_info=True)
            from backend.services.checkpoint_service import get_checkpoint_service
            checkpoint = get_checkpoint_service().update_checkpoint(
                task_id, status='failed', error_message=str(e),
                metadata={'failure_stage': 'processing', 'failure_error': str(e)}
            )
            if checkpoint is None:
                logger.error('无法将失败状态写入检查点: %s', task_id)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            return {'code': 1, 'msg': f'处理失败: {str(e)}', 'data': None}

    def _strict_ai_results_enabled(self) -> bool:
        return bool(self.config_manager and self.config_manager.global_config.strict_ai_results)

    def _analyze_video(self, video_path: str, task_id: str, config: Optional[Dict] = None) -> Optional[Dict]:
        """步骤1: 视频画面分析"""
        try:
            # 确保配置始终为字典，避免 NameError
            if config is None:
                config = {}

            if not self.vision_analyzer:
                if self._strict_ai_results_enabled():
                    raise AIConfigurationError()
                logger.warning('视觉分析引擎不可用，使用简化分析')
                return self._simple_video_analysis(video_path)

            precomputed_shots = config.get('precomputed_shots')

            # ========= 基于文件签名与预计算分镜的视频分析缓存 =========
            cache_file = None
            try:
                # 使用绝对路径 + 文件大小 + 修改时间 构建稳定签名
                video_abs = os.path.abspath(video_path)
                stat = os.stat(video_abs)
                sig_src = f"{video_abs}|{stat.st_size}|{int(stat.st_mtime)}"
                if isinstance(precomputed_shots, list):
                    stable_shots = [
                        {
                            'start_time': shot.get('start_time'), 'end_time': shot.get('end_time'),
                            'start_frame': shot.get('start_frame'), 'end_frame': shot.get('end_frame'),
                        }
                        for shot in precomputed_shots if isinstance(shot, dict)
                    ]
                    shots_digest = hashlib.sha256(
                        json.dumps(stable_shots, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
                    ).hexdigest()
                    sig_src += f'|shots:{shots_digest}'
                cache_key = hashlib.md5(sig_src.encode('utf-8')).hexdigest()

                analysis_dir = TEMP_DIR / 'analysis'
                analysis_dir.mkdir(parents=True, exist_ok=True)
                cache_file = analysis_dir / f'frame_analysis_{cache_key}.json'
            except Exception as e:
                logger.warning(f'⚠️ 计算视频签名失败，将不使用缓存: {e}')
                cache_file = None

            # 1. 优先尝试复用缓存结果。云视觉曾失败的缓存必须重新分析，
            # 否则修复配置后仍会持续生成与视频无关的宽泛文案。
            if cache_file and cache_file.exists() and not self._strict_ai_results_enabled():
                try:
                    with cache_file.open('r', encoding='utf-8') as f:
                        cached = json.load(f)
                    cloud_vision = cached.get('cloud_vision') or {} if isinstance(cached, dict) else {}
                    descriptions = cached.get('descriptions') or [] if isinstance(cached, dict) else []
                    has_enhanced_descriptions = any(
                        isinstance(item, dict) and str(item.get('enhanced_description') or '').strip()
                        for item in descriptions
                    )
                    cache_is_usable = (
                        isinstance(cached, dict)
                        and cached.get('scenes') is not None
                        and cloud_vision.get('available') is not False
                        and (not cloud_vision.get('attempted') or has_enhanced_descriptions)
                    )
                    if cache_is_usable:
                        logger.info(f'📂 复用视频分析缓存: {cache_file}')
                        self._emit_progress(task_id, 25, '已复用视频分析缓存')
                        return cached
                    logger.warning('⚠️ 视频分析缓存缺少有效云视觉描述，忽略缓存并重新分析')
                except Exception as e:
                    logger.warning(f'⚠️ 读取视频分析缓存失败，将重新分析: {e}')

            logger.info('🎬 开始视频画面分析...')

            # 2. 使用视觉分析引擎。智能镜头分割默认启用，逐帧识别镜头边界后为每段保留代表画面。
            scene_accuracy = str(config.get('sceneAccuracy') or config.get('scene_accuracy') or 'smart_shot').lower()
            def report_analysis_stage(progress_or_msg, maybe_msg=None):
                # vision_analyzer 支持两种签名：progress_callback(progress, message) 或 progress_callback(message)
                if isinstance(progress_or_msg, (int, float)):
                    stage_pct = max(0.0, min(100.0, float(progress_or_msg)))
                    message = maybe_msg if isinstance(maybe_msg, str) else '正在分析视频画面...'
                else:
                    stage_pct = 50.0
                    message = str(progress_or_msg)
                # 画面分析占总体进度的 18% -> 48% 区间，占比 30 个百分点
                overall = int(round(18 + stage_pct / 100.0 * 30))
                self._emit_progress(task_id, overall, message)

            results = self.vision_analyzer.analyze_video(
                video_path,
                max_keyframes=15,
                scene_accuracy=scene_accuracy,
                progress_callback=report_analysis_stage,
                precomputed_scenes=precomputed_shots,
            )
            if results:
                results.setdefault('analysis_source', 'local_vision')

            # 3. 严格模式下，每一个可用关键帧都必须获得云视觉描述。
            keyframes = (results or {}).get('keyframes') or []
            descriptions = (results or {}).get('descriptions') or []
            strict_ai_results = bool(config.get('strict_ai_results', self._strict_ai_results_enabled()))
            if strict_ai_results and (not self.multi_model or not self.config_manager):
                logger.warning('strict_ai_results 已启用但多模型管理器未就绪，跳过云视觉增强')
            if self.multi_model and self.config_manager and keyframes:
                logger.info('使用已配置的云视觉模型增强画面描述')
                analysis_dir = TEMP_DIR / 'analysis'
                analysis_dir.mkdir(parents=True, exist_ok=True)
                # 读取前端传入的视觉模型选择；默认 custom_vision 复用自定义 API 配置
                vision_model_type = (config or {}).get('vision_model') or 'custom_vision'
                enhanced_count = 0

                for i, frame_info in enumerate(keyframes):
                    frame_info = frame_info or {}
                    frame = frame_info.get('image')
                    img_path: Optional[Path] = None
                    if frame is not None:
                        ts = frame_info.get('timestamp') or i
                        img_path = analysis_dir / f'mm_keyframe_{int(ts)}_{i}.jpg'
                        if not cv2.imwrite(str(img_path), frame):
                            img_path = None
                    if img_path is None:
                        candidate = frame_info.get('image_path') or frame_info.get('path') or frame
                        if isinstance(candidate, str) and os.path.exists(candidate):
                            img_path = Path(candidate)
                    if img_path is None or not img_path.exists():
                        if strict_ai_results:
                            logger.warning('云视觉增强跳过关键帧 %s：图像不可用（strict模式下也仅警告）', i + 1)
                        else:
                            logger.warning('云视觉增强跳过关键帧 %s：图像不可用', i + 1)
                        results['cloud_vision'] = {
                            'attempted': True,
                            'available': False,
                            'reason': 'response_invalid',
                        }
                        continue
                    try:
                        enhanced_desc = self.multi_model.analyze_image(
                            str(img_path),
                            '请准确描述画面中的场景、主体、动作、情绪和氛围；看不清时明确说明；使用简洁中文，不超过100字。',
                            model_type=vision_model_type
                        )
                    except (AIConfigurationError, AIRequestError, AIResponseError) as exc:
                        # 云视觉增强是可选增强，不是必需步骤。
                        # 即使 strict_ai_results=True，也只警告并回退到本地分析，
                        # 绝不因为单个关键帧的云视觉失败而阻断整个视频分析流程。
                        logger.warning('云视觉增强关键帧 %s 失败，回退到本地分析: %s (cause=%s)', i + 1, exc.code, exc.__cause__ or '')
                        results['cloud_vision'] = {
                            'attempted': True,
                            'available': False,
                            'reason': 'request_failed' if isinstance(exc, AIRequestError) else 'response_invalid',
                        }
                        continue
                    except Exception as exc:
                        logger.warning('云视觉增强关键帧 %s 请求异常，回退到本地分析: %s', i + 1, exc)
                        results['cloud_vision'] = {
                            'attempted': True,
                            'available': False,
                            'reason': 'request_failed',
                        }
                        continue
                    if not isinstance(enhanced_desc, str) or not enhanced_desc.strip():
                        logger.warning('云视觉增强关键帧 %s 返回空描述，继续使用本地分析', i + 1)
                        results['cloud_vision'] = {
                            'attempted': True,
                            'available': False,
                            'reason': 'response_invalid',
                        }
                        continue
                    while len(descriptions) <= i:
                        descriptions.append({})
                    descriptions[i]['enhanced_description'] = enhanced_desc.strip()
                    enhanced_count += 1
                    self._emit_progress(task_id, 10 + i * 2, f'分析关键帧 {i + 1}...')
                results['descriptions'] = descriptions
                if enhanced_count > 0:
                    results['cloud_vision'] = {
                        'attempted': True,
                        'available': True,
                        'enhanced_count': enhanced_count,
                        'total_keyframes': len(keyframes),
                    }
            elif strict_ai_results and not (self.multi_model and self.config_manager):
                # strict 模式下多模型未配置，仅警告不阻断
                logger.warning('strict_ai_results 已启用但多模型管理器未就绪，跳过云视觉增强')
            if not results:
                logger.error('❌ 视频分析返回空结果')
                return None

            logger.info(f'✅ 视频分析完成: {len(results.get("scenes", []))}个场景, {len(results.get("keyframes", []))}个关键帧')

            # 4. 智能场景筛选：评估场景质量并筛选高分场景
            try:
                from backend.engine.scene_scorer import score_and_filter_scenes

                scenes = results.get('scenes', [])
                # 获取目标时长（用于智能筛选）
                target_duration = config.get('target_duration') or config.get('target_duration_seconds')
                if target_duration:
                    try:
                        target_duration = float(target_duration)
                    except Exception:
                        target_duration = None

                # 收集对象检测结果
                objects_list = [obj_info.get('objects', []) for obj_info in results.get('objects', [])]

                # 执行评分和筛选
                if precomputed_shots:
                    logger.info('📌 使用预计算分镜，保持场景与关键帧分析结果一一对应，跳过二次筛选')
                elif scenes and len(scenes) > 3:  # 只在场景数>3时才筛选
                    logger.info(f'🧠 开始智能场景筛选: 原始{len(scenes)}个场景')
                    filtered_scenes = score_and_filter_scenes(
                        scenes=scenes,
                        video_path=video_path,
                        objects_list=objects_list if objects_list else None,
                        target_duration=target_duration
                    )

                    if filtered_scenes and len(filtered_scenes) < len(scenes):
                        # 筛选成功，更新结果
                        results['scenes'] = filtered_scenes
                        results['original_scenes'] = scenes  # 保留原始场景供参考
                        logger.info(
                            f'✅ 智能筛选完成: '
                            f'{len(scenes)}个场景 → {len(filtered_scenes)}个高质量场景, '
                            f'平均评分: {np.mean([s.get("score", 0) for s in filtered_scenes]):.1f}'
                        )
                    else:
                        logger.info('📌 场景质量均衡，无需筛选')
                else:
                    logger.info(f'📌 场景数量较少({len(scenes)})，跳过筛选')

            except Exception as e:
                logger.warning(f'⚠️ 智能场景筛选失败，使用原始场景: {e}')

            # 5. 写入缓存（去除不可序列化字段）
            if cache_file:
                try:
                    safe_results = json.loads(
                        json.dumps(results, ensure_ascii=False, default=lambda o: None)
                    )
                    with cache_file.open('w', encoding='utf-8') as f:
                        json.dump(safe_results, f, ensure_ascii=False)
                    logger.info(f'💾 已写入视频分析缓存: {cache_file}')
                except Exception as e:
                    logger.warning(f'⚠️ 写入视频分析缓存失败: {e}')

            return results

        except (AIConfigurationError, AIRequestError, AIResponseError):
            raise
        except Exception:
            logger.exception('视频分析服务发生未预期错误')
            return None

    @staticmethod
    def _clean_script_line(text: Any) -> str:
        value = re.sub(r'\s+', ' ', str(text or '').strip())
        value = re.sub(r'(\.\.\.+|\u2026\u2026+)$', '', value).strip()
        return value

    def _postprocess_generated_script(self, script: Dict[str, Any], target_duration: Optional[float] = None) -> Dict[str, Any]:
        if not isinstance(script, dict):
            return script
        terminal_re = re.compile(r'[\u3002\uff01\uff1f!?;\uff1b]$')
        incomplete_tail_re = re.compile(r'[\uff0c\u3001:\uff1a\uff08(\u300a\u201c\"\']$')
        raw_items = []
        if isinstance(script.get('opening'), str):
            raw_items.append(('opening', {'text': script.get('opening')}))
        for idx, segment in enumerate(script.get('segments') or []):
            if isinstance(segment, dict):
                segment_item = dict(segment)
                segment_item['index'] = segment_item.get('index', idx)
                raw_items.append(('segment', segment_item))
            elif isinstance(segment, str):
                raw_items.append(('segment', {'index': idx, 'text': segment}))
        if isinstance(script.get('closing'), str):
            raw_items.append(('closing', {'text': script.get('closing')}))

        cleaned = []
        dropped = 0
        for kind, item in raw_items:
            text = self._clean_script_line(item.get('text'))
            if not text:
                continue
            if len(text) < 6 and terminal_re.search(text):
                if cleaned:
                    cleaned[-1][1]['text'] = (cleaned[-1][1]['text'] + text).strip()
                else:
                    dropped += 1
                continue
            previous = cleaned[-1][1]['text'] if cleaned else ''
            if cleaned and (len(text) < 10 or incomplete_tail_re.search(previous) or not terminal_re.search(previous)):
                cleaned[-1][1]['text'] = (previous + text).strip()
                continue
            item['text'] = text
            cleaned.append((kind, item))

        if not cleaned:
            return script
        opening = ''
        closing = ''
        segments = []
        for kind, item in cleaned:
            text = item.get('text', '')
            if kind == 'opening' and not opening:
                opening = text
            elif kind == 'closing':
                closing = text
            else:
                segment = dict(item)
                segment['index'] = len(segments)
                segment['text'] = text
                segments.append(segment)
        if not segments and opening:
            segments.append({'index': 0, 'text': opening})
            opening = ''
        result = dict(script)
        if opening:
            result['opening'] = opening
        if closing:
            result['closing'] = closing
        result['segments'] = segments
        total_chars = sum(len(seg.get('text', '')) for seg in segments) + len(opening) + len(closing)
        estimated_duration = total_chars / 3.5 if total_chars else 0.0
        warnings = list(result.get('warnings') or [])
        if dropped:
            warnings.append(f'dropped {dropped} incomplete generated script fragments')
        if target_duration and estimated_duration > float(target_duration) * 1.15:
            warnings.append('generated script is longer than target duration; consider shortening or increasing speech speed')
        if warnings:
            result['warnings'] = warnings
        result['estimated_duration_seconds'] = round(estimated_duration, 2)
        return result

    def _generate_script(self, vision_results: Dict, config: Dict, task_id: str) -> Optional[Dict]:
        """步骤2: AI生成解说文案"""
        try:
            # 1. 根据前端传入的 llm 选择动态切换当前使用的 LLM 模型
            llm_from_config = None
            try:
                llm_from_config = (config.get('llm') or config.get('llm_model') or '').strip()  # type: ignore[arg-type]
            except Exception:
                llm_from_config = None

            # 项目选择的模型仅作用于本次生成，不能改写系统默认模型或影响并发项目。
            script_generator = None
            if self.global_state:
                try:
                    script_generator = self.global_state.create_script_generator(llm_from_config)
                except Exception as e:
                    logger.error(f'❌ 获取请求级文案生成引擎失败: {e}', exc_info=True)
            else:
                script_generator = self.script_generator

            if not script_generator:
                logger.warning('文案生成引擎不可用，使用模板文案')
                return self._template_script(vision_results)

            logger.info('📝 开始生成解说文案...')

            # 获取风格（前端发送 camelCase 字段名）
            style = config.get('scriptStyle') or config.get('style') or 'professional'
            narration_mode = config.get('narrationMode') or config.get('narration_mode') or 'general'
            mode_lower = (narration_mode or 'general').lower()

            # 根据解说类型自动选择合适的开头钩子类型
            # 默认使用悬念式；若前端传了 hookType 且非 auto，则用前端值覆盖
            hook_type = 'suspense'
            user_hook = str(config.get('hookType') or config.get('hook_type') or '').strip()
            if user_hook and user_hook != 'auto':
                hook_type = user_hook
            elif mode_lower in ('anime', 'romance', 'animation_3rd', 'travel_edu'):
                # 动漫/情感/旅行类，更适合情感共鸣型开头
                hook_type = 'empathy'
            elif mode_lower in ('film_explain', 'film_3rd', 'short_drama', 'suspense_twist'):
                # 影视解说/短剧，突出剧情反转
                hook_type = 'reversal'
            elif mode_lower in ('documentary', 'tech'):
                # 纪录片/科技数码，适合问题引导型或信息型开头
                hook_type = 'question'
            elif mode_lower in ('food', 'food_commentary', 'variety', 'sports'):
                # 美食探店/综艺/体育，更适合感叹式钩子
                hook_type = 'exclamation'
            elif mode_lower == 'film_1st':
                # 第一人称强代入，悬念式更抓人
                hook_type = 'suspense'

            # 整理前端传入的高级配置，用于构建自定义创作要求
            # 注意：前端发送的是 camelCase 字段名（scriptLength/scriptStructure/targetAudience/creativityLevel）
            template = config.get('template') or 'custom'
            emotion_tone = config.get('emotion_tone') or config.get('emotionTone') or 'neutral'
            structure = config.get('scriptStructure') or config.get('structure') or 'complete'
            target_audience = config.get('targetAudience') or config.get('target_audience') or 'general'
            length = config.get('scriptLength') or config.get('length') or 'medium'
            creativity = config.get('creativityLevel') or config.get('creativity') or 'moderate'

            # 目标时长：优先使用前端传入的 target_duration_seconds，其次使用视觉分析中的 duration
            target_duration = config.get('target_duration_seconds') or vision_results.get('duration')
            try:
                if target_duration is not None:
                    target_duration = float(target_duration)
            except Exception:
                target_duration = vision_results.get('duration')

            # 当用户选择目标时长小于整段视频时，仅基于前 target_duration 秒的场景生成文案
            vision_for_script = vision_results
            try:
                full_duration = None
                if 'duration' in vision_results:
                    full_duration = float(vision_results.get('duration') or 0.0)
            except Exception:
                full_duration = None

            if target_duration and full_duration and target_duration < full_duration - 0.5:
                try:
                    scenes = vision_results.get('scenes') or []
                    new_scenes = []
                    for idx, sc in enumerate(scenes):
                        try:
                            sc_start = float(sc.get('start_time', 0.0) or 0.0)
                            sc_end = float(sc.get('end_time', sc_start) or sc_start)
                        except Exception:
                            sc_start, sc_end = 0.0, 0.0

                        # 完全超出目标时长的场景直接丢弃
                        if sc_start >= target_duration:
                            break

                        # 与目标时长有交集的最后一个场景，截断到目标时长
                        if sc_end > target_duration:
                            sc_end = target_duration

                        if sc_end <= sc_start:
                            continue

                        sc_new = dict(sc)
                        sc_new['start_time'] = float(sc_start)
                        sc_new['end_time'] = float(sc_end)
                        sc_new['duration'] = float(sc_end - sc_start)
                        new_scenes.append(sc_new)

                    # 按场景数量截断描述/情绪信息，避免与场景错位
                    desc_list = (vision_results.get('descriptions') or [])[:len(new_scenes)]
                    emo_list = (vision_results.get('emotions') or [])[:len(new_scenes)]
                    obj_list = (vision_results.get('objects') or [])[:len(new_scenes)]

                    vision_for_script = dict(vision_results)
                    vision_for_script['scenes'] = new_scenes
                    vision_for_script['descriptions'] = desc_list
                    vision_for_script['emotions'] = emo_list
                    vision_for_script['objects'] = obj_list
                    vision_for_script['duration'] = float(target_duration)
                except Exception as e:
                    logger.warning(f'⚠️ 基于目标时长截断场景失败，将使用完整视频分析: {e}')

            # 将结构、长度、创意度等枚举值映射为更易理解的中文描述
            structure_map = {
                'complete': '完整起承转合结构',
                'direct': '直接切入结构（省略开头，开门见山）',
                'suspense': '悬念式结构（引发好奇，逐步揭晓）',
                'question': '提问互动式结构（用问题引导观众）',
                'outline': '提纲式要点结构',
                'three_act': '三幕式结构（开端-发展-高潮/结局）',
                'episode': '分集递进结构',
                'highlight': '高光集锦结构',
                'arc': '角色成长弧结构',
                'hook_line_sinker': '钩子-展开-收网结构',
                'chronicle': '编年史结构',
            }
            length_map = {
                'short': '整体字数偏短，控制在约100-200字',
                'medium': '标准长度，控制在约200-400字',
                'long': '内容更详细，控制在约400-800字',
                'auto': '根据视频时长自动计算合适字数',
            }
            creativity_map = {
                'conservative': '创意度偏保守，以事实和画面为主，少用夸张和网络梗',
                'low': '创意度偏保守，以事实和画面为主，少用夸张和网络梗',
                'moderate': '适度创意，在保证信息准确的前提下增强吸引力',
                'creative': '创意度较高，可以合理虚构细节增强故事性，但不能违背画面内容',
                'high': '创意度较高，可以合理虚构细节增强故事性，但不能违背画面内容',
            }
            audience_map = {
                'general': '面向大众观众，语言口语化、易懂',
                'young': '面向年轻人（18-30岁），语言活泼、可适度使用网络流行语',
                'professional': '面向专业人士，可适度使用专业术语、逻辑更严谨',
                'family': '面向家庭用户，语言温和积极、避免冲突性表达',
                'senior': '面向中老年观众，语速放缓、表达朴实直白',
                'kids': '面向儿童或家庭用户，语言温和、积极、避免复杂表达',
            }

            structure_desc = structure_map.get(str(structure), str(structure))

            base_chars = None
            if target_duration:
                try:
                    base_chars = max(60, int(float(target_duration) * 3.5))
                except Exception:
                    base_chars = None

            if base_chars:
                length_str = str(length)
                if length_str == 'short':
                    min_chars = int(base_chars * 0.6)
                    max_chars = int(base_chars * 0.85)
                elif length_str == 'long':
                    min_chars = int(base_chars * 1.0)
                    max_chars = int(base_chars * 1.35)
                elif length_str == 'auto':
                    min_chars = int(base_chars * 0.8)
                    max_chars = int(base_chars * 1.1)
                else:
                    min_chars = int(base_chars * 0.75)
                    max_chars = int(base_chars * 1.05)
                length_desc = f'整体字数控制在约{min_chars}-{max_chars}字，使正常语速朗读时长尽量贴近剪辑后目标视频时长（约{target_duration:.0f}秒）。'
            else:
                length_desc = length_map.get(str(length), str(length))

            creativity_desc = creativity_map.get(str(creativity), str(creativity))
            audience_desc = audience_map.get(str(target_audience), str(target_audience))

            # 基于模板补充具体的创作方法，避免仅将模板键名直接暴露给模型。
            template_requirements_map = {
                'food_commentary': '''
- 美食解说写法：采用短视频探店/后厨跟拍口吻，开头优先用价格反差、稀缺食材、排队热度或一道菜的核心看点制造钩子；随后按画面中可见的备料、清洗、切配、烹饪、摆盘、食用顺序推进。
- 描写重点：说清食材、关键动作、火候或工艺、成品卖相和口感联想；多用短句与有画面感的动词，节奏明快、口语自然，让观众能跟着镜头“看懂这口吃的”。
- 信息边界：只描述画面已出现或视频资料明确给出的食材、价格、产地、工艺和口感；无法确认的店名、价格、产地、时长、味道不要编造。对味觉使用“看起来、像是、预计会”等审慎表达。
- 收束方式：结尾概括这道菜最突出的风味或性价比，并用一句自然互动收尾；不要生硬分段、不要使用标题、不要堆砌夸张形容词。'''
            }
            template_requirement = template_requirements_map.get(template, '')
            user_custom_prompt = str(config.get('custom_prompt') or '').strip()

            # 组合成交给大模型的自定义创作要求
            # 文稿风格（scriptStyle）→ 中文创作指引映射，让 LLM 理解每种风格的具体含义
            script_style_map = {
                'professional': '正式解说风格：语言规范严谨，措辞精准，逻辑清晰，适合科技/评测/知识类内容。',
                'casual': '轻松幽默风格：语言活泼生动，多用口语和比喻，节奏轻快，适合综艺/生活/搞笑类内容。',
                'passionate': '激情澎湃风格：语言高燃热血，善用感叹号和短句，情绪饱满，适合体育/游戏/战斗类内容。',
                'suspense': '悬疑推理风格：善用悬念和伏笔，信息逐步释放，营造紧张感，适合犯罪/推理/惊悚类内容。',
                'emotional': '情感共鸣风格：措辞细腻感性，注重情绪渲染和心理描写，适合爱情/亲情/治愈类内容。',
                'calm': '平和叙述风格：语调温和舒缓，娓娓道来，不刻意制造冲突，适合风景/文化/慢生活类内容。',
                'documentary': '纪录片风格：语调深沉稳重，用词客观准确，兼具故事性与知识性，适合科普/历史/人文类内容。',
                '中二热血': '中二热血风格：语言高燃中二，配合战斗名场面和热血台词，角色称呼统一，适合动漫/番剧解说。',
                '爽点密集': '爽点密集风格：快节奏强反转，每30秒一个钩子，密集制造冲突和反转，适合短剧/爽文类内容。',
                'sensory_detail': '感官细节风格：多用五感描写（色香味触声），画面感极强，适合美食/探店/旅行类内容。',
                'narrative_plain': '叙事白描风格：简洁克制的白描手法，不加过度修饰，以事实推进为主，适合新闻/纪实类内容。',
                'hook_reverse': '钩子反转风格：每段结尾留钩子，频繁使用反转和意外，制造"下一秒发生什么"的悬念，适合悬疑/剧情类内容。',
            }
            script_style_desc = script_style_map.get(str(style), '')
            if not script_style_desc:
                # 未匹配到的 style 值，用原始值兜底
                script_style_desc = f'文稿风格：{style}（请按此风格基调创作）'

            custom_requirements_lines = [
                f"- 模板/类型偏好：{template}（可以据此选择更贴合的叙事风格，例如影视解说/动画解说/纪录片解说等）",
                f"- 文稿风格：{script_style_desc}",
                f"- 目标受众：{audience_desc}",
                f"- 文稿结构：{structure_desc}",
                f"- 文稿长度：{length_desc}",
                f"- 创意程度：{creativity_desc}",
                f"- 情感基调：整体情绪基调倾向于“{emotion_tone}”，请在措辞和节奏上体现这一点。"
            ]
            if template_requirement:
                custom_requirements_lines.append(template_requirement.strip())
            if user_custom_prompt:
                custom_requirements_lines.append(f"- 用户自定义提示词：{user_custom_prompt}")
            if target_duration:
                custom_requirements_lines.append(
                    f"- 目标整体时长：约{float(target_duration):.0f}秒，请控制文稿节奏和信息密度，使朗读时长与该目标大致匹配。"
                )

            # 若前端或工作台传入了4.2解说风格写作人格，把NarrationStyles提示词注入LLM
            narration_style_key = (
                config.get('narrationStyle')
                or config.get('narration_style')
                or (config.get('advancedParams') or {}).get('narration_style')
                or ''
            )
            narration_style_key = str(narration_style_key or '').strip()
            if narration_style_key:
                try:
                    from backend.prompts.narration_styles import NarrationStyles
                    if narration_style_key in NarrationStyles.STYLES:
                        style_prompt = NarrationStyles.get_style_prompt(narration_style_key).strip()
                        if style_prompt:
                            custom_requirements_lines.append(
                                "- 写作风格设定（按4.2解说风格配置）：\n" + style_prompt
                            )
                except Exception as _exc:
                    logger.warning(f'加载NarrationStyles失败，跳过风格人格提示: {_exc}')
            narrative_view = str(
                config.get('narrativeView')
                or config.get('narrative_view')
                or (config.get('advancedParams') or {}).get('narrative_view')
                or ''
            ).strip()
            emotion_density = str(
                config.get('emotionDensity')
                or config.get('emotion_density')
                or (config.get('advancedParams') or {}).get('emotion_density')
                or ''
            ).strip()
            _nv_map = {
                'third': '以第三人称上帝视角叙述，视角客观全面，不使用"我"作为故事主角。',
                'first': '以第一人称代入视角叙述，使用"我"增强观众代入感。',
                'inner': '使用主角内心独白的视角，突出心理活动和情绪，不使用上帝视角解释。',
                'objective': '完全客观中立叙述，隐藏叙述者，只展示画面中的事实、动作和对话。'
            }
            _ed_map = {
                'low': '情感浓度低：以叙事为主，措辞克制，不煽情，情绪表达到位点到为止。',
                'medium': '情感浓度适中：叙事和情感并重，在关键镜头适当使用情绪词和感叹。',
                'high': '情感浓度高：整体用情绪化表达，重要场景强烈使用感叹、修辞和情绪渲染。',
                'extreme': '情感浓度极高：爆点密集，整体用强烈感叹、疑问和情绪化措辞点燃观众。'
            }
            if narrative_view and _nv_map.get(narrative_view):
                custom_requirements_lines.append(f"- 叙事视角设定：{_nv_map[narrative_view]}")
            if emotion_density and _ed_map.get(emotion_density):
                custom_requirements_lines.append(f"- 情感浓度设定：{_ed_map[emotion_density]}")

            custom_requirements_lines.extend([
                '- Write a complete chronological narration arc: opening, development, turning point, and ending.',
                '- Every segment must be a complete sentence and must not end with ellipsis, comma, colon, or an unfinished phrase.',
                '- Each narration segment should correspond to a visible shot/time range from the source video; do not invent unrelated events.',
                '- Avoid isolated one-line fragments. Adjacent segments must connect causally so the final video can be understood from beginning to end.',
            ])

            custom_prompt = "\n".join(custom_requirements_lines)

            logger.info(f'📝 调用文案生成器，目标时长: {target_duration}秒')
            script = script_generator.generate_script(
                vision_analysis=vision_for_script,
                style=style,
                duration=target_duration,
                narration_mode=narration_mode,
                custom_prompt=custom_prompt,
                hook_type=hook_type
            )

            # 立即检查生成的文案字数
            if script and script.get('segments'):
                total_chars = sum(len(seg.get('text', '')) for seg in script['segments'])
                estimated_duration = total_chars / 3.5
                logger.info(
                    f'📊 文案生成完成: 总字数={total_chars}字, '
                    f'预计时长={estimated_duration:.1f}秒, '
                    f'目标时长={target_duration}秒'
                )
                if target_duration and estimated_duration > target_duration * 1.2:
                    logger.error(
                        f'❌ 文案严重超标！预计{estimated_duration:.1f}秒 > 目标{target_duration}秒的1.2倍，'
                        f'字数控制可能失败！'
                    )

            if not isinstance(script, dict):
                try:
                    script = json.loads(script)
                except Exception as exc:
                    logger.warning('文案生成结果不是结构化JSON，使用模板文案: %s', exc)
                    return self._template_script(vision_results)

            return self._postprocess_generated_script(script, target_duration)

        except (AIConfigurationError, AIRequestError, AIResponseError):
            raise
        except Exception as exc:
            logger.exception('文案生成服务发生未预期错误')
            return self._template_script(vision_results)

    def _optimize_script(self, script_text: str, config: Dict, task_id: str) -> Optional[Dict]:
        """AI优化已有解说文稿

        接收用户已有文稿文本，调用LLM进行润色优化，返回结构化文稿。
        """
        try:
            if not script_text or not script_text.strip():
                return None

            llm_from_config = None
            try:
                llm_from_config = (config.get('llm') or config.get('llm_model') or '').strip()  # type: ignore[arg-type]
            except Exception:
                llm_from_config = None

            script_generator = None
            if self.global_state:
                try:
                    script_generator = self.global_state.create_script_generator(llm_from_config)
                except Exception as e:
                    logger.error(f'❌ 获取请求级文案生成引擎失败: {e}', exc_info=True)
            else:
                script_generator = self.script_generator

            if not script_generator:
                logger.warning('文案生成引擎不可用，无法优化文稿')
                return None

            logger.info('✨ 开始AI优化解说文稿...')

            style = config.get('scriptStyle') or config.get('style') or 'professional'
            emotion_tone = config.get('emotionTone') or config.get('emotion_tone') or 'neutral'
            target_audience = config.get('targetAudience') or config.get('target_audience') or 'general'
            creativity = config.get('creativityLevel') or config.get('creativity') or 'moderate'

            prompt = (
                f"你是一位专业的视频解说文案编辑。请对以下解说文稿进行优化润色，"
                f"使其更加流畅、生动、有吸引力。\n\n"
                f"风格要求：{style}\n"
                f"情感基调：{emotion_tone}\n"
                f"目标受众：{target_audience}\n"
                f"创意程度：{creativity}\n\n"
                f"优化要求：\n"
                f"1. 保持原有核心内容和信息不变\n"
                f"2. 优化语句流畅度和节奏感\n"
                f"3. 增强表达力和感染力\n"
                f"4. 修正语法和用词问题\n"
                f"5. 适当增加过渡和衔接\n\n"
                f"请以JSON格式返回优化后的文稿，格式为：\n"
                f'{{"title": "标题", "opening": "开头引言", '
                f'"segments": [{{"text": "段落1"}}, {{"text": "段落2"}}], '
                f'"closing": "结尾"}}\n\n'
                f"原始文稿：\n{script_text}"
            )

            try:
                result_text = script_generator._call_provider(prompt)
            except Exception as exc:
                logger.error(f'❌ LLM优化文稿请求失败: {exc}', exc_info=True)
                return None

            if not result_text or not str(result_text).strip():
                logger.warning('LLM优化文稿返回空结果')
                return None

            result_str = str(result_text).strip()
            try:
                if result_str.startswith('```json'):
                    result_str = result_str.replace('```json', '', 1).rsplit('```', 1)[0].strip()
                elif result_str.startswith('```'):
                    result_str = result_str.replace('```', '', 1).rsplit('```', 1)[0].strip()
                script = json.loads(result_str)
            except Exception:
                logger.info('优化结果非JSON格式，包装为结构化文稿')
                parts = [p.strip() for p in result_str.split('\n\n') if p.strip()]
                if not parts:
                    return None
                script = {
                    'title': '优化文稿',
                    'opening': parts[0] if parts else '',
                    'segments': [{'text': p} for p in parts[1:-1]] if len(parts) > 2 else [],
                    'closing': parts[-1] if len(parts) > 1 else ''
                }

            logger.info('✅ AI优化文稿完成')
            return script

        except (AIConfigurationError, AIRequestError, AIResponseError):
            raise
        except Exception as exc:
            logger.exception('AI优化文稿服务发生未预期错误')
            return None

    def _validated_voice_segments(self, segments: Any) -> list:
        """返回可复用的前端分段配音文件路径（按序号排序）；兼容两种结构：
        A. 旧格式：segment.status=='ready' + segment.voice_path + segment.duration>0
        B. 新工作台格式：segment.audio_path / segment.audio_url + (segment.duration or segment.duration_seconds)
        任一 segment 无效时，仅跳过该段，不再整体放弃，以免"已经配好很多段但因为1段空白全部重生成"。
        """
        return [Path(item['voice_path']) for item in self._validated_voice_segment_records(segments)]

    def _validated_voice_segment_records(self, segments: Any) -> list:
        """Return ready narration records without losing text/duration alignment."""
        if not isinstance(segments, list) or not segments:
            return []
        validated = []
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                continue
            # 状态判断：有 status 就按 status 判定，无 status 则只要有 audio_path/audio_url 就视为 ready
            status_ok = True
            if segment.get('status') is not None:
                status_ok = (str(segment.get('status', '')).lower() in ('ready', 'done', 'success', 'ok', 'true', '1'))
            # 音频路径：voice_path（旧）/ audio_path / audio_url（相对路径也能映射回 PROJECT_ROOT）
            path_value = (
                segment.get('voice_path')
                or segment.get('audio_path')
                or segment.get('audio_url')
                or ''
            )
            path_value = str(path_value or '').strip()
            # audio_url 往往是 /api/download/output/xxx.mp3，需要还原真实路径
            if path_value and path_value.startswith('/api/download/'):
                path_value = path_value[len('/api/download/'):]
            if not path_value:
                continue
            # 时长校验（宽松：允许 0 时长，但实际文件不存在时再过滤）
            duration = 0.0
            for _dk in ('duration', 'duration_seconds'):
                try:
                    _dv = float(segment.get(_dk, 0) or 0)
                    if _dv > 0:
                        duration = _dv
                        break
                except (TypeError, ValueError):
                    pass
            # 找文件
            audio_file = Path(path_value)
            if not audio_file.is_absolute():
                audio_file = PROJECT_ROOT / audio_file
            try:
                if not audio_file.exists() or not audio_file.is_file():
                    # 再试相对 static
                    audio_file_alt = PROJECT_ROOT / 'frontend' / 'static' / Path(path_value).name
                    if audio_file_alt.exists() and audio_file_alt.is_file():
                        audio_file = audio_file_alt
                    else:
                        continue
            except Exception:
                continue
            # 如果 duration 还是 0，则用 ffprobe 实测兜底
            if duration <= 0:
                try:
                    from backend.utils.file_utils import get_audio_duration_safe
                    _ffd = float(get_audio_duration_safe(str(audio_file)) or 0.0)
                    if _ffd > 0:
                        duration = _ffd
                        segment['duration'] = duration
                        segment['duration_seconds'] = duration
                except Exception:
                    pass
            if duration <= 0:
                continue
            if not status_ok:
                continue
            text = str(segment.get('text') or '').strip()
            if not text:
                continue
            idx = int(segment.get('index', index))
            validated.append((idx, {
                'index': idx, 'id': str(segment.get('id') or f'voice_{idx}'),
                'text': text, 'voice_path': str(audio_file.resolve()),
                'duration': duration,
            }))
        validated.sort(key=lambda item: item[0])
        return [record for _, record in validated]

    def _build_workbench_storyboard(self, config: Dict[str, Any], voices: list, video_path: str,
                                    vision_results: Optional[Dict[str, Any]] = None) -> list:
        """Plan a true segment timeline when the workbench supplied real inputs.

        Returning an empty list means this request did not contain the workbench
        prerequisites.  A partial set is an error: silently replacing a user's
        segment soundtrack with a first-N-seconds preview is never acceptable.
        """
        supplied_voices = config.get('voice_segments') or []
        supplied_shots = config.get('precomputed_shots') or (config.get('shot_segmentation') or {}).get('shots') or []
        if not supplied_voices and not supplied_shots:
            return []
        if not supplied_voices or not supplied_shots:
            raise RuntimeError('原创解说精剪需要同时具备逐段配音和智能分镜；缺少其中一项，已停止以避免普通裁切冒充智能成片')
        if len(voices) != len([item for item in supplied_voices if isinstance(item, dict) and str(item.get('text') or '').strip()]):
            raise RuntimeError('存在未完成或无效的配音段，已停止生成，避免字幕与配音错位')
        from backend.engine.storyboard_planner import StoryboardPlanner
        from backend.engine.puppet_sync_engine import PuppetSyncEngine

        descriptions = []
        for position, raw_description in enumerate((vision_results or {}).get('descriptions') or []):
            if not isinstance(raw_description, dict):
                continue
            text = str(raw_description.get('enhanced_description') or raw_description.get('description') or raw_description.get('summary') or '').strip()
            if not text:
                continue
            timestamp = raw_description.get('timestamp', raw_description.get('time', raw_description.get('start_time')))
            try:
                timestamp = float(timestamp)
            except (TypeError, ValueError):
                timestamp = float(position)
            descriptions.append((timestamp, text))
        normalized_shots = []
        for position, raw in enumerate(supplied_shots):
            if not isinstance(raw, dict):
                continue
            start = float(raw.get('start_time', raw.get('start', 0)) or 0)
            end = float(raw.get('end_time', raw.get('end', 0)) or 0)
            duration = float(raw.get('duration', 0) or 0)
            if end <= start:
                end = start + duration
            if end <= start:
                continue
            item = dict(raw)
            midpoint = (start + end) / 2
            if descriptions:
                nearest_description = min(descriptions, key=lambda entry: abs(entry[0] - midpoint))[1]
                item['description'] = str(raw.get('description') or nearest_description)
            item.update({
                'id': str(raw.get('id') or raw.get('shot_id') or f'shot_{position}'),
                'start_time': start, 'end_time': end, 'duration': end - start,
                'source_video': str(raw.get('source_video') or raw.get('video_path') or video_path),
            })
            normalized_shots.append(item)
        if not normalized_shots:
            raise RuntimeError('智能分镜没有有效源时间范围，无法建立真实音画时间线')
        planned_shots = StoryboardPlanner().plan(normalized_shots, voices)
        timeline = PuppetSyncEngine().match_shots_to_voices(
            planned_shots, voices, allow_reuse=False, insert_original_audio=False,
        )
        logger.info('🎬 完整处理入口已使用故事板时间线: %s 段配音 / %s 个源窗口', len(voices), len(timeline))
        return timeline


    def _concat_existing_voice_segments(self, voice_paths: list, task_id: str) -> str:
        """用 concat demuxer 顺序拼接已有分段配音；失败时不重新生成 TTS。"""
        output_dir = PROJECT_ROOT / 'output'
        output_dir.mkdir(parents=True, exist_ok=True)
        concat_file = output_dir / f'commentary_voice_concat_{task_id}_{uuid.uuid4().hex[:6]}.txt'
        output_file = output_dir / f'commentary_audio_reused_{int(time.time())}_{uuid.uuid4().hex[:6]}.m4a'
        try:
            with open(concat_file, 'w', encoding='utf-8', newline='\n') as handle:
                for voice_path in voice_paths:
                    escaped_path = voice_path.as_posix().replace("'", "'\\''")
                    handle.write(f"file '{escaped_path}'\n")
            result = subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file), '-c:a', 'aac', str(output_file)],
                capture_output=True, text=True, timeout=600
            )
            if result.returncode != 0 or not output_file.exists():
                raise RuntimeError((result.stderr or 'ffmpeg concat failed').strip()[-1000:])
            logger.info('复用 %d 段已生成配音，不重新合成TTS', len(voice_paths))
            return str(output_file.relative_to(PROJECT_ROOT)).replace('\\', '/')
        except Exception as exc:
            raise RuntimeError(f'已有分段配音拼接失败，未重新生成TTS: {exc}') from exc
        finally:
            try:
                concat_file.unlink(missing_ok=True)
            except OSError:
                pass

    def _generate_voiceover(self, script: Dict[str, Any], config: Dict[str, Any], task_id: str) -> Optional[str]:
        """步骤3: 智能配音

        供完整流程 process_video 与 /api/commentary/generate-voiceover 调用。
        返回相对项目根目录的路径，例如: "output/commentary_audio_xxx.mp3"。
        """
        try:
            if not self.tts_engine:
                logger.warning('⚠️ TTS引擎不可用')
                return None

            # 聚合脚本文本（支持脚本为结构化字典或纯字符串）
            full_text = ''

            # 1）优先按结构化 dict 解析（title + opening + segments + closing）
            if isinstance(script, dict):
                try:
                    parts = []
                    title = script.get('title') or ''
                    if title:
                        parts.append(title)
                    opening = script.get('opening') or ''
                    if opening:
                        parts.append(opening)
                    for seg in script.get('segments') or []:
                        text = seg.get('text') or ''
                        if text:
                            parts.append(text)
                    closing = script.get('closing') or ''
                    if closing:
                        parts.append(closing)
                    full_text = "\n".join(parts).strip()
                except Exception as e:
                    # 结构化解析失败时，退回到纯文本模式，避免 AttributeError: 'str' object has no attribute 'get'
                    logger.warning(f'⚠️ 脚本结构化解析失败，将按纯文本处理: {e}')
                    try:
                        full_text = str(script).strip()
                    except Exception:
                        full_text = ''

            # 2）如果不是 dict，或上一步未能成功生成文本，则退回到字符串处理
            if not full_text:
                if isinstance(script, str):
                    full_text = script.strip()
                else:
                    try:
                        full_text = str(script).strip()
                    except Exception:
                        full_text = ''

            if not full_text:
                raise Exception('脚本内容为空，无法生成配音')

            # 获取音色参数，不使用 or 运算符避免空字符串被当作 False
            voice = config.get('voice')
            if not voice:  # 只在真正为空时才用全局 TTS 默认音色
                from backend.services.voiceover_service import VoiceoverService
                voice = VoiceoverService._default_voice_id()
            logger.info(f'🎤 用户选择的音色: {voice}')

            # 前端可选指定首选 TTS 引擎；未指定时沿用全局默认引擎。
            try:
                raw_engine = (config.get('tts_engine') or config.get('ttsEngine') or '').strip().lower()
            except Exception:
                raw_engine = ''
            engine_aliases = {
                'edge': 'edge-tts',
                'edgetts': 'edge-tts',
                'azure-tts': 'azure',
                'google': 'gtts',
                'google-tts': 'gtts',
                'local': 'pyttsx3',
                'offline': 'pyttsx3',
            }
            preferred_engine = engine_aliases.get(raw_engine, raw_engine) or None

            # 输出到项目根目录下的 output/commentary_audio_*.mp3，便于前端通过 /output 静态路由访问
            file_name = f"commentary_audio_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
            rel_path = f"output/{file_name}"
            out_path = PROJECT_ROOT / 'output' / file_name
            out_path.parent.mkdir(parents=True, exist_ok=True)

            success = False

            # 按用户选择或全局默认引擎合成；Edge-TTS 失败时由统一服务回退本地引擎。
            engine0 = preferred_engine or getattr(self.tts_engine, 'default_engine', 'edge-tts') or 'edge-tts'
            logger.info(f'🎵 正在调用 {engine0} 引擎，音色: {voice}')

            # 从 config 中提取 advanced_config（如果有）
            advanced_config = config.get('advanced_config') or {}
            # 兼容旧字段：emotion_tone/emotionTone 也映射进去
            _et = config.get('emotionTone') or config.get('emotion_tone')
            if _et and not advanced_config.get('emotion_type'):
                advanced_config['emotion_type'] = _et

            try:
                success = self.tts_engine.synthesize(
                    text=full_text,
                    output_path=str(out_path),
                    engine=engine0,
                    voice=voice,
                    rate='+0%',
                    volume='+0%',
                    advanced_config=advanced_config if advanced_config else None
                )
            except Exception as e:
                logger.error(f"❌ TTS 引擎({engine0}) 合成失败: {e}", exc_info=True)
                success = False

            # Edge-TTS 等在线引擎不可用时，仅回退到已注册的本地 pyttsx3。
            if (not success or not out_path.exists()) and engine0 != 'pyttsx3':
                available = list(getattr(self.tts_engine, 'available_engines', []) or [])
                if 'pyttsx3' in available:
                    try:
                        logger.warning(f'⚠️ {engine0} 合成失败，回退本地 pyttsx3')
                        success = self.tts_engine.synthesize(
                            text=full_text,
                            output_path=str(out_path),
                            engine='pyttsx3',
                            voice=voice,
                            rate='+0%',
                            volume='+0%'
                        )
                    except Exception as e:
                        logger.error(f"❌ 本地 pyttsx3 回退合成失败: {e}", exc_info=True)
                        success = False

            if not success or not out_path.exists():
                raise Exception('配音文件生成失败')

            # 读取配音实际时长，用于重新调整字幕时间轴（直接使用 ffprobe，兼容音频文件）
            try:
                cmd = [
                    'ffprobe',
                    '-v', 'error',
                    '-show_entries', 'format=duration',
                    '-of', 'default=noprint_wrappers=1:nokey=1',
                    str(out_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                actual_audio_duration = 0.0
                if result.returncode == 0:
                    dur_str = (result.stdout or '').strip()
                    try:
                        if dur_str:
                            actual_audio_duration = float(dur_str)
                    except Exception:
                        actual_audio_duration = 0.0

                if actual_audio_duration > 0:
                    logger.info(f'✅ 配音生成完成: {rel_path}，实际时长: {actual_audio_duration:.2f}秒')
                    # 将实际时长保存到全局变量，供后续字幕调整使用
                    if not hasattr(self, '_audio_duration_cache'):
                        self._audio_duration_cache = {}
                    self._audio_duration_cache[task_id] = actual_audio_duration
                else:
                    logger.warning('⚠️ ffprobe 未能读取配音时长，将按脚本文本估算')
            except Exception as e:
                logger.warning(f'⚠️ 无法读取配音时长(ffprobe调用失败): {e}')

            logger.info(f'✅ 配音生成完成: {rel_path}')
            return rel_path

        except Exception as e:
            logger.error(f'❌ 配音生成失败: {e}', exc_info=True)
            return None

    def _sync_all(self, video_path: str, audio_path: str, script: Dict,
                  vision_results: Dict, task_id: str,
                  config: Optional[Dict] = None) -> Optional[Dict]:
        """步骤4: 三同步处理"""
        try:
            if config is None:
                config = {}

            if not self.sync_engine:
                logger.warning('⚠️ 同步引擎不可用')
                return None

            # 在同步前，先根据配音实际时长重新调整字幕时间轴
            actual_audio_duration = getattr(self, '_audio_duration_cache', {}).get(task_id)
            if actual_audio_duration and script and isinstance(script, dict):
                segments = script.get('segments') or []
                if segments:
                    # 计算原始 segments 的总时长
                    original_duration = max(seg.get('end_time', 0) for seg in segments) if segments else 0

                    if original_duration > 0 and abs(actual_audio_duration - original_duration) > 1.0:
                        logger.warning(
                            f'⚠️ 配音实际时长({actual_audio_duration:.2f}s)与原始场景时长({original_duration:.2f}s)'
                            f'差异较大，重新调整字幕时间轴'
                        )

                        # 按比例调整每个 segment 的时间
                        scale = actual_audio_duration / original_duration
                        for seg in segments:
                            try:
                                old_start = float(seg.get('start_time', 0))
                                old_end = float(seg.get('end_time', old_start))
                                seg['start_time'] = old_start * scale
                                seg['end_time'] = old_end * scale
                            except Exception as e:
                                logger.warning(f'⚠️ 调整segment时间失败: {e}')

                        logger.info(f'✅ 已根据配音实际时长重新调整字幕时间轴')

            logger.info('🔄 开始执行三同步...')

            # 提取时间轴优化配置
            sync_options = {}
            timeline_alignment = config.get('timeline_alignment') or config.get('timelineAlignment')
            sync_precision = config.get('sync_precision') or config.get('syncPrecision')
            similarity_calc = config.get('similarity_calc') or config.get('similarityCalc')
            backtrack_strategy = config.get('backtrack_strategy') or config.get('backtrackStrategy')

            if timeline_alignment:
                sync_options['alignment_method'] = timeline_alignment
            if sync_precision:
                sync_options['precision'] = sync_precision
            if similarity_calc:
                sync_options['similarity_metric'] = similarity_calc
            if backtrack_strategy:
                sync_options['path_strategy'] = backtrack_strategy

            if sync_options:
                logger.info(f'⏱️ 时间轴优化配置: {sync_options}')

            # 执行三同步
            sync_results = self.sync_engine.sync_all(
                video_path=video_path,
                audio_path=audio_path,
                script=script,
                vision_analysis=vision_results,
                options=sync_options if sync_options else None
            )

            logger.info(f'✅ 三同步完成，质量评分: {sync_results.get("sync_quality", 0):.2f}')

            return sync_results

        except Exception as e:
            logger.error(f'❌ 三同步失败: {e}')
            return None

    def _subtitle_audio_duration(self, audio_path: Path) -> float:
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(audio_path)],
                capture_output=True, text=True, timeout=15,
            )
            return max(0.0, float(result.stdout.strip())) if result.returncode == 0 else 0.0
        except Exception:
            return 0.0

    def _configured_subtitle_limit(self, config: Dict) -> float:
        for key in ('target_duration_seconds', 'source_duration_seconds'):
            try:
                value = float(config.get(key) or 0)
                if value > 0:
                    return value
            except (TypeError, ValueError):
                continue
        return 0.0

    def _clamp_subtitle_script(self, subtitle_script: Dict[str, Any], maximum: float) -> Optional[Dict[str, Any]]:
        narrations = []
        for narration in subtitle_script.get('narrations', []):
            try:
                start_text, end_text = str(narration.get('time_range', '')).removesuffix('s').split('s-', 1)
                start = max(0.0, min(float(start_text), maximum))
                end = max(start, min(float(end_text), maximum))
            except (AttributeError, TypeError, ValueError):
                continue
            if end > start and str(narration.get('text') or '').strip():
                narrations.append({'time_range': f'{start:.3f}s-{end:.3f}s', 'text': narration['text']})
        return {'narrations': narrations} if narrations else None

    def _estimate_subtitle_script(self, script: Dict, audio_path: Path) -> Optional[Dict[str, Any]]:
        """同步结果缺失时，按成片配音总时长顺序估算字幕，不能替代精确音字同步。"""
        texts = [str(segment.get('text') or '').strip() for segment in (script or {}).get('segments', []) if isinstance(segment, dict)]
        texts = [text for text in texts if text]
        total_duration = self._subtitle_audio_duration(audio_path)
        if not texts or total_duration <= 0:
            return None
        weights = [max(1, len(text)) for text in texts]
        total_weight = sum(weights)
        cursor = 0.0
        narrations = []
        for index, text in enumerate(texts):
            end = total_duration if index == len(texts) - 1 else min(total_duration, cursor + total_duration * weights[index] / total_weight)
            if end > cursor:
                narrations.append({'time_range': f'{cursor:.3f}s-{end:.3f}s', 'text': text})
            cursor = end
        logger.warning('三同步字幕不可用，已按配音总时长顺序估算字幕时间；该时间线不是精确音字同步。')
        return {'narrations': narrations} if narrations else None

    def _compose_final_video(self, video_path: str, audio_path: str, script: Dict,
                            sync_results: Dict, config: Dict, task_id: str) -> Optional[str]:
        """步骤5: 合成最终视频"""
        try:
            logger.info('🎬 开始合成最终视频...')

            base_dir = PROJECT_ROOT
            output_dir = project_output_dir('commentary')

            video_path_obj = Path(video_path)
            if not video_path_obj.is_absolute():
                video_path_obj = base_dir / video_path_obj

            audio_path_obj = Path(audio_path)
            if not audio_path_obj.is_absolute():
                audio_path_obj = base_dir / audio_path_obj

            storyboard_timeline = config.get('_storyboard_timeline') or []
            if storyboard_timeline:
                from backend.engine.puppet_sync_engine import PuppetSyncEngine
                subtitle_path = None
                if bool(config.get('auto_subtitle', True)):
                    narrations = []
                    for item in storyboard_timeline:
                        text = str(item.get('subtitle_text') or '').strip()
                        if text and not item.get('original_audio'):
                            narrations.append({
                                'time_range': f"{float(item['timeline_start']):.3f}s-{float(item['timeline_end']):.3f}s",
                                'text': text,
                            })
                    if narrations:
                        srt_path = output_dir / f"commentary_storyboard_{int(time.time())}_{uuid.uuid4().hex[:6]}.srt"
                        subtitle_path = SubtitleGenerator().generate_srt_from_script({'narrations': narrations}, str(srt_path))
                output_file = output_dir / f"commentary_storyboard_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"
                rendered = PuppetSyncEngine().render_timeline(
                    video_path=str(video_path_obj), timeline=storyboard_timeline, output_path=str(output_file),
                    subtitle_path=subtitle_path,
                )
                logger.info('✅ 已按故事板时间线渲染完整原创解说，不使用开头裁切回退')
                return rendered

            subtitle_path: Optional[str] = None
            auto_subtitle = bool(config.get('auto_subtitle', True))

            if auto_subtitle:
                narration_script: Optional[Dict[str, Any]] = None
                subtitle_segments = None
                try:
                    subtitle_segments = (sync_results or {}).get('audio_text_sync', {}).get('subtitle_segments')
                except Exception:
                    subtitle_segments = None

                if subtitle_segments:
                    narrations = []
                    for seg in subtitle_segments:
                        start = float(seg.get('start', seg.get('start_time', 0.0)))
                        end = float(seg.get('end', seg.get('end_time', start)))
                        text = seg.get('text', '')
                        if str(text).strip() and end > start:
                            narrations.append({'time_range': f"{start:.3f}s-{end:.3f}s", 'text': text})
                    if narrations:
                        narration_script = {'narrations': narrations}
                if not narration_script:
                    narration_script = self._estimate_subtitle_script(script, audio_path_obj)
                subtitle_limit = self._configured_subtitle_limit(config)
                if narration_script and subtitle_limit > 0:
                    narration_script = self._clamp_subtitle_script(narration_script, subtitle_limit)

                if narration_script:
                    try:
                        srt_path = output_dir / f"commentary_{int(time.time())}_{uuid.uuid4().hex[:6]}.srt"
                        generator = SubtitleGenerator()
                        subtitle_path = generator.generate_srt_from_script(narration_script, str(srt_path))
                    except Exception as se:
                        logger.error(f'❌ 生成字幕失败: {se}')
                        subtitle_path = None

            bgm_path: Optional[str] = None
            if config.get('auto_bgm'):
                # 优先使用配置中的BGM路径
                bgm_value = config.get('bgm')
                if bgm_value:
                    bgm_obj = Path(bgm_value)
                    if not bgm_obj.is_absolute():
                        bgm_obj = base_dir / bgm_obj
                    if bgm_obj.exists():
                        bgm_path = str(bgm_obj)
                    else:
                        logger.warning(f'指定的BGM文件不存在: {bgm_obj}')
                else:
                    # 未显式指定BGM时，尝试使用默认背景音乐 backend/assets/audio/default_bgm.mp3
                    default_bgm = AUDIO_DIR / 'default_bgm.mp3'
                    if default_bgm.exists():
                        bgm_path = str(default_bgm)
                        logger.info(f'🎵 自动BGM已启用，使用默认背景音乐: {default_bgm}')
                    else:
                        candidates = []
                        try:
                            for ext in ('.mp3', '.wav', '.m4a', '.flac', '.ogg'):
                                candidates.extend(AUDIO_DIR.glob(f'**/*{ext}'))
                        except Exception as se:
                            logger.warning(f'自动BGM搜索资源失败: {se}')
                            candidates = []

                        if candidates:
                            try:
                                candidates = sorted(candidates, key=lambda p: str(p))
                            except Exception:
                                pass

                            preferred = [p for p in candidates if p.name.lower().startswith(('bgm_', 'default_'))]
                            chosen = preferred[0] if preferred else candidates[0]
                            bgm_path = str(chosen)
                            logger.info(f'🎵 自动BGM已启用，从音频资源目录选择: {chosen}')
                        else:
                            logger.warning(
                                f'自动BGM已启用，但未提供bgm且默认BGM文件不存在，且音频资源目录为空: {AUDIO_DIR}'
                            )

            # 计算目标时长：优先使用前端传入的 target_duration_seconds，并结合源视频时长进行夹紧
            target_duration: Optional[float] = None
            source_duration: Optional[float] = None

            try:
                td_val = config.get('target_duration_seconds')
                if td_val is not None:
                    target_duration = float(td_val)
            except Exception:
                target_duration = None

            try:
                sd_val = config.get('source_duration_seconds')
                if sd_val is not None:
                    source_duration = float(sd_val)
            except Exception:
                source_duration = None

            # 如未显式提供源视频时长，则尝试在后端探测一次
            if source_duration is None or source_duration <= 0:
                try:
                    vp = VideoProcessor()
                    info = vp.get_video_info(str(video_path_obj)) or {}
                    src_dur = float(info.get('duration') or 0.0)
                    if src_dur > 0:
                        source_duration = src_dur
                except Exception as e:
                    logger.warning(f'⚠️ 获取源视频时长失败，将跳过基于源时长的夹紧: {e}')

            max_duration_for_merge: Optional[float] = None
            if target_duration is not None:
                # 基本下限保护
                if target_duration < 1.0:
                    target_duration = 1.0
                # 不超过源视频
                if source_duration and source_duration > 0 and target_duration > source_duration:
                    logger.info(
                        '目标时长 %.2fs 大于源视频时长 %.2fs，已在合成阶段自动夹紧',
                        target_duration,
                        source_duration,
                    )
                    target_duration = source_duration

                max_duration_for_merge = target_duration

            output_file = output_dir / f"commentary_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp4"

            # 读取字幕样式相关配置：样式预设 / 位置 / 字号
            subtitle_style_name = (config.get('subtitle_style')
                                   or config.get('subtitleStyle')
                                   or 'large')
            subtitle_position_conf = config.get('subtitle_position') or config.get('subtitlePosition')
            subtitle_font_size_conf = config.get('subtitle_font_size') or config.get('subtitleFontSize')
            subtitle_font_conf = config.get('subtitle_font') or config.get('subtitleFont')
            subtitle_color_conf = config.get('subtitle_color') or config.get('subtitleColor')
            subtitle_bg_color_conf = config.get('subtitle_bg_color') or config.get('subtitleBgColor')
            subtitle_stroke_color_conf = config.get('subtitle_stroke_color') or config.get('subtitleStrokeColor')
            subtitle_stroke_width_conf = config.get('subtitle_stroke_width') or config.get('subtitleStrokeWidth')

            original_volume_default = config.get('original_audio_volume', 0)
            try:
                keep_original_audio = bool(config.get('keep_original_audio')) if 'keep_original_audio' in config else float(original_volume_default or 0) > 0
            except (TypeError, ValueError):
                keep_original_audio = False
            options: Dict[str, Any] = {
                # 仅当生成了有效的字幕文件且开启了自动字幕时才启用字幕
                'subtitle_enabled': bool(subtitle_path) and Path(subtitle_path).is_file() and Path(subtitle_path).stat().st_size > 0 and bool(config.get('auto_subtitle', True)),
                'keep_original_audio': keep_original_audio,
                # 原创解说默认使用更醒目的“大号字幕”样式，如前端选择则按选择覆盖
                'subtitle_style': subtitle_style_name or 'large',
            }

            # 允许前端覆盖字幕位置
            if subtitle_position_conf:
                options['subtitle_position'] = str(subtitle_position_conf)

            # 允许前端覆盖字幕字体大小（数值合法时生效）
            try:
                if subtitle_font_size_conf is not None:
                    fs_val = int(float(subtitle_font_size_conf))
                    if fs_val > 0:
                        options['subtitle_font_size'] = fs_val
            except Exception:
                pass

            # 高级字幕样式覆盖：字体 / 颜色 / 描边 / 背景
            if subtitle_font_conf:
                try:
                    options['subtitle_font'] = str(subtitle_font_conf)
                except Exception:
                    pass

            if subtitle_color_conf:
                try:
                    options['subtitle_color'] = str(subtitle_color_conf)
                except Exception:
                    pass

            if subtitle_bg_color_conf:
                try:
                    options['subtitle_bg_color'] = str(subtitle_bg_color_conf)
                except Exception:
                    pass

            if subtitle_stroke_color_conf:
                try:
                    options['stroke_color'] = str(subtitle_stroke_color_conf)
                except Exception:
                    pass

            try:
                if subtitle_stroke_width_conf is not None:
                    sw_val = int(float(subtitle_stroke_width_conf))
                    if sw_val >= 0:
                        options['stroke_width'] = sw_val
            except Exception:
                pass

            # 若存在合法目标时长，则传递给合成器在加载后裁剪视频长度
            if max_duration_for_merge is not None and max_duration_for_merge > 0:
                options['max_duration'] = float(max_duration_for_merge)

            # 从 config 中读取音量控制参数
            voice_volume_conf = config.get('voice_volume')
            bgm_volume_conf = config.get('bgm_volume')
            original_volume_conf = config.get('original_audio_volume')

            if voice_volume_conf is not None:
                try:
                    options['voice_volume'] = float(voice_volume_conf)
                except Exception:
                    pass

            if bgm_volume_conf is not None:
                try:
                    options['bgm_volume'] = float(bgm_volume_conf)
                except Exception:
                    pass

            if original_volume_conf is not None:
                try:
                    options['original_audio_volume'] = float(original_volume_conf)
                except Exception:
                    pass

            # 花字音效仅在配置显式开启时混入预览成片。
            flower_config = config.get('flower_config') if isinstance(config.get('flower_config'), dict) else config
            if narration_script and bool(flower_config.get('sound_effects_enabled', flower_config.get('flower_sfx_enabled', False))):
                flower_track = SubtitleGenerator().build_jianying_flower_track(narration_script, flower_config)
                options['flower_sound_effects'] = flower_track.get('flower_sfx') or []
                options['sound_effects_enabled'] = True

            # === 视频输出参数（分辨率、编码、比特率） ===
            video_resolution = config.get('video_resolution') or config.get('videoResolution')
            video_codec = config.get('video_codec') or config.get('videoCodec')
            bitrate_control = config.get('bitrate_control') or config.get('bitrateControl')
            speed_priority = config.get('speed_priority') or config.get('speedPriority')

            if video_resolution:
                options['resolution'] = video_resolution
            if video_codec:
                options['video_codec'] = video_codec
            if bitrate_control:
                options['bitrate'] = bitrate_control
            if speed_priority:
                options['preset'] = speed_priority

            composer = VideoComposer()
            composed_path = composer.merge_materials(
                video_path=str(video_path_obj),
                audio_path=str(audio_path_obj),
                output_path=str(output_file),
                subtitle_path=subtitle_path,
                bgm_path=bgm_path,
                options=options,
            )

            try:
                rel_path = Path(composed_path).resolve().relative_to(base_dir)
                rel_str = str(rel_path).replace('\\', '/')
            except Exception:
                rel_str = str(output_file).replace('\\', '/')

            logger.info(f'✅ 视频合成完成: {rel_str}')

            return rel_str

        except Exception as e:
            logger.error(f'❌ 视频合成失败: {e}')
            return None

    def _simple_video_analysis(self, video_path: str) -> Dict:
        """简化的视频分析（备用方案）

        不再返回与真实视频无关的固定结果，而是基于视频元数据构建粗略的场景信息，
        保证在视觉引擎不可用时仍然能提供与时长相符的分析结构。
        """
        duration = 60.0
        width = None
        height = None

        try:
            vp = VideoProcessor()
            info = vp.get_video_info(video_path) or {}
            duration = float(info.get('duration') or duration)
            if duration <= 0:
                duration = 60.0
            try:
                width = int(info.get('width')) if info.get('width') is not None else None
                height = int(info.get('height')) if info.get('height') is not None else None
            except Exception:
                width = height = None
        except Exception as e:
            logger.warning(f'⚠️ 简化视频分析获取元数据失败，将使用默认时长: {e}')

        # 按时长平均分段，生成基础场景
        duration = max(1.0, duration)
        segment_count = max(1, min(6, int(duration // 10) or 1))
        seg_dur = duration / segment_count

        scenes = []
        descriptions = []
        for i in range(segment_count):
            start = i * seg_dur
            end = duration if i == segment_count - 1 else (i + 1) * seg_dur
            scenes.append({
                'id': i,
                'start_time': float(start),
                'end_time': float(end),
                'duration': float(end - start)
            })
            descriptions.append({
                'timestamp': float((start + end) / 2.0),
                'description': f'第{i+1}段画面'
            })

        summary = '原创解说视频'
        if scenes:
            summary = f"约 {int(duration)} 秒的原创解说视频，大致划分为 {len(scenes)} 个场景。"

        result: Dict[str, Any] = {
            'scenes': scenes,
            'keyframes': [],
            'descriptions': descriptions,
            'emotions': [],
            'summary': summary,
            'duration': duration
        }
        if width and height:
            result['resolution'] = f'{width}x{height}'

        return result

    def _template_script(self, vision_results: Dict) -> Dict:
        """规则文案（备用方案）

        当 ScriptGenerator 不可用时，根据视频分析结果动态生成一个结构化的解说文案，
        输出结构与主流程保持一致：包含 opening / segments / closing 字段，
        且每个片段的起止时间与场景时长匹配。
        """
        # 推断总时长
        duration = 0.0
        try:
            if 'duration' in vision_results:
                duration = float(vision_results.get('duration') or 0.0)
        except Exception:
            duration = 0.0

        scenes = vision_results.get('scenes') or []
        if not scenes and duration <= 0:
            # 如果没有场景信息与时长，则退回到一个约30秒的视频假设
            duration = 30.0
            segment_count = 3
            seg_dur = duration / segment_count
            scenes = []
            for i in range(segment_count):
                start = i * seg_dur
                end = duration if i == segment_count - 1 else (i + 1) * seg_dur
                scenes.append({
                    'id': i,
                    'start_time': float(start),
                    'end_time': float(end),
                    'duration': float(end - start)
                })
        elif not scenes:
            # 只有时长，按时长均分生成场景
            duration = max(duration, 1.0)
            segment_count = max(3, min(6, int(duration // 6) or 3))
            seg_dur = duration / segment_count
            scenes = []
            for i in range(segment_count):
                start = i * seg_dur
                end = duration if i == segment_count - 1 else (i + 1) * seg_dur
                scenes.append({
                    'id': i,
                    'start_time': float(start),
                    'end_time': float(end),
                    'duration': float(end - start)
                })

        # 如果时长仍未知，则根据最后一个场景推断
        if duration <= 0 and scenes:
            try:
                duration = float(scenes[-1].get('end_time') or 0.0)
            except Exception:
                duration = 0.0

        # 基于场景构造 segments
        segments = []
        for idx, scene in enumerate(scenes):
            try:
                start = float(scene.get('start_time', 0.0))
                end = float(scene.get('end_time', start))
            except Exception:
                start, end = 0.0, 0.0
            text = f"第{idx+1}段：这里展示的是视频的精彩画面片段，创作者可以在此处补充更具体的讲解内容。"
            segments.append({
                'scene_id': scene.get('id', idx),
                'start_time': start,
                'end_time': end,
                'text': text,
                'emotion': 'neutral'
            })

        summary = vision_results.get('summary') or '原创解说视频'
        opening = f"欢迎观看本期原创解说视频。{summary}"
        closing = "本期解说就到这里，感谢您的观看，我们下期再见。"

        return {
            'title': '原创解说文稿',
            'opening': opening,
            'segments': segments,
            'closing': closing
        }

    def _register_project_artifacts(self, project_id: str, video_path: str,
                                     audio_path: str, sync_results: Dict,
                                     output_path: str, config: Dict) -> None:
        """将原创解说的原视频、配音、字幕、成片登记为素材，并写入统一 tracks。

        统一 tracks schema：
          tracks: [
            { id, type: 'video'|'audio'|'subtitle', clips: [ {id, name, path, start, duration} ] }
          ]
        """
        import uuid as _uuid

        def _abs(p: str) -> str:
            if not p:
                return ''
            po = Path(p)
            if not po.is_absolute():
                po = PROJECT_ROOT / p
            return str(po)

        def _file_size(p: str) -> int:
            try:
                ap = Path(_abs(p))
                return ap.stat().st_size if ap.exists() else 0
            except Exception:
                return 0

        def _probe_duration(p: str) -> float:
            try:
                vp = VideoProcessor()
                info = vp.get_video_info(_abs(p)) or {}
                return float(info.get('duration') or 0)
            except Exception:
                return 0.0

        # 1) 登记素材（去重，避免重复登记同名素材）
        existing = self.db_manager.get_materials(project_id) or []
        existing_paths = {str(m.get('path', '')) for m in existing}

        artifacts = [
            ('video', '原始视频', video_path),
            ('audio', '解说配音', audio_path),
            ('video', '解说成片', output_path),
        ]
        for mtype, mname, mpath in artifacts:
            if not mpath:
                continue
            ap = _abs(mpath)
            if ap in existing_paths:
                continue
            try:
                self.db_manager.create_material(
                    project_id=project_id,
                    material_type=mtype,
                    name=mname,
                    path=ap,
                    size=_file_size(ap),
                    duration=_probe_duration(ap),
                    metadata={'source': 'commentary'}
                )
            except Exception as e:
                logger.warning(f'⚠️ 登记素材失败 {mname}: {e}')

        # 2) 构建统一 tracks
        project = self.db_manager.get_project(project_id) or {}
        raw_config = project.get('config')
        if isinstance(raw_config, str):
            try:
                project_config = json.loads(raw_config) if raw_config else {}
            except Exception:
                project_config = {}
        elif isinstance(raw_config, dict):
            project_config = raw_config
        else:
            project_config = {}

        tracks = list(project_config.get('tracks') or [])

        def _ensure_track(tid: str, ttype: str) -> Dict:
            for item in tracks:
                if item.get('id') == tid and item.get('type') == ttype:
                    return item
            new_track = {'id': tid, 'type': ttype, 'clips': []}
            tracks.append(new_track)
            return new_track

        video_track = _ensure_track('video-track-1', 'video')
        audio_track = _ensure_track('audio-track-1', 'audio')
        subtitle_track = _ensure_track('text-track-1', 'subtitle')

        # 视频轨：成片
        vclips = list(video_track.get('clips') or [])
        out_dur = _probe_duration(output_path)
        vclips.append({
            'id': f"clip-{_uuid.uuid4().hex[:8]}",
            'name': Path(output_path).name if output_path else 'commentary_output',
            'path': _abs(output_path),
            'start': 0.0,
            'duration': out_dur,
        })
        video_track['clips'] = vclips

        # 音频轨：配音
        aclips = list(audio_track.get('clips') or [])
        audio_dur = _probe_duration(audio_path)
        aclips.append({
            'id': f"clip-{_uuid.uuid4().hex[:8]}",
            'name': Path(audio_path).name if audio_path else 'commentary_audio',
            'path': _abs(audio_path),
            'start': 0.0,
            'duration': audio_dur,
        })
        audio_track['clips'] = aclips

        # 字幕轨：segments
        sclips = list(subtitle_track.get('clips') or [])
        script = (sync_results or {}).get('script') or {}
        segments = script.get('segments') or []
        for seg in segments:
            try:
                start = float(seg.get('start_time', 0))
                end = float(seg.get('end_time', start))
                text = seg.get('text', '')
            except Exception:
                continue
            if not text:
                continue
            sclips.append({
                'id': f"clip-{_uuid.uuid4().hex[:8]}",
                'name': text[:20],
                'text': text,
                'start': start,
                'duration': max(0.1, end - start),
            })
        subtitle_track['clips'] = sclips

        project_config['tracks'] = tracks
        self.db_manager.update_project(project_id, {'config': project_config})

    def _emit_progress(self, task_id: str, progress: int, message: str):
        """发送进度更新"""
        try:
            if self.socketio:
                self.socketio.emit('task_progress', {
                    'task_id': task_id,
                    'progress': progress,
                    'message': message
                })

            # 更新任务进度（数据库）
            try:
                self.db_manager.update_task_progress(task_id, progress)
            except Exception:
                pass

            logger.info(f'📊 进度: {progress}% - {message}')

        except Exception as e:
            logger.error(f'❌ 发送进度失败: {e}')

    def get_project_result(self, project_id: str) -> Dict:
        """获取项目结果"""
        try:
            project = self.db_manager.get_project(project_id)

            if not project:
                return {'code': 1, 'msg': '项目不存在', 'data': None}

            raw_result = project.get('result')
            result: Dict[str, Any]
            if isinstance(raw_result, str):
                try:
                    result = json.loads(raw_result) or {}
                except Exception:
                    result = {}
            elif isinstance(raw_result, dict):
                result = raw_result
            else:
                result = {}

            return {
                'code': 0,
                'msg': '获取成功',
                'data': {
                    'project': project,
                    'result': result
                }
            }

        except Exception as e:
            logger.error(f'❌ 获取结果失败: {e}')
            return {'code': 1, 'msg': f'获取失败: {str(e)}', 'data': None}
