# -*- coding: utf-8 -*-
"""
File Utils
文件工具函数 - 完整版
提供文件操作、路径处理等工具函数
"""

import os
import shutil
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


def ensure_dir(directory: str) -> bool:
    """
    确保目录存在，不存在则创建
    
    Args:
        directory: 目录路径
        
    Returns:
        是否成功
    """
    try:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f'创建目录失败: {e}')
        return False


def get_file_size(file_path: str) -> int:
    """
    获取文件大小（字节）
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件大小
    """
    try:
        return Path(file_path).stat().st_size
    except Exception as e:
        logger.error(f'获取文件大小失败: {e}')
        return 0


def format_file_size(size_bytes: int) -> str:
    """
    格式化文件大小
    
    Args:
        size_bytes: 字节数
        
    Returns:
        格式化的大小字符串
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def get_file_hash(file_path: str, algorithm: str = 'md5') -> str:
    """
    计算文件哈希值
    
    Args:
        file_path: 文件路径
        algorithm: 哈希算法（md5/sha1/sha256）
        
    Returns:
        哈希值
    """
    try:
        hash_obj = hashlib.new(algorithm)
        
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_obj.update(chunk)
        
        return hash_obj.hexdigest()
    except Exception as e:
        logger.error(f'计算文件哈希失败: {e}')
        return ''


def copy_file(src: str, dst: str, overwrite: bool = False) -> bool:
    """
    复制文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        overwrite: 是否覆盖已存在的文件
        
    Returns:
        是否成功
    """
    try:
        dst_path = Path(dst)
        
        if dst_path.exists() and not overwrite:
            logger.warning(f'目标文件已存在: {dst}')
            return False
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        
        logger.info(f'✅ 文件复制成功: {src} -> {dst}')
        return True
    except Exception as e:
        logger.error(f'文件复制失败: {e}')
        return False


def move_file(src: str, dst: str, overwrite: bool = False) -> bool:
    """
    移动文件
    
    Args:
        src: 源文件路径
        dst: 目标文件路径
        overwrite: 是否覆盖已存在的文件
        
    Returns:
        是否成功
    """
    try:
        dst_path = Path(dst)
        
        if dst_path.exists() and not overwrite:
            logger.warning(f'目标文件已存在: {dst}')
            return False
        
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(src, dst)
        
        logger.info(f'✅ 文件移动成功: {src} -> {dst}')
        return True
    except Exception as e:
        logger.error(f'文件移动失败: {e}')
        return False


def delete_file(file_path: str) -> bool:
    """
    删除文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        是否成功
    """
    try:
        Path(file_path).unlink(missing_ok=True)
        logger.info(f'✅ 文件删除成功: {file_path}')
        return True
    except Exception as e:
        logger.error(f'文件删除失败: {e}')
        return False


def list_files(directory: str, pattern: str = '*', recursive: bool = False) -> List[str]:
    """
    列出目录中的文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式
        recursive: 是否递归搜索
        
    Returns:
        文件路径列表
    """
    try:
        dir_path = Path(directory)
        
        if recursive:
            files = list(dir_path.rglob(pattern))
        else:
            files = list(dir_path.glob(pattern))
        
        return [str(f) for f in files if f.is_file()]
    except Exception as e:
        logger.error(f'列出文件失败: {e}')
        return []


def get_file_info(file_path: str) -> Dict:
    """
    获取文件详细信息
    
    Args:
        file_path: 文件路径
        
    Returns:
        文件信息字典
    """
    try:
        path = Path(file_path)
        stat = path.stat()
        
        return {
            'name': path.name,
            'path': str(path.absolute()),
            'size': stat.st_size,
            'size_formatted': format_file_size(stat.st_size),
            'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
            'extension': path.suffix,
            'is_file': path.is_file(),
            'is_dir': path.is_dir()
        }
    except Exception as e:
        logger.error(f'获取文件信息失败: {e}')
        return {}


def clean_directory(directory: str, older_than_days: Optional[int] = None) -> int:
    """
    清理目录中的文件
    
    Args:
        directory: 目录路径
        older_than_days: 只删除N天前的文件（None表示删除所有）
        
    Returns:
        删除的文件数量
    """
    try:
        count = 0
        dir_path = Path(directory)
        
        if not dir_path.exists():
            return 0
        
        current_time = datetime.now().timestamp()
        
        for file_path in dir_path.rglob('*'):
            if file_path.is_file():
                if older_than_days is None:
                    file_path.unlink()
                    count += 1
                else:
                    file_age_days = (current_time - file_path.stat().st_mtime) / 86400
                    if file_age_days > older_than_days:
                        file_path.unlink()
                        count += 1
        
        logger.info(f'✅ 清理完成，删除了 {count} 个文件')
        return count
    except Exception as e:
        logger.error(f'清理目录失败: {e}')
        return 0


def get_unique_filename(directory: str, filename: str) -> str:
    """
    获取唯一的文件名（如果文件已存在，添加序号）
    
    Args:
        directory: 目录路径
        filename: 文件名
        
    Returns:
        唯一的文件名
    """
    path = Path(directory) / filename
    
    if not path.exists():
        return filename
    
    name = path.stem
    ext = path.suffix
    counter = 1
    
    while True:
        new_filename = f"{name}_{counter}{ext}"
        new_path = Path(directory) / new_filename
        
        if not new_path.exists():
            return new_filename
        
        counter += 1
