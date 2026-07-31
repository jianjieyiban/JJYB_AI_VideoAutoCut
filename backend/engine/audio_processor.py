# -*- coding: utf-8 -*-
"""
Audio Processor
音频处理引擎 - 完整版
负责音频剪切、合并、混音、降噪等操作
"""

import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class AudioProcessor:
    """音频处理引擎 - 完整版"""
    
    def __init__(self, ffmpeg_path: str = 'ffmpeg'):
        """
        初始化音频处理引擎
        
        Args:
            ffmpeg_path: FFmpeg可执行文件路径
        """
        self.ffmpeg_path = ffmpeg_path
        logger.info('✅ 音频处理引擎初始化完成')
    
    def cut_audio(self, input_path: str, output_path: str,
                 start_time: float, end_time: float) -> bool:
        """
        剪切音频
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            start_time: 开始时间（秒）
            end_time: 结束时间（秒）
            
        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            duration = end_time - start_time
            
            cmd = [
                self.ffmpeg_path,
                '-i', input_path,
                '-ss', str(start_time),
                '-t', str(duration),
                '-acodec', 'copy',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                logger.info(f'✅ 音频剪切成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 音频剪切失败: {result.stderr}')
                return False
                
        except Exception as e:
            logger.error(f'音频剪切异常: {e}', exc_info=True)
            return False
    
    def merge_audios(self, input_paths: List[str], output_path: str) -> bool:
        """
        合并多个音频
        
        Args:
            input_paths: 输入音频路径列表
            output_path: 输出音频路径
            
        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            # 创建文件列表
            list_file = Path(output_path).parent / 'audio_list.txt'
            with open(list_file, 'w', encoding='utf-8') as f:
                for path in input_paths:
                    f.write(f"file '{path}'\n")
            
            cmd = [
                self.ffmpeg_path,
                '-f', 'concat',
                '-safe', '0',
                '-i', str(list_file),
                '-c', 'copy',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            list_file.unlink(missing_ok=True)
            
            if result.returncode == 0:
                logger.info(f'✅ 音频合并成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 音频合并失败: {result.stderr}')
                return False
                
        except Exception as e:
            logger.error(f'音频合并异常: {e}', exc_info=True)
            return False
    
    def mix_audios(self, audio1_path: str, audio2_path: str,
                  output_path: str, volume1: float = 1.0,
                  volume2: float = 1.0) -> bool:
        """
        混合两个音频
        
        Args:
            audio1_path: 第一个音频路径
            audio2_path: 第二个音频路径
            output_path: 输出音频路径
            volume1: 第一个音频音量（0.0-1.0）
            volume2: 第二个音频音量（0.0-1.0）
            
        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                self.ffmpeg_path,
                '-i', audio1_path,
                '-i', audio2_path,
                '-filter_complex',
                f'[0:a]volume={volume1}[a1];[1:a]volume={volume2}[a2];[a1][a2]amix=inputs=2:duration=first',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode == 0:
                logger.info(f'✅ 音频混合成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 音频混合失败: {result.stderr}')
                return False
                
        except Exception as e:
            logger.error(f'音频混合异常: {e}', exc_info=True)
            return False
    
    def adjust_volume(self, input_path: str, output_path: str,
                     volume: float = 1.0) -> bool:
        """
        调整音频音量
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            volume: 音量倍数（1.0为原音量）
            
        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                self.ffmpeg_path,
                '-i', input_path,
                '-filter:a', f'volume={volume}',
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                logger.info(f'✅ 音量调整成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 音量调整失败: {result.stderr}')
                return False
                
        except Exception as e:
            logger.error(f'音量调整异常: {e}', exc_info=True)
            return False
    
    def convert_format(self, input_path: str, output_path: str,
                      format: str = 'mp3', bitrate: str = '192k') -> bool:
        """
        转换音频格式
        
        Args:
            input_path: 输入音频路径
            output_path: 输出音频路径
            format: 输出格式
            bitrate: 比特率
            
        Returns:
            是否成功
        """
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            
            cmd = [
                self.ffmpeg_path,
                '-i', input_path,
                '-b:a', bitrate,
                '-y',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if result.returncode == 0:
                logger.info(f'✅ 格式转换成功: {output_path}')
                return True
            else:
                logger.error(f'❗ 格式转换失败: {result.stderr}')
                return False
                
        except Exception as e:
            logger.error(f'格式转换异常: {e}', exc_info=True)
            return False
