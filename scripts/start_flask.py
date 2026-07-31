#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发调试用启动脚本 - 仅启动 Flask 服务，不启动桌面窗口。

放置于 scripts/ 目录，可在任意位置运行：
    py -3 scripts/start_flask.py

正式启动请使用根目录的 启动应用.bat 或 py -3 frontend/app.py。
"""
import sys
import os

# 设置编码
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 动态解析项目根目录（scripts/ 的上一级）
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

# 切换工作目录，确保相对路径（config/、uploads/ 等）基于项目根
os.chdir(BASE_DIR)

# 导入并启动
from frontend.app import app, socketio, APP_HOST, APP_PORT

print(f'')
print(f'=' * 60)
print(f'  JJYB_AI智剪 Flask 服务启动中（开发模式，无桌面窗口）...')
print(f'  项目根目录: {BASE_DIR}')
print(f'  访问地址: http://127.0.0.1:{APP_PORT}')
print(f'  原创解说: http://127.0.0.1:{APP_PORT}/commentary')
print(f'  视频混剪: http://127.0.0.1:{APP_PORT}/remix')
print(f'  AI配音:   http://127.0.0.1:{APP_PORT}/voiceover')
print(f'=' * 60)
print(f'')

socketio.run(
    app,
    host=APP_HOST,
    port=APP_PORT,
    debug=False,
    use_reloader=False,
    allow_unsafe_werkzeug=True
)
