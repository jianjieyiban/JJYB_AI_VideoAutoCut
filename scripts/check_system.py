# -*- coding: utf-8 -*-
"""
System Check Script
Check all dependencies, APIs, and files.

放置于 scripts/ 目录，可在任意位置运行：
    py -3 scripts/check_system.py
"""

import os
import sys
import subprocess

# Set stdout encoding to utf-8
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')

# 动态解析项目根目录（scripts/ 的上一级），切换工作目录确保相对路径生效
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)

def print_header(text):
    """打印标题"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)

def check_python_version():
    """Check Python version"""
    print("\n[Check] Python version...")
    version = sys.version_info
    if version.major == 3 and version.minor >= 8:
        print(f"   [OK] Python {version.major}.{version.minor}.{version.micro} - Supported")
        return True
    else:
        print(f"   [ERROR] Python {version.major}.{version.minor}.{version.micro} - Need 3.8+")
        return False

def check_dependencies():
    """检查Python依赖"""
    print("\n[检查] Python依赖...")

    required_packages = {
        'flask': 'flask',
        'flask_socketio': 'flask_socketio',
        'requests': 'requests',
        'yaml': 'yaml',  # PyYAML
        'loguru': 'loguru',
        'psutil': 'psutil',
    }

    all_installed = True
    for package_name, import_name in required_packages.items():
        try:
            __import__(import_name)
            print(f"   [OK] {package_name} - 已安装")
        except Exception:
            print(f"   [ERROR] {package_name} - 未安装")
            all_installed = False

    return all_installed

def check_ffmpeg():
    """检查FFmpeg"""
    print("\n[检查] FFmpeg...")
    try:
        result = subprocess.run(['ffmpeg', '-version'],
                              capture_output=True,
                              text=True,
                              timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print(f"   [OK] FFmpeg - 已安装")
            print(f"      {version_line}")
            return True
        else:
            print("   [ERROR] FFmpeg - 未安装或无法运行")
            return False
    except Exception as e:
        print(f"   [ERROR] FFmpeg - 未找到 ({str(e)})")
        return False

def check_directories():
    """检查必要的目录结构"""
    print("\n[检查] 目录结构...")

    required_dirs = [
        'frontend/templates',
        'frontend/static',
        'backend/api',
        'backend/engine',
        'backend/database',
        'config',
        'logs',
        'output',
        'uploads',
        'temp'
    ]

    for dir_path in required_dirs:
        if os.path.exists(dir_path):
            print(f"   [OK] {dir_path}/")
        else:
            print(f"   [WARN] {dir_path}/ - 不存在（首次运行会自动创建或在运行时生成）")

    # 目录缺失不阻止启动
    return True

def check_api_files():
    """检查API文件"""
    print("\n[检查] API文件...")

    api_files = [
        'backend/api/project_api.py',
        'backend/api/material_routes.py',
        'backend/api/settings_api.py',
        'backend/api/export_api.py',
        'backend/api/voiceover_api.py',
        'backend/api/effects_api.py',
        'backend/api/subtitle_api.py',
        'backend/api/remix_api.py',
        'backend/api/commentary_api.py'
    ]

    all_exist = True
    for file_path in api_files:
        if os.path.exists(file_path):
            print(f"   [OK] {os.path.basename(file_path)}")
        else:
            print(f"   [ERROR] {os.path.basename(file_path)} - 缺失")
            all_exist = False

    return all_exist

def check_template_files():
    """检查模板文件"""
    print("\n[检查] 模板文件...")

    template_files = [
        'frontend/templates/index.html',
        'frontend/templates/projects.html',
        'frontend/templates/materials.html',
        'frontend/templates/settings.html',
        'frontend/templates/voiceover.html',
        'frontend/templates/commentary.html',
        'frontend/templates/remix.html',
        'frontend/templates/base.html'
    ]

    all_exist = True
    for file_path in template_files:
        if os.path.exists(file_path):
            print(f"   [OK] {os.path.basename(file_path)}")
        else:
            print(f"   [ERROR] {os.path.basename(file_path)} - 缺失")
            all_exist = False

    return all_exist

def check_database():
    """检查数据库"""
    print("\n[检查] 数据库...")

    db_file = None
    try:
        import yaml
        if os.path.exists('config/config.yaml'):
            with open('config/config.yaml', 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            db_rel = (cfg.get('database') or {}).get('path') or 'database/jjyb_ai.db'
        else:
            db_rel = 'database/jjyb_ai.db'
        db_file = db_rel if os.path.isabs(db_rel) else os.path.join(os.getcwd(), db_rel)
    except Exception:
        db_file = os.path.join(os.getcwd(), 'database', 'jjyb_ai.db')

    db_dir = os.path.dirname(db_file)
    print(f"   [INFO] 路径: {db_file}")
    if os.path.isdir(db_dir):
        print(f"   [OK] 目录存在: {db_dir}")
    else:
        print(f"   [WARN] 目录不存在: {db_dir}（首次运行将自动创建）")

    # 不阻止启动
    return True

def check_configs():
    """
    检查配置文件与日志目录
    """
    print("\n[检查] 配置文件与日志...")
    ok = True
    # config/config.yaml
    try:
        if os.path.exists('config/config.yaml'):
            import yaml
            with open('config/config.yaml', 'r', encoding='utf-8') as f:
                yaml.safe_load(f)
            print("   [OK] config/config.yaml 可读取")
        else:
            print("   [WARN] 缺少 config/config.yaml")
    except Exception as e:
        print(f"   [ERROR] 解析 config/config.yaml 失败: {e}")
        ok = False

    # config/ai_config.json
    try:
        import json
        if os.path.exists('config/ai_config.json'):
            with open('config/ai_config.json', 'r', encoding='utf-8') as f:
                json.load(f)
            print("   [OK] config/ai_config.json 可读取")
        else:
            print("   [WARN] 缺少 config/ai_config.json")
    except Exception as e:
        print(f"   [ERROR] 解析 config/ai_config.json 失败: {e}")
        ok = False

    # 日志目录可写
    try:
        os.makedirs('logs', exist_ok=True)
        test_file = os.path.join('logs', '.writetest')
        with open(test_file, 'w', encoding='utf-8') as f:
            f.write('ok')
        os.remove(test_file)
        print("   [OK] 日志目录可写: logs/")
    except Exception as e:
        print(f"   [WARN] 日志目录不可写: logs/ - {e}")
    return ok
def check_hardware_accel():
    """检查实际 GPU、FFmpeg 编码和 IndexTTS 设备限制。"""
    print("\n[检查] 硬件加速...")
    try:
        from backend.services.hardware_capability_service import hardware_capability_service
        capabilities = hardware_capability_service.capabilities()
        gpu = capabilities['gpu']
        ffmpeg = capabilities['ffmpeg']
        adapters = capabilities['display_adapters']
        print("   [INFO] 显示适配器: " + (', '.join(adapters) if adapters else '未检测到或当前平台不支持查询'))
        print("   [OK] NVIDIA CUDA: " + ('可用' if gpu['nvidia_cuda_available'] else '未检测到/不可用'))
        print("   [OK] AMD GPU: " + ('已检测到' if gpu['amd_detected'] else '未检测到'))
        print("   [INFO] FFmpeg: " + ('可用' if ffmpeg['available'] else '未检测到'))
        print("   [INFO] 硬件编码器: NVENC=%s, QSV=%s, AMF=%s" % (
            '是' if ffmpeg['nvenc'] else '否',
            '是' if ffmpeg['qsv'] else '否',
            '是' if ffmpeg['amf'] else '否',
        ))
        print("   [INFO] " + capabilities['encoding']['amd_note'])
        print("   [INFO] " + capabilities['index_tts']['note'])
    except Exception as e:
        print(f"   [WARN] 硬件加速检查异常: {e}")
    return True


def check_tts_asr():
    """
    检查 TTS/ASR 引擎可用性（仅信息展示，不阻塞）
    """
    print("\n[检查] 语音AI引擎...")
    def _try(name):
        try:
            __import__(name)
            print(f"   [OK] {name} - 已安装")
            return True
        except Exception:
            print(f"   [WARN] {name} - 未安装")
            return False
    # TTS
    _try('edge_tts')
    _try('gtts')
    _try('pyttsx3')
    # ASR
    _try('whisper')
    return True


def print_summary(checks):
    """打印总结"""
    print_header("检查总结")

    total = len(checks)
    passed = sum(1 for v in checks.values() if v)

    print(f"\n   总检查项: {total}")
    print(f"   [OK] 通过: {passed}")
    print(f"   [ERROR] 失败: {total - passed}")

    if passed == total:
        print("\n   [成功] 所有核心检查通过！系统可以启动。")
        print("\n   启动命令:")
        print("   py -3 frontend/app.py")
    else:
        print("\n   [警告] 部分检查失败，请先解决问题。")

        if not checks.get('dependencies'):
            print("\n   安装依赖（推荐）:")
            print("   pip install -r requirements.txt")

        if not checks.get('ffmpeg'):
            print("\n   安装FFmpeg:")
            print("   https://ffmpeg.org/download.html")

        print("\n   其他提示:")
        print("   - 可在 config/config.yaml 配置 app.port / database.path / logging")
        print("   - 可通过环境变量覆盖：APP_PORT / DB_PATH 等")

def main():
    """主函数"""
    print_header("JJYB_AI智剪 - 系统检查")

    checks = {
        'python': check_python_version(),
        'dependencies': check_dependencies(),
        'ffmpeg': check_ffmpeg(),
        'directories': check_directories(),
        'api_files': check_api_files(),
        'templates': check_template_files(),
        'database': check_database(),
        'configs': check_configs(),
        'hardware': check_hardware_accel(),
        'tts_asr': check_tts_asr(),
    }

    # 端口占用快速检查
    try:
        print("\n[检查] 端口占用...")
        app_port = 5000
        try:
            import yaml
            if os.path.exists('config/config.yaml'):
                with open('config/config.yaml', 'r', encoding='utf-8') as f:
                    cfg = yaml.safe_load(f) or {}
                app_port = int(os.getenv('APP_PORT') or ((cfg.get('app') or {}).get('port') or 5000))
            else:
                app_port = int(os.getenv('APP_PORT') or 5000)
        except Exception:
            pass
        occupied = False
        proc_info = ''
        try:
            import psutil
            for c in psutil.net_connections(kind='inet'):
                if c.laddr and hasattr(c.laddr, 'port') and c.laddr.port == app_port and c.status == 'LISTEN':
                    occupied = True
                    try:
                        proc_info = psutil.Process(c.pid).name()
                    except Exception:
                        proc_info = f"pid={c.pid}"
                    break
        except Exception:
            pass
        if not occupied:
            try:
                import socket
                s = socket.socket()
                try:
                    s.settimeout(0.4)
                    s.connect(('127.0.0.1', app_port))
                    occupied = True
                except Exception:
                    occupied = False
                finally:
                    s.close()
            except Exception:
                pass
        if occupied:
            print(f"   [WARN] 端口 {app_port} 已被占用（{proc_info or '未知进程'}）")
        else:
            print(f"   [OK] 端口 {app_port} 可用")
    except Exception as e:
        print(f"   [WARN] 端口检查异常: {e}")

    print_summary(checks)

if __name__ == '__main__':
    main()
