# -*- coding: utf-8 -*-
"""
片头片尾检测器（对标剪映"粗剪"的掐头去尾策略）

三层检测策略（保守组合，宁可漏判不误杀正片）：
  1. 黑场/纯色检测：ffmpeg blackdetect + 抽帧亮度方差，识别片头片尾的黑场、
     白场、纯色 logo 底等低信息画面。
  2. 固定比例保护：默认额外掐掉头部/尾部各 5% 时长（受 min/max margin 约束），
     这正是剪映粗剪"掐头去尾"的默认行为，用于兜底黑场检测漏掉的订阅画面、
     关注引导、水印页等。
  3. 多素材模板检测：同一批素材中，若多个视频的片头（或片尾）代表帧的感知哈希
     彼此高度相似，说明是同系列视频的重复片头模板，整段剔除。

所有结果按 (path, mtime) 进程级缓存，同一任务内不会重复探测。
"""
from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认参数（偏保守，避免误杀正片）
# ---------------------------------------------------------------------------
HEAD_RATIO = 0.05        # 默认掐掉头部 5% 时长
TAIL_RATIO = 0.05        # 默认掐掉尾部 5% 时长
MIN_MARGIN = 0.8         # 最少掐掉 0.8s（低于此值无意义）
MAX_MARGIN = 8.0         # 单侧最多掐 8s（防止短视频被掐过头）
BLACK_SCAN_SECONDS = 20  # 片头/片尾各扫描的秒数（黑场+抽帧检测范围）
FRAME_SAMPLE_FPS = 4     # 低信息帧抽帧采样率
FLAT_VARIANCE = 28.0     # 灰度方差低于此值视为"纯色/低信息"帧
FLAT_RUN_FRAMES = 4      # 连续 FLAT_RUN_FRAMES 帧低信息才判定为片头/片尾画面
TEMPLATE_HAMMING = 6     # dHash 海明距离 <= 6 视为同一模板画面
FFPROBE_BIN = 'ffprobe'
FFMPEG_BIN = 'ffmpeg'

_CACHE: Dict[Tuple[str, float], dict] = {}


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------
def probe_duration(video_path: str) -> float:
    """ffprobe 读取视频时长（秒），失败返回 0。"""
    try:
        result = subprocess.run(
            [FFPROBE_BIN, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)],
            capture_output=True, text=True, timeout=60,
        )
        return float((result.stdout or '').strip())
    except Exception:
        return 0.0


def _open_capture(video_path: str):
    try:
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None
        return cap
    except Exception:
        return None


def frame_dhash(cap, timestamp: float) -> Optional[int]:
    """在指定时间点抽帧并计算 64bit dHash（差异哈希）。失败返回 None。"""
    try:
        cap.set(2, max(0.0, timestamp) * 1000.0)  # CAP_PROP_POS_MSEC
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        import cv2
        gray = cv2.cvtColor(cv2.resize(frame, (9, 8)), cv2.COLOR_BGR2GRAY)
        bits = 0
        for row in range(8):
            for col in range(8):
                bits = (bits << 1) | (1 if gray[row, col] > gray[row, col + 1] else 0)
        return bits
    except Exception:
        return None


def hamming_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count('1')


def _frame_is_flat(cap, timestamp: float) -> Optional[bool]:
    """判断指定时间点的帧是否为低信息画面（黑/白/纯色/logo 底）。"""
    try:
        cap.set(2, max(0.0, timestamp) * 1000.0)
        ok, frame = cap.read()
        if not ok or frame is None:
            return None
        import cv2
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return float(gray.var()) < FLAT_VARIANCE
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 黑场检测（ffmpeg blackdetect）
# ---------------------------------------------------------------------------
def _detect_black_edges(video_path: str, duration: float) -> Tuple[float, float]:
    """返回 (head_black_end, tail_black_start)。

    仅扫描片头/片尾各 BLACK_SCAN_SECONDS 秒，解析 blackdetect 输出：
    与文件开头连续相接的黑场决定 head_black_end；与文件结尾连续相接的黑场
    决定 tail_black_start。
    """
    head_end, tail_start = 0.0, duration
    scan = min(BLACK_SCAN_SECONDS, max(1.0, duration / 3.0))
    try:
        proc = subprocess.run(
            [FFMPEG_BIN, '-hide_banner', '-nostats',
             '-ss', '0', '-t', f'{scan:.3f}', '-i', str(video_path),
             '-vf', 'blackdetect=d=0.12:pix_th=0.10', '-an', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=120,
        )
        for line in (proc.stderr or '').splitlines():
            if 'black_start:' not in line:
                continue
            fields = dict(
                part.split(':', 1) for part in line.split() if ':' in part
            )
            try:
                b_start = float(fields.get('black_start', 'nan'))
                b_end = float(fields.get('black_end', 'nan'))
            except ValueError:
                continue
            if math.isnan(b_start) or math.isnan(b_end):
                continue
            # 与文件开头相接的黑场
            if b_start <= 0.25:
                head_end = max(head_end, min(b_end, scan))
    except Exception:
        pass

    if duration > scan * 2:
        try:
            proc = subprocess.run(
                [FFMPEG_BIN, '-hide_banner', '-nostats',
                 '-ss', f'{duration - scan:.3f}', '-i', str(video_path),
                 '-vf', 'blackdetect=d=0.12:pix_th=0.10', '-an', '-f', 'null', '-'],
                capture_output=True, text=True, timeout=120,
            )
            for line in (proc.stderr or '').splitlines():
                if 'black_start:' not in line:
                    continue
                fields = dict(
                    part.split(':', 1) for part in line.split() if ':' in part
                )
                try:
                    b_start = float(fields.get('black_start', 'nan'))
                    b_end = float(fields.get('black_end', 'nan'))
                except ValueError:
                    continue
                if math.isnan(b_start) or math.isnan(b_end):
                    continue
                # 黑场块延伸到文件结尾 → tail 黑场
                if b_end >= duration - 0.25:
                    tail_start = min(tail_start, max(duration - scan, b_start))
        except Exception:
            pass
    return head_end, tail_start


# ---------------------------------------------------------------------------
# 低信息画面（纯色/logo 底）检测：抽帧扫片头片尾
# ---------------------------------------------------------------------------
def _detect_flat_edges(video_path: str, duration: float) -> Tuple[float, float]:
    """抽帧检测片头/片尾的连续低信息画面，返回 (head_end, tail_start)。"""
    cap = _open_capture(video_path)
    if cap is None:
        return 0.0, duration
    try:
        head_end, tail_start = 0.0, duration
        scan = min(BLACK_SCAN_SECONDS, max(1.0, duration / 3.0))
        step = 1.0 / FRAME_SAMPLE_FPS

        # 片头：从 0 向后找连续低信息帧串
        run_start: Optional[float] = None
        run_len = 0
        t = 0.0
        while t < scan:
            flag = _frame_is_flat(cap, t)
            if flag:
                if run_start is None:
                    run_start = t
                run_len += 1
                if run_len >= FLAT_RUN_FRAMES:
                    head_end = max(head_end, t + step)
            else:
                run_start, run_len = None, 0
                if t > 0.5:  # 开头就遇到正片画面，提前结束
                    break
            t += step

        # 片尾：从结尾向前找连续低信息帧串
        run_end: Optional[float] = None
        run_len = 0
        t = duration - step
        while t > duration - scan:
            flag = _frame_is_flat(cap, t)
            if flag:
                if run_end is None:
                    run_end = t + step
                run_len += 1
                if run_len >= FLAT_RUN_FRAMES:
                    tail_start = min(tail_start, max(0.0, t))
            else:
                run_end, run_len = None, 0
                if t < duration - 0.5:
                    break
            t -= step
        return head_end, tail_start
    finally:
        cap.release()


# ---------------------------------------------------------------------------
# 多素材片头/片尾模板检测
# ---------------------------------------------------------------------------
def detect_intro_templates(video_paths: List[str], duration_by_path: Dict[str, float]) -> dict:
    """检测同系列视频的重复片头/片尾模板。

    Returns:
        {
          path: {
            'head_cut': float,   # 模板片头应剔除的秒数（无模板为 0）
            'tail_cut': float,   # 模板片尾应剔除的秒数
          }
        }
    """
    template_cut = {str(p): {'head_cut': 0.0, 'tail_cut': 0.0} for p in video_paths}
    paths = [str(p) for p in video_paths if (p) and Path(p).exists()]
    if len(paths) < 2:
        return template_cut

    head_hashes: List[Tuple[str, int]] = []
    tail_hashes: List[Tuple[str, int]] = []
    for path in paths:
        duration = duration_by_path.get(path) or probe_duration(path)
        if duration <= 2.0:
            continue
        cap = _open_capture(path)
        if cap is None:
            continue
        try:
            h = frame_dhash(cap, min(0.6, duration * 0.05))
            if h is not None:
                head_hashes.append((path, h))
            h = frame_dhash(cap, duration - min(0.6, duration * 0.05))
            if h is not None:
                tail_hashes.append((path, h))
        finally:
            cap.release()

    def _mark_pairs(hashes: List[Tuple[str, int]], is_head: bool) -> None:
        for i in range(len(hashes)):
            for j in range(i + 1, len(hashes)):
                if hamming_distance(hashes[i][1], hashes[j][1]) <= TEMPLATE_HAMMING:
                    for path, _ in (hashes[i], hashes[j]):
                        key = 'head_cut' if is_head else 'tail_cut'
                        fallback = duration_by_path.get(path, 0.0) * (
                            HEAD_RATIO if is_head else TAIL_RATIO
                        )
                        template_cut[path][key] = max(
                            template_cut[path][key],
                            fallback if fallback > 0 else 1.0,
                        )

    _mark_pairs(head_hashes, True)
    _mark_pairs(tail_hashes, False)
    return template_cut


# ---------------------------------------------------------------------------
# 综合有效区间
# ---------------------------------------------------------------------------
def compute_effective_ranges(
    video_paths: List[str],
    *,
    head_ratio: float = HEAD_RATIO,
    tail_ratio: float = TAIL_RATIO,
    enable_black_detect: bool = True,
    enable_template_detect: bool = True,
) -> Dict[str, dict]:
    """批量计算每个素材的有效区间（掐头去尾后）。

    Returns:
        { path: {
            'start': float, 'end': float, 'duration': float,
            'skipped_head': float, 'skipped_tail': float,
            'reasons': [str, ...]
        } }
    """
    duration_by_path: Dict[str, float] = {}
    for path in video_paths:
        p = str(path)
        if not p or not Path(p).exists():
            continue
        mtime = Path(p).stat().st_mtime
        cache_key = (p, mtime)
        if cache_key in _CACHE:
            duration_by_path[p] = _CACHE[cache_key]['duration']
            continue
        duration = probe_duration(p)
        if duration <= 0:
            continue
        duration_by_path[p] = duration

    templates: dict = {}
    if enable_template_detect and len(video_paths) > 1:
        try:
            templates = detect_intro_templates(video_paths, duration_by_path)
        except Exception as exc:
            logger.warning('片头模板检测失败（忽略，继续黑场+比例策略）: %s', exc)

    result: Dict[str, dict] = {}
    for path in video_paths:
        p = str(path)
        duration = duration_by_path.get(p)
        if not duration or duration <= 1.0:
            continue
        mtime = Path(p).stat().st_mtime
        cache_key = (p, mtime)
        if cache_key in _CACHE:
            result[p] = _CACHE[cache_key]
            continue

        reasons: List[str] = []
        ratio_head = duration * head_ratio
        ratio_tail = duration * tail_ratio
        head_cut = min(max(ratio_head, MIN_MARGIN), MAX_MARGIN, duration * 0.2)
        tail_cut = min(max(ratio_tail, MIN_MARGIN), MAX_MARGIN, duration * 0.2)
        reasons.append(f'比例保护: 头{head_cut:.2f}s/尾{tail_cut:.2f}s')

        if enable_black_detect:
            try:
                bh_end, tb_start = _detect_black_edges(p, duration)
                fh_end, ft_start = _detect_flat_edges(p, duration)
                if bh_end > head_cut:
                    head_cut = min(bh_end, duration * 0.25)
                    reasons.append(f'片头黑场至 {bh_end:.2f}s')
                if fh_end > head_cut:
                    head_cut = min(fh_end, duration * 0.25)
                    reasons.append(f'片头低信息画面至 {fh_end:.2f}s')
                if tb_start < duration - tail_cut:
                    tail_cut = min(duration - tb_start, duration * 0.25)
                    reasons.append(f'片尾黑场起 {tb_start:.2f}s')
                if ft_start < duration - tail_cut:
                    tail_cut = min(duration - ft_start, duration * 0.25)
                    reasons.append(f'片尾低信息画面起 {ft_start:.2f}s')
            except Exception as exc:
                logger.warning('黑场/低信息检测失败 %s: %s', p, exc)

        tmpl = templates.get(p) or {}
        if tmpl.get('head_cut', 0.0) > head_cut:
            head_cut = min(tmpl['head_cut'], duration * 0.25)
            reasons.append('多素材片头模板: 重复片头画面')
        if tmpl.get('tail_cut', 0.0) > tail_cut:
            tail_cut = min(tmpl['tail_cut'], duration * 0.25)
            reasons.append('多素材片尾模板: 重复片尾画面')

        # 留给正片的时间不足时收缩保护边距
        if duration - head_cut - tail_cut < duration * 0.5:
            shrink = (duration * 0.5 - (duration - head_cut - tail_cut)) / 2
            head_cut = max(0.0, head_cut - shrink)
            tail_cut = max(0.0, tail_cut - shrink)
            reasons.append('素材过短: 已收缩保护边距保留正片')

        info = {
            'start': round(head_cut, 3),
            'end': round(duration - tail_cut, 3),
            'duration': round(duration - head_cut - tail_cut, 3),
            'skipped_head': round(head_cut, 3),
            'skipped_tail': round(tail_cut, 3),
            'reasons': reasons,
            'source_duration': round(duration, 3),
        }
        _CACHE[cache_key] = info
        result[p] = info
        logger.info('片头片尾检测 %s: 有效区间 [%.2f, %.2f] (%s)', p, info['start'], info['end'], '; '.join(reasons))
    return result


def clamp_clip_to_range(clip: dict, effective: Optional[dict]) -> dict:
    """把候选片段 [start_time, end_time] 夹紧到素材有效区间内；无效返回 None。"""
    if not effective:
        return clip
    try:
        start = float(clip.get('start_time') or 0)
        end = float(clip.get('end_time') or 0)
    except (TypeError, ValueError):
        return None
    lo, hi = float(effective['start']), float(effective['end'])
    if end <= lo + 0.05 or start >= hi - 0.05:
        return None
    start, end = max(start, lo), min(end, hi)
    if end - start < 0.12:
        return None
    out = dict(clip)
    out['start_time'] = round(start, 3)
    out['end_time'] = round(end, 3)
    out['duration'] = round(end - start, 3)
    return out
