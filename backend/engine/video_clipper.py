#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : video_clipper.py
@Author : AI Assistant
@Date   : 2025-11-10
@Desc   : 视频智能剪辑器 - 基于NarratoAI clip_video.py实现
          支持FFmpeg硬件加速、精确时间戳剪辑、批量处理
"""

import os
import subprocess
import json
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from loguru import logger


class VideoClipper:
    """
    视频智能剪辑器

    核心功能：
    1. FFmpeg硬件加速自动检测
    2. 精确时间戳剪辑（支持毫秒级）
    3. 批量剪辑处理
    4. 智能编码器配置
    """

    def __init__(self):
        """初始化视频剪辑器"""
        logger.info("初始化VideoClipper...")

        # 检测FFmpeg
        self.ffmpeg_available = self._check_ffmpeg()
        if not self.ffmpeg_available:
            raise RuntimeError("FFmpeg未安装或不可用，请先安装FFmpeg")

        # 检测硬件加速
        self.hwaccel_type = self._detect_hardware_acceleration()
        logger.info(f"硬件加速类型: {self.hwaccel_type or '软件编码'}")

        # 获取编码器配置
        self.encoder_config = self._get_encoder_config()
        logger.info(f"编码器配置: {self.encoder_config}")

        logger.success("✅ VideoClipper初始化完成")

    def _check_ffmpeg(self) -> bool:
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info("✅ FFmpeg已安装")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ FFmpeg检查失败: {e}")
            return False

    def _detect_hardware_acceleration(self) -> Optional[str]:
        """
        检测可用的硬件加速类型

        检测顺序：
        1. NVIDIA NVENC (h264_nvenc)
        2. Intel QSV (h264_qsv)
        3. AMD AMF (h264_amf)
        4. Apple VideoToolbox (h264_videotoolbox)
        5. Software Fallback (libx264)

        Returns:
            硬件加速类型字符串，如果不支持则返回None
        """
        logger.info("检测硬件加速...")

        # 1. 测试NVIDIA NVENC
        if self._test_encoder("h264_nvenc"):
            logger.info("✅ 检测到NVIDIA NVENC硬件加速")
            return "nvenc"

        # 2. 测试Intel QSV
        if self._test_encoder("h264_qsv"):
            logger.info("✅ 检测到Intel QSV硬件加速")
            return "qsv"

        # 3. 测试AMD AMF
        if self._test_encoder("h264_amf"):
            logger.info("✅ 检测到AMD AMF硬件加速")
            return "amf"

        # 4. 测试Apple VideoToolbox
        if self._test_encoder("h264_videotoolbox"):
            logger.info("✅ 检测到Apple VideoToolbox硬件加速")
            return "videotoolbox"

        logger.info("⚠️  未检测到硬件加速，将使用软件编码")
        return None

    def _test_encoder(self, encoder: str) -> bool:
        """
        测试编码器是否可用

        Args:
            encoder: 编码器名称（如h264_nvenc）

        Returns:
            编码器是否可用
        """
        try:
            # 创建1秒的黑色视频测试编码器
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "lavfi",
                "-i", "color=c=black:s=640x480:d=1",
                "-c:v", encoder,
                "-f", "null",
                "-"
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10
            )

            return result.returncode == 0

        except Exception as e:
            logger.debug(f"编码器 {encoder} 测试失败: {e}")
            return False

    def _get_encoder_config(self) -> Dict[str, str]:
        """
        获取编码器配置（基于NarratoAI优化方案）

        Returns:
            编码器配置字典
                {
                    "video_codec": "h264_nvenc",  # 视频编码器
                    "quality_param": "cq",        # 质量参数类型
                    "quality_value": "23",        # 质量值
                    "preset": "medium",           # 预设
                    "pixel_format": "yuv420p",    # 像素格式
                    "audio_codec": "aac"          # 音频编码器
                }
        """
        # 基础配置
        config = {
            "video_codec": "libx264",
            "audio_codec": "aac",
            "pixel_format": "yuv420p",
            "preset": "medium",
            "quality_param": "crf",
            "quality_value": "23"
        }

        # 根据硬件加速类型调整
        if self.hwaccel_type == "nvenc":
            # NVIDIA硬件加速
            config["video_codec"] = "h264_nvenc"
            config["preset"] = "medium"
            config["quality_param"] = "cq"  # 使用CQ而不是CRF
            config["quality_value"] = "23"

        elif self.hwaccel_type == "qsv":
            # Intel QSV
            config["video_codec"] = "h264_qsv"
            config["preset"] = "medium"
            config["quality_param"] = "global_quality"
            config["quality_value"] = "23"

        elif self.hwaccel_type == "amf":
            # AMD AMF
            config["video_codec"] = "h264_amf"
            config["preset"] = "balanced"
            config["quality_param"] = "qp_i"
            config["quality_value"] = "23"

        elif self.hwaccel_type == "videotoolbox":
            # Apple VideoToolbox
            config["video_codec"] = "h264_videotoolbox"
            config["preset"] = "medium"
            config["quality_param"] = "b:v"
            config["quality_value"] = "5M"  # 比特率

        return config

    def parse_timestamp(self, timestamp: str) -> Tuple[str, str]:
        """
        解析时间戳字符串

        Args:
            timestamp: 格式为'HH:MM:SS-HH:MM:SS'或'HH:MM:SS.mmm-HH:MM:SS.mmm'

        Returns:
            (开始时间, 结束时间) 元组
        """
        parts = timestamp.split('-')
        if len(parts) != 2:
            raise ValueError(f"无效的时间戳格式: {timestamp}")

        start_time = parts[0].strip()
        end_time = parts[1].strip()

        return start_time, end_time

    def clip_video_by_timestamp(
        self,
        input_video: str,
        output_video: str,
        start_time: str,
        end_time: str,
        quality: Optional[str] = None
    ) -> str:
        """
        按时间戳剪辑视频

        Args:
            input_video: 输入视频路径
            output_video: 输出视频路径
            start_time: 开始时间 "HH:MM:SS" 或 "HH:MM:SS.mmm"
            end_time: 结束时间
            quality: 质量值（可选），默认使用配置中的值

        Returns:
            输出视频路径

        FFmpeg命令示例：
            ffmpeg -ss 00:00:10.500 -to 00:00:30.200 -i input.mp4
                   -c:v h264_nvenc -cq 23 -c:a aac output.mp4
        """
        if not os.path.exists(input_video):
            raise FileNotFoundError(f"输入视频不存在: {input_video}")

        # 创建输出目录
        output_dir = os.path.dirname(output_video)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"🎬 开始剪辑视频")
        logger.info(f"  输入: {input_video}")
        logger.info(f"  输出: {output_video}")
        logger.info(f"  时间范围: {start_time} - {end_time}")

        # 构建FFmpeg命令
        cmd = self._build_clip_command(
            input_video,
            output_video,
            start_time,
            end_time,
            quality
        )

        # 执行命令
        try:
            logger.debug(f"执行命令: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5分钟超时
            )

            if result.returncode != 0:
                logger.error(f"❌ FFmpeg执行失败")
                logger.error(f"错误输出: {result.stderr}")
                raise RuntimeError(f"视频剪辑失败: {result.stderr}")

            if os.path.exists(output_video):
                file_size = os.path.getsize(output_video) / (1024 * 1024)  # MB
                logger.success(f"✅ 视频剪辑完成: {output_video} ({file_size:.2f}MB)")
                return output_video
            else:
                raise RuntimeError("输出视频文件未生成")

        except subprocess.TimeoutExpired:
            logger.error("❌ FFmpeg执行超时")
            raise RuntimeError("视频剪辑超时")
        except Exception as e:
            logger.error(f"❌ 视频剪辑异常: {e}")
            raise

    def _build_clip_command(
        self,
        input_video: str,
        output_video: str,
        start_time: str,
        end_time: str,
        quality: Optional[str] = None
    ) -> List[str]:
        """
        构建FFmpeg剪辑命令

        Args:
            input_video: 输入视频
            output_video: 输出视频
            start_time: 开始时间
            end_time: 结束时间
            quality: 质量值（可选）

        Returns:
            FFmpeg命令列表
        """
        config = self.encoder_config
        quality_value = quality or config["quality_value"]

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-ss", start_time,        # 开始时间（快速定位）
            "-to", end_time,          # 结束时间
            "-i", input_video,        # 输入文件
            "-c:v", config["video_codec"],  # 视频编码器
            f"-{config['quality_param']}", quality_value,  # 质量参数
            "-preset", config["preset"],    # 编码预设
            "-pix_fmt", config["pixel_format"],  # 像素格式
            "-c:a", config["audio_codec"],  # 音频编码器
            "-y",                     # 覆盖输出文件
            output_video              # 输出文件
        ]

        return cmd

    def batch_clip_videos(
        self,
        input_video: str,
        clip_list: List[Dict],
        output_dir: str,
        progress_callback: Optional[callable] = None
    ) -> List[str]:
        """
        批量剪辑视频片段

        Args:
            input_video: 输入视频路径
            clip_list: 剪辑列表，每个字典包含：
                [
                    {
                        "start": "00:00:00",
                        "end": "00:00:15",
                        "name": "clip_001"  # 可选
                    },
                    ...
                ]
            output_dir: 输出目录
            progress_callback: 进度回调函数 callback(current, total, clip_name)

        Returns:
            剪辑后的视频路径列表
        """
        if not os.path.exists(input_video):
            raise FileNotFoundError(f"输入视频不存在: {input_video}")

        os.makedirs(output_dir, exist_ok=True)

        logger.info(f"📹 开始批量剪辑，共{len(clip_list)}个片段")

        output_paths = []
        total = len(clip_list)

        for i, clip_info in enumerate(clip_list):
            # 生成输出文件名
            clip_name = clip_info.get('name', f'clip_{i:03d}')
            output_filename = f"{clip_name}.mp4"
            output_path = os.path.join(output_dir, output_filename)

            # 解析时间
            start_time = clip_info.get('start', clip_info.get('start_time', '00:00:00'))
            end_time = clip_info.get('end', clip_info.get('end_time', '00:00:05'))

            logger.info(f"  [{i+1}/{total}] 剪辑片段: {clip_name}")

            try:
                # 剪辑视频
                self.clip_video_by_timestamp(
                    input_video=input_video,
                    output_video=output_path,
                    start_time=start_time,
                    end_time=end_time
                )

                output_paths.append(output_path)

                # 调用进度回调
                if progress_callback:
                    progress_callback(i + 1, total, clip_name)

            except Exception as e:
                logger.error(f"  ❌ 片段 {clip_name} 剪辑失败: {e}")
                # 继续处理下一个片段
                continue

        logger.success(f"✅ 批量剪辑完成，成功{len(output_paths)}/{total}个片段")

        return output_paths

    def merge_video_clips(
        self,
        clip_paths: List[str],
        output_video: str,
        transition: Optional[str] = None
    ) -> str:
        """
        合并多个视频片段

        Args:
            clip_paths: 视频片段路径列表
            output_video: 输出视频路径
            transition: 转场效果（可选）

        Returns:
            合并后的视频路径
        """
        if not clip_paths:
            raise ValueError("视频片段列表为空")

        logger.info(f"🔗 开始合并{len(clip_paths)}个视频片段")

        # 创建临时文件列表
        list_file = os.path.join(
            os.path.dirname(output_video),
            "concat_list.txt"
        )

        try:
            # 写入文件列表
            with open(list_file, 'w', encoding='utf-8') as f:
                for clip_path in clip_paths:
                    # FFmpeg concat需要绝对路径或转义路径
                    abs_path = os.path.abspath(clip_path)
                    f.write(f"file '{abs_path}'\n")

            # 构建合并命令
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", list_file,
                "-c", "copy",  # 直接复制流，不重新编码
                "-y",
                output_video
            ]

            logger.debug(f"执行命令: {' '.join(cmd)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode != 0:
                logger.error(f"❌ 视频合并失败: {result.stderr}")
                raise RuntimeError(f"视频合并失败: {result.stderr}")

            if os.path.exists(output_video):
                file_size = os.path.getsize(output_video) / (1024 * 1024)
                logger.success(f"✅ 视频合并完成: {output_video} ({file_size:.2f}MB)")
                return output_video
            else:
                raise RuntimeError("合并后的视频文件未生成")

        finally:
            # 清理临时文件
            if os.path.exists(list_file):
                os.remove(list_file)

    def get_video_info(self, video_path: str) -> Dict:
        """
        获取视频信息

        Args:
            video_path: 视频文件路径

        Returns:
            视频信息字典
                {
                    "duration": 120.5,
                    "width": 1920,
                    "height": 1080,
                    "fps": 30.0,
                    "codec": "h264",
                    "bitrate": "5000k"
                }
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate,codec_name,bit_rate",
            "-show_entries", "format=duration",
            "-of", "json",
            video_path
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                raise RuntimeError(f"ffprobe执行失败: {result.stderr}")

            data = json.loads(result.stdout)

            # 解析信息
            stream = data.get('streams', [{}])[0]
            format_info = data.get('format', {})

            # 解析帧率
            fps_str = stream.get('r_frame_rate', '30/1')
            fps_parts = fps_str.split('/')
            fps = float(fps_parts[0]) / float(fps_parts[1]) if len(fps_parts) == 2 else 30.0

            info = {
                'duration': float(format_info.get('duration', 0)),
                'width': int(stream.get('width', 0)),
                'height': int(stream.get('height', 0)),
                'fps': fps,
                'codec': stream.get('codec_name', 'unknown'),
                'bitrate': stream.get('bit_rate', 'unknown')
            }

            return info

        except Exception as e:
            logger.error(f"❌ 获取视频信息失败: {e}")
            return {}


# 便捷使用函数
def clip_video(
    input_video: str,
    output_video: str,
    start_time: str,
    end_time: str
) -> str:
    """
    便捷函数：剪辑视频

    Args:
        input_video: 输入视频路径
        output_video: 输出视频路径
        start_time: 开始时间 "HH:MM:SS"
        end_time: 结束时间 "HH:MM:SS"

    Returns:
        输出视频路径
    """
    clipper = VideoClipper()
    return clipper.clip_video_by_timestamp(
        input_video,
        output_video,
        start_time,
        end_time
    )


if __name__ == '__main__':
    # 测试代码
    test_input = "test_video.mp4"
    test_output = "output/clip_test.mp4"

    if os.path.exists(test_input):
        try:
            clipper = VideoClipper()

            # 测试单个剪辑
            result = clipper.clip_video_by_timestamp(
                input_video=test_input,
                output_video=test_output,
                start_time="00:00:10",
                end_time="00:00:20"
            )
            print(f"剪辑完成: {result}")

            # 测试批量剪辑
            clips = [
                {"start": "00:00:00", "end": "00:00:10", "name": "intro"},
                {"start": "00:00:10", "end": "00:00:20", "name": "main"},
                {"start": "00:00:20", "end": "00:00:30", "name": "outro"}
            ]

            outputs = clipper.batch_clip_videos(
                input_video=test_input,
                clip_list=clips,
                output_dir="output/clips"
            )
            print(f"批量剪辑完成: {len(outputs)}个片段")

        except Exception as e:
            print(f"测试失败: {e}")
    else:
        print(f"测试视频不存在: {test_input}")
