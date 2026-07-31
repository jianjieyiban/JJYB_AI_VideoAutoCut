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

    SHORT_VOICE_THRESHOLD = 1.2
    SPEED_MIN = 0.25
    SPEED_MAX = 2.0

    def __init__(self):
        self.logger = logger
        self.last_original_audio_summary: Dict[str, Any] = {'requested': 0, 'inserted': 0, 'skipped_reason': []}

    def match_shots_to_voices(self, shots, voices, allow_reuse=False, insert_original_audio=False,
                              original_clip_interval=3, original_clip_duration=3.0,
                              original_audio_volume=1.0, target_duration_seconds=None,
                              original_audio_mode='interval', original_audio_ratio=None):
        self.logger.info('🎯 开始拟人化匹配: %s 个镜头 ↔ %s 段配音', len(shots), len(voices))
        if not shots or not voices:
            self.logger.warning('⚠️ 镜头或配音为空，无法匹配')
            return []
        voice_groups = self._group_short_voices(voices)
        timeline = []
        used_shot_ids, shot_idx = set(), 0
        for g_idx, group in enumerate(voice_groups):
            audio_duration = sum(float(v.get('duration', 0) or 0) for v in group)
            candidate, candidate_idx = self._pick_next_shot(shots, used_shot_ids, shot_idx, allow_reuse, audio_duration)
            if candidate is None:
                self.logger.warning('⚠️ 第 %s 组配音无可用镜头，跳过', g_idx)
                continue
            shot_idx = candidate_idx + 1
            if not allow_reuse:
                used_shot_ids.add(candidate.get('id'))
            match = self._compute_match_strategy(candidate, audio_duration)
            match.update({'shot_id': candidate['id'], 'voice_indices': [v.get('index', i) for i, v in enumerate(group)], 'voice_paths': [v.get('voice_path', '') for v in group], 'subtitle_text': ''.join(v.get('text', '') for v in group), 'audio_duration': round(audio_duration, 3), 'source_audio_duration': round(audio_duration, 3), 'shot_start': round(candidate['start_time'], 3), 'shot_end': round(candidate['end_time'], 3), 'shot_duration': round(candidate['duration'], 3), 'scene_type': candidate.get('scene_type', 'neutral'), 'shot_score': candidate.get('score', 0.5), 'source_video': candidate.get('source_video') or candidate.get('source_video_path') or candidate.get('video_path') or candidate.get('source_path') or ''})
            timeline.append(match)
        try:
            original_audio_volume = max(0.0, min(1.0, float(original_audio_volume)))
        except (TypeError, ValueError):
            original_audio_volume = 1.0
        mode = str(original_audio_mode or 'interval').lower()
        if mode == 'ratio' and insert_original_audio and target_duration_seconds and original_audio_ratio is not None:
            return self._apply_ratio_original_audio(timeline, shots, used_shot_ids, float(target_duration_seconds), original_audio_ratio, max(0.1, float(original_clip_duration or 3.0)), original_audio_volume)
        return self._apply_interval_original_audio(timeline, shots, used_shot_ids, insert_original_audio, original_clip_interval, original_clip_duration, original_audio_volume)

    def _apply_interval_original_audio(self, timeline, shots, used_for_voice, enabled, interval, clip_duration, volume):
        if not enabled:
            self.last_original_audio_summary = {'mode': 'interval', 'requested': 0, 'inserted': 0, 'skipped_reason': ['未启用原声穿插'], 'warnings': []}
            return timeline
        interval, clip_duration = max(1, int(interval or 3)), max(0.1, float(clip_duration or 3.0))
        remaining = sorted((s for s in shots if s.get('id') not in used_for_voice), key=lambda s: float(s.get('start_time', 0) or 0))
        requested, inserted, skipped, enriched = len(timeline) // interval, 0, [], []
        for index, item in enumerate(timeline, 1):
            enriched.append(item)
            if index % interval:
                continue
            if not remaining:
                skipped.append('没有未分配给解说的镜头')
                continue
            source = next((s for s in remaining if float(s.get('duration', 0) or 0) >= clip_duration), remaining[0])
            remaining.remove(source)
            start, duration = float(source.get('start_time', 0) or 0), min(clip_duration, max(0.1, float(source.get('duration', 0) or 0)))
            enriched.append(self._original_audio_item(source, start, duration, volume, 'duration_sufficient' if duration >= clip_duration else 'duration_insufficient_fallback'))
            inserted += 1
        self.last_original_audio_summary = {'mode': 'interval', 'requested': requested, 'inserted': inserted, 'skipped_reason': skipped, 'warnings': skipped}
        return enriched

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
            warnings.append(f'原声比例达到 100%，但存在解说；为避免解说被压缩为零，保留 {safe_voice_budget:.3f} 秒解说预算')
        voice_target = max(safe_voice_budget, target_total - original_target)
        if valid_voice and voice_target <= 0:
            safe_voice_budget = min(0.1, target_total)
            voice_target = safe_voice_budget
            warnings.append('原声比例导致解说预算为零；已保留 %.3f 秒安全解说预算' % safe_voice_budget)
        if not valid_voice or voice_total <= 0:
            warnings.append('没有有效解说片段，无法按比例归一化')
        else:
            for item in valid_voice:
                old = float(item['final_duration'])
                source_audio_duration = max(0.0, float(item.get('source_audio_duration', item.get('audio_duration', old)) or 0))
                new = max(0.0, old * voice_target / voice_total)
                if new <= 0:
                    warnings.append('已跳过零时长解说片段')
                    continue
                item['source_audio_duration'] = round(source_audio_duration, 3)
                item['final_duration'] = round(new, 3)
                item['audio_duration'] = round(new, 3)
                item['audio_speed_factor'] = round(source_audio_duration / new, 6) if source_audio_duration > 0 else 1.0
                item['speed_factor'] = round(max(self.SPEED_MIN, min(self.SPEED_MAX, float(item.get('speed_factor', 1) or 1) * old / new)), 3)
        voice_budget = sum(float(item.get('final_duration', 0) or 0) for item in valid_voice)
        original_budget = max(0.0, target_total - voice_budget)
        if original_budget + 0.0005 < original_target:
            warnings.append('原声目标受保留解说预算限制，原声实际预算最多为 %.3f 秒' % original_budget)
        remaining = original_budget
        candidates = []
        for shot in sorted((s for s in shots if s.get('id') not in used_for_voice), key=lambda s: float(s.get('start_time', 0) or 0)):
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
        if shortfall > 0.0005:
            skipped.append('未分配镜头素材不足，无法达到原声预算')
            warnings.append('原声预算缺少 %.3f 秒，已由解说片段补足总时长' % shortfall)
            if valid_voice:
                last_voice = valid_voice[-1]
                last_voice['final_duration'] = round(float(last_voice['final_duration']) + shortfall, 3)
                last_voice['audio_duration'] = last_voice['final_duration']
                source_audio_duration = float(last_voice.get('source_audio_duration', 0) or 0)
                last_voice['audio_speed_factor'] = round(source_audio_duration / last_voice['final_duration'], 6) if source_audio_duration > 0 else 1.0
        enriched = list(timeline)
        for offset, original in enumerate(originals):
            position = int(round((offset + 1) * len(enriched) / (len(originals) + 1))) + offset
            enriched.insert(max(0, min(len(enriched), position)), original)
        actual_total = sum(max(0.0, float(item.get('final_duration', 0) or 0)) for item in enriched)
        correction = target_total - actual_total
        adjustable = next((item for item in reversed(enriched) if not item.get('original_audio') and float(item.get('final_duration', 0) or 0) + correction >= 0), None)
        if adjustable and abs(correction) > 0.0005:
            adjustable['final_duration'] = round(max(0.0, float(adjustable['final_duration']) + correction), 3)
            adjustable['audio_duration'] = adjustable['final_duration']
            source_audio_duration = float(adjustable.get('source_audio_duration', 0) or 0)
            adjustable['audio_speed_factor'] = round(source_audio_duration / adjustable['final_duration'], 6) if source_audio_duration > 0 and adjustable['final_duration'] > 0 else 1.0
            actual_total = sum(max(0.0, float(item.get('final_duration', 0) or 0)) for item in enriched)
        exact = safe_voice_budget <= 0 and shortfall <= 0.0005 and abs(actual_total - target_total) <= 0.005
        self.last_original_audio_summary = {'mode': 'ratio', 'target_ratio': ratio, 'target_total_seconds': round(target_total, 3), 'actual_total_seconds': round(actual_total, 3), 'target_seconds': round(original_target, 3), 'actual_seconds': round(actual_original, 3), 'actual_ratio': round(actual_original / actual_total, 6) if actual_total else 0, 'exact_ratio_achieved': exact, 'requested': round(original_target, 3), 'inserted': len(originals), 'shortfall_seconds': round(shortfall, 3), 'skipped_reason': skipped, 'warnings': warnings}
        return enriched

    @staticmethod
    def _build_atempo_chain(speed_factor: float) -> str:
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
        return {'kind': 'original_audio', 'original_audio': True, 'original_audio_volume': volume, 'selection_reason': reason, 'shot_id': shot.get('id'), 'voice_indices': [], 'voice_paths': [], 'subtitle_text': '', 'audio_duration': round(duration, 3), 'final_duration': round(duration, 3), 'source_duration': round(duration, 3), 'target_duration': round(duration, 3), 'shot_start': round(source_start, 3), 'shot_end': round(source_end, 3), 'shot_duration': round(duration, 3), 'source_start': round(source_start, 3), 'source_end': round(source_end, 3), 'source_video': shot.get('source_video') or shot.get('source_video_path') or shot.get('video_path') or shot.get('source_path') or '', 'speed_factor': 1.0, 'freeze_tail': False, 'is_fixed_ost': False, 'cut_strategy': 'direct'}

    def _group_short_voices(self, voices):
        if not voices:
            return []
        voices = [dict(v) for v in voices]
        for i, v in enumerate(voices):
            v.setdefault('index', i)
        groups = []
        i = 0
        while i < len(voices):
            cur = voices[i]
            cur_dur = float(cur.get('duration', 0))
            if cur_dur < self.SHORT_VOICE_THRESHOLD and i + 1 < len(voices):
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

    def _pick_next_shot(self, shots, used_shot_ids, start_idx, allow_reuse, target_duration):
        for i in range(start_idx, len(shots)):
            if shots[i].get('id') not in used_shot_ids:
                return shots[i], i
        for i in range(0, min(start_idx, len(shots))):
            if shots[i].get('id') not in used_shot_ids:
                return shots[i], i
        if allow_reuse and shots:
            best_index, best_shot = max(enumerate(shots), key=lambda pair: pair[1].get('score', 0))
            return best_shot, best_index
        return None, -1

    def _compute_match_strategy(self, shot, audio_duration):
        shot_dur = float(shot.get('duration', 0))
        audio_dur = max(0.1, float(audio_duration))
        final_duration = audio_dur
        if shot_dur <= 0:
            return {'cut_strategy': 'cut_highlight', 'speed_factor': 1.0, 'freeze_tail': False, 'final_duration': round(final_duration, 3), 'source_start': 0.0, 'source_end': round(min(audio_dur, 3.0), 3)}
        if abs(shot_dur - audio_dur) < 0.3 or 0.9 <= (shot_dur / audio_dur) <= 1.1:
            return {'cut_strategy': 'direct', 'speed_factor': 1.0, 'freeze_tail': False, 'final_duration': round(final_duration, 3), 'source_start': round(float(shot.get('start_time', 0)), 3), 'source_end': round(float(shot.get('end_time', shot_dur)), 3)}
        if shot_dur < audio_dur:
            speed = shot_dur / audio_dur
            if speed >= self.SPEED_MIN:
                return {'cut_strategy': 'slow_down', 'speed_factor': round(speed, 3), 'freeze_tail': False, 'final_duration': round(final_duration, 3), 'source_start': round(float(shot.get('start_time', 0)), 3), 'source_end': round(float(shot.get('end_time', shot_dur)), 3)}
            else:
                frozen_part = audio_dur - (shot_dur / self.SPEED_MIN)
                return {'cut_strategy': 'freeze', 'speed_factor': round(self.SPEED_MIN, 3), 'freeze_tail': True, 'freeze_duration': round(max(0.0, frozen_part), 3), 'final_duration': round(final_duration, 3), 'source_start': round(float(shot.get('start_time', 0)), 3), 'source_end': round(float(shot.get('end_time', shot_dur)), 3)}
        shot_start = float(shot.get('start_time', 0))
        shot_end = float(shot.get('end_time', shot_dur))
        center = (shot_start + shot_end) / 2
        half_audio = audio_dur / 2
        cut_start = max(shot_start, center - half_audio)
        cut_end = min(shot_end, cut_start + audio_dur)
        if cut_end - cut_start < audio_dur:
            cut_start = max(shot_start, cut_end - audio_dur)
        return {'cut_strategy': 'cut_highlight', 'speed_factor': 1.0, 'freeze_tail': False, 'final_duration': round(final_duration, 3), 'source_start': round(cut_start, 3), 'source_end': round(cut_end, 3)}

    def render_timeline(self, video_path, timeline, output_path=None, bgm_path=None, bgm_volume=0.25, subtitle_path=None):
        self.logger.info(f'🎬 开始渲染拟人化剪辑时间轴: {len(timeline)} 个片段')
        if not timeline:
            raise ValueError('时间轴为空，无法渲染')
        v_path = Path(video_path).resolve()
        if not v_path.exists():
            raise FileNotFoundError(f'源视频不存在: {v_path}')
        out_dir = PROJECT_ROOT / 'output' / 'videos'
        out_dir.mkdir(parents=True, exist_ok=True)
        if not output_path:
            output_path = str(out_dir / f"puppet_{datetime.now().strftime('%Y%m%d%H%M%S')}.mp4")
        tmp_dir = out_dir / f"tmp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        try:
            clip_paths = []
            for i, item in enumerate(timeline):
                item_video_path = item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path')
                clip_source = Path(item_video_path).resolve() if item_video_path else v_path
                if not clip_source.exists():
                    raise FileNotFoundError(f'时间线片段源视频不存在: {clip_source}')
                clip_path = self._render_single_clip(clip_source, item, tmp_dir / f"clip_{i:04d}.mp4")
                if clip_path:
                    prev_item = timeline[i - 1] if i > 0 else None
                    has_next = i < len(timeline) - 1
                    clip_path = self._apply_transition(Path(clip_path), item, prev_item, has_next)
                    clip_paths.append(clip_path)
            if not clip_paths:
                raise RuntimeError('所有片段渲染失败')
            concat_path = tmp_dir / 'concat.txt'
            with open(concat_path, 'w', encoding='utf-8', newline='\n') as f:
                for p in clip_paths:
                    abs_p = Path(p).resolve().as_posix()
                    abs_p_escaped = abs_p.replace("'", "'\\''")
                    f.write(f"file '{abs_p_escaped}'\n")
            merged_video = tmp_dir / 'merged.mp4'
            cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_path), '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-an', str(merged_video)]
            self._run_ffmpeg(cmd, '拼接片段')
            audio_parts = []
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
                        self._run_ffmpeg(['ffmpeg', '-y', '-ss', f'{source_start:.3f}', '-i', str(audio_source), '-t', f'{duration:.3f}', '-vn', '-af', f'volume={original_audio_volume:.3f},apad', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)], f'提取原声片段 shot={item.get("shot_id")}')
                    except RuntimeError:
                        self.logger.warning('原声提取失败，使用等长静音: shot=%s', item.get('shot_id'))
                        self._run_ffmpeg(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', f'{duration:.3f}', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)], f'生成原声静音段 {index}')
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
                        self._run_ffmpeg(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(voice_list), '-t', f'{duration:.3f}', '-af', audio_filter, '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)], f'合并配音段 {index}')
                    else:
                        self._run_ffmpeg(['ffmpeg', '-y', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', f'{duration:.3f}', '-ar', '48000', '-ac', '2', '-c:a', 'pcm_s16le', str(part_path)], f'生成配音空白段 {index}')
                if part_path.exists():
                    audio_parts.append(part_path)
            merged_audio = tmp_dir / 'timeline_audio.aac'
            if audio_parts:
                audio_concat = tmp_dir / 'audio_concat.txt'
                with open(audio_concat, 'w', encoding='utf-8', newline='\n') as handle:
                    for audio_part in audio_parts:
                        abs_p = audio_part.resolve().as_posix()
                        handle.write(f"file '{abs_p.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'\n")
                self._run_ffmpeg(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(audio_concat), '-ar', '48000', '-ac', '2', '-c:a', 'aac', str(merged_audio)], '按时间轴合并配音与原声')
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
                sub_path = Path(subtitle_path).resolve().as_posix()
                sub_escaped = sub_path.replace('\\', '/').replace(':', '\\:')
                final_cmd.extend(['-vf', f"subtitles='{sub_escaped}'"])
            final_cmd.extend(['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', output_path])
            self._run_ffmpeg(final_cmd, '最终合成')
            self.logger.info(f'✅ 渲染完成: {output_path}')
            return output_path
        finally:
            try:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def _build_dedup_filters(item):
        dt = item.get('dedup_transform') if isinstance(item, dict) else None
        if not dt:
            return ''
        filters = []
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

    def _render_single_clip(self, video_path, item, output_path):
        strategy = item.get('cut_strategy', 'direct')
        src_start = float(item.get('source_start', 0))
        src_end = float(item.get('source_end', 0))
        speed = max(0.0001, float(item.get('speed_factor', 1.0)))
        target_duration = max(0.05, float(item.get('final_duration') or item.get('audio_duration') or (src_end - src_start)))
        freeze = item.get('freeze_tail', False)
        freeze_dur = float(item.get('freeze_duration', 0))
        dedup_filters = self._build_dedup_filters(item)

        def normalize_duration(input_path, label):
            input_dur = 0.0
            try:
                probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(input_path)], capture_output=True, text=True, timeout=60)
                input_dur = float(probe.stdout.strip() or '0')
            except Exception:
                input_dur = 0.0
            if input_dur > 0 and target_duration >= input_dur and (target_duration - input_dur) < 0.05:
                if input_path.resolve() != output_path.resolve():
                    import shutil
                    shutil.copy2(str(input_path), str(output_path))
                return str(output_path)
            normalized_path = output_path
            replace_output = input_path.resolve() == output_path.resolve()
            if replace_output:
                normalized_path = output_path.with_suffix('.normalized.mp4')
            self._run_ffmpeg(['ffmpeg', '-y', '-i', str(input_path), '-filter:v', f'trim=duration={target_duration:.3f},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration={target_duration:.3f}', '-t', f'{target_duration:.3f}', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', str(normalized_path)], label)
            if replace_output:
                normalized_path.replace(output_path)
            return str(output_path)

        try:
            if strategy == 'direct' or strategy == 'cut_highlight':
                duration = max(0.05, min(src_end - src_start, target_duration))
                cmd = ['ffmpeg', '-y', '-ss', f'{src_start:.3f}', '-i', str(video_path), '-t', f'{duration:.3f}']
                if dedup_filters:
                    cmd.extend(['-filter:v', dedup_filters])
                cmd.extend(['-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', str(output_path)])
                self._run_ffmpeg(cmd, f'截取片段 shot={item.get("shot_id")}')
                return normalize_duration(output_path, f'校正片段时长 shot={item.get("shot_id")}')
            elif strategy == 'slow_down':
                src_duration = max(0.05, src_end - src_start)
                pts_factor = 1.0 / speed
                vfilter = ','.join(filter(None, [dedup_filters, f'setpts={pts_factor:.3f}*PTS']))
                cmd = ['ffmpeg', '-y', '-ss', f'{src_start:.3f}', '-i', str(video_path), '-t', f'{src_duration:.3f}', '-filter:v', vfilter, '-an', str(output_path)]
                self._run_ffmpeg(cmd, f'变速片段 shot={item.get("shot_id")} speed={speed}')
                return normalize_duration(output_path, f'校正慢放时长 shot={item.get("shot_id")}')
            elif strategy == 'freeze':
                src_duration = max(0.05, src_end - src_start)
                pts_factor = 1.0 / speed
                slow_clip = output_path.with_suffix('.slow.mp4')
                slow_vfilter = ','.join(filter(None, [dedup_filters, f'setpts={pts_factor:.3f}*PTS']))
                cmd = ['ffmpeg', '-y', '-ss', f'{src_start:.3f}', '-i', str(video_path), '-t', f'{src_duration:.3f}', '-filter:v', slow_vfilter, '-an', str(slow_clip)]
                self._run_ffmpeg(cmd, f'慢放片段 shot={item.get("shot_id")}')
                if freeze_dur > 0.1 and slow_clip.exists():
                    last_frame = output_path.with_suffix('.last.png')
                    last_frame_ok = False
                    try:
                        cmd = ['ffmpeg', '-y', '-sseof', '-0.05', '-i', str(slow_clip), '-frames:v', '1', str(last_frame)]
                        self._run_ffmpeg(cmd, '提取末帧(-sseof)')
                        last_frame_ok = last_frame.exists() and last_frame.stat().st_size > 0
                    except RuntimeError as e:
                        self.logger.warning('⚠️ -sseof 提取末帧失败: %s', e)
                    if not last_frame_ok:
                        try:
                            probe = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=nb_frames', '-of', 'default=noprint_wrappers=1:nokey=1', str(slow_clip)], capture_output=True, text=True, timeout=60)
                            frame_count = int(probe.stdout.strip() or '0')
                            if frame_count > 0:
                                cmd = ['ffmpeg', '-y', '-i', str(slow_clip), '-vf', f'select=eq(n\\,{frame_count - 1})', '-frames:v', '1', str(last_frame)]
                                self._run_ffmpeg(cmd, f'提取末帧(select n={frame_count - 1})')
                                last_frame_ok = last_frame.exists() and last_frame.stat().st_size > 0
                        except (RuntimeError, ValueError) as e:
                            self.logger.warning('⚠️ select 提取末帧失败: %s', e)
                    if last_frame_ok:
                        freeze_clip = output_path.with_suffix('.freeze.mp4')
                        cmd = ['ffmpeg', '-y', '-loop', '1', '-i', str(last_frame), '-t', f'{freeze_dur:.3f}', '-r', '30', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', str(freeze_clip)]
                        self._run_ffmpeg(cmd, '生成定格片段')
                        concat_file = output_path.with_suffix('.concat.txt')
                        with open(concat_file, 'w', encoding='utf-8', newline='\n') as f:
                            slow_p = slow_clip.resolve().as_posix().replace("'", "'\\''")
                            freeze_p = freeze_clip.resolve().as_posix().replace("'", "'\\''")
                            f.write(f"file '{slow_p}'\n")
                            f.write(f"file '{freeze_p}'\n")
                        cmd = ['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(concat_file), '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-an', str(output_path)]
                        self._run_ffmpeg(cmd, '拼接慢放+定格')
                        return normalize_duration(output_path, f'校正定格时长 shot={item.get("shot_id")}')
                    else:
                        self.logger.warning('⚠️ 末帧提取失败，改用 tpad 克隆填充定格段 shot=%s', item.get('shot_id'))
                        self._run_ffmpeg(['ffmpeg', '-y', '-i', str(slow_clip), '-vf', f'tpad=stop_mode=clone:stop_duration={freeze_dur:.3f}', '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', str(output_path)], 'tpad 克隆填充定格段')
                        return normalize_duration(output_path, f'校正(tpad)定格时长 shot={item.get("shot_id")}')
                return normalize_duration(slow_clip, f'校正慢放定格时长 shot={item.get("shot_id")}')
            else:
                self.logger.warning(f'⚠️ 未知策略: {strategy}')
                return None
        except Exception as e:
            self.logger.error(f'❗ 渲染片段失败 shot={item.get("shot_id")}: {e}')
            return None

    def _apply_transition(self, clip_path, item, prev_item, has_next):
        fade_in_dur = 0.0
        fade_out_dur = 0.0
        if prev_item:
            trans_in = str(prev_item.get('transition', 'none') or 'none').lower()
            if trans_in in ('fade', 'dissolve'):
                try:
                    fade_in_dur = float(prev_item.get('transition_duration', 0.3) or 0.3)
                except (TypeError, ValueError):
                    fade_in_dur = 0.3
        if has_next:
            trans_out = str(item.get('transition', 'none') or 'none').lower()
            if trans_out in ('fade', 'dissolve'):
                try:
                    fade_out_dur = float(item.get('transition_duration', 0.3) or 0.3)
                except (TypeError, ValueError):
                    fade_out_dur = 0.3
        if fade_in_dur <= 0 and fade_out_dur <= 0:
            return str(clip_path)
        clip_dur = 0.0
        try:
            probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(clip_path)], capture_output=True, text=True, timeout=60)
            clip_dur = float(probe.stdout.strip() or '0')
        except Exception:
            clip_dur = 0.0
        if clip_dur <= 0:
            return str(clip_path)
        if fade_in_dur + fade_out_dur >= clip_dur:
            return str(clip_path)
        filters = []
        if fade_in_dur > 0:
            filters.append(f'fade=t=in:st=0:d={fade_in_dur:.3f}')
        if fade_out_dur > 0:
            filters.append(f'fade=t=out:st={max(0.0, clip_dur - fade_out_dur):.3f}:d={fade_out_dur:.3f}')
        out_path = clip_path.with_suffix('.trans.mp4')
        self._run_ffmpeg(['ffmpeg', '-y', '-i', str(clip_path), '-vf', ','.join(filters), '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-an', str(out_path)], f'转场处理 fade_in={fade_in_dur:.2f}s fade_out={fade_out_dur:.2f}s')
        return str(out_path)

    def _run_ffmpeg(self, cmd, label=''):
        self.logger.info(f'🎬 FFmpeg [{label}]: {" ".join(cmd)}')
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            err = (result.stderr or '')[:500]
            raise RuntimeError(f'FFmpeg 执行失败 [{label}]: {err}')
        return True


_instance = None


def get_puppet_sync_engine():
    global _instance
    if _instance is None:
        _instance = PuppetSyncEngine()
    return _instance
