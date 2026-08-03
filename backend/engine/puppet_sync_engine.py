# -*- coding: utf-8 -*-
"""
PuppetSyncEngine - 拟人化字画音画同步引擎
实现用户核心需求：
  1. 每段语音匹配一个画面，画面不重复
  2. 画面 < 配音时长 → 变速慢放或定格末帧匹配音频时长
  3. 画面 > 配音时长 → 智能选取重要部分（高光），其余切割
  4. 一个画面匹配一段配音；非常短的配音允许两段配音共用一个画面
  5. 智能灵活匹配，做到真正的拟人手法
"""

import logging
import math
import os
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger('JJYB_AI智剪')


class PuppetSyncEngine:
    """拟人化同步引擎：画面 ↔ 配音 ↔ 字幕 三对齐"""

    # 极短配音阈值（秒）：低于此值的配音允许与相邻配音共用一个画面
    SHORT_VOICE_THRESHOLD = 1.2
    # 变速上限（避免画面失真）：最快 2x，最慢 0.25x
    SPEED_MIN = 0.25
    SPEED_MAX = 2.0
    # 对配音时长的纠正必须处于可理解的语速范围内。
    VOICE_SPEED_MIN = 0.85
    VOICE_SPEED_MAX = 1.15
    TIMELINE_EPSILON = 0.005
    ENCODING_DURATION_EPSILON = 0.05
    # Workbench output is a review render.  Keeping the intermediate clips
    # compatible lets concat join them without a second full-resolution pass.
    PREVIEW_PRESET = 'veryfast'
    PREVIEW_CRF = '21'

    @staticmethod
    def _shot_key(shot: Dict[str, Any], index: int) -> Tuple[str, str, int]:
        """用来源、外部 id 和列表位置共同标识内部镜头，避免重复外部 id 冲突。"""
        source = str(shot.get('source_video') or shot.get('source_video_path') or shot.get('video_path') or shot.get('source_path') or '')
        return source, str(shot.get('id', '')), index

    def _rebuild_item_strategy(self, item: Dict[str, Any], final_duration: float) -> None:
        """按实际源窗口重建策略，保证 FFmpeg 输出时长等于 final_duration。"""
        final_duration = round(max(0.05, float(final_duration)), 3)
        source_start = float(item.get('shot_start', item.get('source_start', 0.0)) or 0.0)
        source_end = float(item.get('shot_end', item.get('source_end', source_start)) or source_start)
        available = source_end - source_start
        if not math.isfinite(available) or available <= 0:
            raise ValueError('无法为片段重建有效的半开源区间')

        item['final_duration'] = round(final_duration, 3)
        item['audio_duration'] = round(final_duration, 3)
        item['freeze_tail'] = False
        item.pop('freeze_duration', None)
        if available >= final_duration - self.TIMELINE_EPSILON:
            # 不需要变速时，截取一个长度严格等于目标的窗口。
            start = source_start + max(0.0, (available - final_duration) / 2.0)
            item.update({
                'cut_strategy': 'direct' if abs(available - final_duration) <= self.TIMELINE_EPSILON else 'cut_highlight',
                'speed_factor': 1.0,
                'source_start': round(start, 3),
                'source_end': round(start + final_duration, 3),
            })
            return

        speed = available / final_duration
        if speed >= self.SPEED_MIN:
            item.update({
                'cut_strategy': 'slow_down',
                'speed_factor': speed,
                'source_start': round(source_start, 3),
                'source_end': round(source_end, 3),
            })
            return

        raise ValueError(
            '镜头源区间 %.3fs 即使以 SPEED_MIN=%.2f 慢放也无法匹配 %.3fs 解说；拒绝生成定格补帧策略' %
            (available, self.SPEED_MIN, final_duration)
        )

    def _expected_render_duration(self, item: Dict[str, Any]) -> float:
        """纯函数：按策略计算预期视频输出时长，供规划与测试共用。"""
        source_duration = float(item['source_end']) - float(item['source_start'])
        strategy = item.get('cut_strategy', 'direct')
        if strategy in {'direct', 'cut_highlight'}:
            return source_duration
        if strategy == 'slow_down':
            return source_duration / float(item.get('speed_factor', 1.0))
        if strategy == 'freeze':
            return source_duration / float(item.get('speed_factor', 1.0)) + float(item.get('freeze_duration', 0.0))
        raise ValueError('未知剪辑策略: %s' % strategy)

    def _finalize_timeline(self, timeline: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """写入连续半开时间线区间，并在渲染前拒绝不完整时间线。"""
        cursor = 0.0
        for item in timeline:
            duration = float(item.get('final_duration', item.get('audio_duration', 0)) or 0)
            if not math.isfinite(duration) or duration <= 0:
                raise ValueError('时间线包含零时长或无效片段')
            item['final_duration'] = round(duration, 3)
            item['timeline_start'] = round(cursor, 3)
            cursor += duration
            item['timeline_end'] = round(cursor, 3)
        self._validate_timeline(timeline)
        return timeline

    def _validate_timeline(self, timeline: List[Dict[str, Any]]) -> None:
        """校验时间线无重叠、空洞及无效的半开源区间。"""
        cursor = 0.0
        previous_source_starts: Dict[str, float] = {}
        for index, item in enumerate(timeline):
            try:
                start, end = float(item['timeline_start']), float(item['timeline_end'])
                source_start, source_end = float(item['source_start']), float(item['source_end'])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError('时间线片段缺少有效时间边界: %s' % index) from exc
            if not all(math.isfinite(value) for value in (start, end, source_start, source_end)):
                raise ValueError('时间线片段包含非有限时间: %s' % index)
            if end - start <= 0 or abs(start - cursor) > self.TIMELINE_EPSILON:
                raise ValueError('时间线存在重叠、空洞或零时长片段: %s' % index)
            duration = float(item.get('final_duration', item.get('audio_duration', 0)) or 0)
            expected = self._expected_render_duration(item)
            if abs(expected - duration) > self.TIMELINE_EPSILON:
                raise ValueError('时间线视频策略与目标时长不一致: %s (预计 %.3fs，目标 %.3fs)' % (index, expected, duration))
            if source_start < 0 or source_end <= source_start:
                raise ValueError('时间线源区间必须是有效半开区间: %s' % index)
            if item.get('original_audio'):
                source = str(item.get('source_video') or '')
                previous = previous_source_starts.get(source)
                if previous is not None and source_start + self.TIMELINE_EPSILON < previous:
                    raise ValueError('同一来源原声镜头未按 source_start 单调递增排序')
                previous_source_starts[source] = source_start
            cursor = end

    def __init__(self):
        self.logger = logger
        self.last_original_audio_summary: Dict[str, Any] = {
            'requested': 0,
            'inserted': 0,
            'skipped_reason': [],
        }

    # ------------------------------------------------------------------ #
    # 核心匹配 API
    # ------------------------------------------------------------------ #
    def match_shots_to_voices(
        self,
        shots: List[Dict[str, Any]],
        voices: List[Dict[str, Any]],
        allow_reuse: bool = False,
        insert_original_audio: bool = False,
        original_clip_interval: int = 3,
        original_clip_duration: float = 3.0,
        original_audio_volume: float = 1.0,
        target_duration_seconds: Optional[float] = None,
        original_audio_mode: str = 'interval',
        original_audio_ratio: Optional[float] = None,
        original_audio_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """将镜头匹配至配音；比例模式按目标成片时长精确安排未分配镜头的原声。"""
        self.logger.info('🎯 开始拟人化匹配: %s 个镜头 ↔ %s 段配音', len(shots), len(voices))
        if not shots or not voices:
            self.logger.warning('⚠️ 镜头或配音为空，无法匹配')
            return []

        # Each narration item must retain its own visual and subtitle timing.
        # Grouping short lines made a single subtitle span cover unrelated lines
        # and prevented the planner from making a one-to-one semantic assignment.
        voice_groups = [[dict(voice)] for voice in voices]
        timeline: List[Dict[str, Any]] = []
        used_shot_keys, shot_idx = set(), 0
        for g_idx, group in enumerate(voice_groups):
            audio_duration = sum(float(v.get('duration', 0) or 0) for v in group)
            candidate, candidate_idx = self._pick_next_shot(shots, used_shot_keys, shot_idx, allow_reuse, audio_duration)
            if candidate is None:
                raise ValueError('第 %s 组配音没有可用镜头，拒绝生成会错位的成片' % g_idx)
            shot_idx = candidate_idx + 1
            if not allow_reuse:
                used_shot_keys.add(self._shot_key(candidate, candidate_idx))
            match = self._compute_match_strategy(candidate, audio_duration)
            match.update({
                'shot_id': candidate['id'], 'voice_indices': [v.get('index', i) for i, v in enumerate(group)],
                'voice_paths': [v.get('voice_path', '') for v in group], 'subtitle_text': ''.join(v.get('text', '') for v in group),
                'audio_duration': round(audio_duration, 3), 'source_audio_duration': round(audio_duration, 3), 'shot_start': round(float(candidate.get('start_time', 0) or 0), 3),
                'shot_end': round(float(candidate.get('end_time', float(candidate.get('start_time', 0) or 0) + float(candidate.get('duration', 0) or 0)) or 0), 3), 'shot_duration': round(float(candidate.get('duration', 0) or 0), 3),
                'scene_type': candidate.get('scene_type', 'neutral'), 'shot_score': candidate.get('score', 0.5),
                'source_video': candidate.get('source_video') or candidate.get('source_video_path') or candidate.get('video_path') or candidate.get('source_path') or '',
            })
            self._rebuild_item_strategy(match, audio_duration)
            timeline.append(match)

        try:
            original_audio_volume = max(0.0, min(1.0, float(original_audio_volume)))
        except (TypeError, ValueError):
            original_audio_volume = 1.0
        mode = str(original_audio_mode or 'interval').lower()
        audio_candidates = original_audio_candidates if original_audio_candidates is not None else shots
        if mode == 'ratio' and insert_original_audio and target_duration_seconds and original_audio_ratio is not None:
            return self._apply_ratio_original_audio(
                timeline, audio_candidates, used_shot_keys, float(target_duration_seconds), original_audio_ratio,
                max(0.1, float(original_clip_duration or 3.0)), original_audio_volume,
            )
        return self._apply_interval_original_audio(
            timeline, audio_candidates, used_shot_keys, insert_original_audio, original_clip_interval,
            original_clip_duration, original_audio_volume, target_duration_seconds,
        )

    def _apply_interval_original_audio(self, timeline, shots, used_for_voice, enabled, interval, clip_duration, volume, target_total=None):
        warnings = []
        if not enabled:
            enriched = list(timeline)
            self.last_original_audio_summary = {'mode': 'interval', 'requested': 0, 'inserted': 0, 'skipped_reason': ['未启用原声穿插'], 'warnings': warnings}
        else:
            interval, clip_duration = max(1, int(interval or 3)), max(0.1, float(clip_duration or 3.0))
            remaining = [
                (s, i) for i, s in enumerate(shots)
                if self._shot_key(s, i) not in used_for_voice
            ]
            consumed_until: Dict[str, float] = {}
            requested, inserted, skipped, enriched = len(timeline) // interval, 0, [], []
            for index, item in enumerate(timeline, 1):
                enriched.append(item)
                if index % interval:
                    continue
                previous_source = str(item.get('source_video') or '')
                previous_end = float(item.get('source_end', item.get('shot_end', 0)) or 0)
                eligible = [
                    pair for pair in remaining
                    if float(pair[0].get('duration', 0) or 0) >= clip_duration
                    and float(pair[0].get('start_time', 0) or 0) + self.TIMELINE_EPSILON >= consumed_until.get(
                        str(pair[0].get('source_video') or pair[0].get('source_video_path') or pair[0].get('video_path') or pair[0].get('source_path') or ''),
                        float('-inf'),
                    )
                ]
                same_source = [
                    pair for pair in eligible
                    if str(pair[0].get('source_video') or pair[0].get('source_video_path') or pair[0].get('video_path') or pair[0].get('source_path') or '') == previous_source
                    and float(pair[0].get('start_time', 0) or 0) + self.TIMELINE_EPSILON >= previous_end
                ]
                if same_source:
                    source, source_idx = min(
                        same_source,
                        key=lambda pair: (float(pair[0].get('start_time', 0) or 0) - previous_end, pair[1]),
                    )
                    reason = 'interval_same_source_after_previous'
                elif eligible:
                    source, source_idx = min(
                        eligible,
                        key=lambda pair: (
                            abs(float(pair[0].get('start_time', 0) or 0) - previous_end),
                            str(pair[0].get('source_video') or pair[0].get('source_video_path') or pair[0].get('video_path') or pair[0].get('source_path') or ''),
                            pair[1],
                        ),
                    )
                    reason = 'interval_global_nearest_source_time'
                else:
                    skipped.append('没有满足指定原声时长且未重复消费的镜头')
                    continue
                remaining.remove((source, source_idx))
                source_name = str(source.get('source_video') or source.get('source_video_path') or source.get('video_path') or source.get('source_path') or '')
                start, duration = float(source.get('start_time', 0) or 0), clip_duration
                consumed_until[source_name] = start + duration
                self.logger.info('原声 interval 选择 shot=%s 原因=%s 前解说来源=%s 源时间=%.3f-%.3f', source.get('id'), reason, previous_source, start, start + duration)
                enriched.append(self._original_audio_item(source, start, duration, volume, reason))
                inserted += 1
            warnings = list(skipped)
            self.last_original_audio_summary = {'mode': 'interval', 'requested': requested, 'inserted': inserted, 'skipped_reason': skipped, 'warnings': warnings}

        try:
            target = float(target_total) if target_total is not None else 0.0
        except (TypeError, ValueError):
            target = 0.0
        if target > 0:
            current = sum(max(0.0, float(item.get('final_duration', 0) or 0)) for item in enriched)
            correction = target - current
            if abs(correction) > self.TIMELINE_EPSILON:
                warnings.append('目标时长差 %.3f 秒；未通过改变配音/视频时长伪造精确结果' % correction)
            self.last_original_audio_summary.update({
                'target_total_seconds': round(target, 3),
                'timeline_duration_seconds': round(current, 3),
                'timeline_duration_delta_seconds': round(current - target, 3),
                'warnings': warnings,
            })
        return self._finalize_timeline(enriched)

    def _apply_ratio_original_audio(self, timeline, shots, used_for_voice, target_total, ratio, clip_limit, volume):
        warnings, skipped = [], []
        ratio = float(ratio)
        if ratio > 1:
            ratio /= 100.0
        ratio = max(0.0, min(1.0, ratio))
        target_total = max(0.1, target_total)
        original_target = target_total * ratio
        valid_voice = [item for item in timeline if float(item.get('final_duration', 0) or 0) > 0]
        voice_total = sum(float(item['final_duration']) for item in valid_voice)
        safe_voice_budget = 0.0
        if valid_voice and ratio >= 1.0:
            safe_voice_budget = min(0.1, target_total)
            warnings.append(f'原声比例达到 100%，但存在解说；为避免解说被压缩为零，保留 {safe_voice_budget:.3f} 秒解说预算，无法精确达到原声比例')
        voice_target = max(safe_voice_budget, target_total - original_target)
        if valid_voice and voice_target <= 0:
            safe_voice_budget = min(0.1, target_total)
            voice_target = safe_voice_budget
            warnings.append('原声比例导致解说预算为零；已保留 %.3f 秒安全解说预算，无法精确达到原声比例' % safe_voice_budget)
        if not valid_voice or voice_total <= 0:
            warnings.append('没有有效解说片段，无法按比例归一化')
        else:
            desired_scale = voice_target / voice_total
            audio_speed = 1.0 / desired_scale if desired_scale > 0 else float('inf')
            if not self.VOICE_SPEED_MIN <= audio_speed <= self.VOICE_SPEED_MAX:
                warnings.append(
                    '目标比例需要 %.3fx 配音速度，超出允许范围 %.2f-%.2f；保留原始解说时长，无法伪造精确比例' %
                    (audio_speed, self.VOICE_SPEED_MIN, self.VOICE_SPEED_MAX)
                )
                voice_target = voice_total
            else:
                for item in valid_voice:
                    old = float(item['final_duration'])
                    source_audio_duration = max(0.0, float(item.get('source_audio_duration', item.get('audio_duration', old)) or 0))
                    new = old * desired_scale
                    item['source_audio_duration'] = round(source_audio_duration, 3)
                    item['audio_speed_factor'] = round(source_audio_duration / new, 6) if source_audio_duration > 0 else 1.0
                    self._rebuild_item_strategy(item, new)
        voice_budget = sum(float(item.get('final_duration', 0) or 0) for item in valid_voice)
        original_budget = max(0.0, target_total - voice_budget)
        if original_budget + 0.0005 < original_target:
            warnings.append('原声目标受保留解说预算限制，原声实际预算最多为 %.3f 秒' % original_budget)
        remaining = original_budget
        candidates = []
        for shot, index in sorted(
            ((s, i) for i, s in enumerate(shots) if self._shot_key(s, i) not in used_for_voice),
            key=lambda pair: (str(pair[0].get('source_video') or pair[0].get('source_video_path') or pair[0].get('video_path') or pair[0].get('source_path') or ''), float(pair[0].get('start_time', 0) or 0)),
        ):
            duration = max(0.0, float(shot.get('duration', 0) or 0))
            if duration > 0:
                candidates.append([shot, float(shot.get('start_time', 0) or 0), duration])
        originals = []
        while remaining > 0.0005 and candidates:
            progressed = False
            for candidate in candidates:
                if remaining <= 0.0005:
                    break
                shot, cursor, available = candidate
                if available <= 0.0005:
                    continue
                duration = min(clip_limit, available, remaining)
                originals.append(self._original_audio_item(shot, cursor, duration, volume, 'ratio_budget'))
                candidate[1], candidate[2] = cursor + duration, available - duration
                remaining -= duration
                progressed = True
            if not progressed:
                break
        actual_original = sum(float(item['final_duration']) for item in originals)
        shortfall = max(0.0, original_budget - actual_original)
        if shortfall > self.TIMELINE_EPSILON:
            skipped.append('未分配镜头素材不足，无法达到原声预算')
            warnings.append('原声预算缺少 %.3f 秒；保留实际时长，未用解说片段伪造补足' % shortfall)
        # 按最接近的解说源时间边界安放原声；同一来源的原声块保持取用顺序。
        insertion_buckets: Dict[int, List[Dict[str, Any]]] = {}
        last_gap_by_source: Dict[str, int] = {}
        for original in originals:
            original_source = str(original.get('source_video') or '')
            original_start = float(original.get('source_start', 0) or 0)
            scored_gaps = []
            for gap in range(len(timeline) + 1):
                boundaries = []
                if gap:
                    boundaries.append((timeline[gap - 1], 'source_end'))
                if gap < len(timeline):
                    boundaries.append((timeline[gap], 'source_start'))
                same_source_distances = [
                    abs(original_start - float(boundary.get(edge, 0) or 0))
                    for boundary, edge in boundaries
                    if str(boundary.get('source_video') or '') == original_source
                ]
                all_distances = [
                    abs(original_start - float(boundary.get(edge, 0) or 0))
                    for boundary, edge in boundaries
                ]
                scored_gaps.append((0 if same_source_distances else 1, min(same_source_distances or all_distances or [float('inf')]), gap))
            min_gap = last_gap_by_source.get(original_source, 0)
            _, distance, gap = min((score for score in scored_gaps if score[2] >= min_gap), key=lambda score: (score[0], score[1], score[2]))
            last_gap_by_source[original_source] = gap
            placement = 'ratio_nearest_same_source_boundary' if any(
                str(boundary.get('source_video') or '') == original_source
                for boundary in ([timeline[gap - 1]] if gap else []) + ([timeline[gap]] if gap < len(timeline) else [])
            ) else 'ratio_nearest_source_time_boundary'
            original['selection_reason'] = placement
            self.logger.info('原声 ratio 安放 shot=%s 原因=%s 解说间隙=%s 源时间距离=%.3f', original.get('shot_id'), placement, gap, distance)
            insertion_buckets.setdefault(gap, []).append(original)
        enriched = []
        for gap in range(len(timeline) + 1):
            enriched.extend(insertion_buckets.get(gap, []))
            if gap < len(timeline):
                enriched.append(timeline[gap])
        actual_total = sum(max(0.0, float(item.get('final_duration', 0) or 0)) for item in enriched)
        correction = target_total - actual_total
        if abs(correction) > self.TIMELINE_EPSILON:
            warnings.append('目标总时长差 %.3f 秒；未通过改变配音/视频时长伪造精确结果' % correction)
        exact = safe_voice_budget <= 0 and shortfall <= self.TIMELINE_EPSILON and abs(actual_total - target_total) <= self.TIMELINE_EPSILON
        self.last_original_audio_summary = {
            'mode': 'ratio', 'target_ratio': ratio, 'target_total_seconds': round(target_total, 3),
            'actual_total_seconds': round(actual_total, 3), 'target_seconds': round(original_target, 3),
            'actual_seconds': round(actual_original, 3), 'actual_ratio': round(actual_original / actual_total, 6) if actual_total else 0,
            'exact_ratio_achieved': exact, 'requested': round(original_target, 3), 'inserted': len(originals),
            'shortfall_seconds': round(shortfall, 3), 'skipped_reason': skipped, 'warnings': warnings,
        }
        return self._finalize_timeline(enriched)

    @staticmethod
    def _build_atempo_chain(speed_factor: float) -> str:
        """将任意正的播放速度拆成 FFmpeg atempo 支持的 0.5~2.0 倍链。"""
        factor = float(speed_factor)
        if not math.isfinite(factor) or factor <= 0:
            return ''
        filters = []
        while factor > 2.0:
            filters.append('atempo=2.0')
            factor /= 2.0
        while factor < 0.5:
            filters.append('atempo=0.5')
            factor /= 0.5
        if not math.isclose(factor, 1.0, rel_tol=1e-6, abs_tol=1e-6):
            filters.append('atempo=%.9g' % factor)
        return ','.join(filters)

    def _original_audio_item(self, shot, source_start, duration, volume, reason):
        source_end = source_start + duration
        return {
            'kind': 'original_audio', 'original_audio': True, 'original_audio_volume': volume,
            'selection_reason': reason, 'shot_id': shot.get('id'), 'voice_indices': [], 'voice_paths': [], 'subtitle_text': '',
            'audio_duration': round(duration, 3), 'final_duration': round(duration, 3), 'source_duration': round(duration, 3),
            'target_duration': round(duration, 3), 'shot_start': round(source_start, 3), 'shot_end': round(source_end, 3),
            'shot_duration': round(duration, 3), 'source_start': round(source_start, 3), 'source_end': round(source_end, 3),
            'source_video': shot.get('source_video') or shot.get('source_video_path') or shot.get('video_path') or shot.get('source_path') or '',
            'speed_factor': 1.0, 'freeze_tail': False, 'is_fixed_ost': False, 'cut_strategy': 'direct',
        }

    # ------------------------------------------------------------------ #
    # 极短配音合并
    # ------------------------------------------------------------------ #
    def _group_short_voices(
        self, voices: List[Dict[str, Any]]
    ) -> List[List[Dict[str, Any]]]:
        """将极短配音与相邻配音合并为一组，共用一个画面"""
        if not voices:
            return []

        # 深拷贝避免修改传入字典（原 dict 上 setdefault 会污染调用方数据）
        voices = [dict(v) for v in voices]

        # 为每段配音加索引
        for i, v in enumerate(voices):
            v.setdefault('index', i)

        groups: List[List[Dict[str, Any]]] = []
        i = 0
        while i < len(voices):
            cur = voices[i]
            cur_dur = float(cur.get('duration', 0))

            if cur_dur < self.SHORT_VOICE_THRESHOLD and i + 1 < len(voices):
                # 极短配音与下一段合并
                nxt = voices[i + 1]
                groups.append([cur, nxt])
                i += 2
            else:
                groups.append([cur])
                i += 1

        merged_count = sum(1 for g in groups if len(g) > 1)
        if merged_count:
            self.logger.info(f'🔗 合并 {merged_count} 组极短配音共用画面')
        return groups

    # ------------------------------------------------------------------ #
    # 镜头选取
    # ------------------------------------------------------------------ #
    def _pick_next_shot(
        self,
        shots: List[Dict[str, Any]],
        used_shot_ids: set,
        start_idx: int,
        allow_reuse: bool,
        target_duration: float,
    ) -> Tuple[Optional[Dict[str, Any]], int]:
        """按列表下标顺序选取下一个可用镜头，镜头实际 id 用于去重。"""
        # 1. 从当前位置向后找第一个未用过的内部镜头。
        for i in range(start_idx, len(shots)):
            if self._shot_key(shots[i], i) not in used_shot_ids:
                return shots[i], i

        # 2. 从头找
        for i in range(0, min(start_idx, len(shots))):
            if self._shot_key(shots[i], i) not in used_shot_ids:
                return shots[i], i

        # 3. 允许复用时，选评分最高的
        if allow_reuse and shots:
            best_index, best_shot = max(
                enumerate(shots), key=lambda pair: pair[1].get('score', 0)
            )
            return best_shot, best_index

        return None, -1

    # ------------------------------------------------------------------ #
    # 匹配策略计算（核心：拟人剪辑逻辑）
    # ------------------------------------------------------------------ #
    def _compute_match_strategy(
        self, shot: Dict[str, Any], audio_duration: float
    ) -> Dict[str, Any]:
        """
        根据画面与音频时长差异，计算剪辑策略：
          - 画面 == 音频 → 直接使用
          - 画面 < 音频 → 仅在安全范围内变速慢放，否则明确拒绝
          - 画面 > 音频 → 智能选取重要部分（高光中段）
        """
        shot_dur = float(shot.get('duration', 0))
        audio_dur = max(0.1, float(audio_duration))
        final_duration = audio_dur  # 最终片段时长始终对齐音频

        # 防御：shot 缺失 duration 字段（shot_dur<=0）时，避免落入“画面<音频”分支
        # 导致 speed=0 → setpts 极端值；直接走 cut_highlight，取开头至多 3 秒
        if shot_dur <= 0:
            return {
                'cut_strategy': 'cut_highlight',
                'speed_factor': 1.0,
                'freeze_tail': False,
                'final_duration': round(final_duration, 3),
                'source_start': 0.0,
                'source_end': round(min(audio_dur, 3.0), 3),
            }

        # 情况1：画面时长 ≈ 音频时长（差异 < 10%）
        if abs(shot_dur - audio_dur) < 0.3 or 0.9 <= (shot_dur / audio_dur) <= 1.1:
            return {
                'cut_strategy': 'direct',
                'speed_factor': 1.0,
                'freeze_tail': False,
                'final_duration': round(final_duration, 3),
                'source_start': round(float(shot.get('start_time', 0)), 3),
                'source_end': round(float(shot.get('end_time', float(shot.get('start_time', 0) or 0) + shot_dur)), 3),
            }

        # 情况2：画面 < 音频（需要拉长画面）
        if shot_dur < audio_dur:
            # 优先尝试变速慢放（在合理范围内）
            speed = shot_dur / audio_dur  # <1
            if speed >= self.SPEED_MIN:
                return {
                    'cut_strategy': 'slow_down',
                    'speed_factor': round(speed, 3),
                    'freeze_tail': False,
                    'final_duration': round(final_duration, 3),
                    'source_start': round(float(shot.get('start_time', 0)), 3),
                    'source_end': round(float(shot.get('end_time', shot_dur)), 3),
                }
            else:
                raise ValueError(
                    '镜头 %.3fs 即使以 SPEED_MIN=%.2f 慢放也无法匹配 %.3fs 解说；拒绝生成定格补帧策略' %
                    (shot_dur, self.SPEED_MIN, audio_dur)
                )

        # 情况3：画面 > 音频（需要截取重要部分）
        # 选取镜头中段（通常最稳定且最精彩），按 audio_dur 截取
        shot_start = float(shot.get('start_time', 0))
        shot_end = float(shot.get('end_time', shot_start + shot_dur))
        center = (shot_start + shot_end) / 2
        half_audio = audio_dur / 2
        # 截取中段，但确保不超出镜头边界
        cut_start = max(shot_start, center - half_audio)
        cut_end = min(shot_end, cut_start + audio_dur)
        # 如果末尾不够，向前调整
        if cut_end - cut_start < audio_dur:
            cut_start = max(shot_start, cut_end - audio_dur)

        return {
            'cut_strategy': 'cut_highlight',
            'speed_factor': 1.0,
            'freeze_tail': False,
            'final_duration': round(final_duration, 3),
            'source_start': round(cut_start, 3),
            'source_end': round(cut_end, 3),
        }

    # ------------------------------------------------------------------ #
    # FFmpeg 实际剪辑执行
    # ------------------------------------------------------------------ #
    def render_timeline(
        self,
        video_path: str,
        timeline: List[Dict[str, Any]],
        output_path: Optional[str] = None,
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.25,
        subtitle_path: Optional[str] = None,
    ) -> str:
        """
        根据 match_shots_to_voices 生成的时间轴，使用 FFmpeg 渲染最终视频。

        策略：
          1. 对每个片段按 cut_strategy 单独处理（变速/截取/定格）
          2. 拼接所有片段
          3. 替换/叠加配音音频
          4. 可选叠加 BGM 和字幕

        Args:
            video_path: 源视频路径
            timeline: match_shots_to_voices 返回的匹配结果
            output_path: 输出视频路径
            bgm_path: 可选背景音乐
            bgm_volume: BGM 音量（0-1）
            subtitle_path: 可选 SRT 字幕文件

        Returns:
            输出视频路径
        """
        self.logger.info(f'🎬 开始渲染拟人化剪辑时间轴: {len(timeline)} 个片段')

        if not timeline:
            raise ValueError('时间轴为空，无法渲染')
        self._validate_timeline(timeline)

        v_path = Path(video_path).resolve()
        if not v_path.exists():
            raise FileNotFoundError(f'源视频不存在: {v_path}')

        out_dir = PROJECT_ROOT / 'output' / 'videos'
        out_dir.mkdir(parents=True, exist_ok=True)
        if not output_path:
            output_path = str(
                out_dir / f"puppet_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4"
            )

        tmp_dir = out_dir / f"tmp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        tmp_dir.mkdir(parents=True, exist_ok=True)

        try:
            clip_paths: List[str] = []
            for i, item in enumerate(timeline):
                item_video_path = item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path')
                clip_source = Path(item_video_path).resolve() if item_video_path else v_path
                if not clip_source.exists():
                    raise FileNotFoundError(f'时间线片段源视频不存在: {clip_source}')
                clip_path = self._render_single_clip(
                    clip_source, item, tmp_dir / f"clip_{i:04d}.mp4"
                )
                if not clip_path:
                    raise RuntimeError('时间线片段渲染失败，已中止整个成片: index=%s shot=%s' % (i, item.get('shot_id')))
                # 应用转场（淡入/淡出），concat 之前为相邻片段叠加简单转场
                prev_item = timeline[i - 1] if i > 0 else None
                has_next = i < len(timeline) - 1
                clip_path = self._apply_transition(Path(clip_path), item, prev_item, has_next)
                clip_paths.append(clip_path)

            if not clip_paths:
                raise RuntimeError('所有片段渲染失败')

            # 拼接片段
            concat_path = tmp_dir / 'concat.txt'
            with open(concat_path, 'w', encoding='utf-8', newline='\n') as f:
                for p in clip_paths:
                    abs_p = Path(p).resolve().as_posix()
                    # 转义单引号，避免路径含 ' 破坏 concat 文件格式
                    abs_p_escaped = abs_p.replace("'", "'\\''")
                    f.write(f"file '{abs_p_escaped}'\n")

            merged_video = tmp_dir / 'merged.mp4'
            # Every clip is normalized by _render_single_clip / transition
            # processing.  Stream-copy first: re-encoding this whole timeline
            # here used to add a costly 4K pass before subtitle burn-in.
            cmd = [
                'ffmpeg', '-y',
                '-f', 'concat', '-safe', '0',
                '-i', str(concat_path),
                '-c', 'copy', '-an',
                str(merged_video)
            ]
            try:
                self._run_ffmpeg(cmd, '拼接片段（直拷）')
            except RuntimeError as exc:
                self.logger.warning('片段直拷拼接失败，回退为一次快速兼容编码: %s', exc)
                self._run_ffmpeg([
                    'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_path),
                    '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF,
                    '-pix_fmt', 'yuv420p', '-an', str(merged_video),
                ], '拼接片段（兼容编码）')

            # 按最终时间轴组合音频：解说段放 TTS，原声段抽取源视频原声，缺口写入等长静音。
            audio_parts: List[Path] = []
            for index, item in enumerate(timeline):
                duration = float(item.get('final_duration') or item.get('audio_duration') or 0)
                if duration <= 0:
                    continue
                part_path = tmp_dir / f'audio_{index:04d}.wav'
                if item.get('kind') == 'original_audio' or item.get('original_audio'):
                    source_start = float(item.get('source_start', 0))
                    item_video_path = item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path')
                    audio_source = Path(item_video_path).resolve() if item_video_path else v_path
                    try:
                        original_audio_volume = float(item.get('original_audio_volume', 1.0))
                    except (TypeError, ValueError):
                        original_audio_volume = 1.0
                    original_audio_volume = max(0.0, min(1.0, original_audio_volume))
                    try:
                        self._run_ffmpeg([
                            'ffmpeg', '-y', '-ss', f'{source_start:.3f}', '-i', str(audio_source),
                            '-t', f'{duration:.3f}', '-vn', '-af', f'volume={original_audio_volume:.3f}',
                            '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)
                        ], f'提取原声片段 shot={item.get("shot_id")}')
                    except RuntimeError as exc:
                        raise RuntimeError('原声提取失败，已中止整个成片: shot=%s' % item.get('shot_id')) from exc
                else:
                    voice_paths = []
                    for path_value in item.get('voice_paths', []):
                        if not path_value:
                            continue
                        voice_path = Path(path_value)
                        if not voice_path.is_absolute():
                            voice_path = PROJECT_ROOT / voice_path
                        if voice_path.exists():
                            voice_paths.append(voice_path.resolve())
                    if voice_paths:
                        voice_list = tmp_dir / f'voice_{index:04d}.txt'
                        with open(voice_list, 'w', encoding='utf-8', newline='\n') as handle:
                            for voice_path in voice_paths:
                                handle.write(f"file '{voice_path.as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n")
                        source_audio_duration = float(item.get('source_audio_duration', duration) or duration)
                        audio_speed_factor = source_audio_duration / duration if source_audio_duration > 0 and duration > 0 else 1.0
                        atempo_chain = self._build_atempo_chain(audio_speed_factor)
                        audio_filter = ','.join(filter(None, [atempo_chain, 'apad']))
                        self._run_ffmpeg([
                            'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(voice_list),
                            '-t', f'{duration:.3f}', '-af', audio_filter,
                            '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)
                        ], f'合并配音段 {index}')
                    else:
                        self._run_ffmpeg([
                            'ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
                            '-t', f'{duration:.3f}', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)
                        ], f'生成配音空白段 {index}')
                if part_path.exists():
                    audio_parts.append(part_path)

            merged_audio = tmp_dir / 'timeline_audio.aac'
            if audio_parts:
                audio_concat = tmp_dir / 'audio_concat.txt'
                with open(audio_concat, 'w', encoding='utf-8', newline='\n') as handle:
                    for audio_part in audio_parts:
                        abs_p = audio_part.resolve().as_posix()
                        handle.write(f"file '{abs_p.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
                self._run_ffmpeg([
                    'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(audio_concat),
                    '-ar', '48000', '-ac', '2', '-c:a', 'aac', str(merged_audio)
                ], '按时间轴合并配音与原声')

            # 最终合成：时间轴音频（含原声插入）+ 可选 BGM
            final_cmd = ['ffmpeg', '-y', '-i', str(merged_video)]
            if merged_audio.exists():
                final_cmd.extend(['-i', str(merged_audio)])
            if bgm_path and Path(bgm_path).exists():
                final_cmd.extend(['-i', str(bgm_path)])

            if merged_audio.exists() and bgm_path and Path(bgm_path).exists():
                filter_complex = f'[1:a]volume=1.0[a1];[2:a]volume={bgm_volume}[a2];[a1][a2]amix=inputs=2:duration=first[aout]'
                final_cmd.extend(['-filter_complex', filter_complex, '-map', '0:v', '-map', '[aout]'])
            elif merged_audio.exists():
                final_cmd.extend(['-map', '0:v', '-map', '1:a'])
            else:
                final_cmd.extend(['-map', '0:v'])

            if subtitle_path and Path(subtitle_path).exists():
                # 烧录字幕
                sub_path = Path(subtitle_path).resolve().as_posix()
                # 转义反斜杠和冒号
                sub_escaped = sub_path.replace('\\', '/').replace(':', '\\:')
                final_cmd.extend(['-vf', f"subtitles='{sub_escaped}'"])

            final_cmd.extend([
                '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF,
                '-pix_fmt', 'yuv420p', '-shortest',
                '-c:a', 'aac', '-b:a', '192k',
                '-movflags', '+faststart',
                output_path
            ])
            expected_duration = sum(float(item.get('final_duration') or item.get('audio_duration') or 0) for item in timeline)
            self._run_ffmpeg(final_cmd, '最终合成', expected_duration=expected_duration)
            self._validate_rendered_media(output_path, expected_duration, require_audio=merged_audio.exists())

            self.logger.info(f'✅ 渲染完成: {output_path}')
            return output_path

        finally:
            # 清理临时目录
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _build_dedup_filters(item: Dict[str, Any]) -> str:
        """根据 clip 的 dedup_transform 构造去重变换滤镜链。

        支持字段：flip_horizontal / rotation(度) / zoom_scale(>1.0)。
        返回的滤镜链需置于 setpts/trim 之前，以逗号串联；无变换时返回空串。
        """
        dt = item.get('dedup_transform') if isinstance(item, dict) else None
        if not dt:
            return ''
        filters: List[str] = []
        if dt.get('flip_horizontal'):
            filters.append('hflip')
        rotation = dt.get('rotation')
        if rotation:
            try:
                rad = float(rotation) * math.pi / 180.0
            except (TypeError, ValueError):
                rad = 0.0
            if not math.isclose(rad, 0.0, abs_tol=1e-6):
                filters.append(f'rotate={rad:.6f}')
        zoom = dt.get('zoom_scale')
        if zoom:
            try:
                zoom = float(zoom)
            except (TypeError, ValueError):
                zoom = 0.0
            if zoom > 1.0:
                filters.append(f'scale=iw*{zoom:.6f}:ih*{zoom:.6f}')
                filters.append(f'crop=iw/{zoom:.6f}:ih/{zoom:.6f}')
        return ','.join(filters)

    def _render_single_clip(
        self, video_path: Path, item: Dict[str, Any], output_path: Path
    ) -> Optional[str]:
        """渲染单个片段（变速/截取/定格）"""
        strategy = item.get('cut_strategy', 'direct')
        src_start = float(item.get('source_start', 0))
        src_end = float(item.get('source_end', 0))
        speed = max(0.0001, float(item.get('speed_factor', 1.0)))
        target_duration = max(0.05, float(item.get('final_duration') or item.get('audio_duration') or (src_end - src_start)))
        freeze = item.get('freeze_tail', False)
        freeze_dur = float(item.get('freeze_duration', 0))
        # 去重变换滤镜链（general_mode_remix 写入），渲染时应用，置于 setpts/trim 之前
        dedup_filters = self._build_dedup_filters(item)

        def normalize_duration(input_path: Path, label: str) -> str:
            # 探测输入片段实际时长，避免对已精确截取（如 cut_highlight 中段）的片段二次裁剪
            input_dur = 0.0
            try:
                probe = subprocess.run(
                    ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                     '-of', 'default=noprint_wrappers=1:nokey=1', str(input_path)],
                    capture_output=True, text=True, timeout=60,
                )
                input_dur = float(probe.stdout.strip() or '0')
            except Exception:
                input_dur = 0.0
            # 仅允许编码时间基带来的微小舍入误差；不使用 tpad 掩盖时长不一致。
            if input_dur > 0 and abs(target_duration - input_dur) <= self.ENCODING_DURATION_EPSILON:
                if input_path.resolve() != output_path.resolve():
                    import shutil
                    shutil.copy2(str(input_path), str(output_path))
                return str(output_path)
            if input_dur <= 0 or abs(target_duration - input_dur) > self.TIMELINE_EPSILON:
                raise RuntimeError('%s 时长不一致：实际 %.3fs，目标 %.3fs' % (label, input_dur, target_duration))
            return str(output_path)

        try:
            if strategy == 'direct' or strategy == 'cut_highlight':
                # 直接截取
                duration = max(0.05, min(src_end - src_start, target_duration))
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', f'{src_start:.3f}',
                    '-i', str(video_path),
                    '-t', f'{duration:.3f}',
                ]
                # 去重变换（若有）作为视频滤镜应用，置于后续 trim 之前
                if dedup_filters:
                    cmd.extend(['-filter:v', dedup_filters])
                cmd.extend([
                    '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF,
                    '-pix_fmt', 'yuv420p',
                    '-an',
                    str(output_path)
                ])
                self._run_ffmpeg(cmd, f'截取片段 shot={item.get("shot_id")}')
                return normalize_duration(output_path, f'校正片段时长 shot={item.get("shot_id")}')

            elif strategy == 'slow_down':
                # 变速慢放：使用 setpts
                src_duration = max(0.05, src_end - src_start)
                pts_factor = 1.0 / speed  # speed<1 时 pts_factor>1，画面变慢
                # 去重变换在 setpts 之前应用（逗号串联）
                vfilter = ','.join(filter(None, [dedup_filters, f'setpts={pts_factor:.3f}*PTS']))
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', f'{src_start:.3f}',
                    '-i', str(video_path),
                    '-t', f'{src_duration:.3f}',
                    '-filter:v', vfilter,
                    '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF,
                    '-pix_fmt', 'yuv420p',
                    '-an',
                    str(output_path)
                ]
                self._run_ffmpeg(cmd, f'变速片段 shot={item.get("shot_id")} speed={speed}')
                return normalize_duration(output_path, f'校正慢放时长 shot={item.get("shot_id")}')

            elif strategy == 'freeze':
                # 慢放 + 末帧定格
                src_duration = max(0.05, src_end - src_start)
                pts_factor = 1.0 / speed
                # 先慢放（去重变换在 setpts 之前应用）
                slow_clip = output_path.with_suffix('.slow.mp4')
                slow_vfilter = ','.join(filter(None, [dedup_filters, f'setpts={pts_factor:.9g}*PTS', f'trim=duration={max(0.05, target_duration - freeze_dur):.9g}', 'setpts=PTS-STARTPTS']))
                cmd = [
                    'ffmpeg', '-y',
                    '-ss', f'{src_start:.3f}',
                    '-i', str(video_path),
                    '-t', f'{src_duration:.3f}',
                    '-filter:v', slow_vfilter,
                    '-an',
                    str(slow_clip)
                ]
                self._run_ffmpeg(cmd, f'慢放片段 shot={item.get("shot_id")}')

                # 提取末帧并定格 freeze_dur 秒；确保定格段总时长 = 慢放段 + 定格段
                if freeze_dur > 0.1 and slow_clip.exists():
                    last_frame = output_path.with_suffix('.last.png')
                    last_frame_ok = False
                    # 方法1：从慢放片段结尾前 0.05s 提取末帧（比 -0.1 对短片段更鲁棒）
                    try:
                        cmd = [
                            'ffmpeg', '-y',
                            '-sseof', '-0.05',
                            '-i', str(slow_clip),
                            '-frames:v', '1',
                            str(last_frame),
                        ]
                        self._run_ffmpeg(cmd, '提取末帧(-sseof)')
                        last_frame_ok = last_frame.exists() and last_frame.stat().st_size > 0
                    except RuntimeError as e:
                        self.logger.warning('⚠️ -sseof 提取末帧失败: %s', e)

                    # 方法2：用 ffprobe 已知帧数 select 最后一帧
                    if not last_frame_ok:
                        try:
                            probe = subprocess.run(
                                ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                                 '-show_entries', 'stream=nb_frames',
                                 '-of', 'default=noprint_wrappers=1:nokey=1', str(slow_clip)],
                                capture_output=True, text=True, timeout=60,
                            )
                            frame_count = int(probe.stdout.strip() or '0')
                            if frame_count > 0:
                                cmd = [
                                    'ffmpeg', '-y',
                                    '-i', str(slow_clip),
                                    '-vf', f'select=eq(n\\,{frame_count - 1})',
                                    '-frames:v', '1',
                                    str(last_frame),
                                ]
                                self._run_ffmpeg(cmd, f'提取末帧(select n={frame_count - 1})')
                                last_frame_ok = last_frame.exists() and last_frame.stat().st_size > 0
                        except (RuntimeError, ValueError) as e:
                            self.logger.warning('⚠️ select 提取末帧失败: %s', e)

                    if last_frame_ok:
                        freeze_clip = output_path.with_suffix('.freeze.mp4')
                        cmd = [
                            'ffmpeg', '-y',
                            '-loop', '1', '-i', str(last_frame),
                            '-t', f'{freeze_dur:.3f}',
                            '-r', '30',
                            '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF,
                            '-pix_fmt', 'yuv420p',
                            str(freeze_clip)
                        ]
                        self._run_ffmpeg(cmd, '生成定格片段')

                        # 拼接慢放 + 定格（总时长 = 慢放段时长 + 定格时长）
                        concat_file = output_path.with_suffix('.concat.txt')
                        with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
                            slow_p = slow_clip.resolve().as_posix().replace("'", "'\\''")
                            freeze_p = freeze_clip.resolve().as_posix().replace("'", "'\\''")
                            f.write(f"file '{slow_p}'\n")
                            f.write(f"file '{freeze_p}'\n")
                        cmd = [
                            'ffmpeg', '-y',
                            '-f', 'concat', '-safe', '0',
                            '-i', str(concat_file),
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-an',
                            str(output_path)
                        ]
                        self._run_ffmpeg(cmd, '拼接慢放+定格')
                        return normalize_duration(output_path, f'校正定格时长 shot={item.get("shot_id")}')
                    else:
                        raise RuntimeError('末帧提取失败，拒绝使用 tpad 克隆定格帧补足时长')

                return normalize_duration(slow_clip, f'校正慢放定格时长 shot={item.get("shot_id")}')

            else:
                self.logger.warning(f'⚠️ 未知策略: {strategy}')
                return None

        except Exception as e:
            self.logger.error(f'❗ 渲染片段失败 shot={item.get("shot_id")}: {e}')
            return None

    def _apply_transition(
        self,
        clip_path: Path,
        item: Dict[str, Any],
        prev_item: Optional[Dict[str, Any]],
        has_next: bool,
    ) -> str:
        """对单段应用淡入/淡出转场（非重叠方案：开头淡入 + 末尾淡出，不缩短总时长）。

        transition 字段描述「本段→下段」的转场类型：
          - fade / dissolve：本段末尾淡出（下段开头由它自己的 prev 决定淡入）
          - none 或缺省：硬切
        转场时长取自 clip 的 transition_duration（默认 0.3s）。
        """
        fade_in_dur = 0.0
        fade_out_dur = 0.0

        # 开头淡入：由前一段的 transition 决定（前段有转场则本段开头淡入）
        if prev_item:
            trans_in = str(prev_item.get('transition', 'none') or 'none').lower()
            if trans_in in ('fade', 'dissolve'):
                try:
                    fade_in_dur = float(prev_item.get('transition_duration', 0.3) or 0.3)
                except (TypeError, ValueError):
                    fade_in_dur = 0.3

        # 末尾淡出：由本段的 transition 决定（仅当有下一段时才需要）
        if has_next:
            trans_out = str(item.get('transition', 'none') or 'none').lower()
            if trans_out in ('fade', 'dissolve'):
                try:
                    fade_out_dur = float(item.get('transition_duration', 0.3) or 0.3)
                except (TypeError, ValueError):
                    fade_out_dur = 0.3

        if fade_in_dur <= 0 and fade_out_dur <= 0:
            return str(clip_path)

        # 探测片段时长，避免转场时长超过片段本身
        clip_dur = 0.0
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1', str(clip_path)],
                capture_output=True, text=True, timeout=60,
            )
            clip_dur = float(probe.stdout.strip() or '0')
        except Exception:
            clip_dur = 0.0
        if clip_dur <= 0:
            return str(clip_path)

        # 转场总时长不超过片段时长的一半，留出主体内容
        if fade_in_dur + fade_out_dur >= clip_dur:
            return str(clip_path)

        filters = []
        if fade_in_dur > 0:
            filters.append(f'fade=t=in:st=0:d={fade_in_dur:.3f}')
        if fade_out_dur > 0:
            filters.append(f'fade=t=out:st={max(0.0, clip_dur - fade_out_dur):.3f}:d={fade_out_dur:.3f}')

        out_path = clip_path.with_suffix('.trans.mp4')
        self._run_ffmpeg([
            'ffmpeg', '-y', '-i', str(clip_path),
            '-vf', ','.join(filters),
            '-c:v', 'libx264', '-preset', self.PREVIEW_PRESET, '-crf', self.PREVIEW_CRF, '-pix_fmt', 'yuv420p', '-an',
            str(out_path)
        ], f'转场处理 fade_in={fade_in_dur:.2f}s fade_out={fade_out_dur:.2f}s')
        return str(out_path)

    def _run_ffmpeg(self, cmd: List[str], label: str = '', expected_duration: float = 0.0):
        """执行 FFmpeg 命令并检查返回码，渲染上限随成片时长增长。"""
        self.logger.info(f'🎬 FFmpeg [{label}]: {" ".join(cmd)}')
        # A fixed 600 second ceiling was too short for legitimate 4K subtitle
        # rendering, but an unbounded wait hides deadlocks.  The cap remains
        # finite and is deliberately based on the actual timeline duration.
        timeout = max(180, min(1800, int(180 + max(0.0, expected_duration) * 6)))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f'FFmpeg 超时 [{label}]：{timeout} 秒内未完成；已停止本次渲染') from exc
        if result.returncode != 0:
            # FFmpeg writes the actionable reason at the end; retaining the
            # tail avoids reporting only its long build banner.
            err = (result.stderr or '')[-2000:]
            raise RuntimeError(f'FFmpeg 执行失败 [{label}]: {err}')
        return True

    def _validate_rendered_media(self, output_path: str, expected_duration: float, require_audio: bool) -> None:
        """Reject a partial/empty file before a task can be marked completed."""
        target = Path(output_path)
        if not target.is_file() or target.stat().st_size < 1024:
            raise RuntimeError(f'最终成片不存在或文件过小: {target}')
        try:
            probe = subprocess.run(
                ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                 '-of', 'json', str(target)],
                capture_output=True, text=True, timeout=60, check=True,
            )
            import json
            info = json.loads(probe.stdout or '{}')
            duration = float((info.get('format') or {}).get('duration') or 0)
            stream_types = {stream.get('codec_type') for stream in info.get('streams', [])}
        except Exception as exc:
            raise RuntimeError(f'无法验证最终成片媒体流: {target}') from exc
        if duration <= 0 or 'video' not in stream_types or (require_audio and 'audio' not in stream_types):
            raise RuntimeError(f'最终成片无有效音视频流: 时长={duration:.3f}s，流={sorted(stream_types)}')
        if expected_duration > 0 and abs(duration - expected_duration) > max(1.0, expected_duration * 0.03):
            raise RuntimeError(f'最终成片时长异常: 实际 {duration:.3f}s，时间轴 {expected_duration:.3f}s')


# 单例
_instance: Optional[PuppetSyncEngine] = None


def get_puppet_sync_engine() -> PuppetSyncEngine:
    global _instance
    if _instance is None:
        _instance = PuppetSyncEngine()
    return _instance
