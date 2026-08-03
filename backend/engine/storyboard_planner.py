# -*- coding: utf-8 -*-
"""Build a renderable narration storyboard from coarse scene boundaries.

The planner runs before FFmpeg. A detected scene boundary is only a coarse
candidate: long scenes are split into real source windows, then narration
segments are assigned to non-overlapping windows in source-time order.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Set


class StoryboardPlanningError(ValueError):
    """A valid, honest storyboard cannot be built from the supplied media."""

    def __init__(self, message: str, unmatched_segments: List[Dict[str, Any]] | None = None):
        super().__init__(message)
        self.unmatched_segments = unmatched_segments or []


@dataclass(frozen=True)
class _Window:
    shot: Dict[str, Any]
    start: float
    end: float
    ordinal: int

    @property
    def midpoint(self) -> float:
        return (self.start + self.end) / 2.0


class StoryboardPlanner:
    """Choose visual windows by story coverage, relevance, duration, and continuity."""

    MIN_WINDOW_SECONDS = 1.0
    GAP_SECONDS = 0.08
    CURSOR_EPSILON = 0.04
    _WORD_RE = re.compile(r"[A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}")

    @classmethod
    def _tokens(cls, value: Any) -> Set[str]:
        text = str(value or "").lower()
        tokens: Set[str] = set(cls._WORD_RE.findall(text))
        chinese = ''.join(ch for ch in text if '\u4e00' <= ch <= '\u9fff')
        tokens.update(chinese[i:i + 2] for i in range(max(0, len(chinese) - 1)))
        tokens.update(chinese[i:i + 3] for i in range(max(0, len(chinese) - 2)))
        return tokens

    @staticmethod
    def _shot_end(shot: Dict[str, Any]) -> float:
        start = float(shot.get('start_time', 0) or 0)
        end = float(shot.get('end_time', 0) or 0)
        duration = float(shot.get('duration', 0) or 0)
        return end if end > start else start + duration

    def _window_candidates(self, shots: Iterable[Dict[str, Any]], duration: float) -> List[_Window]:
        windows: List[_Window] = []
        ordinal = 0
        needed = max(self.MIN_WINDOW_SECONDS, duration)
        for shot in sorted(shots, key=lambda s: float(s.get('start_time', 0) or 0)):
            start = max(0.0, float(shot.get('start_time', 0) or 0))
            end = self._shot_end(shot)
            available = end - start
            if available + 1e-6 < needed:
                continue
            step = max(needed + self.GAP_SECONDS, min(8.0, needed * 1.35))
            cursor = start
            while cursor + needed <= end + 1e-6:
                windows.append(_Window(shot, round(cursor, 3), round(cursor + needed, 3), ordinal))
                ordinal += 1
                cursor += step
            tail_start = end - needed
            if not windows or windows[-1].shot is not shot or abs(windows[-1].start - tail_start) > 0.2:
                windows.append(_Window(shot, round(tail_start, 3), round(end, 3), ordinal))
                ordinal += 1
        return sorted(windows, key=lambda w: (w.start, w.end, w.ordinal))

    @staticmethod
    def _overlaps(window: _Window, consumed: List[tuple[float, float]]) -> bool:
        return any(window.start < end - 1e-4 and window.end > start + 1e-4 for start, end in consumed)

    @staticmethod
    def _visual_text(shot: Dict[str, Any]) -> str:
        keys = (
            'description', 'enhanced_description', 'desc', 'summary', 'objects',
            'labels', 'scene_type', 'tags', 'ocr', 'action', 'emotion'
        )
        return ' '.join(str(shot.get(key, '')) for key in keys)

    def _future_capacity(self, windows: List[_Window], start_time: float, consumed: List[tuple[float, float]]) -> int:
        cursor = start_time
        count = 0
        for window in windows:
            if window.start + self.CURSOR_EPSILON < cursor or self._overlaps(window, consumed):
                continue
            count += 1
            cursor = window.end + self.GAP_SECONDS
        return count

    def _eligible_windows(
        self,
        windows: List[_Window],
        floor_time: float,
        consumed: List[tuple[float, float]],
        remaining_after_this: int,
    ) -> List[_Window]:
        candidates: List[_Window] = []
        for window in windows:
            if window.start + self.CURSOR_EPSILON < floor_time:
                continue
            if self._overlaps(window, consumed):
                continue
            next_consumed = consumed + [(window.start, window.end)]
            if self._future_capacity(windows, window.end + self.GAP_SECONDS, next_consumed) < remaining_after_this:
                continue
            candidates.append(window)
        return candidates

    def plan(self, shots: List[Dict[str, Any]], voices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not shots or not voices:
            raise StoryboardPlanningError('missing shots or voice segments; cannot build storyboard')

        source_start = min(float(shot.get('start_time', 0) or 0) for shot in shots)
        source_end = max(self._shot_end(shot) for shot in shots)
        span = max(0.001, source_end - source_start)
        voice_count = len(voices)
        anchor_step = span / max(1, voice_count - 1)
        anchor_tolerance = max(8.0, min(45.0, span / max(2.0, voice_count * 1.8)))

        consumed: List[tuple[float, float]] = []
        planned: List[Dict[str, Any]] = []
        unmatched: List[Dict[str, Any]] = []
        cursor_time = source_start
        all_windows_by_duration: Dict[float, List[_Window]] = {}

        for index, voice in enumerate(voices):
            duration = float(voice.get('duration', 0) or 0)
            if not math.isfinite(duration) or duration <= 0:
                unmatched.append({'index': index, 'text': voice.get('text', ''), 'reason': 'invalid voice duration'})
                continue

            duration_key = round(max(self.MIN_WINDOW_SECONDS, duration), 3)
            if duration_key not in all_windows_by_duration:
                all_windows_by_duration[duration_key] = self._window_candidates(shots, duration)
            windows = all_windows_by_duration[duration_key]
            remaining_after_this = voice_count - index - 1

            target_start = min(source_end - duration_key, source_start + anchor_step * index)
            target_start = max(source_start, target_start)
            preferred_floor = max(cursor_time, target_start - anchor_tolerance)
            candidates = self._eligible_windows(windows, preferred_floor, consumed, remaining_after_this)
            if not candidates and preferred_floor > cursor_time:
                candidates = self._eligible_windows(windows, cursor_time, consumed, remaining_after_this)

            if not candidates:
                unmatched.append({
                    'index': index,
                    'text': voice.get('text', ''),
                    'duration': duration,
                    'reason': 'not enough forward, non-overlapping source windows',
                })
                continue

            voice_tokens = self._tokens(voice.get('text'))
            desired = (target_start - source_start) / span

            def rank(window: _Window) -> tuple[float, float, float, float, int]:
                shot = window.shot
                visual_tokens = self._tokens(self._visual_text(shot))
                overlap = len(voice_tokens & visual_tokens)
                semantic = overlap / max(1, len(voice_tokens))
                window_pos = (window.start - source_start) / span
                coverage = 1.0 - min(1.0, abs(window_pos - desired) * 2.2)
                continuity = 1.0 / (1.0 + max(0.0, window.start - preferred_floor) / max(6.0, anchor_tolerance))
                anchor_distance = abs(window.start - target_start)
                anchor_score = 1.0 / (1.0 + anchor_distance / max(4.0, anchor_tolerance))
                quality = max(0.0, min(1.0, float(shot.get('score', 0.5) or 0.5)))
                score = semantic * 0.34 + coverage * 0.18 + continuity * 0.18 + anchor_score * 0.22 + quality * 0.08
                return (score, semantic, continuity, anchor_score, -window.ordinal)

            chosen = max(candidates, key=rank)
            total_score, semantic_score, continuity_score, anchor_score, _ = rank(chosen)
            consumed.append((chosen.start, chosen.end))
            cursor_time = chosen.end + self.GAP_SECONDS

            original = chosen.shot
            item = dict(original)
            item.update({
                'id': 'storyboard_%03d' % index,
                'storyboard_source_shot_id': original.get('id'),
                'start_time': chosen.start,
                'end_time': chosen.end,
                'duration': round(chosen.end - chosen.start, 3),
                'score': round(total_score, 4),
                'semantic_score': round(semantic_score, 4),
                'continuity_score': round(continuity_score, 4),
                'anchor_score': round(anchor_score, 4),
                'target_start': round(target_start, 3),
                'selection_reason': 'semantic=%.3f, continuity=%.3f, anchor=%.3f, target=%.3f, source=%.3f-%.3f' % (
                    semantic_score, continuity_score, anchor_score, target_start, chosen.start, chosen.end,
                ),
            })
            planned.append(item)

        if unmatched:
            raise StoryboardPlanningError(
                'not enough source material to create a forward non-overlapping storyboard',
                unmatched,
            )
        return planned
