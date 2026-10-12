"""
资源路径配置模块
管理项目中所有资源文件的路径
"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller 冻结模式（Anna Executa 二进制分发）：
    # 资源（backend/assets）随包打包在 _MEIPASS/backend 下保持原布局，
    # 输出/临时目录重定向到用户可写目录，避免写入程序安装目录。
    BASE_DIR = Path(getattr(sys, "_MEIPASS", "")) / "backend"
    PROJECT_ROOT = Path(os.environ.get("LOCALAPPDATA") or str(Path.home())) / "JJYB_AI智剪"
    OUTPUT_DIR = PROJECT_ROOT / "output"
else:
    # 项目根目录
    BASE_DIR = Path(__file__).resolve().parent.parent
    PROJECT_ROOT = BASE_DIR.parent
    OUTPUT_DIR = PROJECT_ROOT / 'output'


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def ensure_project_path(path: str | Path, *, allow_output_relative: bool = True) -> Path:
    """将用户给出的路径限制在项目根内；相对路径仅可解析到项目根。"""
    raw = Path(path).expanduser()
    candidate = raw.resolve() if raw.is_absolute() else (PROJECT_ROOT / raw).resolve()
    if not _is_within(candidate, PROJECT_ROOT):
        raise ValueError(f'路径必须位于项目根目录: {PROJECT_ROOT}')
    return candidate


def project_output_dir(*parts: str | Path, create: bool = True) -> Path:
    """返回项目根 output 下的安全目录，拒绝绝对或越界子路径。"""
    candidate = OUTPUT_DIR
    for part in parts:
        piece = Path(part)
        if piece.is_absolute():
            raise ValueError('output 子路径只能是项目内相对路径')
        candidate /= piece
    candidate = candidate.resolve()
    if not _is_within(candidate, OUTPUT_DIR):
        raise ValueError(f'输出路径必须位于项目 output 目录: {OUTPUT_DIR}')
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def get_project_output_dir(create: bool = True) -> Path:
    """返回唯一允许创建产物的项目内 output 目录。"""
    return project_output_dir(create=create)


def resolve_output_path(value: str | Path = '', *, create_parent: bool = False) -> Path:
    """规范化输出路径；相对路径固定落在 PROJECT_ROOT/output，拒绝外部绝对路径。"""
    raw = Path(value).expanduser() if value else Path()
    if raw.is_absolute():
        candidate = raw.resolve()
        if not _is_within(candidate, OUTPUT_DIR):
            import logging
            logging.getLogger('JJYB_AI智剪').warning('拒绝项目 output 外的输出路径: %s', candidate)
            raise ValueError(f'输出路径必须位于项目 output 目录: {OUTPUT_DIR}')
    else:
        parts = raw.parts
        relative = Path(*parts[1:]) if parts and parts[0].casefold() == 'output' else raw
        candidate = (OUTPUT_DIR / relative).resolve()
    if not _is_within(candidate, OUTPUT_DIR):
        import logging
        logging.getLogger('JJYB_AI智剪').warning('拒绝越界输出路径: %s', candidate)
        raise ValueError(f'输出路径必须位于项目 output 目录: {OUTPUT_DIR}')
    if create_parent:
        candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate

# ==================== 资源目录配置 ====================

# 后端资源目录
ASSETS_DIR = BASE_DIR / 'assets'
FONTS_DIR = ASSETS_DIR / 'fonts'
IMAGES_DIR = ASSETS_DIR / 'images'
AUDIO_DIR = ASSETS_DIR / 'audio'

# 确保目录存在
ASSETS_DIR.mkdir(exist_ok=True)
FONTS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

# ==================== 字体配置 ====================

# 默认中文字体 - 微软雅黑
DEFAULT_FONT = str(FONTS_DIR / 'wryh.ttf')
DEFAULT_FONT_NAME = '微软雅黑'

# 字体大小配置
DEFAULT_FONT_SIZE = 40
MIN_FONT_SIZE = 12
MAX_FONT_SIZE = 120

# 字体颜色配置
DEFAULT_FONT_COLOR = '#FFFFFF'  # 白色
DEFAULT_STROKE_COLOR = '#000000'  # 黑色描边
DEFAULT_STROKE_WIDTH = 2

# ==================== 字幕配置 ====================

# 字幕位置选项
SUBTITLE_POSITION_BOTTOM = 'bottom'
SUBTITLE_POSITION_TOP = 'top'
SUBTITLE_POSITION_CENTER = 'center'
SUBTITLE_POSITION_CUSTOM = 'custom'

DEFAULT_SUBTITLE_POSITION = SUBTITLE_POSITION_BOTTOM

# 字幕样式配置
SUBTITLE_STYLES = {
    'default': {
        'font': DEFAULT_FONT,
        'font_size': 40,
        'color': '#FFFFFF',
        'bg_color': 'transparent',
        'stroke_color': '#000000',
        'stroke_width': 2,
        'position': 'bottom'
    },
    'large': {
        'font': DEFAULT_FONT,
        'font_size': 80,
        'color': '#FFFFFF',
        'bg_color': 'transparent',
        'stroke_color': '#000000',
        'stroke_width': 4,
        'position': 'bottom'
    },
    'small': {
        'font': DEFAULT_FONT,
        'font_size': 30,
        'color': '#FFFFFF',
        'bg_color': 'transparent',
        'stroke_color': '#000000',
        'stroke_width': 1,
        'position': 'bottom'
    },
    'colorful': {
        'font': DEFAULT_FONT,
        'font_size': 45,
        'color': '#FFD700',  # 金色
        'bg_color': 'rgba(0,0,0,0.5)',
        'stroke_color': '#FF4500',  # 橙红色
        'stroke_width': 2,
        'position': 'bottom'
    },
    'zihun_wulongcha': {
        'font': str(FONTS_DIR / '字魂乌龙茶.ttf'),
        'font_size': 64,
        'color': '#FFFF66',
        'bg_color': 'rgba(0,0,0,0.4)',
        'stroke_color': '#000000',
        'stroke_width': 3,
        'position': 'bottom'
    },
    'zihun_guochao': {
        'font': str(FONTS_DIR / '字魂国潮手书.ttf'),
        'font_size': 60,
        'color': '#FFEE00',
        'bg_color': 'rgba(0,0,0,0.3)',
        'stroke_color': '#FF4500',
        'stroke_width': 3,
        'position': 'bottom'
    },
    'sourcehan_song_bold': {
        'font': str(FONTS_DIR / '思源宋体-Bold.otf'),
        'font_size': 50,
        'color': '#FFFFFF',
        'bg_color': 'rgba(0,0,0,0.5)',
        'stroke_color': '#000000',
        'stroke_width': 2,
        'position': 'bottom'
    }
}


def _auto_register_font_styles():
    """根据字体目录中的字体文件自动扩展字幕样式

    为每个字体文件创建一个基础样式（如果同名样式尚未定义），
    这样只需把字体文件放入 FONTS_DIR 并重启应用，就可以在样式下拉中使用。
    """
    try:
        if not FONTS_DIR.exists():
            return
        for font_path in FONTS_DIR.iterdir():
            if not font_path.is_file():
                continue
            if font_path.suffix.lower() not in {'.ttf', '.otf', '.ttc'}:
                continue

            style_id = font_path.stem
            if style_id in SUBTITLE_STYLES:
                # 已有同名手动配置样式时不覆盖
                continue

            SUBTITLE_STYLES[style_id] = {
                'font': str(font_path),
                'font_size': DEFAULT_FONT_SIZE,
                'color': DEFAULT_FONT_COLOR,
                'bg_color': 'transparent',
                'stroke_color': DEFAULT_STROKE_COLOR,
                'stroke_width': DEFAULT_STROKE_WIDTH,
                'position': DEFAULT_SUBTITLE_POSITION,
            }
    except Exception:
        # 自动扩展失败不影响基础样式使用
        pass


_auto_register_font_styles()

# ==================== 临时文件目录 ====================

TEMP_DIR = PROJECT_ROOT / 'temp'
UPLOADS_DIR = TEMP_DIR / 'uploads'
PROCESSING_DIR = TEMP_DIR / 'processing'
# 兼容旧名称：运行时可下载输出固定到项目根 output。
OUTPUTS_DIR = OUTPUT_DIR / 'temp_outputs'

# 确保临时目录存在
TEMP_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)
PROCESSING_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)

# ==================== 模型目录配置（可选） ====================

MODELS_DIR = BASE_DIR / 'models'
MODELS_DIR.mkdir(exist_ok=True)

# TransNetV2 场景检测模型
TRANSNETV2_MODEL_DIR = MODELS_DIR / 'transnetv2'

# ==================== 工具目录配置（可选） ====================

TOOLS_DIR = BASE_DIR / 'tools'
TOOLS_DIR.mkdir(exist_ok=True)

# ImageMagick工具路径
IMAGEMAGICK_DIR = TOOLS_DIR / 'imagemagick'

# ==================== 前端静态资源 ====================

FRONTEND_DIR = PROJECT_ROOT / 'frontend'
FRONTEND_STATIC_DIR = FRONTEND_DIR / 'static'
FRONTEND_TEMPLATES_DIR = FRONTEND_DIR / 'templates'

# ==================== 辅助函数 ====================

def get_font_path(font_name: str = None) -> str:
    """
    获取字体文件路径

    Args:
        font_name: 字体文件名，如 'wryh.ttf'，None则返回默认字体

    Returns:
        str: 字体文件的绝对路径
    """
    if font_name is None:
        return DEFAULT_FONT

    font_path = FONTS_DIR / font_name
    if font_path.exists():
        return str(font_path)
    else:
        # 如果指定字体不存在，返回默认字体
        return DEFAULT_FONT

def get_subtitle_style(style_name: str = 'default') -> dict:
    """
    获取字幕样式配置

    Args:
        style_name: 样式名称 ('default', 'large', 'small', 'colorful')

    Returns:
        dict: 字幕样式配置字典
    """
    return SUBTITLE_STYLES.get(style_name, SUBTITLE_STYLES['default']).copy()

def ensure_temp_dir() -> Path:
    """
    确保临时目录存在并返回路径

    Returns:
        Path: 临时目录路径
    """
    TEMP_DIR.mkdir(exist_ok=True)
    return TEMP_DIR

def clean_temp_dir():
    """递归清理临时目录中的普通文件，保留目录结构并返回清理统计。"""
    stats = {'deleted_files': 0, 'deleted_bytes': 0}
    try:
        for item in TEMP_DIR.rglob('*'):
            if not item.is_file():
                continue
            try:
                size = item.stat().st_size
                item.unlink()
                stats['deleted_files'] += 1
                stats['deleted_bytes'] += size
            except Exception:
                pass
    except Exception:
        pass
    return stats

def get_output_path(filename: str) -> Path:
    """
    获取输出文件路径

    Args:
        filename: 输出文件名

    Returns:
        Path: 输出文件的完整路径
    """
    return OUTPUTS_DIR / filename

# ==================== 路径验证 ====================

def validate_paths():
    """
    验证所有关键路径是否存在

    Returns:
        dict: 验证结果
    """
    results = {
        '基础目录': BASE_DIR.exists(),
        '资源目录': ASSETS_DIR.exists(),
        '字体目录': FONTS_DIR.exists(),
        '默认字体': Path(DEFAULT_FONT).exists(),
        '临时目录': TEMP_DIR.exists(),
        '输出目录': OUTPUTS_DIR.exists()
    }

    return results

# ==================== 配置信息输出 ====================

def print_config():
    """
    打印当前配置信息（用于调试）
    """
    print("=" * 60)
    print("📁 资源路径配置")
    print("=" * 60)
    print(f"项目根目录: {PROJECT_ROOT}")
    print(f"后端目录: {BASE_DIR}")
    print(f"资源目录: {ASSETS_DIR}")
    print(f"字体目录: {FONTS_DIR}")
    print(f"默认字体: {DEFAULT_FONT}")
    print(f"临时目录: {TEMP_DIR}")
    print(f"输出目录: {OUTPUTS_DIR}")
    print("=" * 60)
    print("✅ 路径验证结果:")
    for name, exists in validate_paths().items():
        status = "✅" if exists else "❌"
        print(f"  {status} {name}")
    print("=" * 60)


if __name__ == '__main__':
    # 测试配置
    print_config()

    # 测试获取字体
    print(f"\n默认字体路径: {get_font_path()}")
    print(f"默认字幕样式: {get_subtitle_style('default')}")
