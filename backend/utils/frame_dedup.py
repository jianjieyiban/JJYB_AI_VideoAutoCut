# -*- coding: utf-8 -*-
"""
片段内容去重器（解决"混剪成片大量重复镜头"的用户反馈）

思路对标剪映粗剪的去重环节：
  - 对每个候选片段在"片段中点"抽一帧，计算 64bit dHash（差异感知哈希）；
  - 海明距离 <= DUP_HAMMING_THRESHOLD 判定为相似画面；
  - 相似组内保留精彩度得分最高的片段，其余丢弃；
  - 支持从备用候选池自动补位，保证去重后总时长仍能覆盖目标。

抽帧使用 OpenCV（单进程内 seek，不起 ffmpeg 子进程），每个 (path, mtime)
的 VideoCapture 按任务生命周期缓存复用，避免反复打开大文件。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from backend.utils.intro_outro_detector import (
    frame_dhash,
    hamming_distance,
    probe_duration,
)

logger = logging.getLogger(__name__)

# dHash 64bit；距离 <=10 视为"相似画面"（同一镜头或同款模板）。
# 阈值偏保守：不同镜头误杀率低，而完全相同的片头/重复镜头距离通常为 0~6。
DUP_HAMMING_THRESHOLD = 10
CLIP_HASH_OFFSET_RATIO = 0.5   # 在片段中点抽帧
FALLBACK_OFFSET = 0.5          # 中点 seek 失败时的备用偏移
MIN_CLIP_FOR_HASH = 0.2        # 片段过短时直接在起点附近抽帧


class _CapturePool:
    """按视频路径缓存 VideoCapture，同一批任务复用。"""

    def __init__(self) -> None:
        self._pool: Dict[str, object] = {}

    def get(self, video_path: str):
        key = str(video_path)
        cap = self._pool.get(key)
        if cap is not None:
            return cap
        try:
            import cv2
            new_cap = cv2.VideoCapture(key)
            if not new_cap.isOpened():
                return None
            self._pool[key] = new_cap
            return new_cap
        except Exception:
            return None

    def close(self) -> None:
        for cap in self._pool.values():
            try:
                cap.release()
            except Exception:
                pass
        self._pool.clear()


def _clip_hash(pool: _CapturePool, clip: dict) -> Optional[int]:
    """计算片段代表帧的 dHash。"""
    path = clip.get('video_path') or clip.get('source_video')
    if not path or not Path(str(path)).exists():
        return None
    try:
        start = float(clip.get('start_time') or 0)
        end = float(clip.get('end_time') or 0)
    except (TypeError, ValueError):
        return None
    duration = max(0.0, end - start)
    if duration < MIN_CLIP_FOR_HASH:
        offset = 0.05
    else:
        offset = duration * CLIP_HASH_OFFSET_RATIO
    cap = pool.get(str(path))
    if cap is None:
        return None
    h = frame_dhash(cap, start + offset)
    if h is None:
        h = frame_dhash(cap, start + FALLBACK_OFFSET)
    return h


def dedup_clips(
    clips: List[dict],
    *,
    threshold: int = DUP_HAMMING_THRESHOLD,
    keep_key=None,
) -> Tuple[List[dict], int]:
    """对已选片段去重：相似画面保留得分最高者。

    Args:
        clips: 已按时间线顺序（或任意顺序）的片段列表
        keep_key: 排序函数，返回值越大越优先保留，默认 score

    Returns:
        (保留的片段列表, 被丢弃的数量)
    """
    if not clips:
        return [], 0
    pool = _CapturePool()
    try:
        if keep_key is None:
            def keep_key(c):
                try:
                    return float(c.get('score') or 0.5)
                except (TypeError, ValueError):
                    return 0.5

        ranked = sorted(enumerate(clips), key=lambda pair: keep_key(pair[1]), reverse=True)
        kept: List[Tuple[int, dict, int]] = []
        dropped = 0
        for original_index, clip in ranked:
            h = _clip_hash(pool, clip)
            if h is None:
                kept.append((original_index, clip, -1))  # 抽帧失败：保守保留
                continue
            duplicate = False
            for _, _, kept_hash in kept:
                if kept_hash >= 0 and hamming_distance(h, kept_hash) <= threshold:
                    duplicate = True
                    break
            if duplicate:
                dropped += 1
                logger.info(
                    '去重: 丢弃相似片段 %.2f-%.2f (%s)',
                    float(clip.get('start_time') or 0), float(clip.get('end_time') or 0),
                    clip.get('video_path'),
                )
            else:
                kept.append((original_index, clip, h))
        kept.sort(key=lambda item: item[0])  # 恢复传入顺序
        return [clip for _, clip, _ in kept], dropped
    finally:
        pool.close()


def dedup_with_refill(
    selected: List[dict],
    candidates: List[dict],
    *,
    threshold: int = DUP_HAMMING_THRESHOLD,
) -> Tuple[List[dict], int]:
    """去重 + 从候选池补位（保持时间线原有顺序）。

    先对 selected 逐个抽帧判重；发现重复片段时，从 candidates 中挑选
    与已保留片段均不相似、且得分最高的候选**顶替原位置**，从而完全保留
    调用方已排定的叙事顺序（如混剪的相对进度交错）。

    Returns:
        (去重补位后的片段列表, 未能补回的丢弃数量)
    """
    if not selected:
        return [], 0
    pool = _CapturePool()
    try:
        def score_of(c):
            try:
                return float(c.get('score') or 0.5)
            except (TypeError, ValueError):
                return 0.5

        def clip_identity(c):
            return (
                str(c.get('video_path') or c.get('source_video') or ''),
                round(float(c.get('start_time') or 0), 3),
                round(float(c.get('end_time') or 0), 3),
            )

        selected_ids = {clip_identity(c) for c in selected}
        refill_pool = sorted(
            (c for c in candidates if clip_identity(c) not in selected_ids),
            key=score_of, reverse=True,
        )
        kept_hashes: List[int] = []
        result: List[dict] = []
        unrefilled = 0

        def _similar_to_kept(h: int) -> bool:
            return any(hamming_distance(h, kh) <= threshold for kh in kept_hashes)

        for clip in selected:
            h = _clip_hash(pool, clip)
            if h is not None and kept_hashes and _similar_to_kept(h):
                replacement = None
                for cand in list(refill_pool):
                    ch = _clip_hash(pool, cand)
                    if ch is None:
                        continue
                    if kept_hashes and _similar_to_kept(ch):
                        continue
                    replacement = cand
                    refill_pool.remove(cand)
                    kept_hashes.append(ch)
                    break
                if replacement is not None:
                    logger.info(
                        '去重补位: %.2f-%.2f 与已选镜头重复，替换为 %.2f-%.2f (%s)',
                        float(clip.get('start_time') or 0), float(clip.get('end_time') or 0),
                        float(replacement.get('start_time') or 0), float(replacement.get('end_time') or 0),
                        replacement.get('video_path') or replacement.get('source_video'),
                    )
                    result.append(replacement)
                else:
                    unrefilled += 1
                    logger.info(
                        '去重: 丢弃重复片段 %.2f-%.2f (%s)，无可用替补',
                        float(clip.get('start_time') or 0), float(clip.get('end_time') or 0),
                        clip.get('video_path') or clip.get('source_video'),
                    )
                continue
            result.append(clip)
            if h is not None:
                kept_hashes.append(h)
        return result, unrefilled
    finally:
        pool.close()


__all__ = [
    'DUP_HAMMING_THRESHOLD',
    'dedup_clips',
    'dedup_with_refill',
    'probe_duration',
]
