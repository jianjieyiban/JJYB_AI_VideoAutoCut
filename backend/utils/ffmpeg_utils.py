# -*- coding: utf-8 -*-
"""
FFmpeg Utils - FFmpeg 工具函数
提供 FFmpeg/FFprobe 检测、版本验证、错误处理等功能
"""

import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

logger = logging.getLogger('JJYB_AI智剪')


@dataclass
class FFmpegInfo:
    """FFmpeg 信息"""
    found: bool
    ffmpeg_path: Optional[str] = None
    ffprobe_path: Optional[str] = None
    version: Optional[str] = None
    version_info: Optional[Dict] = None
    error: Optional[str] = None


# 常见 FFmpeg 安装位置（Windows）
FFMPEG_CANDIDATE_PATHS = [
    # 用户本地安装
    Path(r'C:\Program Files\ffmpeg\bin'),
    Path(r'C:\ffmpeg\bin'),
    Path(r'%LOCALAPPDATA%\Programs\ffmpeg\bin'),
    # 项目捆绑
    None,  # 由 shutil.which 搜索
]

# FFmpeg 版本最低要求
MIN_VERSION = (4, 0, 0)


def _parse_version(version_str: str) -> Tuple[int, ...]:
    """解析 FFmpeg 版本字符串"""
    import re
    # 匹配 "ffmpeg version X.Y.Z" 或 "X.Y.Z"
    match = re.search(r'(\d+)\.(\d+)(?:\.(\d+))?', version_str)
    if match:
        major = int(match.group(1))
        minor = int(match.group(2))
        patch = int(match.group(3)) if match.group(3) else 0
        return (major, minor, patch)
    return (0, 0, 0)


def find_ffmpeg() -> FFmpegInfo:
    """
    查找系统中可用的 FFmpeg 和 FFprobe
    
    Returns:
        FFmpegInfo 对象，包含检测结果
    """
    result = FFmpegInfo(found=False)
    
    # 1. 尝试通过 shutil.which 查找
    for name in ['ffmpeg', 'ffmpeg.exe', 'ffprobe', 'ffprobe.exe']:
        path = shutil.which(name)
        if path:
            if 'ffmpeg' in name and not result.ffmpeg_path:
                result.ffmpeg_path = path
            elif 'ffprobe' in name and not result.ffprobe_path:
                result.ffprobe_path = path
    
    # 2. 检查常见安装位置（Windows）
    if not result.ffmpeg_path or not result.ffprobe_path:
        for base in FFMPEG_CANDIDATE_PATHS:
            if base is None:
                continue
            base = Path(base)
            if not base.exists():
                continue
                
            ffmpeg_exe = base / 'ffmpeg.exe'
            ffprobe_exe = base / 'ffprobe.exe'
            
            if ffmpeg_exe.exists() and not result.ffmpeg_path:
                result.ffmpeg_path = str(ffmpeg_exe)
            if ffprobe_exe.exists() and not result.ffprobe_path:
                result.ffprobe_path = str(ffprobe_exe)
    
    # 3. 验证找到的 FFmpeg
    if result.ffmpeg_path:
        version_info = get_ffmpeg_version(result.ffmpeg_path)
        if version_info:
            result.found = True
            result.version = version_info.get('version', '')
            result.version_info = version_info
            
            # 检查版本是否满足最低要求
            parsed = _parse_version(result.version)
            if parsed < MIN_VERSION:
                result.error = (
                    f'FFmpeg 版本过低: {result.version}，最低要求: {".".join(map(str, MIN_VERSION))}\n'
                    f'请升级 FFmpeg: https://ffmpeg.org/download.html'
                )
                logger.warning(result.error)
        else:
            result.error = f'无法获取 FFmpeg 版本信息: {result.ffmpeg_path}'
    
    if not result.found:
        result.error = _get_ffmpeg_install_guide()
        logger.error(f'未找到 FFmpeg: {result.error}')
    
    return result


def get_ffmpeg_version(ffmpeg_path: Optional[str] = None) -> Optional[Dict]:
    """
    获取 FFmpeg 版本信息
    
    Args:
        ffmpeg_path: FFmpeg 路径，None 则自动查找
        
    Returns:
        版本信息字典
    """
    cmd = [ffmpeg_path] if ffmpeg_path else ['ffmpeg', '-version']
    
    try:
        proc = subprocess.run(
            cmd + ['-version'],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if proc.returncode == 0:
            output = proc.stdout
            # 解析版本
            version_line = output.split('\n')[0] if output else ''
            import re
            match = re.search(r'ffmpeg version ([^\s]+)', version_line)
            version = match.group(1) if match else 'unknown'
            
            # 解析支持的编解码器
            codecs = []
            if 'libx264' in output:
                codecs.append('h264')
            if 'libx265' in output or 'hevc' in output.lower():
                codecs.append('hevc')
            if 'aac' in output:
                codecs.append('aac')
            if 'opus' in output:
                codecs.append('opus')
            
            return {
                'version': version,
                'full_output': output[:500],  # 限制长度
                'supported_codecs': codecs,
            }
    except Exception as e:
        logger.warning(f'获取 FFmpeg 版本失败: {e}')
    
    return None


def _get_ffmpeg_install_guide() -> str:
    """获取 FFmpeg 安装指南"""
    return """
未找到 FFmpeg，请安装 FFmpeg 后重试。

安装方法:
1. Windows: 
   - 官网下载: https://www.gyan.dev/ffmpeg/builds/
   - 或使用 winget: winget install ffmpeg
   - 或使用 Chocolatey: choco install ffmpeg
   
2. 将 FFmpeg 添加到系统 PATH 环境变量
   - 或将 ffmpeg.exe 所在目录放入 PATH

3. 验证安装:
   - 打开命令行，输入: ffmpeg -version
   - 如果显示版本信息则安装成功
"""


def check_video_file(video_path: str) -> Dict:
    """
    检查视频文件是否有效
    
    Args:
        video_path: 视频文件路径
        
    Returns:
        检查结果字典
    """
    result = {
        'valid': False,
        'exists': False,
        'readable': False,
        'has_video': False,
        'has_audio': False,
        'duration': 0.0,
        'resolution': None,
        'fps': 0.0,
        'error': None,
    }
    
    # 1. 检查文件存在
    path = Path(video_path)
    if not path.exists():
        result['error'] = f'文件不存在: {video_path}'
        return result
    result['exists'] = True
    
    # 2. 检查文件可读
    if not path.is_file():
        result['error'] = f'路径不是文件: {video_path}'
        return result
    
    # 3. 检查文件大小
    size = path.stat().st_size
    if size < 1000:  # 小于1KB可能是错误文件
        result['error'] = f'文件过小 ({size} bytes)，可能不是有效视频'
        return result
    
    result['readable'] = True
    
    # 4. 使用 ffprobe 检查视频流信息
    ffmpeg_info = find_ffmpeg()
    if not ffmpeg_info.found:
        result['error'] = 'FFmpeg 未安装，无法验证视频'
        return result
    
    try:
        cmd = [
            ffmpeg_info.ffprobe_path or 'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration:stream=codec_type,width,height,r_frame_rate',
            '-of', 'json',
            str(path)
        ]
        
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if proc.returncode == 0:
            import json
            info = json.loads(proc.stdout) if proc.stdout else {}
            
            # 解析格式信息
            format_info = info.get('format', {})
            duration = float(format_info.get('duration', 0) or 0)
            result['duration'] = duration
            
            # 解析流信息
            streams = info.get('streams', [])
            for stream in streams:
                codec_type = stream.get('codec_type', '')
                if codec_type == 'video':
                    result['has_video'] = True
                    result['resolution'] = f"{stream.get('width', 0)}x{stream.get('height', 0)}"
                    # 解析帧率
                    fps_str = stream.get('r_frame_rate', '0/1')
                    if '/' in fps_str:
                        num, denom = fps_str.split('/')
                        result['fps'] = float(num) / float(denom) if float(denom) != 0 else 0
                elif codec_type == 'audio':
                    result['has_audio'] = True
            
            result['valid'] = result['has_video']
            
            if not result['has_video']:
                result['error'] = '文件中不包含视频流'
        else:
            result['error'] = f'FFprobe 检查失败: {proc.stderr}'
            
    except subprocess.TimeoutExpired:
        result['error'] = 'FFprobe 超时'
    except Exception as e:
        result['error'] = f'检查失败: {str(e)}'
    
    return result


def estimate_processing_time(
    video_duration: float,
    output_duration: float,
    resolution: str = '1080p',
    has_transitions: bool = False,
    has_effects: bool = False
) -> Dict:
    """
    估算视频处理所需时间
    
    Args:
        video_duration: 输入视频时长（秒）
        output_duration: 输出视频时长（秒）
        resolution: 输出分辨率
        has_transitions: 是否有转场
        has_effects: 是否有特效
        
    Returns:
        时间估算字典
    """
    # 基础处理速度（实时倍率）
    base_speed = {
        '480p': 0.3,   # 480p 需要 0.3x 实时处理
        '720p': 0.5,
        '1080p': 0.8,
        '4k': 2.0,
    }
    
    speed = base_speed.get(resolution, 1.0)
    
    # 特效会增加处理时间
    if has_transitions:
        speed *= 1.2
    if has_effects:
        speed *= 1.5
    
    # 总处理时间 = 最大(输入时长, 输出时长) / 速度
    max_duration = max(video_duration, output_duration)
    estimated_seconds = max_duration / speed
    
    return {
        'estimated_seconds': round(estimated_seconds, 1),
        'estimated_minutes': round(estimated_seconds / 60, 1),
        'resolution': resolution,
        'has_transitions': has_transitions,
        'has_effects': has_effects,
        'speed_factor': speed,
    }


# 全局单例
_ffmpeg_info: Optional[FFmpegInfo] = None


def get_ffmpeg() -> FFmpegInfo:
    """获取 FFmpeg 信息（带缓存）"""
    global _ffmpeg_info
    if _ffmpeg_info is None:
        _ffmpeg_info = find_ffmpeg()
    return _ffmpeg_info


def require_ffmpeg() -> str:
    """
    确保 FFmpeg 可用，返回 ffmpeg 路径
    
    Raises:
        RuntimeError: FFmpeg 不可用时抛出
    """
    info = get_ffmpeg()
    if not info.found:
        raise RuntimeError(
            f'FFmpeg 不可用，无法执行视频处理操作。\n{info.error}'
        )
    if info.error and '版本过低' in info.error:
        raise RuntimeError(info.error)
    return info.ffmpeg_path or 'ffmpeg'
