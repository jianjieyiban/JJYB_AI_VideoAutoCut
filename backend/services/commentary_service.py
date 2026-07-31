# -*- coding: utf-8 -*-
"""
原创解说剪辑服务 - 完整AI流程
视频画面分析 → 文案生成 → 智能配音 → 三同步
"""

import logging
from typing import Dict, Any, Optional, List
import os
import json
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
        """处理原创解说剪辑。"""
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
                        logger.info('目标时长 %s 大于源视频时长 %s，已在后端自动夹紧', target_sec, source_sec)
                        target_sec = source_sec
                    config['target_duration_seconds'] = target_sec
            except Exception as e:
                logger.warning(f'目标时长兜底校验失败: {e}')

            task_id = self.task_service.create_commentary_task(project_id=project_id, config=config)
            logger.info(f'✅ 原创解说任务已创建: {task_id}')
            return task_id
        except Exception as e:
            logger.error(f'❗ 处理原创解说失败: {e}', exc_info=True)
            raise

    def auto_clip_video(self, video_path: str, script: Dict) -> List[Dict]:
        """根据文稿自动剪辑视频。"""
        try:
            logger.info('✂️ 自动剪辑视频...')
            clips = []
            for i, paragraph in enumerate(script.get('paragraphs', [])):
                clips.append({'index': i, 'start_time': paragraph['time'], 'end_time': paragraph['time'] + paragraph['duration'], 'duration': paragraph['duration'], 'text': paragraph['text']})
            logger.info(f'✅ 自动剪辑完成: {len(clips)}个片段')
            return clips
        except Exception as e:
            logger.error(f'❗ 自动剪辑失败: {e}', exc_info=True)
            raise

    def add_voice_over(self, clips: List[Dict], voice_config: Dict) -> List[Dict]:
        """添加配音。"""
        try:
            logger.info('🎙️ 添加配音...')
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
                ok = self.tts_engine.synthesize(text=text, output_path=str(voice_file), engine=engine, voice=voice_id)
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
        """添加背景音乐。"""
        try:
            logger.info('🎵 添加背景音乐...')
            if not video_path or not bgm_path:
                raise ValueError('video_path 和 bgm_path 不能为空')
            v_path = Path(video_path)
            if not v_path.is_absolute(): v_path = PROJECT_ROOT / video_path
            a_path = Path(bgm_path)
            if not a_path.is_absolute(): a_path = PROJECT_ROOT / bgm_path
            if not v_path.exists(): raise FileNotFoundError(f'视频文件不存在: {v_path}')
            if not a_path.exists(): raise FileNotFoundError(f'背景音乐文件不存在: {a_path}')
            out_dir = PROJECT_ROOT / 'output' / 'videos'
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = out_dir / f"with_bgm_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
            logger.info(f'🎵 为视频叠加BGM: video={v_path}, bgm={a_path}, volume={volume}')
            ok = self.video_processor.add_audio_to_video(video_path=str(v_path), audio_path=str(a_path), output_path=str(output_path), replace=False)
            if not ok: raise RuntimeError('叠加背景音乐失败')
            logger.info(f'✅ 背景音乐添加完成: {output_path}')
            return str(output_path)
        except Exception as e:
            logger.error(f'❗ 添加背景音乐失败: {e}', exc_info=True)
            raise

    def generate_subtitles(self, script: Dict) -> str:
        """生成字幕文件。"""
        try:
            logger.info('📝 生成字幕...')
            srt_path = f"output/subtitles/subtitle_{datetime.now().strftime('%Y%m%d%H%M%S')}.srt"
            Path(srt_path).parent.mkdir(parents=True, exist_ok=True)
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, paragraph in enumerate(script.get('paragraphs', []), 1):
                    f.write(f"{i}\n{self._format_srt_time(paragraph['time'])} --> {self._format_srt_time(paragraph['time'] + paragraph['duration'])}\n{paragraph['text']}\n\n")
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
