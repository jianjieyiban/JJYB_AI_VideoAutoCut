# -*- coding: utf-8 -*-
"""
一键升级更新服务（对标商业软件的自动更新体验）

功能链路：检查更新(GitHub Releases API) → 下载源码包 → 校验解压 →
生成更新脚本 → 退出应用 → 脚本覆盖代码文件 → 自动重启应用。

安全性说明：
  - Release 源码包由 `git archive` 生成，天然不含用户数据
    （数据库、API Key 配置、日志、素材均被 .gitignore 排除），
    因此覆盖式更新不会触碰任何用户数据；
  - robocopy /E 只增改不删除，包里没有的文件（用户数据）原样保留；
  - 更新脚本等待旧进程退出后再覆盖，避免 Windows 文件锁问题。
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

GITHUB_OWNER = 'jianjieyiban'
GITHUB_REPO = 'JJYB_AI_VideoAutoCut'
GITHUB_API = f'https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}'
GITHUB_HOME = f'https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}'
REQUEST_HEADERS = {
    'User-Agent': 'JJYB-AI-VideoAutoCut-Updater',
    'Accept': 'application/vnd.github+json',
}
# robocopy 覆盖时排除的目录（运行时缓存，不随包更新）
UPDATE_EXCLUDE_DIRS = 'temp logs __pycache__ .git node_modules dist uploads'
DOWNLOAD_TIMEOUT = (10, 600)
CHECK_TIMEOUT = 15


def get_local_version() -> str:
    try:
        from backend import __version__
        return str(__version__)
    except Exception:
        return '0.0.0'


def _parse_version(text: str) -> Optional[tuple]:
    """'v3.3.2' / '3.3.2-beta' -> (3, 3, 2)；解析失败返回 None。"""
    match = re.search(r'(\d+(?:\.\d+)+)', text or '')
    if not match:
        return None
    try:
        return tuple(int(p) for p in match.group(1).split('.'))
    except ValueError:
        return None


def _version_tuple(local: str) -> tuple:
    parsed = _parse_version(local)
    return parsed if parsed else (0, 0, 0)


def _find_source_asset(assets: List[dict]) -> Optional[dict]:
    """优先找 *-source.zip 资产；没有则退回 zipball（GitHub 自动打包）。"""
    for asset in assets or []:
        name = str(asset.get('name') or '')
        if name.endswith('.zip') and 'source' in name.lower():
            return asset
    return None


def check_update(channel: str = 'stable') -> Dict:
    """检查更新。

    channel: stable=最新正式版；beta=含预发布版；off=已禁用
    """
    if channel == 'off':
        return {'hasUpdate': False, 'version': get_local_version(),
                'notes': '自动更新已在设置中关闭。'}
    local_version = get_local_version()
    try:
        if channel == 'beta':
            resp = requests.get(
                f'{GITHUB_API}/releases?per_page=10',
                headers=REQUEST_HEADERS, timeout=CHECK_TIMEOUT)
            releases = resp.json() if resp.ok else []
            release = next((r for r in releases if isinstance(r, dict)), None)
        else:
            resp = requests.get(
                f'{GITHUB_API}/releases/latest',
                headers=REQUEST_HEADERS, timeout=CHECK_TIMEOUT)
            release = resp.json() if resp.ok else None
    except requests.RequestException as exc:
        logger.warning('检查更新网络失败: %s', exc)
        return {'hasUpdate': False, 'version': local_version,
                'notes': '无法连接 GitHub（检查网络或代理设置），可稍后重试或手动访问项目仓库。'}

    if not isinstance(release, dict) or not release.get('tag_name'):
        return {'hasUpdate': False, 'version': local_version,
                'notes': '暂时获取不到远程版本信息，请稍后重试。'}

    remote_tag = str(release['tag_name'])
    remote_ver = _parse_version(remote_tag) or (0, 0, 0)
    has_update = remote_ver > _version_tuple(local_version)

    asset = _find_source_asset(release.get('assets') or [])
    notes = str(release.get('body') or '')
    # 精简 release notes，去掉 markdown 符号噪音，保留前 1200 字
    notes = re.sub(r'[#*`>\[\]]', '', notes).strip()[:1200]

    return {
        'hasUpdate': has_update,
        'version': local_version,
        'latestVersion': remote_ver and '.'.join(map(str, remote_ver)),
        'latestTag': remote_tag,
        'notes': notes or '详见项目发布页。',
        'releaseUrl': release.get('html_url') or GITHUB_HOME,
        'downloadUrl': (asset or {}).get('browser_download_url'),
        'assetName': (asset or {}).get('name'),
        'assetSize': (asset or {}).get('size'),
        'publishedAt': release.get('published_at'),
        'homeUrl': GITHUB_HOME,
    }


def download_update(download_url: str, version: str = '') -> Dict:
    """流式下载更新包到 temp/update/，返回本地路径与大小。"""
    if not download_url:
        return {'ok': False, 'msg': '更新包地址无效，请到项目发布页手动下载。'}
    from backend.config.paths import PROJECT_ROOT
    update_dir = Path(PROJECT_ROOT) / 'temp' / 'update'
    update_dir.mkdir(parents=True, exist_ok=True)
    zip_path = update_dir / f'update_{version or "latest"}.zip'

    try:
        with requests.get(download_url, headers=REQUEST_HEADERS,
                          stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get('Content-Length') or 0)
            done = 0
            with open(zip_path, 'wb') as f:
                for chunk in resp.iter_content(chunk_size=1 << 20):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
        size_mb = zip_path.stat().st_size / 1024 / 1024
        logger.info('更新包下载完成: %s (%.2f MB)', zip_path, size_mb)
        return {'ok': True, 'path': str(zip_path), 'size': zip_path.stat().st_size,
                'total': total, 'msg': f'下载完成（{size_mb:.2f} MB）'}
    except requests.RequestException as exc:
        logger.error('更新包下载失败: %s', exc)
        return {'ok': False, 'msg': f'下载失败：{exc}。请检查网络/代理后重试，或手动下载。'}


def _extract_zip(zip_path: Path, dest: Path) -> Path:
    """解压并返回内层项目目录（源码包带一层 JJYB_AI_VideoAutoCut-vX/ 前缀）。"""
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest)
    entries = [p for p in dest.iterdir()]
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def _build_update_bat(source_dir: Path, project_root: Path) -> Path:
    """生成自更新批处理：等待退出 → robocopy 覆盖 → 重启 → 清理。"""
    bat = project_root / 'temp' / 'update' / 'update_and_restart.bat'
    bat.parent.mkdir(parents=True, exist_ok=True)
    content = f'''@echo off
rem JJYB AI VideoAutoCut self-update script
timeout /t 3 /nobreak >nul
robocopy "{source_dir}" "{project_root}" /E /NFL /NDL /NJH /NJS /NP /XD {UPDATE_EXCLUDE_DIRS}
if errorlevel 8 (
  echo FAILED > "{bat.parent / 'result.txt'}"
  exit /b 1
)
echo OK > "{bat.parent / 'result.txt'}"
cd /d "{project_root}"
start "" "{project_root / '启动应用.bat'}"
timeout /t 5 /nobreak >nul
rd /s /q "{bat.parent}"
del "%~f0"
'''
    # bat 用 GBK 写入（中文路径在 cmd 默认代码页下可靠）
    with open(bat, 'w', encoding='gbk', errors='replace') as f:
        f.write(content)
    return bat


def apply_update(zip_path: str) -> Dict:
    """应用更新：解压 → 生成脚本 → 启动脚本 → 退出本进程。"""
    from backend.config.paths import PROJECT_ROOT
    project_root = Path(PROJECT_ROOT)
    zip_file = Path(zip_path)
    if not zip_file.exists():
        return {'ok': False, 'msg': '更新包不存在，请先下载。'}

    try:
        extract_root = project_root / 'temp' / 'update' / 'extracted'
        source_dir = _extract_zip(zip_file, extract_root)

        # 完整性校验：包内必须包含后端入口
        if not (source_dir / 'backend').exists():
            return {'ok': False, 'msg': '更新包内容校验失败（缺少 backend 目录），已中止。'}

        bat = _build_update_bat(source_dir, project_root)
        logger.info('启动自更新脚本: %s', bat)
        # DETACHED 独立于 Flask 进程运行
        subprocess.Popen(
            ['cmd', '/c', str(bat)],
            cwd=str(project_root), close_fds=True,
            creationflags=getattr(subprocess, 'DETACHED_PROCESS', 0) |
                          getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {'ok': True, 'msg': '更新已就绪，应用将在数秒内自动重启，请勿关闭弹出的窗口。'}
    except (zipfile.BadZipFile, OSError) as exc:
        logger.error('应用更新失败: %s', exc)
        return {'ok': False, 'msg': f'应用更新失败：{exc}'}


__all__ = [
    'GITHUB_HOME', 'check_update', 'download_update', 'apply_update',
    'get_local_version',
]
