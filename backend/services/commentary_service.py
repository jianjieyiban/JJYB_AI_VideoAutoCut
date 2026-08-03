# -*- coding: utf-8 -*-
"""
原创解说剪辑服务 - 完整AI流程
视频画面分析 → 文案生成 → 智能配音 → 三同步
"""

import logging
from typing import Dict, Any, Optional, List
import os
import json
import re
import shutil
import uuid
from pathlib import Path
from datetime import datetime

from backend.config.paths import PROJECT_ROOT
from backend.engine.script_generator import ScriptGenerator
from backend.engine.tts_engine import TTSEngine
from backend.engine.video_processor import VideoProcessor

logger = logging.getLogger('JJYB_AI智剪')


class CommentaryService:
    """原创解说剪辑服务 - 完整实现"""

    def __init__(self, db_manager, socketio, task_service):
        """
        初始化原创解说剪辑服务

        Args:
            db_manager: 数据库管理器
            socketio: SocketIO实例
            task_service: 任务服务
        """
        self.db_manager = db_manager
        self.socketio = socketio
        self.task_service = task_service

        # 为旧版原创解说提供最小可用的AI能力（不影响增强版流程）
        try:
            self.script_generator = ScriptGenerator(
                api_key=None,
                model='gpt-4'
            )
        except Exception:
            self.script_generator = None

        self.tts_engine = TTSEngine()
        self.video_processor = VideoProcessor()

        logger.info('✅ 原创解说剪辑服务初始化完成')

    def create_commentary_project(self, data: Dict) -> Dict:
        """
        创建原创解说剪辑项目

        Args:
            data: 项目数据
                - name: 项目名称
                - video_path: 视频路径
                - script: 解说文稿（可选）
                - voice: 配音音色
                - bgm: 背景音乐（可选）

        Returns:
            项目信息
        """
        try:
            logger.info('🎬 创建原创解说剪辑项目...')

            # 创建项目
            project = self.db_manager.create_project(
                name=data.get('name', '原创解说项目'),
                project_type='commentary',
                description='原创解说剪辑项目',
                template='commentary'
            )

            project_id = project['id']

            # 如果有视频，添加为素材
            if data.get('video_path'):
                self.db_manager.create_material(
                    project_id=project_id,
                    material_type='video',
                    name='原始视频',
                    path=data['video_path'],
                    metadata={'source': 'upload'}
                )

            # 保存配置
            config = {
                'script': data.get('script', ''),
                'voice': data.get('voice', 'zh-CN-XiaoxiaoNeural'),
                'bgm': data.get('bgm', ''),
                'auto_subtitle': data.get('auto_subtitle', True),
                'auto_bgm': data.get('auto_bgm', True)
            }

            self.db_manager.update_project(project_id, {'config': config})

            logger.info(f'✅ 原创解说项目创建成功: {project_id}')

            return {
                'project_id': project_id,
                'project': project,
                'config': config
            }

        except Exception as e:
            logger.error(f'❗ 创建原创解说项目失败: {e}', exc_info=True)
            raise

    def generate_script(self, project_id: str, video_info: Dict) -> Dict:
        """
        AI生成解说文稿

        Args:
            project_id: 项目ID
            video_info: 视频信息

        Returns:
            生成的文稿
        """
        try:
            logger.info(f'📝 生成解说文稿: {project_id}')

            # 从项目信息中提取基础信息（若可用）
            project = None
            try:
                project = self.db_manager.get_project(project_id)
            except Exception:
                project = None

            duration = float(video_info.get('duration') or 0.0)
            if duration <= 0 and project:
                try:
                    meta = (project.get('metadata') or {})
                    duration = float(meta.get('duration') or 0.0)
                except Exception:
                    duration = 0.0

            # 构造一个简化的 vision_analysis 结构，便于 ScriptGenerator 使用
            vision_analysis: Dict[str, Any] = {
                'scenes': [],
                'descriptions': [],
                'emotions': [],
                'summary': project.get('description', '原创解说视频') if project else '原创解说视频'
            }

            if duration > 0:
                # 按时长平均分段，生成基础场景信息
                segment_count = max(1, min(6, int(duration // 8) or 1))
                seg_dur = duration / segment_count
                scenes = []
                descriptions = []
                for i in range(segment_count):
                    start = i * seg_dur
                    end = min(duration, (i + 1) * seg_dur)
                    scenes.append({
                        'id': i,
                        'start_time': start,
                        'end_time': end,
                        'duration': end - start
                    })
                    descriptions.append({'description': f'第{i+1}段画面'})
                vision_analysis['scenes'] = scenes
                vision_analysis['descriptions'] = descriptions

            # 优先使用 ScriptGenerator（如可用），否则退回到规则生成
            if getattr(self, 'script_generator', None):
                try:
                    script = self.script_generator.generate_script(
                        vision_analysis=vision_analysis,
                        style='professional',
                        duration=duration or None,
                        narration_mode='general',
                        custom_prompt=None,
                        hook_type='suspense',
                        use_viral_prompts=True
                    )
                    if script:
                        logger.info('✅ 文稿生成完成（ScriptGenerator）')
                        return script
                except Exception as se:
                    logger.warning(f'⚠️ ScriptGenerator 生成文稿失败，使用规则生成: {se}')

            # 规则生成回退：根据场景信息构建简单文稿
            paragraphs: List[Dict[str, Any]] = []
            cur_time = 0.0
            if duration <= 0:
                duration = 30.0
            segment_count = max(3, min(6, int(duration // 6)))
            seg_dur = duration / segment_count
            for i in range(segment_count):
                text = f"第{i+1}段：这里展示的是视频的精彩内容片段，创作者可以在此处补充更具体的讲解。"
                paragraphs.append({
                    'time': int(cur_time),
                    'duration': int(seg_dur),
                    'text': text
                })
                cur_time += seg_dur

            full_text = ''.join(p['text'] for p in paragraphs)
            script = {
                'title': project.get('name', '原创解说文稿') if project else '原创解说文稿',
                'content': full_text,
                'paragraphs': paragraphs,
                'total_duration': int(duration),
                'word_count': len(full_text)
            }

            logger.info(f'✅ 文稿生成完成（规则生成）: {script["word_count"]}字')

            return script

        except Exception as e:
            logger.error(f'❗ 生成文稿失败: {e}', exc_info=True)
            raise

    def process_commentary(self, project_id: str, config: Dict) -> str:
        """
        处理原创解说剪辑

        Args:
            project_id: 项目ID
            config: 配置信息

        Returns:
            任务ID
        """
        try:
            logger.info(f'🎬 开始处理原创解说剪辑: {project_id}')
            try:
                target = config.get('target_duration_seconds')
                source = config.get('source_duration_seconds')
                if target is not None and source is not None:
                    target_sec = int(float(target))
                    source_sec = int(float(source))
                    if target_sec < 1:
                        target_sec = 1
                    if source_sec < 1:
                        source_sec = 1
                    if target_sec > source_sec:
                        logger.info(
                            '目标时长 %s 大于源视频时长 %s，已在后端自动夹紧',
                            target_sec, source_sec
                        )
                        target_sec = source_sec
                    config['target_duration_seconds'] = target_sec
            except Exception as e:
                logger.warning(f'目标时长兜底校验失败: {e}')

            task_id = self.task_service.create_commentary_task(
                project_id=project_id,
                config=config
            )

            logger.info(f'✅ 原创解说任务已创建: {task_id}')

            return task_id

        except Exception as e:
            logger.error(f'❗ 处理原创解说失败: {e}', exc_info=True)
            raise

    def auto_clip_video(self, video_path: str, script: Dict) -> List[Dict]:
        """
        根据文稿自动剪辑视频

        Args:
            video_path: 视频路径
            script: 解说文稿

        Returns:
            剪辑片段列表
        """
        try:
            logger.info('✂️ 自动剪辑视频...')

            clips = []
            for i, paragraph in enumerate(script.get('paragraphs', [])):
                clip = {
                    'index': i,
                    'start_time': paragraph['time'],
                    'end_time': paragraph['time'] + paragraph['duration'],
                    'duration': paragraph['duration'],
                    'text': paragraph['text']
                }
                clips.append(clip)

            logger.info(f'✅ 自动剪辑完成: {len(clips)}个片段')

            return clips

        except Exception as e:
            logger.error(f'❗ 自动剪辑失败: {e}', exc_info=True)
            raise

    def add_voice_over(self, clips: List[Dict], voice_config: Dict) -> List[Dict]:
        """
        添加配音

        Args:
            clips: 视频片段
            voice_config: 配音配置

        Returns:
            添加配音后的片段
        """
        try:
            logger.info('🎙️ 添加配音...')
            voice_config = self._normalize_voice_config(voice_config)

            if not clips:
                return []

            voice_id = voice_config.get('voice_id') or voice_config.get('voice') or 'zh-CN-XiaoxiaoNeural'
            engine = voice_config.get('engine') or None

            out_dir = PROJECT_ROOT / 'output' / 'commentary_voice'
            out_dir.mkdir(parents=True, exist_ok=True)

            for clip in clips:
                text = str(clip.get('text') or '').strip()
                idx = clip.get('index') if isinstance(clip.get('index'), int) else 0
                if not text:
                    logger.warning(f'⚠️ 片段 {idx} 文本为空，跳过配音生成')
                    clip['voice_path'] = ''
                    continue

                voice_file = out_dir / f"clip_{idx}_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp3"
                logger.info(f"  🔊 生成片段配音: index={idx}, voice={voice_id}, engine={engine or self.tts_engine.default_engine}")

                ok = self.tts_engine.synthesize(
                    text=text,
                    output_path=str(voice_file),
                    engine=engine,
                    voice=voice_id
                )
                if ok and voice_file.exists():
                    clip['voice_path'] = str(voice_file)
                else:
                    logger.error(f'❗ 片段 {idx} 配音生成失败')
                    clip['voice_path'] = ''

            logger.info(f'✅ 配音添加完成: {len(clips)}个片段')

            return clips

        except Exception as e:
            logger.error(f'❗ 添加配音失败: {e}', exc_info=True)
            raise

    def add_bgm(self, video_path: str, bgm_path: str, volume: float = 0.3) -> str:
        """
        添加背景音乐

        Args:
            video_path: 视频路径
            bgm_path: 背景音乐路径
            volume: 音量（0-1）

        Returns:
            输出视频路径
        """
        try:
            logger.info('🎵 添加背景音乐...')

            if not video_path or not bgm_path:
                raise ValueError('video_path 和 bgm_path 不能为空')

            v_path = Path(video_path)
            if not v_path.is_absolute():
                v_path = PROJECT_ROOT / video_path
            a_path = Path(bgm_path)
            if not a_path.is_absolute():
                a_path = PROJECT_ROOT / bgm_path

            if not v_path.exists():
                raise FileNotFoundError(f'视频文件不存在: {v_path}')
            if not a_path.exists():
                raise FileNotFoundError(f'背景音乐文件不存在: {a_path}')

            out_dir = PROJECT_ROOT / 'output' / 'videos'
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"with_bgm_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"

            # 目前使用简单叠加：保持原视频画面，叠加 BGM（replace=False 表示混合音轨）
            logger.info(f'🎵 为视频叠加BGM: video={v_path}, bgm={a_path}, volume={volume}')

            ok = self.video_processor.add_audio_to_video(
                video_path=str(v_path),
                audio_path=str(a_path),
                output_path=str(output_path),
                replace=False
            )
            if not ok:
                raise RuntimeError('叠加背景音乐失败')

            logger.info(f'✅ 背景音乐添加完成: {output_path}')

            return str(output_path)

        except Exception as e:
            logger.error(f'❗ 添加背景音乐失败: {e}', exc_info=True)
            raise

    def generate_subtitles(self, script: Dict) -> str:
        """
        生成字幕文件

        Args:
            script: 解说文稿

        Returns:
            字幕文件路径
        """
        try:
            logger.info('📝 生成字幕...')

            srt_path = f"output/subtitles/subtitle_{datetime.now().strftime('%Y%m%d%H%M%S')}.srt"
            Path(srt_path).parent.mkdir(parents=True, exist_ok=True)

            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, paragraph in enumerate(script.get('paragraphs', []), 1):
                    start_time = self._format_srt_time(paragraph['time'])
                    end_time = self._format_srt_time(paragraph['time'] + paragraph['duration'])

                    f.write(f"{i}\n")
                    f.write(f"{start_time} --> {end_time}\n")
                    f.write(f"{paragraph['text']}\n\n")

            logger.info(f'✅ 字幕生成完成: {srt_path}')

            return srt_path

        except Exception as e:
            logger.error(f'❗ 生成字幕失败: {e}', exc_info=True)
            raise

    def _format_srt_time(self, seconds: float) -> str:
        """格式化SRT时间"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

    # ================================================================== #
    # 升级能力 1：智能镜头分割（剪映专业版风格）
    # ================================================================== #
    def smart_segment_shots(self,
                            video_path: str,
                            threshold: float = 0.5,
                            min_scene_len_sec: float = 0.4,
                            use_transnetv2: bool = True,
                            export_keyframes: bool = True,
                            max_shots: Optional[int] = None,
                            progress_callback=None,
                            cancel_callback=None) -> Dict:
        """
        智能分割视频镜头（一个分割画面 = 一帧），分析帧数无上限

        Args:
            video_path: 视频路径
            threshold: TransNetV2 边界阈值
            min_scene_len_sec: 最小镜头时长
            use_transnetv2: 是否优先使用 TransNetV2
            export_keyframes: 是否导出关键帧缩略图
            max_shots: 最大镜头数（None=无上限）

        Returns:
            dict: shots 列表 + 统计信息
        """
        try:
            from backend.engine.smart_shot_segmenter import (
                SmartShotSegmenter, SmartShotSegmentationCancelled,
            )

            def check_cancel():
                if cancel_callback and cancel_callback():
                    raise SmartShotSegmentationCancelled('智能镜头分割已取消')

            check_cancel()
            v_path = Path(video_path)
            if not v_path.is_absolute():
                v_path = PROJECT_ROOT / video_path
            if not v_path.exists():
                raise FileNotFoundError(f'视频文件不存在: {v_path}')

            segmenter = SmartShotSegmenter(
                threshold=threshold,
                min_scene_len_sec=min_scene_len_sec,
                use_transnetv2=use_transnetv2,
            )
            def report(progress: float, message: str):
                if progress_callback:
                    progress_callback(progress, message)

            report(0, '准备智能镜头分割')
            check_cancel()
            shots = segmenter.detect_shots(
                str(v_path), progress_callback=lambda progress: report(progress * 0.75, '正在检测镜头边界或评分'),
                max_shots=max_shots,
                cancel_callback=cancel_callback,
            )

            check_cancel()
            report(75, '正在完成镜头评分')
            if export_keyframes and shots:
                kf_dir = PROJECT_ROOT / 'output' / 'keyframes' / v_path.stem
                shots = segmenter.export_keyframes(
                    str(v_path), shots, str(kf_dir),
                    progress_callback=lambda progress: report(75 + progress * 0.25, '正在导出关键帧'),
                    cancel_callback=cancel_callback,
                )
            check_cancel()
            report(100, '智能镜头分割完成')

            logger.info(f'✅ 智能镜头分割完成: {len(shots)} 个镜头')
            return {
                'video_path': str(v_path),
                'total_shots': len(shots),
                'shots': shots,
                'method': shots[0].get('method', 'opencv') if shots else 'none',
            }
        except Exception as e:
            logger.error(f'❗ 智能镜头分割失败: {e}', exc_info=True)
            raise

    # ================================================================== #
    # 升级能力 2：拟人化字画音画同步剪辑
    # ================================================================== #
    def _timeline_subtitle_srt(self, timeline: List[Dict]) -> tuple[str, int]:
        clips = []
        cursor = 0.0
        for item in timeline:
            duration = max(0.0, float(item.get('final_duration') or item.get('audio_duration') or 0))
            text = '' if item.get('kind') == 'original_audio' or item.get('original_audio') else str(item.get('subtitle_text') or '').strip()
            if text and duration > 0:
                clips.append((cursor, cursor + duration, text))
            cursor += duration
        if not clips:
            return '', 0

        def srt_time(seconds: float) -> str:
            milliseconds = max(0, int(round(seconds * 1000)))
            hours, remainder = divmod(milliseconds, 3_600_000)
            minutes, remainder = divmod(remainder, 60_000)
            secs, milliseconds = divmod(remainder, 1000)
            return f'{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}'

        subtitle_dir = PROJECT_ROOT / 'output' / 'subtitles'
        subtitle_dir.mkdir(parents=True, exist_ok=True)
        subtitle_file = subtitle_dir / f'puppet_{datetime.now().strftime("%Y%m%d%H%M%S")}_{uuid.uuid4().hex[:8]}.srt'
        lines = []
        for index, (start, end, text) in enumerate(clips, 1):
            lines.extend([str(index), f'{srt_time(start)} --> {srt_time(end)}', text, ''])
        subtitle_file.write_text('\n'.join(lines), encoding='utf-8')
        return str(subtitle_file), len(clips)

    def puppet_sync_commentary(self,
                               video_path: str,
                               shots: List[Dict],
                               voices: List[Dict],
                               bgm_path: str = '',
                               subtitle_path: str = '',
                               allow_reuse: bool = False,
                               insert_original_audio: bool = False,
                               original_clip_interval: int = 3,
                               original_clip_duration: float = 3.0,
                               original_audio_volume: float = 1.0,
                               render: bool = True,
                               output_path: str = '',
                               target_duration_seconds: float = None,
                               project_id: str = '',
                               original_audio_mode: str = 'interval',
                               original_audio_ratio: float = None) -> Dict:
        """
        拟人化字画音画同步：每段语音匹配一个画面，画面不重复，
        画面短于配音则变速/定格，画面长于配音则智能截取。

        Args:
            video_path: 源视频路径
            shots: smart_segment_shots 返回的镜头列表
            voices: 配音段列表 [{text, voice_path, duration}, ...]
            bgm_path: 可选 BGM 路径
            subtitle_path: 可选 SRT 字幕路径
            allow_reuse: 是否允许画面重复使用
            render: 是否实际渲染视频
            output_path: 指定输出路径

        Returns:
            dict: timeline + 输出视频路径（若渲染）
        """
        try:
            from backend.engine.puppet_sync_engine import PuppetSyncEngine
            from backend.engine.video_processor import VideoProcessor

            v_path = Path(video_path)
            if not v_path.is_absolute():
                v_path = PROJECT_ROOT / video_path
            if not v_path.exists():
                raise FileNotFoundError(f'视频文件不存在: {v_path}')

            # 复用 video_processor 自带的 ffprobe
            try:
                _vp = VideoProcessor()
                _ffprobe_path = getattr(_vp, 'ffprobe_path', 'ffprobe')
                _ffmpeg_path = getattr(_vp, 'ffmpeg_path', 'ffmpeg')
            except Exception:
                _ffprobe_path = 'ffprobe'
                _ffmpeg_path = 'ffmpeg'

            def _probe_duration(media_path: str) -> float:
                try:
                    cmd = [_ffprobe_path, '-v', 'quiet', '-print_format', 'json',
                           '-show_entries', 'format=duration', '-i', str(media_path)]
                    import subprocess as _sp
                    out = _sp.run(cmd, capture_output=True, text=True, check=False, timeout=30)
                    if out and out.returncode == 0 and out.stdout:
                        import json as _json
                        data = _json.loads(out.stdout) or {}
                        return max(0.0, float((data.get('format') or {}).get('duration') or 0.0))
                except Exception:
                    pass
                return 0.0

            # ============================================================
            # 入参标准化：兼容前端不同格式（audio_path/voice_path/duration/duration_seconds）
            # ============================================================
            def _to_abs_path(p: str) -> str:
                p = str(p or '').strip()
                if not p:
                    return ''
                if p.startswith('/api/download/'):
                    p = p[len('/api/download/'):]
                po = Path(p)
                if not po.is_absolute():
                    po = PROJECT_ROOT / po
                return str(po.resolve()) if po.exists() and po.is_file() else ''

            normalized_voices: List[Dict] = []
            for pos, raw_voice in enumerate(voices or []):
                if not isinstance(raw_voice, dict):
                    continue
                text = str(raw_voice.get('text') or '').strip()
                if not text:
                    continue
                audio_path = (
                    raw_voice.get('voice_path')
                    or raw_voice.get('audio_path')
                    or raw_voice.get('audio_url')
                    or ''
                )
                abs_audio = _to_abs_path(audio_path)
                if raw_voice.get('status') == 'failed':
                    raise ValueError('第%s段配音生成失败，请先重录后再生成拟人化成片' % (pos + 1))
                if render and not abs_audio:
                    raise ValueError('第%s段配音没有可用音频文件，请先完成全部配音后再生成拟人化成片' % (pos + 1))
                duration = 0.0
                for key in ('duration', 'duration_seconds', 'audio_duration_seconds'):
                    try:
                        d = float(raw_voice.get(key) or 0)
                        if d > 0:
                            duration = d
                            break
                    except (TypeError, ValueError):
                        continue
                if (not duration or duration <= 0) and abs_audio:
                    duration = max(0.0, float(_probe_duration(abs_audio) or 0.0))
                # 按字数粗略估算，避免后面匹配时全部跳过
                if not duration or duration <= 0:
                    duration = max(0.5, len(text) * 0.28)
                merged = dict(raw_voice)
                merged.setdefault('index', raw_voice.get('index', pos))
                merged.setdefault('id', str(raw_voice.get('id') or ('v_%d' % pos)))
                merged['text'] = text
                merged['voice_path'] = abs_audio or str(audio_path)
                merged['audio_path'] = abs_audio or str(audio_path)
                merged['duration'] = duration
                merged['duration_seconds'] = duration
                merged['status'] = 'ready' if abs_audio else (raw_voice.get('status') or 'pending')
                normalized_voices.append(merged)

            normalized_shots: List[Dict] = []
            raw_shots = shots or []
            # 支持包装结构：{'shots': [...]} / {'segments': [...]}
            if isinstance(raw_shots, dict):
                for key in ('shots', 'segments', 'scenes', 'clips'):
                    if isinstance(raw_shots.get(key), list):
                        raw_shots = raw_shots[key]
                        break
            for pos, raw_shot in enumerate(raw_shots or []):
                if not isinstance(raw_shot, dict):
                    continue
                def _f(k_list, default=0.0):
                    for k in k_list:
                        try:
                            v = float(raw_shot.get(k) or 0)
                            if v > 0 or k in ('start_time', 'start'):
                                return v
                        except (TypeError, ValueError):
                            continue
                    return float(default)
                start = _f(('start_time', 'start', 'from', 'begin_time'))
                end = _f(('end_time', 'end', 'to', 'finish_time'))
                dur = _f(('duration', 'duration_seconds', 'shot_duration'), 0.0)
                if end <= 0 and dur > 0:
                    end = start + dur
                if dur <= 0 and end > start:
                    dur = end - start
                if dur <= 0:
                    continue
                if end <= start:
                    end = start + dur
                score = raw_shot.get('score')
                try:
                    if score is None:
                        score = 0.5
                    else:
                        score = float(score)
                except (TypeError, ValueError):
                    score = 0.5
                shot_id = str(raw_shot.get('id') or raw_shot.get('shot_id') or ('shot_%d' % pos))
                scene_type = str(raw_shot.get('scene_type') or raw_shot.get('category') or 'neutral')
                desc = str(raw_shot.get('description') or raw_shot.get('desc') or raw_shot.get('summary') or '')
                merged_shot = dict(raw_shot)
                merged_shot.update({
                    'id': shot_id,
                    'index': raw_shot.get('index', pos),
                    'start_time': start,
                    'end_time': end,
                    'duration': dur,
                    'score': score,
                    'scene_type': scene_type,
                    'description': desc,
                    'source_video': str(
                        raw_shot.get('source_video')
                        or raw_shot.get('source_video_path')
                        or raw_shot.get('video_path')
                        or raw_shot.get('source_path')
                        or str(v_path)
                    ),
                })
                normalized_shots.append(merged_shot)

            if not normalized_shots:
                # 镜头列表完全无效时，兜底按视频时长均分生成 10 段基础镜头
                try:
                    from backend.engine import VideoProcessor
                    info = VideoProcessor().get_video_info(str(v_path)) or {}
                    src_dur = max(1.0, float(info.get('duration') or 0.0) or 0.0)
                except Exception:
                    src_dur = 60.0
                seg_count = max(3, min(12, int(src_dur // 8) or 3))
                seg_d = src_dur / seg_count
                for i in range(seg_count):
                    normalized_shots.append({
                        'id': ('fallback_shot_%d' % i),
                        'index': i,
                        'start_time': i * seg_d,
                        'end_time': (i + 1) * seg_d,
                        'duration': seg_d,
                        'score': 0.5,
                        'scene_type': 'neutral',
                        'description': '',
                        'source_video': str(v_path),
                    })

            if not normalized_voices:
                raise ValueError('配音段列表为空或文本全部无效，无法同步')

            # A scene boundary is only a coarse candidate.  Expand long scenes
            # into real source windows and assign one window to every narration
            # segment before the renderer receives the timeline.
            from backend.engine.storyboard_planner import StoryboardPlanner
            planned_shots = StoryboardPlanner().plan(normalized_shots, normalized_voices)
            logger.info(
                '🎬 Storyboard planned: %s narration segments from %s coarse shots',
                len(planned_shots), len(normalized_shots),
            )

            engine = PuppetSyncEngine()
            timeline = engine.match_shots_to_voices(
                planned_shots, normalized_voices, allow_reuse=False,
                insert_original_audio=insert_original_audio,
                original_clip_interval=original_clip_interval,
                original_clip_duration=original_clip_duration,
                original_audio_volume=original_audio_volume,
                target_duration_seconds=target_duration_seconds,
                original_audio_mode=original_audio_mode,
                original_audio_ratio=original_audio_ratio,
            )

            timeline_duration = round(sum(
                max(0.0, float(seg.get('final_duration', 0) or 0))
                for seg in timeline if isinstance(seg, dict)
            ), 3)
            try:
                normalized_target_duration = float(target_duration_seconds) if target_duration_seconds is not None else None
                if normalized_target_duration is not None and normalized_target_duration <= 0:
                    normalized_target_duration = None
            except (TypeError, ValueError):
                normalized_target_duration = None
            duration_tolerance_seconds = 0.35
            if normalized_target_duration is not None:
                logger.info(
                    '🎯 拟人化同步目标时长校验: 目标 %.2fs，时间线估算 %.2fs，差值 %.2fs',
                    normalized_target_duration, timeline_duration, timeline_duration - normalized_target_duration,
                )

            resolved_subtitle_path = ''
            if subtitle_path:
                candidate = Path(subtitle_path)
                if not candidate.is_absolute():
                    candidate = PROJECT_ROOT / candidate
                if candidate.exists() and candidate.is_file():
                    resolved_subtitle_path = str(candidate.resolve())
                else:
                    logger.warning('传入字幕文件不存在，改为按最终时间线生成: %s', subtitle_path)
            subtitle_count = 0
            if render and not resolved_subtitle_path:
                resolved_subtitle_path, subtitle_count = self._timeline_subtitle_srt(timeline)

            result = {
                'timeline': timeline,
                'clip_count': len(timeline),
                'original_audio_summary': engine.last_original_audio_summary,
                'video_path': str(v_path),
                'subtitle_path': resolved_subtitle_path,
                'subtitle_count': subtitle_count,
                'target_duration_seconds': normalized_target_duration,
                'timeline_duration': timeline_duration,
                'actual_duration_seconds': None,
                'duration_delta_seconds': round(timeline_duration - normalized_target_duration, 3) if normalized_target_duration is not None else None,
                'duration_within_tolerance': None,
                'duration_estimated': True,
                'duration_tolerance_seconds': duration_tolerance_seconds,
            }

            if render and timeline:
                out = engine.render_timeline(
                    video_path=str(v_path),
                    timeline=timeline,
                    output_path=output_path or None,
                    bgm_path=bgm_path or None,
                    subtitle_path=resolved_subtitle_path or None,
                )
                result['output_video'] = out
                result['output_url'] = '/' + str(Path(out).relative_to(PROJECT_ROOT)).replace('\\', '/')
                rendered_duration = _probe_duration(out)
                if rendered_duration > 0:
                    result['actual_duration_seconds'] = round(rendered_duration, 3)
                    result['duration_delta_seconds'] = round(rendered_duration - normalized_target_duration, 3) if normalized_target_duration is not None else None
                    result['duration_within_tolerance'] = (
                        abs(rendered_duration - normalized_target_duration) <= duration_tolerance_seconds
                        if normalized_target_duration is not None else None
                    )
                    result['duration_estimated'] = False
                else:
                    result['duration_probe_warning'] = '未能读取最终文件时长，以下时长仅为时间线估算'
                    result.setdefault('warnings', []).append(result['duration_probe_warning'])

            if project_id:
                try:
                    project = self.db_manager.get_project(project_id)
                    if project:
                        def as_dict(value):
                            if isinstance(value, dict):
                                return value
                            if isinstance(value, str):
                                parsed = json.loads(value) if value else {}
                                return parsed if isinstance(parsed, dict) else {}
                            return {}
                        config = as_dict(project.get('config'))
                        result_data = as_dict(project.get('result'))
                        workbench = as_dict(config.get('workbench'))
                        workbench.update({
                            'voice_segments': json.loads(json.dumps(voices, ensure_ascii=False, default=str)),
                            'shot_segmentation': {'shots': json.loads(json.dumps(shots, ensure_ascii=False, default=str))},
                            'puppet_sync': {
                                'timeline': json.loads(json.dumps(timeline, ensure_ascii=False, default=str)),
                                'original_audio_summary': json.loads(json.dumps(engine.last_original_audio_summary, ensure_ascii=False, default=str)),
                                'subtitle_path': resolved_subtitle_path,
                                'output_video': result.get('output_video', ''), 'output_url': result.get('output_url', ''),
                                'target_duration_seconds': result.get('target_duration_seconds'),
                                'timeline_duration': result.get('timeline_duration'),
                                'actual_duration_seconds': result.get('actual_duration_seconds'),
                                'duration_delta_seconds': result.get('duration_delta_seconds'),
                                'duration_within_tolerance': result.get('duration_within_tolerance'),
                                'duration_estimated': result.get('duration_estimated'),
                            },
                        })
                        config.update({
                            'video_path': str(v_path), 'target_duration_seconds': target_duration_seconds,
                            'original_audio_plan': {'enabled': bool(insert_original_audio), 'mode': original_audio_mode,
                                'target_ratio': original_audio_ratio, 'legacy_interval': original_clip_interval,
                                'legacy_clip_duration': original_clip_duration, 'volume': original_audio_volume},
                            'workbench': workbench,
                        })
                        result_data.update({'puppet_output_path': result.get('output_video', ''), 'puppet_output_url': result.get('output_url', '')})
                        self.db_manager.update_project(project_id, {'config': config, 'result': result_data})
                except Exception as persist_error:
                    warning = '拟人化同步结果保存到项目失败：%s' % persist_error
                    logger.warning(warning, exc_info=True)
                    result.setdefault('warnings', []).append(warning)

            logger.info(f'✅ 拟人化同步剪辑完成: {len(timeline)} 个片段')
            return result
        except Exception as e:
            logger.error(f'❗ 拟人化同步剪辑失败: {e}', exc_info=True)
            raise

    # ================================================================== #
    # 升级能力 3：导出剪映草稿（自动检测草稿目录）
    # ================================================================== #
    def export_jianying_draft(self,
                              project_id: str,
                              timeline: List[Dict],
                              video_path: str = '',
                              audio_paths: List[str] = None,
                              subtitle_text: str = '',
                              draft_dir: str = '',
                              bgm_path: str = '',
                              project_name: str = '',
                              flower_config: Optional[Dict] = None) -> Dict:
        """
        导出剪映草稿包（含视频轨道、TTS配音轨道、BGM轨道、字幕文字轨道）

        Args:
            project_id: 项目ID
            timeline: 拟人化同步时间轴
            video_path: 源视频路径
            audio_paths: 配音音频路径列表
            subtitle_text: 字幕文本
            draft_dir: 指定草稿目录（空则自动检测剪映草稿目录）
            bgm_path: 可选 BGM 路径
            project_name: 可选草稿项目名

        Returns:
            dict: 草稿包路径与信息
        """
        try:
            from backend.utils.jianying_detector import (
                detect_jianying_draft_dir, export_draft_package
            )

            # ============================================================
            # 兜底：timeline / audio_paths / video_path 缺失时，从项目 workbench / config 回填
            # ============================================================
            resolved_video = str(video_path or '').strip()
            resolved_timeline = list(timeline) if isinstance(timeline, list) else []
            resolved_audio_paths = list(audio_paths) if isinstance(audio_paths, list) else []
            resolved_bgm = str(bgm_path or '').strip()
            resolved_subtitle = str(subtitle_text or '').strip()
            resolved_project_name = str(project_name or '').strip()
            resolved_flower_config = dict(flower_config) if isinstance(flower_config, dict) else None

            project: Dict[str, Any] = {}
            project_config: Dict[str, Any] = {}
            try:
                project = self.db_manager.get_project(project_id) or {}
                raw_config = project.get('config')
                if isinstance(raw_config, str):
                    try:
                        project_config = json.loads(raw_config) if raw_config else {}
                    except Exception:
                        project_config = {}
                elif isinstance(raw_config, dict):
                    project_config = raw_config
            except Exception as get_err:
                logger.warning('导出剪映草稿读取项目失败（继续尝试）: %s', get_err)

            workbench: Dict[str, Any] = project_config.get('workbench') if isinstance(project_config, dict) else {}
            if not isinstance(workbench, dict):
                workbench = {}
            if resolved_flower_config is None:
                candidate_flower_config = project_config.get('flower_config') if isinstance(project_config, dict) else None
                if isinstance(candidate_flower_config, dict):
                    resolved_flower_config = dict(candidate_flower_config)
            # 1) 兜底 timeline
            if not resolved_timeline:
                puppet_sync = workbench.get('puppet_sync') or {}
                if isinstance(puppet_sync, dict):
                    candidate = puppet_sync.get('timeline')
                    if isinstance(candidate, list):
                        resolved_timeline = list(candidate)
                        logger.info('从 workbench.puppet_sync 回填 timeline: %s 段', len(resolved_timeline))
            # 2) 兜底 audio_paths
            if not resolved_audio_paths:
                voice_segs = workbench.get('voice_segments') or []
                if isinstance(voice_segs, list):
                    collected: List[str] = []
                    for v in voice_segs:
                        if not isinstance(v, dict):
                            continue
                        p = v.get('voice_path') or v.get('audio_path') or v.get('audio_url') or ''
                        p = str(p or '').strip()
                        if p:
                            collected.append(p)
                    resolved_audio_paths = collected
                    logger.info('从 workbench.voice_segments 回填 audio_paths: %s 条', len(resolved_audio_paths))
            # 3) 兜底 video_path
            if not resolved_video:
                for key in ('video_path', 'source_video_path', 'source_path'):
                    candidate = project_config.get(key) if isinstance(project_config, dict) else None
                    candidate = str(candidate or '').strip()
                    if candidate:
                        resolved_video = candidate
                        break
                if not resolved_video:
                    for seg in resolved_timeline:
                        if isinstance(seg, dict):
                            candidate = str(seg.get('source_video') or seg.get('video_path') or '').strip()
                            if candidate:
                                resolved_video = candidate
                                break
            # 4) 兜底 bgm_path
            if not resolved_bgm:
                candidate = project_config.get('bgm_path') if isinstance(project_config, dict) else None
                candidate = str(candidate or '').strip()
                if candidate:
                    resolved_bgm = candidate
            # 5) 兜底 subtitle_text
            if not resolved_subtitle:
                pieces = [str(seg.get('subtitle_text') or '').strip() for seg in resolved_timeline if isinstance(seg, dict)]
                pieces = [p for p in pieces if p]
                resolved_subtitle = '\n'.join(pieces)
                if not resolved_subtitle:
                    script_text = str(project_config.get('script') or '').strip() if isinstance(project_config, dict) else ''
                    if script_text:
                        resolved_subtitle = script_text
            # 6) 项目名
            if not resolved_project_name:
                pname = str((project or {}).get('name') or '').strip() if isinstance(project, dict) else ''
                if pname:
                    resolved_project_name = pname

            # 自动检测草稿目录
            if not draft_dir:
                draft_dir = detect_jianying_draft_dir()
                if not draft_dir:
                    logger.warning('⚠️ 未检测到剪映草稿目录，将生成项目内原生草稿目录')

            logger.info('📦 导出剪映草稿到: %s (timeline=%s, audios=%s)', draft_dir, len(resolved_timeline), len(resolved_audio_paths))

            result = export_draft_package(
                draft_dir=draft_dir,
                project_id=project_id,
                timeline=resolved_timeline,
                video_path=resolved_video,
                audio_paths=resolved_audio_paths,
                subtitle_text=resolved_subtitle,
                bgm_path=resolved_bgm,
                project_name=resolved_project_name,
                flower_config=resolved_flower_config,
            )

            # 同步写入项目 config.tracks / jianying_draft
            try:
                project = self.db_manager.get_project(project_id) or {}
                raw_config = project.get('config')
                if isinstance(raw_config, str):
                    project_config = json.loads(raw_config) if raw_config else {}
                elif isinstance(raw_config, dict):
                    project_config = raw_config
                else:
                    project_config = {}

                project_config['tracks'] = result.get('tracks', [])
                project_config.pop('jianying_draft', None)
                project_config['jianying_draft'] = {
                    key: result.get(key)
                    for key in ('native_jianying_project', 'draft_path', 'draft_root_path',
                                'draft_content_path', 'draft_meta_info_path', 'draft_name', 'warnings')
                }
                self.db_manager.update_project(project_id, {'config': project_config})
            except Exception as pe:
                logger.warning(f'⚠️ 写入项目草稿信息失败（不影响导出）: {pe}')

            logger.info(
                '%s: %s',
                '✅ 剪映原生草稿导出成功' if result.get('native_jianying_project') else '✅ 本地草稿包导出成功（剪映不会自动扫描）',
                result.get('draft_path'),
            )
            return result
        except Exception as e:
            logger.error(f'❗ 导出剪映草稿失败: {e}', exc_info=True)
            raise

    # ================================================================== #
    # 升级能力 4：从文稿生成配音段（供 puppet_sync 使用）
    # ================================================================== #
    @staticmethod
    def _sanitize_voice_paragraphs(paragraphs: List[Dict]) -> List[Dict]:
        cleaned: List[Dict] = []
        terminal_re = re.compile(r'[\u3002\uff01\uff1f!?;\uff1b]$')
        incomplete_tail_re = re.compile(r'[\uff0c\u3001:\uff1a\uff08(\u300a\u201c\"\']$')
        for paragraph in paragraphs:
            text = re.sub(r'\s+', ' ', str(paragraph.get('text') or '').strip())
            text = re.sub(r'(\.\.\.+|\u2026\u2026+)$', '', text).strip()
            if not text:
                continue
            if len(text) < 6 and terminal_re.search(text):
                if cleaned:
                    cleaned[-1]['text'] = (cleaned[-1]['text'] + text).strip()
                continue
            previous_text = str(cleaned[-1].get('text', '')) if cleaned else ''
            if cleaned and (len(text) < 10 or incomplete_tail_re.search(previous_text) or not terminal_re.search(previous_text)):
                cleaned[-1]['text'] = (previous_text + text).strip()
                continue
            item = dict(paragraph)
            item['text'] = text
            cleaned.append(item)
        return cleaned

    @staticmethod
    def _normalize_voice_config(voice_config: Optional[Dict]) -> Dict:
        """把前端倍率统一转换为 TTS 引擎可识别的参数。"""
        config = dict(voice_config or {})
        engine = TTSEngine._normalize_engine_name(config.get('engine'))

        def percent(value, default=1.0) -> str:
            if isinstance(value, str) and value.strip().endswith('%'):
                return TTSEngine._normalize_edge_percent(value)
            try:
                multiplier = float(value)
                if multiplier != multiplier or multiplier in (float('inf'), float('-inf')):
                    multiplier = default
            except (TypeError, ValueError):
                multiplier = default
            return TTSEngine._normalize_edge_percent((multiplier - 1.0) * 100.0)

        config['engine'] = engine
        policy = str(config.get('fallback_policy') or 'auto_fallback').strip().lower()
        config['fallback_policy'] = policy if policy in ('auto_fallback', 'edge_only') else 'auto_fallback'
        config['rate'] = percent(config.get('rate'), 1.0)
        config['volume'] = percent(config.get('volume'), 1.0)
        config['pitch'] = (
            TTSEngine.normalize_edge_pitch(config.get('pitch'))
            if engine == 'edge-tts' else TTSEngine.normalize_pitch(config.get('pitch'))
        )
        return config

    def generate_voices_from_script(self,
                                    script: Any,
                                    voice_config: Dict,
                                    segments: Optional[List[Dict]] = None,
                                    with_details: bool = False) -> Any:
        """根据文稿或指定分段生成配音；with_details=False 时保持旧列表返回。"""
        voice_config = self._normalize_voice_config(voice_config)
        voices: List[Dict] = []
        failed_items: List[Dict] = []
        out_dir = PROJECT_ROOT / 'output' / 'commentary_voice'
        out_dir.mkdir(parents=True, exist_ok=True)
        voice_id = voice_config.get('voice_id') or voice_config.get('voice') or 'zh-CN-XiaoxiaoNeural'
        engine = (voice_config.get('engine') or '').strip().lower()
        engine = {'azure-tts': 'azure', 'azure_tts': 'azure', 'edge': 'edge-tts', 'edgetts': 'edge-tts',
                  'indextts': 'indextts2', 'index_tts': 'indextts2', 'index-tts2': 'indextts2'}.get(engine, engine)

        if isinstance(segments, list) and segments:
            paragraphs = [
                {'id': str(item.get('id') or uuid.uuid4().hex), 'index': item.get('index', pos),
                 'text': str(item.get('text') or '').strip()}
                for pos, item in enumerate(segments) if isinstance(item, dict) and str(item.get('text') or '').strip()
            ]
        elif isinstance(script, str):
            paragraphs = [{'id': uuid.uuid4().hex, 'index': i, 'text': line.strip()}
                          for i, line in enumerate(script.splitlines()) if line.strip()]
        elif isinstance(script, dict):
            paragraphs = [
                {'id': str(p.get('id') or uuid.uuid4().hex), 'index': p.get('index', i),
                 'text': str(p.get('text') or '').strip()}
                for i, p in enumerate(script.get('paragraphs', [])) if isinstance(p, dict) and str(p.get('text') or '').strip()
            ]
        else:
            raise ValueError(f'script 参数类型无效：期望 str 或 dict，得到 {type(script).__name__}')

        original_count = len(paragraphs)
        paragraphs = self._sanitize_voice_paragraphs(paragraphs)
        if not paragraphs:
            raise ValueError('script does not contain any complete voice segment after cleanup')
        if len(paragraphs) != original_count:
            logger.info('voice paragraph cleanup merged/dropped segments: %s -> %s', original_count, len(paragraphs))

        def audio_url(path: Path) -> str:
            try:
                relative = path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
            except (ValueError, OSError):
                return ''
            if relative.startswith('output/commentary_voice/'):
                return '/' + relative
            if relative.startswith('temp/outputs/local_voice_clone/'):
                return '/' + relative
            return ''

        def voice_item(paragraph: Dict, path: Path, duration: float,
                       engine_used: Optional[str] = None, fallback_reason: str = '') -> Dict:
            url = audio_url(path)
            duration = float(duration or 0.0)
            if duration <= 0:
                duration = max(0.1, len(paragraph['text']) / 4.0)
            actual_engine = engine_used or engine or self.tts_engine.default_engine
            fallback_used = bool(fallback_reason and actual_engine != engine)
            return {'id': paragraph['id'], 'index': paragraph['index'], 'text': paragraph['text'],
                    'voice_path': str(path), 'audio_path': str(path), 'audio_url': url,
                    'duration': duration, 'duration_seconds': duration, 'status': 'ready', 'error': None, 'reason': None,
                    'engine': actual_engine, 'engine_requested': engine or self.tts_engine.default_engine,
                    'engine_used': actual_engine, 'fallback_used': fallback_used,
                    'fallback_reason': fallback_reason if fallback_used else None,
                    'voice': voice_id, 'rate': voice_config['rate'], 'volume': voice_config['volume'],
                    'pitch': voice_config['pitch'], 'fallback_policy': voice_config['fallback_policy']}

        def failed(paragraph: Dict, reason: str = 'TTS 合成失败') -> None:
            engine_name = engine or self.tts_engine.default_engine
            reason = str(reason or 'TTS 合成失败')
            if not reason.startswith(f'[{engine_name}]'):
                reason = f'[{engine_name}] {reason}'
            failed_items.append({'id': paragraph['id'], 'index': paragraph['index'], 'text': paragraph['text'],
                                 'voice_path': '', 'audio_path': '', 'audio_url': '',
                                 'duration': 0.0, 'duration_seconds': 0.0, 'status': 'failed',
                                 'error': reason, 'reason': reason,
                                 'engine': engine or self.tts_engine.default_engine,
                                 'engine_requested': engine or self.tts_engine.default_engine,
                                 'engine_used': None, 'fallback_used': False, 'fallback_reason': None,
                                 'fallback_policy': voice_config['fallback_policy'], 'voice': voice_id,
                                 'rate': voice_config['rate'], 'volume': voice_config['volume'], 'pitch': voice_config['pitch']})

        def finalize():
            all_segments = voices + failed_items
            if not with_details:
                return voices
            fallback_count = sum(1 for item in voices if item.get('fallback_used'))
            return {'voices': all_segments, 'segments': all_segments, 'total_count': len(paragraphs),
                    'success_count': len(voices), 'failed_count': len(failed_items),
                    'fallback_count': fallback_count, 'failed_items': failed_items,
                    'total_duration_seconds': sum(float(item.get('duration_seconds') or 0) for item in voices)}

        if engine == 'indextts2':
            reference_audio = voice_config.get('reference_audio') or ''
            if not reference_audio:
                raise ValueError('IndexTTS2 克隆语音必须提供 reference_audio 参考音频路径')
            if not bool(voice_config.get('consent', False)):
                raise ValueError('使用克隆语音必须明确确认已获得参考音频权利人的授权（consent=true）')
            from backend.services.local_voice_clone_service import LocalVoiceCloneError, local_voice_clone_service
            status = local_voice_clone_service.status()
            if not status.get('ready'):
                raise RuntimeError(f'IndexTTS2 引擎未就绪: {status.get("reason") or "请检查环境和模型文件"}')
            for paragraph in paragraphs:
                try:
                    result = local_voice_clone_service.generate(text=paragraph['text'], reference_audio=reference_audio)
                    rel_path = result.get('output_path', '')
                    path = PROJECT_ROOT / rel_path if rel_path else None
                    if path and path.is_file() and path.stat().st_size >= 1024:
                        voices.append(voice_item(paragraph, path, self._probe_audio_duration(path)))
                    else:
                        failed(paragraph)
                except LocalVoiceCloneError:
                    failed(paragraph)
                except Exception:
                    logger.exception('IndexTTS2 配音失败: %s', paragraph['index'])
                    failed(paragraph)
            return finalize()

        if engine == 'volcano':
            volcano_voice_id = voice_config.get('voice_id') or voice_config.get('volcano_voice_id') or ''
            if not volcano_voice_id:
                raise ValueError('火山引擎 TTS 必须提供 voice_id（音色ID）')
            from backend.services.voiceover_service import VoiceoverService
            vs = getattr(self, '_voiceover_service', None) or VoiceoverService(db_manager=None, socketio=None)
            self._voiceover_service = vs
            for paragraph in paragraphs:
                suffix = uuid.uuid4().hex[:8]
                voice_file = out_dir / f"voice_{paragraph['index']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{suffix}.mp3"
                try:
                    result = vs.generate_clone_voiceover(text=paragraph['text'], reference_audio=voice_config.get('reference_audio') or '', engine='volcano', voice_config={'voice_id': volcano_voice_id, 'speed': voice_config.get('rate', '+0%'), 'volume': voice_config.get('volume', '+0%'), 'pitch': voice_config.get('pitch', 0)}, output_dir=str(voice_file.parent))
                    result_path = Path((result or {}).get('output_path') or (result or {}).get('audio_path') or '')
                    if result_path.exists() and result_path != voice_file:
                        try: shutil.move(str(result_path), str(voice_file))
                        except Exception: voice_file = result_path
                    if voice_file.is_file() and voice_file.stat().st_size >= 1024:
                        voices.append(voice_item(paragraph, voice_file, self._probe_audio_duration(voice_file)))
                    else:
                        failed(paragraph, 'TTS 未生成有效音频文件')
                except Exception:
                    logger.exception('火山引擎配音失败: %s', paragraph['index'])
                    failed(paragraph, 'TTS 合成失败')
            return finalize()

        total_paragraphs = len(paragraphs)
        for position, paragraph in enumerate(paragraphs, 1):
            suffix = uuid.uuid4().hex[:8]
            voice_file = out_dir / f"voice_{paragraph['index']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{suffix}.mp3"
            logger.info('配音段开始：第 %s/%s 段（index=%s）', position, total_paragraphs, paragraph['index'])
            try:
                requested_engine = engine or self.tts_engine.default_engine
                ok = self.tts_engine.synthesize(
                    text=paragraph['text'], output_path=str(voice_file), engine=requested_engine,
                    voice=voice_id, rate=voice_config.get('rate', '+0%'),
                    volume=voice_config.get('volume', '+0%'), pitch=voice_config.get('pitch', 0),
                )
                call_error = self.tts_engine.last_error
                used_engine = requested_engine
                fallback_reason = ''
                valid_audio = ok and self.tts_engine._validate_audio_file(voice_file)
                if (not valid_audio and requested_engine == 'edge-tts'
                        and voice_config['fallback_policy'] == 'auto_fallback'):
                    fallback_reason = call_error or 'Edge TTS 未返回有效音频（已完成 3 次重试）'
                    candidates = []
                    if self.tts_engine.has_compatible_pyttsx3_voice(voice_id):
                        candidates.append('pyttsx3')
                    if 'gtts' in self.tts_engine.available_engines:
                        candidates.append('gtts')
                    for candidate in candidates:
                        self.tts_engine._remove_partial_output(str(voice_file))
                        logger.warning('配音段 Edge 失败，尝试透明回退：段=%s，引擎=%s', paragraph['index'], candidate)
                        ok = self.tts_engine.synthesize(
                            text=paragraph['text'], output_path=str(voice_file), engine=candidate,
                            voice=voice_id, rate=voice_config.get('rate', '+0%'),
                            volume=voice_config.get('volume', '+0%'), pitch=voice_config.get('pitch', 0),
                        )
                        if ok and self.tts_engine._validate_audio_file(voice_file):
                            used_engine = candidate
                            valid_audio = True
                            break
                        call_error = self.tts_engine.last_error or call_error
                    if not valid_audio:
                        fallback_reason = ''
                if valid_audio:
                    voices.append(voice_item(
                        paragraph, voice_file, self._probe_audio_duration(voice_file),
                        engine_used=used_engine, fallback_reason=fallback_reason,
                    ))
                    if used_engine != requested_engine:
                        logger.warning('配音段已回退成功：第 %s/%s 段，%s → %s', position, total_paragraphs, requested_engine, used_engine)
                    else:
                        logger.info('配音段成功：第 %s/%s 段（index=%s）', position, total_paragraphs, paragraph['index'])
                else:
                    self.tts_engine._remove_partial_output(str(voice_file))
                    if requested_engine == 'edge-tts' and voice_config['fallback_policy'] == 'edge_only':
                        call_error = f'{call_error or "Edge TTS 未生成有效音频"}；当前为 edge_only，未启用回退。可切换 auto_fallback，或检查本地中文语音。'
                    elif requested_engine == 'edge-tts' and voice_config['fallback_policy'] == 'auto_fallback':
                        call_error = f'{call_error or "Edge TTS 未生成有效音频"}；本地 Windows SAPI/gTTS 回退均不可用或未生成有效非静音音频，请检查本地中文语音或切换 edge_only。'
                    failed(paragraph, call_error or 'TTS 未生成有效音频文件')
                    logger.warning('配音段失败：第 %s/%s 段（index=%s）：%s；继续下一段',
                                   position, total_paragraphs, paragraph['index'], call_error)
            except Exception as error:
                reason = self.tts_engine.last_error or f'TTS 合成失败：{error}'
                failed(paragraph, reason)
                logger.warning('配音段异常：第 %s/%s 段（index=%s）：%s；继续下一段',
                               position, total_paragraphs, paragraph['index'], reason)
        return finalize()

    @staticmethod
    def _probe_audio_duration(path: Path) -> float:
        """使用 ffprobe 读取音频时长"""
        try:
            import subprocess as sp
            cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                str(path)
            ]
            result = sp.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0.0
