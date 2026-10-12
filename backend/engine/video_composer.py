#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : video_composer.py
@Author : AI Assistant
@Date   : 2025-11-10
@Desc   : 视频合成器 - 基于NarratoAI generate_video.py实现
          负责合并视频、音频、BGM、字幕，实现完整的视频合成
"""

import os
import sys
import tempfile
import subprocess
import json
import uuid
from typing import Optional, Dict, Any, Tuple
from loguru import logger

# 导入路径配置
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
try:
    from config.paths import (
        DEFAULT_FONT,
        DEFAULT_FONT_SIZE,
        DEFAULT_FONT_COLOR,
        DEFAULT_STROKE_COLOR,
        DEFAULT_STROKE_WIDTH,
        DEFAULT_SUBTITLE_POSITION,
        get_font_path,
        get_subtitle_style
    )
    PATHS_CONFIG_AVAILABLE = True
    logger.info(f"✅ 资源路径配置加载成功，默认字体: {DEFAULT_FONT}")
except ImportError as e:
    PATHS_CONFIG_AVAILABLE = False
    DEFAULT_FONT = ''
    DEFAULT_FONT_SIZE = 40
    DEFAULT_FONT_COLOR = '#FFFFFF'
    DEFAULT_STROKE_COLOR = '#000000'
    DEFAULT_STROKE_WIDTH = 2
    DEFAULT_SUBTITLE_POSITION = 'bottom'
    logger.warning(f"⚠️ 路径配置模块未找到: {e}")

# 导入AudioNormalizer
sys.path.insert(0, os.path.dirname(__file__))
try:
    from audio_normalizer import AudioNormalizer
    AUDIO_NORMALIZER_AVAILABLE = True
except ImportError:
    AUDIO_NORMALIZER_AVAILABLE = False
    logger.warning("⚠️ AudioNormalizer未安装")

try:
    from moviepy import (
        VideoFileClip,
        AudioFileClip,
        CompositeAudioClip,
        CompositeVideoClip,
        TextClip,
        afx,
    )
    MOVIEPY_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ MoviePy未安装，部分功能不可用")
    MOVIEPY_AVAILABLE = False

try:
    from PIL import ImageFont
    PIL_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ Pillow未安装，字体功能受限")
    PIL_AVAILABLE = False


class AudioVolumeConfig:
    """音量配置常量"""
    VOICE_VOLUME = 1.0          # 配音音量
    BGM_VOLUME = 0.3            # 背景音乐音量
    ORIGINAL_VOLUME = 0.7       # 原声音量
    MIN_VOLUME = 0.0            # 最小音量
    MAX_VOLUME = 2.0            # 最大音量


class VideoComposer:
    """
    视频合成器 - 核心合成引擎

    功能：
    1. 合并视频和音频
    2. 添加字幕（SRT格式）
    3. 混合多轨音频（配音+BGM+原声）
    4. 智能音量调整
    5. 字幕样式自定义
    """

    def __init__(self, use_smart_volume: bool = True):
        """
        初始化视频合成器

        Args:
            use_smart_volume: 是否使用智能音量调整（AudioNormalizer）
        """
        if not MOVIEPY_AVAILABLE:
            raise RuntimeError("MoviePy未安装，无法使用视频合成功能")

        self.use_smart_volume = use_smart_volume and AUDIO_NORMALIZER_AVAILABLE

        if self.use_smart_volume:
            self.audio_normalizer = AudioNormalizer()
            logger.info("✅ 智能音量调整已启用")
        else:
            self.audio_normalizer = None
            if use_smart_volume and not AUDIO_NORMALIZER_AVAILABLE:
                logger.warning("⚠️ AudioNormalizer不可用，已禁用智能音量调整")

        logger.info("初始化VideoComposer...")
        logger.success("✅ VideoComposer初始化完成")

    def merge_materials(
        self,
        video_path: str,
        audio_path: str,
        output_path: str,
        subtitle_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        合并视频、音频、BGM和字幕生成最终视频

        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径（配音）
            output_path: 输出文件路径
            subtitle_path: 字幕文件路径（SRT格式），可选
            bgm_path: 背景音乐文件路径，可选
            options: 其他选项配置，可包含以下字段：
                # 音量控制
                - voice_volume: 配音音量，默认1.0
                - bgm_volume: 背景音乐音量，默认0.3
                - original_audio_volume: 原始音频音量，默认0.7
                - keep_original_audio: 是否保留原始音频，默认True

                # 字幕配置
                - subtitle_enabled: 是否启用字幕，默认True
                - subtitle_font: 字幕字体，默认None（系统默认）
                - subtitle_font_size: 字幕字体大小，默认40
                - subtitle_color: 字幕颜色，默认白色
                - subtitle_bg_color: 字幕背景颜色，默认透明
                - subtitle_position: 字幕位置 'bottom'/'top'/'center'，默认'bottom'
                - stroke_color: 描边颜色，默认黑色
                - stroke_width: 描边宽度，默认1

                # 视频参数
                - threads: 处理线程数，默认2
                - fps: 输出帧率，默认30
                - resolution: 输出分辨率，如 '1080p'/'720p'/'4k' 或 '1920x1080'，默认None（保持原分辨率）
                - video_codec: 视频编码器，如 'libx264'/'libx265'/'libvpx-vp9'/'libaom-av1'，默认 'libx264'
                - bitrate: 视频比特率，如 '5M'/'8M'/'10M'，默认 None（自动）
                - preset: 编码速度预设，如 'ultrafast'/'fast'/'medium'/'slow'，默认 'medium'

        Returns:
            输出视频的路径
        """
        # 合并选项默认值
        if options is None:
            options = {}

        # 音量参数
        voice_volume = options.get('voice_volume', AudioVolumeConfig.VOICE_VOLUME)
        bgm_volume = options.get('bgm_volume', AudioVolumeConfig.BGM_VOLUME)
        original_audio_volume = options.get('original_audio_volume', AudioVolumeConfig.ORIGINAL_VOLUME)
        keep_original_audio = options.get('keep_original_audio', True)

        # 字幕参数 - 使用配置的默认值，并支持样式预设
        subtitle_enabled = options.get('subtitle_enabled', True)
        subtitle_style_name = options.get('subtitle_style')
        if PATHS_CONFIG_AVAILABLE:
            base_style = get_subtitle_style(subtitle_style_name or 'default')
            subtitle_font = options.get('subtitle_font', base_style.get('font', DEFAULT_FONT))
            subtitle_font_size = options.get('subtitle_font_size', base_style.get('font_size', DEFAULT_FONT_SIZE))
            subtitle_color = options.get('subtitle_color', base_style.get('color', '#FFFFFF'))
            subtitle_bg_color = options.get('subtitle_bg_color', base_style.get('bg_color', 'transparent'))
            subtitle_position = options.get('subtitle_position', base_style.get('position', DEFAULT_SUBTITLE_POSITION))
            stroke_color = options.get('stroke_color', base_style.get('stroke_color', DEFAULT_STROKE_COLOR))
            stroke_width = options.get('stroke_width', base_style.get('stroke_width', DEFAULT_STROKE_WIDTH))
        else:
            subtitle_font = options.get('subtitle_font', DEFAULT_FONT)
            subtitle_font_size = options.get('subtitle_font_size', DEFAULT_FONT_SIZE)
            subtitle_color = options.get('subtitle_color', '#FFFFFF')
            subtitle_bg_color = options.get('subtitle_bg_color', 'transparent')
            subtitle_position = options.get('subtitle_position', 'bottom')
            stroke_color = options.get('stroke_color', '#000000')
            stroke_width = options.get('stroke_width', DEFAULT_STROKE_WIDTH)

        # 视频参数
        threads = options.get('threads', 2)
        fps = options.get('fps', 30)
        max_duration = None
        try:
            if 'max_duration' in options and options.get('max_duration') is not None:
                md_val = float(options.get('max_duration'))
                if md_val > 0:
                    max_duration = md_val
        except Exception:
            max_duration = None

        # 输出分辨率、编码、比特率
        output_resolution = options.get('resolution') or options.get('output_resolution')
        video_codec = options.get('video_codec') or options.get('videoCodec') or 'libx264'
        video_bitrate = options.get('bitrate') or options.get('video_bitrate')
        encode_preset = options.get('preset') or options.get('encode_preset') or 'medium'
        vertical_crop = options.get('vertical_crop', False)  # 是否裁剪为竖屏
        vertical_anchor = options.get('vertical_anchor', 'center')  # 竖屏裁剪锚点

        # 将分辨率名称映射为具体尺寸
        resolution_map = {
            # 横屏格式
            '720p': (1280, 720),
            '1080p': (1920, 1080),
            '2k': (2560, 1440),
            '4k': (3840, 2160),
            # 竖屏格式 (YouTube Shorts / TikTok)
            '9:16_720p': (720, 1280),
            '9:16_1080p': (1080, 1920),
            '9:16': (1080, 1920),  # 默认竖屏
            'vertical_720p': (720, 1280),
            'vertical_1080p': (1080, 1920),
            'vertical': (1080, 1920),  # 默认竖屏
            'shorts': (1080, 1920),   # YouTube Shorts
            'tiktok': (1080, 1920),
            'reels': (1080, 1920),     # Instagram Reels
            # 方形格式
            '1:1_720p': (720, 720),
            '1:1_1080p': (1080, 1080),
            'square': (1080, 1080),
        }
        target_width = None
        target_height = None
        is_vertical = False
        if output_resolution:
            res_lower = str(output_resolution).lower()
            if res_lower in resolution_map:
                target_width, target_height = resolution_map[res_lower]
                is_vertical = target_height > target_width if target_width and target_height else False
            elif 'x' in res_lower:
                try:
                    parts = res_lower.split('x')
                    target_width = int(parts[0])
                    target_height = int(parts[1])
                    is_vertical = target_height > target_width
                except Exception:
                    pass

        # 将编码名称映射为 FFmpeg 编码器
        codec_map = {
            'h264': 'libx264',
            'h265': 'libx265',
            'hevc': 'libx265',
            'vp9': 'libvpx-vp9',
            'av1': 'libaom-av1',
        }
        if str(video_codec).lower() in codec_map:
            video_codec = codec_map[str(video_codec).lower()]

        # 比特率映射
        if video_bitrate and isinstance(video_bitrate, str):
            br_lower = video_bitrate.lower()
            bitrate_map = {
                'low': '3M',
                'medium': '6M',
                'high': '12M',
                'auto': None,
            }
            if br_lower in bitrate_map:
                video_bitrate = bitrate_map[br_lower]

        # 编码预设映射（速度优先 → 最快，质量优先 → 最慢）
        preset_map = {
            'speed': 'ultrafast',
            'fast': 'fast',
            'balanced': 'medium',
            'quality': 'slow',
            'realtime': 'ultrafast',
        }
        if str(encode_preset).lower() in preset_map:
            encode_preset = preset_map[str(encode_preset).lower()]

        # 配置日志
        logger.info(f"🎬 开始合成视频")
        logger.info(f"音量配置:")
        logger.info(f"  - 配音音量: {voice_volume}")
        logger.info(f"  - BGM音量: {bgm_volume}")
        logger.info(f"  - 原声音量: {original_audio_volume}")
        logger.info(f"  - 保留原声: {keep_original_audio}")
        logger.info(f"字幕配置:")
        logger.info(f"  - 启用字幕: {subtitle_enabled}")
        logger.info(f"  - 字幕文件: {subtitle_path}")

        # 音量参数验证
        voice_volume = self._validate_volume(voice_volume, "配音")
        bgm_volume = self._validate_volume(bgm_volume, "BGM")
        original_audio_volume = self._validate_volume(original_audio_volume, "原声")

        # 处理透明背景色
        if subtitle_bg_color == 'transparent':
            subtitle_bg_color = None

        # 所有合成产物必须落在项目根 output；拒绝外部绝对路径。
        try:
            from backend.config.paths import resolve_output_path
            output_path = str(resolve_output_path(output_path, create_parent=True))
        except ValueError:
            raise
        except Exception as exc:
            logger.warning(f'输出路径安全校验不可用: {exc}')
            raise

        # 创建输出目录
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"素材文件:")
        logger.info(f"  ① 视频: {video_path}")
        logger.info(f"  ② 音频: {audio_path}")
        if subtitle_path:
            logger.info(f"  ③ 字幕: {subtitle_path}")
        if bgm_path:
            logger.info(f"  ④ BGM: {bgm_path}")
        logger.info(f"  ⑤ 输出: {output_path}")

        # 加载视频。所有在本方法内创建的 MoviePy 对象均在 finally 中关闭，避免 Windows 文件锁。
        video_clip = None
        final_audio = None
        original_audio = None
        voice_audio = None
        bgm_clip = None
        sfx_clips = []
        audio_tracks = []
        subtitle_clips = []
        temp_audiofile = None
        temp_original_path = None
        try:
            video_clip = VideoFileClip(video_path)

            # 如配置了最大时长，则在加载后立即裁剪视频，确保后续音频与BGM等都基于裁剪后长度
            if max_duration is not None:
                try:
                    orig_dur = float(getattr(video_clip, 'duration', 0.0) or 0.0)
                except Exception:
                    orig_dur = 0.0

                if orig_dur > 0 and max_duration < orig_dur - 0.05:
                    cut_to = max(0.1, min(max_duration, orig_dur))
                    try:
                        logger.info(f"根据配置裁剪视频时长: {orig_dur:.2f}s -> {cut_to:.2f}s")
                        video_clip = video_clip.subclipped(0, cut_to)
                        orig_dur = cut_to
                    except Exception as e:
                        logger.warning(f"裁剪视频至目标时长失败，将使用完整视频: {e}")

            try:
                clip_dur = float(getattr(video_clip, 'duration', 0.0) or 0.0)
            except Exception:
                clip_dur = 0.0

            try:
                vh = int(video_clip.size[1])
            except Exception:
                vh = 0

            if subtitle_enabled and 'subtitle_font_size' not in options and vh > 0:
                if vh >= 2160:
                    subtitle_font_size = max(subtitle_font_size, 68)
                elif vh >= 1440:
                    subtitle_font_size = max(subtitle_font_size, 52)
                elif vh >= 1080:
                    subtitle_font_size = max(subtitle_font_size, 44)

            logger.info(f"视频尺寸: {video_clip.size[0]}x{video_clip.size[1]}, 时长: {clip_dur:.2f}秒")

            # ========================================
            # 9:16 竖屏视频智能裁剪（用于 YouTube Shorts / TikTok）
            # ========================================
            vertical_anchor = options.get('vertical_anchor', 'center')
            if target_width and target_height and target_width < target_height:
                # 目标是竖屏格式
                try:
                    orig_w, orig_h = video_clip.size
                    orig_aspect = orig_w / orig_h if orig_h > 0 else 1.0
                    target_aspect = target_width / target_height if target_height > 0 else 1.0

                    if orig_aspect > target_aspect:
                        # 源视频更宽 (如16:9)，需要裁剪左右两侧
                        # 计算裁剪后的宽度
                        crop_h = orig_h
                        crop_w = int(crop_h * target_aspect)

                        # 根据锚点计算裁剪位置
                        if vertical_anchor == 'top':
                            x1 = 0
                        elif vertical_anchor == 'bottom':
                            x1 = orig_w - crop_w
                        else:  # center
                            x1 = (orig_w - crop_w) // 2

                        logger.info(f"📐 竖屏裁剪: {orig_w}x{orig_h} -> {crop_w}x{crop_h}, 锚点: {vertical_anchor}, x1={x1}")
                        video_clip = video_clip.cropped(x1=x1, x2=x1 + crop_w, y1=0, y2=crop_h)

                    elif orig_aspect < target_aspect:
                        # 源视频更高 (如9:16)，需要裁剪上下两侧
                        crop_w = orig_w
                        crop_h = int(crop_w / target_aspect)

                        if vertical_anchor == 'top':
                            y1 = 0
                        elif vertical_anchor == 'bottom':
                            y1 = orig_h - crop_h
                        else:  # center
                            y1 = (orig_h - crop_h) // 2

                        logger.info(f"📐 竖屏裁剪(源更高): {orig_w}x{orig_h} -> {crop_w}x{crop_h}, 锚点: {vertical_anchor}, y1={y1}")
                        video_clip = video_clip.cropped(x1=0, x2=crop_w, y1=y1, y2=y1 + crop_h)
                except Exception as e:
                    logger.warning(f"竖屏裁剪失败，将使用原始视频: {e}")

            # 应用输出分辨率调整（如果指定了目标分辨率）
            if target_width and target_height:
                try:
                    orig_w, orig_h = video_clip.size
                    if orig_w != target_width or orig_h != target_height:
                        logger.info(f"📐 调整视频分辨率: {orig_w}x{orig_h} -> {target_width}x{target_height}")
                        video_clip = video_clip.resized(width=target_width, height=target_height)
                except Exception as e:
                    logger.warning(f"调整视频分辨率失败，将保持原分辨率: {e}")

            # 提取视频原声（如果需要）
            original_audio = None
            if keep_original_audio and original_audio_volume > 0:
                try:
                    original_audio = video_clip.audio
                    if original_audio:
                        # 只有当音量不为1.0时才进行调整
                        if abs(original_audio_volume - 1.0) > 0.001:
                            original_audio = original_audio.with_effects([
                                afx.MultiplyVolume(original_audio_volume)
                            ])
                            logger.info(f"已提取视频原声，音量: {original_audio_volume}")
                        else:
                            logger.info("已提取视频原声，保持原始音量")
                    else:
                        logger.warning("视频没有音轨，无法提取原声")
                except Exception as e:
                    logger.error(f"提取视频原声失败: {e}")
                    original_audio = None

            # 移除原始音轨
            video_clip = video_clip.without_audio()

        except Exception as e:
            logger.error(f"加载视频失败: {e}")
            raise

        # 智能音量调整
        if self.use_smart_volume and audio_path and original_audio and os.path.exists(audio_path):
            try:
                logger.info("🔊 使用智能音量调整...")

                # 提取原声到临时文件（如果需要）
                temp_original_path = None
                if original_audio:
                    temp_original_path = os.path.join(
                        output_dir or tempfile.gettempdir(),
                        f'jjyb_original_{uuid.uuid4().hex}.m4a'
                    )
                    original_audio.write_audiofile(temp_original_path, codec='aac', logger=None)

                # 计算音量调整系数
                voice_adj, original_adj = self.audio_normalizer.calculate_volume_adjustment(
                    audio_path,
                    temp_original_path
                )

                # 应用调整系数
                voice_volume = voice_volume * voice_adj
                original_audio_volume = original_audio_volume * original_adj

                logger.info(f"智能音量调整完成: 配音={voice_adj:.2f}, 原声={original_adj:.2f}")

                # 清理临时文件
                if temp_original_path and os.path.exists(temp_original_path):
                    os.remove(temp_original_path)
                    temp_original_path = None

            except Exception as e:
                logger.warning(f"智能音量调整失败，使用默认音量: {e}")

        # 处理音频轨道
        audio_tracks = []

        # 1. 添加配音
        if audio_path and os.path.exists(audio_path):
            try:
                voice_audio = AudioFileClip(audio_path).with_effects([
                    afx.MultiplyVolume(voice_volume)
                ])
                audio_tracks.append(voice_audio)
                logger.info(f"已添加配音音频，音量: {voice_volume:.2f}")
            except Exception as e:
                logger.error(f"加载配音音频失败: {e}")

        # 2. 添加原声
        if original_audio is not None:
            audio_tracks.append(original_audio)
            logger.info(f"已添加视频原声")

        # 3. 添加BGM
        if bgm_path and os.path.exists(bgm_path):
            try:
                bgm_clip = AudioFileClip(bgm_path).with_effects([
                    afx.MultiplyVolume(bgm_volume),
                    afx.AudioFadeOut(3),  # 3秒淡出
                    afx.AudioLoop(duration=video_clip.duration)  # 循环至视频长度
                ])
                audio_tracks.append(bgm_clip)
                logger.info(f"已添加BGM，音量: {bgm_volume}")
            except Exception as e:
                logger.error(f"添加BGM失败: {e}")

        # 4. 添加与花字时间轴同步的原创音效（显式启用才生效）
        flower_sfx_enabled = bool(options.get('flower_sound_effects', options.get('sound_effects_enabled', False)))
        flower_sfx_items = options.get('flower_sound_effects') if isinstance(options.get('flower_sound_effects'), list) else options.get('flower_sfx') or []
        if flower_sfx_enabled:
            for sfx in flower_sfx_items:
                try:
                    sfx_path = str(sfx.get('asset_path') or sfx.get('sfx_path') or '')
                    start = max(0.0, float(sfx.get('start_seconds', 0)))
                    volume = self._validate_volume(float(sfx.get('volume', 0.18)), '花字音效')
                    if not sfx_path or not os.path.isfile(sfx_path) or start >= video_clip.duration:
                        logger.warning('花字音效资源不存在或无效，已跳过: %s', sfx_path)
                        continue
                    clip = AudioFileClip(sfx_path)
                    duration = min(float(clip.duration or 0), max(0.0, video_clip.duration - start))
                    if duration <= 0:
                        clip.close()
                        continue
                    clip = clip.subclipped(0, duration).with_start(start).with_effects([afx.MultiplyVolume(volume)])
                    sfx_clips.append(clip)
                    audio_tracks.append(clip)
                except Exception as e:
                    logger.warning(f'添加花字音效失败，已跳过: {e}')
        if sfx_clips:
            logger.info(f'已添加 {len(sfx_clips)} 个花字同步音效')

        # 合成最终音频轨道
        if audio_tracks:
            final_audio = CompositeAudioClip(audio_tracks)
            try:
                clip_total = float(getattr(video_clip, 'duration', 0.0) or 0.0)
            except Exception:
                clip_total = 0.0
            if clip_total > 0:
                try:
                    final_audio = final_audio.subclipped(0, clip_total)
                except Exception as e:
                    logger.warning(f"音频裁剪到视频时长失败，将使用完整音频: {e}")
            video_clip = video_clip.with_audio(final_audio)
            logger.info(f"已合成所有音频轨道，共{len(audio_tracks)}个")
        else:
            logger.warning("没有可用的音频轨道，输出视频将没有声音")

        # 处理字幕
        if subtitle_enabled and subtitle_path and self._is_valid_subtitle_file(subtitle_path):
            logger.info("开始处理字幕")
            try:
                video_clip = self._add_subtitles(
                    video_clip,
                    subtitle_path,
                    subtitle_font,
                    subtitle_font_size,
                    subtitle_color,
                    subtitle_bg_color,
                    subtitle_position,
                    stroke_color,
                    stroke_width
                )
                subtitle_clips = getattr(video_clip, '_jjyb_subtitle_clips', [])
            except Exception as e:
                logger.error(f"处理字幕失败: {e}")
                logger.warning("字幕处理失败，继续生成无字幕视频")
        elif not subtitle_enabled:
            logger.info("字幕已禁用，跳过字幕处理")
        elif not subtitle_path:
            logger.info("未提供字幕文件，跳过字幕处理")
        else:
            logger.warning(f"字幕文件无效或为空: {subtitle_path}")

        # 在导出前，根据 max_duration 再次夹紧最终视频长度，防止字幕等操作拉长总时长
        if max_duration is not None:
            try:
                final_total = float(getattr(video_clip, 'duration', 0.0) or 0.0)
            except Exception:
                final_total = 0.0
            if final_total > 0 and max_duration > 0 and final_total - max_duration > 0.05:
                cut_to = max_duration
                try:
                    logger.info(f"最终合成后再次裁剪时长: {final_total:.2f}s -> {cut_to:.2f}s")
                    video_clip = video_clip.with_duration(cut_to)
                except Exception as e:
                    logger.warning(f"最终时长裁剪失败，将使用当前长度: {e}")

        # 导出最终视频
        temp_audiofile = None
        try:
            logger.info("开始导出视频...")
            logger.info(f"🎞️ 编码配置: codec={video_codec}, preset={encode_preset}, bitrate={video_bitrate or 'auto'}")

            # AAC 临时音频必须使用 AAC 容器扩展名，且每次导出独占文件，不能写入 .mp3。
            temp_audiofile = os.path.join(
                output_dir or tempfile.gettempdir(),
                f'jjyb_moviepy_{uuid.uuid4().hex}.m4a'
            )
            write_kwargs = {
                'filename': output_path,
                'audio_codec': 'aac',
                'temp_audiofile': temp_audiofile,
                'threads': threads,
                'fps': fps,
                'logger': None,
                'codec': video_codec,
                'preset': encode_preset,
            }

            # 比特率参数（如果指定了）
            if video_bitrate:
                write_kwargs['bitrate'] = video_bitrate

            # 删除可能存在的旧输出文件（避免文件锁定问题）
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except Exception:
                    pass

            # 使用 MoviePy 写入视频
            try:
                video_clip.write_videofile(**write_kwargs)
            except Exception as write_error:
                # 检查是否创建了空文件，如果是则删除
                if os.path.exists(output_path):
                    try:
                        file_size = os.path.getsize(output_path)
                        if file_size < 1024:  # 小于1KB认为是损坏的文件
                            os.remove(output_path)
                            logger.warning(f"删除了损坏的输出文件: {output_path}")
                    except Exception:
                        pass
                raise write_error

            # 验证输出文件
            self._validate_output(output_path, require_audio=bool(audio_tracks), expected_duration=max_duration)
            file_size = os.path.getsize(output_path) / (1024 * 1024)
            logger.success(f"✅ 视频合成完成: {output_path} ({file_size:.2f}MB)")
            return output_path

        except Exception as e:
            logger.error(f"导出视频失败: {e}")
            # 清理可能损坏的输出文件
            if 'output_path' in dir() and os.path.exists(output_path):
                try:
                    file_size = os.path.getsize(output_path)
                    if file_size < 1024:
                        os.remove(output_path)
                        logger.info(f"已清理损坏的输出文件: {output_path}")
                except Exception:
                    pass
            raise
        finally:
            # 关闭本方法创建的所有合成/素材 clip；重复 close 对 MoviePy 对象安全，逐个隔离避免清理被中断。
            for clip in [video_clip, final_audio, voice_audio, bgm_clip, original_audio, *audio_tracks, *sfx_clips, *subtitle_clips]:
                try:
                    if clip is not None:
                        clip.close()
                except Exception:
                    pass
            for temp_path in (temp_audiofile, temp_original_path):
                try:
                    if temp_path and os.path.exists(temp_path):
                        os.remove(temp_path)
                except OSError as cleanup_error:
                    logger.warning(f"清理临时音频失败: {temp_path}: {cleanup_error}")

    def _validate_output(self, output_path: str, require_audio: bool, expected_duration: float = None) -> None:
        """使用 FFprobe 验证最终成片，避免把不完整文件标记为成功。"""
        # 1. 检查文件存在性和大小
        if not os.path.isfile(output_path):
            raise RuntimeError('输出视频文件未生成')
        file_size = os.path.getsize(output_path)
        if file_size <= 0:
            raise RuntimeError('输出视频文件为空')
        
        # 2. 最小文件大小检查（防止生成不完整文件）
        min_size = 10 * 1024  # 10KB
        if file_size < min_size:
            raise RuntimeError(f'输出视频文件过小 ({file_size} bytes < {min_size} bytes)，可能生成不完整')
        
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 
                 'format=duration,size:stream=codec_type,codec_name,width,height', 
                 '-of', 'json', output_path],
                capture_output=True, text=True, timeout=30, check=False
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or 'FFprobe 无法读取输出视频')
            
            info = json.loads(result.stdout or '{}')
            streams = info.get('streams') or []
            format_info = info.get('format') or {}
            
            # 3. 检查视频流
            video_streams = [s for s in streams if s.get('codec_type') == 'video']
            if not video_streams:
                raise RuntimeError('输出视频缺少视频流')
            
            video_stream = video_streams[0]
            video_width = video_stream.get('width', 0)
            video_height = video_stream.get('height', 0)
            
            # 4. 检查音频流（如果需要）
            if require_audio:
                audio_streams = [s for s in streams if s.get('codec_type') == 'audio']
                if not audio_streams:
                    raise RuntimeError('输出视频缺少音频流')
                logger.info(f"✅ 音频流验证通过: {audio_streams[0].get('codec_name')}")
            
            # 5. 检查视频时长
            duration_str = format_info.get('duration')
            if duration_str:
                duration = float(duration_str)
                if duration <= 0:
                    raise RuntimeError('输出视频时长无效')
                
                # 如果提供了预期时长，检查偏差
                if expected_duration and expected_duration > 0:
                    duration_diff = abs(duration - expected_duration)
                    max_diff = expected_duration * 0.1  # 允许10%的偏差
                    if duration_diff > max_diff:
                        logger.warning(
                            f'⚠️ 视频时长与预期偏差较大: {duration:.2f}s vs 预期 {expected_duration:.2f}s'
                        )
                else:
                    logger.info(f"✅ 视频时长验证通过: {duration:.2f}秒")
            
            # 6. 验证视频尺寸
            if video_width > 0 and video_height > 0:
                logger.info(f"✅ 输出视频尺寸: {video_width}x{video_height}")
            
            logger.info(f"✅ 输出文件大小: {file_size / (1024*1024):.2f}MB")
        except FileNotFoundError as exc:
            raise RuntimeError('未找到 FFprobe，无法验证输出视频') from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(f'无法解析输出视频信息: {exc}') from exc

    def _validate_volume(self, volume: float, name: str) -> float:
        """
        验证并限制音量范围

        Args:
            volume: 音量值
            name: 音量名称（用于日志）

        Returns:
            限制后的音量值
        """
        if not (AudioVolumeConfig.MIN_VOLUME <= volume <= AudioVolumeConfig.MAX_VOLUME):
            logger.warning(
                f"{name}音量 {volume} 超出有效范围 "
                f"[{AudioVolumeConfig.MIN_VOLUME}, {AudioVolumeConfig.MAX_VOLUME}]，将被限制"
            )
            return max(AudioVolumeConfig.MIN_VOLUME, min(volume, AudioVolumeConfig.MAX_VOLUME))
        return volume

    def _is_valid_subtitle_file(self, subtitle_path: str) -> bool:
        """
        检查字幕文件是否有效

        Args:
            subtitle_path: 字幕文件路径

        Returns:
            如果字幕文件存在且包含有效内容则返回True
        """
        if not subtitle_path or not os.path.exists(subtitle_path):
            return False

        try:
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            # 检查文件是否为空
            if not content:
                return False

            # 检查是否包含时间戳格式（SRT格式）
            import re
            time_pattern = r'\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}'
            if not re.search(time_pattern, content):
                return False

            return True

        except Exception as e:
            logger.warning(f"检查字幕文件时出错: {e}")
            return False

    def _parse_srt_file(self, subtitle_path: str):
        """解析简单的 SRT 文件，返回 [(start, end, text), ...]，时间单位为秒。"""
        entries = []
        if not subtitle_path or not os.path.exists(subtitle_path):
            return entries
        try:
            import re
            with open(subtitle_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()
            if not content:
                return entries
            blocks = re.split(r'\n{2,}', content)
            for block in blocks:
                lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
                if len(lines) < 2:
                    continue
                # 第一行通常是序号，第二行是时间轴
                time_line = lines[1]
                m = re.match(
                    (r'(?P<start_h>\d{2}):(?P<start_m>\d{2}):(?P<start_s>\d{2}),(?P<start_ms>\d{3})\s*-->'
                     r'\s*(?P<end_h>\d{2}):(?P<end_m>\d{2}):(?P<end_s>\d{2}),(?P<end_ms>\d{3})'),
                    time_line
                )
                if not m:
                    continue
                def _to_seconds(h, m_, s, ms):
                    return (int(h) * 3600 + int(m_) * 60 + int(s)) + int(ms) / 1000.0
                start = _to_seconds(
                    m.group('start_h'), m.group('start_m'),
                    m.group('start_s'), m.group('start_ms')
                )
                end = _to_seconds(
                    m.group('end_h'), m.group('end_m'),
                    m.group('end_s'), m.group('end_ms')
                )
                if end <= start:
                    continue
                text = '\n'.join(lines[2:]) if len(lines) > 2 else ''
                if not text:
                    continue
                entries.append((start, end, text))
        except Exception as e:
            logger.warning(f"解析SRT字幕文件失败，将跳过字幕渲染: {e}")
            return []
        return entries

    def _add_subtitles(
        self,
        video_clip,
        subtitle_path: str,
        font: str,
        font_size: int,
        color: str,
        bg_color: Optional[str],
        position: str,
        stroke_color: str,
        stroke_width: int
    ):
        """
        添加字幕到视频

        Args:
            video_clip: 视频片段对象
            subtitle_path: 字幕文件路径
            font: 字体
            font_size: 字体大小
            color: 字幕颜色
            bg_color: 背景颜色
            position: 位置
            stroke_color: 描边颜色
            stroke_width: 描边宽度

        Returns:
            添加了字幕的视频对象
        """
        video_width, video_height = video_clip.size

        # 解析 SRT 字幕
        subtitles = self._parse_srt_file(subtitle_path)
        if not subtitles:
            logger.warning(f"字幕文件解析结果为空，跳过字幕渲染: {subtitle_path}")
            return video_clip

        # 获取视频时长，用于裁剪字幕区间，避免字幕片段比视频更长
        try:
            clip_total = float(getattr(video_clip, 'duration', 0.0) or 0.0)
        except Exception:
            clip_total = 0.0

        # 创建每个字幕片段并设置位置
        text_clips = []
        for (start, end, phrase) in subtitles:
            if clip_total > 0:
                # 将字幕时间区间限制在 [0, clip_total] 内，避免拉长最终合成时长
                if start >= clip_total:
                    continue
                adj_start = max(0.0, start)
                adj_end = min(end, clip_total)
                if adj_end <= adj_start:
                    continue
                start, end = adj_start, adj_end
            clip = self._create_text_clip(
                subtitle_item=((start, end), phrase),
                video_size=(video_width, video_height),
                font=font,
                font_size=font_size,
                color=color,
                bg_color=bg_color,
                position=position,
                stroke_color=stroke_color,
                stroke_width=stroke_width
            )
            text_clips.append(clip)

        # 合成视频和字幕
        final_clip = CompositeVideoClip([video_clip, *text_clips])
        # 由调用方统一关闭，确保 TextClip 在 Windows 上不遗留文件句柄。
        setattr(final_clip, '_jjyb_subtitle_clips', text_clips)
        logger.success(f"✅ 字幕添加成功，共{len(text_clips)}个片段")

        return final_clip

    def _create_text_clip(
        self,
        subtitle_item,
        video_size: Tuple[int, int],
        font: str,
        font_size: int,
        color: str,
        bg_color: Optional[str],
        position: str,
        stroke_color: str,
        stroke_width: int
    ):
        """创建单个字幕片段"""
        phrase = subtitle_item[1]
        video_width, video_height = video_size

        # 创建文本片段
        try:
            logger.info(f"创建字幕: 字号={font_size}, 字体={font}, 颜色={color}, 描边={stroke_width}")
            _clip = TextClip(
                text=phrase,
                font=font if font else None,
                font_size=font_size,
                color=color,
                bg_color=bg_color,
                stroke_color=stroke_color if stroke_width > 0 else None,
                stroke_width=stroke_width if stroke_width > 0 else 0
            )
        except Exception as e:
            logger.warning(f"创建字幕片段失败，使用简化参数: {e}")
            _clip = TextClip(
                text=phrase,
                font_size=font_size,
                color=color
            )

        # 设置字幕时间
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)

        # 设置字幕位置
        if position == "bottom":
            _clip = _clip.with_position(("center", video_height * 0.93 - _clip.h))
        elif position == "top":
            _clip = _clip.with_position(("center", video_height * 0.1))
        elif position == "center":
            _clip = _clip.with_position(("center", "center"))
        else:
            # 默认底部
            _clip = _clip.with_position(("center", video_height * 0.9 - _clip.h))

        return _clip


# 便捷使用函数
def merge_video_audio(
    video_path: str,
    audio_path: str,
    output_path: str,
    subtitle_path: Optional[str] = None,
    bgm_path: Optional[str] = None,
    **options
) -> str:
    """
    便捷函数：合并视频和音频

    Args:
        video_path: 视频文件路径
        audio_path: 音频文件路径
        output_path: 输出文件路径
        subtitle_path: 字幕文件路径（可选）
        bgm_path: BGM文件路径（可选）
        **options: 其他选项

    Returns:
        输出视频路径
    """
    composer = VideoComposer()
    return composer.merge_materials(
        video_path=video_path,
        audio_path=audio_path,
        output_path=output_path,
        subtitle_path=subtitle_path,
        bgm_path=bgm_path,
        options=options
    )


if __name__ == '__main__':
    # 测试代码
    test_video = "test_video.mp4"
    test_audio = "test_audio.mp3"
    test_subtitle = "test_subtitle.srt"
    test_output = "output/composed_video.mp4"

    if os.path.exists(test_video) and os.path.exists(test_audio):
        try:
            composer = VideoComposer()

            result = composer.merge_materials(
                video_path=test_video,
                audio_path=test_audio,
                output_path=test_output,
                subtitle_path=test_subtitle if os.path.exists(test_subtitle) else None,
                options={
                    'voice_volume': 1.0,
                    'subtitle_enabled': True,
                    'subtitle_font_size': 40,
                    'fps': 30
                }
            )

            print(f"视频合成完成: {result}")

        except Exception as e:
            print(f"测试失败: {e}")
    else:
        print(f"测试文件不存在")
