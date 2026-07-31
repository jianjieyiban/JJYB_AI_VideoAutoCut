# -*- coding: utf-8 -*-
"""
Video Processor
视频处理引擎 - 完整版
负责所有视频处理操作：剪切、合并、转码、特效等
"""

import logging
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import json

logger = logging.getLogger(__name__)


class VideoProcessor:
    """视频处理引擎 - 完整版"""

    def __init__(self, ffmpeg_path: str = 'ffmpeg'):
        """
        初始化视频处理引擎

        Args:
            ffmpeg_path: FFmpeg可执行文件路径
        """
        self.ffmpeg_path = ffmpeg_path
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """检查FFmpeg是否可用"""
        try:
            result = subprocess.run(
                [self.ffmpeg_path, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info('✅ FFmpeg检查通过')
            else:
                logger.warning('⚠️ FFmpeg可能未正确安装')
        except Exception as e:
            logger.error(f'❗ FFmpeg检查失败: {e}')

    def get_video_info(self, video_path: str) -> Dict:
        """获取视频信息"""
        try:
            cmd = ['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', video_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                video_stream = next((s for s in data.get('streams', []) if s['codec_type'] == 'video'), None)
                if video_stream:
                    fps_str = str(video_stream.get('r_frame_rate', '0/1'))
                    try:
                        if '/' in fps_str:
                            num, den = fps_str.split('/')
                            den_v = float(den) if den else 1.0
                            fps = (float(num) / den_v) if den_v != 0 else 0.0
                        else:
                            fps = float(fps_str)
                    except Exception:
                        fps = 0.0
                    return {'duration': float(data['format'].get('duration', 0)), 'size': int(data['format'].get('size', 0)), 'width': video_stream.get('width', 0), 'height': video_stream.get('height', 0), 'fps': fps, 'codec': video_stream.get('codec_name', 'unknown'), 'bitrate': int(data['format'].get('bit_rate', 0))}
            return {}
        except Exception as e:
            logger.error(f'获取视频信息失败: {e}', exc_info=True)
            return {}

    def cut_video_with_speed(self, input_path: str, output_path: str, start_time: float, end_time: float, speed_factor: float = 1.0, progress_callback=None) -> bool:
        """剪切视频并应用变速效果（节拍卡点专用）"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            duration = end_time - start_time
            if speed_factor != 1.0 and 0.5 <= speed_factor <= 2.0:
                video_speed = 1.0 / speed_factor
                audio_speed = speed_factor
                audio_filter = f'atempo={audio_speed}' if 0.5 <= audio_speed <= 2.0 else ''
                cmd = [self.ffmpeg_path, '-i', input_path, '-ss', str(start_time), '-t', str(duration), '-filter:v', f'setpts={video_speed}*PTS']
                if audio_filter:
                    cmd.extend(['-filter:a', audio_filter])
                cmd.extend(['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-y', output_path])
                logger.info(f'应用变速效果: speed={speed_factor:.2f}x')
            else:
                return self.cut_video(input_path, output_path, start_time, end_time, progress_callback)
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                logger.info(f'✅ 变速剪切成功: {output_path}')
                return True
            logger.error(f'❗ 变速剪切失败: {stderr}')
            return False
        except Exception as e:
            logger.error(f'变速剪切异常: {e}', exc_info=True)
            return False

    def cut_video(self, input_path: str, output_path: str, start_time: float, end_time: float, progress_callback=None) -> bool:
        """剪切视频（重编码，确保画面完整）"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            duration = end_time - start_time
            logger.info('使用重编码切割，确保画面完整无黑屏')
            cmd = [self.ffmpeg_path, '-i', input_path, '-ss', str(start_time), '-t', str(duration), '-c:v', 'libx264', '-c:a', 'aac', '-preset', 'veryfast', '-crf', '18', '-movflags', '+faststart', '-y', output_path]
            logger.info(f'执行视频剪切: {input_path} -> {output_path}')
            logger.info(f'时间范围: {start_time}s - {end_time}s')
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                logger.info(f'✅ 视频剪切成功: {output_path}')
                return True
            logger.error(f'❗ 视频剪切失败: {stderr}')
            return False
        except Exception as e:
            logger.error(f'视频剪切异常: {e}', exc_info=True)
            return False

    def merge_videos(self, input_paths: List[str], output_path: str, progress_callback=None) -> bool:
        """合并多个视频"""
        try:
            if len(input_paths) < 2:
                logger.error('至少需要2个视频文件进行合并')
                return False
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            list_file = Path(output_path).parent / 'filelist.txt'
            with open(list_file, 'w', encoding='utf-8') as f:
                for path in input_paths:
                    f.write(f"file '{path}'\n")
            cmd = [self.ffmpeg_path, '-f', 'concat', '-safe', '0', '-i', str(list_file), '-c', 'copy', '-y', output_path]
            logger.info(f'执行视频合并: {len(input_paths)}个文件 -> {output_path}')
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            list_file.unlink(missing_ok=True)
            if process.returncode == 0:
                logger.info(f'✅ 视频合并成功: {output_path}')
                return True
            logger.error(f'❗ 视频合并失败: {stderr}')
            return False
        except Exception as e:
            logger.error(f'视频合并异常: {e}', exc_info=True)
            return False

    def merge_videos_with_transitions(self, input_paths: List[str], output_path: str, transition: str = 'fade', trans_duration: float = 0.15, durations: Optional[List[float]] = None) -> bool:
        """使用转场效果合并多个视频（基于 xfade）"""
        try:
            if len(input_paths) < 2:
                logger.error('至少需要2个视频文件进行转场合并')
                return False
            if not durations or len(durations) != len(input_paths):
                logger.warning('转场合并缺少有效的片段时长信息，回退到普通合并')
                return self.merge_videos(input_paths, output_path)
            trans_key = (transition or '').lower()
            transition_map = {'cut': None, 'flash': 'fadewhite', 'zoom': 'zoomin', 'shake': 'squeezeh'}
            xf_transition = transition_map.get(trans_key, 'fade')
            if xf_transition is None:
                logger.info('使用 cut 转场（无特效），回退到普通合并')
                return self.merge_videos(input_paths, output_path)
            if trans_duration is None:
                t = {'flash': 0.08, 'zoom': 0.22, 'shake': 0.16}.get(trans_key, 0.15)
            else:
                try:
                    t = float(trans_duration)
                except Exception:
                    t = 0.15
            t = max(0.05, min(t, 1.0))
            try:
                positive_durs = [float(d or 0.0) for d in durations if float(d or 0.0) > 0.0]
            except Exception:
                positive_durs = []
            if positive_durs:
                min_seg = min(positive_durs)
                if min_seg > 0 and t >= min_seg:
                    safe_t = max(0.05, min_seg * 0.6)
                    if t > safe_t:
                        logger.info(f'转场时长 {t:.3f}s 相对于最短片段 {min_seg:.3f}s 过长，自动调整为 {safe_t:.3f}s')
                        t = safe_t
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            filter_parts = []
            input_labels = [f'[{i}:v]' for i in range(len(input_paths))]
            prev_label = input_labels[0]
            try:
                combined_duration = float(durations[0] or 0.0)
            except Exception:
                combined_duration = 0.0
            out_label = None
            for idx in range(1, len(input_paths)):
                cur_label = input_labels[idx]
                try:
                    seg_dur = float(durations[idx] or 0.0)
                except Exception:
                    seg_dur = 0.0
                offset = max(combined_duration - t, 0.0)
                out_label = f'[v{idx}]'
                filter_parts.append(f"{prev_label}{cur_label} xfade=transition={xf_transition}:duration={t}:offset={offset} {out_label}")
                combined_duration = combined_duration + seg_dur - t
                prev_label = out_label
            if not filter_parts or out_label is None:
                logger.warning('转场 filter 构建失败，回退到普通合并')
                return self.merge_videos(input_paths, output_path)
            filter_complex = '; '.join(filter_parts)
            cmd = [self.ffmpeg_path]
            for p in input_paths:
                cmd.extend(['-i', p])
            cmd.extend(['-filter_complex', filter_complex, '-map', out_label, '-map', '0:a?', '-c:v', 'libx264', '-c:a', 'aac', '-b:a', '192k', '-preset', 'veryfast', '-crf', '18', '-movflags', '+faststart', '-y', output_path])
            logger.info(f"执行带转场的视频合并: {len(input_paths)}个文件 -> {output_path}, transition={xf_transition}, duration={t}")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                logger.info(f'✅ 带转场视频合并成功: {output_path}')
                return True
            logger.error(f'❗ 带转场视频合并失败: {stderr}')
            return self.merge_videos(input_paths, output_path)
        except Exception as e:
            logger.error(f'带转场视频合并异常，回退到普通合并: {e}', exc_info=True)
            return self.merge_videos(input_paths, output_path)

    def convert_video(self, input_path: str, output_path: str, codec: str = 'libx264', bitrate: str = '2M', resolution: Optional[Tuple[int, int]] = None, progress_callback=None) -> bool:
        """转码视频"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = [self.ffmpeg_path, '-i', input_path, '-c:v', codec, '-b:v', bitrate, '-c:a', 'aac', '-b:a', '128k']
            if resolution:
                cmd.extend(['-s', f'{resolution[0]}x{resolution[1]}'])
            cmd.extend(['-y', output_path])
            logger.info(f'执行视频转码: {input_path} -> {output_path}')
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = process.communicate()
            if process.returncode == 0:
                logger.info(f'✅ 视频转码成功: {output_path}')
                return True
            logger.error(f'❗ 视频转码失败: {stderr}')
            return False
        except Exception as e:
            logger.error(f'视频转码异常: {e}', exc_info=True)
            return False

    def extract_audio(self, video_path: str, audio_path: str, audio_format: str = 'mp3') -> bool:
        """从视频中提取音频"""
        try:
            Path(audio_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = [self.ffmpeg_path, '-i', video_path, '-vn', '-acodec', 'libmp3lame' if audio_format == 'mp3' else 'copy', '-y', audio_path]
            logger.info(f'提取音频: {video_path} -> {audio_path}')
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info(f'✅ 音频提取成功: {audio_path}')
                return True
            logger.error(f'❗ 音频提取失败: {result.stderr}')
            return False
        except Exception as e:
            logger.error(f'音频提取异常: {e}', exc_info=True)
            return False

    def add_audio_to_video(self, video_path: str, audio_path: str, output_path: str, replace: bool = True) -> bool:
        """为视频添加音频"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            if replace:
                cmd = [self.ffmpeg_path, '-i', video_path, '-i', audio_path, '-c:v', 'copy', '-c:a', 'aac', '-map', '0:v:0', '-map', '1:a:0', '-shortest', '-y', output_path]
            else:
                cmd = [self.ffmpeg_path, '-i', video_path, '-i', audio_path, '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=first', '-c:v', 'copy', '-c:a', 'aac', '-y', output_path]
            logger.info(f'添加音频到视频: {video_path} + {audio_path} -> {output_path}')
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                logger.info(f'✅ 音频添加成功: {output_path}')
                return True
            logger.error(f'❗ 音频添加失败: {result.stderr}')
            return False
        except Exception as e:
            logger.error(f'音频添加异常: {e}', exc_info=True)
            return False

    def generate_thumbnail(self, video_path: str, output_path: str, timestamp: float = 1.0) -> bool:
        """生成视频缩略图"""
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cmd = [self.ffmpeg_path, '-i', video_path, '-ss', str(timestamp), '-vframes', '1', '-y', output_path]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f'✅ 缩略图生成成功: {output_path}')
                return True
            logger.error(f'❗ 缩略图生成失败: {result.stderr}')
            return False
        except Exception as e:
            logger.error(f'缩略图生成异常: {e}', exc_info=True)
            return False
