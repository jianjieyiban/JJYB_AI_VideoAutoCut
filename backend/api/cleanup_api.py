# -*- coding: utf-8 -*-
"""
Cleanup API
提供三大核心功能的清理接口：缓存、文案脚本、音频、视频、画面帧等
目标：commentary(原创解说剪辑) / voiceover(AI配音) / remix(混剪模式) / smart_cut(同commentary自动剪辑)
"""

import os
import shutil
import glob
import logging
import time
from typing import Dict, List, Tuple
from flask import Blueprint, request, jsonify

from backend.config.paths import PROJECT_ROOT, OUTPUT_DIR

logger = logging.getLogger('JJYB_AI智剪')

cleanup_bp = Blueprint('cleanup', __name__)


def _ensure_abs(p: str) -> str:
    return os.path.abspath(p)


def _path_size(path: str) -> int:
    try:
        if os.path.isfile(path):
            return os.path.getsize(path)
        total = 0
        for root, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root, f))
                except Exception:
                    pass
        return total
    except Exception:
        return 0


def _delete_path(path: str) -> Tuple[int, int]:
    """删除指定路径（文件或目录）。返回 (deleted_count, bytes_freed)。"""
    if not path:
        return 0, 0
    if not os.path.exists(path):
        return 0, 0
    try:
        bytes_freed = _path_size(path)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            try:
                os.remove(path)
            except IsADirectoryError:
                shutil.rmtree(path, ignore_errors=True)
        return 1, bytes_freed
    except Exception as e:
        logger.warning(f"删除失败: {path}: {e}")
        return 0, 0


def _expand_patterns(patterns: List[str]) -> List[str]:
    matched: List[str] = []
    for pat in patterns:
        try:
            g = glob.glob(pat, recursive=True)
            if g:
                matched.extend(g)
        except Exception:
            pass
    # 去重并保持存在
    out = []
    seen = set()
    for p in g if False else patterns:  # placeholder to keep lints calm
        pass
    for p in matched:
        ap = _ensure_abs(p)
        if ap not in seen and os.path.exists(ap):
            seen.add(ap)
            out.append(ap)
    return out


def _filter_by_age(paths: List[str], max_age_days: float) -> List[str]:
    """按修改时间过滤路径列表，仅保留最近 max_age_days 天内修改过的项。

    max_age_days <= 0 或 None 表示不过滤。
    """
    if not max_age_days or max_age_days <= 0:
        return paths

    try:
        cutoff = time.time() - float(max_age_days) * 86400.0
    except Exception:
        return paths

    filtered: List[str] = []
    for p in paths:
        try:
            mtime = os.path.getmtime(p)
            if mtime >= cutoff:
                filtered.append(p)
        except Exception:
            # 读取失败则跳过该路径
            continue
    return filtered


def _build_cleanup_plan(target: str, include: Dict) -> Dict:
    """根据目标与包含项构建需要删除的路径列表。"""
    TEMP = _ensure_abs(str(PROJECT_ROOT / 'temp'))
    OUTPUT = _ensure_abs(str(OUTPUT_DIR))
    UPLOADS = _ensure_abs(str(PROJECT_ROOT / 'uploads'))
    EXPORTS = _ensure_abs(str(PROJECT_ROOT / 'exports'))
    BACKEND_TEMP = _ensure_abs(str(PROJECT_ROOT / 'backend' / 'temp'))

    final_flag = bool(include.get('final'))  # 明确包含最终导出才删 output 下最终文件

    # 通用中间产物
    common_patterns = []
    if include.get('cache'):
        common_patterns += [
            # 分析缓存
            os.path.join(TEMP, 'analysis', 'frame_analysis_*.json'),
            os.path.join(BACKEND_TEMP, 'analysis', 'frame_analysis_*.json'),
            # 临时输出
            os.path.join(TEMP, 'outputs', '*'),
            os.path.join(BACKEND_TEMP, 'outputs', '*'),
            # 混剪片段缓存（重要）
            os.path.join(TEMP, 'remix_segments', '*', '*'),
            os.path.join(TEMP, 'remix_segments', '*'),
            # 处理过程缓存
            os.path.join(TEMP, 'processing', '*'),
        ]
    if include.get('scripts'):
        common_patterns += [
            # 解说文案脚本
            os.path.join(TEMP, 'narration_script.json'),
            os.path.join(BACKEND_TEMP, 'narration_script.json'),
            os.path.join(TEMP, 'script_*.json'),
            os.path.join(OUTPUT, 'commentary', '*_script.json'),
            # AI生成的文案
            os.path.join(TEMP, 'generated_script_*.txt'),
        ]
    if include.get('audio'):
        common_patterns += [
            # 临时音频
            os.path.join(TEMP, 'audio', '*'),
            os.path.join(TEMP, 'outputs', '*.mp3'),
            os.path.join(TEMP, 'outputs', '*.wav'),
            # 配音输出
            os.path.join(OUTPUT, 'voiceovers', '*'),
            os.path.join(OUTPUT, 'audios', '*'),
            os.path.join(OUTPUT, 'previews', '*.mp3'),
            # 解说音频
            os.path.join(OUTPUT, 'commentary', '*_audio.mp3'),
            os.path.join(OUTPUT, 'commentary_audio_*.mp3'),
        ]

    # 源音频清理（用户上传的原始音频）
    if include.get('source_audio'):
        common_patterns += [
            os.path.join(UPLOADS, 'audio', '*'),
            os.path.join(UPLOADS, '*.mp3'),
            os.path.join(UPLOADS, '*.wav'),
            os.path.join(UPLOADS, '*.m4a'),
            os.path.join(UPLOADS, 'music', '*'),
        ]
    if include.get('video'):
        common_patterns += [
            # 剪辑片段
            os.path.join(TEMP, 'clips', '*'),
            os.path.join(TEMP, 'segments', '*'),
            # 合并视频
            os.path.join(TEMP, 'merged_video.mp4'),
            os.path.join(TEMP, 'merged_*.mp4'),
            # 临时输出视频
            os.path.join(TEMP, 'outputs', '*.mp4'),
        ]
        if final_flag:
            # 仅用户显式要求才清理最终输出
            common_patterns += [
                # 自动剪辑成片
                os.path.join(OUTPUT, 'auto_clip_*.mp4'),
                # 原创解说成片
                os.path.join(OUTPUT, 'commentary', '*.mp4'),
                os.path.join(OUTPUT, 'commentary_final_*.mp4'),
                # 混剪成片
                os.path.join(OUTPUT, 'remix', '*.mp4'),
                # 导出目录
                os.path.join(EXPORTS, '**', '*.mp4'),
            ]

    # 源视频清理（用户上传的原始视频）
    if include.get('source_video'):
        common_patterns += [
            os.path.join(UPLOADS, 'videos', '*'),
            os.path.join(UPLOADS, '*.mp4'),
            os.path.join(UPLOADS, '*.avi'),
            os.path.join(UPLOADS, '*.mov'),
            os.path.join(UPLOADS, '*.mkv'),
        ]
    if include.get('frames'):
        common_patterns += [
            # 帧目录
            os.path.join(TEMP, 'analysis', 'frames_*'),
            os.path.join(BACKEND_TEMP, 'analysis', 'frames_*'),
            os.path.join(TEMP, 'frames', '*'),
            # 关键帧图片（重要）
            os.path.join(TEMP, 'analysis', 'mm_keyframe_*.jpg'),
            os.path.join(TEMP, 'analysis', 'keyframe_*.jpg'),
            os.path.join(TEMP, 'analysis', '*.jpg'),
            os.path.join(TEMP, 'analysis', '*.png'),
            # 场景分析帧
            os.path.join(TEMP, 'scene_frames', '*'),
        ]
    if include.get('subtitles'):
        common_patterns += [
            # 临时字幕
            os.path.join(TEMP, 'subtitle.srt'),
            os.path.join(TEMP, 'subtitle_*.srt'),
            os.path.join(TEMP, '*.srt'),
            # 输出字幕
            os.path.join(OUTPUT, '*.srt'),
            os.path.join(OUTPUT, 'commentary', '*.srt'),
            # ASS格式字幕
            os.path.join(TEMP, '*.ass'),
            os.path.join(OUTPUT, '*.ass'),
        ]

    # 目标专属（当前多数产物已覆盖）
    target_patterns = []
    t = (target or '').lower()
    if t in ('smart_cut', 'smartcut', 'auto_clip', 'autoclip', 'commentary'):
        # 已通过 common_patterns 覆盖 temp/analysis, temp/audio, temp/clips, merged, subtitle
        pass
    elif t == 'voiceover':
        # 主要清理语音生成产物
        pass
    elif t == 'remix':
        # 混剪模式：清理片段缓存、关键帧等
        if include.get('cache'):
            target_patterns += [
                os.path.join(TEMP, 'remix_segments', '*'),
            ]
        if include.get('frames'):
            target_patterns += [
                os.path.join(TEMP, 'analysis', 'mm_keyframe_*.jpg'),
            ]
        if include.get('video'):
            target_patterns += [
                os.path.join(TEMP, 'remix', '*'),
                os.path.join(OUTPUT, 'remix', '*') if final_flag else '',
            ]

    # 过滤空字符串
    target_patterns = [p for p in target_patterns if p]

    return {
        'patterns': common_patterns + target_patterns,
        'safe_roots': [TEMP, OUTPUT, UPLOADS, EXPORTS, BACKEND_TEMP]
    }


@cleanup_bp.route('/api/cleanup', methods=['POST'])
def cleanup():
    """
    清理产物
    请求体示例：
    {
        "target": "commentary" | "voiceover" | "remix" | "smart_cut" | "all",
        "include": {
            "cache": true,           // 缓存（分析缓存、remix_segments等）
            "scripts": true,          // 文案脚本（AI生成的解说文案）
            "audio": true,            // 音频（配音、解说音频等）
            "source_audio": false,    // 源音频（用户上传的原始音频，谨慎）
            "video": true,            // 视频（剪辑片段、临时视频等）
            "source_video": false,    // 源视频（用户上传的原始视频，谨慎）
            "frames": true,           // 画面帧（关键帧、分析帧等）
            "subtitles": true,        // 字幕（SRT、ASS格式）
            "final": false            // 最终导出成片（谨慎）
        },
        "dry_run": false,
        "max_age_days": null         // 可选：仅清理N天内修改的文件
    }
    返回：删除统计与预览列表（数量受限）。
    """
    try:
        data = request.get_json() or {}
        target = (data.get('target') or 'all').lower()
        include = data.get('include') or {}
        dry_run = bool(data.get('dry_run'))
        # 可选：仅清理最近 N 天内的产物
        max_age_days_raw = data.get('max_age_days')
        try:
            max_age_days = float(max_age_days_raw) if max_age_days_raw is not None else None
            if max_age_days is not None and max_age_days <= 0:
                max_age_days = None
        except Exception:
            max_age_days = None

        # 合并：all -> 三大目标通用规则
        targets = ['commentary', 'voiceover', 'remix'] if target in ('all', '*') else [target]

        all_patterns: List[str] = []
        safe_roots: List[str] = []
        for t in targets:
            plan = _build_cleanup_plan(t, include)
            all_patterns.extend(plan['patterns'])
            for r in plan.get('safe_roots', []):
                if r not in safe_roots:
                    safe_roots.append(r)

        # 展开匹配
        candidates = _expand_patterns(all_patterns)
        # 去重
        unique = []
        seen = set()
        for p in candidates:
            ap = _ensure_abs(p)
            if ap not in seen:
                seen.add(ap)
                unique.append(ap)

        # 安全根路径过滤，防止误删
        def _under_safe_roots(p: str, roots: List[str]) -> bool:
            p_norm = os.path.normcase(os.path.abspath(p))
            for root in roots:
                try:
                    r_norm = os.path.normcase(os.path.abspath(root))
                    # 确保以目录边界比较
                    if p_norm == r_norm or p_norm.startswith(r_norm + os.sep):
                        return True
                except Exception:
                    continue
            return False

        unique = [p for p in unique if _under_safe_roots(p, safe_roots)]

        # 按时间范围过滤：仅保留最近 N 天修改过的路径
        unique = _filter_by_age(unique, max_age_days)

        preview = unique[:80]  # 返回最多80条预览

        if dry_run:
            total_size = sum(_path_size(p) for p in unique)
            return jsonify({
                'code': 0,
                'msg': '预览成功',
                'data': {
                    'count': len(unique),
                    'bytes': total_size,
                    'preview': preview
                }
            })

        # 真正删除
        deleted = 0
        bytes_freed = 0
        for p in unique:
            c, b = _delete_path(p)
            deleted += c
            bytes_freed += b

        logger.info(f"🧹 清理完成: 删除{deleted}项, 回收{bytes_freed/1024/1024:.2f}MB")

        return jsonify({
            'code': 0,
            'msg': '清理完成',
            'data': {
                'deleted': deleted,
                'bytes_freed': bytes_freed,
                'preview': preview
            }
        })

    except Exception as e:
        logger.error(f"清理失败: {e}", exc_info=True)
        return jsonify({'code': 1, 'msg': f'清理失败: {str(e)}'}), 500


def register_cleanup_routes(app):
    """注册清理路由"""
    app.register_blueprint(cleanup_bp)
    logger.info('✅ 清理API路由注册成功 (1个)')
