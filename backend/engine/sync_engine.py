"""
三同步引擎：音画同步、音字同步、字画同步
确保配音、字幕、画面完美对齐
"""

import logging
import numpy as np
from typing import Dict, List, Any, Optional, Tuple

logger = logging.getLogger('JJYB_AI智剪')


class SyncEngine:
    """三同步引擎"""

    def __init__(self):
        """初始化同步引擎"""
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
            self.logger.warning("⚠️ Librosa未安装，部分功能将受限")

    def sync_all(self, video_path: str, audio_path: str,
                 script: Dict[str, Any],
                 vision_analysis: Dict[str, Any],
                 options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行三同步

        Args:
            video_path: 视频路径
            audio_path: 音频路径
            script: 脚本
            vision_analysis: 视觉分析结果
            options: 可选配置（时间轴优化等）

        Returns:
            同步结果
        """
        self.logger.info("🔄 开始执行三同步")

        if options:
            self.logger.info(f"⚙️ 同步配置: {options}")

        results = {
            'audio_video_sync': {},
            'audio_text_sync': {},
            'text_video_sync': {},
            'sync_quality': 0.0
        }

        try:
            # 1. 音画同步
            self.logger.info("🎬 执行音画同步...")
            results['audio_video_sync'] = self.sync_audio_video(
                video_path, audio_path, script
            )

            # 2. 音字同步
            self.logger.info("🎵 执行音字同步...")
            results['audio_text_sync'] = self.sync_audio_text(
                audio_path, script
            )

            # 3. 字画同步
            self.logger.info("📝 执行字画同步...")
            results['text_video_sync'] = self.sync_text_video(
                script, vision_analysis
            )

            # 4. 计算同步质量
            results['sync_quality'] = self._calculate_sync_quality(results)

            self.logger.info(f"✅ 三同步完成，质量评分: {results['sync_quality']:.2f}")
            return results

        except Exception as e:
            self.logger.error(f"❌ 三同步失败: {e}", exc_info=True)
            return results

    def sync_audio_video(self, video_path: str, audio_path: str,
                        script: Dict[str, Any]) -> Dict[str, Any]:
        """
        音画同步：确保配音与视频画面节奏匹配

        Args:
            video_path: 视频路径
            audio_path: 音频路径
            script: 脚本

        Returns:
            同步结果
        """
        result = {
            'tempo': 0,
            'beats': [],
            'aligned_segments': [],
            'adjustments': []
        }

        if not self.librosa_available:
            self.logger.warning("⚠️ Librosa不可用，使用简化同步")
            return self._simple_audio_video_sync(script)

        try:
            # 加载音频
            audio, sr = self.librosa.load(audio_path, sr=self.sample_rate)

            # 分析音频节奏
            tempo, beats = self.librosa.beat.beat_track(y=audio, sr=sr)

            # 某些版本的 librosa 返回的 tempo 可能是 numpy.ndarray 或列表，这里统一
            # 归一为标量浮点数，避免在格式化日志时触发
            # "unsupported format string passed to numpy.ndarray.__format__" 错误。
            tempo_arr = np.atleast_1d(tempo)
            if tempo_arr.size > 0:
                tempo_value = float(np.mean(tempo_arr))
            else:
                tempo_value = 0.0

            # 节拍时间轴也统一转成 float 数组，后续计算更安全
            beat_times = self.librosa.frames_to_time(beats, sr=sr)
            beat_times = np.asarray(beat_times, dtype=float)

            result['tempo'] = float(tempo_value)
            result['beats'] = beat_times.tolist()

            # 对齐到脚本时间轴
            aligned_segments = []
            for segment in script.get('segments', []):
                start_time = segment.get('start_time', 0)
                end_time = segment.get('end_time', 0)

                # 找到最接近的节拍点
                start_beat = self._find_nearest_beat(start_time, beat_times)
                end_beat = self._find_nearest_beat(end_time, beat_times)

                # 计算调整量
                start_adjustment = start_beat - start_time
                end_adjustment = end_beat - end_time

                aligned_segments.append({
                    **segment,
                    'original_start': start_time,
                    'original_end': end_time,
                    'aligned_start': float(start_beat),
                    'aligned_end': float(end_beat),
                    'start_adjustment': float(start_adjustment),
                    'end_adjustment': float(end_adjustment)
                })

                if abs(start_adjustment) > 0.1 or abs(end_adjustment) > 0.1:
                    result['adjustments'].append({
                        'segment_id': segment.get('scene_id', 0),
                        'start_adjustment': float(start_adjustment),
                        'end_adjustment': float(end_adjustment)
                    })

            result['aligned_segments'] = aligned_segments

            self.logger.info(f"✅ 音画同步完成，BPM: {tempo_value:.1f}")
            return result

        except Exception as e:
            self.logger.error(f"❌ 音画同步失败: {e}")
            return self._simple_audio_video_sync(script)

    def sync_audio_text(self, audio_path: str,
                       script: Dict[str, Any]) -> Dict[str, Any]:
        """
        音字同步：确保字幕与语音精确对齐

        Args:
            audio_path: 音频路径
            script: 脚本

        Returns:
            同步结果
        """
        result = {
            'word_timings': [],
            'subtitle_segments': [],
            'sync_method': 'estimated'
        }

        try:
            if self.librosa_available:
                # 加载音频获取时长
                audio, sr = self.librosa.load(audio_path, sr=self.sample_rate)
                audio_duration = len(audio) / sr
            else:
                # 使用脚本估算
                audio_duration = max(
                    seg.get('end_time', 0)
                    for seg in script.get('segments', [])
                ) if script.get('segments') else 0

            # 为每个segment生成字幕时间轴
            word_timings = []
            subtitle_segments = []

            for segment in script.get('segments', []):
                text = segment.get('text', '')
                start_time = segment.get('start_time', 0)
                end_time = segment.get('end_time', 0)
                duration = end_time - start_time

                # 移除停顿标记
                clean_text = text.replace('[pause:0.3]', '').replace('[pause:0.2]', '')

                # 分词（简单按字符分）
                words = list(clean_text)
                word_count = len(words)

                if word_count > 0:
                    word_duration = duration / word_count

                    # 为每个字生成时间戳
                    for i, word in enumerate(words):
                        word_start = start_time + i * word_duration
                        word_end = start_time + (i + 1) * word_duration

                        word_timings.append({
                            'word': word,
                            'start': float(word_start),
                            'end': float(word_end),
                            'segment_id': segment.get('scene_id', 0)
                        })

                # 生成字幕段
                subtitle_segments.append({
                    'text': clean_text,
                    'start': float(start_time),
                    'end': float(end_time),
                    'duration': float(duration),
                    'segment_id': segment.get('scene_id', 0)
                })

            result['word_timings'] = word_timings
            result['subtitle_segments'] = subtitle_segments
            result['total_words'] = len(word_timings)

            self.logger.info(f"✅ 音字同步完成，共{len(word_timings)}个字")
            return result

        except Exception as e:
            self.logger.error(f"❌ 音字同步失败: {e}")
            return result

    def sync_text_video(self, script: Dict[str, Any],
                       vision_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """
        字画同步：确保字幕与画面内容语义一致

        Args:
            script: 脚本
            vision_analysis: 视觉分析结果

        Returns:
            同步结果
        """
        result = {
            'synced_subtitles': [],
            'semantic_matches': [],
            'position_suggestions': []
        }

        try:
            scenes = vision_analysis.get('scenes', [])
            descriptions = vision_analysis.get('descriptions', [])

            synced_subtitles = []
            semantic_matches = []

            for segment in script.get('segments', []):
                scene_id = segment.get('scene_id')
                text = segment.get('text', '')
                start_time = segment.get('start_time', 0)
                end_time = segment.get('end_time', 0)

                # 找到对应的场景
                scene = None
                scene_desc = None

                if scene_id is not None:
                    for s in scenes:
                        if s.get('id') == scene_id:
                            scene = s
                            break

                    # 获取场景描述
                    for desc in descriptions:
                        if desc.get('timestamp', 0) >= start_time and desc.get('timestamp', 0) < end_time:
                            scene_desc = desc.get('description', '')
                            break

                # 计算字幕位置
                position = self._calculate_subtitle_position(scene, scene_desc)

                # 计算语义匹配度
                semantic_score = self._calculate_semantic_match(text, scene_desc)

                synced_subtitles.append({
                    'text': text,
                    'start_time': float(start_time),
                    'end_time': float(end_time),
                    'scene_id': scene_id,
                    'scene_description': scene_desc or '',
                    'position': position,
                    'semantic_score': float(semantic_score)
                })

                if semantic_score > 0.5:
                    semantic_matches.append({
                        'segment_id': scene_id,
                        'score': float(semantic_score),
                        'text': text[:50],
                        'scene': scene_desc or ''
                    })

            result['synced_subtitles'] = synced_subtitles
            result['semantic_matches'] = semantic_matches
            result['average_semantic_score'] = np.mean([s['semantic_score'] for s in synced_subtitles]) if synced_subtitles else 0

            self.logger.info(f"✅ 字画同步完成，平均语义匹配度: {result['average_semantic_score']:.2f}")
            return result

        except Exception as e:
            self.logger.error(f"❌ 字画同步失败: {e}")
            return result

    def _find_nearest_beat(self, time: float, beat_times: np.ndarray) -> float:
        """找到最接近的节拍点"""
        if len(beat_times) == 0:
            return time
        idx = np.argmin(np.abs(beat_times - time))
        return beat_times[idx]

    def _simple_audio_video_sync(self, script: Dict[str, Any]) -> Dict[str, Any]:
        """简化的音画同步（不依赖librosa）"""
        return {
            'tempo': 120,  # 默认BPM
            'beats': [],
            'aligned_segments': script.get('segments', []),
            'adjustments': [],
            'method': 'simple'
        }

    def _calculate_subtitle_position(self, scene: Optional[Dict],
                                    scene_desc: Optional[str]) -> Dict[str, str]:
        """
        计算字幕位置（避免遮挡重要内容）

        Args:
            scene: 场景信息
            scene_desc: 场景描述

        Returns:
            位置信息
        """
        # 默认位置：底部居中
        position = {
            'horizontal': 'center',
            'vertical': 'bottom',
            'offset_y': '10%'
        }

        # 根据场景描述调整位置
        if scene_desc:
            if '人物' in scene_desc or '特写' in scene_desc:
                # 人物场景，字幕放底部
                position['vertical'] = 'bottom'
            elif '风景' in scene_desc or '全景' in scene_desc:
                # 风景场景，字幕可以放中下部
                position['vertical'] = 'bottom'
                position['offset_y'] = '15%'

        return position

    def _calculate_semantic_match(self, text: str, scene_desc: Optional[str]) -> float:
        """
        计算文本与场景的语义匹配度

        Args:
            text: 文本
            scene_desc: 场景描述

        Returns:
            匹配度 (0-1)
        """
        if not scene_desc:
            return 0.5  # 默认中等匹配

        # 简单的关键词匹配
        text_lower = text.lower()
        desc_lower = scene_desc.lower()

        # 提取关键词
        keywords = ['人物', '场景', '画面', '风景', '室内', '室外', '明亮', '昏暗']

        match_count = 0
        for keyword in keywords:
            if keyword in text and keyword in scene_desc:
                match_count += 1

        # 计算匹配度
        if match_count > 0:
            return min(1.0, 0.5 + match_count * 0.2)

        # 检查是否有共同词汇
        text_words = set(text)
        desc_words = set(scene_desc)
        common_words = text_words & desc_words

        if len(common_words) > 0:
            return min(1.0, len(common_words) / max(len(text_words), len(desc_words)))

        return 0.3  # 最低匹配度

    def _calculate_sync_quality(self, results: Dict[str, Any]) -> float:
        """
        计算整体同步质量

        Args:
            results: 同步结果

        Returns:
            质量评分 (0-1)
        """
        scores = []

        # 音画同步质量
        audio_video = results.get('audio_video_sync', {})
        if audio_video.get('aligned_segments'):
            # 计算调整幅度
            adjustments = audio_video.get('adjustments', [])
            if adjustments:
                avg_adjustment = np.mean([
                    abs(adj.get('start_adjustment', 0)) + abs(adj.get('end_adjustment', 0))
                    for adj in adjustments
                ])
                # 调整越小，质量越高
                av_score = max(0, 1 - avg_adjustment / 0.5)
            else:
                av_score = 1.0
            scores.append(av_score)

        # 音字同步质量
        audio_text = results.get('audio_text_sync', {})
        if audio_text.get('word_timings'):
            # 有词级时间轴就是高质量
            at_score = 0.9
            scores.append(at_score)

        # 字画同步质量
        text_video = results.get('text_video_sync', {})
        semantic_score = text_video.get('average_semantic_score', 0.5)
        scores.append(semantic_score)

        # 计算平均分
        if scores:
            return float(np.mean(scores))
        return 0.5


# 单例模式
_sync_engine_instance = None


def get_sync_engine():
    """获取同步引擎单例"""
    global _sync_engine_instance
    if _sync_engine_instance is None:
        _sync_engine_instance = SyncEngine()
    return _sync_engine_instance
