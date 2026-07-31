#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : curated_remake_engine.py
@Desc   : 精选视频复刻引擎 - 融入JJYB-ZJ的curated_remake功能
          参考视频复刻新视频，多原片匹配，存疑高亮标记
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class RemakeConfig:
    """复刻配置"""
    # 匹配参数
    match_threshold: float = 0.6       # 匹配置信度阈值
    suspect_threshold: float = 0.4     # 存疑阈值（低于此值标记为存疑）
    max_clips_per_narration: int = 3   # 每段解说最多匹配的片段数
    min_clip_duration: float = 1.0     # 最小片段时长
    max_clip_duration: float = 30.0    # 最大片段时长

    # 跨集匹配
    enable_cross_video: bool = True    # 启用跨视频匹配
    prefer_same_video: bool = True     # 优先选择同一视频的片段

    # 仅复刻模式
    remix_mode: str = 'remake'         # remake=仅复刻 / cover=覆盖模式
    keep_original_audio: bool = True   # 仅复刻模式保留解说原声
    narration_volume: float = 1.0      # 解说轨音量
    original_volume: float = 0.5       # 原片音量

    # 输出
    export_suspect_list: bool = True   # 导出存疑清单


@dataclass
class MatchResult:
    """单段匹配结果"""
    narration_index: int
    narration_text: str
    tts_duration: float
    clip_count: int
    clip_duration: float
    clip_range: str
    scene_ids: List[int]
    confidence: float
    is_suspect: bool = False
    source_video: str = ''


class CuratedRemakeEngine:
    """精选视频复刻引擎"""

    def __init__(self, config: Optional[RemakeConfig] = None):
        self.config = config or RemakeConfig()
        logger.info("精选视频复刻引擎初始化完成")

    def match_narrations_to_scenes(
        self,
        narrations: List[Dict],
        scenes_by_video: Dict[str, List[Dict]],
        tts_durations: Optional[List[float]] = None
    ) -> List[MatchResult]:
        """
        将解说文案匹配到视频场景

        Args:
            narrations: 解说文案列表 [{index, text, start, end}]
            scenes_by_video: 按视频分组的场景 {video_path: [{id, start, end, description}]}
            tts_durations: TTS配音时长列表
        """
        results = []
        used_scenes = set()  # 已使用的场景（避免重复）

        for i, nar in enumerate(narrations):
            tts_dur = tts_durations[i] if tts_durations and i < len(tts_durations) else 3.0

            # 为该文案找候选场景
            candidates = self._find_candidates(
                nar, scenes_by_video, used_scenes, tts_dur
            )

            if not candidates:
                # 无候选，标记为存疑
                results.append(MatchResult(
                    narration_index=i,
                    narration_text=nar.get('text', '')[:50],
                    tts_duration=tts_dur,
                    clip_count=0,
                    clip_duration=0,
                    clip_range="0.0-0.0",
                    scene_ids=[],
                    confidence=0.0,
                    is_suspect=True
                ))
                continue

            # 选择最佳候选
            best = candidates[0]
            confidence = best.get('score', 0.0)

            # 标记场景为已使用
            scene_id = best.get('id', 0)
            video_path = best.get('video_path', '')
            scene_key = f"{video_path}_{scene_id}"
            used_scenes.add(scene_key)

            # 计算片段时长
            clip_dur = best.get('end', 0) - best.get('start', 0)

            result = MatchResult(
                narration_index=i,
                narration_text=nar.get('text', '')[:50],
                tts_duration=tts_dur,
                clip_count=1,
                clip_duration=round(clip_dur, 2),
                clip_range=f"{best.get('start', 0)}-{best.get('end', 0)}",
                scene_ids=[scene_id],
                confidence=round(confidence, 3),
                is_suspect=confidence < self.config.suspect_threshold,
                source_video=video_path
            )
            results.append(result)

        return results

    def _find_candidates(
        self,
        narration: Dict,
        scenes_by_video: Dict[str, List[Dict]],
        used_scenes: set,
        target_duration: float
    ) -> List[Dict]:
        """为单段文案查找候选场景"""
        candidates = []

        nar_text = narration.get('text', '').lower()

        for video_path, scenes in scenes_by_video.items():
            for scene in scenes:
                # 跳过已使用的场景
                scene_key = f"{video_path}_{scene.get('id', 0)}"
                if scene_key in used_scenes and self.config.prefer_same_video:
                    continue

                # 计算匹配分数
                score = self._calculate_match_score(nar_text, scene, target_duration)

                if score >= self.config.match_threshold:
                    candidates.append({
                        **scene,
                        'video_path': video_path,
                        'score': score
                    })

        # 按分数排序
        candidates.sort(key=lambda x: x['score'], reverse=True)

        # 限制候选数量
        return candidates[:self.config.max_clips_per_narration]

    def _calculate_match_score(
        self,
        narration_text: str,
        scene: Dict,
        target_duration: float
    ) -> float:
        """计算文案与场景的匹配分数"""
        score = 0.0
        scene_desc = scene.get('description', '').lower()

        # 1. 关键词匹配
        nar_words = set(narration_text.split())
        scene_words = set(scene_desc.split())
        if nar_words and scene_words:
            overlap = len(nar_words & scene_words)
            score += (overlap / max(len(nar_words), 1)) * 0.4

        # 2. 时长匹配
        scene_dur = scene.get('end', 0) - scene.get('start', 0)
        if scene_dur > 0 and target_duration > 0:
            dur_ratio = min(scene_dur, target_duration) / max(scene_dur, target_duration)
            score += dur_ratio * 0.3

        # 3. 场景质量（有描述的加分）
        if scene_desc:
            score += 0.2
        if len(scene_desc) > 20:
            score += 0.1

        return min(score, 1.0)

    def generate_match_report(self, results: List[MatchResult]) -> Dict:
        """生成匹配报告"""
        total = len(results)
        matched = sum(1 for r in results if r.clip_count > 0)
        suspect = sum(1 for r in results if r.is_suspect)
        avg_confidence = sum(r.confidence for r in results) / total if total else 0

        # 按视频分组统计
        video_stats = {}
        for r in results:
            if r.source_video:
                video_stats[r.source_video] = video_stats.get(r.source_video, 0) + 1

        return {
            'total_narrations': total,
            'matched_count': matched,
            'suspect_count': suspect,
            'match_rate': round(matched / total, 2) if total else 0,
            'suspect_rate': round(suspect / total, 2) if total else 0,
            'avg_confidence': round(avg_confidence, 3),
            'video_distribution': video_stats,
            'suspect_list': [
                {
                    'narration_index': r.narration_index,
                    'narration_text': r.narration_text,
                    'confidence': r.confidence
                }
                for r in results if r.is_suspect
            ]
        }

    def export_suspect_list(self, results: List[MatchResult], output_path: str) -> str:
        """导出存疑清单"""
        suspect_list = [
            f"[{r.narration_index}] 置信度: {r.confidence} | 文案: {r.narration_text}"
            for r in results if r.is_suspect
        ]
        content = "=== 精选复刻存疑清单 ===\n"
        content += f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        content += f"存疑总数: {len(suspect_list)}\n\n"
        content += "\n".join(suspect_list)

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        logger.info(f"存疑清单已导出: {output_path}")
        return output_path

    def build_remake_plan(
        self,
        results: List[MatchResult],
        scenes_by_video: Dict[str, List[Dict]]
    ) -> List[Dict]:
        """构建复刻执行计划"""
        plan = []
        for r in results:
            if r.clip_count == 0:
                continue

            # 获取场景详情
            scenes = scenes_by_video.get(r.source_video, [])
            selected_scenes = [s for s in scenes if s.get('id') in r.scene_ids]

            plan.append({
                'narration_index': r.narration_index,
                'narration_text': r.narration_text,
                'tts_duration': r.tts_duration,
                'source_video': r.source_video,
                'clip_range': r.clip_range,
                'clip_duration': r.clip_duration,
                'scenes': selected_scenes,
                'confidence': r.confidence,
                'is_suspect': r.is_suspect,
                'audio_config': {
                    'narration_volume': self.config.narration_volume,
                    'original_volume': self.config.original_volume,
                    'keep_original_audio': self.config.keep_original_audio
                }
            })

        return plan
