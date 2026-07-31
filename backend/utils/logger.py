# -*- coding: utf-8 -*-
"""
日志工具模块
"""

import logging
import os
from datetime import datetime

def setup_logger(name='JJYB_AI智剪', log_file=None, level=logging.INFO):
    """配置日志记录器"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    return logger

def get_logger(name='JJYB_AI智剪'):
    """获取日志记录器"""
    return logging.getLogger(name)

logger = get_logger()
