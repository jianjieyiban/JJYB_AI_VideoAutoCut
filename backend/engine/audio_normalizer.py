#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : audio_normalizer.py
@Author : AI Assistant (基于NarratoAI学习)
@Date   : 2025-11-10
@Desc   : 音频响度分析和标准化工具
          支持LUFS广播标准、RMS音量计算、智能音量调整
"""

import os
import subprocess
import json
import numpy as np
from typing import Optional, Tuple
from loguru import logger

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    logger.warning("⚠️ pydub未安装，部分功能不可用")


class AudioNormalizer:
    """
    音频响度分析和标准化工具

    功能：
    1. LUFS响度分析（符合广播标准）
    2. RMS音量计算
    3. 音频标准化
    4. 智能音量调整
    5. 多轨音频平衡
    """

    def __init__(self):
        """初始化音频规范化器"""
        self.target_lufs = -23.0  # 目标响度 (LUFS)，符合广播标准
        self.max_peak = -1.0      # 最大峰值 (dBFS)
        self.lra = 7.0            # 响度范围

        logger.info("AudioNormalizer初始化完成")

    def analyze_audio_lufs(self, audio_path: str) -> Optional[float]:
        """
        使用FFmpeg分析音频的LUFS响度

        LUFS (Loudness Units Full Scale) 是国际广播标准ITU-R BS.1770定义的响度单位

        Args:
            audio_path: 音频文件路径

        Returns:
            LUFS值，如果分析失败返回None
        """
        if not os.path.exists(audio_path):
            logger.error(f"音频文件不存在: {audio_path}")
            return None

        try:
            # 使用FFmpeg的loudnorm滤镜分析音频响度
            cmd = [
                'ffmpeg', '-hide_banner', '-nostats',
                '-i', audio_path,
                '-af', f'loudnorm=I={self.target_lufs}:TP={self.max_peak}:LRA={self.lra}:print_format=json',
                '-f', 'null', '-'
            ]

            logger.debug(f"分析音频LUFS: {os.path.basename(audio_path)}")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=60
            )

            # 从stderr中提取JSON信息
            stderr_lines = result.stderr.split('\n')
            json_start = False
            json_lines = []

            for line in stderr_lines:
                if line.strip() == '{':
                    json_start = True
                if json_start:
                    json_lines.append(line)
                if line.strip() == '}':
                    break

            if json_lines:
                try:
                    loudness_data = json.loads('\n'.join(json_lines))
                    input_i = float(loudness_data.get('input_i', 0))
                    logger.info(f"音频 {os.path.basename(audio_path)} 的LUFS: {input_i:.2f}")
                    return input_i
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"解析LUFS数据失败: {e}")

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg执行超时")
        except Exception as e:
            logger.error(f"分析音频LUFS失败: {e}")

        return None

    def get_audio_rms(self, audio_path: str) -> Optional[float]:
        """
        计算音频的RMS值作为响度的简单估计

        RMS (Root Mean Square) 均方根值，简单快速的音量估算方法

        Args:
            audio_path: 音频文件路径

        Returns:
            RMS值 (dB)，如果计算失败返回None
        """
        if not PYDUB_AVAILABLE:
            logger.warning("pydub未安装，无法计算RMS")
            return None

        try:
            audio = AudioSegment.from_file(audio_path)

            # 转换为numpy数组
            samples = np.array(audio.get_array_of_samples())

            # 如果是立体声，取平均值
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                samples = samples.mean(axis=1)

            # 计算RMS
            rms = np.sqrt(np.mean(samples**2))

            # 转换为dB
            if rms > 0:
                rms_db = 20 * np.log10(rms / (2**15))  # 假设16位音频
                logger.info(f"音频 {os.path.basename(audio_path)} 的RMS: {rms_db:.2f} dB")
                return rms_db
            else:
                return -60.0  # 静音

        except Exception as e:
            logger.error(f"计算音频RMS失败: {e}")
            return None

    def normalize_audio_lufs(self, input_path: str, output_path: str,
                            target_lufs: Optional[float] = None) -> bool:
        """
        使用FFmpeg的loudnorm滤镜标准化音频响度（两遍处理）

        第一遍：分析音频参数
        第二遍：应用标准化

        Args:
            input_path: 输入音频文件路径
            output_path: 输出音频文件路径
            target_lufs: 目标LUFS值，默认使用-23.0

        Returns:
            是否成功
        """
        if target_lufs is None:
            target_lufs = self.target_lufs

        try:
            logger.info(f"开始标准化音频LUFS: {os.path.basename(input_path)}")

            # 第一遍：分析音频
            analyze_cmd = [
                'ffmpeg', '-hide_banner', '-nostats',
                '-i', input_path,
                '-af', f'loudnorm=I={target_lufs}:TP={self.max_peak}:LRA={self.lra}:print_format=json',
                '-f', 'null', '-'
            ]

            analyze_result = subprocess.run(
                analyze_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )

            # 提取分析结果
            stderr_lines = analyze_result.stderr.split('\n')
            json_start = False
            json_lines = []

            for line in stderr_lines:
                if line.strip() == '{':
                    json_start = True
                if json_start:
                    json_lines.append(line)
                if line.strip() == '}':
                    break

            if not json_lines:
                logger.error("无法从FFmpeg获取音频分析数据")
                return False

            loudness_data = json.loads('\n'.join(json_lines))

            # 第二遍：应用标准化
            measured_i = loudness_data.get('input_i')
            measured_tp = loudness_data.get('input_tp')
            measured_lra = loudness_data.get('input_lra')
            measured_thresh = loudness_data.get('input_thresh')

            normalize_cmd = [
                'ffmpeg', '-hide_banner',
                '-i', input_path,
                '-af', (f'loudnorm=I={target_lufs}:TP={self.max_peak}:LRA={self.lra}:'
                       f'measured_I={measured_i}:'
                       f'measured_TP={measured_tp}:'
                       f'measured_LRA={measured_lra}:'
                       f'measured_thresh={measured_thresh}:'
                       f'linear=true:print_format=summary'),
                '-ar', '44100',
                '-y',
                output_path
            ]

            normalize_result = subprocess.run(
                normalize_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=120
            )

            if normalize_result.returncode == 0 and os.path.exists(output_path):
                logger.success(f"✅ 音频标准化完成: {output_path}")
                return True
            else:
                logger.error(f"音频标准化失败: {normalize_result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            logger.error("FFmpeg执行超时")
            return False
        except Exception as e:
            logger.error(f"标准化音频失败: {e}")
            return False

    def calculate_volume_adjustment(self, audio1_path: str, audio2_path: str) -> Tuple[float, float]:
        """
        计算两个音频的相对音量调整系数

        用于平衡配音和原声、BGM之间的音量关系

        Args:
            audio1_path: 音频1路径（例如：配音）
            audio2_path: 音频2路径（例如：原声）

        Returns:
            (adjustment1, adjustment2) 音量调整系数
        """
        # 分析两个音频的LUFS
        lufs1 = self.analyze_audio_lufs(audio1_path)
        lufs2 = self.analyze_audio_lufs(audio2_path)

        if lufs1 is None or lufs2 is None:
            logger.warning("无法分析音频LUFS，使用默认调整系数")
            return (1.0, 0.7)  # 默认值

        # 计算调整系数
        # 目标：让两个音频都接近目标LUFS
        adjustment1 = 10 ** ((self.target_lufs - lufs1) / 20)
        adjustment2 = 10 ** ((self.target_lufs - lufs2) / 20)

        # 限制调整范围
        adjustment1 = max(0.1, min(adjustment1, 3.0))
        adjustment2 = max(0.1, min(adjustment2, 3.0))

        logger.info(f"计算音量调整系数: audio1={adjustment1:.2f}, audio2={adjustment2:.2f}")

        return (adjustment1, adjustment2)


# 便捷函数
def normalize_audio(input_path: str, output_path: str, target_lufs: float = -23.0) -> bool:
    """
    便捷函数：标准化音频

    Args:
        input_path: 输入音频
        output_path: 输出音频
        target_lufs: 目标LUFS值

    Returns:
        是否成功
    """
    normalizer = AudioNormalizer()
    return normalizer.normalize_audio_lufs(input_path, output_path, target_lufs)


if __name__ == '__main__':
    # 测试代码
    test_audio = "test_audio.mp3"

    if os.path.exists(test_audio):
        normalizer = AudioNormalizer()

        # 测试LUFS分析
        lufs = normalizer.analyze_audio_lufs(test_audio)
        print(f"LUFS: {lufs}")

        # 测试RMS计算
        if PYDUB_AVAILABLE:
            rms = normalizer.get_audio_rms(test_audio)
            print(f"RMS: {rms} dB")

        # 测试标准化
        output_audio = "test_audio_normalized.mp3"
        success = normalizer.normalize_audio_lufs(test_audio, output_audio)
        print(f"标准化成功: {success}")
    else:
        print(f"测试音频不存在: {test_audio}")
