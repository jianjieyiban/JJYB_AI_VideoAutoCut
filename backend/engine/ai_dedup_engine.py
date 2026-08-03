#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : ai_dedup_engine.py
@Desc   : AI智能去重引擎 - 融入JJYB-ZJ的AI智能去重功能
          随机片段放大 / 水平镜像 / 调色 / 旋转，每段独立按概率命中
          + 覆盖视频轨方案（低不透明度+低音量盖在主轨之上）
"""

import os
import random
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class DedupConfig:
    """AI智能去重配置"""
    # 片段级变换（每段独立按概率命中）
    enable_zoom: bool = True          # 随机片段放大
    zoom_probability: float = 0.3     # 命中概率
    zoom_range: Tuple[float, float] = (1.05, 1.15)  # 放大倍数范围

    enable_mirror: bool = True        # 水平镜像
    mirror_probability: float = 0.2   # 命中概率

    enable_color: bool = True         # 调色
    color_probability: float = 0.4    # 命中概率
    saturation_range: Tuple[float, float] = (0.9, 1.1)   # 饱和度
    temperature_range: Tuple[float, float] = (-0.05, 0.05)  # 色温
    tint_range: Tuple[float, float] = (-0.05, 0.05)      # 色调

    enable_rotate: bool = False       # 旋转（默认关闭，影响画面较大）
    rotate_probability: float = 0.1
    rotate_range: Tuple[float, float] = (-1.0, 1.0)  # 旋转角度范围

    # 全局参数
    enable_overlay_video: bool = False  # 启用覆盖视频轨
    overlay_video_path: str = ''        # 覆盖视频路径
    overlay_opacity: float = 0.15       # 覆盖不透明度
    overlay_volume: float = 0.05        # 覆盖音量

    # 全局视频参数
    global_volume: float = 1.0          # 主视频音量
    global_opacity: float = 1.0         # 主视频不透明度

    # 输出参数
    seed: Optional[int] = None          # 随机种子（None=随机）


@dataclass
class SegmentTransform:
    """单段视频的变换方案"""
    segment_index: int
    start_time: float
    end_time: float
    zoom: float = 1.0
    mirror: bool = False
    saturation: float = 1.0
    temperature: float = 0.0
    tint: float = 0.0
    rotate: float = 0.0
    has_transform: bool = False


class AIDedupEngine:
    """AI智能去重引擎"""

    def __init__(self, config: Optional[DedupConfig] = None):
        self.config = config or DedupConfig()
        if self.config.seed is not None:
            random.seed(self.config.seed)
        logger.info("AI智能去重引擎初始化完成")

    def plan_transforms(self, segments: List[Dict]) -> List[SegmentTransform]:
        """为每个片段生成变换方案"""
        plans = []
        for i, seg in enumerate(segments):
            plan = SegmentTransform(
                segment_index=i,
                start_time=seg.get('start', 0.0),
                end_time=seg.get('end', 0.0)
            )

            # 随机放大
            if self.config.enable_zoom and random.random() < self.config.zoom_probability:
                plan.zoom = random.uniform(*self.config.zoom_range)
                plan.has_transform = True

            # 随机镜像
            if self.config.enable_mirror and random.random() < self.config.mirror_probability:
                plan.mirror = True
                plan.has_transform = True

            # 随机调色
            if self.config.enable_color and random.random() < self.config.color_probability:
                plan.saturation = random.uniform(*self.config.saturation_range)
                plan.temperature = random.uniform(*self.config.temperature_range)
                plan.tint = random.uniform(*self.config.tint_range)
                plan.has_transform = True

            # 随机旋转
            if self.config.enable_rotate and random.random() < self.config.rotate_probability:
                plan.rotate = random.uniform(*self.config.rotate_range)
                plan.has_transform = True

            plans.append(plan)

        transformed_count = sum(1 for p in plans if p.has_transform)
        logger.info(f"AI去重方案生成完成：{len(plans)}段，{transformed_count}段有变换")
        return plans

    def build_ffmpeg_filter(self, plan: SegmentTransform) -> str:
        """为单个片段构建ffmpeg filter字符串"""
        filters = []

        # 放大（用scale+crop实现）
        if plan.zoom > 1.0:
            # 放大后裁剪回原尺寸
            filters.append(f"scale=iw*{plan.zoom}:ih*{plan.zoom}")
            filters.append(f"crop=iw/{plan.zoom}:ih/{plan.zoom}")

        # 镜像
        if plan.mirror:
            filters.append("hflip")

        # 调色
        if plan.saturation != 1.0 or plan.temperature != 0 or plan.tint != 0:
            eq_parts = []
            if plan.saturation != 1.0:
                eq_parts.append(f"saturation={plan.saturation}")
            if plan.temperature != 0:
                # 色温用r/g/b gain近似
                eq_parts.append(f"r='r+{plan.temperature*20}':b='b-{plan.temperature*20}'")
            if plan.tint != 0:
                eq_parts.append(f"g='g+{plan.tint*20}'")
            filters.append("eq=" + ":".join(eq_parts))

        # 旋转
        if plan.rotate != 0:
            filters.append(f"rotate={plan.rotate}*PI/180:fillcolor=black")

        return ",".join(filters)

    def build_global_filters(self) -> str:
        """构建全局滤镜"""
        filters = []
        if self.config.global_opacity < 1.0:
            filters.append(f"format=rgba,colorchannelmixer=aa={self.config.global_opacity}")
        return ",".join(filters)

    def generate_overlay_video_track(self, total_duration: float, output_path: str) -> Optional[str]:
        """生成覆盖视频轨"""
        if not self.config.enable_overlay_video or not self.config.overlay_video_path:
            return None
        if not os.path.exists(self.config.overlay_video_path):
            logger.warning(f"覆盖视频文件不存在: {self.config.overlay_video_path}")
            return None

        try:
            # 循环铺满总时长，并设置不透明度和音量
            cmd = [
                'ffmpeg', '-y',
                '-stream_loop', '-1',
                '-i', self.config.overlay_video_path,
                '-t', str(total_duration),
                '-vf', f"format=rgba,colorchannelmixer=aa={self.config.overlay_opacity}",
                '-af', f"volume={self.config.overlay_volume}",
                '-c:v', 'libx264', '-preset', 'fast',
                '-c:a', 'aac',
                output_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode == 0:
                logger.info(f"覆盖视频轨生成完成: {output_path}")
                return output_path
            else:
                logger.error(f"覆盖视频轨生成失败: {result.stderr[-500:]}")
                return None
        except Exception as e:
            logger.error(f"覆盖视频轨生成异常: {e}")
            return None

    def get_plan_summary(self, plans: List[SegmentTransform]) -> Dict:
        """获取去重方案摘要"""
        total = len(plans)
        transformed = sum(1 for p in plans if p.has_transform)
        zoomed = sum(1 for p in plans if p.zoom > 1.0)
        mirrored = sum(1 for p in plans if p.mirror)
        colored = sum(1 for p in plans if p.saturation != 1.0 or p.temperature != 0 or p.tint != 0)
        rotated = sum(1 for p in plans if p.rotate != 0)
        return {
            'total_segments': total,
            'transformed_segments': transformed,
            'zoom_applied': zoomed,
            'mirror_applied': mirrored,
            'color_applied': colored,
            'rotate_applied': rotated,
            'transform_ratio': round(transformed / total, 2) if total else 0,
            'overlay_video_enabled': self.config.enable_overlay_video
        }


class HighlightSelector:
    """高光选择器 - 智能穿插原片功能"""

    def __init__(self):
        logger.info("高光选择器初始化完成")

    def score_scenes(self, scenes: List[Dict]) -> List[Dict]:
        """为每个场景打分，找出高光片段"""
        scored = []
        for i, scene in enumerate(scenes):
            score = self._calculate_scene_score(scene, i, len(scenes))
            scored.append({
                **scene,
                'highlight_score': score,
                'scene_index': i
            })
        # 按分数降序排序
        scored.sort(key=lambda x: x['highlight_score'], reverse=True)
        return scored

    def _calculate_scene_score(self, scene: Dict, index: int, total: int) -> float:
        """计算场景的高光分数"""
        score = 0.0

        # 1. 场景描述中的高能关键词
        desc = scene.get('description', '').lower()
        highlight_keywords = [
            '高潮', '爆发', '冲突', '战斗', '追逐', '惊险', '震撼',
            '爆炸', '争吵', '对决', '反转', '揭晓', '真相', '死亡',
            '哭', '笑', '怒', '惊', '怕', '爱'
        ]
        for kw in highlight_keywords:
            if kw in desc:
                score += 2.0

        # 2. 场景时长（中等时长的场景更可能是高光）
        duration = scene.get('end', 0) - scene.get('start', 0)
        if 3.0 <= duration <= 15.0:
            score += 1.5
        elif duration > 15.0:
            score += 0.5

        # 3. 场景位置（开头的场景更适合做钩子）
        if index == 0:
            score += 1.0
        elif index == total - 1:
            score += 0.5  # 结尾场景

        # 4. 动作描述
        action_keywords = ['跑', '跳', '打', '冲', '抓', '扔', '摔', '飞']
        for kw in action_keywords:
            if kw in desc:
                score += 1.0

        # 5. 情绪描述
        emotion_keywords = ['激动', '愤怒', '开心', '悲伤', '恐惧', '惊讶']
        for kw in emotion_keywords:
            if kw in desc:
                score += 1.0

        return round(score, 2)

    def select_highlights(self, scenes: List[Dict], count: int = 3, min_duration: float = 3.0) -> List[Dict]:
        """选择指定数量的高光片段"""
        scored = self.score_scenes(scenes)
        highlights = []
        for scene in scored:
            duration = scene.get('end', 0) - scene.get('start', 0)
            if duration >= min_duration:
                highlights.append(scene)
                if len(highlights) >= count:
                    break
        return highlights

    def select_hook_scene(self, scenes: List[Dict]) -> Optional[Dict]:
        """选择最适合做开头钩子的场景"""
        if not scenes:
            return None
        scored = self.score_scenes(scenes)
        return scored[0] if scored else None


class CoverageAuditEngine:
    """覆盖审计引擎 - 检查文案与视频的时间覆盖情况"""

    def __init__(self):
        logger.info("覆盖审计引擎初始化完成")

    def audit_coverage(
        self,
        video_duration: float,
        scenes: List[Dict],
        narrations: List[Dict],
        gap_threshold: float = 5.0
    ) -> Dict:
        """
        审计文案与视频的覆盖情况

        Args:
            video_duration: 视频总时长（秒）
            scenes: 场景列表 [{start, end, description}]
            narrations: 文案列表 [{start, end, text}]
            gap_threshold: 时间断层阈值（秒）
        """
        # 1. 占位命中率
        placeholder_count = 0
        for nar in narrations:
            has_match = any(
                self._is_time_overlap(nar, scene) for scene in scenes
            )
            if not has_match:
                placeholder_count += 1
        placeholder_ratio = placeholder_count / len(narrations) if narrations else 0

        # 2. 时间断层检测
        gaps = []
        if narrations:
            sorted_nar = sorted(narrations, key=lambda x: x.get('start', 0))
            for i in range(1, len(sorted_nar)):
                prev_end = sorted_nar[i-1].get('end', 0)
                curr_start = sorted_nar[i].get('start', 0)
                gap = curr_start - prev_end
                if gap > gap_threshold:
                    gaps.append({
                        'start': prev_end,
                        'end': curr_start,
                        'duration': round(gap, 2)
                    })

        # 3. 尾部覆盖检查
        tail_threshold = video_duration * 0.8
        tail_coverage = any(
            nar.get('end', 0) >= tail_threshold for nar in narrations
        )

        # 4. 重复匹配检测
        scene_usage = {}
        for nar in narrations:
            for scene in scenes:
                if self._is_time_overlap(nar, scene):
                    scene_idx = scene.get('id', f"{scene.get('start')}-{scene.get('end')}")
                    scene_usage.setdefault(scene_idx, []).append(nar.get('text', '')[:30])
        duplicates = {k: v for k, v in scene_usage.items() if len(v) > 2}

        # 5. 综合评分
        score = self._calculate_overall_score(
            placeholder_ratio, len(gaps), tail_coverage, len(duplicates)
        )

        return {
            'placeholder_ratio': round(placeholder_ratio, 2),
            'placeholder_count': placeholder_count,
            'gap_count': len(gaps),
            'gap_details': gaps,
            'tail_coverage': tail_coverage,
            'duplicate_matches': duplicates,
            'overall_score': score,
            'suggestions': self._generate_suggestions(
                placeholder_ratio, len(gaps), tail_coverage, len(duplicates)
            )
        }

    def _is_time_overlap(self, a: Dict, b: Dict) -> bool:
        """检查两个时间段是否有重叠"""
        a_start, a_end = a.get('start', 0), a.get('end', 0)
        b_start, b_end = b.get('start', 0), b.get('end', 0)
        return not (a_end <= b_start or a_start >= b_end)

    def _calculate_overall_score(
        self, placeholder_ratio: float, gap_count: int,
        tail_coverage: bool, duplicate_count: int
    ) -> float:
        """计算综合覆盖评分"""
        score = 100.0
        score -= placeholder_ratio * 40  # 占位率高扣分
        score -= gap_count * 5           # 断层扣分
        if not tail_coverage:
            score -= 15                   # 尾部未覆盖扣分
        score -= duplicate_count * 3     # 重复匹配扣分
        return max(0.0, round(score, 2))

    def _generate_suggestions(
        self, placeholder_ratio: float, gap_count: int,
        tail_coverage: bool, duplicate_count: int
    ) -> List[str]:
        """生成改进建议"""
        suggestions = []
        if placeholder_ratio > 0.3:
            suggestions.append("占位画面过多，建议补充场景描述或调整文案时间戳")
        if gap_count > 0:
            suggestions.append(f"检测到{gap_count}处时间断层，建议在断层处补充文案或调整时间戳")
        if not tail_coverage:
            suggestions.append("视频尾部未覆盖文案，建议补充结尾文案")
        if duplicate_count > 0:
            suggestions.append(f"检测到{duplicate_count}处场景被多次匹配，建议分散场景选择")
        if not suggestions:
            suggestions.append("覆盖情况良好，无需调整")
        return suggestions


class ForceAlignEngine:
    """音画强制对齐引擎 - 配音略长于原片时双向微调"""

    def __init__(self):
        logger.info("音画强制对齐引擎初始化完成")

    def align(
        self,
        segments: List[Dict],
        max_video_speed: float = 1.05,
        max_audio_speed: float = 1.05,
        min_duration: float = 0.5
    ) -> List[Dict]:
        """
        对齐音画时长

        Args:
            segments: 分镜列表，每个包含video_duration和audio_duration
            max_video_speed: 视频最大加速倍数
            max_audio_speed: 音频最大加速倍数
            min_duration: 最小有效时长
        """
        aligned = []
        for seg in segments:
            video_dur = seg.get('video_duration', 0)
            audio_dur = seg.get('audio_duration', 0)

            if video_dur <= 0 or audio_dur <= 0:
                aligned.append(seg)
                continue

            diff = audio_dur - video_dur  # 正数=音频长于视频

            if abs(diff) < 0.3:
                # 差异很小，不调整
                aligned.append({**seg, 'align_action': 'none', 'video_speed': 1.0, 'audio_speed': 1.0})
                continue

            if diff > 0:
                # 音频长于视频：视频加速 + 音频轻微减速
                video_speed = min(max_video_speed, 1.0 + diff / video_dur * 0.5)
                audio_speed = max(1.0 / max_audio_speed, video_dur / audio_dur)
                aligned.append({
                    **seg,
                    'align_action': 'audio_longer',
                    'video_speed': round(video_speed, 3),
                    'audio_speed': round(audio_speed, 3),
                    'adjusted_video_duration': round(video_dur / video_speed, 3),
                    'adjusted_audio_duration': round(audio_dur / audio_speed, 3)
                })
            else:
                # 视频长于音频：音频加速 + 视频轻微减速
                audio_speed = min(max_audio_speed, 1.0 + (-diff) / audio_dur * 0.5)
                video_speed = max(1.0 / max_video_speed, audio_dur / video_dur)
                aligned.append({
                    **seg,
                    'align_action': 'video_longer',
                    'video_speed': round(video_speed, 3),
                    'audio_speed': round(audio_speed, 3),
                    'adjusted_video_duration': round(video_dur / video_speed, 3),
                    'adjusted_audio_duration': round(audio_dur / audio_speed, 3)
                })

        return aligned
