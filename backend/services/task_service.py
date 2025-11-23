# -*- coding: utf-8 -*-
"""
Task Service
任务处理服务 - 负责所有异步任务的处理
集成所有处理引擎，提供完整的任务处理能力
"""

import logging
import time
import uuid
import threading
from typing import Dict
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
            # 标记任务运行中
            self.db_manager.update_task_status(task_id, 'running')
            self.db_manager.update_task_progress(task_id, 5)
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'running',
                    'progress': 5
                })
            except Exception:
                pass

            plan: Dict = (input_data or {}).get('plan') or {}
            project_id: str = (input_data or {}).get('project_id') or ''
            mode = (plan.get('mode') or plan.get('remix_mode') or 'general').lower()
            auto_bgm = bool(plan.get('auto_bgm', True))

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

            output_dir = self.base_dir / 'output' / 'remix'
            output_dir.mkdir(parents=True, exist_ok=True)

            final_path = None
            used_beat_remix = False

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
                                self.db_manager.update_task_progress(task_id, 20)
                                logger.info(f'🎵 混剪任务 {task_id}: 使用 BeatRemixEngine 进行音乐卡点剪辑')

                                target_duration = None
                                try:
                                    td = plan.get('target_duration')
                                    if td is not None:
                                        target_duration = float(td)
                                except Exception:
                                    target_duration = None

                                beat_result = engine.create_beat_remix(
                                    video_clips=abs_video_paths,
                                    music_path=str(bgm_obj),
                                    style=plan.get('style') or 'dynamic',
                                    target_duration=target_duration,
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
                                    for idx, match in enumerate(beat_matches):
                                        clip_path = match.get('clip_path')
                                        clip_info = match.get('clip_info') or {}
                                        clip_duration = float(clip_info.get('duration') or 0)
                                        seg_duration = float(match.get('duration') or 0)
                                        if not clip_path or seg_duration <= 0:
                                            continue

                                        # BeatRemixEngine 新增的源视频内部时间范围（优先使用）
                                        start_sec = float(match.get('clip_start') or 0.0)
                                        end_sec = float(match.get('clip_end') or 0.0)

                                        if end_sec <= start_sec:
                                            # 兼容旧数据：未提供 clip_start/clip_end 时，退回基于时长的截取
                                            cut_duration = seg_duration
                                            if clip_duration > 0:
                                                cut_duration = min(seg_duration, clip_duration)
                                            if cut_duration <= 0:
                                                continue
                                            start_sec = 0.0
                                            end_sec = start_sec + cut_duration
                                        else:
                                            cut_duration = end_sec - start_sec

                                        if cut_duration <= 0:
                                            continue

                                        seg_out = segments_dir / f"{task_id}_seg_{idx:03d}.mp4"
                                        
                                        # 获取变速因子，应用节拍卡点的变速效果
                                        speed_factor = float(match.get('speed_factor') or 1.0)
                                        
                                        if speed_factor != 1.0 and 0.5 <= speed_factor <= 2.0:
                                            logger.info(f'🎬 片段 {idx}: 应用变速 {speed_factor:.2f}x')
                                            ok_seg = self.video_processor.cut_video_with_speed(
                                                input_path=clip_path,
                                                output_path=str(seg_out),
                                                start_time=start_sec,
                                                end_time=end_sec,
                                                speed_factor=speed_factor
                                            )
                                            # 变速后片段的实际时长 ≈ 源时长 / speed_factor
                                            try:
                                                real_duration = max(cut_duration / speed_factor, 0.05)
                                            except Exception:
                                                real_duration = max(cut_duration, 0.05)
                                        else:
                                            ok_seg = self.video_processor.cut_video(
                                                input_path=clip_path,
                                                output_path=str(seg_out),
                                                start_time=start_sec,
                                                end_time=end_sec
                                            )
                                            real_duration = max(cut_duration, 0.05)
                                        
                                        if ok_seg:
                                            segment_paths.append(str(seg_out))
                                            segment_durations.append(real_duration)

                                    if segment_paths:
                                        merged_path = output_dir / f'{task_id}_beat_merged.mp4'
                                        self.db_manager.update_task_progress(task_id, 60)
                                        if len(segment_paths) >= 2:
                                            beat_trans = plan.get('beat_transition') or plan.get('beatTransition') or 'cut'
                                            logger.info(
                                                f'🎬 混剪任务 {task_id}: 使用转场 {beat_trans} 合并 {len(segment_paths)} 个节拍片段'
                                            )
                                            merged_ok = self.video_processor.merge_videos_with_transitions(
                                                segment_paths,
                                                str(merged_path),
                                                transition=str(beat_trans),
                                                trans_duration=None,
                                                durations=segment_durations
                                            )
                                        else:
                                            logger.info(f'🎬 混剪任务 {task_id}: 仅1个节拍片段，执行转码')
                                            merged_ok = self.video_processor.convert_video(segment_paths[0], str(merged_path))

                                        if merged_ok and merged_path.exists():
                                            music_out = output_dir / f'{task_id}_beat_with_bgm.mp4'
                                            self.db_manager.update_task_progress(task_id, 80)
                                            logger.info(f'🎵 混剪任务 {task_id}: 为节拍剪辑结果叠加背景音乐 {bgm_obj}')
                                            ok_audio = self.video_processor.add_audio_to_video(
                                                video_path=str(merged_path),
                                                audio_path=str(bgm_obj),
                                                output_path=str(music_out),
                                                replace=True
                                            )
                                            final_path = music_out if ok_audio else merged_path

                                            # 为提升播放器兼容性，最后对节拍混剪结果做一次转码，避免部分环境下出现中途黑屏
                                            try:
                                                from pathlib import Path as _P
                                                fp = _P(final_path)
                                                if fp.exists():
                                                    reencoded = output_dir / f'{task_id}_beat_final.mp4'
                                                    logger.info(
                                                        f'🎥 混剪任务 {task_id}: 对节拍混剪结果进行转码以提升兼容性 -> {reencoded}'
                                                    )
                                                    if self.video_processor.convert_video(str(fp), str(reencoded)):
                                                        final_path = reencoded
                                            except Exception as te:
                                                logger.error(f'节拍混剪结果转码失败: {te}', exc_info=True)

                                            used_beat_remix = True
                except Exception as e:
                    logger.error(f'音乐卡点智能剪辑失败，将回退到普通混剪: {e}', exc_info=True)

            # 如未能使用 BeatRemixEngine，则回退到基于精彩片段/整段合并的普通混剪逻辑
            if not used_beat_remix:
                clips = (plan.get('clips') or []) if isinstance(plan, dict) else []
                merged_path = None
                merge_source_path = None

                # 1）优先根据精彩片段方案进行剪辑+合并
                if clips:
                    segments_dir = self.base_dir / 'temp' / 'remix_clips' / task_id
                    segments_dir.mkdir(parents=True, exist_ok=True)
                    segment_paths = []
                    segment_durations = []

                    for idx, clip in enumerate(clips):
                        try:
                            clip_src = clip.get('video_path') or ''
                            if not clip_src:
                                continue
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
                                    continue

                            start_sec = float(clip.get('start_time') or clip.get('start') or 0.0)
                            end_sec = float(clip.get('end_time') or clip.get('end') or 0.0)
                            if end_sec <= start_sec:
                                continue
                            duration = end_sec - start_sec

                            seg_out = segments_dir / f"{task_id}_clip_{idx:03d}.mp4"
                            ok_seg = self.video_processor.cut_video(
                                input_path=str(clip_path),
                                output_path=str(seg_out),
                                start_time=start_sec,
                                end_time=end_sec
                            )
                            if ok_seg and seg_out.exists():
                                segment_paths.append(str(seg_out))
                                segment_durations.append(duration)
                        except Exception as ce:
                            logger.error(f'生成精彩片段片段失败: {ce}', exc_info=True)
                            continue

                    if segment_paths:
                        merged_path = output_dir / f'{task_id}_clips_merged.mp4'
                        # 稍微提前一些进度，表示已完成片段裁剪
                        self.db_manager.update_task_progress(task_id, 30)
                        if len(segment_paths) >= 2:
                            trans = plan.get('transition_style') or plan.get('transition') or 'fade'
                            logger.info(
                                f'🎬 混剪任务 {task_id}: 使用精彩片段方案合并 {len(segment_paths)} 段，转场={trans}'
                            )
                            merged_ok = self.video_processor.merge_videos_with_transitions(
                                segment_paths,
                                str(merged_path),
                                transition=str(trans),
                                trans_duration=None,
                                durations=segment_durations
                            )
                        else:
                            logger.info(f'🎬 混剪任务 {task_id}: 仅1个精彩片段，执行转码')
                            merged_ok = self.video_processor.convert_video(segment_paths[0], str(merged_path))

                        if not merged_ok:
                            raise RuntimeError('精彩片段合并失败')

                        self.db_manager.update_task_progress(task_id, 60)
                        merge_source_path = merged_path
                        final_path = merged_path
                    else:
                        logger.warning(f'混剪任务 {task_id}: 未生成有效精彩片段，将回退到整段合并逻辑')

                # 2）如未生成 clips 或失败，则使用整段合并逻辑
                if merged_path is None:
                    merged_path = output_dir / f'{task_id}_merged.mp4'

                    # 合并/转码视频
                    self.db_manager.update_task_progress(task_id, 20)
                    merged_ok = False
                    if len(abs_video_paths) >= 2:
                        logger.info(f'🎬 混剪任务 {task_id}: 合并 {len(abs_video_paths)} 个视频')
                        merged_ok = self.video_processor.merge_videos(abs_video_paths, str(merged_path))
                    else:
                        logger.info(f'🎬 混剪任务 {task_id}: 仅1个视频，执行转码')
                        merged_ok = self.video_processor.convert_video(abs_video_paths[0], str(merged_path))

                    if not merged_ok:
                        raise RuntimeError('视频合并/转码失败')

                    self.db_manager.update_task_progress(task_id, 60)
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

            self.db_manager.update_task_progress(task_id, 90)

            # 获取输出视频信息
            info = {}
            try:
                info = self.video_processor.get_video_info(str(final_path)) or {}
            except Exception:
                info = {}

            duration = float(info.get('duration') or 0)
            size = int(info.get('size') or 0)

            video_url = f'/output/remix/{final_path.name}'
            output_data = {
                'video_url': video_url,
                'output_file': str(final_path),
                'duration': duration,
                'size': size,
                'video_count': len(abs_video_paths),
                'mode': mode,
                'project_id': project_id
            }

            self.db_manager.update_task_progress(task_id, 100)
            self.db_manager.update_task_status(task_id, 'completed', output_data=output_data)
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'completed',
                    'progress': 100,
                    'output': output_data
                })
            except Exception:
                pass

            logger.info(f'✅ 混剪任务完成: {task_id} -> {final_path}')

        except Exception as e:
            logger.error(f'❌ 混剪任务失败: {e}', exc_info=True)
            self.db_manager.update_task_status(task_id, 'failed', error_message=str(e))
            try:
                self.socketio.emit('task_status', {
                    'task_id': task_id,
                    'status': 'failed',
                    'error': str(e)
                })
            except Exception:
                pass
    
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
            voice = data.get('voice', 'zh-CN-XiaoxiaoNeural')
            
            # 统一使用本地 pyttsx3 离线引擎，忽略在线TTS请求
            engine_req = ''
            try:
                engine_req = (data.get('engine') or '').strip().lower()
            except Exception:
                engine_req = ''

            if engine_req and engine_req not in ('pyttsx3', 'local', 'offline'):
                logger.warning(
                    f"TTS 任务 {task_id} 请求在线引擎 {engine_req}，当前版本仅支持本地 pyttsx3，将自动切换为离线引擎。"
                )

            ok = False
            try:
                ok = tts_engine.synthesize(
                    text=text,
                    output_path=str(out_path),
                    engine='pyttsx3',
                    voice=voice,
                    rate='+0%',
                    volume='+0%'
                )
            except Exception as e:
                logger.error(f'❌ 本地 pyttsx3 合成失败: {e}', exc_info=True)
                ok = False
            
            if not ok or not out_path.exists():
                raise RuntimeError('TTS 合成失败（本地 pyttsx3）')
            
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
            result = asr_engine.transcribe(
                audio_path=data.get('audio_path'),
                language=data.get('language', 'zh')
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
