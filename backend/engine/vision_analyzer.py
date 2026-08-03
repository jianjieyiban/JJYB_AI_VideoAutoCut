"""
视频画面分析引擎
使用视觉大模型分析视频内容
"""

import cv2
import numpy as np
from PIL import Image
import logging
from typing import List, Dict, Any, Callable, Optional
import os

logger = logging.getLogger('JJYB_AI智剪')


class VisionAnalyzer:
    """视频画面分析引擎"""

    def __init__(self):
        """初始化视觉分析器"""
        self.logger = logger
        self.models_loaded = False
        self._load_models()

    def _load_clip(self):
        """加载CLIP模型"""
        try:
            import clip
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
            self.clip_model, self.clip_preprocess = clip.load("ViT-B/32", device=device)
            self.clip_available = True
            self.logger.info('✅ CLIP模型加载成功')
        except ImportError:
            # CLIP未安装，使用备用方案
            self.logger.info('ℹ️ CLIP模型未安装，将使用备用图像分析方案')
            self.clip_available = False
            self.clip_model = None
            self.clip_preprocess = None
        except Exception as e:
            self.logger.warning(f'⚠️ CLIP模型加载失败: {e}')
            self.clip_available = False
            self.clip_model = None
            self.clip_preprocess = None

    def _load_models(self):
        """加载AI模型（延迟加载）"""
        try:
            # 尝试加载CLIP模型
            self._load_clip()

            # 尝试加载YOLO模型
            try:
                from ultralytics import YOLO
                self.yolo_model = YOLO('yolov8n.pt')
                self.yolo_available = True
                self.logger.info("✅ YOLO模型加载成功")
            except Exception as e:
                self.yolo_available = False
                self.yolo_model = None
                self.logger.warning(f"⚠️ YOLO模型加载失败: {e}")

            self.models_loaded = True

        except Exception as e:
            self.logger.error(f"❌ 模型加载失败: {e}")
            self.models_loaded = False

    @staticmethod
    def _invoke_progress(cb, progress_val: float, message: str):
        """统一调度 progress_callback，兼容两种签名：
        - 新签名（推荐）：cb(progress: float, message: str)
        - 旧签名：cb(message: str)
        """
        if not cb:
            return
        try:
            # 尝试双参数调用：(progress, message)
            cb(float(progress_val), str(message))
            return
        except TypeError:
            pass
        try:
            # 兼容旧单参数调用
            cb(str(message))
        except Exception:
            pass

    def analyze_video(
        self,
        video_path: str,
        max_keyframes: int = 10,
        scene_accuracy: str = 'smart_shot',
        progress_callback=None,
        precomputed_scenes=None,
    ) -> Dict[str, Any]:
        """分析视频，并根据精度选项生成场景或逐帧高精度镜头片段。

        复刻剪映专业版智能镜头分割流程：
          - 优先 TransNetV2 深度学习镜头边界检测（100帧滑动窗口 + 边界填充处理）
          - 退化时 OpenCV 内容差异+直方图双重校验，配合动态跳帧加速
          - 镜头评分：运动强度 + 色彩丰富度 + 亮度综合计算
          - 一个分割画面即一帧（一个镜头片段）
        """
        self.logger.info(f"🎬 开始分析视频: {video_path}")

        results = {
            'video_path': video_path,
            'keyframes': [],
            'scenes': [],
            'objects': [],
            'descriptions': [],
            'emotions': [],
            'summary': ''
        }

        # 视频基础信息（所有阶段都需要）
        cap_meta = cv2.VideoCapture(video_path)
        if cap_meta.isOpened():
            fps = float(cap_meta.get(cv2.CAP_PROP_FPS) or 30.0)
            total_frames = int(cap_meta.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = total_frames / fps if fps > 0 else 0.0
            results['fps'] = fps
            results['total_frames'] = total_frames
            results['duration'] = duration
        else:
            fps, total_frames, duration = 30.0, 0, 0.0
            results['fps'], results['total_frames'], results['duration'] = fps, total_frames, duration
        cap_meta.release()

        try:
            # ========== 阶段1: 智能镜头/场景检测（占 0-50%） ==========
            smart_shot_split = scene_accuracy == 'smart_shot' or bool(precomputed_scenes)
            if precomputed_scenes:
                scenes = []
                for index, item in enumerate(precomputed_scenes):
                    start = float(item.get('start_time', item.get('start', 0)))
                    end = float(item.get('end_time', item.get('end', start)))
                    scene = dict(item)
                    scene.update({
                        'id': item.get('id', index), 'type': item.get('type', 'smart_shot'),
                        'start_time': start, 'end_time': end, 'duration': end - start,
                        'start_frame': int(item.get('start_frame', round(start * fps))),
                        'end_frame': int(item.get('end_frame', round(end * fps))),
                    })
                    scene['representative_frame'] = int(item.get(
                        'representative_frame',
                        scene['start_frame'] + max(0, (scene['end_frame'] - scene['start_frame']) // 2),
                    ))
                    scenes.append(scene)
                self._invoke_progress(progress_callback, 50.0, f'已使用{len(scenes)}个预计算镜头')
            else:
                self._invoke_progress(progress_callback, 2.0, '正在逐帧检测镜头边界...')

                def shot_progress_cb(progress_0_100: float):
                    overall = 2.0 + float(progress_0_100) * 0.48
                    msg = ('正在检测镜头边界（评分阶段）' if progress_0_100 > 70 else '正在逐帧检测镜头边界...')
                    self._invoke_progress(progress_callback, overall, msg)

                scenes = self.detect_scenes(
                    video_path,
                    accuracy=scene_accuracy,
                    smart_shot_split=smart_shot_split,
                    progress_callback=shot_progress_cb if smart_shot_split else None,
                )
            results['scenes'] = scenes
            results['scene_accuracy'] = scene_accuracy
            results['smart_shot_split'] = smart_shot_split
            self.logger.info(f"✅ 检测到 {len(scenes)} 个{'智能镜头' if smart_shot_split else '场景'}")
            self._invoke_progress(progress_callback, 52.0, f'已检测到{len(scenes)}个镜头')

            # ========== 阶段2: 关键帧提取（占 50-60%） ==========
            keyframe_limit = len(scenes) if smart_shot_split else max_keyframes
            self._invoke_progress(progress_callback, 55.0, '正在提取镜头代表画面...')
            keyframes = self.extract_keyframes(video_path, scenes, keyframe_limit, one_per_scene=smart_shot_split)
            results['keyframes'] = keyframes
            self.logger.info(f"✅ 提取了 {len(keyframes)} 个关键帧")
            self._invoke_progress(progress_callback, 62.0, f'已提取{len(keyframes)}张代表画面')

            # ========== 阶段3: 关键帧内容理解（占 60-95%） ==========
            total_kf = len(keyframes)
            for i, frame_info in enumerate(keyframes):
                frame = frame_info['image']
                timestamp = frame_info['timestamp']

                if i == 0 or (i + 1) == total_kf or (i + 1) % max(1, total_kf // 10) == 0:
                    overall_pct = 62.0 + (i + 1) / max(1, total_kf) * 33.0  # 62 → 95
                    self._invoke_progress(
                        progress_callback, overall_pct,
                        f'正在理解镜头画面（{i + 1}/{total_kf}）...',
                    )
                # 物体检测
                if self.yolo_available:
                    objects = self.detect_objects(frame)
                    results['objects'].append({
                        'timestamp': timestamp,
                        'objects': objects
                    })

                # 生成描述
                description = self.generate_description(frame, timestamp)
                results['descriptions'].append({
                    'timestamp': timestamp,
                    'description': description
                })

                # 情感分析
                emotion = self.analyze_emotion(frame)
                results['emotions'].append({
                    'timestamp': timestamp,
                    'emotion': emotion
                })

                self.logger.info(f"✅ 分析关键帧 {i+1}/{total_kf}")

            # ========== 阶段4: 视频摘要（占 95-100%） ==========
            self._invoke_progress(progress_callback, 96.0, '正在生成视频摘要...')
            results['summary'] = self.generate_summary(results)
            self._invoke_progress(progress_callback, 100.0, '视频分析完成')

            self.logger.info("✅ 视频分析完成")
            return results

        except Exception as e:
            self.logger.error(f"❌ 视频分析失败: {e}", exc_info=True)
            self._invoke_progress(progress_callback, 100.0, f'视频分析失败: {e}')
            return results

    def detect_scenes(
        self,
        video_path: str,
        threshold: float = 30.0,
        accuracy: str = 'smart_shot',
        smart_shot_split: bool = False,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """检测场景或镜头边界。

        smart_shot_split 模式下直接调用 SmartShotSegmenter：
        - 优先 TransNetV2（参考项目 JJYB-ZJ 的 100 帧滑动窗口 + 前后填充算法）
        - 模型不可用时退化到 OpenCV 内容差异+直方图双重校验
        - 动态步长跳帧加速（1秒内帧处理速度提升 10~30 倍）
        - 逐帧计算运动强度、色彩丰富度与亮度，产出镜头评分
        """
        if smart_shot_split or accuracy == 'smart_shot':
            return self._detect_smart_shots(video_path, progress_callback=progress_callback)

        threshold_map = {
            'high': 22.0,
            'medium': 30.0,
            'low': 42.0,
        }
        threshold = threshold_map.get(accuracy, threshold)
        sample_interval = 1 if accuracy == 'high' else (5 if accuracy == 'medium' else 15)
        scenes = []
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            self.logger.error(f"❌ 无法打开视频: {video_path}")
            return scenes

        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        prev_frame = None
        scene_start = 0
        scene_id = 0

        for frame_num in range(0, total_frames, sample_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if not ret:
                break

            if prev_frame is not None:
                diff_score = np.mean(cv2.absdiff(prev_frame, frame))
                if diff_score > threshold:
                    scene_end = frame_num / fps
                    if scene_end > scene_start:
                        scenes.append({
                            'id': scene_id,
                            'start_time': scene_start,
                            'end_time': scene_end,
                            'duration': scene_end - scene_start
                        })
                        scene_start = scene_end
                        scene_id += 1

            prev_frame = frame

        total_duration = total_frames / fps
        if scene_start < total_duration:
            scenes.append({
                'id': scene_id,
                'start_time': scene_start,
                'end_time': total_duration,
                'duration': total_duration - scene_start
            })

        cap.release()
        return scenes

    def _detect_smart_shots(
        self,
        video_path: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """复刻剪映专业版智能镜头分割：调用 SmartShotSegmenter。

        核心算法：
        - 1) TransNetV2 深度学习模型（100帧滑动窗口、前后25帧填充）
        - 2) OpenCV 退化：帧差 + 直方图双重校验
        - 3) 动态步长跳帧（短视频逐帧、长视频采样）
        - 4) 镜头评分（运动强度、色彩丰富度、亮度）
        """
        shots_raw: List[Dict] = []
        fallback_used = False

        # --- 1) 优先调用封装好的 SmartShotSegmenter（TransNetV2 + 动态跳帧） ---
        try:
            from backend.engine.smart_shot_segmenter import SmartShotSegmenter

            segmenter = SmartShotSegmenter()
            result = segmenter.detect_shots(
                video_path=video_path,
                progress_callback=progress_callback,
            )
            if isinstance(result, dict):
                shots_raw = result.get('shots') or result.get('scenes') or []
                if not shots_raw and isinstance(result, list):
                    shots_raw = result
            elif isinstance(result, list):
                shots_raw = result
            self.logger.info(f"✅ SmartShotSegmenter 返回 {len(shots_raw)} 个镜头")
        except Exception as seg_exc:
            fallback_used = True
            self.logger.warning(f"⚠️ SmartShotSegmenter 不可用，将使用 OpenCV 退化算法: {seg_exc}")

        # --- 2) 退化算法（兜底）：逐帧联合特征 ---
        if not shots_raw:
            fallback_used = True
            self.logger.info("ℹ️ 使用 OpenCV 帧差+直方图退化算法进行镜头分割")
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                self.logger.error(f"❌ 无法打开视频: {video_path}")
                return []

            fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
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

                if progress_callback and total_frames > 0 and (frame_num % 10 == 0 or frame_num == total_frames - 1):
                    try:
                        progress_callback(min(99.0, frame_num / max(1, total_frames) * 100.0))
                    except Exception:
                        pass

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

            cap.release()
            frame_count = frame_num or total_frames
            if frame_count <= 0:
                return []
            if cuts[-1] != frame_count:
                cuts.append(frame_count)

            for index, (start_frame, end_frame) in enumerate(zip(cuts, cuts[1:])):
                if end_frame <= start_frame:
                    continue
                shots_raw.append({
                    'id': index,
                    'type': 'smart_shot',
                    'start_frame': start_frame,
                    'end_frame': end_frame - 1,
                    'start_time': round(start_frame / fps, 3),
                    'end_time': round(end_frame / fps, 3),
                    'duration': round((end_frame - start_frame) / fps, 3),
                    'representative_frame': start_frame + (end_frame - start_frame) // 2,
                    'score': 0.7,  # 退化算法默认中等评分
                })

        # --- 3) 规范输出格式，保证字段一致 ---
        fps = 30.0
        try:
            _c = cv2.VideoCapture(video_path)
            if _c.isOpened():
                fps = float(_c.get(cv2.CAP_PROP_FPS) or 30.0)
            _c.release()
        except Exception:
            pass

        shots: List[Dict[str, Any]] = []
        for index, s in enumerate(shots_raw):
            start = s.get('start_time')
            end = s.get('end_time')
            if start is None and 'start_frame' in s:
                start = s['start_frame'] / fps
            if end is None and 'end_frame' in s:
                end = s['end_frame'] / fps
            if start is None or end is None:
                continue
            start = round(float(start), 3)
            end = round(float(end), 3)
            if end <= start:
                continue
            start_frame = int(s.get('start_frame', int(start * fps)))
            end_frame = int(s.get('end_frame', int(end * fps)))
            repr_frame = int(
                s.get('representative_frame',
                      start_frame + max(0, (end_frame - start_frame) // 2))
            )
            shots.append({
                'id': int(s.get('id', index)),
                'type': s.get('type', 'smart_shot'),
                'start_frame': start_frame,
                'end_frame': end_frame,
                'start_time': start,
                'end_time': end,
                'duration': round(end - start, 3),
                'representative_frame': repr_frame,
                'score': float(s.get('score', s.get('visual_score', 0.7))),
                'algorithm': ('opencv_fallback' if fallback_used else
                              (s.get('algorithm') or 'smart_shot_segmenter')),
            })

        # 最后推一次 100% 进度，避免卡在 99%
        if progress_callback:
            try:
                progress_callback(100.0)
            except Exception:
                pass

        return shots

    def extract_keyframes(
        self,
        video_path: str,
        scenes: List[Dict],
        max_frames: int = 10,
        one_per_scene: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        提取关键帧

        Args:
            video_path: 视频路径
            scenes: 场景列表
            max_frames: 最大帧数

        Returns:
            关键帧列表
        """
        keyframes = []
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            return keyframes

        fps = cap.get(cv2.CAP_PROP_FPS)

        # 如果没有场景，创建一个默认场景
        if not scenes:
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            scenes = [{
                'id': 0,
                'start_time': 0,
                'end_time': total_frames / fps,
                'duration': total_frames / fps
            }]

        # 智能镜头分割固定每镜头保留一个代表画面；其他模式按最大关键帧数均匀采样。
        frames_per_scene = 1 if one_per_scene else max(1, max_frames // len(scenes))

        for scene in scenes:
            start_frame = int(scene['start_time'] * fps)
            end_frame = int(scene['end_time'] * fps)
            duration = end_frame - start_frame

            if duration <= 0:
                continue

            if one_per_scene:
                frame_num = int(scene.get('representative_frame', start_frame + duration // 2))
                frame_num = min(max(frame_num, start_frame), end_frame - 1)
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()
                if ret:
                    keyframes.append({
                        'timestamp': frame_num / fps,
                        'frame_number': frame_num,
                        'image': frame,
                        'scene_id': scene['id'],
                        'type': 'shot_representative_frame',
                    })
                continue

            step = max(1, duration // (frames_per_scene + 1))

            for i in range(1, frames_per_scene + 1):
                frame_num = start_frame + i * step
                if frame_num >= end_frame:
                    break

                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
                ret, frame = cap.read()

                if ret:
                    keyframes.append({
                        'timestamp': frame_num / fps,
                        'frame_number': frame_num,
                        'image': frame,
                        'scene_id': scene['id']
                    })

        cap.release()
        return keyframes

    def detect_objects(self, image: np.ndarray) -> List[Dict[str, Any]]:
        """
        检测图像中的物体

        Args:
            image: 图像数组

        Returns:
            物体列表
        """
        if not self.yolo_available:
            return []

        try:
            results = self.yolo_model(image, verbose=False)
            objects = []

            for r in results:
                for box in r.boxes:
                    objects.append({
                        'class': r.names[int(box.cls)],
                        'confidence': float(box.conf),
                        'bbox': box.xyxy[0].tolist()
                    })

            return objects

        except Exception as e:
            self.logger.error(f"❌ 物体检测失败: {e}")
            return []

    def generate_description(self, image: np.ndarray, timestamp: float) -> str:
        """
        生成图像描述

        Args:
            image: 图像数组
            timestamp: 时间戳

        Returns:
            描述文本
        """
        if self.clip_available:
            try:
                import torch
                import clip

                # 转换图像
                image_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
                image_input = self.clip_preprocess(image_pil).unsqueeze(0)

                # 预定义的描述候选
                text_candidates = [
                    "人物特写镜头",
                    "人物在说话",
                    "人物在行走",
                    "室内场景",
                    "室外场景",
                    "风景画面",
                    "动作场景",
                    "静态画面",
                    "明亮的场景",
                    "昏暗的场景"
                ]

                text_tokens = clip.tokenize(text_candidates)

                with torch.no_grad():
                    image_features = self.clip_model.encode_image(image_input)
                    text_features = self.clip_model.encode_text(text_tokens)

                    # 计算相似度
                    similarity = (100.0 * image_features @ text_features.T).softmax(dim=-1)
                    values, indices = similarity[0].topk(1)

                return text_candidates[indices[0]]

            except Exception as e:
                self.logger.error(f"❌ CLIP描述生成失败: {e}")

        # 备用方案：基于图像特征的简单描述
        return self._generate_simple_description(image)

    def _generate_simple_description(self, image: np.ndarray) -> str:
        """生成简单描述（备用方案）"""
        # 分析图像亮度
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        brightness = np.mean(gray)

        # 分析颜色
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        saturation = np.mean(hsv[:, :, 1])

        if brightness > 150:
            desc = "明亮的画面"
        elif brightness < 80:
            desc = "昏暗的画面"
        else:
            desc = "正常光线的画面"

        if saturation > 100:
            desc += "，色彩鲜艳"

        return desc

    def analyze_emotion(self, image: np.ndarray) -> str:
        """
        分析画面情感

        Args:
            image: 图像数组

        Returns:
            情感标签
        """
        # 基于颜色和亮度的简单情感分析
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        avg_brightness = hsv[:, :, 2].mean()
        avg_saturation = hsv[:, :, 1].mean()
        avg_hue = hsv[:, :, 0].mean()

        # 情感判断
        if avg_brightness > 150 and avg_saturation > 100:
            return "happy"  # 明亮且鲜艳 = 快乐
        elif avg_brightness < 100:
            return "sad"  # 昏暗 = 悲伤
        elif avg_saturation > 150:
            return "excited"  # 高饱和度 = 兴奋
        elif avg_hue < 30 or avg_hue > 150:
            return "warm"  # 暖色调 = 温暖
        else:
            return "neutral"  # 中性

    def generate_summary(self, analysis_results: Dict[str, Any]) -> str:
        """
        生成视频摘要

        Args:
            analysis_results: 分析结果

        Returns:
            摘要文本
        """
        scenes_count = len(analysis_results['scenes'])
        keyframes_count = len(analysis_results['keyframes'])

        # 统计主要情感
        emotions = [e['emotion'] for e in analysis_results['emotions']]
        main_emotion = max(set(emotions), key=emotions.count) if emotions else 'neutral'

        # 统计主要物体
        all_objects = []
        for obj_info in analysis_results['objects']:
            all_objects.extend([o['class'] for o in obj_info['objects']])

        main_objects = []
        if all_objects:
            from collections import Counter
            object_counts = Counter(all_objects)
            main_objects = [obj for obj, count in object_counts.most_common(3)]

        summary = f"视频包含{scenes_count}个场景，"
        summary += f"提取了{keyframes_count}个关键帧。"
        summary += f"整体氛围偏向{main_emotion}。"

        if main_objects:
            summary += f"主要内容包含：{', '.join(main_objects)}。"

        return summary


# 单例模式
_vision_analyzer_instance = None


def get_vision_analyzer():
    """获取视觉分析器单例"""
    global _vision_analyzer_instance
    if _vision_analyzer_instance is None:
        _vision_analyzer_instance = VisionAnalyzer()
    return _vision_analyzer_instance
