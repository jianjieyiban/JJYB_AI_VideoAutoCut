#!/usr/bin/env python3
"""构建后校验：PYZ 归档必须包含全部运行时模块（防 PyInstaller 静默漏包）。

用法：python check_pyz.py <onedir>/_internal/PYZ-00.pyz
任一必需模块缺失 -> exit 1。
"""
import sys
from pathlib import Path

from PyInstaller.archive.readers import ZlibArchiveReader

REQUIRED = [
    # 1.0.4 云端崩溃根因相关（urllib3 等 requests 传递依赖）
    "urllib3", "requests", "charset_normalizer", "idna", "certifi",
    # TTS 懒加载链
    "edge_tts", "aiohttp", "aiosignal", "frozenlist", "multidict", "yarl",
    "srt", "tabulate", "gtts",
    # AI SDK 懒加载链
    "openai", "httpx", "httpcore", "h11", "anyio", "sniffio", "pydantic",
    "pydantic_core",
    # 引擎链
    "backend.engine.auto_clip_controller", "backend.engine.tts_engine",
    "backend.engine.video_analyzer", "backend.engine.multi_model_adapter",
    "backend.engine.video_composer",
    "cv2", "moviepy", "imageio_ffmpeg", "scenedetect", "pydub",
    "loguru", "yaml", "psutil",
]

# 私有桥接模块不在开源仓库内：仅当本地存在源文件时才参与校验，
# 避免开源构建环境因缺该模块而误报漏包。
_PRIVATE_OPTIONAL = [
    "backend.engine.anna_host_llm",
]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    pyz = Path(sys.argv[1])
    if not pyz.is_file():
        print(f"PYZ not found: {pyz}", file=sys.stderr)
        return 2
    toc = set(ZlibArchiveReader(str(pyz)).toc.keys())
    repo_root = Path(__file__).resolve().parents[1]
    required = list(REQUIRED)
    for m in _PRIVATE_OPTIONAL:
        if (repo_root / m.replace('.', '/')).with_suffix('.py').exists():
            required.append(m)
    missing = [m for m in required if m not in toc]
    print(f"[pyz] {pyz.name}: {len(toc)} modules archived")
    if missing:
        print("[pyz] MISSING MODULES:", ", ".join(missing), file=sys.stderr)
        return 1
    print("[pyz] ALL REQUIRED MODULES PRESENT")
    return 0


if __name__ == "__main__":
    sys.exit(main())
