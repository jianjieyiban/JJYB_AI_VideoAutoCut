# -*- coding: utf-8 -*-
"""
Remix Service
混剪模式服务 - 完整实现
批量处理、智能识别、多种风格
"""

import logging
import hashlib
import math
import re
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    import cv2
except ImportError:
    cv2 = None

from backend.config.paths import PROJECT_ROOT
from backend.engine.video_processor import VideoProcessor
from backend.utils.intro_outro_detector import (
    compute_effective_ranges,
    clamp_clip_to_range,
)
from backend.utils.frame_dedup import dedup_with_refill

logger = logging.getLogger(__name__)


class RemixService:
    """混剪模式服务 - 完整实现"""

    DURATION_TOLERANCE_SECONDS = 0.35

    @classmethod
    def _effective_ranges_for(cls, video_paths: List) -> Dict[str, dict]:
        """计算素材有效区间（片头片尾剔除），失败时返回空 dict 不阻塞流程。"""
        try:
            paths = [str(p) for p in (video_paths or []) if p]
            return compute_effective_ranges(paths)
        except Exception as exc:
            logger.warning('片头片尾检测失败，跳过该保护策略: %s', exc)
            return {}

    @staticmethod
    def _clamp_shots_to_ranges(shots: List[Dict], ranges: Dict[str, dict]) -> List[Dict]:
        """把智能镜头夹紧到有效区间，剔除完全落在片头/片尾保护带内的镜头。"""
        if not ranges or not shots:
            return shots
        kept: List[Dict] = []
        for shot in shots:
            source = str(shot.get('source_video') or shot.get('video_path') or '')
            effective = ranges.get(source)
            if not effective:
                kept.append(shot)
                continue
            clamped = clamp_clip_to_range(shot, effective)
            if clamped is None:
                logger.info(
                    '片头片尾过滤: 剔除镜头 %.2f-%.2f (%s)',
                    float(shot.get('start_time') or 0), float(shot.get('end_time') or 0), source,
                )
                continue
            kept.append(clamped)
        return kept

    @staticmethod
    def _require_target_duration(target_duration: object) -> float:
        try:
            value = float(target_duration)
        except (TypeError, ValueError):
            raise ValueError('必须显式提供大于 0 的 target_duration_seconds')
        if not math.isfinite(value) or value <= 0:
            raise ValueError('target_duration_seconds 必须为大于 0 的有限数值')
        return value

    @classmethod
    def _duration_status(cls, target_duration: float, actual_duration: float) -> Dict:
        delta = round(float(actual_duration) - float(target_duration), 3)
        within = abs(delta) <= cls.DURATION_TOLERANCE_SECONDS
        return {
            'target_duration_seconds': round(float(target_duration), 3),
            'actual_duration_seconds': round(float(actual_duration), 3),
            'duration_delta_seconds': delta,
            'duration_tolerance_seconds': cls.DURATION_TOLERANCE_SECONDS,
            'duration_within_tolerance': within,
            'duration_status': 'completed' if within else 'partial',
        }

    def _get_render_duration_status(self, output_path: str, target_duration: float) -> Dict:
        info = self.video_processor.get_video_info(str(output_path)) or {}
        actual = float(info.get('duration') or 0)
        if actual <= 0:
            raise RuntimeError('无法读取成片实际时长，拒绝将目标时长标记为达标')
        return self._duration_status(target_duration, actual)

    @staticmethod
    def _safe_float(value: object, default: float = 0.0) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if math.isfinite(parsed) else default

    def _normalize_remix_candidate(self, item: Dict, fallback_path: str = '', source_index: int = 0) -> Optional[Dict]:
        if not isinstance(item, dict):
            return None
        source = item.get('video_path') or item.get('source_video') or item.get('source_video_path') or item.get('path') or fallback_path
        if not source:
            return None
        start = self._safe_float(item.get('start_time', item.get('start', item.get('source_start', 0.0))))
        end_default = start + self._safe_float(item.get('duration'), 0.0)
        end = self._safe_float(item.get('end_time', item.get('end', item.get('source_end', end_default))), end_default)
        if end <= start:
            return None
        clip = dict(item)
        clip.update({
            'video_path': str(source),
            'source_video': str(source),
            'source_video_path': str(source),
            'start_time': round(start, 3),
            'end_time': round(end, 3),
            'duration': round(end - start, 3),
            'score': self._safe_float(item.get('score', item.get('shot_score', item.get('cloud_vision_score', 50.0) / 100.0)), 0.5),
            'source_index': int(item.get('source_index', source_index) or 0),
            'description': item.get('description') or item.get('scene_type') or item.get('type') or '智能镜头片段',
        })
        return clip

    @staticmethod
    def _resolve_video_path(video_path: object) -> Path:
        raw = str(video_path or '').strip().replace('\\', '/')
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        try:
            return path.resolve()
        except OSError:
            return path.absolute()

    @classmethod
    def _dedupe_video_paths(cls, video_paths: object) -> List[str]:
        unique: List[str] = []
        seen = set()
        for raw_path in video_paths if isinstance(video_paths, list) else []:
            if not str(raw_path or '').strip():
                continue
            resolved = cls._resolve_video_path(raw_path)
            key = str(resolved).replace('\\', '/').lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append(str(raw_path).strip())
        return unique

    def _select_coverage_remix_clips(self, candidates: List[Dict], target_duration: float, style: str = 'dynamic') -> List[Dict]:
        normalized = [c for c in (self._normalize_remix_candidate(item) for item in candidates) if c]
        if not normalized:
            return []
        total_available = sum(float(c.get('duration') or 0) for c in normalized)
        if total_available + 0.08 < target_duration:
            raise RuntimeError('可用智能镜头总时长 %.3fs，少于目标 %.3fs，拒绝重复、定格或从开头硬截补足' % (total_available, target_duration))

        style_config = self._get_style_config(style)
        avg_clip_duration = max(1.0, sum(style_config.get('clip_duration', (3, 5))) / 2.0)
        desired_count = max(1, min(len(normalized), int(math.ceil(target_duration / avg_clip_duration)) + 2))

        by_source: Dict[str, List[Dict]] = {}
        for clip in normalized:
            by_source.setdefault(str(clip.get('video_path')), []).append(clip)
        for items in by_source.values():
            items.sort(key=lambda c: float(c.get('start_time') or 0))

        source_spans = {
            source: max(float(c.get('end_time') or 0) for c in items) - min(float(c.get('start_time') or 0) for c in items)
            for source, items in by_source.items() if items
        }
        total_span = sum(max(0.001, span) for span in source_spans.values()) or float(len(by_source))
        selected: List[Dict] = []
        used_keys = set()

        def clip_key(clip: Dict):
            return (clip.get('video_path'), round(float(clip.get('start_time') or 0), 3), round(float(clip.get('end_time') or 0), 3))

        for source, items in sorted(by_source.items(), key=lambda pair: min(float(c.get('start_time') or 0) for c in pair[1])):
            span = max(0.001, source_spans.get(source, 0.001))
            bucket_count = max(1, int(round(desired_count * span / total_span)))
            start_min = min(float(c.get('start_time') or 0) for c in items)
            end_max = max(float(c.get('end_time') or 0) for c in items)
            for bucket in range(bucket_count):
                left = start_min + (end_max - start_min) * bucket / bucket_count
                right = start_min + (end_max - start_min) * (bucket + 1) / bucket_count
                bucket_items = [c for c in items if clip_key(c) not in used_keys and float(c.get('start_time') or 0) < right and float(c.get('end_time') or 0) > left]
                if not bucket_items:
                    continue
                best = max(bucket_items, key=lambda c: (float(c.get('score') or 0.5), float(c.get('duration') or 0)))
                selected.append(best)
                used_keys.add(clip_key(best))

        if len(selected) < desired_count:
            for clip in sorted(normalized, key=lambda c: (float(c.get('score') or 0.5), float(c.get('duration') or 0)), reverse=True):
                key = clip_key(clip)
                if key in used_keys:
                    continue
                selected.append(clip)
                used_keys.add(key)
                if len(selected) >= desired_count:
                    break

        if sum(float(c.get('duration') or 0) for c in selected) + 0.08 < target_duration:
            for clip in sorted(normalized, key=lambda c: (float(c.get('score') or 0.5), float(c.get('duration') or 0)), reverse=True):
                key = clip_key(clip)
                if key in used_keys:
                    continue
                selected.append(clip)
                used_keys.add(key)
                if sum(float(c.get('duration') or 0) for c in selected) + 0.08 >= target_duration:
                    break

        selected.sort(key=lambda c: (float(c.get('start_time') or 0) / max(0.001, max(float(x.get('end_time') or 0) for x in by_source.get(str(c.get('video_path')), [c]))), int(c.get('source_index') or 0), float(c.get('score') or 0.5)))

        # 内容去重：相似画面保留高分者并从候选池补位（保持已排定的叙事顺序）。
        try:
            selected, dropped_unfilled = dedup_with_refill(selected, normalized)
            if dropped_unfilled:
                logger.info('混剪去重: %d 个重复片段无替补被移除', dropped_unfilled)
        except Exception as exc:
            logger.warning('片段去重失败（忽略，继续时间线规划）: %s', exc)

        planned: List[Dict] = []
        remaining = float(target_duration)
        for idx, clip in enumerate(selected):
            if remaining <= 0.001:
                break
            duration = float(clip.get('duration') or 0)
            if duration <= 0:
                continue
            remaining_slots = max(1, len(selected) - idx)
            budget = remaining / remaining_slots
            # Do not let short early shots consume the equal-share budget and
            # leave an impossible tail for the last shot.  The lower bound
            # reserves every later candidate's real capacity, so a target that
            # the selected, non-reused shots can cover is always covered.
            later_capacity = sum(
                max(0.0, float(item.get('duration') or 0))
                for item in selected[idx + 1:]
            )
            required_here = max(0.0, remaining - later_capacity)
            use_duration = min(
                duration,
                remaining if remaining_slots == 1 else max(0.12, budget, required_here),
            )
            if use_duration < 0.12 and planned:
                planned[-1]['end_time'] = round(float(planned[-1]['end_time']) + use_duration, 3)
                planned[-1]['duration'] = round(float(planned[-1]['duration']) + use_duration, 3)
                remaining = 0.0
                break
            out = dict(clip)
            out['start_time'] = float(clip['start_time'])
            out['end_time'] = round(float(clip['start_time']) + use_duration, 3)
            out['duration'] = round(use_duration, 3)
            out['selection_strategy'] = 'coverage_highlight'
            planned.append(out)
            remaining -= use_duration

        if remaining > 0.08:
            raise RuntimeError('覆盖式镜头规划后仍缺少 %.3fs，拒绝重复或开头硬截补足' % remaining)
        if planned:
            actual_total = sum(float(item.get('duration') or 0) for item in planned)
            delta = round(actual_total - float(target_duration), 6)
            if abs(delta) > 0.000001:
                last = planned[-1]
                last['duration'] = round(float(last.get('duration') or 0) - delta, 3)
                last['end_time'] = round(float(last.get('start_time') or 0) + float(last['duration']), 3)
        return planned

    @staticmethod
    def _coalesce_beat_points(beat_points: List[float], target_duration: float, min_visual_duration: float) -> List[float]:
        """Merge overly dense beats into edit-safe visual intervals.

        A beat detector can return boundaries every few frames.  Treating each
        boundary as a compulsory cut creates flicker and makes a finite shot
        pool appear exhausted.  This keeps the first/last boundary exact while
        retaining only boundaries that leave a visible shot on both sides.
        """
        target = float(target_duration)
        minimum = max(0.12, float(min_visual_duration))
        result = [0.0]
        for raw in sorted({float(point) for point in beat_points if 0.0 < float(point) < target}):
            if raw - result[-1] >= minimum:
                result.append(round(raw, 3))
        if target - result[-1] < minimum and len(result) > 1:
            result.pop()
        result.append(round(target, 3))
        return result

    @staticmethod
    def _allocate_beat_source_windows(shots: List[Dict], beat_points: List[float], sections: List[Dict],
                                      slow_motion_at_climax: bool) -> List[Dict]:
        """Allocate source windows without reusing a source frame.

        A shot is a semantic boundary, not a one-use token: a long shot may
        safely supply several adjacent beat intervals as long as the source
        windows do not overlap.
        """
        ranked = sorted(shots, key=lambda item: float(item.get('score') or 0), reverse=True)
        source_reservations: Dict[str, List[tuple]] = {}
        previous_id = None
        allocations: List[Dict] = []

        def source_key(shot: Dict) -> str:
            return str(shot.get('source_video') or shot.get('source_video_path') or shot.get('video_path') or shot.get('id'))

        def first_free_window(shot: Dict, required: float) -> Optional[tuple]:
            source = source_key(shot)
            candidate_start = float(shot.get('start_time') or 0)
            candidate_end = float(shot.get('end_time') or candidate_start)
            for reserved_start, reserved_end in sorted(source_reservations.get(source, [])):
                if reserved_end <= candidate_start:
                    continue
                if reserved_start - candidate_start + 1e-6 >= required:
                    return candidate_start, candidate_start + required
                candidate_start = max(candidate_start, reserved_end)
                if candidate_start + required > candidate_end + 1e-6:
                    return None
            if candidate_start + required <= candidate_end + 1e-6:
                return candidate_start, candidate_start + required
            return None

        for index, beat_time in enumerate(beat_points[:-1]):
            final_duration = float(beat_points[index + 1] - beat_time)
            in_climax = any(
                section.get('type') == 'high'
                and float(section.get('start', 0)) <= beat_time < float(section.get('end', 0))
                for section in sections
            )
            speed = 0.7 if slow_motion_at_climax and in_climax else 1.0
            required_source_duration = final_duration * speed

            eligible = []
            for shot in ranked:
                window = first_free_window(shot, required_source_duration)
                if window:
                    eligible.append((shot, window[0], window[1]))
            if not eligible:
                available = sum(
                    max(0.0, float(shot.get('end_time') or 0) - float(shot.get('start_time') or 0))
                    for shot in ranked
                )
                raise RuntimeError(
                    '第%s个卡点区间需要 %.3fs 的未重复镜头窗口，但剩余真实镜头容量只有 %.3fs；'
                    '已拒绝重复画面、定格和开头硬截补足' % (index + 1, required_source_duration, available)
                )

            # Prefer a different visual when possible, then the best scored
            # candidate.  Falling back to the previous shot remains valid only
            # for a later, non-overlapping source window.
            alternatives = [entry for entry in eligible if str(entry[0].get('id')) != previous_id]
            shot, source_start, source_end = (alternatives or eligible)[0]
            shot_id = str(shot.get('id'))
            source_reservations.setdefault(source_key(shot), []).append((source_start, source_end))
            previous_id = shot_id
            allocations.append({
                'shot': shot,
                'source_start': round(source_start, 3),
                'source_end': round(source_end, 3),
                'final_duration': round(final_duration, 3),
                'speed_factor': round(speed, 3),
                'in_climax': in_climax,
            })
        return allocations

    def __init__(self, db_manager, socketio, task_service):
        """
        初始化混剪模式服务

        Args:
            db_manager: 数据库管理器
            socketio: SocketIO实例
            task_service: 任务服务
        """
        self.db_manager = db_manager
        self.socketio = socketio
        self.task_service = task_service
        # 视频处理引擎，用于获取基础信息（时长/分辨率等）
        self.video_processor = VideoProcessor()
        logger.info('✅ 混剪模式服务初始化完成')

    def create_remix_project(self, data: Dict) -> Dict:
        """
        创建混剪项目

        Args:
            data: 项目数据
                - name: 项目名称
                - video_paths: 视频路径列表
                - style: 混剪风格
                - duration: 目标时长

        Returns:
            项目信息
        """
        try:
            logger.info('🎬 创建混剪项目...')

            # 创建项目
            project = self.db_manager.create_project(
                name=data.get('name', '混剪项目'),
                project_type='remix',
                description='混剪模式项目',
                template='remix'
            )

            project_id = project['id']

            # 添加视频素材
            raw_video_paths = data.get('video_paths', []) if isinstance(data.get('video_paths'), list) else []
            video_names = data.get('video_names') if isinstance(data.get('video_names'), list) else []
            name_by_path = {}
            for index, raw_path in enumerate(raw_video_paths):
                key = str(self._resolve_video_path(raw_path)).replace('\\', '/').lower()
                requested = str(video_names[index] if index < len(video_names) else '').strip()
                if key and requested and key not in name_by_path:
                    name_by_path[key] = Path(requested).name
            video_paths = self._dedupe_video_paths(raw_video_paths)
            for i, video_path in enumerate(video_paths):
                resolved_path = self._resolve_video_path(video_path)
                exists = resolved_path.is_file()
                file_size = resolved_path.stat().st_size if exists else 0
                info = self.video_processor.get_video_info(str(resolved_path)) if exists else {}
                duration = self._safe_float(info.get('duration'), 0.0)
                path_key = str(resolved_path).replace('\\', '/').lower()
                material_name = name_by_path.get(path_key) or resolved_path.name or f'素材视频{i + 1}'
                self.db_manager.create_material(
                    project_id=project_id,
                    material_type='video',
                    name=material_name,
                    path=video_path,
                    size=file_size,
                    duration=duration,
                    metadata={
                        'index': i,
                        'exists': exists,
                        'absolute_path': str(resolved_path),
                        'width': info.get('width', 0),
                        'height': info.get('height', 0),
                        'fps': info.get('fps', 0),
                        'codec': info.get('codec', ''),
                        'has_audio': bool(info.get('has_audio', False)),
                    }
                )

            # 保存配置
            config = {
                'style': data.get('style', 'dynamic'),  # dynamic/calm/exciting
                'duration_mode': data.get('duration_mode'),
                'target_duration_seconds': data.get('target_duration_seconds'),
                'target_duration': data.get('target_duration_seconds'),
                'transition': data.get('transition', 'auto'),
                'music_style': data.get('music_style', 'auto'),
                'auto_highlight': data.get('auto_highlight', True),
                'auto_bgm': data.get('auto_bgm', True),
                'scene_segmentation': data.get('scene_segmentation', 'smart_shot'),
                'smart_shot_split': bool(data.get('smart_shot_split', True)),
                'vision_model': data.get('vision_model', 'custom_vision'),
            }

            self.db_manager.update_project(project_id, {'config': config})

            logger.info(f'✅ 混剪项目创建成功: {project_id}')

            return {
                'project_id': project_id,
                'project': project,
                'config': config,
                'material_count': len(video_paths)
            }

        except Exception as e:
            logger.error(f'❗ 创建混剪项目失败: {e}', exc_info=True)
            raise

    def batch_analyze_videos(
        self,
        video_paths: List[str],
        scene_segmentation: str = 'smart_shot',
        smart_shot_split: bool = True,
        vision_model: str = None,
    ) -> List[Dict]:
        """批量分析视频；默认逐帧分割镜头并将每个镜头视为独立候选片段。"""
        video_paths = self._dedupe_video_paths(video_paths)
        logger.info(f'🔍 批量分析视频: {len(video_paths)}个，场景模式: {scene_segmentation}')
        results: List[Dict] = []
        use_smart_shots = smart_shot_split and scene_segmentation == 'smart_shot'
        for idx, video_path in enumerate(video_paths):
            try:
                analysis = self._analyze_local_video(
                    video_path,
                    scene_segmentation=scene_segmentation,
                    smart_shot_split=use_smart_shots,
                    video_idx=idx,
                )
                if vision_model and analysis.get('highlights'):
                    self._enhance_highlights_with_cloud_vision(analysis, vision_model)
                results.append(analysis)
            except Exception as exc:
                logger.warning(f'⚠️ 本地视频分析失败: {video_path}: {exc}')
                results.append({
                    'path': video_path,
                    'duration': 0.0,
                    'resolution': 'unknown',
                    'fps': 0.0,
                    'quality_score': None,
                    'highlights': [],
                    'scenes': [],
                    'analysis_source': 'local_opencv',
                    'analysis_status': 'failed',
                    'analysis_error': str(exc)
                })
        logger.info(f'✅ 视频分析完成: {len(results)}个')
        return results

    def _enhance_highlights_with_cloud_vision(self, analysis: Dict, vision_model: str) -> None:
        """用云视觉补充得分最高的智能镜头描述；失败时保留本地候选。"""
        candidates = [
            item for item in analysis.get('highlights', [])
            if item.get('type') == 'smart_shot'
        ]
        for item in candidates:
            item['cloud_vision_used'] = False
        if not candidates:
            return

        try:
            from backend.engine.multi_model_adapter import get_multi_model_manager
            multi_model = get_multi_model_manager()
        except Exception as exc:
            self._record_cloud_vision_error(candidates, exc)
            return

        prompt = (
            '分析这张混剪候选镜头代表帧。仅返回两行：'
            'SCORE:0-100（镜头作为精彩混剪片段的可信评分）和 '
            'DESC:简短中文画面描述（不超过80字）。'
        )
        video_path = analysis.get('path')
        for highlight in sorted(candidates, key=self._local_highlight_score, reverse=True)[:6]:
            image_path = None
            try:
                image_path = self._extract_highlight_representative_frame(video_path, highlight)
                response = multi_model.analyze_image(
                    str(image_path), prompt, model_type=vision_model
                )
                description, cloud_score = self._parse_cloud_vision_response(response)
                if description:
                    highlight['description'] = description
                if cloud_score is not None:
                    local_score = float(highlight.get('score') or 0.0)
                    highlight['score'] = round((local_score + cloud_score / 100.0) / 2.0, 4)
                    highlight['cloud_vision_score'] = cloud_score
                highlight['cloud_vision_used'] = True
            except Exception as exc:
                highlight['cloud_vision_error'] = self._safe_cloud_vision_error(exc)
                logger.warning('云视觉增强混剪候选失败: %s', highlight['cloud_vision_error'])
            finally:
                if image_path:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception:
                        pass

    def _extract_highlight_representative_frame(self, video_path: str, highlight: Dict) -> Path:
        """从候选镜头范围内提取实际可解码的代表帧到临时 JPEG。"""
        if cv2 is None:
            raise RuntimeError('未安装 OpenCV，无法提取候选镜头代表帧')
        path_obj = Path(video_path)
        if not path_obj.is_absolute():
            path_obj = PROJECT_ROOT / path_obj
        capture = cv2.VideoCapture(str(path_obj))
        if not capture.isOpened():
            raise RuntimeError('无法打开候选镜头源视频')
        try:
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            if frame_count <= 0 or fps <= 0:
                raise RuntimeError('候选镜头源视频元数据无效')
            start_frame = max(0, int(float(highlight.get('start_time', 0.0)) * fps))
            end_frame = min(frame_count - 1, max(start_frame, int(float(highlight.get('end_time', 0.0)) * fps) - 1))
            requested_frame = highlight.get('representative_frame')
            try:
                frame_number = int(requested_frame)
            except (TypeError, ValueError):
                frame_number = (start_frame + end_frame) // 2
            if frame_number < start_frame or frame_number > end_frame:
                frame_number = (start_frame + end_frame) // 2
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise RuntimeError('无法读取候选镜头代表帧')
            temp_dir = PROJECT_ROOT / 'output' / 'tmp'
            temp_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                suffix='.jpg', prefix='remix_vision_', dir=str(temp_dir), delete=False
            ) as temp_file:
                image_path = Path(temp_file.name)
            if not cv2.imwrite(str(image_path), frame):
                image_path.unlink(missing_ok=True)
                raise RuntimeError('无法写入候选镜头临时帧')
            return image_path
        finally:
            capture.release()

    @staticmethod
    def _local_highlight_score(highlight: Dict) -> float:
        try:
            return float(highlight.get('score') or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _parse_cloud_vision_response(response) -> tuple:
        text = str(response or '').strip()
        score_match = re.search(r'SCORE\s*:\s*(100|[1-9]?\d)(?:\.\d+)?', text, re.IGNORECASE)
        desc_match = re.search(r'DESC\s*:\s*(.+)', text, re.IGNORECASE | re.DOTALL)
        description = desc_match.group(1).strip() if desc_match else text
        score = float(score_match.group(1)) if score_match else None
        return description[:500], score

    @staticmethod
    def _safe_cloud_vision_error(exc: Exception) -> str:
        return f'{exc.__class__.__name__}: 云视觉增强失败'[:200]

    def _record_cloud_vision_error(self, highlights: List[Dict], exc: Exception) -> None:
        error = self._safe_cloud_vision_error(exc)
        for highlight in highlights:
            highlight['cloud_vision_used'] = False
            highlight['cloud_vision_error'] = error
        logger.warning('云视觉服务不可用，保留本地混剪候选: %s', error)

    def _analyze_local_video(
        self,
        video_path: str,
        scene_segmentation: str = 'smart_shot',
        smart_shot_split: bool = True,
        video_idx: int = 0,
    ) -> Dict:
        """从实际解码帧计算画质、运动与场景变化，并按所选模式生成镜头候选片段。"""
        if cv2 is None:
            raise RuntimeError('未安装 OpenCV，无法进行本地自动高光分析')

        path_obj = Path(video_path)
        if not path_obj.is_absolute():
            path_obj = PROJECT_ROOT / video_path
        if not path_obj.exists():
            raise FileNotFoundError(f'视频文件不存在: {path_obj}')

        capture = cv2.VideoCapture(str(path_obj))
        if not capture.isOpened():
            raise RuntimeError(f'无法解码视频: {path_obj}')
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            if fps <= 0 or width <= 0 or height <= 0:
                raise RuntimeError('视频元数据无效，无法可靠分析')

            sample_step = max(1, frame_count // 120) if frame_count else max(1, int(fps))
            samples: List[Dict] = []
            previous_gray = None
            frame_index = 0
            while len(samples) < 120:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % sample_step:
                    frame_index += 1
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gray = cv2.resize(gray, (160, max(1, int(gray.shape[0] * 160 / gray.shape[1]))))
                brightness = float(gray.mean())
                contrast = float(gray.std())
                sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                motion = 0.0
                scene_change = 0.0
                if previous_gray is not None:
                    difference = float(cv2.absdiff(gray, previous_gray).mean())
                    motion = min(1.0, difference / 40.0)
                    scene_change = min(1.0, difference / 60.0)
                visual_quality = (
                    min(1.0, sharpness / 500.0) * 0.45
                    + max(0.0, 1.0 - abs(brightness - 128.0) / 128.0) * 0.30
                    + min(1.0, contrast / 64.0) * 0.25
                )
                samples.append({
                    'time': frame_index / fps,
                    'sharpness': sharpness,
                    'brightness': brightness,
                    'contrast': contrast,
                    'motion': motion,
                    'scene_change': scene_change,
                    'visual_quality': visual_quality,
                    'highlight_score': visual_quality * 0.35 + motion * 0.35 + scene_change * 0.30
                })
                previous_gray = gray
                frame_index += 1

            if len(samples) < 8:
                raise RuntimeError(f'仅解码到 {len(samples)} 个有效采样帧，少于本地分析所需的 8 个')

            duration = frame_count / fps if frame_count > 0 else samples[-1]['time']
            quality_score = sum(item['visual_quality'] for item in samples) / len(samples)
            scene_changes = [item for item in samples if item['scene_change'] >= 0.35]

            # 智能镜头分割：逐帧识别镜头边界，每个镜头作为独立候选片段参与后续筛选排序
            smart_shots: List[Dict] = []
            if smart_shot_split:
                smart_shots = self._detect_smart_shots_remix(str(path_obj), fps, frame_count, video_idx=video_idx)
                highlights = self._highlights_from_smart_shots(smart_shots, samples, duration, str(path_obj))
            else:
                highlights = self._select_highlight_peaks(samples, duration)

            result = {
                'path': video_path,
                'duration': round(duration, 3),
                'resolution': f'{width}x{height}',
                'fps': fps,
                'quality_score': round(quality_score, 4),
                'highlights': highlights,
                'scenes': [
                    {'time': round(item['time'], 2), 'scene_change': round(item['scene_change'], 4)}
                    for item in scene_changes
                ],
                'analysis_source': 'local_opencv',
                'analysis_status': 'completed',
                'analysis_metadata': {
                    'sample_count': len(samples),
                    'factors': ['sharpness', 'brightness', 'contrast', 'motion', 'scene_change'],
                    'audio_analysis': 'not_used',
                    'scene_segmentation': scene_segmentation,
                    'smart_shot_split': smart_shot_split,
                    'shot_count': len(smart_shots),
                }
            }
            if smart_shots:
                result['smart_shots'] = smart_shots
            return result
        finally:
            capture.release()

    def _detect_smart_shots_remix(
        self,
        video_path: str,
        fps: float,
        total_frames: int,
        video_idx: int = 0,
    ) -> List[Dict]:
        """逐帧联合特征识别镜头切点，返回可直接作为混剪片段的镜头列表。

        优先复用项目内 SmartShotSegmenter（TransNetV2/OpenCV 双模式）；
        若加载失败则退回内置的亮度+直方图+边缘联合评分检测。

        Args:
            video_path: 视频文件路径
            fps: 视频帧率
            total_frames: 总帧数
            video_idx: 视频在批处理中的索引，用于生成全局唯一 shot.id
        """
        shots: List[Dict] = []
        try:
            from backend.engine.smart_shot_segmenter import SmartShotSegmenter
            segmenter = SmartShotSegmenter(threshold=0.5, use_transnetv2=True)
            shots = segmenter.detect_shots(video_path)
            if shots:
                for index, shot in enumerate(shots):
                    # 生成全局唯一 id，避免多视频合并后 id 重复导致音乐卡点散列失效
                    shot['id'] = f"{video_idx}_{index}"
                    shot.setdefault('type', 'smart_shot')
                    shot['source_video'] = video_path
                logger.info(f'✅ 智能镜头分割完成（SmartShotSegmenter）: {video_path} -> {len(shots)} 个镜头')
                return shots
        except Exception as exc:
            logger.warning(f'⚠️ SmartShotSegmenter 不可用，退回内置检测: {exc}')

        # 退回内置逐帧检测：亮度 + 颜色直方图 + 边缘联合评分
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return []
        try:
            min_shot_frames = max(6, int(fps * 0.28))
            cuts = [0]
            prev_gray = None
            prev_hist = None
            last_cut = 0
            frame_num = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                small_gray = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
                hist = cv2.calcHist(
                    [frame], [0, 1, 2], None, [8, 8, 8],
                    [0, 256, 0, 256, 0, 256],
                )
                hist = cv2.normalize(hist, hist).flatten()
                if prev_gray is not None:
                    luma_delta = float(cv2.absdiff(prev_gray, small_gray).mean()) / 255.0
                    hist_distance = 1.0 - max(-1.0, min(1.0, cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)))
                    edges = cv2.Canny(small_gray, 80, 160)
                    prev_edges = cv2.Canny(prev_gray, 80, 160)
                    edge_delta = float(cv2.absdiff(prev_edges, edges).mean()) / 255.0
                    cut_score = 0.50 * luma_delta + 0.38 * hist_distance + 0.12 * edge_delta
                    if cut_score >= 0.30 and frame_num - last_cut >= min_shot_frames:
                        cuts.append(frame_num)
                        last_cut = frame_num
                prev_gray = small_gray
                prev_hist = hist
                frame_num += 1
            if frame_num <= 0:
                return []
            if cuts[-1] != frame_num:
                cuts.append(frame_num)
            shots = []
            for index, (start_frame, end_frame) in enumerate(zip(cuts, cuts[1:])):
                if end_frame <= start_frame:
                    continue
                shots.append({
                    'id': f"{video_idx}_{index}",
                    'type': 'smart_shot',
                    'source_video': video_path,
                    'start_frame': start_frame,
                    'end_frame': end_frame - 1,
                    'start_time': round(start_frame / fps, 3),
                    'end_time': round(end_frame / fps, 3),
                    'duration': round((end_frame - start_frame) / fps, 3),
                    'representative_frame': start_frame + (end_frame - start_frame) // 2,
                })
            logger.info(f'✅ 智能镜头分割完成（内置检测）: {video_path} -> {len(shots)} 个镜头')
            return shots
        finally:
            cap.release()

    def _highlights_from_smart_shots(
        self,
        shots: List[Dict],
        samples: List[Dict],
        duration: float,
        video_path: str = '',
    ) -> List[Dict]:
        """把智能分割的镜头转为混剪高光候选片段；为每段补充画面评分。

        在原有采样帧评分基础上，加入代表帧运动强度作为加权因子（权重 0.15，
        原有评分权重相应降至 0.85）。若无法读取代表帧则保持原有评分逻辑。
        """
        if not shots:
            return []
        # 用采样帧的中位评分作为默认画面分，避免镜头内无采样帧时评分为 0
        default_score = 0.0
        if samples:
            default_score = sum(s.get('highlight_score', 0.0) for s in samples) / len(samples)

        highlights: List[Dict] = []
        for shot in shots:
            start = float(shot.get('start_time', 0.0))
            end = float(shot.get('end_time', start + float(shot.get('duration', 0.0) or 0.0)))
            if end <= start:
                continue
            # 取该镜头时间中点附近的采样帧评分（遍历所有 ±1.0s 范围内的采样帧取最高分）
            mid = (start + end) / 2.0
            best_score = default_score
            for s in samples:
                if abs(s.get('time', 0.0) - mid) < 1.0:
                    best_score = max(best_score, float(s.get('highlight_score', 0.0)))

            # 附加改进：读取代表帧与下一帧的差异作为运动强度，作为加权因子融合到评分
            rep_frame = shot.get('representative_frame')
            motion_intensity = None
            if rep_frame is not None and video_path:
                motion_intensity = self._compute_shot_motion_intensity(video_path, int(rep_frame))
            if motion_intensity is not None:
                # 运动量权重 0.15，原有评分权重降至 0.85
                final_score = best_score * 0.85 + motion_intensity * 0.15
            else:
                final_score = best_score

            highlights.append({
                'start_time': round(start, 2),
                'end_time': round(end, 2),
                'score': round(final_score, 4),
                'type': 'smart_shot',
                'description': '智能镜头分割片段（逐帧高精度，每镜头一张代表画面）',
                'analysis_source': 'local_opencv_smart_shot',
                'source_shot_id': shot.get('id'),
                'representative_frame': shot.get('representative_frame'),
            })
            if motion_intensity is not None:
                highlights[-1]['motion_intensity'] = round(motion_intensity, 4)
        return highlights

    def _compute_shot_motion_intensity(self, video_path: str, rep_frame: int) -> Optional[float]:
        """读取代表帧和下一帧的差异作为运动强度（0-1）。

        Args:
            video_path: 视频文件路径
            rep_frame: 代表帧的帧号

        Returns:
            归一化运动强度（0-1）；若无法读取则返回 None。
        """
        if cv2 is None or not video_path:
            return None
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return None
        try:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames <= 0:
                return None
            frame_idx = max(0, min(total_frames - 2, int(rep_frame)))
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok1, f1 = cap.read()
            ok2, f2 = cap.read()
            if not ok1 or not ok2 or f1 is None or f2 is None:
                return None
            g1 = cv2.cvtColor(f1, cv2.COLOR_BGR2GRAY)
            g2 = cv2.cvtColor(f2, cv2.COLOR_BGR2GRAY)
            diff = float(cv2.absdiff(g1, g2).mean()) / 255.0
            # 归一化：0.4 的均值差异视为运动强度满值 1.0
            return min(1.0, diff / 0.4)
        except Exception as exc:
            logger.debug('计算镜头运动强度失败: %s', exc)
            return None
        finally:
            cap.release()

    def _select_highlight_peaks(self, samples: List[Dict], duration: float) -> List[Dict]:
        """只在从实际样本中检测到的局部峰值附近生成片段。"""
        if duration <= 0:
            return []
        scores = [item['highlight_score'] for item in samples]
        mean_score = sum(scores) / len(scores)
        variance = sum((score - mean_score) ** 2 for score in scores) / len(scores)
        threshold = mean_score + math.sqrt(variance) * 0.35
        candidates = []
        for index in range(1, len(samples) - 1):
            current = samples[index]
            if (current['highlight_score'] >= threshold
                    and current['highlight_score'] >= samples[index - 1]['highlight_score']
                    and current['highlight_score'] >= samples[index + 1]['highlight_score']):
                candidates.append(current)

        highlights: List[Dict] = []
        for peak in sorted(candidates, key=lambda item: item['highlight_score'], reverse=True):
            start = max(0.0, peak['time'] - 2.0)
            end = min(duration, peak['time'] + 2.0)
            if end - start < 1.0 or any(start < item['end_time'] and end > item['start_time'] for item in highlights):
                continue
            highlights.append({
                'start_time': round(start, 2),
                'end_time': round(end, 2),
                'score': round(peak['highlight_score'], 4),
                'type': 'visual_peak',
                'description': '基于本地画面质量、运动和场景变化的峰值片段',
                'analysis_source': 'local_opencv',
                'factors': {
                    'sharpness': round(peak['sharpness'], 3),
                    'brightness': round(peak['brightness'], 3),
                    'contrast': round(peak['contrast'], 3),
                    'motion': round(peak['motion'], 4),
                    'scene_change': round(peak['scene_change'], 4)
                }
            })
            if len(highlights) >= 6:
                break
        return sorted(highlights, key=lambda item: item['start_time'])

    def detect_highlights(self, video_path: str) -> List[Dict]:
        """识别有本地帧分析证据支持的高光片段。"""
        logger.info(f'⭐ 识别本地视频高光: {video_path}')
        return self._analyze_local_video(video_path)['highlights']

    def create_remix_plan(self, analyses: List[Dict], config: Dict) -> Dict:
        """
        创建混剪方案

        Args:
            analyses: 视频分析结果
            config: 混剪配置

        Returns:
            混剪方案
        """
        try:
            logger.info('📋 创建混剪方案...')

            target_duration = self._require_target_duration(
                config.get('target_duration_seconds', config.get('target_duration'))
            )

            style = config.get('style', 'dynamic')
            auto_highlight = bool(config.get('auto_highlight', True))
            preferred_highlights = config.get('preferred_highlights') or []
            preferred_by_video: Dict[str, List[Dict]] = {}
            for highlight in preferred_highlights:
                if not isinstance(highlight, dict):
                    continue
                video_path = str(highlight.get('video_path') or highlight.get('source_video') or '')
                if video_path:
                    preferred_by_video.setdefault(video_path, []).append(highlight)

            # 显式提供的 highlights 原样使用；只有请求自动高光时才补做本地分析。
            clips: List[Dict] = []
            total_duration: float = 0.0
            candidate_clips: List[Dict] = []
            analysis_failures: List[str] = []
            preferred_matched = False
            # 片头片尾有效区间：所有高光候选必须落在有效区间内
            effective_ranges = self._effective_ranges_for(
                [str(a.get('path')) for a in analyses if a.get('path')]
            )

            for analysis in analyses:
                highlights = analysis.get('highlights') or []
                analysis_path = str(analysis.get('path') or '')
                selected_highlights = preferred_by_video.get(analysis_path, [])
                if not selected_highlights and analysis_path:
                    # 多视频场景下做路径模糊匹配（后缀匹配），按 (video_path, start, end) 三元组关联
                    for pref_path, pref_items in preferred_by_video.items():
                        if not pref_path:
                            continue
                        if (pref_path == analysis_path
                                or pref_path.endswith(analysis_path)
                                or analysis_path.endswith(pref_path)):
                            selected_highlights = pref_items
                            break
                if not selected_highlights and preferred_highlights and len(analyses) == 1:
                    selected_highlights = preferred_highlights
                if selected_highlights:
                    preferred_matched = True
                    highlights = selected_highlights
                elif not highlights and auto_highlight:
                    if analysis.get('analysis_status') == 'failed':
                        analysis_failures.append(
                            f"{analysis.get('path')}: {analysis.get('analysis_error', '本地分析失败')}"
                        )
                        continue
                    try:
                        highlights = self.detect_highlights(analysis.get('path'))
                        analysis['highlights'] = highlights
                    except Exception as he:
                        analysis_failures.append(f"{analysis.get('path')}: {he}")
                        continue

                for highlight in highlights:

                    try:
                        start = float(highlight.get('start_time', highlight.get('start', 0.0)))
                        end = float(highlight.get('end_time', highlight.get('end', 0.0)))
                    except Exception:
                        continue

                    # 片头片尾保护：落在保护带内的高光直接剔除，跨界高光夹紧
                    clamped = clamp_clip_to_range(
                        {'video_path': analysis_path, 'start_time': start, 'end_time': end},
                        effective_ranges.get(analysis_path),
                    )
                    if clamped is None:
                        continue
                    start, end = float(clamped['start_time']), float(clamped['end_time'])
                    clip_duration = end - start
                    if clip_duration <= 0:
                        continue

                    candidate_clips.append({
                        'video_path': analysis.get('path'),
                        'start_time': start,
                        'end_time': end,
                        'duration': clip_duration,
                        'type': highlight.get('type'),
                        'score': highlight.get('score'),
                        'description': highlight.get('description'),
                        'analysis_source': highlight.get('analysis_source', analysis.get('analysis_source')),
                        'source_index': int(analysis.get('source_index', 0) or 0),
                        'factors': highlight.get('factors'),
                        'cloud_vision_used': bool(highlight.get('cloud_vision_used', False)),
                        'cloud_vision_score': highlight.get('cloud_vision_score'),
                        'cloud_vision_error': highlight.get('cloud_vision_error'),
                    })
                    total_duration += clip_duration

            if candidate_clips:
                clips = self._select_coverage_remix_clips(candidate_clips, target_duration, style)
                total_duration = sum(float(clip.get('duration') or 0) for clip in clips)

            if auto_highlight and not clips:
                detail = '; '.join(analysis_failures) or '本地分析未检测到具有足够证据的高光峰值'
                raise RuntimeError(f'自动高光分析未生成可用片段，已停止混剪而非回退到基础合并: {detail}')

            if preferred_highlights and not preferred_matched:
                logger.warning(
                    'preferred_highlights 在多视频场景下未匹配到任何视频（按 (video_path, start, end) 三元组），已忽略并不阻塞流程'
                )

            if clips and abs(total_duration - target_duration) > 0.08:
                raise RuntimeError('覆盖式高光规划未精确达到目标时长：%.3fs / %.3fs' % (total_duration, target_duration))

            plan = {
                'clips': clips,
                'total_clips': len(clips),
                'total_duration': total_duration,
                'style': style,
                'preferred_highlights_applied': bool(preferred_highlights),
                'vision_model': config.get('vision_model'),
                'transitions': self._generate_transitions(len(clips)),
                'bgm_segments': self._generate_bgm_plan(total_duration)
            }

            logger.info(f'✅ 混剪方案创建完成: {len(clips)}个片段, 总时长{total_duration}秒')

            return plan

        except Exception as e:
            logger.error(f'❗ 创建混剪方案失败: {e}', exc_info=True)
            raise

    def process_remix(self, project_id: str, plan: Dict) -> str:
        """
        执行混剪处理

        Args:
            project_id: 项目ID
            plan: 混剪方案

        Returns:
            任务ID
        """
        try:
            logger.info(f'🎬 开始执行混剪: {project_id}')

            # 仅当调用方请求自动高光且未显式提供 clips 时，才进行本地高光分析。
            video_paths = list((plan or {}).get('video_paths') or [])
            mode = (plan.get('mode') or plan.get('remix_mode') or 'general').lower()
            has_clips = bool((plan or {}).get('clips'))
            auto_highlight = bool((plan or {}).get('auto_highlight', mode != 'music'))
            # 已提交的智能分割结果直接转为 clips，避免主任务再次进行场景检测。
            segment_data = (plan or {}).get('segment_data')
            if isinstance(segment_data, dict) and not has_clips:
                shots = segment_data.get('shots') or segment_data.get('all_shots') or []
                if isinstance(shots, list):
                    segment_clips = []
                    for shot in shots:
                        if not isinstance(shot, dict):
                            continue
                        try:
                            start = float(shot.get('start_time', shot.get('start', 0.0)))
                            end = float(shot.get('end_time', shot.get('end', start + float(shot.get('duration', 0.0)))) )
                        except (TypeError, ValueError):
                            continue
                        source = shot.get('source_video') or shot.get('video_path')
                        if source and end > start:
                            segment_clips.append({
                                'video_path': str(source), 'source_video': str(source),
                                'start_time': start, 'end_time': end, 'duration': end - start,
                                'type': shot.get('type', 'smart_shot'),
                                'score': shot.get('score'), 'scene_type': shot.get('scene_type'),
                                'description': shot.get('description') or shot.get('scene_type') or '智能镜头片段',
                                'source_index': shot.get('source_index', 0),
                            })
                    if segment_clips:
                        target_for_segments = self._require_target_duration(plan.get('target_duration_seconds', plan.get('target_duration')))
                        plan['clips'] = self._select_coverage_remix_clips(
                            segment_clips, target_for_segments, plan.get('style', 'dynamic')
                        )
                        has_clips = True
                        logger.info('✅ 复用智能分割镜头池生成覆盖式混剪片段: %s -> %s', len(segment_clips), len(plan['clips']))
            if video_paths and not has_clips and auto_highlight:
                scene_segmentation = plan.get('scene_segmentation', 'smart_shot')
                smart_shot_split = bool(plan.get('smart_shot_split', True))
                analyses = self.batch_analyze_videos(
                    video_paths,
                    scene_segmentation=scene_segmentation,
                    smart_shot_split=smart_shot_split,
                    vision_model=plan.get('vision_model'),
                )
                cfg = {
                    'target_duration_seconds': plan.get('target_duration_seconds', plan.get('target_duration')),
                    'style': plan.get('style', 'dynamic'),
                    'auto_highlight': True,
                    # 用户在高级功能中确认的高光优先构成实际剪辑方案。
                    'preferred_highlights': plan.get('preferred_highlights') or [],
                    # 视觉模型：若后续启用云视觉增强，按此选择调用
                    'vision_model': plan.get('vision_model', 'custom_vision'),
                }
                remix_plan = self.create_remix_plan(analyses, cfg)
                if not remix_plan.get('clips'):
                    raise RuntimeError('自动高光分析未生成可用片段，混剪任务未创建')
                for key, value in remix_plan.items():
                    plan.setdefault(key, value)
                logger.info('✅ 已根据本地分析结果自动生成混剪方案（clips）')

            # 创建任务
            task_id = self.task_service.create_remix_task(
                project_id=project_id,
                plan=plan
            )

            logger.info(f'✅ 混剪任务已创建: {task_id}')

            return task_id

        except Exception as e:
            logger.error(f'❗ 执行混剪失败: {e}', exc_info=True)
            raise

    def apply_style(self, clips: List[Dict], style: str) -> List[Dict]:
        """
        应用混剪风格

        Args:
            clips: 视频片段列表
            style: 风格类型

        Returns:
            应用风格后的片段
        """
        try:
            logger.info(f'🎨 应用混剪风格: {style}')

            config = self._get_style_config(style)

            for clip in clips:
                clip['style_config'] = config

            logger.info(f'✅ 风格应用完成')

            return clips

        except Exception as e:
            logger.error(f'❗ 应用风格失败: {e}', exc_info=True)
            raise

    def _get_style_config(self, style: str) -> Dict:
        """根据风格名返回风格配置（clip_duration/transition_duration/speed）。

        dynamic: 节奏明快；calm: 沉稳舒缓；exciting: 激烈快切。未知风格回退为 dynamic。
        """
        style_configs = {
            'dynamic': {
                'clip_duration': (3, 5),
                'transition_duration': 0.5,
                'speed': 1.2
            },
            'calm': {
                'clip_duration': (5, 8),
                'transition_duration': 1.0,
                'speed': 1.0
            },
            'exciting': {
                'clip_duration': (2, 4),
                'transition_duration': 0.3,
                'speed': 1.5
            }
        }
        return style_configs.get(style, style_configs['dynamic'])

    def _generate_transitions(self, clip_count: int) -> List[str]:
        """生成转场效果列表"""
        transitions = ['fade', 'dissolve', 'wipe', 'slide']
        return [transitions[i % len(transitions)] for i in range(clip_count - 1)]

    def _generate_bgm_plan(self, duration: float) -> List[Dict]:
        """生成背景音乐方案"""
        return [
            {
                'start_time': 0,
                'duration': duration,
                'music_type': 'auto',
                'volume': 0.3
            }
        ]

    # ================================================================== #
    # 升级能力 1：智能镜头分割（双模式通用前置步骤）
    # ================================================================== #
    def smart_segment_remix_shots(self,
                                  video_paths: List[str],
                                  threshold: float = 0.5,
                                  use_transnetv2: bool = True,
                                  max_shots_per_video: int = None,
                                  export_keyframes: bool = True,
                                  progress_callback: Optional[Callable[[float, str, Dict], None]] = None) -> Dict:
        """批量分割混剪素材，并汇总单素材阶段进度和可用关键帧。"""
        from backend.engine.smart_shot_segmenter import SmartShotSegmenter

        video_paths = self._dedupe_video_paths(video_paths)
        requested_video_count = len(video_paths)
        segmenter = SmartShotSegmenter(threshold=threshold, use_transnetv2=use_transnetv2)
        all_shots: List[Dict] = []
        per_video: List[Dict] = []
        skipped_videos: List[Dict] = []
        failures: List[Dict] = []

        def report(progress: float, message: str, detail: Dict) -> None:
            if progress_callback:
                progress_callback(max(0.0, min(100.0, progress)), message, detail)

        for index, video_path in enumerate(video_paths):
            video_number = index + 1
            path_obj = Path(video_path)
            if not path_obj.is_absolute():
                path_obj = PROJECT_ROOT / path_obj
            video_name = path_obj.name or str(video_path)
            base_progress = index / max(1, requested_video_count) * 100.0

            if not path_obj.exists():
                reason = f'视频文件不存在: {path_obj}'
                record = {'video_path': str(video_path), 'video_name': video_name, 'source_index': index, 'status': 'skipped', 'shot_count': 0, 'reason': reason}
                skipped_videos.append(record)
                per_video.append(record)
                report((index + 1) / max(1, requested_video_count) * 100.0,
                       f'已跳过第 {video_number}/{requested_video_count} 个素材：{video_name}（文件不存在）', record)
                continue

            def segment_progress(single_progress: float) -> None:
                single_progress = max(0.0, min(100.0, float(single_progress)))
                if single_progress < 70:
                    phase = '检测'
                else:
                    phase = '评分'
                report(base_progress + single_progress / max(1, requested_video_count),
                       f'正在分析第 {video_number}/{requested_video_count} 个素材：{video_name}（{phase}）',
                       {'video_path': str(path_obj), 'video_name': video_name, 'source_index': index, 'phase': phase})

            try:
                report(base_progress, f'正在分析第 {video_number}/{requested_video_count} 个素材：{video_name}（检测）',
                       {'video_path': str(path_obj), 'video_name': video_name, 'source_index': index, 'phase': '检测'})
                shots = segmenter.detect_shots(str(path_obj), progress_callback=segment_progress,
                                               max_shots=max_shots_per_video)
                for shot in shots:
                    shot['source_video'] = str(path_obj)
                    shot['source_index'] = index

                if export_keyframes and shots:
                    signature = hashlib.sha256(str(path_obj.resolve()).encode('utf-8')).hexdigest()[:8]
                    safe_stem = re.sub(r'[^\w.-]+', '_', path_obj.stem, flags=re.UNICODE).strip('._') or 'video'
                    output_dir = PROJECT_ROOT / 'output' / 'keyframes' / 'remix' / f'{safe_stem}_{signature}'
                    report(base_progress + 90.0 / max(1, requested_video_count),
                           f'正在分析第 {video_number}/{requested_video_count} 个素材：{video_name}（导出）',
                           {'video_path': str(path_obj), 'video_name': video_name, 'source_index': index, 'phase': '导出'})
                    segmenter.export_keyframes(str(path_obj), shots, output_dir=str(output_dir))

                all_shots.extend(shots)
                record = {'video_path': str(path_obj), 'video_name': video_name, 'source_index': index, 'status': 'completed',
                          'shot_count': len(shots), 'shots': shots}
                per_video.append(record)
                report((index + 1) / max(1, requested_video_count) * 100.0,
                       f'已完成第 {video_number}/{requested_video_count} 个素材：{video_name}（{len(shots)} 个镜头）', record)
            except Exception as exc:
                reason = str(exc) or '镜头分割失败'
                record = {'video_path': str(path_obj), 'video_name': video_name, 'source_index': index, 'status': 'failed', 'shot_count': 0, 'reason': reason}
                failures.append(record)
                per_video.append(record)
                logger.warning('混剪素材智能分割失败，继续处理其余素材: %s: %s', path_obj, reason)
                report((index + 1) / max(1, requested_video_count) * 100.0,
                       f'第 {video_number}/{requested_video_count} 个素材分析失败：{video_name}（已跳过）', record)

        processed_video_count = sum(1 for item in per_video if item['status'] == 'completed')
        if not processed_video_count:
            reasons = '；'.join(f"{item['video_name']}: {item['reason']}" for item in per_video) or '未找到可处理素材'
            raise RuntimeError(f'所有混剪素材智能镜头分割失败：{reasons}')

        logger.info('✅ 混剪智能镜头分割完成: 请求 %s 个，处理 %s 个，共 %s 个镜头',
                    requested_video_count, processed_video_count, len(all_shots))
        return {
            'requested_video_count': requested_video_count,
            'processed_video_count': processed_video_count,
            'skipped_videos': skipped_videos,
            'failures': failures,
            'per_video': per_video,
            'all_shots': all_shots,
            'total_shots': len(all_shots),
        }

    # ================================================================== #
    # 升级能力 2：普通模式混剪（高光 + 台词，一个画面一段配音）
    # ================================================================== #
    def general_mode_remix(self,
                           video_paths: List[str],
                           voices: List[Dict] = None,
                           target_duration: Optional[float] = None,
                           duration_mode: Optional[str] = None,
                           style: str = 'dynamic',
                           preferred_highlights: List[Dict] = None,
                           advanced_style: str = '',
                           dedup_plans: List[Dict] = None,
                           render: bool = True,
                           output_path: str = '') -> Dict:
        """
        普通模式混剪：根据视频高光和台词混剪，一个画面一段配音

        Args:
            video_paths: 视频路径列表
            voices: 配音段列表（可选，[{text, voice_path, duration}, ...]）
            target_duration: 目标时长
            style: 风格 dynamic/calm/exciting
            render: 是否渲染视频
            output_path: 指定输出路径

        Returns:
            dict: timeline + 输出视频路径
        """
        try:
            video_paths = self._dedupe_video_paths(video_paths)
            target_duration = self._require_target_duration(target_duration)
            from backend.engine.smart_shot_segmenter import SmartShotSegmenter
            from backend.engine.puppet_sync_engine import PuppetSyncEngine

            # 1. 智能分割镜头
            segmenter = SmartShotSegmenter(use_transnetv2=True)
            all_shots: List[Dict] = []
            global_shot_counter = 0
            effective_ranges = self._effective_ranges_for(video_paths)
            for video_idx, vp in enumerate(video_paths):
                v_path = Path(vp)
                if not v_path.is_absolute():
                    v_path = PROJECT_ROOT / vp
                if not v_path.exists():
                    continue
                shots = segmenter.detect_shots(str(v_path))
                shots = self._clamp_shots_to_ranges(shots, effective_ranges)
                for s in shots:
                    s['source_video'] = str(v_path)
                    # 生成全局唯一 id，避免多视频合并后 id 重复导致散列失效
                    s['id'] = f"{video_idx}_{global_shot_counter}"
                    global_shot_counter += 1
                all_shots.extend(shots)

            if not all_shots:
                raise RuntimeError('智能分割未得到任何镜头')

            # 2. 按评分筛选高光镜头；用户应用的高级高光优先。
            preferred_highlights = preferred_highlights or []
            if preferred_highlights:
                preferred_keys = {
                    (str(item.get('video_path', item.get('source_video', ''))), round(float(item.get('start', item.get('start_time', 0))), 3), round(float(item.get('end', item.get('end_time', 0))), 3))
                    for item in preferred_highlights
                }
                preferred_shots = [
                    shot for shot in all_shots
                    if any(
                        round(float(shot.get('start_time', 0)), 3) == start and round(float(shot.get('end_time', 0)), 3) == end
                        and (not source or str(shot.get('source_video', '')) == source)
                        for source, start, end in preferred_keys
                    )
                ]
                sorted_shots = preferred_shots or sorted(all_shots, key=lambda x: x.get('score', 0), reverse=True)
            else:
                sorted_shots = sorted(all_shots, key=lambda x: x.get('score', 0), reverse=True)
            # 风格配置：影响平均片段时长估算
            style_config = self._get_style_config(style)
            avg_clip_dur = sum(style_config['clip_duration']) / 2.0
            needed = int(target_duration / avg_clip_dur) + 2
            top_shots = sorted_shots[:max(needed, 10)]
            # 内容去重：相似画面只保留评分最高的一个，避免成片出现重复镜头
            try:
                from backend.utils.frame_dedup import dedup_clips
                top_shots, _dropped = dedup_clips(top_shots)
            except Exception as exc:
                logger.warning('镜头去重失败（忽略，继续拟人匹配）: %s', exc)
            # 按时间排序（每个视频内）
            top_shots.sort(key=lambda x: (x.get('source_video', ''), x.get('start_time', 0)))

            # 3. 若无配音，生成占位配音段（按镜头时长）
            if not voices:
                voices = []
                for i, s in enumerate(top_shots):
                    dur = float(s.get('duration', 3.0))
                    voices.append({
                        'index': i,
                        'text': f'第{i+1}段高光画面',
                        'voice_path': '',
                        'duration': dur,
                    })

            # 4. 拟人化匹配（允许复用，因为多视频镜头池较大）
            engine = PuppetSyncEngine()
            timeline = engine.match_shots_to_voices(top_shots, voices, allow_reuse=True)
            dedup_plans = dedup_plans or []
            dedup_by_range = {
                (round(float(item.get('start_time', item.get('start', 0))), 3),
                 round(float(item.get('end_time', item.get('end', 0))), 3)): item
                for item in dedup_plans if isinstance(item, dict) and item.get('has_transform', True)
            }
            for clip in timeline:
                clip['source_video_path'] = clip.get('source_video')
                clip['video_path'] = clip.get('source_video')
                key = (
                    round(float(clip.get('shot_start', clip.get('source_start', 0))), 3),
                    round(float(clip.get('shot_end', clip.get('source_end', 0))), 3)
                )
                plan = dedup_by_range.get(key)
                if plan:
                    clip['dedup_transform'] = plan

            # 风格只影响镜头候选和转场元数据；不能改变 PuppetSyncEngine
            # 已计算且将被实际渲染的 speed_factor/final_duration。
            style_config = self._get_style_config(style)
            for clip in timeline:
                clip['style_config'] = style_config
                clip['transition_duration'] = style_config['transition_duration']

            # 5. 时长约束：保持 PuppetSyncEngine 计算的音画策略，不缩放 final_duration/audio_duration。
            timeline_duration = sum(float(c.get('final_duration', 0) or 0) for c in timeline)
            duration_status = self._duration_status(target_duration, timeline_duration)
            duration_warnings = []
            if not duration_status['duration_within_tolerance']:
                raise RuntimeError(
                    '普通混剪时间轴未达到显式目标时长：实测 %.3fs，目标 %.3fs，误差 %.3fs' %
                    (timeline_duration, target_duration, duration_status['duration_delta_seconds'])
                )

            result = {
                'timeline': timeline,
                'clip_count': len(timeline),
                'mode': 'general',
                'style': style,
                'advanced_style': advanced_style,
                'preferred_highlights_applied': bool(preferred_highlights),
                'dedup_plans_applied': sum(1 for clip in timeline if clip.get('dedup_transform')),
                'total_shots_analyzed': len(all_shots),
                'duration_mode': duration_mode,
                **duration_status,
                'duration_warnings': duration_warnings,
            }

            # 5. 渲染：PuppetSyncEngine 会逐项使用 timeline 中的 source_video，
            # video_path 仅作为缺失来源字段时的兼容后备。
            if render and timeline and video_paths:
                fallback_path = video_paths[0]
                vp_path = Path(fallback_path)
                if not vp_path.is_absolute():
                    vp_path = PROJECT_ROOT / fallback_path
                try:
                    out = engine.render_timeline(
                        video_path=str(vp_path),
                        timeline=timeline,
                        output_path=output_path or None,
                    )
                    result.update(self._get_render_duration_status(out, target_duration))
                    if not result['duration_within_tolerance']:
                        result['duration_warnings'].append('渲染成片未达到目标时长容差，结果仅报告实测状态')
                    result['output_video'] = out
                    result['output_url'] = '/' + str(Path(out).relative_to(PROJECT_ROOT)).replace('\\', '/')
                except Exception as re:
                    logger.error(f'普通模式渲染失败: {re}', exc_info=True)
                    raise

            logger.info(f'✅ 普通模式混剪完成: {len(timeline)} 个片段')
            return result
        except Exception as e:
            logger.error(f'❗ 普通模式混剪失败: {e}', exc_info=True)
            raise

    # ================================================================== #
    # 升级能力 3：音乐卡点模式混剪（剪映智能卡点二风格）
    # ================================================================== #
    def music_beat_remix(self,
                         video_paths: List[str],
                         music_path: str,
                         target_duration: Optional[float] = None,
                         duration_mode: Optional[str] = None,
                         beat_density: str = 'dense',
                         slow_motion_at_climax: bool = True,
                         preferred_highlights: List[Dict] = None,
                         advanced_style: str = '',
                         style: str = 'dynamic',
                         dedup_plans: List[Dict] = None,
                         render: bool = True,
                         output_path: str = '') -> Dict:
        """
        音乐卡点模式：参考剪映智能卡点二
          1. 先给 BGM 密集卡点（提取所有节拍 + 强拍）
          2. 根据点位剪辑视频，一个卡点一个名场面/高光时刻
          3. 关键时刻（高潮段）适度慢放
          4. 先智能分割视频镜头再进行后续操作

        Args:
            video_paths: 视频路径列表
            music_path: BGM 音乐路径
            target_duration: 目标时长
            beat_density: 卡点密度 dense/medium/sparse
            slow_motion_at_climax: 高潮段是否慢放
            render: 是否渲染
            output_path: 指定输出路径

        Returns:
            dict: timeline + 输出视频路径
        """
        try:
            video_paths = self._dedupe_video_paths(video_paths)
            target_duration = self._require_target_duration(target_duration)
            from backend.engine.smart_shot_segmenter import SmartShotSegmenter
            from backend.engine.beat_remix_engine import get_beat_remix_engine

            # 1. 智能分割镜头
            segmenter = SmartShotSegmenter(use_transnetv2=True)
            all_shots: List[Dict] = []
            global_shot_counter = 0
            effective_ranges = self._effective_ranges_for(video_paths)
            for video_idx, vp in enumerate(video_paths):
                v_path = Path(vp)
                if not v_path.is_absolute():
                    v_path = PROJECT_ROOT / vp
                if not v_path.exists():
                    continue
                shots = segmenter.detect_shots(str(v_path))
                shots = self._clamp_shots_to_ranges(shots, effective_ranges)
                for s in shots:
                    s['source_video'] = str(v_path)
                    # 生成全局唯一 id，避免多视频合并后音乐卡点 last_id 散列失效
                    s['id'] = f"{video_idx}_{global_shot_counter}"
                    global_shot_counter += 1
                all_shots.extend(shots)

            if not all_shots:
                raise RuntimeError('智能分割未得到任何镜头')

            # 2. 分析 BGM 节拍
            m_path = Path(music_path)
            if not m_path.is_absolute():
                m_path = PROJECT_ROOT / music_path
            if not m_path.exists():
                raise FileNotFoundError(f'BGM 不存在: {m_path}')

            beat_engine = get_beat_remix_engine()
            music_analysis = beat_engine.analyze_music(str(m_path))

            beats_all = list(music_analysis.get('beats', []) or [])
            beats_strong = list(music_analysis.get('strong_beats', []) or [])
            sections = music_analysis.get('sections', []) or []

            # 3. 密集卡点选择（剪映智能卡点二风格：所有节拍都用上）
            density = (beat_density or 'dense').lower()
            if density == 'dense':
                # 密集：所有节拍都卡点
                beat_points = beats_all
            elif density == 'sparse':
                # 稀疏：只用强拍
                beat_points = beats_strong or beats_all[::2]
            else:
                # 中等：每两拍一个
                beat_points = beats_all[::2] if len(beats_all) > 1 else beats_all

            if len(beat_points) < 2:
                raise RuntimeError(f'BGM 节拍数过少（{len(beat_points)}），无法卡点')

            # 节拍区间必须显式覆盖 [0, target_duration]；不回退至目标之外的默认节拍。
            min_visual_duration = {'dense': 0.55, 'medium': 1.0, 'sparse': 1.6}.get(density, 0.8)
            beat_points = self._coalesce_beat_points(beat_points, target_duration, min_visual_duration)
            if len(beat_points) < 2:
                raise RuntimeError('目标区间内没有可用节拍，无法生成覆盖 0 到目标结束的卡点时间轴')

            # 4. 一个卡点一个镜头，按评分排序选高光；已应用高级高光时优先使用。
            sorted_shots = sorted(all_shots, key=lambda x: x.get('score', 0), reverse=True)
            preferred_highlights = preferred_highlights or []
            if preferred_highlights:
                preferred_keys = {
                    (str(item.get('video_path', item.get('source_video', ''))), round(float(item.get('start', item.get('start_time', 0))), 3), round(float(item.get('end', item.get('end_time', 0))), 3))
                    for item in preferred_highlights
                }
                preferred_shots = [
                    shot for shot in all_shots
                    if any(
                        round(float(shot.get('start_time', 0)), 3) == start and round(float(shot.get('end_time', 0)), 3) == end
                        and (not source or str(shot.get('source_video', '')) == source)
                        for source, start, end in preferred_keys
                    )
                ]
                if preferred_shots:
                    sorted_shots = preferred_shots
            # 每个卡点区间必须使用不同且足够长的镜头；素材不足时明确失败，绝不复用、定格或极低速填补。
            style_config = self._get_style_config(style)
            style_config = self._get_style_config(style)
            allocations = self._allocate_beat_source_windows(
                sorted_shots, beat_points, sections, slow_motion_at_climax
            )
            selected: List[Dict] = [allocation['shot'] for allocation in allocations]
            used_shot_ids = set()
            # Retained only as a legacy diagnostic reference; allocation is
            # now completed by the non-overlapping source-window planner.
            for i, beat_time in enumerate(()):
                seg_duration = float(beat_points[i + 1] - beat_time)
                in_climax = any(
                    sec.get('type') == 'high'
                    and float(sec.get('start', 0)) <= beat_time < float(sec.get('end', 0))
                    for sec in sections
                )
                # 仅高潮慢放改变播放速率；风格不通过变速既有素材来改变时长。
                speed = 0.7 if slow_motion_at_climax and in_climax else 1.0
                required_source_duration = seg_duration * speed
                shot = next(
                    (
                        candidate for candidate in sorted_shots
                        if candidate.get('id') not in used_shot_ids
                        and float(candidate.get('duration') or (
                            float(candidate.get('end_time', 0)) - float(candidate.get('start_time', 0))
                        )) >= required_source_duration
                    ),
                    None
                )
                if shot is None:
                    raise RuntimeError(
                        '第 %s 个卡点区间需要至少 %.3fs 的未使用镜头，但没有可用素材；'
                        '未使用定格、重复或极低速变速补足' %
                        (i + 1, required_source_duration)
                    )
                selected.append(shot)
                used_shot_ids.add(shot.get('id'))

            # 5. 构建时间轴：每段时长 = 相邻节拍间隔，高潮段慢放
            # 风格配置：影响非高潮段速度与转场时长
            timeline: List[Dict] = []
            for i, beat_time in enumerate(beat_points[:-1]):
                next_beat = beat_points[i + 1]
                seg_duration = float(next_beat - beat_time)
                if seg_duration < 0.1:
                    continue

                shot = selected[i] if i < len(selected) else selected[-1]
                shot_dur = float(shot.get('duration', 0))

                # 判断是否在高潮段
                in_climax = False
                for sec in sections:
                    if (sec.get('type') == 'high'
                            and float(sec.get('start', 0)) <= beat_time < float(sec.get('end', 0))):
                        in_climax = True
                        break

                # 仅高潮段明确慢放；其他段保持 1x，并据此构造与节拍严格一致的源窗口。
                speed = 0.7 if slow_motion_at_climax and in_climax else 1.0

                # 计算源截取
                if shot_dur > 0:
                    # 从镜头中截取 seg_duration * speed 秒的内容
                    src_use = seg_duration * speed
                    if shot_dur >= src_use:
                        # 截取中段
                        shot_start = float(shot.get('start_time', 0))
                        shot_end = float(shot.get('end_time', shot_start + shot_dur))
                        center = (shot_start + shot_end) / 2
                        half = src_use / 2
                        src_start = max(float(shot.get('start_time', 0)), center - half)
                        src_end = min(shot_end, src_start + src_use)
                        if src_end - src_start < src_use:
                            src_start = max(float(shot.get('start_time', 0)), src_end - src_use)
                        cut_strategy = 'slow_down' if speed < 1.0 else 'cut_highlight'
                    else:
                        raise RuntimeError(
                            '第 %s 个卡点区间选中的镜头时长 %.3fs 不足所需 %.3fs；拒绝通过低速、定格或重复素材填满节拍段' %
                            (i + 1, shot_dur, src_use)
                        )
                else:
                    src_start = 0
                    src_end = seg_duration
                    cut_strategy = 'direct'

                # Use the allocated source window rather than recentering the
                # same shot for every beat interval.
                allocation = allocations[i]
                shot = allocation['shot']
                src_start = allocation['source_start']
                src_end = allocation['source_end']
                speed = allocation['speed_factor']
                in_climax = allocation['in_climax']
                cut_strategy = 'slow_down' if speed < 1.0 else 'cut_highlight'
                timeline.append({
                    'shot_id': shot.get('id', i),
                    'source_video': shot.get('source_video', ''),
                    'source_video_path': shot.get('source_video', ''),
                    'video_path': shot.get('source_video', ''),
                    'beat_index': i,
                    'beat_time': round(float(beat_time), 3),
                    'final_duration': round(seg_duration, 3),
                    'audio_duration': round(seg_duration, 3),
                    'speed_factor': round(speed, 3),
                    'freeze_tail': False,
                    'cut_strategy': cut_strategy,
                    'source_start': round(src_start, 3),
                    'source_end': round(src_end, 3),
                    'shot_duration': round(shot_dur, 3),
                    'scene_type': shot.get('scene_type', 'neutral'),
                    'shot_score': shot.get('score', 0.5),
                    'in_climax': in_climax,
                    'subtitle_text': '',
                    'style_config': style_config,
                    'transition_duration': style_config['transition_duration'],
                })

            timeline_duration = sum(float(item.get('final_duration', 0) or 0) for item in timeline)
            from backend.engine.puppet_sync_engine import PuppetSyncEngine
            timeline = PuppetSyncEngine()._finalize_timeline(timeline)
            timeline_duration = sum(float(item.get('final_duration', 0) or 0) for item in timeline)
            duration_status = self._duration_status(target_duration, timeline_duration)
            if not duration_status['duration_within_tolerance']:
                raise RuntimeError(
                    '卡点时间轴未覆盖目标时长：实测 %.3fs，目标 %.3fs，误差 %.3fs' %
                    (timeline_duration, target_duration, duration_status['duration_delta_seconds'])
                )

            result = {
                'timeline': timeline,
                'clip_count': len(timeline),
                'mode': 'music',
                'beat_density': density,
                'beat_count': len(beat_points),
                'style': style,
                'advanced_style': advanced_style,
                'preferred_highlights_applied': bool(preferred_highlights),
                'music_analysis': {
                    'tempo': music_analysis.get('tempo', 120),
                    'total_beats': len(beats_all),
                    'strong_beats': len(beats_strong),
                    'sections': sections,
                },
                'total_shots_analyzed': len(all_shots),
                'duration_mode': duration_mode,
                **duration_status,
                'duration_warnings': [],
            }
            if render and timeline and video_paths:
                from backend.engine.puppet_sync_engine import PuppetSyncEngine
                fallback_path = video_paths[0]
                vp_path = Path(fallback_path)
                if not vp_path.is_absolute():
                    vp_path = PROJECT_ROOT / fallback_path
                try:
                    puppet = PuppetSyncEngine()
                    out = puppet.render_timeline(
                        video_path=str(vp_path),
                        timeline=timeline,
                        output_path=output_path or None,
                        bgm_path=str(m_path),
                    )
                    result.update(self._get_render_duration_status(out, target_duration))
                    if not result['duration_within_tolerance']:
                        raise RuntimeError(
                            '卡点渲染成片未达到目标时长容差：实测 %.3fs，目标 %.3fs，误差 %.3fs' %
                            (result['actual_duration_seconds'], target_duration, result['duration_delta_seconds'])
                        )
                    result['output_video'] = out
                    result['output_url'] = '/' + str(Path(out).relative_to(PROJECT_ROOT)).replace('\\', '/')
                except Exception as re:
                    logger.error(f'音乐卡点渲染失败: {re}', exc_info=True)
                    raise

            logger.info(f'✅ 音乐卡点混剪完成: {len(timeline)} 个片段, {len(beat_points)} 个卡点')
            return result
        except Exception as e:
            logger.error(f'❗ 音乐卡点混剪失败: {e}', exc_info=True)
            raise

    # ================================================================== #
    # 升级能力 4：导出剪映草稿
    # ================================================================== #
    def export_jianying_draft(self,
                              project_id: str,
                              timeline: List[Dict],
                              final_video_path: str = '',
                              audio_paths: List[str] = None,
                              bgm_path: str = '',
                              subtitle_text: str = '',
                              draft_dir: str = '',
                              export_basis: str = 'remix_timeline') -> Dict:
        """根据真实源素材片段导出剪映草稿，成片仅作为可选参考。"""
        try:
            from backend.utils.jianying_detector import (
                detect_jianying_draft_dir, export_draft_package
            )

            if not isinstance(timeline, list) or not timeline:
                raise ValueError('必须提供非空有效时间线')
            normalized_timeline = []
            for index, item in enumerate(timeline, 1):
                if not isinstance(item, dict):
                    raise ValueError(f'时间线第 {index} 段无效')
                source = item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path') or item.get('path')
                source_path = Path(str(source)) if source else None
                if source_path and not source_path.is_absolute():
                    source_path = PROJECT_ROOT / source_path
                if not source_path or not source_path.is_file():
                    raise ValueError(f'时间线第 {index} 段来源视频不存在')
                try:
                    start = float(item.get('source_start', item.get('shot_start')))
                    end = float(item.get('source_end', item.get('shot_end')))
                except (TypeError, ValueError):
                    raise ValueError(f'时间线第 {index} 段缺少有效起止时间')
                if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                    raise ValueError(f'时间线第 {index} 段范围无效')
                clip = dict(item)
                clip.update({'source_video': str(source_path.resolve()), 'source_start': start, 'source_end': end})
                normalized_timeline.append(clip)
            final_path = Path(final_video_path) if final_video_path else None
            if final_path and not final_path.is_absolute():
                final_path = PROJECT_ROOT / final_path
            rendered_reference = final_path if final_path and final_path.is_file() else None

            if not draft_dir:
                draft_dir = detect_jianying_draft_dir()
                if not draft_dir:
                    draft_dir = str(PROJECT_ROOT / 'output' / 'jianying_drafts')

            result = export_draft_package(
                draft_dir=draft_dir,
                project_id=project_id,
                timeline=normalized_timeline,
                video_path='',
                audio_paths=audio_paths or [],
                subtitle_text=subtitle_text,
                bgm_path=bgm_path,
            )
            result['export_basis'] = 'rendered_timeline' if rendered_reference else export_basis
            if rendered_reference:
                result.setdefault('warnings', []).append('已提供渲染成片作为参考；视频轨仍由源素材拆分镜头组成。')

            # 写入项目 config.tracks
            try:
                project = self.db_manager.get_project(project_id) or {}
                import json as _json
                raw_config = project.get('config')
                if isinstance(raw_config, str):
                    project_config = _json.loads(raw_config) if raw_config else {}
                elif isinstance(raw_config, dict):
                    project_config = raw_config
                else:
                    project_config = {}
                project_config['tracks'] = result.get('tracks', [])
                project_config.pop('jianying_draft', None)
                project_config['jianying_draft'] = {
                    key: result.get(key)
                    for key in ('native_jianying_project', 'draft_path', 'draft_root_path',
                                'draft_content_path', 'draft_meta_info_path', 'draft_name', 'warnings')
                }
                self.db_manager.update_project(project_id, {'config': project_config})
            except Exception as pe:
                logger.warning(f'⚠️ 写入项目草稿信息失败: {pe}')

            logger.info(
                '%s: %s',
                '✅ 剪映原生草稿导出成功' if result.get('native_jianying_project') else '✅ 本地草稿包导出成功（剪映不会自动扫描）',
                result.get('draft_path'),
            )
            return result
        except Exception as e:
            logger.error(f'❗ 混剪草稿导出失败: {e}', exc_info=True)
            raise
