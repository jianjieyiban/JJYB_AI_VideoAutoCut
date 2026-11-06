# -*- coding: utf-8 -*-
"""
Video Processor
视频处理引擎 - 完整版
负责所有视频处理操作：剪切、合并、转码、特效等
"""

import logging
import math
import subprocess
import time
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable
import json

from backend.utils.ffmpeg_utils import find_ffmpeg, get_ffmpeg, require_ffmpeg, check_video_file

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
        self._last_merge_error = ''
        self._check_ffmpeg()

    def _check_ffmpeg(self):
        """检查FFmpeg是否可用"""
        info = find_ffmpeg()
        if info.found:
            logger.info(f'✅ FFmpeg检查通过: {info.version}')
            if info.error:
                logger.warning(f'⚠️ {info.error}')
        else:
            logger.error(f'❗ FFmpeg检查失败: {info.error}')
            raise RuntimeError(f'FFmpeg不可用: {info.error}')

    def _run_ffmpeg_with_retry(
        self,
        cmd: List[str],
        operation_name: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        validate_output: Callable[[str], bool] = None,
        output_path: str = None
    ) -> Tuple[bool, str]:
        """
        执行FFmpeg命令，支持重试机制

        Args:
            cmd: FFmpeg命令列表
            operation_name: 操作名称（用于日志）
            max_retries: 最大重试次数
            retry_delay: 重试间隔（秒）
            validate_output: 输出验证函数，接收输出路径，返回是否有效
            output_path: 输出文件路径

        Returns:
            (成功标志, 错误信息)
        """
        last_error = ''
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f'🔄 重试 {operation_name} (第 {attempt}/{max_retries} 次)')
                    time.sleep(retry_delay)

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                stdout, stderr = process.communicate(timeout=600)

                if process.returncode == 0:
                    # 检查输出文件是否有效
                    if output_path and validate_output:
                        if not validate_output(output_path):
                            last_error = '输出文件验证失败'
                            logger.warning(f'⚠️ {operation_name} 输出验证失败，将重试')
                            continue
                    logger.info(f'✅ {operation_name} 成功')
                    return True, ''
                else:
                    last_error = stderr.strip()
                    logger.warning(f'⚠️ {operation_name} 失败 (尝试 {attempt+1}/{max_retries}): {last_error[:200]}')

            except subprocess.TimeoutExpired:
                last_error = f'{operation_name} 超时'
                logger.error(f'❗ {last_error}')
                process.kill()
            except Exception as e:
                last_error = str(e)
                logger.error(f'❗ {operation_name} 异常: {e}')

        logger.error(f'❌ {operation_name} 最终失败: {last_error[:200]}')
        return False, last_error

    def get_video_info(self, video_path: str) -> Dict:
        """
        获取视频信息

        Args:
            video_path: 视频文件路径

        Returns:
            视频信息字典（时长、分辨率、编码等）
        """
        try:
            cmd = [
                'ffprobe',
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                video_path
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                data = json.loads(result.stdout)

                # 提取视频流信息
                video_stream = next(
                    (s for s in data.get('streams', []) if s['codec_type'] == 'video'),
                    None
                )

                if video_stream:
                    # 安全解析帧率（避免使用 eval）
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
                    return {
                        'duration': float(data['format'].get('duration', 0)),
                        'size': int(data['format'].get('size', 0)),
                        'width': video_stream.get('width', 0),
                        'height': video_stream.get('height', 0),
                        'fps': fps,
                        'codec': video_stream.get('codec_name', 'unknown'),
                        'bitrate': int(data['format'].get('bit_rate', 0)),
                        'has_audio': any(s.get('codec_type') == 'audio' for s in data.get('streams', []))
                    }

            return {}
        except Exception as e:
            logger.error(f'获取视频信息失败: {e}', exc_info=True)
            return {}

    def cut_video_with_speed(self, input_path: str, output_path: str,
                            start_time: float, end_time: float,
                            speed_factor: float = 1.0,
                            progress_callback=None) -> bool:
        """
        剪切视频并应用变速效果（节拍卡点专用）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            speed_factor: 速度因子（>1加速，<1减速）
            progress_callback: 进度回调函数

        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            duration = end_time - start_time

            # 构建变速滤镜
            if speed_factor != 1.0 and 0.5 <= speed_factor <= 2.0:
                # setpts调整视频速度，atempo调整音频速度
                video_speed = 1.0 / speed_factor
                audio_speed = speed_factor

                # 音频变速需要在0.5-2.0范围内
                audio_filter = f'atempo={audio_speed}' if 0.5 <= audio_speed <= 2.0 else ''

                cmd = [
                    self.ffmpeg_path,
                    '-i', input_path,
                    '-ss', str(start_time),
                    '-t', str(duration),
                    '-filter:v', f'setpts={video_speed}*PTS',
                ]

                if audio_filter:
                    cmd.extend(['-filter:a', audio_filter])

                cmd.extend([
                    '-c:v', 'libx264',
                    '-preset', 'veryfast',
                    '-crf', '18',
                    '-c:a', 'aac',
                    '-b:a', '192k',
                    '-movflags', '+faststart',
                    '-y', output_path
                ])

                logger.info(f'应用变速效果: speed={speed_factor:.2f}x')
            else:
                # 无变速或超出范围，使用普通剪切
                return self.cut_video(input_path, output_path, start_time, end_time, progress_callback)

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout, stderr = process.communicate()

            if process.returncode == 0:
                logger.info(f'✅ 变速剪切成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 变速剪切失败: {stderr}')
                return False

        except Exception as e:
            logger.error(f'变速剪切异常: {e}', exc_info=True)
            return False

    def cut_video(self, input_path: str, output_path: str,
                  start_time: float, end_time: float,
                  progress_callback=None) -> bool:
        """
        剪切视频（重编码，确保画面完整）

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            progress_callback: 进度回调函数

        Returns:
            是否成功
        """
        try:
            # 确保输出目录存在
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            duration = end_time - start_time

            logger.info('使用重编码切割，确保画面完整无黑屏')
            cmd = [
                self.ffmpeg_path,
                '-i', input_path,
                '-ss', str(start_time),
                '-t', str(duration),
                '-c:v', 'libx264',  # 重编码视频，避免黑屏
                '-c:a', 'aac',      # 重编码音频
                '-preset', 'veryfast',
                '-crf', '18',
                '-movflags', '+faststart',  # Web优化
                '-y',
                output_path
            ]

            logger.info(f'执行视频剪切: {input_path} -> {output_path}')
            logger.info(f'时间范围: {start_time}s - {end_time}s')

            # 使用重试机制
            success, error = self._run_ffmpeg_with_retry(
                cmd=cmd,
                operation_name='视频剪切',
                output_path=output_path,
                validate_output=lambda p: check_video_file(p) if p else False
            )

            if success:
                return True
            else:
                logger.error(f'❗ 视频剪切失败: {error}')
                return False

        except Exception as e:
            logger.error(f'视频剪切异常: {e}', exc_info=True)
            return False

    def merge_videos(self, input_paths: List[str], output_path: str,
                    progress_callback=None) -> bool:
        """
        合并多个视频

        Args:
            input_paths: 输入视频路径列表
            output_path: 输出视频路径
            progress_callback: 进度回调函数

        Returns:
            是否成功
        """
        try:
            if len(input_paths) < 2:
                logger.error('至少需要2个视频文件进行合并')
                return False

            return self.merge_videos_with_transitions(
                input_paths, output_path, transition='cut'
            )

        except Exception as e:
            logger.error(f'视频合并异常: {e}', exc_info=True)
            return False

    def merge_videos_with_transitions(self, input_paths: List[str], output_path: str,
                                      transition: str = 'fade', trans_duration: float = 0.15,
                                      durations: Optional[List[float]] = None) -> bool:
        """使用转场效果合并多个视频（基于 xfade）

        Args:
            input_paths: 输入视频路径列表
            output_path: 输出视频路径
            transition: 高层转场类型（cut/flash/zoom/shake/...）
            trans_duration: 单次转场时长（秒）
            durations: 每个输入片段的时长列表（秒），用于计算转场触发时间

        Returns:
            是否成功
        """
        try:
            if len(input_paths) < 2:
                logger.error('至少需要2个视频文件进行转场合并')
                return False

            infos = [self.get_video_info(path) for path in input_paths]
            if any(not info for info in infos):
                logger.error('无法获取片段信息，不能安全归一化拼接')
                return False

            if not durations or len(durations) != len(input_paths):
                durations = [info.get('duration', 0) for info in infos]
            segment_durations = [float(duration) for duration in durations]
            if any(not math.isfinite(duration) or duration <= 0
                   for duration in segment_durations):
                logger.error('片段时长必须为有限正数')
                return False

            width = max(2, int(infos[0]['width']) // 2 * 2)
            height = max(2, int(infos[0]['height']) // 2 * 2)
            fps = float(infos[0].get('fps') or 30)
            if not math.isfinite(fps) or fps <= 0:
                fps = 30.0
            # 将片段时长对齐到输出帧，保证音频和视频使用同一条时间轴。
            segment_durations = [math.ceil(duration * fps) / fps
                                 for duration in segment_durations]

            # 高层转场到 xfade 内置转场名称的映射
            # 结合内置更丰富的 transition，让 flash/zoom/shake 视觉差异更明显
            trans_key = (transition or '').lower()
            transition_map = {
                'cut': None,           # 不使用转场，保持原有快切
                'flash': 'fadewhite',  # 强烈闪白
                'zoom': 'zoomin',      # 冲击感缩放
                'shake': 'squeezeh'    # 横向挤压，模拟震动感
            }
            xf_transition = transition_map.get(trans_key, 'fade')

            # 基本安全限制，并根据转场类型微调默认时长
            # 仅当未显式指定 trans_duration (为 None) 时，才使用类型默认值
            if trans_duration is None:
                if trans_key == 'flash':
                    t = 0.08   # 非常短促的闪白
                elif trans_key == 'zoom':
                    t = 0.22   # 稍长一点的缩放冲击
                elif trans_key == 'shake':
                    t = 0.16   # 中等长度的震动感过渡
                else:
                    t = 0.15   # 其它转场使用通用默认值
            else:
                try:
                    t = float(trans_duration)
                except Exception:
                    t = 0.15

            t = max(0.05, min(t, 1.0))

            # 中间片段需要容纳前后两次重叠，转场不超过最短片段的一半。
            t = min(t, min(segment_durations) / 2)
            if xf_transition is None:
                t = 0.0

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            if xf_transition is None:
                # cut（快切）模式：走"逐段归一化 + concat copy"路径。
                # 原实现把全部片段塞进一条 filter_complex，片段数多时
                # 命令行超长/内存过高导致 ffmpeg 失败（用户反馈"精彩片段合并失败"）。
                merged = self._merge_cut_mode(
                    input_paths, output_path, infos, segment_durations,
                    width, height, fps)
                if merged:
                    return True
                # 归一化拼接失败时回退到一次性 filter_complex 路径（小批量仍稳定）
                logger.warning('归一化拼接失败，回退到 filter_complex 合并')

            return self._merge_via_filter_complex(
                input_paths, output_path, infos, segment_durations,
                xf_transition, t, width, height, fps)

        except Exception as e:
            logger.error(f'带转场视频合并异常: {e}', exc_info=True)
            self._last_merge_error = str(e)[:300]
            return False

    def _merge_via_filter_complex(self, input_paths, output_path, infos,
                                  segment_durations, xf_transition, t,
                                  width, height, fps) -> bool:
        """一次性 filter_complex 合并（原实现）。转场模式必须走这里；cut 模式作为回退。"""
        try:
            filter_parts = []
            for idx, (info, duration) in enumerate(zip(infos, segment_durations)):
                filter_parts.append(
                    f'[{idx}:v:0]setpts=PTS-STARTPTS,'
                    f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                    f'fps={fps},format=yuv420p,tpad=stop_mode=clone:stop_duration={duration},'
                    f'trim=duration={duration},settb=AVTB,setpts=PTS-STARTPTS[vnorm{idx}]'
                )
                audio_source = (f'[{idx}:a:0]aresample=48000,'
                                if info.get('has_audio') else
                                'anullsrc=r=48000:cl=stereo,')
                filter_parts.append(
                    f'{audio_source}aformat=sample_fmts=fltp:sample_rates=48000:'
                    f'channel_layouts=stereo,asetpts=PTS-STARTPTS,apad,'
                    f'atrim=duration={duration},asettb=1/48000,'
                    f'asetpts=PTS-STARTPTS[anorm{idx}]'
                )

            out_label = '[vout]'
            audio_label = '[aout]'
            if xf_transition is None:
                concat_inputs = ''.join(f'[vnorm{idx}][anorm{idx}]'
                                        for idx in range(len(input_paths)))
                filter_parts.append(
                    f'{concat_inputs}concat=n={len(input_paths)}:v=1:a=1'
                    f'{out_label}{audio_label}'
                )
            else:
                prev_label = '[vnorm0]'
                prev_audio = '[anorm0]'
                combined_duration = segment_durations[0]
                for idx in range(1, len(input_paths)):
                    offset = combined_duration - t
                    video_output = f'[vfade{idx}]'
                    audio_output = f'[afade{idx}]'
                    filter_parts.append(
                        f'{prev_label}[vnorm{idx}]xfade=transition={xf_transition}:'
                        f'duration={t}:offset={offset}{video_output}'
                    )
                    filter_parts.append(
                        f'{prev_audio}[anorm{idx}]acrossfade=d={t}:c1=tri:c2=tri'
                        f'{audio_output}'
                    )
                    combined_duration += segment_durations[idx] - t
                    prev_label = video_output
                    prev_audio = audio_output
                out_label = prev_label
                audio_label = prev_audio

            filter_complex = '; '.join(filter_parts)

            cmd = [self.ffmpeg_path]
            for p in input_paths:
                cmd.extend(['-i', p])

            cmd.extend([
                '-filter_complex', filter_complex,
                '-map', out_label,
                '-map', audio_label,
                '-c:v', 'libx264',
                '-c:a', 'aac',   # 音频编码
                '-b:a', '192k',  # 音频码率
                '-preset', 'veryfast',
                '-crf', '18',
                '-movflags', '+faststart',
                '-y', output_path
            ])

            logger.info(f"执行带转场的视频合并: {len(input_paths)}个文件 -> {output_path}, "
                        f"transition={xf_transition}, duration={t}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout, stderr = process.communicate()

            if process.returncode == 0:
                logger.info(f'✅ 带转场视频合并成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 带转场视频合并失败: {stderr}')
                self._last_merge_error = (stderr or '')[-300:]
                return False

        except Exception as e:
            logger.error(f'带转场视频合并异常: {e}', exc_info=True)
            self._last_merge_error = str(e)[:300]
            return False

    def _merge_cut_mode(self, input_paths, output_path, infos,
                        segment_durations, width, height, fps) -> bool:
        """cut（快切）模式合并：逐段归一化到统一参数，再用 concat demuxer 流复制拼接。

        单次 ffmpeg 只处理一路输入，规避多片段单命令的命令行超长与内存峰值问题；
        全部片段输出统一编码参数（libx264 crf18 / aac 192k / 48kHz 立体声），
        copy 拼接安全。无音轨片段补静音轨，保证拼接参数一致。
        """
        import shutil
        tmp_dir = Path(output_path).parent / f'norm_tmp_{Path(output_path).stem}'
        tmp_dir.mkdir(parents=True, exist_ok=True)
        norm_paths = []
        try:
            for idx, (src, duration) in enumerate(zip(input_paths, segment_durations)):
                norm = tmp_dir / f'norm_{idx:04d}.mp4'
                vfilter = (
                    f'scale={width}:{height}:force_original_aspect_ratio=decrease,'
                    f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,'
                    f'fps={fps},format=yuv420p'
                )
                has_audio = bool(infos[idx].get('has_audio'))
                cmd = [self.ffmpeg_path, '-hide_banner', '-loglevel', 'error']
                if has_audio:
                    cmd.extend(['-i', str(src)])
                else:
                    # 无音轨片段：补一条静音源，统一输出参数
                    cmd.extend(['-i', str(src),
                                '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo'])
                cmd.extend([
                    '-t', f'{duration:.6f}',
                    '-vf', vfilter,
                ])
                if has_audio:
                    cmd.extend(['-af', (
                        'aresample=48000,'
                        'aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,'
                        f'apad,atrim=duration={duration:.6f}'
                    )])
                cmd.extend([
                    '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18',
                    '-c:a', 'aac', '-b:a', '192k',
                    '-movflags', '+faststart',
                ])
                if not has_audio:
                    cmd.extend(['-map', '0:v:0', '-map', '1:a:0', '-shortest'])
                cmd.extend(['-y', str(norm)])

                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
                if proc.returncode != 0 or not norm.exists() or norm.stat().st_size == 0:
                    logger.error('❗ 片段归一化失败 #%d: %s', idx, (proc.stderr or '')[-300:])
                    self._last_merge_error = (proc.stderr or '')[-300:]
                    return False
                norm_paths.append(norm)

            # concat demuxer 流复制拼接
            concat_list = tmp_dir / 'concat_list.txt'
            concat_list.write_text(
                '\n'.join(f"file '{p.as_posix()}'" for p in norm_paths),
                encoding='utf-8')
            cmd = [self.ffmpeg_path, '-hide_banner', '-loglevel', 'error',
                   '-f', 'concat', '-safe', '0', '-i', str(concat_list),
                   '-c', 'copy', '-movflags', '+faststart', '-y', str(output_path)]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            if proc.returncode == 0 and Path(output_path).exists() and Path(output_path).stat().st_size > 0:
                logger.info(f'✅ 归一化拼接合并成功: {len(norm_paths)}个片段 -> {output_path}')
                return True
            logger.error('❗ concat copy 拼接失败: %s', (proc.stderr or '')[-300:])
            self._last_merge_error = (proc.stderr or '')[-300:]
            return False
        except Exception as e:
            logger.error('归一化拼接异常: %s', e, exc_info=True)
            self._last_merge_error = str(e)[:300]
            return False
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def convert_video(self, input_path: str, output_path: str,
                     codec: str = 'libx264', bitrate: str = '2M',
                     resolution: Optional[Tuple[int, int]] = None,
                     progress_callback=None) -> bool:
        """
        转码视频

        Args:
            input_path: 输入视频路径
            output_path: 输出视频路径
            codec: 视频编码器
            bitrate: 比特率
            resolution: 分辨率 (width, height)
            progress_callback: 进度回调函数

        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                self.ffmpeg_path,
                '-i', input_path,
                '-c:v', codec,
                '-b:v', bitrate,
                '-c:a', 'aac',
                '-b:a', '128k'
            ]

            if resolution:
                cmd.extend(['-s', f'{resolution[0]}x{resolution[1]}'])

            cmd.extend(['-y', output_path])

            logger.info(f'执行视频转码: {input_path} -> {output_path}')

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            stdout, stderr = process.communicate()

            if process.returncode == 0:
                logger.info(f'✅ 视频转码成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 视频转码失败: {stderr}')
                return False

        except Exception as e:
            logger.error(f'视频转码异常: {e}', exc_info=True)
            return False

    def extract_audio(self, video_path: str, audio_path: str,
                     audio_format: str = 'mp3') -> bool:
        """
        从视频中提取音频

        Args:
            video_path: 视频文件路径
            audio_path: 输出音频路径
            audio_format: 音频格式

        Returns:
            是否成功
        """
        try:
            Path(audio_path).parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                self.ffmpeg_path,
                '-i', video_path,
                '-vn',  # 不处理视频
                '-acodec', 'libmp3lame' if audio_format == 'mp3' else 'copy',
                '-y',
                audio_path
            ]

            logger.info(f'提取音频: {video_path} -> {audio_path}')

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                logger.info(f'✅ 音频提取成功: {audio_path}')
                return True
            else:
                logger.error(f'❗ 音频提取失败: {result.stderr}')
                return False

        except Exception as e:
            logger.error(f'音频提取异常: {e}', exc_info=True)
            return False

    def add_audio_to_video(self, video_path: str, audio_path: str,
                          output_path: str, replace: bool = True) -> bool:
        """
        为视频添加音频

        Args:
            video_path: 视频文件路径
            audio_path: 音频文件路径
            output_path: 输出视频路径
            replace: 是否替换原音频（True）还是混合（False）

        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            if replace:
                # 替换音频
                cmd = [
                    self.ffmpeg_path,
                    '-i', video_path,
                    '-i', audio_path,
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-map', '0:v:0',
                    '-map', '1:a:0',
                    '-shortest',
                    '-y',
                    output_path
                ]
            else:
                # 混合音频
                cmd = [
                    self.ffmpeg_path,
                    '-i', video_path,
                    '-i', audio_path,
                    '-filter_complex', '[0:a][1:a]amix=inputs=2:duration=first',
                    '-c:v', 'copy',
                    '-c:a', 'aac',
                    '-y',
                    output_path
                ]

            logger.info(f'添加音频到视频: {video_path} + {audio_path} -> {output_path}')

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                logger.info(f'✅ 音频添加成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 音频添加失败: {result.stderr}')
                return False

        except Exception as e:
            logger.error(f'音频添加异常: {e}', exc_info=True)
            return False

    def generate_thumbnail(self, video_path: str, output_path: str,
                          timestamp: float = 1.0) -> bool:
        """
        生成视频缩略图

        Args:
            video_path: 视频文件路径
            output_path: 输出图片路径
            timestamp: 截取时间点（秒）

        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            cmd = [
                self.ffmpeg_path,
                '-i', video_path,
                '-ss', str(timestamp),
                '-vframes', '1',
                '-y',
                output_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                logger.info(f'✅ 缩略图生成成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 缩略图生成失败: {result.stderr}')
                return False

        except Exception as e:
            logger.error(f'缩略图生成异常: {e}', exc_info=True)
            return False
