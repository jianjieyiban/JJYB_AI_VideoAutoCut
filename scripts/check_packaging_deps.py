#!/usr/bin/env python3
"""PyInstaller 打包前置依赖自检（Windows / Linux 通用）。

1.0.4 Linux 包云端崩溃的根因是构建 venv 残缺（requests 缺 urllib3 等传递依赖），
PyInstaller 静态分析静默漏包。构建前必须运行本脚本，任何缺失直接失败退出：
    python scripts/check_packaging_deps.py [--python /path/to/python]
"""
import argparse
import importlib.util
import subprocess
import sys

# auto_clip 全链路运行时必需的第三方模块（含懒加载与传递依赖）
REQUIRED = [
    # HTTP / requests 传递依赖（1.0.4 云端崩溃点）
    "requests", "urllib3", "charset_normalizer", "idna", "certifi",
    # TTS：edge-tts（依赖 aiohttp）与 gTTS（依赖 requests）
    "edge_tts", "aiohttp", "aiosignal", "frozenlist", "multidict", "yarl",
    "propcache", "aiohappyeyeballs", "attrs", "srt", "tabulate", "gtts",
    # AI SDK：openai（依赖 httpx/pydantic）与 anthropic
    "openai", "httpx", "httpcore", "h11", "anyio", "sniffio", "jiter",
    "pydantic", "pydantic_core", "annotated_types", "anthropic",
    "docstring_parser",
    # 视频处理链
    "moviepy", "imageio_ffmpeg", "cv2", "scenedetect", "pydub",
    "pysrt", "soundfile", "PIL", "numpy",
    # 日志与工具
    "loguru", "yaml", "psutil", "dotenv",
]

REQUIRED_BINARIES = ["ffmpeg", "ffprobe"]


def check_interpreter(python: str) -> int:
    code = (
        "import importlib.util as u, sys; "
        f"mods = {REQUIRED!r}; "
        "missing = [m for m in mods if u.find_spec(m) is None]; "
        "print('MISSING:' + ','.join(missing) if missing else 'DEPS_OK')"
    )
    out = subprocess.run(
        [python, "-c", code], capture_output=True, text=True, timeout=120
    )
    line = (out.stdout or "").strip().splitlines()
    verdict = line[-1] if line else ""
    if verdict == "DEPS_OK":
        print(f"[deps] all {len(REQUIRED)} required modules present ({python})")
        return 0
    print(f"[deps] FAIL ({python}): missing -> {verdict}", file=sys.stderr)
    if out.stderr:
        print(out.stderr, file=sys.stderr)
    return 1


def check_binaries() -> int:
    import shutil

    missing = [b for b in REQUIRED_BINARIES if shutil.which(b) is None]
    if not missing:
        print(f"[deps] ffmpeg/ffprobe found on PATH")
        return 0
    # 构建脚本会把 ffmpeg 拷入包内，PATH 没有时允许（Windows spec 用绝对路径）
    print(f"[deps] WARN not on PATH (ok if bundled by spec): {missing}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--python", default=sys.executable,
        help="target interpreter to inspect (default: current)",
    )
    args = parser.parse_args()
    rc = check_interpreter(args.python)
    rc += check_binaries()
    if rc:
        print(
            "[deps] install missing packages into the BUILD interpreter "
            "before running PyInstaller, e.g.:\n"
            "  <python> -m pip install urllib3 charset_normalizer idna "
            "certifi aiohttp srt tabulate httpx httpcore h11 anyio sniffio "
            "jiter pydantic pydantic-core annotated-types docstring-parser",
            file=sys.stderr,
        )
    return 1 if rc else 0


if __name__ == "__main__":
    sys.exit(main())
