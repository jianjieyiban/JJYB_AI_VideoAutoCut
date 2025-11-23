#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : auto_clip_controller.py
@Author : AI Assistant
@Date   : 2025-11-10
@Desc   : 自动剪辑流程控制器
          整合VideoAnalyzer、ScriptGenerator、TTSEngine、VideoClipper、VideoComposer
          实现完整的视频自动剪辑工作流
"""

import os
import json
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime
from loguru import logger

# 导入核心引擎模块
try:
    from .video_analyzer import VideoAnalyzer
    from .script_generator import ScriptGenerator
    from .video_clipper import VideoClipper
    from .video_composer import VideoComposer
    from .tts_engine import TTSEngine
    from .subtitle_generator import SubtitleGenerator
    from .audio_normalizer import AudioNormalizer
    from .audio_processor import AudioProcessor
except ImportError:
    # 兼容直接运行的情况
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from video_analyzer import VideoAnalyzer
    from script_generator import ScriptGenerator
    from video_clipper import VideoClipper
    from video_composer import VideoComposer
    from tts_engine import TTSEngine
    from subtitle_generator import SubtitleGenerator
    from audio_normalizer import AudioNormalizer
    from audio_processor import AudioProcessor


class AutoClipController:
    """
    自动剪辑流程控制器
    
    完整工作流程：
    1. 视频分析阶段 → frame_analysis.json
    2. 文案生成阶段 → narration_script.json  
    3. 配音合成阶段 → audio_files/*.mp3
    4. 视频剪辑阶段 → video_clips/*.mp4
    5. 素材合成阶段 → final_output.mp4
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化控制器
        
        Args:
            config: 配置字典
                {
                    # LLM配置
                    "llm_api_key": "sk-xxx",
                    "llm_base_url": "https://api.openai.com/v1",
                    "llm_model": "gpt-4-vision-preview",
                    "llm_temperature": 0.7,
                    
                    # TTS配置
                    "tts_provider": "pyttsx3",
                    "tts_voice": "zh-CN-XiaoxiaoNeural",
                    "tts_rate": 1.0,
                    
                    # 视频分析配置
                    "frame_interval": 3.0,  # 帧提取间隔（秒）
                    "max_frames": 100,      # 最大帧数
                    "batch_size": 5,        # 批次大小
                    
                    # 输出配置
                    "output_dir": "./output",
                    "temp_dir": "./temp",
                    
                    # 合成配置
                    "voice_volume": 1.0,
                    "bgm_volume": 0.3,
                    "subtitle_enabled": True,
                    "fps": 30
                }
        """
        self.config = config
        
        # 创建工作目录
        self.output_dir = Path(config.get('output_dir', './output'))
        self.temp_dir = Path(config.get('temp_dir', './temp'))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("初始化AutoClipController...")
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"临时目录: {self.temp_dir}")
        
        # 初始化核心模块
        self._init_modules()
        
        logger.success("✅ AutoClipController初始化完成")
    
    def _init_modules(self):
        """初始化核心模块"""
        try:
            # 1. 视频分析器
            self.analyzer = VideoAnalyzer(output_dir=str(self.temp_dir / 'analysis'))
            logger.info("✅ VideoAnalyzer初始化完成")
            
            # 2. 文案生成器
            self.script_generator = ScriptGenerator(
                api_key=self.config.get('llm_api_key'),
                model=self.config.get('llm_model', 'gpt-4'),
                base_url=self.config.get('llm_base_url')
            )
            logger.info("✅ ScriptGenerator初始化完成")
            
            # 3. TTS引擎
            self.tts_engine = TTSEngine()
            logger.info("✅ TTSEngine初始化完成")
            
            # 4. 视频剪辑器
            self.clipper = VideoClipper()
            logger.info("✅ VideoClipper初始化完成")
            
            # 5. 视频合成器（启用智能音量）
            use_smart_volume = self.config.get('use_smart_volume', True)
            self.composer = VideoComposer(use_smart_volume=use_smart_volume)
            logger.info("✅ VideoComposer初始化完成")
            
            # 6. 字幕生成器
            self.subtitle_generator = SubtitleGenerator()
            logger.info("✅ SubtitleGenerator初始化完成")
            
            # 7. 音频规范化器
            self.audio_normalizer = AudioNormalizer()
            logger.info("✅ AudioNormalizer初始化完成")

            # 8. 音频处理器（用于拼接/合并配音音频）
            self.audio_processor = AudioProcessor()
            logger.info("✅ AudioProcessor初始化完成")
            logger.info("✅ AudioNormalizer初始化完成")
            
        except Exception as e:
            logger.error(f"❌ 模块初始化失败: {e}")
            raise
    
    async def auto_clip_workflow(
        self,
        video_path: str,
        bgm_path: Optional[str] = None,
        output_filename: Optional[str] = None,
        progress_callback: Optional[callable] = None
    ) -> str:
        """
        完整自动剪辑工作流（异步）
        
        Args:
            video_path: 输入视频路径
            bgm_path: 背景音乐路径（可选）
            output_filename: 输出文件名（可选）
            progress_callback: 进度回调 callback(step, total, message)
        
        Returns:
            最终输出视频路径
        """
        logger.info("=" * 60)
        logger.info("🎬 开始视频自动剪辑工作流")
        logger.info("=" * 60)
        
        total_steps = 5
        
        try:
            # 步骤1: 视频分析
            if progress_callback:
                progress_callback(1, total_steps, "分析视频内容...")
            
            frame_analysis_json = await self._step1_analyze_video(video_path)
            
            # 步骤2: 生成文案
            if progress_callback:
                progress_callback(2, total_steps, "AI生成解说文案...")
            
            narration_script = await self._step2_generate_script(frame_analysis_json)
            
            # 步骤3: 配音合成
            if progress_callback:
                progress_callback(3, total_steps, "生成配音音频...")
            
            audio_files = await self._step3_generate_voiceover(narration_script)
            
            # 步骤4: 视频剪辑
            if progress_callback:
                progress_callback(4, total_steps, "智能剪辑视频...")
            
            video_clips = await self._step4_clip_videos(video_path, narration_script)
            
            # 步骤5: 素材合成
            if progress_callback:
                progress_callback(5, total_steps, "合成最终视频...")
            
            final_output = await self._step5_compose_final_video(
                video_clips,
                audio_files,
                bgm_path,
                output_filename,
                narration_script  # 传递文案用于生成字幕
            )
            
            logger.info("=" * 60)
            logger.success(f"🎉 自动剪辑完成！")
            logger.success(f"输出文件: {final_output}")
            logger.info("=" * 60)
            
            return final_output
            
        except Exception as e:
            logger.error(f"❌ 自动剪辑工作流失败: {e}")
            raise
    
    async def _step1_analyze_video(self, video_path: str) -> str:
        """步骤1: 视频分析"""
        logger.info("📊 步骤1/5: 分析视频内容")
        
        # 提取关键帧
        key_frames = self.analyzer.extract_key_frames(
            video_path=video_path,
            interval_seconds=self.config.get('frame_interval', 3.0),
            max_frames=self.config.get('max_frames', 100)
        )
        
        # AI分析
        analysis_result = self.analyzer.analyze_frames_with_llm(
            key_frames=key_frames,
            llm_api_key=self.config['llm_api_key'],
            llm_base_url=self.config['llm_base_url'],
            llm_model=self.config['llm_model'],
            batch_size=self.config.get('batch_size', 5)
        )
        
        # 导出结果
        json_path = self.analyzer.export_analysis_json(analysis_result)
        
        logger.success(f"✅ 视频分析完成: {json_path}")
        return json_path
    
    async def _step2_generate_script(self, frame_analysis_json: str) -> Dict:
        """步骤2: 生成文案（支持钩子类型）"""
        logger.info("✍️  步骤2/5: AI生成解说文案")
        
        # 读取分析结果
        with open(frame_analysis_json, 'r', encoding='utf-8') as f:
            analysis_data = json.load(f)
        
        # 获取配置中的钩子类型
        hook_type = self.config.get('hook_type', 'suspense')
        use_viral_prompts = self.config.get('use_viral_prompts', True)
        
        # 使用ScriptGenerator生成文案
        vision_analysis = self._convert_to_vision_analysis(analysis_data)
        
        script_result = self.script_generator.generate_script(
            vision_analysis=vision_analysis,
            hook_type=hook_type,
            use_viral_prompts=use_viral_prompts,
            custom_prompt=self.config.get('custom_prompt')
        )
        
        # 转换为narration_script格式
        narration_script = {
            'title': script_result.get('title', '精彩视频解说'),
            'narrations': []
        }
        
        for segment in script_result.get('segments', []):
            narration_script['narrations'].append({
                'time_range': f"{segment['start_time']:.1f}s-{segment['end_time']:.1f}s",
                'text': segment['text'],
                'duration': segment['end_time'] - segment['start_time']
            })
        
        # 保存文案
        script_path = self.temp_dir / 'narration_script.json'
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(narration_script, f, ensure_ascii=False, indent=2)
        
        logger.success(f"✅ 文案生成完成: {script_path}")
        return narration_script
    
    def _convert_to_vision_analysis(self, analysis_data: Dict) -> Dict:
        """将帧分析数据转换为ScriptGenerator需要的格式"""
        scenes = []
        descriptions = []
        
        for i, summary in enumerate(analysis_data.get('overall_activity_summaries', [])):
            time_range = summary.get('time_range', '00:00:00-00:00:05')
            start_str, end_str = time_range.split('-')
            
            # 简单的时间转换（假设格式为HH:MM:SS）
            def time_to_seconds(t_str):
                parts = t_str.strip().split(':')
                if len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                return 0
            
            start_time = time_to_seconds(start_str)
            end_time = time_to_seconds(end_str)
            
            scenes.append({
                'id': i,
                'start_time': start_time,
                'end_time': end_time,
                'duration': end_time - start_time
            })
            
            descriptions.append({
                'description': summary.get('summary', '精彩内容')
            })
        
        return {
            'scenes': scenes,
            'descriptions': descriptions
        }
    
    async def _step3_generate_voiceover(self, narration_script: Dict) -> List[Dict]:
        """步骤3: 配音合成"""
        logger.info("🎙️ 步骤3/5: 生成配音音频")
        
        audio_dir = self.temp_dir / 'audio'
        audio_dir.mkdir(exist_ok=True)
        
        audio_files = []
        narrations = narration_script.get('narrations', [])
        
        for i, narration in enumerate(narrations):
            text = narration['text']
            time_range = narration.get('time_range', '')
            
            audio_filename = f"audio_{i:03d}.mp3"
            audio_path = audio_dir / audio_filename
            
            # 生成音频（使用统一TTSEngine接口）
            if not text.strip():
                logger.warning(f"  ⚠️ 第{i+1}条文案为空，跳过音频生成")
                continue

            logger.info(f"  生成音频 {i+1}/{len(narrations)}: {audio_filename}")
            ok = self.tts_engine.synthesize(
                text=text,
                output_path=str(audio_path),
                engine=None,
                voice=self.config.get('tts_voice', 'zh-CN-XiaoxiaoNeural')
            )
            if not ok or not audio_path.exists():
                logger.error(f"  ❗ 音频生成失败: {audio_filename}")
                continue

            # 可选：进行响度标准化，避免不同句子音量差异过大
            try:
                normalized_path = audio_dir / f"audio_{i:03d}_norm.mp3"
                if self.audio_normalizer.normalize_audio_lufs(str(audio_path), str(normalized_path)):
                    audio_path = normalized_path
            except Exception as ne:
                logger.warning(f"  ⚠️ 音频标准化失败（忽略）: {ne}")
            
            audio_files.append({
                'audio_path': str(audio_path),
                'time_range': time_range,
                'text': text
            })
        
        logger.success(f"✅ 配音合成完成，共{len(audio_files)}个音频")
        return audio_files
    
    async def _step4_clip_videos(
        self,
        video_path: str,
        narration_script: Dict
    ) -> List[str]:
        """步骤4: 视频剪辑"""
        logger.info("✂️  步骤4/5: 智能剪辑视频")
        
        clips_dir = self.temp_dir / 'clips'
        clips_dir.mkdir(exist_ok=True)
        
        # 根据文案时间戳剪辑视频
        clip_list = []
        for i, narration in enumerate(narration_script.get('narrations', [])):
            time_range = narration.get('time_range', '00:00:00-00:00:05')
            start_time, end_time = time_range.split('-')
            
            clip_list.append({
                'start': start_time.strip(),
                'end': end_time.strip(),
                'name': f'clip_{i:03d}'
            })
        
        # 批量剪辑
        video_clips = self.clipper.batch_clip_videos(
            input_video=video_path,
            clip_list=clip_list,
            output_dir=str(clips_dir)
        )
        
        logger.success(f"✅ 视频剪辑完成，共{len(video_clips)}个片段")
        return video_clips
    
    async def _step5_compose_final_video(
        self,
        video_clips: List[str],
        audio_files: List[Dict],
        bgm_path: Optional[str],
        output_filename: Optional[str],
        narration_script: Optional[Dict] = None
    ) -> str:
        """步骤5: 合成最终视频（含字幕生成）"""
        logger.info("🎞️ 步骤5/5: 合成最终视频")
        
        # 1. 先合并所有视频片段
        merged_video = self.temp_dir / 'merged_video.mp4'
        if len(video_clips) > 1:
            self.clipper.merge_video_clips(
                clip_paths=video_clips,
                output_video=str(merged_video)
            )
        else:
            merged_video = Path(video_clips[0])
        
        # 2. 合并所有音频
        merged_audio = self.temp_dir / 'merged_audio.mp3'
        valid_audio_paths = [Path(a['audio_path']) for a in audio_files if a.get('audio_path')]
        valid_audio_paths = [p for p in valid_audio_paths if p.exists()]
        if not valid_audio_paths:
            logger.warning("⚠️ 未找到可用的配音音频，跳过音频合并，使用静音占位")
        else:
            try:
                if len(valid_audio_paths) == 1:
                    # 单个音频，直接转换/复制为目标文件
                    ok_merge = self.audio_processor.convert_format(
                        input_path=str(valid_audio_paths[0]),
                        output_path=str(merged_audio),
                        format='mp3'
                    )
                else:
                    ok_merge = self.audio_processor.merge_audios(
                        [str(p) for p in valid_audio_paths],
                        str(merged_audio)
                    )

                if not ok_merge or not merged_audio.exists():
                    raise RuntimeError("音频合并失败")
                logger.success(f"✅ 配音音频合并完成: {merged_audio}")
            except Exception as me:
                logger.error(f"❌ 配音音频合并失败，将退回使用第一段音频: {me}")
                merged_audio = valid_audio_paths[0]
        
        # 3. 生成字幕文件（如果启用）
        subtitle_path = None
        if self.config.get('subtitle_enabled', True) and narration_script:
            try:
                logger.info("📝 生成SRT字幕...")
                subtitle_path = self.temp_dir / 'subtitle.srt'
                self.subtitle_generator.generate_srt_from_script(
                    narration_script,
                    str(subtitle_path)
                )
                logger.success(f"✅ 字幕生成完成: {subtitle_path}")
            except Exception as e:
                logger.error(f"❌ 字幕生成失败: {e}")
                subtitle_path = None
        
        # 4. 生成最终输出文件名
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"auto_clip_{timestamp}.mp4"
        
        final_output = self.output_dir / output_filename
        
        # 5. 合成所有素材
        options = {
            'voice_volume': self.config.get('voice_volume', 1.0),
            'bgm_volume': self.config.get('bgm_volume', 0.3),
            'subtitle_enabled': bool(subtitle_path),
            'subtitle_font_size': self.config.get('subtitle_font_size', 40),
            'subtitle_position': self.config.get('subtitle_position', 'bottom'),
            'fps': self.config.get('fps', 30),
            'threads': 2
        }
        
        self.composer.merge_materials(
            video_path=str(merged_video),
            audio_path=str(merged_audio),
            output_path=str(final_output),
            subtitle_path=str(subtitle_path) if subtitle_path else None,
            bgm_path=bgm_path,
            options=options
        )
        
        logger.success(f"✅ 最终视频合成完成: {final_output}")
        return str(final_output)
    
    def _convert_analysis_to_markdown(self, analysis_data: Dict) -> str:
        """将视频分析结果转换为Markdown格式"""
        markdown = "# 视频内容分析\n\n"
        
        for i, summary in enumerate(analysis_data.get('overall_activity_summaries', [])):
            time_range = summary.get('time_range', '')
            summary_text = summary.get('summary', '')
            
            markdown += f"## 片段 {i+1}\n"
            markdown += f"- 时间范围：{time_range}\n"
            markdown += f"- 片段描述：{summary_text}\n"
            markdown += "- 详细描述：\n"
            
            # 添加对应批次的帧观察
            batch_frames = [
                f for f in analysis_data.get('frame_observations', [])
                if f.get('batch_index') == summary.get('batch_index')
            ]
            
            for frame in batch_frames:
                timestamp = frame.get('timestamp', '')
                observation = frame.get('observation', '')
                markdown += f"  - {timestamp}: {observation}\n"
            
            markdown += "\n"
        
        return markdown


# 便捷使用函数
async def auto_clip_video(
    video_path: str,
    config: Dict[str, Any],
    bgm_path: Optional[str] = None,
    output_filename: Optional[str] = None,
    progress_callback: Optional[callable] = None
) -> str:
    """
    一键自动剪辑视频
    
    Args:
        video_path: 输入视频路径
        config: 配置字典
        bgm_path: BGM路径（可选）
        output_filename: 输出文件名（可选）
        progress_callback: 进度回调（可选）
    
    Returns:
        最终输出视频路径
    """
    controller = AutoClipController(config)
    return await controller.auto_clip_workflow(
        video_path=video_path,
        bgm_path=bgm_path,
        output_filename=output_filename,
        progress_callback=progress_callback
    )


if __name__ == '__main__':
    # 测试代码
    test_config = {
        'llm_api_key': 'sk-xxx',
        'llm_base_url': 'https://api.openai.com/v1',
        'llm_model': 'gpt-4-vision-preview',
        'tts_provider': 'pyttsx3',
        'tts_voice': 'zh-CN-XiaoxiaoNeural',
        'output_dir': './output',
        'temp_dir': './temp'
    }
    
    test_video = "test_video.mp4"
    
    if os.path.exists(test_video):
        def progress(step, total, message):
            print(f"[{step}/{total}] {message}")
        
        result = asyncio.run(
            auto_clip_video(
                video_path=test_video,
                config=test_config,
                progress_callback=progress
            )
        )
        
        print(f"完成！输出文件: {result}")
    else:
        print(f"测试视频不存在: {test_video}")
