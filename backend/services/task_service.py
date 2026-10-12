# -*- coding: utf-8 -*-
"""
Task Service
任务处理服务 - 负责所有异步任务的处理
集成所有处理引擎，提供完整的任务处理能力
"""

import logging
import math
import time
import uuid
import json
import threading
import subprocess
from typing import Dict, List, Optional
from pathlib import Path

# 导入所有处理引擎
from backend.engine import (
    VideoProcessor,
    AudioProcessor,
    TTSEngine,
    ASREngine,
    SceneDetector
)
from backend.engine.beat_remix_engine import get_beat_remix_engine
from backend.config.paths import AUDIO_DIR

logger = logging.getLogger(__name__)


class TaskService:
    """任务处理服务"""

    def __init__(self, db_manager, socketio):
        """
        初始化任务服务

        Args:
            db_manager: 数据库管理器实例
            socketio: SocketIO实例
        """
        self.db_manager = db_manager
        self.socketio = socketio
        self.base_dir = Path(__file__).parent.parent.parent

        # 初始化所有处理引擎
        self.video_processor = VideoProcessor()
        self.audio_processor = AudioProcessor()
        self.tts_engine = TTSEngine()
        self.asr_engine = ASREngine()
        self.scene_detector = SceneDetector()

        logger.info('✅ TaskService初始化完成，所有引擎已加载')

    def _emit_progress(self, task_id: str, progress: int, step: str, detail: str = None):
        """
        发送详细进度更新到前端

        Args:
            task_id: 任务ID
            progress: 进度值 (0-100)
            step: 当前步骤名称
            detail: 详细描述
        """
        try:
            self.db_manager.update_task_progress(task_id, progress)
            self.socketio.emit('task_progress', {
                'task_id': task_id,
                'progress': progress,
                'step': step,
                'detail': detail or '',
                'timestamp': time.time()
            })
        except Exception as e:
            logger.debug(f'进度推送失败 (任务 {task_id}): {e}')

    def process_task(self, task_id: str, task_type: str, input_data: Dict):
        """
        通用任务处理

        Args:
            task_id: 任务ID
            task_type: 任务类型
            input_data: 输入数据
        """
        try:
            normalized_type = (task_type or '').strip().lower()

            # 统一标记运行中状态（具体处理函数内部会继续更新进度/状态）
            self.db_manager.update_task_status(task_id, 'running')
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'running',
                    'progress': 0
                })
            except Exception:
                pass

            # 根据任务类型分发到具体实现
            if normalized_type == 'video_cut':
                self.process_video_cut(task_id, input_data or {})
            elif normalized_type == 'video_merge':
                self.process_video_merge(task_id, input_data or {})
            elif normalized_type == 'tts':
                self.process_tts(task_id, input_data or {})
            elif normalized_type == 'asr':
                self.process_asr(task_id, input_data or {})
            elif normalized_type == 'scene_detect':
                self.process_scene_detect(task_id, input_data or {})
            elif normalized_type == 'remix':
                # 兼容通过通用接口触发的混剪任务
                payload = {
                    'project_id': (input_data or {}).get('project_id'),
                    'plan': (input_data or {}).get('plan') or {}
                }
                self._run_remix_task(task_id, payload)
            else:
                # 未知任务类型：直接标记失败，避免虚假成功
                msg = f'不支持的任务类型: {task_type}'
                logger.error(msg)
                self.db_manager.update_task_status(task_id, 'failed', error_message=msg)
                try:
                    self.socketio.emit('task_status', {
                        'task_id': task_id,
                        'status': 'failed',
                        'error': msg
                    })
                except Exception:
                    pass
                return

        except Exception as e:
            logger.error(f'任务处理失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {
                'task_id': task_id,
                'status': 'failed',
                'error': str(e)
            })

    def process_video_cut(self, task_id: str, data: Dict):
        """
        处理视频剪切任务

        Args:
            task_id: 任务ID
            data: 输入数据（包含video_path, start_time, end_time）
        """
        try:
            self.db_manager.update_task_status(task_id, 'running')
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'running'})

            # 实际调用视频剪辑器
            from backend.engine.video_clipper import VideoClipper

            logger.info(f'开始处理视频剪切任务: {task_id}')
            logger.info(f'输入参数: {data}')

            clipper = VideoClipper()
            start_sec = float(data.get('start_time'))
            end_sec = float(data.get('end_time'))

            def _fmt(sec: float) -> str:
                total = float(sec)
                total_ms = int(total * 1000 + 0.5)
                total_secs, ms = divmod(total_ms, 1000)
                h = total_secs // 3600
                m = (total_secs % 3600) // 60
                s = total_secs % 60
                return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"

            out_path = Path(f"temp/outputs/{task_id}.mp4")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            clipper.clip_video_by_timestamp(
                input_video=data.get('video_path'),
                output_video=str(out_path),
                start_time=_fmt(start_sec),
                end_time=_fmt(end_sec)
            )
            output_path = str(out_path)

            self.db_manager.update_task_status(task_id, 'completed', output_data={'output_path': output_path})
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})
            logger.info(f'✅ 视频剪切完成: {output_path}')

        except Exception as e:
            logger.error(f'❌ 视频剪切失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

    def create_remix_task(self, project_id: str, plan: Dict) -> str:
        """创建混剪任务

        Args:
            project_id: 项目ID
            plan: 混剪方案/配置

        Returns:
            任务ID
        """
        task_id = str(uuid.uuid4())
        input_data: Dict = {
            'project_id': project_id,
            'plan': plan or {}
        }

        # 写入任务记录
        self.db_manager.create_task(
            task_id=task_id,
            task_type='remix',
            project_id=project_id,
            input_data=input_data
        )
        from backend.services.checkpoint_service import get_checkpoint_service
        checkpoint_service = get_checkpoint_service()
        checkpoint_service.create_checkpoint(task_id, project_id, 'remix')
        checkpoint_service.update_checkpoint(
            task_id, stage='upload', stage_progress=100,
            stage_data={'video_paths': list((plan or {}).get('video_paths') or [])}, status='running'
        )
        checkpoint_service.mark_stage_completed(task_id, 'upload')

        # 启动后台线程执行
        threading.Thread(
            target=self._run_remix_task,
            args=(task_id, input_data),
            daemon=True
        ).start()

        logger.info(f'✅ 混剪任务创建完成: {task_id}')
        return task_id

    def _run_remix_task(self, task_id: str, input_data: Dict):
        """执行混剪任务的实际处理逻辑（基础版）"""
        try:
            # 标记任务运行中，发送详细进度
            self.db_manager.update_task_status(task_id, 'running')
            self._emit_progress(task_id, 5, '准备阶段', '初始化混剪任务...')

            plan: Dict = (input_data or {}).get('plan') or {}
            project_id: str = (input_data or {}).get('project_id') or ''
            from backend.services.checkpoint_service import get_checkpoint_service
            checkpoint_service = get_checkpoint_service()
            try:
                target_duration = float(plan.get('target_duration_seconds', plan.get('target_duration')))
            except (TypeError, ValueError):
                raise RuntimeError('必须显式提供 target_duration_seconds')
            if not math.isfinite(target_duration) or target_duration <= 0:
                raise RuntimeError('target_duration_seconds 必须为大于 0 的有限数值')
            duration_mode = plan.get('duration_mode')
            mode = (plan.get('mode') or plan.get('remix_mode') or 'general').lower()
            auto_bgm = bool(plan.get('auto_bgm', True))
            # 自动高光策略：默认 general 模式启用，music 模式默认关闭。
            # 显式 auto_highlight 优先，避免与用户意图冲突。
            auto_highlight = bool(plan.get('auto_highlight', mode != 'music'))
            editing_mode = 'basic_merge'  # 默认标记为基础合并，仅在真实高光/卡点成功时改写
            auto_highlight_used = False
            beat_remix_used = False
            beat_remix_failure: str = ''

            def _resolve_bgm_path():
                explicit = plan.get('bgm_file') or plan.get('music_path')
                if explicit:
                    return str(explicit)
                if not auto_bgm:
                    return None

                default_bgm = AUDIO_DIR / 'default_bgm.mp3'
                if default_bgm.exists():
                    return str(default_bgm)

                candidates = []
                try:
                    for ext in ('.mp3', '.wav', '.m4a', '.flac', '.ogg'):
                        candidates.extend(AUDIO_DIR.glob(f'**/*{ext}'))
                except Exception:
                    candidates = []

                if not candidates:
                    return None

                try:
                    candidates_sorted = sorted(candidates, key=lambda p: str(p))
                except Exception:
                    candidates_sorted = candidates

                preferred = [p for p in candidates_sorted if p.name.lower().startswith(('bgm_', 'default_'))]
                chosen = preferred[0] if preferred else candidates_sorted[0]
                return str(chosen)

            # 源视频路径列表
            video_paths = plan.get('video_paths') or []
            abs_video_paths = []
            for p in video_paths:
                try:
                    path_obj = Path(p)
                    if not path_obj.is_absolute():
                        path_obj = self.base_dir / p
                    if path_obj.exists():
                        abs_video_paths.append(str(path_obj))
                except Exception:
                    continue

            if not abs_video_paths:
                raise RuntimeError('没有可用的视频素材')
            checkpoint_service.mark_stage_completed(
                task_id, 'segment', {'video_count': len(abs_video_paths), 'mode': mode}
            )
            checkpoint_service.update_checkpoint(task_id, stage='clip_plan', stage_progress=25)

            output_dir = self.base_dir / 'output' / 'remix'
            output_dir.mkdir(parents=True, exist_ok=True)

            final_path = None
            used_beat_remix = False
            timeline: List[Dict] = []
            timeline_cursor = 0.0

            def record_timeline(source_path, source_start, source_end, text='',
                                output_duration=None, output_start=None, beat_index=None):
                nonlocal timeline_cursor
                source_duration = max(0.0, float(source_end) - float(source_start))
                render_duration = source_duration if output_duration is None else float(output_duration)
                if not source_path or source_duration <= 0 or render_duration <= 0:
                    return
                start = timeline_cursor if output_start is None else float(output_start)
                entry = {
                    'id': f'clip-{len(timeline)}',
                    'source_video': str(source_path),
                    'source_start': float(source_start),
                    'source_end': float(source_end),
                    'start': start,
                    'end': start + render_duration,
                    'duration': render_duration,
                    'subtitle_text': str(text or ''),
                }
                if beat_index is not None:
                    entry['beat_index'] = int(beat_index)
                timeline.append(entry)
                timeline_cursor = max(timeline_cursor, entry['end'])

            def _add_bgm_exact(video_path, audio_path, output_path):
                """循环或裁切 BGM，使其精确覆盖视频，且必须产出音轨。"""
                video_info = self.video_processor.get_video_info(str(video_path)) or {}
                video_duration = float(video_info.get('duration') or 0)
                if video_duration <= 0:
                    raise RuntimeError('无法读取待配乐视频时长')
                cmd = [
                    'ffmpeg', '-y', '-i', str(video_path), '-stream_loop', '-1', '-i', str(audio_path),
                    '-filter_complex', f'[1:a]atrim=duration={video_duration:.6f},asetpts=N/SR/TB[a]',
                    '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac',
                    '-t', f'{video_duration:.6f}', '-movflags', '+faststart', str(output_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if result.returncode != 0 or not Path(output_path).exists():
                    raise RuntimeError('BGM 精确覆盖失败: %s' % result.stderr[-400:])
                output_info = self.video_processor.get_video_info(str(output_path)) or {}
                if not output_info.get('has_audio'):
                    raise RuntimeError('BGM 叠加后成片没有音频流')
                if abs(float(output_info.get('duration') or 0) - video_duration) > 0.08:
                    raise RuntimeError('BGM 叠加改变了视频时长')
                return True

            # 已应用的去重方案在片段渲染阶段注入 FFmpeg 滤镜，避免仅停留在界面预览。
            dedup_plans = [item for item in (plan.get('dedup_plans') or []) if isinstance(item, dict)]
            dedup_by_range = {
                (round(float(item.get('start_time', item.get('start', 0))), 3),
                 round(float(item.get('end_time', item.get('end', 0))), 3)): item
                for item in dedup_plans if item.get('has_transform', True) and item.get('ffmpeg_filter')
            }

            # 音乐卡点模式：优先尝试使用 BeatRemixEngine 进行智能卡点剪辑
            if mode == 'music':
                try:
                    bgm_path = _resolve_bgm_path()
                    if bgm_path:
                        bgm_obj = Path(bgm_path)
                        if not bgm_obj.is_absolute():
                            bgm_obj = self.base_dir / bgm_path
                        if bgm_obj.exists():
                            engine = get_beat_remix_engine()
                            if getattr(engine, 'librosa_available', False) and getattr(engine, 'cv2_available', False):
                                self._emit_progress(task_id, 20, '卡点分析', '正在分析音乐节拍...')
                                logger.info(f'🎵 混剪任务 {task_id}: 使用 BeatRemixEngine 进行音乐卡点剪辑')

                                beat_target_duration = target_duration

                                beat_result = engine.create_beat_remix(
                                    video_clips=abs_video_paths,
                                    music_path=str(bgm_obj),
                                    style=plan.get('style') or 'dynamic',
                                    target_duration=beat_target_duration,
                                    beat_detection=plan.get('beat_detection'),
                                    beat_sensitivity=plan.get('beat_sensitivity'),
                                    fast_keyframe=plan.get('fast_keyframe') or plan.get('fastKeyframe'),
                                    slow_keyframe=plan.get('slow_keyframe') or plan.get('slowKeyframe'),
                                    speed_curve=plan.get('speed_curve') or plan.get('speedCurve'),
                                    beat_transition=plan.get('beat_transition') or plan.get('beatTransition'),
                                    rhythm_match=plan.get('rhythm_match') or plan.get('rhythmMatch'),
                                    sync_precision=plan.get('sync_precision') or plan.get('syncPrecision')
                                )

                                beat_matches = beat_result.get('beat_matches') or []
                                if beat_matches:
                                    segments_dir = self.base_dir / 'temp' / 'remix_segments' / task_id
                                    segments_dir.mkdir(parents=True, exist_ok=True)

                                    segment_paths = []
                                    segment_durations = []
                                    total_segments = len(beat_matches)
                                    self._emit_progress(task_id, 25, '片段裁剪', f'正在裁剪 {total_segments} 个卡点片段...')
                                    for idx, match in enumerate(beat_matches):
                                        clip_path = match.get('clip_path')
                                        output_duration = float(match.get('output_duration', match.get('duration')) or 0)
                                        playback_speed = float(match.get('playback_speed', match.get('speed_factor', 1.0)) or 1.0)
                                        start_sec = float(match.get('source_start', match.get('clip_start', 0.0)) or 0.0)
                                        end_sec = float(match.get('source_end', match.get('clip_end', 0.0)) or 0.0)
                                        beat_start = float(match.get('start_time') or 0.0)
                                        beat_end = float(match.get('end_time') or 0.0)
                                        if (not clip_path or output_duration <= 0 or end_sec <= start_sec or
                                                abs((beat_end - beat_start) - output_duration) > 0.001 or
                                                abs((end_sec - start_sec) - output_duration * playback_speed) > 0.001):
                                            raise RuntimeError('卡点匹配数据不满足固定输出时长契约')

                                        seg_out = segments_dir / f"{task_id}_seg_{idx:03d}.mp4"
                                        if playback_speed != 1.0:
                                            ok_seg = self.video_processor.cut_video_with_speed(
                                                clip_path, str(seg_out), start_sec, end_sec, playback_speed
                                            )
                                        else:
                                            ok_seg = self.video_processor.cut_video(
                                                clip_path, str(seg_out), start_sec, end_sec
                                            )
                                        if not ok_seg or not seg_out.exists():
                                            raise RuntimeError('第 %s 个卡点片段裁切失败' % idx)
                                        rendered_info = self.video_processor.get_video_info(str(seg_out)) or {}
                                        rendered_duration = float(rendered_info.get('duration') or 0)
                                        if abs(rendered_duration - output_duration) > 0.08:
                                            raise RuntimeError(
                                                '第 %s 个卡点片段时长不符：实测 %.3fs，应为 %.3fs' %
                                                (idx, rendered_duration, output_duration)
                                            )
                                        segment_paths.append(str(seg_out))
                                        segment_durations.append(output_duration)
                                        record_timeline(
                                            clip_path, start_sec, end_sec, output_duration=output_duration,
                                            output_start=beat_start, beat_index=match.get('beat_index', idx)
                                        )

                                    if not segment_paths or len(segment_paths) != len(beat_matches):
                                        raise RuntimeError('未完整渲染全部卡点片段')
                                    merged_path = output_dir / f'{task_id}_beat_merged.mp4'
                                    self._emit_progress(task_id, 60, '片段合并', '正在合并卡点片段...')
                                    if len(segment_paths) >= 2:
                                        # 音乐卡点必须硬切；任何重叠转场都会破坏 beat 边界。
                                        merged_ok = self.video_processor.merge_videos_with_transitions(
                                            segment_paths, str(merged_path), transition='cut',
                                            durations=segment_durations
                                        )
                                    else:
                                        merged_ok = self.video_processor.convert_video(segment_paths[0], str(merged_path))
                                    if not merged_ok or not merged_path.exists():
                                        raise RuntimeError('卡点片段硬切合并失败')
                                    merged_info = self.video_processor.get_video_info(str(merged_path)) or {}
                                    if abs(float(merged_info.get('duration') or 0) - target_duration) > 0.35:
                                        raise RuntimeError('卡点硬切合并后时长未覆盖目标')

                                    music_out = output_dir / f'{task_id}_beat_with_bgm.mp4'
                                    self._emit_progress(task_id, 80, '添加BGM', '正在添加背景音乐...')
                                    _add_bgm_exact(str(merged_path), str(bgm_obj), str(music_out))
                                    final_path = music_out
                                    used_beat_remix = True
                                    beat_remix_used = True
                                    editing_mode = 'beat_remix'
                except Exception as e:
                    beat_remix_failure = str(e)
                    logger.error(f'音乐卡点智能剪辑失败: {e}', exc_info=True)
                    raise RuntimeError(
                        '音乐卡点混剪失败，未回退为普通混剪伪装完成: %s' % beat_remix_failure
                    )

            # 音乐卡点模式必须真实完成卡点剪辑，不能回退为普通合并。
            if mode == 'music' and not used_beat_remix:
                raise RuntimeError('音乐卡点混剪未生成有效卡点时间轴，未回退为普通混剪伪装完成')

            # 如未能使用 BeatRemixEngine，则回退到基于精彩片段/整段合并的普通混剪逻辑
            if not used_beat_remix:
                clips = (plan.get('clips') or []) if isinstance(plan, dict) else []
                merged_path = None
                merge_source_path = None

                # 1）优先根据精彩片段方案进行剪辑+合并
                if clips:
                    # 普通混剪先严格规划，绝不在渲染完成后才发现素材时长不达标。
                    planned_clips = []
                    remaining = target_duration
                    for raw_clip in clips:
                        if not isinstance(raw_clip, dict):
                            raise RuntimeError('clips 包含无效片段配置')
                        clip = dict(raw_clip)
                        clip_src = clip.get('video_path') or ''
                        if not clip_src:
                            raise RuntimeError('精彩片段缺少 video_path')
                        clip_path = Path(clip_src)
                        if not clip_path.is_absolute():
                            clip_path = self.base_dir / clip_src
                        if not clip_path.exists():
                            matched = next((Path(full) for full in abs_video_paths
                                            if Path(full).name == Path(clip_src).name), None)
                            if not matched:
                                raise RuntimeError('精彩片段源文件不存在: %s' % clip_src)
                            clip_path = matched
                        start_sec = float(clip.get('start_time') or clip.get('start') or 0.0)
                        end_sec = float(clip.get('end_time') or clip.get('end') or 0.0)
                        if end_sec <= start_sec:
                            raise RuntimeError('精彩片段时间范围无效: %s' % clip_src)
                        source_info = self.video_processor.get_video_info(str(clip_path)) or {}
                        if end_sec > float(source_info.get('duration') or 0) + 0.08:
                            raise RuntimeError('精彩片段超出源视频范围: %s' % clip_src)
                        if remaining <= 0:
                            break
                        use_end = min(end_sec, start_sec + remaining)
                        clip['video_path'] = str(clip_path)
                        clip['start_time'] = start_sec
                        clip['end_time'] = use_end
                        planned_clips.append(clip)
                        remaining -= use_end - start_sec
                    if remaining > 0.08:
                        raise RuntimeError('精彩片段总时长不足目标时长，拒绝重复、变速或定格补足')

                    segments_dir = self.base_dir / 'temp' / 'remix_clips' / task_id
                    segments_dir.mkdir(parents=True, exist_ok=True)
                    segment_paths = []
                    segment_durations = []

                    for idx, clip in enumerate(planned_clips):
                        try:
                            clip_src = clip.get('video_path') or ''
                            if not clip_src:
                                raise RuntimeError('精彩片段缺少 video_path')
                            clip_path = Path(clip_src)
                            if not clip_path.is_absolute():
                                clip_path = self.base_dir / clip_src
                            if not clip_path.exists():
                                # 尝试根据文件名在 abs_video_paths 中匹配
                                for full in abs_video_paths:
                                    try:
                                        if Path(full).name == Path(clip_src).name:
                                            clip_path = Path(full)
                                            break
                                    except Exception:
                                        continue
                                else:
                                    raise RuntimeError('精彩片段源文件不存在: %s' % clip_src)

                            start_sec = float(clip.get('start_time') or clip.get('start') or 0.0)
                            end_sec = float(clip.get('end_time') or clip.get('end') or 0.0)
                            if end_sec <= start_sec:
                                raise RuntimeError('精彩片段时间范围无效: %s' % clip_src)
                            duration = end_sec - start_sec

                            seg_out = segments_dir / f"{task_id}_clip_{idx:03d}.mp4"
                            dedup_plan = dedup_by_range.get((round(start_sec, 3), round(end_sec, 3)))
                            if dedup_plan:
                                command = [
                                    'ffmpeg', '-y', '-ss', str(start_sec), '-to', str(end_sec),
                                    '-i', str(clip_path), '-vf', str(dedup_plan['ffmpeg_filter']),
                                    '-c:v', 'libx264', '-c:a', 'aac', str(seg_out)
                                ]
                                transformed = subprocess.run(command, capture_output=True, text=True, timeout=600)
                                ok_seg = transformed.returncode == 0 and seg_out.exists()
                                if not ok_seg:
                                    logger.warning('去重变换渲染失败，已回退原始裁剪: %s', transformed.stderr[-300:])
                                    ok_seg = self.video_processor.cut_video(
                                        input_path=str(clip_path), output_path=str(seg_out),
                                        start_time=start_sec, end_time=end_sec
                                    )
                            else:
                                ok_seg = self.video_processor.cut_video(
                                    input_path=str(clip_path),
                                    output_path=str(seg_out),
                                    start_time=start_sec,
                                    end_time=end_sec
                                )
                            if not ok_seg or not seg_out.exists():
                                raise RuntimeError('生成第 %s 个精彩片段失败' % idx)
                            rendered_info = self.video_processor.get_video_info(str(seg_out)) or {}
                            rendered_duration = float(rendered_info.get('duration') or 0)
                            if abs(rendered_duration - duration) > 0.08:
                                raise RuntimeError('第 %s 个精彩片段时长不符' % idx)
                            segment_paths.append(str(seg_out))
                            segment_durations.append(duration)
                            record_timeline(clip_path, start_sec, end_sec, clip.get('description', ''))
                        except Exception as ce:
                            raise RuntimeError('生成精彩片段失败: %s' % ce) from ce

                    if len(segment_paths) != len(planned_clips):
                        raise RuntimeError('精彩片段未完整渲染')
                    if segment_paths:
                        merged_path = output_dir / f'{task_id}_clips_merged.mp4'
                        # 稍微提前一些进度，表示已完成片段裁剪
                        self._emit_progress(task_id, 30, '片段裁剪完成', f'已裁剪 {len(segment_paths)} 个片段')
                        if len(segment_paths) >= 2:
                            # 目标时长规划后的普通片段同样不能使用重叠转场，否则会缩短成片。
                            merged_ok = self.video_processor.merge_videos_with_transitions(
                                segment_paths, str(merged_path), transition='cut', durations=segment_durations
                            )
                        else:
                            logger.info(f'🎬 混剪任务 {task_id}: 仅1个精彩片段，执行转码')
                            merged_ok = self.video_processor.convert_video(segment_paths[0], str(merged_path))

                        if not merged_ok:
                            raise RuntimeError('精彩片段合并失败')

                        self._emit_progress(task_id, 60, '片段合并', '正在合并视频片段...')
                        merge_source_path = merged_path
                        final_path = merged_path
                        editing_mode = 'highlight_clips'
                        auto_highlight_used = True
                    else:
                        # 严格模式：用户请求自动高光但所有片段裁剪均失败时，
                        # 必须明确失败，不得静默回退到整段合并冒充智能混剪。
                        if auto_highlight:
                            raise RuntimeError(
                                '自动高光模式下所有精彩片段裁剪均失败，已停止混剪而非回退到整段合并'
                            )
                        logger.warning(f'混剪任务 {task_id}: 未生成有效精彩片段，将回退到整段合并逻辑')

                # 2）如未生成 clips 或失败，则使用整段合并逻辑
                if merged_path is None:
                    # 严格模式：用户请求自动高光但没有任何 clips 可用时，
                    # 不允许整段合并冒充智能混剪。
                    if auto_highlight:
                        raise RuntimeError(
                            '自动高光模式下未提供任何精彩片段，已停止混剪而非回退到整段合并'
                        )
                    merged_path = output_dir / f'{task_id}_merged.mp4'

                    # 整段合并也必须先按目标时长规划和裁切，不能把超长或不足推迟到最终检查。
                    source_plan = []
                    remaining = target_duration
                    for source_path in abs_video_paths:
                        source_info = self.video_processor.get_video_info(source_path) or {}
                        source_duration = float(source_info.get('duration') or 0)
                        if source_duration <= 0:
                            raise RuntimeError('无法读取源视频时长: %s' % source_path)
                        if remaining <= 0:
                            break
                        use_duration = min(source_duration, remaining)
                        source_plan.append((source_path, use_duration))
                        remaining -= use_duration
                    if remaining > 0.08:
                        raise RuntimeError('整段素材总时长不足目标时长，拒绝重复、变速或定格补足')

                    segments_dir = self.base_dir / 'temp' / 'remix_full_segments' / task_id
                    segments_dir.mkdir(parents=True, exist_ok=True)
                    planned_paths = []
                    for idx, (source_path, use_duration) in enumerate(source_plan):
                        segment_path = segments_dir / f'{task_id}_full_{idx:03d}.mp4'
                        if not self.video_processor.cut_video(source_path, str(segment_path), 0.0, use_duration):
                            raise RuntimeError('整段素材裁切失败: %s' % source_path)
                        segment_info = self.video_processor.get_video_info(str(segment_path)) or {}
                        if abs(float(segment_info.get('duration') or 0) - use_duration) > 0.08:
                            raise RuntimeError('整段素材裁切时长不符: %s' % source_path)
                        planned_paths.append(str(segment_path))
                        record_timeline(source_path, 0.0, use_duration)
                    if len(planned_paths) == 1:
                        merged_ok = self.video_processor.convert_video(planned_paths[0], str(merged_path))
                    else:
                        merged_ok = self.video_processor.merge_videos(planned_paths, str(merged_path))
                    if not merged_ok or not merged_path.exists():
                        raise RuntimeError('视频合并/转码失败')

                    self._emit_progress(task_id, 60, '视频合并', '整段视频合并完成')
                    merge_source_path = merged_path
                    final_path = merged_path

                # 3）简单叠加BGM（普通/回退混剪均复用此逻辑）
                if auto_bgm or plan.get('bgm_file') or plan.get('music_path'):
                    bgm_path = _resolve_bgm_path()
                    if bgm_path:
                        try:
                            bgm_obj = Path(bgm_path)
                            if not bgm_obj.is_absolute():
                                bgm_obj = self.base_dir / bgm_path
                            if bgm_obj.exists() and merge_source_path and Path(merge_source_path).exists():
                                music_out = output_dir / f'{task_id}_with_bgm.mp4'
                                logger.info(f'🎵 混剪任务 {task_id}: 叠加背景音乐 {bgm_obj}')
                                ok = self.video_processor.add_audio_to_video(
                                    video_path=str(merge_source_path),
                                    audio_path=str(bgm_obj),
                                    output_path=str(music_out),
                                    replace=True
                                )
                                if ok:
                                    final_path = music_out
                        except Exception as e:
                            logger.error(f'叠加BGM失败: {e}', exc_info=True)

            # 补齐仅发生整段合并时的真实源视频时间线；不臆造不存在的片段。
            if not timeline and editing_mode == 'basic_merge':
                for source_path in abs_video_paths:
                    try:
                        source_info = self.video_processor.get_video_info(source_path) or {}
                        source_duration = float(source_info.get('duration') or 0)
                        record_timeline(source_path, 0.0, source_duration)
                    except Exception:
                        continue

            audio_paths: List[str] = []
            subtitle_text = ''
            voiceover_error = ''
            if bool(plan.get('auto_voiceover', False)):
                narration_parts = [
                    str(clip.get('description') or '').strip()
                    for clip in (plan.get('clips') or []) if isinstance(clip, dict)
                    and str(clip.get('description') or '').strip()
                ]
                if not narration_parts:
                    voiceover_error = '未找到可用于自动配音的真实片段文本'
                else:
                    subtitle_text = '\n'.join(narration_parts)
                    try:
                        requested_engine = str(plan.get('tts_engine') or 'edge-tts').strip().lower()
                        if requested_engine in ('azure-tts', 'azure_tts'):
                            requested_engine = 'azure'
                        elif requested_engine in ('edge', 'edgetts'):
                            requested_engine = 'edge-tts'
                        if requested_engine in ('indextts2', 'volcano'):
                            raise RuntimeError(f'主任务暂不支持 {requested_engine} 自动配音合成')
                        voiceover_path = output_dir / f'{task_id}_voiceover.mp3'
                        voice = plan.get('voice')
                        if not voice:
                            from backend.services.voiceover_service import VoiceoverService
                            voice = VoiceoverService._default_voice_id()
                        voice_ok = self.tts_engine.synthesize(
                            text=subtitle_text,
                            output_path=str(voiceover_path),
                            engine=requested_engine,
                            voice=voice,
                        )
                        if voice_ok and voiceover_path.exists() and voiceover_path.stat().st_size > 0:
                            audio_paths.append(str(voiceover_path))
                        else:
                            voiceover_error = '自动配音合成未生成有效音频'
                    except Exception as voice_error:
                        voiceover_error = str(voice_error) or '自动配音合成失败'
                        logger.warning('混剪任务自动配音失败，继续完成视频任务: %s', voiceover_error)

            self._emit_progress(task_id, 90, '后期处理', '正在生成最终视频...')

            # 获取输出视频信息
            info = {}
            try:
                info = self.video_processor.get_video_info(str(final_path)) or {}
            except Exception:
                info = {}

            duration = float(info.get('duration') or 0)
            if duration <= 0:
                raise RuntimeError('无法读取成片实际时长，拒绝将混剪任务标记为完成')
            size = int(info.get('size') or 0)
            duration_tolerance_seconds = 0.35
            duration_delta_seconds = round(duration - target_duration, 3)
            duration_within_tolerance = abs(duration_delta_seconds) <= duration_tolerance_seconds
            duration_status = 'completed' if duration_within_tolerance else 'partial'
            duration_warnings = []
            if not duration_within_tolerance:
                duration_warnings.append(
                    '成片实际时长 %.3fs 与目标 %.3fs 相差 %.3fs，任务结果仅为部分完成' %
                    (duration, target_duration, duration_delta_seconds)
                )
            if not duration_within_tolerance:
                raise RuntimeError(
                    '%s成片未达到目标时长容差：实测 %.3fs，目标 %.3fs，误差 %.3fs' %
                    ('音乐卡点' if mode == 'music' else '普通混剪', duration, target_duration, duration_delta_seconds)
                )

            video_url = f'/output/remix/{final_path.name}'
            output_data = {
                'video_url': video_url,
                'output_path': str(final_path),
                'video_path': str(final_path),
                'output_file': str(final_path),
                'duration': duration,
                'target_duration_seconds': target_duration,
                'actual_duration_seconds': duration if duration > 0 else None,
                'duration_delta_seconds': duration_delta_seconds,
                'duration_within_tolerance': duration_within_tolerance,
                'duration_tolerance_seconds': duration_tolerance_seconds,
                'duration_status': duration_status,
                'duration_warnings': duration_warnings,
                'size': size,
                'video_count': len(abs_video_paths),
                'mode': mode,
                'duration_mode': duration_mode,
                'project_id': project_id,
                # 真实编辑模式标识，避免把基础合并伪装成智能混剪
                'editing_mode': editing_mode,
                'auto_highlight_used': auto_highlight_used,
                'auto_highlight_requested': auto_highlight,
                'beat_remix_used': beat_remix_used,
                'dedup_plans_requested': len(dedup_plans),
                'advanced_style': plan.get('advanced_style') or '',
                'timeline': timeline,
                'audio_paths': audio_paths,
                'subtitle_text': subtitle_text,
                'auto_voiceover_requested': bool(plan.get('auto_voiceover', False)),
            }
            if voiceover_error:
                output_data['voiceover_error'] = voiceover_error
            if beat_remix_failure:
                output_data['beat_remix_failure'] = beat_remix_failure

            self._emit_progress(task_id, 100, '完成', f'视频生成完成，时长 {duration:.1f}秒')
            self.db_manager.update_task_status(task_id, 'completed', output_data=output_data)
            checkpoint_service.mark_stage_completed(task_id, 'clip_plan', {'editing_mode': editing_mode})
            checkpoint_service.mark_stage_completed(task_id, 'video_compose', {'output_path': str(final_path)})
            checkpoint_service.mark_stage_completed(task_id, 'export', {'output_path': str(final_path)})
            checkpoint_service.update_checkpoint(task_id, status='completed')
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'completed',
                    'progress': 100,
                    'step': '完成',
                    'output': output_data
                })
            except Exception:
                pass

            # 将成片写入项目 result / materials / config.tracks，
            # 使混剪与编辑器、草稿包共享同一份时间线数据。
            if project_id:
                try:
                    final_path_obj = Path(final_path)
                    self.db_manager.create_material(
                        project_id=project_id,
                        material_type='video',
                        name=final_path_obj.name,
                        path=str(final_path),
                        size=size,
                        duration=duration,
                        metadata={
                            'source': 'remix_output',
                            'editing_mode': editing_mode,
                            'auto_highlight_used': auto_highlight_used,
                            'beat_remix_used': beat_remix_used,
                        }
                    )
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
                    tracks = project_config.get('tracks') or []
                    tracks = self._append_video_track(
                        tracks, final_path_obj.name, str(final_path), duration
                    )
                    project_config['tracks'] = tracks
                    project_result = project.get('result')
                    if isinstance(project_result, str):
                        try:
                            result_obj = json.loads(project_result) if project_result else {}
                        except Exception:
                            result_obj = {}
                    elif isinstance(project_result, dict):
                        result_obj = project_result
                    else:
                        result_obj = {}
                    result_obj.update({
                        'output_path': str(final_path),
                        'video_path': str(final_path),
                        'video_url': video_url,
                        'duration': duration,
                        'duration_within_tolerance': duration_within_tolerance,
                        'target_duration_seconds': target_duration,
                        'actual_duration_seconds': duration,
                        'editing_mode': editing_mode,
                        'auto_highlight_used': auto_highlight_used,
                        'timeline': timeline,
                        'audio_paths': audio_paths,
                        'subtitle_text': subtitle_text,
                    })
                    self.db_manager.update_project(project_id, {
                        'config': project_config,
                        'result': result_obj,
                        'status': 'completed',
                    })
                except Exception as perr:
                    logger.warning(f'⚠️ 写入项目 result/tracks 失败（不影响任务完成）: {perr}')

            logger.info(f'✅ 混剪任务完成: {task_id} -> {final_path}')

        except Exception as e:
            logger.error(f'❌ 混剪任务失败: {e}', exc_info=True)
            try:
                from backend.services.checkpoint_service import get_checkpoint_service
                get_checkpoint_service().update_checkpoint(
                    task_id, status='failed', error_message=str(e)
                )
            except Exception:
                pass
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'failed',
                    'error': str(e)
                })
            except Exception:
                pass

    @staticmethod
    def _append_video_track(tracks: List[Dict], name: str, path: str,
                            duration: float, track_id: str = 'video-track-1') -> List[Dict]:
        """将一个视频片段追加到项目 tracks 的视频轨道。

        统一 tracks schema：
          tracks: [
            { id, type: 'video'|'audio'|'subtitle', clips: [ {id, name, path, start, duration} ] }
          ]
        """
        tracks = list(tracks or [])
        target = None
        for item in tracks:
            if item.get('id') == track_id and item.get('type') == 'video':
                target = item
                break
        if target is None:
            target = {'id': track_id, 'type': 'video', 'clips': []}
            tracks.append(target)
        clips = list(target.get('clips') or [])
        start_time = float(sum(float(c.get('duration') or 0) for c in clips))
        clips.append({
            'id': f"clip-{uuid.uuid4().hex[:8]}",
            'name': name,
            'path': path,
            'start': start_time,
            'duration': float(duration or 0),
        })
        target['clips'] = clips
        return tracks

    def process_video_merge(self, task_id: str, data: Dict):
        """处理视频合并"""
        try:
            logger.info(f'🎬 开始处理视频合并任务: {task_id}')

            video_paths = list((data or {}).get('video_paths') or [])
            if not video_paths:
                raise ValueError('video_paths 不能为空')

            # 规范化路径（支持相对路径）
            abs_paths = []
            for p in video_paths:
                try:
                    po = Path(p)
                    if not po.is_absolute():
                        po = self.base_dir / p
                    if po.exists():
                        abs_paths.append(str(po))
                    else:
                        logger.warning(f'⚠️ 视频合并任务 {task_id}: 文件不存在，将跳过: {po}')
                except Exception as pe:
                    logger.warning(f'⚠️ 视频合并任务 {task_id}: 解析路径失败 {p}: {pe}')

            if not abs_paths:
                raise RuntimeError('没有可用的视频文件用于合并')

            self.db_manager.update_task_status(task_id, 'running')
            self.db_manager.update_task_progress(task_id, 5)
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'running',
                    'progress': 5,
                    'message': '开始合并视频'
                })
            except Exception:
                pass

            # 输出目录
            output_dir = self.base_dir / 'output' / 'videos'
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{task_id}.mp4"

            # 根据数量选择合并或转码
            merged_ok = False
            if len(abs_paths) >= 2:
                logger.info(f'🎬 视频合并任务 {task_id}: 合并 {len(abs_paths)} 个视频')
                merged_ok = self.video_processor.merge_videos(abs_paths, str(output_path))
            else:
                logger.info(f'🎬 视频合并任务 {task_id}: 仅1个视频，执行转码')
                merged_ok = self.video_processor.convert_video(abs_paths[0], str(output_path))

            if not merged_ok or not output_path.exists():
                raise RuntimeError('视频合并/转码失败')

            self.db_manager.update_task_progress(task_id, 100)
            self.db_manager.update_task_status(task_id, 'completed', output_data={'output_path': str(output_path)})
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'completed',
                    'progress': 100,
                    'output_path': str(output_path)
                })
            except Exception:
                pass

        except Exception as e:
            logger.error(f'视频合并失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

    def process_tts(self, task_id: str, data: Dict):
        """处理TTS语音合成"""
        try:
            self.db_manager.update_task_status(task_id, 'running')
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'running'})

            # 实际调用TTS引擎
            from backend.engine.tts_engine import TTSEngine
            from pathlib import Path

            logger.info(f'开始处理TTS任务: {task_id}')
            logger.info(f'文本内容: {data.get("text")}')

            tts_engine = TTSEngine()
            out_path = Path(f"temp/outputs/{task_id}.mp3")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            text = data.get('text') or ''
            voice = data.get('voice')
            if not voice:
                try:
                    from backend.core.global_state import get_global_state
                    state = get_global_state()
                    language = state.get_user_setting('language', 'tts', None)
                    voice = {
                        'en': 'en-US-JennyNeural',
                        'ja': 'ja-JP-NanamiNeural',
                        'ko': 'ko-KR-SunHiNeural',
                    }.get(str(language or '').lower().split('-', 1)[0], 'zh-CN-XiaoxiaoNeural')
                except Exception:
                    from backend.services.voiceover_service import VoiceoverService
                    voice = VoiceoverService._default_voice_id()

            # 回退链路：edge-tts -> gTTS -> pyttsx3
            ok = False
            try:
                ok = tts_engine.synthesize(
                    text=text,
                    output_path=str(out_path),
                    engine='edge-tts',
                    voice=voice,
                    rate='+0%',
                    volume='+0%'
                )
            except Exception:
                ok = False
            if not ok:
                # 语言推断
                lang = 'zh-CN'
                try:
                    if isinstance(voice, str) and '-' in voice:
                        prefix = voice.split('-', 1)[0].lower()
                        if prefix in ('en', 'enus', 'en-us'):
                            lang = 'en'
                        elif prefix in ('ja', 'ja-jp'):
                            lang = 'ja'
                        elif prefix in ('ko', 'ko-kr'):
                            lang = 'ko'
                except Exception:
                    pass
                try:
                    ok = tts_engine.synthesize(
                        text=text,
                        output_path=str(out_path),
                        engine='gtts',
                        lang=lang,
                        slow=False
                    )
                except Exception:
                    ok = False
            if not ok:
                try:
                    ok = tts_engine.synthesize(
                        text=text,
                        output_path=str(out_path),
                        engine='pyttsx3',
                        rate='+0%',
                        volume='+0%'
                    )
                except Exception:
                    ok = False

            if not ok or not out_path.exists():
                raise RuntimeError('TTS 合成失败')

            self.db_manager.update_task_status(task_id, 'completed', output_data={'output_path': str(out_path)})
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})
            logger.info(f'✅ TTS处理完成: {out_path}')

        except Exception as e:
            logger.error(f'❌ TTS处理失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

    def process_asr(self, task_id: str, data: Dict):
        """处理ASR语音识别"""
        try:
            self.db_manager.update_task_status(task_id, 'running')
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'running'})

            # 实际调用ASR引擎
            from backend.engine.asr_engine import ASREngine

            logger.info(f'开始处理ASR任务: {task_id}')

            asr_engine = ASREngine()
            result = asr_engine.recognize(
                audio_path=data.get('audio_path'),
                language=data.get('language')
            )

            self.db_manager.update_task_status(task_id, 'completed', output_data=result)
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})
            logger.info(f'✅ ASR处理完成')

        except Exception as e:
            logger.error(f'❌ ASR处理失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})

    def process_scene_detect(self, task_id: str, data: Dict):
        """处理场景检测"""
        try:
            self.db_manager.update_task_status(task_id, 'running')
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'running'})

            # 实际调用场景检测器
            from backend.engine.scene_detector import SceneDetector

            logger.info(f'开始处理场景检测任务: {task_id}')

            detector = SceneDetector()
            scenes = detector.detect_scenes(
                video_path=data.get('video_path'),
                threshold=data.get('threshold', 0.3)
            )

            self.db_manager.update_task_status(task_id, 'completed', output_data={'scenes': scenes})
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'completed'})
            logger.info(f'✅ 场景检测完成: {len(scenes)}个场景')

        except Exception as e:
            logger.error(f'❌ 场景检测失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            self.socketio.emit('task_status', {'task_id': task_id, 'status': 'failed', 'error': str(e)})
