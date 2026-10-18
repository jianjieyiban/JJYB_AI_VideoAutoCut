#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : video_analyzer.py
@Author : AI Assistant
@Date   : 2025-11-10
@Desc   : 视频分析器 - 基于NarratoAI架构实现
          负责视频帧提取、场景分析、内容理解
"""

import os
import cv2
import json
import hashlib
import base64
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from pathlib import Path
import numpy as np
from loguru import logger
import requests


class VideoAnalyzer:
    """
    视频分析器 - 核心功能模块

    功能：
    1. 提取视频关键帧
    2. 调用视觉大模型分析画面内容
    3. 生成时间戳标注的frame_observations
    4. 输出结构化分析结果JSON
    """

    def __init__(self, output_dir: str = None):
        """
        初始化视频分析器

        Args:
            output_dir: 输出目录，默认为backend/temp/analysis
        """
        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(__file__), '..', 'temp', 'analysis')
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"VideoAnalyzer初始化完成，输出目录: {self.output_dir}")

    def extract_key_frames(
        self,
        video_path: str,
        interval_seconds: float = 3.0,
        max_frames: int = 100
    ) -> List[Dict]:
        """
        提取视频关键帧

        Args:
            video_path: 视频文件路径
            interval_seconds: 帧提取间隔（秒），默认3秒一帧
            max_frames: 最大提取帧数，默认100帧

        Returns:
            List[Dict]: 关键帧列表，每个字典包含：
                - timestamp: 时间戳(秒)
                - timestamp_str: 格式化时间戳 "HH:MM:SS"
                - frame_index: 帧序号
                - frame_path: 帧图片保存路径
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        logger.info(f"开始提取关键帧: {video_path}")
        logger.info(f"  间隔: {interval_seconds}秒")
        logger.info(f"  最大帧数: {max_frames}")

        # 打开视频
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频文件: {video_path}")

        # 获取视频信息
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0

        logger.info(f"视频信息: FPS={fps:.2f}, 总帧数={total_frames}, 时长={duration:.2f}秒")

        # 计算帧间隔
        frame_interval = int(fps * interval_seconds)

        # 创建帧输出目录
        video_hash = hashlib.md5(video_path.encode()).hexdigest()[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        frames_dir = self.output_dir / f"frames_{video_hash}_{timestamp}"
        frames_dir.mkdir(exist_ok=True)

        key_frames = []
        frame_count = 0
        extracted_count = 0

        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # 检查是否到达提取点
                if frame_count % frame_interval == 0 and extracted_count < max_frames:
                    # 计算时间戳
                    timestamp_seconds = frame_count / fps
                    timestamp_str = self._seconds_to_timestamp(timestamp_seconds)

                    # 保存帧图片
                    frame_filename = f"frame_{extracted_count:04d}_{timestamp_str.replace(':', '-')}.jpg"
                    frame_path = frames_dir / frame_filename
                    cv2.imwrite(str(frame_path), frame)

                    # 记录关键帧信息
                    key_frame_info = {
                        'frame_index': extracted_count,
                        'timestamp': timestamp_seconds,
                        'timestamp_str': timestamp_str,
                        'frame_path': str(frame_path),
                        'video_frame_number': frame_count
                    }
                    key_frames.append(key_frame_info)
                    extracted_count += 1

                    if extracted_count % 10 == 0:
                        logger.info(f"  已提取 {extracted_count} 帧...")

                frame_count += 1

            logger.success(f"✅ 关键帧提取完成: 共{extracted_count}帧，保存至 {frames_dir}")

        finally:
            cap.release()

        return key_frames

    def analyze_frames_with_llm(
        self,
        key_frames: List[Dict],
        llm_api_key: str,
        llm_base_url: str,
        llm_model: str,
        batch_size: int = 5
    ) -> Dict:
        """
        使用大语言模型分析视频帧

        Args:
            key_frames: 关键帧列表
            llm_api_key: LLM API密钥
            llm_base_url: LLM API基础URL
            llm_model: 模型名称
            batch_size: 批次大小，每批分析的帧数

        Returns:
            Dict: 分析结果，包含frame_observations和overall_activity_summaries
        """
        logger.info(f"开始AI分析，总帧数: {len(key_frames)}, 批次大小: {batch_size}")

        frame_observations = []
        overall_activity_summaries = []

        # 按批次分析
        for batch_index in range(0, len(key_frames), batch_size):
            batch_frames = key_frames[batch_index:batch_index + batch_size]

            logger.info(f"分析批次 {batch_index // batch_size + 1}/{(len(key_frames) + batch_size - 1) // batch_size}")

            # 获取批次时间范围
            start_time = batch_frames[0]['timestamp_str']
            end_time = batch_frames[-1]['timestamp_str']
            time_range = f"{start_time}-{end_time}"

            # 分析每一帧
            batch_observations = []
            for frame_info in batch_frames:
                observation = self._analyze_single_frame(
                    frame_info['frame_path'],
                    llm_api_key,
                    llm_base_url,
                    llm_model
                )

                frame_obs = {
                    'batch_index': batch_index // batch_size,
                    'timestamp': frame_info['timestamp_str'],
                    'observation': observation
                }
                frame_observations.append(frame_obs)
                batch_observations.append(observation)

            # 生成批次总结
            batch_summary = self._summarize_batch(
                batch_observations,
                llm_api_key,
                llm_base_url,
                llm_model
            )

            overall_summary = {
                'batch_index': batch_index // batch_size,
                'time_range': time_range,
                'summary': batch_summary
            }
            overall_activity_summaries.append(overall_summary)

            logger.info(f"  批次 {batch_index // batch_size + 1} 完成")

        # 组装最终结果
        analysis_result = {
            'video_info': {
                'total_frames_analyzed': len(key_frames),
                'batch_count': len(overall_activity_summaries),
                'analysis_timestamp': datetime.now().isoformat()
            },
            'frame_observations': frame_observations,
            'overall_activity_summaries': overall_activity_summaries
        }

        logger.success(f"✅ AI分析完成，共{len(frame_observations)}个观察点")

        return analysis_result

    def _analyze_single_frame(
        self,
        frame_path: str,
        api_key: str,
        base_url: str,
        model: str
    ) -> str:
        """
        分析单个视频帧（调用视觉大模型）

        Args:
            frame_path: 帧图片路径
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称

        Returns:
            str: 帧分析结果描述
        """
        frame_name = os.path.basename(frame_path) or "frame"
        logger.debug(f"  分析帧: {frame_name}")

        # 优先使用外部视觉大模型（OpenAI 兼容 chat.completions 接口）
        if api_key and model:
            try:
                with open(frame_path, 'rb') as f:
                    img_bytes = f.read()
                img_b64 = base64.b64encode(img_bytes).decode('utf-8')

                safe_base = base_url or "https://api.openai.com/v1"
                url = safe_base.rstrip('/') + '/chat/completions'

                prompt_text = (
                    "请用简洁的中文描述这张视频关键帧画面中的场景、主要人物和动作，"
                    "不超过50字，不要出现多余的客套话。"
                )

                payload: Dict[str, object] = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个专业的视频画面分析助手，擅长用简洁中文概括画面内容。"
                        },
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt_text},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{img_b64}"
                                    }
                                }
                            ]
                        }
                    ],
                    "max_tokens": 128,
                    "temperature": 0.4
                }

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = (data.get('choices') or [{}])[0].get('message') or {}
                    content = msg.get('content', '') if isinstance(msg, dict) else ''
                    content = str(content).strip()
                    if content:
                        return content
                    logger.warning("视觉模型返回内容为空，将回退到本地规则描述")
                else:
                    logger.error(f"视觉模型调用失败: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                logger.error(f"视觉模型调用异常，将回退到本地规则描述: {e}", exc_info=True)

        # Anna 平台宿主 LLM（无用户密钥时的开箱即用 AI 视觉分析）
        if not (api_key and model):
            try:
                from backend.engine import anna_host_llm
                if anna_host_llm.is_host_llm_available():
                    host_prompt = (
                        "请用简洁的一句话描述这张视频关键帧画面中的场景、主要人物和动作，"
                        "不超过50字，不要出现多余的客套话。"
                    )
                    return anna_host_llm.sample_vision(frame_path, host_prompt, max_tokens=256)
            except Exception as e:
                logger.warning(f"宿主 LLM 帧分析失败，回退本地规则描述: {e}")

        # 回退：使用本地规则生成简要描述
        idx = None
        try:
            digits = ''.join(ch if ch.isdigit() else ' ' for ch in frame_name).split()
            if digits:
                idx = int(digits[-1])
        except Exception:
            idx = None

        if idx is not None:
            return f"第{idx}个关键帧画面，包含主要场景与人物活动，适合作为解说切入点。"
        else:
            return "关键帧画面中包含主体人物与环境元素，可用于编写对应的解说句子。"

    def _summarize_batch(
        self,
        observations: List[str],
        api_key: str,
        base_url: str,
        model: str
    ) -> str:
        """
        总结批次观察结果

        Args:
            observations: 观察结果列表
            api_key: API密钥
            base_url: API基础URL
            model: 模型名称

        Returns:
            str: 批次总结
        """
        if not observations:
            return "本片段画面较少，未检测到明显的活动或场景变化。"

        # 优先使用外部LLM进行文本总结
        if api_key and model:
            try:
                safe_base = base_url or "https://api.openai.com/v1"
                url = safe_base.rstrip('/') + '/chat/completions'

                head = observations[:20]
                obs_text = "\n".join(f"- {str(x)}" for x in head)

                user_prompt = (
                    "下面是某一时间段内多个视频关键帧的描述，请用1-2句话用中文总结这一整段的主要内容，"
                    "突出场景、事件和情绪，不超过80字：\n" + obs_text
                )

                payload: Dict[str, object] = {
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是一个专业的视频内容总结助手，擅长用简洁中文概括一段画面的主要内容。"
                        },
                        {
                            "role": "user",
                            "content": user_prompt
                        }
                    ],
                    "max_tokens": 128,
                    "temperature": 0.3
                }

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                resp = requests.post(url, headers=headers, json=payload, timeout=60)
                if resp.status_code == 200:
                    data = resp.json()
                    msg = (data.get('choices') or [{}])[0].get('message') or {}
                    content = msg.get('content', '') if isinstance(msg, dict) else ''
                    content = str(content).strip()
                    if content:
                        return content
                    logger.warning("批次总结模型返回内容为空，将回退到本地规则总结")
                else:
                    logger.error(f"批次总结模型调用失败: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                logger.error(f"批次总结模型调用异常，将回退到本地规则总结: {e}", exc_info=True)

        # Anna 平台宿主 LLM（无用户密钥时的开箱即用 AI 批次总结）
        if not (api_key and model):
            try:
                from backend.engine import anna_host_llm
                if anna_host_llm.is_host_llm_available():
                    head = observations[:20]
                    obs_text = "\n".join(f"- {str(x)}" for x in head)
                    host_prompt = (
                        "下面是某一时间段内多个视频关键帧的描述，请用1-2句话总结这一整段的主要内容，"
                        "突出场景、事件和情绪，不超过80字：\n" + obs_text
                    )
                    summary = anna_host_llm.sample_text(host_prompt, max_tokens=256)
                    if summary.strip():
                        return summary.strip()
            except Exception as e:
                logger.warning(f"宿主 LLM 批次总结失败，回退本地规则总结: {e}")

        # 回退：使用本地规则对一批帧观察进行汇总
        head = observations[:5]
        joined = "；".join(str(x) for x in head)
        if len(observations) > 5:
            return f"本片段包含多个关键画面，主要内容概括如下：{joined} 等。"
        else:
            return f"本片段的整体内容可概括为：{joined}。"

    def export_analysis_json(
        self,
        analysis_result: Dict,
        output_filename: Optional[str] = None
    ) -> str:
        """
        导出分析结果为JSON文件

        Args:
            analysis_result: 分析结果字典
            output_filename: 输出文件名，默认自动生成

        Returns:
            str: 输出文件路径
        """
        if output_filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"frame_analysis_{timestamp}.json"

        output_path = self.output_dir / output_filename

        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(analysis_result, f, ensure_ascii=False, indent=2)

        logger.success(f"✅ 分析结果已导出: {output_path}")

        return str(output_path)

    @staticmethod
    def _seconds_to_timestamp(seconds: float) -> str:
        """
        将秒数转换为HH:MM:SS格式

        Args:
            seconds: 秒数

        Returns:
            str: 格式化时间戳
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# 便捷使用函数
def analyze_video(
    video_path: str,
    llm_api_key: str,
    llm_base_url: str,
    llm_model: str,
    interval_seconds: float = 3.0,
    max_frames: int = 100,
    batch_size: int = 5,
    output_dir: Optional[str] = None
) -> str:
    """
    一键分析视频并返回结果JSON路径

    Args:
        video_path: 视频文件路径
        llm_api_key: LLM API密钥
        llm_base_url: LLM API基础URL
        llm_model: 模型名称
        interval_seconds: 帧提取间隔（秒）
        max_frames: 最大提取帧数
        batch_size: 批次大小
        output_dir: 输出目录

    Returns:
        str: 分析结果JSON文件路径
    """
    analyzer = VideoAnalyzer(output_dir=output_dir)

    # 1. 提取关键帧
    logger.info("🎬 步骤1: 提取视频关键帧")
    key_frames = analyzer.extract_key_frames(
        video_path=video_path,
        interval_seconds=interval_seconds,
        max_frames=max_frames
    )

    # 2. AI分析
    logger.info("🤖 步骤2: AI分析画面内容")
    analysis_result = analyzer.analyze_frames_with_llm(
        key_frames=key_frames,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        batch_size=batch_size
    )

    # 3. 导出结果
    logger.info("💾 步骤3: 导出分析结果")
    json_path = analyzer.export_analysis_json(analysis_result)

    logger.success(f"🎉 视频分析完成！结果文件: {json_path}")

    return json_path


if __name__ == '__main__':
    # 测试代码
    test_video_path = "test_video.mp4"
    test_api_key = "sk-xxx"
    test_base_url = "https://api.openai.com/v1"
    test_model = "gpt-4-vision-preview"

    if os.path.exists(test_video_path):
        result_json = analyze_video(
            video_path=test_video_path,
            llm_api_key=test_api_key,
            llm_base_url=test_base_url,
            llm_model=test_model,
            interval_seconds=3.0,
            max_frames=50
        )
        print(f"分析结果: {result_json}")
    else:
        print(f"测试视频不存在: {test_video_path}")
