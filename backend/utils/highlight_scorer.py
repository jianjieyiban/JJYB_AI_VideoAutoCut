# -*- coding: utf-8 -*-
"""
多信号高光评分器（借鉴多引擎融合的高光识别思路，自研实现，无外部代码依赖）

在原有视觉评分（运动+色彩+亮度）基础上融合两类新信号，解决"高光识别不准"：

  1. 音频能量信号：高光时刻通常伴随更高的音频能量（笑声、欢呼、BGM 高潮、
     音效爆发）。用 ffmpeg 流式提取单声道 PCM，按 0.5s 桶聚合 RMS，
     以对数刻度归一化后按镜头区间聚合。无声视频自动关闭该信号并重分配权重。
  2. 人物出镜信号：有人出镜的镜头通常更具表现力（口播、反应、互动）。
     用 OpenCV 自带 Haar 级联人脸检测，优先复用镜头关键帧缩略图，零新增依赖。

另外提供场景检测结果磁盘缓存：TransNetV2/OpenCV 检测昂贵而结果确定
（同一路径+修改时间结果不变），缓存后用户调整参数重试时秒级返回。

融合策略（就地更新 shot['score']，保留各子分数便于前端展示与调试）：
  - 有音频：score = 0.60*visual + 0.30*audio + 0.10*face
  - 无音频：score = 0.90*visual + 0.10*face
"""
from __future__ import annotations

import logging
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AUDIO_BUCKET_SECONDS = 0.5      # 音频 RMS 聚合粒度
AUDIO_SAMPLE_RATE = 16000
FACE_WEIGHT_BONUS = 1.0         # 检出人脸的加成满分
W_VISUAL_AUDIO = 0.60
W_AUDIO = 0.30
W_FACE = 0.10
W_VISUAL_ONLY = 0.90
W_FACE_ONLY = 0.10

# 进程级缓存：(path, mtime) -> {'audio': {...}, 'face': {...}}
_SIGNAL_CACHE: Dict[tuple, Dict[str, Any]] = {}
_FACE_CASCADE = None


# ---------------------------------------------------------------------------
# 音频能量信号
# ---------------------------------------------------------------------------
def _extract_audio_rms(video_path: str, duration: float) -> Optional[List[float]]:
    """流式提取单声道 PCM，返回按 AUDIO_BUCKET_SECONDS 聚合的 RMS 序列。

    无音轨或 ffmpeg 失败返回 None（调用方据此关闭音频信号）。
    """
    bucket_samples = int(AUDIO_SAMPLE_RATE * AUDIO_BUCKET_SECONDS)
    buckets: List[List[float]] = []
    try:
        proc = subprocess.Popen(
            ['ffmpeg', '-hide_banner', '-nostats', '-i', str(video_path),
             '-ac', '1', '-ar', str(AUDIO_SAMPLE_RATE), '-f', 'f32le', '-'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
        )
        carry = b''
        total_bytes = 0
        expected = int(max(0.0, duration) * AUDIO_SAMPLE_RATE) * 4
        while True:
            chunk = proc.stdout.read(1 << 16)
            if not chunk:
                break
            carry += chunk
            total_bytes += len(chunk)
            usable = len(carry) - (len(carry) % (bucket_samples * 4))
            if usable:
                import numpy as np
                data = np.frombuffer(carry[:usable], dtype='<f4')
                for i in range(0, len(data), bucket_samples):
                    seg = data[i:i + bucket_samples]
                    buckets.append([float(np.sqrt(np.mean(seg * seg)) + 1e-9)])
                carry = carry[usable:]
        proc.stdout.close()
        proc.wait(timeout=30)
    except Exception as exc:
        logger.warning('音频能量提取失败（忽略音频信号）: %s', exc)
        return None

    if total_bytes < 1024:  # 无音轨或极短
        return None
    import numpy as np
    flat = np.array([b[0] for b in buckets], dtype='<f4') if buckets else np.zeros(1)
    return flat.tolist()


def _normalize_log(values: List[float]) -> List[float]:
    """对数刻度 min-max 归一化到 0-1（音频动态范围大，线性归一化会压扁）。"""
    import math
    if not values:
        return values
    log_vals = [math.log10(max(v, 1e-6)) for v in values]
    lo, hi = min(log_vals), max(log_vals)
    if hi - lo < 1e-6:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in log_vals]


def _audio_signal_for(video_path: str, duration: float) -> Optional[Dict[str, Any]]:
    """计算整条视频的音频信号（带缓存），返回 {'rms_norm': [...], 'bucket': 秒}。"""
    key = ('audio', video_path, Path(video_path).stat().st_mtime)
    if key in _SIGNAL_CACHE:
        return _SIGNAL_CACHE[key]
    rms = _extract_audio_rms(video_path, duration)
    if not rms:
        return None
    norm = _normalize_log(rms)
    result = {'rms_norm': norm, 'bucket': AUDIO_BUCKET_SECONDS}
    _SIGNAL_CACHE[key] = result
    return result


def _shot_audio_score(audio: Dict[str, Any], start: float, end: float) -> float:
    """取镜头区间内 RMS 归一值的均值（含峰值加成）。"""
    bucket = audio['bucket']
    norm = audio['rms_norm']
    lo = max(0, int(start / bucket))
    hi = min(len(norm), max(lo + 1, int(end / bucket)))
    seg = norm[lo:hi]
    if not seg:
        return 0.5
    mean = sum(seg) / len(seg)
    peak = max(seg)
    return min(1.0, 0.7 * mean + 0.3 * peak)


# ---------------------------------------------------------------------------
# 人物出镜信号
# ---------------------------------------------------------------------------
def _get_face_cascade():
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        try:
            import cv2
            _FACE_CASCADE = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
        except Exception as exc:
            logger.warning('人脸检测器加载失败（忽略人物信号）: %s', exc)
            _FACE_CASCADE = False
    return _FACE_CASCADE or None


def _detect_face_in_image(path_str: str) -> bool:
    try:
        import cv2
        img = cv2.imread(path_str)
        if img is None:
            return False
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = _get_face_cascade().detectMultiScale(
            gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
        return len(faces) > 0
    except Exception:
        return False


def _shot_face_score(shot: Dict[str, Any], video_path: str) -> float:
    """镜头中点人脸检测：检出=1.0，未检出=0.0；关键帧缺失时回退抽帧。"""
    cascade = _get_face_cascade()
    if not cascade:
        return 0.0
    keyframe = shot.get('keyframe_path')
    if keyframe and Path(str(keyframe)).exists():
        return FACE_WEIGHT_BONUS if _detect_face_in_image(str(keyframe)) else 0.0
    try:
        import cv2
        cap = cv2.VideoCapture(video_path)
        try:
            mid = (float(shot.get('start_time') or 0) +
                   float(shot.get('end_time') or 0)) / 2
            cap.set(2, max(0.0, mid) * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                return 0.0
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(
                gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
            return FACE_WEIGHT_BONUS if len(faces) > 0 else 0.0
        finally:
            cap.release()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 主入口：多信号融合
# ---------------------------------------------------------------------------
def enrich_shot_scores(shots: List[Dict[str, Any]], video_path: str) -> List[Dict[str, Any]]:
    """就地融合音频/人物信号到镜头评分，返回同一列表（链式调用友好）。"""
    if not shots:
        return shots
    from backend.utils.intro_outro_detector import probe_duration
    duration = probe_duration(video_path)
    if duration <= 0:
        return shots

    face_cache_key = ('face', video_path, Path(video_path).stat().st_mtime)
    face_cache = _SIGNAL_CACHE.setdefault(face_cache_key, {})

    audio = _audio_signal_for(video_path, duration)
    has_audio = audio is not None
    for idx, shot in enumerate(shots):
        try:
            start = float(shot.get('start_time') or 0)
            end = float(shot.get('end_time') or 0)
        except (TypeError, ValueError):
            continue
        visual = float(shot.get('score') or 0.5)

        audio_score = _shot_audio_score(audio, start, end) if has_audio else None
        face_key = f'{idx}:{round(start, 2)}'
        if face_key in face_cache:
            face_score = face_cache[face_key]
        else:
            face_score = _shot_face_score(shot, video_path)
            face_cache[face_key] = face_score

        if has_audio:
            new_score = (W_VISUAL_AUDIO * visual + W_AUDIO * audio_score +
                         W_FACE * face_score)
        else:
            new_score = W_VISUAL_ONLY * visual + W_FACE_ONLY * face_score

        shot['visual_score'] = round(visual, 3)
        if audio_score is not None:
            shot['audio_score'] = round(audio_score, 3)
        shot['face_score'] = round(face_score, 3)
        shot['score'] = round(new_score, 3)
    logger.info(
        '多信号评分完成 %s: %d 个镜头 (音频信号=%s)',
        Path(video_path).name, len(shots), '有' if has_audio else '无')
    return shots


# ---------------------------------------------------------------------------
# 场景检测磁盘缓存（检测昂贵、调参便宜）
# ---------------------------------------------------------------------------
def load_or_detect_shots(segmenter, video_path: str, **kwargs) -> List[Dict[str, Any]]:
    """带磁盘缓存的 detect_shots：缓存键 = 路径 + 修改时间 + 检测器配置。

    缓存存到 temp/shot_cache/*.json，命中时跳过 TransNetV2/OpenCV 全片推理。
    """
    import json
    import time
    from backend.config.paths import PROJECT_ROOT

    try:
        mtime = Path(video_path).stat().st_mtime
    except OSError:
        return segmenter.detect_shots(video_path, **kwargs)

    cfg_tag = f't{int(bool(getattr(segmenter, "use_transnetv2", False)))}'
    cache_dir = Path(PROJECT_ROOT) / 'temp' / 'shot_cache'
    cache_file = cache_dir / f'{Path(video_path).stem}-{int(mtime)}-{cfg_tag}.json'

    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            if data.get('mtime') == mtime and data.get('shots'):
                logger.info('镜头缓存命中: %s (%d 镜头)', Path(video_path).name,
                            len(data['shots']))
                return data['shots']
        except Exception:
            pass

    shots = segmenter.detect_shots(video_path, **kwargs)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(
            json.dumps({'mtime': mtime, 'saved_at': time.time(), 'shots': shots},
                       ensure_ascii=False), encoding='utf-8')
    except Exception as exc:
        logger.warning('镜头缓存写入失败（不影响结果）: %s', exc)
    return shots


__all__ = ['enrich_shot_scores', 'load_or_detect_shots']
