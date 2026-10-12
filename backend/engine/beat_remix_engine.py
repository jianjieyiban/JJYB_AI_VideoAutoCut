"""
音乐卡点混剪引擎
实现音乐节拍检测 + 画面分析 + 关键帧 = 超流畅混剪
"""

import logging
import numpy as np
from typing import List, Dict, Any, Optional
import os

logger = logging.getLogger('JJYB_AI智剪')


class BeatRemixEngine:
    """音乐卡点混剪引擎"""

    def __init__(self):
        """初始化混剪引擎"""
        self.logger = logger
        self.sample_rate = 22050
        self._init_libraries()

    def _init_libraries(self):
        """初始化音频处理库"""
        try:
            import librosa
            self.librosa = librosa
            self.librosa_available = True
            self.logger.info("✅ Librosa加载成功")
        except ImportError:
            self.librosa_available = False
            self.logger.warning("⚠️ Librosa未安装，音乐卡点功能将受限")

        try:
            import cv2
            self.cv2 = cv2
            self.cv2_available = True
        except ImportError:
            self.cv2_available = False
            self.logger.warning("⚠️ OpenCV未安装")

    def create_beat_remix(self, video_clips: List[str], music_path: str,
                         style: str = 'dynamic',
                         target_duration: Optional[float] = None,
                         beat_detection: Optional[str] = None,
                         beat_sensitivity: Optional[str] = None,
                         fast_keyframe: Optional[str] = None,
                         slow_keyframe: Optional[str] = None,
                         speed_curve: Optional[str] = None,
                         beat_transition: Optional[str] = None,
                         rhythm_match: Optional[str] = None,
                         sync_precision: Optional[str] = None) -> Dict[str, Any]:
        """
        创建音乐卡点混剪

        Args:
            video_clips: 视频片段路径列表
            music_path: 音乐文件路径
            style: 混剪风格 (dynamic/calm/exciting)
            target_duration: 目标时长（秒）

        Returns:
            混剪结果
        """
        try:
            target_duration = float(target_duration)
        except (TypeError, ValueError):
            raise ValueError('必须显式提供大于 0 的 target_duration_seconds')
        if not np.isfinite(target_duration) or target_duration <= 0:
            raise ValueError('target_duration_seconds 必须为大于 0 的有限数值')

        self.logger.info(f"🎵 开始创建{style}风格的音乐卡点混剪")

        result = {
            'music_analysis': {},
            'clips_analysis': [],
            'beat_matches': [],
            'keyframes': [],
            'final_timeline': [],
            'config': {
                'style': style,
                'target_duration': target_duration,
                'beat_detection': beat_detection,
                'beat_sensitivity': beat_sensitivity,
                'fast_keyframe': fast_keyframe,
                'slow_keyframe': slow_keyframe,
                'speed_curve': speed_curve,
                'beat_transition': beat_transition,
                'rhythm_match': rhythm_match,
                'sync_precision': sync_precision
            }
        }

        try:
            # 1. 分析音乐
            self.logger.info("🎼 分析音乐节奏...")
            music_analysis = self.analyze_music(music_path)
            result['music_analysis'] = music_analysis

            # 2. 分析视频片段
            self.logger.info("🎬 分析视频片段...")
            clips_analysis = []
            for i, clip_path in enumerate(video_clips):
                self.logger.info(f"  分析片段 {i+1}/{len(video_clips)}")
                clip_info = self.analyze_clip(clip_path)
                clips_analysis.append(clip_info)
            result['clips_analysis'] = clips_analysis

            # 3. 智能匹配片段到节拍
            self.logger.info("🎯 匹配片段到节拍...")
            beat_matches = self.match_clips_to_beats(
                clips_analysis,
                music_analysis,
                style,
                target_duration,
                beat_detection=beat_detection,
                beat_sensitivity=beat_sensitivity,
                fast_keyframe=fast_keyframe,
                slow_keyframe=slow_keyframe,
                speed_curve=speed_curve,
                sync_precision=sync_precision,
                beat_transition=beat_transition,
                rhythm_match=rhythm_match
            )
            result['beat_matches'] = beat_matches

            # 4. 生成关键帧和变速效果
            self.logger.info("⚡ 生成关键帧...")
            keyframes = self.generate_keyframes(beat_matches, music_analysis)
            result['keyframes'] = keyframes

            # 5. 生成最终时间轴
            self.logger.info("📋 生成最终时间轴...")
            timeline = self.generate_timeline(beat_matches, keyframes)
            result['final_timeline'] = timeline

            self.logger.info("✅ 音乐卡点混剪方案生成完成")
            return result

        except Exception as e:
            self.logger.error(f"❌ 混剪创建失败: {e}", exc_info=True)
            raise

    def analyze_music(self, music_path: str) -> Dict[str, Any]:
        """
        分析音乐节奏

        Args:
            music_path: 音乐文件路径

        Returns:
            音乐分析结果
        """
        result = {
            'tempo': 120,
            'beats': [],
            'strong_beats': [],
            'duration': 0,
            'energy_curve': [],
            'sections': []
        }

        if not self.librosa_available:
            self.logger.warning("⚠️ Librosa不可用，使用默认音乐分析")
            return result

        try:
            # 加载音频
            y, sr = self.librosa.load(music_path, sr=self.sample_rate)
            duration = len(y) / sr

            # BPM检测
            tempo, beats = self.librosa.beat.beat_track(y=y, sr=sr)
            # librosa 有时会返回 ndarray，这里统一转为标量，避免后续格式化/日志报错
            try:
                if hasattr(tempo, '__len__'):
                    tempo_scalar = float(tempo[0]) if len(tempo) > 0 else 120.0
                else:
                    tempo_scalar = float(tempo)
            except Exception:
                tempo_scalar = 120.0
            beat_times = self.librosa.frames_to_time(beats, sr=sr)

            # 节奏强度分析
            onset_env = self.librosa.onset.onset_strength(y=y, sr=sr)

            # 检测强拍
            strong_beats = self._detect_strong_beats(onset_env, beats)
            strong_beat_times = self.librosa.frames_to_time(strong_beats, sr=sr)

            # 能量曲线
            rms = self.librosa.feature.rms(y=y)[0]
            energy_times = self.librosa.frames_to_time(np.arange(len(rms)), sr=sr)

            # 音乐分段（高潮、过渡等）
            sections = self._detect_music_sections(y, sr, beat_times)

            result.update({
                'tempo': float(tempo_scalar),
                'beats': beat_times.tolist(),
                'strong_beats': strong_beat_times.tolist(),
                'duration': float(duration),
                'energy_curve': list(zip(energy_times.tolist(), rms.tolist())),
                'sections': sections,
                'beat_count': len(beat_times),
                'strong_beat_count': len(strong_beat_times)
            })

            self.logger.info(f"✅ 音乐分析完成: BPM={tempo_scalar:.1f}, 节拍数={len(beat_times)}")
            return result

        except Exception as e:
            self.logger.error(f"❌ 音乐分析失败: {e}")
            return result

    def analyze_clip(self, clip_path: str) -> Dict[str, Any]:
        """
        分析视频片段

        Args:
            clip_path: 视频片段路径

        Returns:
            片段分析结果
        """
        result = {
            'path': clip_path,
            'duration': 0,
            'fps': 30,
            'motion_intensity': 0.5,
            'scene_type': 'neutral',
            'brightness': 0.5,
            'color_richness': 0.5,
            'suitable_for_beat': True
        }

        if not self.cv2_available:
            return result

        try:
            import cv2
            cap = cv2.VideoCapture(clip_path)

            if not cap.isOpened():
                self.logger.warning(f"⚠️ 无法打开视频: {clip_path}")
                return result

            fps = cap.get(cv2.CAP_PROP_FPS)
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = frame_count / fps if fps > 0 else 0

            # 采样分析
            sample_frames = []
            for i in range(0, frame_count, max(1, frame_count // 10)):
                cap.set(cv2.CAP_PROP_POS_FRAMES, i)
                ret, frame = cap.read()
                if ret:
                    sample_frames.append(frame)

            cap.release()

            if sample_frames:
                # 计算运动强度
                motion_intensity = self._calculate_motion_intensity(sample_frames)

                # 分析亮度
                brightness = self._calculate_brightness(sample_frames)

                # 分析色彩丰富度
                color_richness = self._calculate_color_richness(sample_frames)

                # 场景分类
                scene_type = self._classify_scene(motion_intensity, brightness, color_richness)

                result.update({
                    'duration': float(duration),
                    'fps': float(fps),
                    'motion_intensity': float(motion_intensity),
                    'scene_type': scene_type,
                    'brightness': float(brightness),
                    'color_richness': float(color_richness),
                    'frame_count': frame_count
                })

            self.logger.info(f"✅ 片段分析完成: {os.path.basename(clip_path)}")
            return result

        except Exception as e:
            self.logger.error(f"❌ 片段分析失败: {e}")
            return result

    @staticmethod
    def _coalesce_beat_boundaries(beats: List[float], target_duration: float, min_visual_duration: float) -> List[float]:
        """Merge beat cuts that are too short to be a readable visual shot."""
        target = float(target_duration)
        minimum = max(0.12, float(min_visual_duration))
        boundaries = [0.0]
        for raw in sorted({float(beat) for beat in beats if 0.0 < float(beat) < target}):
            if raw - boundaries[-1] >= minimum:
                boundaries.append(round(raw, 3))
        if target - boundaries[-1] < minimum and len(boundaries) > 1:
            boundaries.pop()
        boundaries.append(round(target, 3))
        return boundaries

    @staticmethod
    def _first_free_source_window(source_path: str, source_duration: float, required_duration: float,
                                  reservations: Dict[str, List[tuple]]) -> Optional[tuple]:
        """Return an unused source range; never loop back to the opening frame."""
        cursor = 0.0
        for reserved_start, reserved_end in sorted(reservations.get(source_path, [])):
            if reserved_end <= cursor:
                continue
            if reserved_start - cursor + 1e-6 >= required_duration:
                return cursor, cursor + required_duration
            cursor = max(cursor, reserved_end)
        if cursor + required_duration <= source_duration + 1e-6:
            return cursor, cursor + required_duration
        return None

    def match_clips_to_beats(self, clips_analysis: List[Dict],
                            music_analysis: Dict,
                            style: str,
                            target_duration: Optional[float] = None,
                            beat_detection: Optional[str] = None,
                            beat_sensitivity: Optional[str] = None,
                            fast_keyframe: Optional[str] = None,
                            slow_keyframe: Optional[str] = None,
                            speed_curve: Optional[str] = None,
                            sync_precision: Optional[str] = None,
                            beat_transition: Optional[str] = None,
                            rhythm_match: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        将片段匹配到音乐节拍

        Args:
            clips_analysis: 片段分析结果列表
            music_analysis: 音乐分析结果
            style: 混剪风格
            target_duration: 目标时长

        Returns:
            匹配结果列表
        """
        beats_all = music_analysis.get('beats', []) or []
        beats_strong = music_analysis.get('strong_beats', []) or []
        tempo = music_analysis.get('tempo', 120)

        det = str(beat_detection or '').lower()
        sens = str(beat_sensitivity or '').lower()
        fk = str(fast_keyframe or '').lower()

        if det in ('fft', 'onset'):
            beats = beats_strong or beats_all
        elif det in ('tempo', 'ml'):
            beats = beats_all or beats_strong
        else:
            beats = beats_strong or beats_all

        # fast_keyframe 对节拍选择的影响：strong 模式只用强拍
        if fk == 'strong' and beats_strong:
            beats = beats_strong

        beats = list(beats)

        if not beats:
            self.logger.warning("⚠️ 没有检测到节拍")
            return []

        try:
            target_duration = float(target_duration)
        except (TypeError, ValueError):
            raise ValueError('必须显式提供大于 0 的 target_duration_seconds')
        if not np.isfinite(target_duration) or target_duration <= 0:
            raise ValueError('target_duration_seconds 必须为大于 0 的有限数值')

        if len(beats) > 1:
            if sens == 'low':
                step = 3 if len(beats) >= 3 else 2
                beats = beats[::step]
            elif sens == 'medium':
                beats = beats[::2]

        if len(beats) < 2:
            self.logger.warning("⚠️ 有效节拍过少，无法进行卡点匹配")
            return []

        if style == 'dynamic':
            target_clip_duration = 60 / tempo if tempo > 0 else 0.5
        elif style == 'calm':
            target_clip_duration = 120 / tempo if tempo > 0 else 1.0
        elif style == 'exciting':
            target_clip_duration = 30 / tempo if tempo > 0 else 0.25
        else:
            target_clip_duration = 60 / tempo if tempo > 0 else 0.5

        min_visual_duration = {'dynamic': 0.55, 'calm': 1.0, 'exciting': 0.4}.get(style, 0.55)
        beats = self._coalesce_beat_boundaries(beats, target_duration, min_visual_duration)
        if len(beats) < 2:
            raise RuntimeError('目标区间内没有可用节拍，无法生成覆盖 0 到目标结束的卡点时间轴')
        
        # 素材不足时发出警告（代码支持复用素材，但仍需告知用户）
        if len(clips_analysis) < len(beats) - 1:
            self.logger.warning(
                '⚠️ 可用素材 %d 个少于卡点区间 %d 个，将启用素材复用模式' %
                (len(clips_analysis), len(beats) - 1)
            )

        total_beats = len(beats) - 1
        matches = []
        source_reservations: Dict[str, List[tuple]] = {}
        previous_clip_path = ''
        # 记录每个源片段已经使用到的视频内偏移，用于让后续节拍在同一素材内向后推进，避免永远从0秒开始
        clip_offsets: Dict[str, float] = {}
        rm = str(rhythm_match or '').lower()
        sk = str(slow_keyframe or '').lower()
        sc = str(speed_curve or '').lower()
        sp = str(sync_precision or '').lower()
        bt = str(beat_transition or '').lower()

        if not sc:
            if bt == 'flash':
                sc = 'sharp'
            elif bt == 'zoom':
                sc = 'smooth'
            elif bt == 'shake':
                sc = 'sharp'

        sections = music_analysis.get('sections', []) or []

        def _section_type_at(t: float) -> str:
            for s in sections:
                try:
                    if float(s.get('start', 0.0)) <= t < float(s.get('end', 0.0)):
                        return str(s.get('type', ''))
                except Exception:
                    continue
            return ''

        for i in range(total_beats):
            beat_time = beats[i]
            next_beat_time = beats[i + 1]
            output_duration = next_beat_time - beat_time
            if output_duration <= 0:
                raise RuntimeError('检测到非递增节拍边界，无法生成卡点时间轴')

            # 速度效果只决定播放速度和所需源窗口，绝不改变 beat->next_beat 的输出边界。
            playback_speed = 1.0
            sec_type = _section_type_at(float(beat_time))
            if sk == 'transition' and sec_type == 'low':
                playback_speed *= 1.5
            elif sk == 'climax' and sec_type == 'high':
                playback_speed *= 1.5

            if sc == 'smooth':
                pos = i / max(1, total_beats - 1)
                playback_speed *= (0.8 + 0.4 * pos)
            elif sc == 'sharp':
                playback_speed *= (0.7 if i % 2 == 0 else 1.3)
            elif sc == 'stepped':
                pos = i / max(1, total_beats)
                playback_speed *= 0.9 if pos < 1 / 3 else (1.0 if pos < 2 / 3 else 1.1)

            if sp == 'frame':
                playback_speed = max(0.8, min(1.2, playback_speed))
            elif sp == 'subframe':
                playback_speed = max(0.7, min(1.3, playback_speed))
            elif sp == 'beat':
                playback_speed = max(0.6, min(1.4, playback_speed))
            if not 0.5 <= playback_speed <= 2.0:
                raise RuntimeError('卡点播放速度超出渲染器支持范围')

            effective_style = style
            if rm == 'intense':
                effective_style = 'exciting'
            elif rm == 'calm':
                effective_style = 'calm'
            elif rm == 'contrast':
                effective_style = 'dynamic' if i % 2 == 0 else 'calm'

            source_duration = output_duration * playback_speed
            clip = self._select_best_clip(
                clips_analysis, source_reservations, effective_style, source_duration, beat_time
            )
            if not clip:
                raise RuntimeError('没有可用素材覆盖当前卡点区间')

            clip_path = clip['path']
            if not clip.get('_source_window'):
                raise RuntimeError('素材不足以覆盖全部卡点区间，拒绝复用镜头补足时长')
            clip_total = float(clip.get('duration') or 0.0)
            if clip_total < source_duration:
                raise RuntimeError(
                    '素材 %s 长度不足：需要 %.3fs 源窗口以输出 %.3fs 卡点区间' %
                    (clip_path, source_duration, output_duration)
                )

            # 每个源文件仅匹配一个区间，不回绕、不缩短、不定格。
            source_start, source_end = clip.get('_source_window', (None, None))
            if source_start is None or source_end is None:
                raise RuntimeError('卡点匹配没有生成有效的未重复源窗口')
            source_reservations.setdefault(clip_path, []).append((source_start, source_end))
            previous_clip_path = clip_path
            matches.append({
                'clip_path': clip_path,
                'beat_index': i,
                'start_time': float(beat_time),
                'end_time': float(next_beat_time),
                # 旧字段保留：duration 始终是成片输出时长。
                'duration': float(output_duration),
                'output_duration': float(output_duration),
                'playback_speed': float(playback_speed),
                'speed_factor': float(playback_speed),
                # 新旧源窗口字段并存以保持调用方兼容。
                'source_start': float(source_start),
                'source_end': float(source_end),
                'clip_start': float(source_start),
                'clip_end': float(source_end),
                'clip_info': clip,
            })
            # The reservation records the exact source window.  Reusing a
            # later, non-overlapping window from this file is intentional.

        self.logger.info(f"✅ 匹配完成: {len(matches)}个片段")
        return matches

    def generate_keyframes(self, beat_matches: List[Dict],
                          music_analysis: Dict) -> List[Dict[str, Any]]:
        """
        生成关键帧和变速效果

        Args:
            beat_matches: 节拍匹配结果
            music_analysis: 音乐分析

        Returns:
            关键帧列表
        """
        keyframes = []

        for match in beat_matches:
            start_time = match['start_time']
            end_time = match['end_time']
            speed_factor = match['speed_factor']

            # 生成关键帧
            # 入点关键帧
            keyframes.append({
                'time': float(start_time),
                'type': 'in',
                'speed': 1.0,
                'easing': 'ease-in',
                'clip_path': match['clip_path']
            })

            # 中间关键帧（变速）
            mid_time = (start_time + end_time) / 2
            keyframes.append({
                'time': float(mid_time),
                'type': 'mid',
                'speed': float(speed_factor),
                'easing': 'linear',
                'clip_path': match['clip_path']
            })

            # 出点关键帧
            keyframes.append({
                'time': float(end_time),
                'type': 'out',
                'speed': 1.0,
                'easing': 'ease-out',
                'clip_path': match['clip_path']
            })

        self.logger.info(f"✅ 生成了{len(keyframes)}个关键帧")
        return keyframes

    def generate_timeline(self, beat_matches: List[Dict],
                         keyframes: List[Dict]) -> List[Dict[str, Any]]:
        """
        生成最终时间轴

        Args:
            beat_matches: 节拍匹配
            keyframes: 关键帧

        Returns:
            时间轴
        """
        timeline = []

        for i, match in enumerate(beat_matches):
            timeline.append({
                'index': i,
                'clip_path': match['clip_path'],
                'start_time': match['start_time'],
                'end_time': match['end_time'],
                'duration': match['duration'],
                'speed_factor': match['speed_factor'],
                'transition': 'cut' if i == 0 else 'fade',
                'transition_duration': 0.1,
                'effects': {
                    'speed_ramping': True,
                    'beat_sync': True
                }
            })

        return timeline

    def _detect_strong_beats(self, onset_env: np.ndarray, beats: np.ndarray) -> np.ndarray:
        """检测强拍"""
        if len(beats) == 0:
            return np.array([])

        # 计算每个节拍的强度
        beat_strengths = onset_env[beats]

        # 选择强度高于平均值+标准差的节拍
        threshold = np.mean(beat_strengths) + np.std(beat_strengths)
        strong_beats = beats[beat_strengths > threshold]

        return strong_beats

    def _detect_music_sections(self, y: np.ndarray, sr: int,
                              beat_times: np.ndarray) -> List[Dict[str, Any]]:
        """检测音乐分段"""
        # 简化版：基于能量变化检测
        rms = self.librosa.feature.rms(y=y)[0]
        if rms is None or len(rms) == 0:
            return []

        # 找到能量变化点
        rms_diff = np.diff(rms)
        if rms_diff is None or len(rms_diff) == 0:
            return []
        threshold = np.std(rms_diff) * 2

        change_points = np.where(np.abs(rms_diff) > threshold)[0]
        change_times = self.librosa.frames_to_time(change_points, sr=sr)

        sections = []
        prev_time = 0
        global_mean = float(np.mean(rms)) if len(rms) else 0.0

        for i, time in enumerate(change_times):
            start_idx = int(prev_time * sr / 512)
            end_idx = int(time * sr / 512)
            if end_idx <= start_idx:
                continue
            window = rms[start_idx:end_idx]
            if window is None or len(window) == 0:
                continue
            avg_energy = float(np.mean(window))

            section_type = 'high' if (global_mean > 0 and avg_energy > global_mean) else 'low'

            sections.append({
                'start': float(prev_time),
                'end': float(time),
                'type': section_type,
                'energy': float(avg_energy)
            })

            prev_time = time

        return sections

    def _calculate_motion_intensity(self, frames: List[np.ndarray]) -> float:
        """计算运动强度"""
        if len(frames) < 2:
            return 0.5

        motion_scores = []
        for i in range(len(frames) - 1):
            diff = self.cv2.absdiff(frames[i], frames[i + 1])
            motion_scores.append(np.mean(diff))

        # 归一化到0-1
        avg_motion = np.mean(motion_scores)
        return min(1.0, avg_motion / 50.0)

    def _calculate_brightness(self, frames: List[np.ndarray]) -> float:
        """计算平均亮度"""
        brightness_scores = []
        for frame in frames:
            gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            brightness_scores.append(np.mean(gray))

        # 归一化到0-1
        return np.mean(brightness_scores) / 255.0

    def _calculate_color_richness(self, frames: List[np.ndarray]) -> float:
        """计算色彩丰富度"""
        saturation_scores = []
        for frame in frames:
            hsv = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2HSV)
            saturation_scores.append(np.mean(hsv[:, :, 1]))

        # 归一化到0-1
        return np.mean(saturation_scores) / 255.0

    def _classify_scene(self, motion: float, brightness: float, color: float) -> str:
        """场景分类"""
        if motion > 0.7:
            return 'action'
        elif motion < 0.3:
            return 'calm'
        elif brightness > 0.7 and color > 0.6:
            return 'vibrant'
        elif brightness < 0.3:
            return 'dark'
        else:
            return 'neutral'

    def _select_best_clip(self, clips: List[Dict], used_clips: List[str],
                         style: str, target_duration: float,
                         beat_time: float) -> Optional[Dict]:
        """选择最佳片段"""
        if isinstance(used_clips, dict):
            eligible = []
            for candidate in clips:
                clip_path = str(candidate.get('path') or '')
                window = self._first_free_source_window(
                    clip_path, float(candidate.get('duration') or 0), target_duration, used_clips
                )
                if window:
                    eligible.append((candidate, window))
            if not eligible:
                return None
            if style == 'dynamic':
                chosen, window = max(eligible, key=lambda entry: entry[0].get('motion_intensity', 0))
            elif style == 'calm':
                chosen, window = min(eligible, key=lambda entry: entry[0].get('motion_intensity', 1))
            elif style == 'exciting':
                chosen, window = max(eligible, key=lambda entry: (
                    entry[0].get('motion_intensity', 0) + entry[0].get('color_richness', 0)
                ) / 2)
            else:
                chosen, window = eligible[0]
            result = dict(chosen)
            result['_source_window'] = window
            return result
        available_clips = [
            c for c in clips
            if c['path'] not in used_clips and float(c.get('duration') or 0.0) >= target_duration
        ]
        if not available_clips:
            raise RuntimeError(
                '没有未使用且足够长的素材覆盖当前 %.3fs 卡点区间；拒绝以定格、重复或极低速补足' %
                target_duration
            )

        # 根据风格选择
        if style == 'dynamic':
            # 选择运动强度高的
            return max(available_clips, key=lambda x: x.get('motion_intensity', 0))
        elif style == 'calm':
            # 选择运动强度低的
            return min(available_clips, key=lambda x: x.get('motion_intensity', 1))
        elif style == 'exciting':
            # 选择色彩丰富、运动强度高的
            return max(available_clips, key=lambda x: (
                x.get('motion_intensity', 0) + x.get('color_richness', 0)
            ) / 2)
        else:
            # 随机选择
            return np.random.choice(available_clips)


# 单例模式
_beat_remix_engine_instance = None


def get_beat_remix_engine():
    """获取混剪引擎单例"""
    global _beat_remix_engine_instance
    if _beat_remix_engine_instance is None:
        _beat_remix_engine_instance = BeatRemixEngine()
    return _beat_remix_engine_instance
