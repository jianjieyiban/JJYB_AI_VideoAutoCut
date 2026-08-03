# -*- coding: utf-8 -*-
"""
智能场景评分和筛选系统
参考热门智能剪辑工具算法（剪映、快影等）
"""

import cv2
import numpy as np
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger('JJYB_AI智剪')


class SceneScorer:
    """
    场景评分器 - 多维度评估场景质量

    评分维度：
    1. 清晰度（Sharpness）- 拉普拉斯方差
    2. 构图质量（Composition）- 三分法则
    3. 运动强度（Motion）- 帧间差异
    4. 对象丰富度（Object Richness）- 关键对象数量和置信度
    5. 亮度质量（Brightness）- 曝光是否合适
    6. 对比度（Contrast）- 视觉冲击力
    """

    def __init__(self):
        self.logger = logger

        # 权重配置（可调整）
        self.weights = {
            'sharpness': 0.20,      # 清晰度权重
            'composition': 0.15,    # 构图权重
            'motion': 0.20,         # 运动权重
            'objects': 0.25,        # 对象丰富度权重（最重要）
            'brightness': 0.10,     # 亮度权重
            'contrast': 0.10        # 对比度权重
        }

        # 关键对象类别（YOLO COCO数据集）
        self.key_objects = {
            'person': 2.0,      # 人物最重要
            'face': 2.0,        # 人脸
            'cat': 1.5,         # 动物
            'dog': 1.5,
            'bird': 1.3,
            'car': 1.2,         # 交通工具
            'bicycle': 1.2,
            'sports_ball': 1.3  # 运动物品
        }

    def score_scene(self, frame: np.ndarray,
                   scene_info: Dict[str, Any],
                   objects: Optional[List[Dict]] = None,
                   prev_frame: Optional[np.ndarray] = None) -> float:
        """
        对单个场景进行综合评分

        Args:
            frame: 场景关键帧
            scene_info: 场景信息
            objects: YOLO检测到的对象列表
            prev_frame: 上一帧（用于计算运动）

        Returns:
            综合评分 (0-100)
        """
        try:
            scores = {}

            # 1. 清晰度评分
            scores['sharpness'] = self._score_sharpness(frame)

            # 2. 构图评分
            scores['composition'] = self._score_composition(frame)

            # 3. 运动评分
            if prev_frame is not None:
                scores['motion'] = self._score_motion(frame, prev_frame)
            else:
                scores['motion'] = 50.0  # 默认中等运动

            # 4. 对象丰富度评分
            scores['objects'] = self._score_objects(objects)

            # 5. 亮度评分
            scores['brightness'] = self._score_brightness(frame)

            # 6. 对比度评分
            scores['contrast'] = self._score_contrast(frame)

            # 计算加权总分
            total_score = sum(
                scores[key] * self.weights[key]
                for key in scores.keys()
            )

            # 记录详细评分（用于调试）
            self.logger.debug(
                f"场景评分: 总分={total_score:.1f}, "
                f"清晰度={scores['sharpness']:.1f}, "
                f"构图={scores['composition']:.1f}, "
                f"运动={scores['motion']:.1f}, "
                f"对象={scores['objects']:.1f}, "
                f"亮度={scores['brightness']:.1f}, "
                f"对比度={scores['contrast']:.1f}"
            )

            return total_score

        except Exception as e:
            self.logger.warning(f"场景评分失败: {e}")
            return 50.0  # 返回中等分数

    def _score_sharpness(self, frame: np.ndarray) -> float:
        """
        清晰度评分 - 使用拉普拉斯方差

        参考：剪映的清晰度检测算法
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

            # 归一化到0-100
            # 经验值：清晰图像的拉普拉斯方差通常>100
            score = min(100, (laplacian_var / 100) * 100)
            return score

        except Exception as e:
            self.logger.warning(f"清晰度评分失败: {e}")
            return 50.0

    def _score_composition(self, frame: np.ndarray) -> float:
        """
        构图评分 - 基于三分法则（Rule of Thirds）

        检测画面的关键点是否在黄金分割线附近
        """
        try:
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # 使用Shi-Tomasi角点检测找关键点
            corners = cv2.goodFeaturesToTrack(
                gray, maxCorners=20, qualityLevel=0.01, minDistance=10
            )

            if corners is None:
                return 50.0

            # 三分线位置
            thirds_x = [w / 3, 2 * w / 3]
            thirds_y = [h / 3, 2 * h / 3]

            # 计算关键点到三分线的距离
            score = 0
            for corner in corners:
                x, y = corner.ravel()

                # 检查是否靠近三分线
                min_dist_x = min(abs(x - thirds_x[0]), abs(x - thirds_x[1]))
                min_dist_y = min(abs(y - thirds_y[0]), abs(y - thirds_y[1]))

                # 距离越近，得分越高
                if min_dist_x < w / 6 or min_dist_y < h / 6:
                    score += 1

            # 归一化到0-100
            max_score = len(corners) * 0.6  # 60%的点在三分线附近算满分
            score = min(100, (score / max_score) * 100) if max_score > 0 else 50

            return score

        except Exception as e:
            self.logger.warning(f"构图评分失败: {e}")
            return 50.0

    def _score_motion(self, frame: np.ndarray, prev_frame: np.ndarray) -> float:
        """
        运动评分 - 基于帧间差异

        适度的运动表示有动态内容，太静止或太快都不好
        """
        try:
            # 计算帧差异
            gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            diff = cv2.absdiff(gray1, gray2)
            motion_score = np.mean(diff)

            # 理想运动范围：10-40
            # 太小表示静止，太大表示剧烈抖动
            if 10 <= motion_score <= 40:
                # 在理想范围内，得分高
                score = 100 - abs(motion_score - 25) * 2
            elif motion_score < 10:
                # 太静止
                score = motion_score * 5
            else:
                # 太剧烈
                score = max(0, 100 - (motion_score - 40) * 2)

            return max(0, min(100, score))

        except Exception as e:
            self.logger.warning(f"运动评分失败: {e}")
            return 50.0

    def _score_objects(self, objects: Optional[List[Dict]]) -> float:
        """
        对象丰富度评分

        参考：剪映的智能识别算法
        - 检测到人物/人脸：高分
        - 检测到动物：中高分
        - 检测到关键物体：中分
        """
        if not objects:
            return 30.0  # 无对象时给低分

        try:
            score = 0
            key_object_count = 0

            for obj in objects:
                obj_class = obj.get('class', '').lower()
                confidence = obj.get('confidence', 0)

                # 关键对象权重加分
                if obj_class in self.key_objects:
                    weight = self.key_objects[obj_class]
                    score += confidence * 20 * weight
                    key_object_count += 1
                else:
                    # 普通对象
                    score += confidence * 10

            # 对象数量加分（但不宜过多）
            count_bonus = min(30, len(objects) * 5)
            score += count_bonus

            # 关键对象额外加分
            if key_object_count > 0:
                score += key_object_count * 10

            return min(100, score)

        except Exception as e:
            self.logger.warning(f"对象评分失败: {e}")
            return 30.0

    def _score_brightness(self, frame: np.ndarray) -> float:
        """
        亮度评分 - 检查曝光是否合适

        过暗或过亮都不好
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            mean_brightness = np.mean(gray)

            # 理想亮度范围：80-170（0-255范围内）
            if 80 <= mean_brightness <= 170:
                # 在理想范围内
                score = 100 - abs(mean_brightness - 125) * 0.8
            elif mean_brightness < 80:
                # 太暗
                score = mean_brightness * 1.25
            else:
                # 太亮
                score = max(0, 100 - (mean_brightness - 170) * 1.2)

            return max(0, min(100, score))

        except Exception as e:
            self.logger.warning(f"亮度评分失败: {e}")
            return 50.0

    def _score_contrast(self, frame: np.ndarray) -> float:
        """
        对比度评分 - 视觉冲击力

        适度的对比度让画面更生动
        """
        try:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            std_dev = np.std(gray)

            # 理想对比度范围：标准差40-80
            if 40 <= std_dev <= 80:
                score = 100 - abs(std_dev - 60) * 1.5
            elif std_dev < 40:
                # 对比度太低
                score = std_dev * 2
            else:
                # 对比度太高
                score = max(0, 100 - (std_dev - 80) * 1.5)

            return max(0, min(100, score))

        except Exception as e:
            self.logger.warning(f"对比度评分失败: {e}")
            return 50.0


class SceneFilter:
    """
    场景筛选器 - 智能选择高质量场景

    参考热门工具的筛选策略：
    1. 保留开头和结尾（保证完整性）
    2. 根据评分排序，保留高分场景
    3. 根据目标时长动态调整保留比例
    4. 避免相似场景重复
    """

    def __init__(self, scorer: SceneScorer):
        self.scorer = scorer
        self.logger = logger

    def filter_scenes(self,
                     scenes: List[Dict[str, Any]],
                     target_duration: Optional[float] = None,
                     min_keep_ratio: float = 0.5,
                     max_keep_ratio: float = 0.9) -> List[Dict[str, Any]]:
        """
        智能筛选场景

        Args:
            scenes: 原始场景列表（包含评分）
            target_duration: 目标时长（秒）
            min_keep_ratio: 最小保留比例
            max_keep_ratio: 最大保留比例

        Returns:
            筛选后的场景列表
        """
        if not scenes:
            return []

        try:
            # 1. 计算总时长
            total_duration = sum(s.get('duration', 0) for s in scenes)

            # 2. 确定保留比例
            if target_duration and total_duration > target_duration * 1.2:
                # 需要缩短到目标时长
                keep_ratio = target_duration / total_duration
                keep_ratio = max(min_keep_ratio, min(keep_ratio, max_keep_ratio))
            else:
                # 时长合适，保留大部分
                keep_ratio = max_keep_ratio

            target_count = max(2, int(len(scenes) * keep_ratio))

            self.logger.info(
                f"🎯 场景筛选: 总场景{len(scenes)}个, "
                f"总时长{total_duration:.1f}秒, "
                f"目标时长{target_duration or '未设置'}秒, "
                f"保留比例{keep_ratio:.1%}, "
                f"目标场景数{target_count}个"
            )

            # 3. 按评分排序
            scored_scenes = sorted(
                scenes,
                key=lambda s: s.get('score', 0),
                reverse=True
            )

            # 4. 智能筛选策略
            selected = []

            # 4.1 始终保留开头场景（如果评分不是太低）
            if scenes and scenes[0].get('score', 0) > 30:
                selected.append(scenes[0])
                target_count -= 1

            # 4.2 始终保留结尾场景（如果评分不是太低）
            if len(scenes) > 1 and scenes[-1].get('score', 0) > 30 and scenes[-1] not in selected:
                selected.append(scenes[-1])
                target_count -= 1

            # 4.3 从高分场景中选择剩余的
            for scene in scored_scenes:
                if len(selected) >= target_count + 2:  # +2 因为开头结尾已占用
                    break
                if scene not in selected:
                    # 避免选择过于相似的连续场景
                    if self._is_diverse_enough(scene, selected):
                        selected.append(scene)

            # 5. 按时间顺序重新排序
            selected.sort(key=lambda s: s.get('start_time', 0))

            # 6. 重新分配ID和时间
            filtered_duration = 0
            for i, scene in enumerate(selected):
                scene['id'] = i
                scene['original_id'] = scene.get('id', i)
                scene['filtered'] = True
                filtered_duration += scene.get('duration', 0)

            self.logger.info(
                f"✅ 筛选完成: 保留{len(selected)}个场景, "
                f"筛选后时长{filtered_duration:.1f}秒, "
                f"平均评分{np.mean([s.get('score', 0) for s in selected]):.1f}"
            )

            return selected

        except Exception as e:
            self.logger.error(f"❌ 场景筛选失败: {e}", exc_info=True)
            return scenes  # 失败时返回原始场景

    def _is_diverse_enough(self, scene: Dict, selected: List[Dict]) -> bool:
        """
        检查场景是否与已选场景足够不同

        避免选择时间过于接近的场景
        """
        if not selected:
            return True

        scene_time = scene.get('start_time', 0)

        for s in selected:
            s_time = s.get('start_time', 0)
            # 如果两个场景时间间隔小于3秒，认为太相似
            if abs(scene_time - s_time) < 3.0:
                return False

        return True


# 便捷函数
def score_and_filter_scenes(scenes: List[Dict[str, Any]],
                           video_path: str,
                           objects_list: Optional[List[List[Dict]]] = None,
                           target_duration: Optional[float] = None) -> List[Dict[str, Any]]:
    """
    对场景进行评分和筛选的便捷函数

    Args:
        scenes: 场景列表
        video_path: 视频路径
        objects_list: 每个场景的对象列表
        target_duration: 目标时长

    Returns:
        筛选后的高质量场景列表
    """
    scorer = SceneScorer()
    filter_obj = SceneFilter(scorer)

    # 打开视频
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"无法打开视频: {video_path}")
        return scenes

    fps = cap.get(cv2.CAP_PROP_FPS)
    prev_frame = None

    # 为每个场景评分
    for i, scene in enumerate(scenes):
        try:
            # 提取场景中间帧作为代表帧
            mid_time = (scene.get('start_time', 0) + scene.get('end_time', 0)) / 2
            frame_num = int(mid_time * fps)

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()

            if not ret:
                scene['score'] = 50.0
                continue

            # 获取该场景的对象信息
            objects = objects_list[i] if objects_list and i < len(objects_list) else None

            # 评分
            score = scorer.score_scene(frame, scene, objects, prev_frame)
            scene['score'] = score

            prev_frame = frame

        except Exception as e:
            logger.warning(f"场景{i}评分失败: {e}")
            scene['score'] = 50.0

    cap.release()

    # 筛选
    filtered_scenes = filter_obj.filter_scenes(scenes, target_duration)

    return filtered_scenes
