# -*- coding: utf-8 -*-
"""
Scene Detector
场景检测引擎 - 完整版
使用多种算法检测视频场景切换
"""

import logging
from pathlib import Path
from typing import List, Dict, Optional
import cv2
import numpy as np

logger = logging.getLogger(__name__)


class SceneDetector:
    """场景检测引擎 - 完整版"""
    
    def __init__(self, threshold: float = 30.0, min_scene_len: int = 15):
        """
        初始化场景检测器
        
        Args:
            threshold: 场景切换阈值
            min_scene_len: 最小场景长度（帧数）
        """
        self.threshold = threshold
        self.min_scene_len = min_scene_len
        logger.info('✅ 场景检测器初始化完成')
    
    def detect_scenes(self, video_path: str,
                     method: str = 'content',
                     progress_callback=None) -> List[Dict]:
        """
        检测视频场景
        
        Args:
            video_path: 视频文件路径
            method: 检测方法（content/threshold/adaptive）
            progress_callback: 进度回调函数
            
        Returns:
            场景列表，每个场景包含start_frame, end_frame, start_time, end_time
        """
        try:
            logger.info(f'开始场景检测: {video_path}')
            
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.error('无法打开视频文件')
                return []
            
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            
            logger.info(f'视频信息: FPS={fps}, 总帧数={total_frames}')
            
            if method == 'content':
                scenes = self._detect_by_content(cap, fps, total_frames, progress_callback)
            elif method == 'threshold':
                scenes = self._detect_by_threshold(cap, fps, total_frames, progress_callback)
            else:
                scenes = self._detect_by_content(cap, fps, total_frames, progress_callback)
            
            cap.release()
            
            logger.info(f'✅ 场景检测完成，共检测到 {len(scenes)} 个场景')
            return scenes
            
        except Exception as e:
            logger.error(f'❗ 场景检测失败: {e}', exc_info=True)
            return []
    
    def _detect_by_content(self, cap, fps: float, total_frames: int,
                          progress_callback=None) -> List[Dict]:
        """基于内容差异的场景检测"""
        scenes = []
        prev_frame = None
        scene_start = 0
        frame_idx = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 转换为灰度图
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            if prev_frame is not None:
                # 计算帧间差异
                diff = cv2.absdiff(prev_frame, gray)
                mean_diff = np.mean(diff)
                
                # 如果差异超过阈值，认为是场景切换
                if mean_diff > self.threshold and (frame_idx - scene_start) >= self.min_scene_len:
                    scenes.append({
                        'start_frame': scene_start,
                        'end_frame': frame_idx - 1,
                        'start_time': scene_start / fps,
                        'end_time': (frame_idx - 1) / fps,
                        'duration': (frame_idx - 1 - scene_start) / fps
                    })
                    scene_start = frame_idx
            
            prev_frame = gray
            frame_idx += 1
            
            # 进度回调
            if progress_callback and frame_idx % 30 == 0:
                progress = (frame_idx / total_frames) * 100
                progress_callback(progress)
        
        # 添加最后一个场景
        if scene_start < frame_idx:
            scenes.append({
                'start_frame': scene_start,
                'end_frame': frame_idx - 1,
                'start_time': scene_start / fps,
                'end_time': (frame_idx - 1) / fps,
                'duration': (frame_idx - 1 - scene_start) / fps
            })
        
        return scenes
    
    def _detect_by_threshold(self, cap, fps: float, total_frames: int,
                            progress_callback=None) -> List[Dict]:
        """基于阈值的场景检测"""
        scenes = []
        prev_hist = None
        scene_start = 0
        frame_idx = 0
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            # 计算直方图
            hist = cv2.calcHist([frame], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist = cv2.normalize(hist, hist).flatten()
            
            if prev_hist is not None:
                # 计算直方图相似度
                similarity = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                
                # 如果相似度低于阈值，认为是场景切换
                if similarity < 0.7 and (frame_idx - scene_start) >= self.min_scene_len:
                    scenes.append({
                        'start_frame': scene_start,
                        'end_frame': frame_idx - 1,
                        'start_time': scene_start / fps,
                        'end_time': (frame_idx - 1) / fps,
                        'duration': (frame_idx - 1 - scene_start) / fps
                    })
                    scene_start = frame_idx
            
            prev_hist = hist
            frame_idx += 1
            
            if progress_callback and frame_idx % 30 == 0:
                progress = (frame_idx / total_frames) * 100
                progress_callback(progress)
        
        # 添加最后一个场景
        if scene_start < frame_idx:
            scenes.append({
                'start_frame': scene_start,
                'end_frame': frame_idx - 1,
                'start_time': scene_start / fps,
                'end_time': (frame_idx - 1) / fps,
                'duration': (frame_idx - 1 - scene_start) / fps
            })
        
        return scenes
    
    def export_scenes(self, scenes: List[Dict], output_path: str) -> bool:
        """
        导出场景信息到JSON文件
        
        Args:
            scenes: 场景列表
            output_path: 输出文件路径
            
        Returns:
            是否成功
        """
        try:
            import json
            
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'total_scenes': len(scenes),
                    'scenes': scenes
                }, f, ensure_ascii=False, indent=2)
            
            logger.info(f'✅ 场景信息导出成功: {output_path}')
            return True
            
        except Exception as e:
            logger.error(f'❗ 场景信息导出失败: {e}', exc_info=True)
            return False
