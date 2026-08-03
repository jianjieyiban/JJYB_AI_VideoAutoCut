#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
封面 / 图像生成 API 路由模块
=================================
支持厂商：
  - OpenAI 兼容网关（openai / siliconflow / openrouter / doubao / chatglm /
                     minimax / custom_openai 等）→ /v1/images/generations
  - 阿里云 通义万相（DashScope ImageSynthesis）
  - 百度 文心一格（AI 绘画 3.0）
  - 腾讯 混元生图（TII / HunyuanImage）
  - Fallback：本地 PIL 模板（当云端未配置或失败时，自动生成带文字+渐变的
    高可读封面，保证功能「永远可用」，不会阻塞用户后续剪辑流程。

路由前缀：/api/cover
"""

import os
import io
import re
import json
import time
import uuid
import base64
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

from flask import Blueprint, request, jsonify, current_app, send_from_directory, abort

logger = logging.getLogger('JJYB_AI智剪')

# =========================================================
# Blueprint + 全局
# =========================================================
cover_bp = Blueprint('cover', __name__, url_prefix='/api/cover')

_lock = threading.Lock()
_history: List[Dict[str, Any]] = []          # 内存中的历史（最近 200 条）
_MAX_HISTORY = 200


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def _covers_dir() -> Path:
    """封面保存目录：优先读配置 save_dir，否则 output/covers/YYYYMMDD/"""
    try:
        from backend.config.ai_config import get_config_manager
        cfg = get_config_manager().image_config
        d = (cfg.save_dir or '').strip()
        if d:
            p = Path(d)
            p.mkdir(parents=True, exist_ok=True)
            return p
    except Exception:
        pass
    base = _project_root() / 'output' / 'covers' / datetime.now().strftime('%Y%m%d')
    base.mkdir(parents=True, exist_ok=True)
    return base


def _history_file() -> Path:
    p = _project_root() / 'output' / 'covers'
    p.mkdir(parents=True, exist_ok=True)
    return p / 'history.json'


def _load_history():
    global _history
    try:
        f = _history_file()
        if f.exists():
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
                if isinstance(data, list):
                    _history = [x for x in data if isinstance(x, dict)][:_MAX_HISTORY]
                    return
    except Exception as e:
        logger.debug(f'读取封面历史失败: {e}')
    _history = []


def _persist_history():
    try:
        with open(_history_file(), 'w', encoding='utf-8') as f:
            json.dump(_history[:_MAX_HISTORY], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f'写入封面历史失败: {e}')


def _append_history(record: Dict[str, Any]):
    with _lock:
        _history.insert(0, record)
        if len(_history) > _MAX_HISTORY:
            del _history[_MAX_HISTORY:]
        _persist_history()


# =========================================================
# 尺寸表
# =========================================================
_SIZE_MAP: Dict[str, str] = {
    # —— 尺寸选择的三大原则：——
    # 1) W/H 均为 64 的倍数（Stable Diffusion / Flux 等 UNet 架构的最佳对齐）
    # 2) 尽量精确贴合所选比例（4:3 就真的是 4:3，不是 16:9 硬凑）
    # 3) 尽可能同时兼容 DALL-E3 仅支持的三档：1024×1024 / 1792×1024 / 1024×1792
    #    若某比例无法同时满足前两点（如 4:3），则优先「精确比例+64对齐」，
    #    DALL-E3 纯网关会就近落到支持的档位，不会再乱返 9:16。
    '16:9': '1792x1024',  # 横屏视频封面 · DALL-E3 原生支持
    '9:16': '1024x1792',  # 抖音/竖屏 · DALL-E3 原生支持
    '1:1':  '1024x1024',  # 正方形 · DALL-E3 原生支持
    '4:3':  '1536x1152',  # 普屏 4:3 · 精确比例 + 64 对齐（1536÷1152=4/3）
    '3:4':  '1152x1536',  # 竖屏 3:4 · 精确比例 + 64 对齐（1152÷1536=3/4）
    '21:9': '1792x768',   # 超宽屏 · 精确比例 + 64 对齐（1792÷768≈2.333=21/9）
}


def _resolve_size(size_str: Optional[str], fallback: str = '1024x1024') -> str:
    """把 16:9 / 9:16 或真实 1280x720 全部标准化为 WxH"""
    s = (size_str or '').strip()
    if not s:
        return fallback
    if re.fullmatch(r'\d+x\d+', s):
        return s
    if s in _SIZE_MAP:
        return _SIZE_MAP[s]
    # 允许 "16:9 · 横屏 1280×720" 这类带中文的复合值，从中提取 WxH
    m = re.search(r'(\d{2,5})[xX×](\d{2,5})', s)
    if m:
        return f'{m.group(1)}x{m.group(2)}'
    return fallback


def _size_to_ratio_label(size_str: str) -> Optional[str]:
    """把 WxH 反查回比例标签（16:9 / 4:3 等），用于网关 aspect_ratio 字段。
    若精确匹配不到就按浮点比例就近取一个。"""
    if not size_str:
        return None
    m = re.fullmatch(r'(\d{2,5})x(\d{2,5})', size_str.strip())
    if not m:
        # 本身就是 "4:3" 这种比例字符串，直接返回
        if re.fullmatch(r'\d{1,2}:\d{1,2}', size_str.strip()):
            return size_str.strip()
        return None
    w, h = int(m.group(1)), int(m.group(2))
    ratio = w / max(1, h)
    # 精确反向查 _SIZE_MAP
    for label, wxh in _SIZE_MAP.items():
        if wxh == f'{w}x{h}':
            return label
    # 就近匹配
    best: Optional[str] = None
    best_diff = 1e9
    for label, wxh in _SIZE_MAP.items():
        mw, mh = map(int, wxh.split('x'))
        mr = mw / max(1, mh)
        diff = abs(ratio - mr)
        if diff < best_diff:
            best_diff = diff
            best = label
    return best


def _probe_image_actual_size(url_or_rel: str) -> Optional[Tuple[int, int]]:
    """尝试读取本地保存图片的真实像素尺寸。读不到则返回 None，不抛异常。"""
    if not url_or_rel:
        return None
    try:
        # URL 可能是 /api/cover/file/xxx.jpg 或本地路径
        p: Optional[Path] = None
        if url_or_rel.startswith('/api/cover/file/'):
            rel = url_or_rel[len('/api/cover/file/'):].lstrip('/')
            p = _covers_dir() / rel
        elif os.path.isabs(url_or_rel):
            p = Path(url_or_rel)
        else:
            # 当作相对 covers 目录
            p = _covers_dir() / url_or_rel.lstrip('/')
        if p and p.exists():
            from PIL import Image as _PILImg
            with _PILImg.open(p) as im:
                return (int(im.size[0]), int(im.size[1]))
    except Exception as e:
        logger.debug(f'读取图片真实尺寸失败（不影响使用）: {url_or_rel[:80]} -> {e}')
    return None


# =========================================================
# 路由注册入口
# =========================================================
def register_cover_routes(app):
    """注册封面相关 API 路由（Blueprint + 静态文件）"""
    try:
        _load_history()
    except Exception:
        pass

    app.register_blueprint(cover_bp)

    # 静态封面文件访问：/api/cover/file/<relpath>
    # 避免把整个 output/ 暴露出去，只暴露 covers 子目录
    @app.route('/api/cover/file/<path:relpath>')
    def cover_serve_file(relpath):
        base = _project_root() / 'output' / 'covers'
        try:
            safe = (base / relpath).resolve()
            if not str(safe).startswith(str(base.resolve())):
                abort(404)
            if not safe.is_file():
                abort(404)
            return send_from_directory(str(base), relpath)
        except Exception:
            abort(404)

    logger.info('✅ 封面生成API路由注册完成（/api/cover/*）')


# =========================================================
# 帮助：统一请求 / 解析
# =========================================================
def _requests():
    import requests as _r
    return _r


def _save_bytes_as_image(b: bytes, suffix: str = '.png') -> str:
    """把图片字节保存到本地，返回相对 URL（/api/cover/file/xxx）"""
    fname = f'cover_{int(time.time())}_{uuid.uuid4().hex[:8]}{suffix}'
    out_path = _covers_dir() / fname
    with open(out_path, 'wb') as f:
        f.write(b)
    # 算出相对于 output/covers/ 的相对路径
    try:
        rel = out_path.relative_to(_project_root() / 'output' / 'covers')
    except Exception:
        rel = Path(fname)
    return f'/api/cover/file/{str(rel).replace(os.sep, "/")}'


def _save_b64_as_image(b64: str) -> str:
    b64 = (b64 or '').strip()
    if b64.startswith('data:'):
        b64 = b64.split(',', 1)[-1]
    raw = base64.b64decode(b64 + '=' * (-len(b64) % 4))
    # 猜格式
    suffix = '.png'
    if raw[:3] == b'\xff\xd8\xff':
        suffix = '.jpg'
    elif raw[:8] == b'\x89PNG\r\n\x1a\n':
        suffix = '.png'
    elif raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        suffix = '.webp'
    return _save_bytes_as_image(raw, suffix=suffix)


def _save_url_as_image(url: str, timeout: int = 30) -> str:
    r = _requests().get(url, timeout=timeout, stream=True)
    r.raise_for_status()
    ctype = (r.headers.get('Content-Type') or '').lower()
    suffix = '.png'
    if 'jpeg' in ctype or 'jpg' in ctype:
        suffix = '.jpg'
    elif 'webp' in ctype:
        suffix = '.webp'
    raw = r.content
    if not raw:
        raise RuntimeError('下载图片为空')
    return _save_bytes_as_image(raw, suffix=suffix)


# =========================================================
# 各家厂商实现
# =========================================================
def _generate_openai_compatible(conn: Dict[str, Any], prompt: str,
                                 size: str, n: int, quality: str,
                                 style: str, seed: Optional[int],
                                 cfg_scale: float = 7.0) -> List[str]:
    """OpenAI 兼容 /images/generations（支持 DALL-E / SD / Flux / Seedream / CogView 等）"""
    base = (conn['base_url'] or '').rstrip('/')
    key = conn.get('api_key') or ''
    model = conn.get('model') or ''
    if not base or not key:
        raise RuntimeError('缺少 Base URL 或 API Key')

    url = f'{base}/images/generations'
    headers = {
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
    }
    if conn.get('group_id'):
        headers['X-Flexflow-Group-ID'] = conn['group_id']

    # —— 尺寸参数：同时传 4 种格式，最大化各种网关/代理的兼容性 ——
    # 1) OpenAI 标准：size = "WxH"（DALL-E 系列、绝大多数兼容网关）
    # 2) width / height 整数（部分 SD/Flux 代理如 OneAPI / NewAPI / 各类自建站）
    # 3) aspect_ratio 比例标签（如 "4:3"，Flux、Stable Diffusion 3 等原生识别）
    try:
        size_clean = (size or '').strip() or '1024x1024'
        m = re.fullmatch(r'(\d{2,5})x(\d{2,5})', size_clean)
        if m:
            w_px, h_px = int(m.group(1)), int(m.group(2))
        else:
            w_px, h_px = 1024, 1024
    except Exception:
        w_px, h_px = 1024, 1024
    ratio_label = _size_to_ratio_label(size)

    payload: Dict[str, Any] = {
        'prompt': prompt,
        'n': int(n) or 1,
        'size': size,
        'width': w_px,
        'height': h_px,
    }
    if ratio_label:
        payload['aspect_ratio'] = ratio_label
    if model:
        payload['model'] = model
    # quality / style 仅 DALL-E 识别，其他厂商会忽略（不报错）
    if quality:
        payload['quality'] = quality
    if style:
        payload['style'] = style
    if seed is not None:
        payload['seed'] = int(seed)
    # CFG Scale：SD/Flux 等开源模型大都支持 guidance_scale 或 cfg_scale，两个都传
    try:
        cfgv = float(cfg_scale)
        if 0.5 <= cfgv <= 30.0 and abs(cfgv - 7.0) > 0.01:
            payload['cfg_scale'] = cfgv
            payload['guidance_scale'] = cfgv
    except Exception:
        pass

    # Flux/SD 等开源模型在部分代理不支持 n>1，此时自动降级循环单张生成
    # 我们先按原始 n 发；如果报错再 fallback。
    read_timeout = max(180, 90 * payload['n'])
    timeout = (15, read_timeout)
    requests_lib = _requests()
    logger.info(
        'OpenAI兼容图片生成请求: provider=%s model=%s n=%s size=%s read_timeout=%ss',
        conn.get('provider'), model, payload['n'], payload['size'], read_timeout,
    )
    try:
        request_started = time.time()
        try:
            r = requests_lib.post(url, headers=headers, json=payload, timeout=timeout)
        except requests_lib.exceptions.ReadTimeout as exc:
            raise RuntimeError(
                f'图片模型生成超过 {read_timeout} 秒，建议单张/较小尺寸或检查上游任务状态'
            ) from exc
        if 400 <= r.status_code < 500 and payload['n'] > 1:
            # 可能是不支持批量，降级成一张张发
            raise ValueError('batch_not_supported')
        r.raise_for_status()
        logger.info(
            'OpenAI兼容图片生成成功: status=%s elapsed=%.3fs',
            r.status_code, time.time() - request_started,
        )
        data = r.json() or {}
        results: List[str] = []
        for item in (data.get('data') or []):
            if isinstance(item, dict):
                if item.get('b64_json'):
                    results.append(_save_b64_as_image(item['b64_json']))
                elif item.get('url'):
                    try:
                        results.append(_save_url_as_image(item['url']))
                    except Exception as e:
                        logger.warning(f'下载封面失败，直接保存URL: {e}')
                        results.append(item['url'])
        if not results:
            raise RuntimeError(f'未返回图片: {json.dumps(data, ensure_ascii=False)[:500]}')
        return results
    except ValueError:
        # batch 降级
        out = []
        for _ in range(payload['n']):
            p2 = dict(payload); p2['n'] = 1
            logger.info(
                'OpenAI兼容图片生成请求: provider=%s model=%s n=%s size=%s read_timeout=%ss',
                conn.get('provider'), model, p2['n'], p2['size'], read_timeout,
            )
            request_started = time.time()
            try:
                r2 = requests_lib.post(url, headers=headers, json=p2, timeout=timeout)
            except requests_lib.exceptions.ReadTimeout as exc:
                raise RuntimeError(
                    f'图片模型生成超过 {read_timeout} 秒，建议单张/较小尺寸或检查上游任务状态'
                ) from exc
            r2.raise_for_status()
            logger.info(
                'OpenAI兼容图片生成成功: status=%s elapsed=%.3fs',
                r2.status_code, time.time() - request_started,
            )
            d2 = r2.json() or {}
            for item in (d2.get('data') or []):
                if isinstance(item, dict):
                    if item.get('b64_json'):
                        out.append(_save_b64_as_image(item['b64_json']))
                    elif item.get('url'):
                        try:
                            out.append(_save_url_as_image(item['url']))
                        except Exception:
                            out.append(item['url'])
        if not out:
            raise RuntimeError('批量降级后仍未返回图片')
        return out


def _generate_dashscope_qwen(conn: Dict[str, Any], prompt: str,
                              size: str, n: int, seed: Optional[int],
                              cfg_scale: float = 7.0) -> List[str]:
    """阿里云 DashScope：通义万相 wanx-v1 / wanx2.1-t2i-turbo 等
    文档：POST https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis
    """
    api_key = conn.get('api_key') or ''
    model = conn.get('model') or 'wanx-v1'
    if not api_key:
        raise RuntimeError('缺少阿里云 API Key')

    url = 'https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis'
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
        'X-DashScope-Async': 'enable',  # 异步任务
    }
    W, H = (size.split('x') + ['1024', '1024'])[:2]
    body = {
        'model': model,
        'input': {
            'prompt': prompt,
            # 通义万相的 size 不是必须，部分模型走单独参数
        },
        'parameters': {
            'size': f'{W}*{H}',
            'n': int(n) or 1,
        },
    }
    if seed is not None:
        body['parameters']['seed'] = int(seed)
    # CFG Scale：通义万相支持 guidance 或 cfg_scale，两个都传兜底
    try:
        cfgv = float(cfg_scale)
        if 0.5 <= cfgv <= 30.0 and abs(cfgv - 7.0) > 0.01:
            body['parameters']['cfg_scale'] = cfgv
            body['parameters']['guidance'] = cfgv
    except Exception:
        pass

    r = _requests().post(url, headers=headers, json=body, timeout=30)
    r.raise_for_status()
    data = r.json() or {}
    task_id = data.get('output', {}).get('task_id')
    if not task_id:
        # 同步返回（turbo模型）
        results: List[str] = []
        for item in (((data.get('output') or {}).get('results')) or []):
            if isinstance(item, dict) and item.get('url'):
                try:
                    results.append(_save_url_as_image(item['url']))
                except Exception:
                    results.append(item['url'])
        if results:
            return results
        raise RuntimeError(f'通义万相返回异常: {json.dumps(data, ensure_ascii=False)[:500]}')

    # 异步轮询
    poll_url = f'https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}'
    total_wait = 180
    step = 5
    for _ in range(0, total_wait, step):
        time.sleep(step)
        pr = _requests().get(poll_url, headers={'Authorization': f'Bearer {api_key}'}, timeout=20)
        pr.raise_for_status()
        pd = pr.json() or {}
        status = ((pd.get('output') or {}).get('task_status')) or pd.get('output', {}).get('task_metrics', {}).get('TOTAL')
        s = str(pd.get('output', {}).get('task_status') or '').upper()
        if s in ('SUCCEEDED', 'SUCCEED'):
            out: List[str] = []
            for item in ((pd.get('output') or {}).get('results') or []):
                if isinstance(item, dict) and item.get('url'):
                    try:
                        out.append(_save_url_as_image(item['url']))
                    except Exception:
                        out.append(item['url'])
            if not out:
                raise RuntimeError('通义万相任务成功但未返回图片')
            return out
        if s in ('FAILED', 'FAIL', 'CANCELED'):
            msg = (pd.get('output') or {}).get('message') or json.dumps(pd, ensure_ascii=False)[:300]
            raise RuntimeError(f'通义万相任务失败: {msg}')
    raise RuntimeError('通义万相任务超时')


def _generate_baidu(conn: Dict[str, Any], prompt: str, size: str, n: int,
                    seed: Optional[int], cfg_scale: float = 7.0) -> List[str]:
    """百度 文心一格 / AI 绘画 3.0：先拿 token 再提交任务，再轮询结果。"""
    ak = conn.get('api_key') or ''
    sk = conn.get('secret_key') or ''
    model = conn.get('model') or ''
    if not ak or not sk:
        raise RuntimeError('缺少百度 API Key / Secret Key')

    # Step 1: token
    tok_r = _requests().post(
        'https://aip.baidubce.com/oauth/2.0/token',
        params={'grant_type': 'client_credentials', 'client_id': ak, 'client_secret': sk},
        timeout=20,
    )
    tok_r.raise_for_status()
    token = (tok_r.json() or {}).get('access_token')
    if not token:
        raise RuntimeError('获取百度 access_token 失败')

    W, H = (size.split('x') + ['1024', '1024'])[:2]
    params = {
        'access_token': token,
    }
    body = {
        'prompt': prompt,
        'width': int(W),
        'height': int(H),
        'image_num': int(n) or 1,
    }
    if seed is not None:
        body['seed'] = int(seed)
    # CFG Scale：百度各版本接口名不一致，尽量全覆盖
    try:
        cfgv = float(cfg_scale)
        if 0.5 <= cfgv <= 30.0 and abs(cfgv - 7.0) > 0.01:
            body['cfg_scale'] = cfgv
            body['cfg'] = cfgv
            body['guidance'] = cfgv
    except Exception:
        pass
    # 百度不同版本路径不同；优先走「AI 绘画（ChatGLM 风格）」的 V1
    submit_url = 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/text2image/' + (model or 'sanguo')
    try:
        r = _requests().post(submit_url, params=params, json=body, timeout=30)
        if r.status_code >= 400:
            # fallback: 通用 AI 绘画 V2
            submit_url2 = 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/plugin/wenxin_drawing'
            r = _requests().post(submit_url2, params=params, json=body, timeout=30)
            r.raise_for_status()
    except Exception:
        raise

    data = r.json() or {}
    # 百度部分接口同步返回 img_url 列表，部分异步（task_id）
    urls: List[str] = []
    for it in (data.get('data') or data.get('img_urls') or []):
        if isinstance(it, dict) and it.get('url') or isinstance(it, str):
            u = it['url'] if isinstance(it, dict) else it
            try:
                urls.append(_save_url_as_image(u))
            except Exception:
                urls.append(u)
    if urls:
        return urls
    task_id = data.get('id') or data.get('taskId') or data.get('task_id')
    if not task_id:
        raise RuntimeError(f'百度生图返回异常: {json.dumps(data, ensure_ascii=False)[:500]}')
    raise RuntimeError(f'百度生图异步轮询暂未实现，task_id={task_id}')


def _generate_tencent(conn: Dict[str, Any], prompt: str, size: str, n: int,
                      cfg_scale: float = 7.0) -> List[str]:
    """腾讯混元生图（这里只占位：签名逻辑需要 tencentcloud-sdk-python 依赖，
    未装 SDK 时给出清晰错误 + fallback 到本地模板，避免功能不可用）"""
    sid = conn.get('secret_id') or ''
    skey = conn.get('secret_key') or ''
    if not sid or not skey:
        raise RuntimeError('缺少腾讯 SecretId / SecretKey')
    try:
        from tencentcloud.common import credential
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.tiia.v20190529 import tiia_client, models
    except Exception as e:
        raise RuntimeError(
            f'未安装腾讯云 SDK（pip install tencentcloud-sdk-python）：{e}'
        )
    cred = credential.Credential(sid, skey)
    hp = HttpProfile(); hp.endpoint = 'tiia.tencentcloudapi.com'
    cp = ClientProfile(httpProfile=hp)
    client = tiia_client.TiiaClient(cred, 'ap-beijing', cp)
    # 注意：混元生图的实际 action 和 model 需要按腾讯云最新文档选择
    # （如 EnhanceImage / 其他图像合成接口），这里抛错让外层走 fallback
    raise RuntimeError('腾讯混元生图模型接口待按最新文档接入，当前自动切换到本地模板')


# =========================================================
# 本地 fallback：高可读文字 + 渐变 + 装饰图形
# =========================================================
_FONT_CANDIDATES = [
    # 优先使用项目内置字体
]


def _builtin_fonts_dir() -> Path:
    return _project_root() / 'backend' / 'assets' / 'fonts'


def _pick_font(size: int = 48, bold: bool = True):
    """优先用项目字体目录下的中文黑体/粗体，找不到就退回系统默认。"""
    from PIL import ImageFont
    builtin = _builtin_fonts_dir()
    cands: List[Path] = []
    if builtin.exists():
        # 优先粗体 / 黑体类
        prefer = ['思源', 'HanYiChao', '字魂金榜', '字魂龙腾', '尔雅', '思源宋体-Bold']
        for p in sorted(builtin.iterdir()):
            if p.suffix.lower() in ('.ttf', '.otf', '.ttc'):
                score = sum(1 for kw in prefer if kw in p.name)
                cands.append((score, p))
        cands.sort(key=lambda x: -x[0])
    for _, p in cands:
        try:
            return ImageFont.truetype(str(p), size=size)
        except Exception:
            continue
    # 系统字体兜底
    for name in ('msyhbd.ttc', 'msyh.ttc', 'simhei.ttf', 'simsun.ttc',
                 'PingFang.ttc', 'Hiragino Sans GB.ttc', 'Arial Unicode.ttf',
                 'NotoSansCJK-Bold.ttc', 'DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def _wrap_text(font, text: str, max_width_px: int) -> List[str]:
    lines: List[str] = []
    cur = ''
    for ch in text:
        test = cur + ch
        try:
            w = font.getlength(test)
        except Exception:
            w = len(test) * (font.size or 16) * 0.6
        if w > max_width_px and cur:
            lines.append(cur); cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def _gradient(w: int, h: int, colors: List[tuple]):
    from PIL import Image
    if len(colors) < 2:
        c = colors[0] if colors else (20, 30, 60)
        return Image.new('RGB', (w, h), c)
    img = Image.new('RGB', (w, h))
    px = img.load()
    n = len(colors) - 1
    for y in range(h):
        t = y / max(h - 1, 1)
        idx = min(n - 1, int(t * n))
        tt = (t * n) - idx
        c1, c2 = colors[idx], colors[min(idx + 1, len(colors) - 1)]
        r = int(c1[0] + (c2[0] - c1[0]) * tt)
        g = int(c1[1] + (c2[1] - c1[1]) * tt)
        b = int(c1[2] + (c2[2] - c1[2]) * tt)
        for x in range(w):
            px[x, y] = (r, g, b)
    return img


def _generate_fallback(prompt: str, size: str, n: int, styles: List[str],
                       seed: Optional[int], cfg_scale: float = 7.0) -> List[str]:
    """本地模板生成：当云端不可用或用户未配置密钥时，立刻返回可用的封面。
    cfg_scale > 7：色彩更饱和、对比更强、细节更锐（越贴合 prompt）
    cfg_scale < 7：色彩更淡、对比更柔、风格更保守
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
    W, H = map(int, (_resolve_size(size).split('x')))
    if seed is not None:
        import random as _r; _r.seed(int(seed))

    palette = [
        [(15, 23, 42), (79, 70, 229), (236, 72, 153)],   # 靛蓝粉紫
        [(12, 74, 110), (6, 182, 212), (34, 211, 238)],   # 赛博青蓝
        [(29, 17, 59), (124, 58, 237), (251, 191, 36)],   # 紫金撞色
        [(127, 29, 29), (220, 38, 38), (252, 211, 77)],   # 红金电影感
        [(19, 78, 74), (16, 185, 129), (45, 212, 191)],   # 翡翠青绿
        [(120, 53, 15), (249, 115, 22), (254, 240, 138)],  # 暖橙落日
        [(76, 5, 25), (236, 72, 153), (56, 189, 248)],    # 品红电蓝
        [(4, 120, 87), (16, 185, 129), (134, 239, 172)],  # 清爽墨绿
    ]
    # 关键词抽取（前 8~12 字作为主标题）
    text = (prompt or '').strip() or 'JJYB 智能视频封面'
    # 去除常见英文prompt尾缀，让标题更干净
    text = re.sub(r'(?i)(\b(masterpiece|best quality|4k|8k|hd|ultra detailed|cinematic|highly detailed)\b[,\s]*)+', '', text).strip()
    title = text[:14] if len(text) <= 14 else (text[:12] + '…')
    sub = text if len(text) <= 28 else (text[:26] + '…')

    has_cyber = any(k in str(styles) for k in ('赛博', 'cyber', '科技', '霓虹', '电竞', '游戏'))
    has_movie = any(k in str(styles) for k in ('电影', 'cinema', '质感', '光影'))
    has_ink = any(k in str(styles) for k in ('国风', '水墨', '水墨'))
    has_3d = any(k in str(styles) for k in ('3D', '卡通'))

    # 根据创意度 CFG 计算色彩/对比/锐度强度
    try:
        cfg_ratio = float(cfg_scale) / 7.0
    except Exception:
        cfg_ratio = 1.0
    if cfg_ratio > 1.0:
        # CFG 大于 7：越激进
        color_fac    = min(2.2, 1.0 + (cfg_ratio - 1.0) * 0.45)
        contrast_fac = min(2.0, 1.0 + (cfg_ratio - 1.0) * 0.35)
        sharp_fac    = min(3.0, 1.0 + (cfg_ratio - 1.0) * 0.7)
    elif cfg_ratio < 1.0:
        # CFG 小于 7：越柔和
        color_fac    = 0.55 + 0.45 * cfg_ratio
        contrast_fac = 0.65 + 0.35 * cfg_ratio
        sharp_fac    = 0.75 + 0.25 * cfg_ratio
    else:
        color_fac = contrast_fac = sharp_fac = 1.0

    urls: List[str] = []
    for i in range(max(1, int(n))):
        colors = palette[i % len(palette)]
        if has_ink:
            colors = [(30, 30, 30), (80, 55, 35), (245, 240, 225)]
        if has_cyber:
            colors = [(3, 7, 18), (46, 7, 88), (6, 182, 212)]
        if has_movie:
            colors = [(8, 8, 12), (127, 29, 29), (251, 191, 36)]
        base = _gradient(W, H, colors)

        # 加一层 vignette 暗角
        import numpy as np
        arr = np.array(base).astype(np.float32)
        Y, X = np.ogrid[:H, :W]
        cx, cy = W / 2, H / 2
        dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
        maxd = np.sqrt(cx ** 2 + cy ** 2)
        vig = 1 - np.clip((dist / maxd - 0.3) / 0.7, 0, 1) ** 0.7
        arr[:, :, 0] *= vig
        arr[:, :, 1] *= vig
        arr[:, :, 2] *= vig
        base = Image.fromarray(arr.astype(np.uint8))

        draw = ImageDraw.Draw(base, 'RGBA')

        # 装饰矩形条（左侧色带）
        bar_w = max(8, int(W * 0.012))
        draw.rectangle([int(W * 0.06), int(H * 0.22), int(W * 0.06) + bar_w, int(H * 0.78)],
                       fill=(255, 255, 255, 230))

        # 标签芯片（右上）
        tag = 'JJYB COVER'
        if has_3d: tag = '3D · 卡通'
        if has_ink: tag = '国风水墨'
        if has_cyber: tag = 'CYBER TECH'
        if has_movie: tag = 'CINEMATIC'
        from PIL import ImageFont
        tag_font = _pick_font(max(14, int(H * 0.022)), bold=True) or ImageFont.load_default()
        tag_w = tag_font.getlength(tag) if hasattr(tag_font, 'getlength') else len(tag) * 16
        tx1, ty1 = int(W * 0.94 - tag_w - 24), int(H * 0.06)
        draw.rounded_rectangle([tx1, ty1, tx1 + tag_w + 24, ty1 + int(H * 0.044)],
                               radius=999, fill=(0, 0, 0, 160), outline=(255, 255, 255, 60), width=1)
        draw.text((tx1 + 12, ty1 + 6), tag, font=tag_font, fill=(255, 255, 255, 235))

        # 主标题 + 副标题
        title_font = _pick_font(max(36, int(H * 0.105)), bold=True) or ImageFont.load_default()
        sub_font = _pick_font(max(18, int(H * 0.046)), bold=False) or ImageFont.load_default()

        max_w = int(W * 0.80)
        title_lines = _wrap_text(title_font, title, max_w)[:2]
        sub_lines = _wrap_text(sub_font, sub, max_w)[:2]

        # 垂直居中偏下
        line_h_title = int(getattr(title_font, 'size', 48) * 1.25)
        line_h_sub = int(getattr(sub_font, 'size', 22) * 1.45)
        block_h = line_h_title * len(title_lines) + 16 + line_h_sub * len(sub_lines)
        y0 = int(H * 0.55 - block_h / 2)
        x0 = int(W * 0.10)

        # 标题半透明底板（提升可读性）
        pad_x, pad_y = 18, 14
        bx = x0 - pad_x
        by = y0 - pad_y
        bw = max(
            max((title_font.getlength(l) if hasattr(title_font, 'getlength') else len(l) * 40) for l in title_lines),
            max((sub_font.getlength(l) if hasattr(sub_font, 'getlength') else len(l) * 22) for l in sub_lines),
        ) + pad_x * 2
        bh = block_h + pad_y * 2
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=22, fill=(0, 0, 0, 140))

        y = y0
        for ln in title_lines:
            draw.text((x0 + 2, y + 2), ln, font=title_font, fill=(0, 0, 0, 120))
            draw.text((x0, y), ln, font=title_font, fill=(255, 255, 255, 255))
            y += line_h_title
        y += 8
        for ln in sub_lines:
            draw.text((x0, y), ln, font=sub_font, fill=(232, 236, 244, 235))
            y += line_h_sub

        # 底部 JJYB 水印
        wm_font = _pick_font(max(14, int(H * 0.026)), bold=True) or ImageFont.load_default()
        wm = 'JJYB  AI  智  剪'
        draw.text((int(W * 0.10), int(H * 0.92 - (getattr(wm_font, 'size', 16)))),
                  wm, font=wm_font, fill=(255, 255, 255, 170))

        # 可选：轻微模糊让画面更柔和
        try:
            base = base.filter(ImageFilter.GaussianBlur(radius=0.6))
        except Exception:
            pass

        # 创意度 CFG：调整饱和度/对比度/锐度（最关键的视觉效果应用！）
        try:
            if abs(color_fac - 1.0) > 0.001:
                base = ImageEnhance.Color(base).enhance(color_fac)
            if abs(contrast_fac - 1.0) > 0.001:
                base = ImageEnhance.Contrast(base).enhance(contrast_fac)
            if abs(sharp_fac - 1.0) > 0.001:
                base = ImageEnhance.Sharpness(base).enhance(sharp_fac)
        except Exception as e:
            logger.warning(f'fallback 封面应用 CFG 创意度调整失败，跳过: {e}')

        # 保存
        buf = io.BytesIO()
        base.convert('RGB').save(buf, format='JPEG', quality=92)
        urls.append(_save_bytes_as_image(buf.getvalue(), suffix='.jpg'))

    return urls


# =========================================================
# 统一派发
# =========================================================
def _is_masked_secret(value) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    return set(text) == {'*'} or '****' in text or (len(text) >= 8 and text.count('*') / len(text) >= 0.30)


def _dispatch(provider: str, prompt: str, size: str, n: int,
              quality: str, style: str, seed: Optional[int],
              styles: List[str], cfg_scale: float = 7.0
              ) -> Tuple[List[str], str, Optional[str]]:
    """统一派发封面生成请求。

    返回:
        (urls, actually_used_provider, fallback_reason)
        actually_used_provider: 实际使用的厂商（custom_openai/siliconflow/local_fallback 等）
        fallback_reason: 若走了 fallback（本地模板），这里给出原因；云端成功时为 None
    """
    from backend.config.ai_config import get_config_manager
    cm = get_config_manager()
    conn = cm.get_image_connection(provider)
    norm = cm.normalize_image_provider(provider)

    if any(_is_masked_secret(value) for value in (
        conn.get('api_key'), conn.get('secret_id'), conn.get('secret_key')
    )):
        reason = '图片专属密钥是掩码污染值、真实Key无法恢复、需图片区重新输入并保存'
        logger.warning(f'[cover_api] 图像模型密钥已被掩码污染，走本地模板: provider={norm}')
        return _generate_fallback(prompt, size, n, styles, seed, cfg_scale), 'local_fallback', reason

    # 先检查有没有配置密钥：没配的直接走 fallback，但明确记录原因
    has_key = bool(conn.get('api_key') or conn.get('secret_id'))
    if not has_key:
        reason = (f'缺少 {norm or provider} 的 API Key / SecretId / SecretKey '
                  f'（请在设置页 → API 配置 → 图片生成模型 / 自定义 OpenAI 兼容 图像版 填好密钥并保存）')
        logger.warning(f'[cover_api] 未配置图像模型密钥，走本地模板: {reason}')
        return _generate_fallback(prompt, size, n, styles, seed, cfg_scale), 'local_fallback', reason

    real_size = _resolve_size(size, conn.get('default_size') or '1024x1024')
    quality = quality or conn.get('default_quality') or 'standard'
    style = style or conn.get('default_style') or ''
    n = int(n or conn.get('default_n') or 1)

    # 调试：把取到的密钥特征（前 8 + 后 3 位）+ 实际发送的尺寸打日志，方便排查"选了4:3却拿到9:16"
    try:
        raw_key = conn.get('api_key') or conn.get('secret_id') or ''
        s = str(raw_key)
        if len(s) >= 12:
            preview = s[:8] + '*' * (len(s) - 11) + s[-3:]
        elif len(s) > 0:
            preview = '*' * len(s)
        else:
            preview = '(EMPTY!)'
        base = (conn.get('base_url') or '(无 Base URL)')
        ratio_tag = _size_to_ratio_label(size) or ''
        if ratio_tag:
            ratio_tag = f' (比例标签 {ratio_tag})'
        logger.info(
            '[cover_api] 图像生成派发: provider=%s, base_url=%s, model=%s, key=%s, '
            '前端原始size="%s"%s → 请求体size=%s (W×H=%s × %s, aspect_ratio=%s, n=%s)',
            norm, base, conn.get('model') or '(空)', preview,
            size, ratio_tag, real_size,
            real_size.split('x')[0], real_size.split('x')[-1],
            _size_to_ratio_label(real_size) or '-', n,
        )
    except Exception:
        pass

    errors: List[str] = []
    # 1) OpenAI 兼容一大票
    if norm in ('openai', 'siliconflow', 'openrouter', 'doubao', 'chatglm',
                'custom_openai', 'minimax'):
        try:
            urls = _generate_openai_compatible(conn, prompt, real_size, n, quality, style, seed, cfg_scale)
            if urls:
                return urls, norm, None
            errors.append(f'{norm}: 未返回图片 URL')
        except Exception as e:
            errors.append(f'{norm}: {e}')
    # 2) 阿里云通义万相
    if norm == 'qwen':
        try:
            urls = _generate_dashscope_qwen(conn, prompt, real_size, n, seed, cfg_scale)
            if urls:
                return urls, norm, None
            errors.append('qwen: 未返回图片 URL')
        except Exception as e:
            errors.append(f'qwen: {e}')
    # 3) 百度
    if norm == 'baidu':
        try:
            urls = _generate_baidu(conn, prompt, real_size, n, seed, cfg_scale)
            if urls:
                return urls, norm, None
            errors.append('baidu: 未返回图片 URL')
        except Exception as e:
            errors.append(f'baidu: {e}')
    # 4) 腾讯
    if norm == 'tencent':
        try:
            urls = _generate_tencent(conn, prompt, real_size, n, cfg_scale)
            if urls:
                return urls, norm, None
            errors.append('tencent: 未返回图片 URL')
        except Exception as e:
            errors.append(f'tencent: {e}')

    # 全部失败：fallback 兜底 + 记录日志 + 明确告诉前端失败原因
    err_summary = ' | '.join(errors) if errors else '未知错误'
    logger.warning(f'[cover_api] 云端生图全部失败，切换本地模板兜底: {err_summary}')
    return (
        _generate_fallback(prompt, real_size, n, styles, seed, cfg_scale),
        'local_fallback',
        f'云端厂商 {norm} 请求失败: {err_summary}'
    )


# =========================================================
# HTTP 路由
# =========================================================
@cover_bp.route('/generate', methods=['POST'])
def cover_generate():
    """生成封面
    Body:
      - prompt: str        封面文案 / 主题 / Prompt
      - provider: str       厂商标识（可选，默认读配置 default_model）
      - size:   str         "16:9" / "9:16" / "1:1" / "1280x720"
      - count / n: int      生成数量 1~9
      - quality: str        standard / hd（仅 DALL-E 有效）
      - style: str          vivid / natural
      - styles: [str]       风格标签（电影感/3D卡通/国风 等，fallback 模板使用）
      - seed: int
      - cfg_scale: float    创意度 / CFG Scale（1.0~20.0，默认 7.0，越大色彩越饱和、细节越强、越贴合 prompt）
    """
    t0 = time.time()
    try:
        data = request.get_json() or {}
        prompt = (data.get('prompt') or data.get('text') or '').strip()
        if not prompt:
            return jsonify({'code': 1, 'msg': '缺少封面主题 / Prompt', 'data': None}), 400
        provider = (data.get('provider') or '').strip() or None
        size = (data.get('size') or '').strip()
        n = max(1, min(9, int(data.get('count') or data.get('n') or 4)))
        quality = (data.get('quality') or '').strip()
        style = (data.get('style') or '').strip()
        styles = data.get('styles') or []
        if isinstance(styles, str):
            styles = [s for s in re.split(r'[\s,，、|]+', styles) if s]
        # 创意度 CFG Scale：1~20，默认 7.0
        cfg_scale = 7.0
        try:
            raw_cfg = data.get('cfg_scale')
            if raw_cfg not in (None, ''):
                v = float(raw_cfg)
                if 0.5 <= v <= 30.0:
                    cfg_scale = v
        except Exception:
            cfg_scale = 7.0
        seed = data.get('seed')
        if seed in (None, ''):
            seed = None
        else:
            try:
                seed = int(seed)
            except Exception:
                seed = None

        # provider 缺省 → 从配置拿默认的；仍为空则直接走 fallback（兜底模板一定可用）
        if not provider:
            try:
                from backend.config.ai_config import get_config_manager
                cm = get_config_manager()
                try:
                    provider = cm.get_image_default_provider() or None
                except Exception:
                    provider = None
                    if hasattr(cm, 'get_config'):
                        cfg = cm.get_config() or {}
                        img_cfg = cfg.get('image') or cfg.get('image_config') or {}
                        provider = img_cfg.get('default_model') or img_cfg.get('default_provider') or None
            except Exception:
                provider = None
        # 如果仍无 provider（说明后端根本没配置任何图像模型）→ 直接 fallback 兜底，不抛错
        if not provider:
            fallback_reason = '后端未配置任何图像默认模型（请在设置页 → API 配置 → 图片生成模型 → 设置默认厂商并保存配置）'
            try:
                urls = _generate_fallback(prompt, size, n, styles or [], seed, cfg_scale)
            except Exception as e:
                logger.error(f'无 provider 时 fallback 封面生成也失败: {e}', exc_info=True)
                return jsonify({'code': 1, 'msg': f'生成失败: {e}', 'data': None}), 500
            dt = round(time.time() - t0, 2)
            # ========== 尺寸链路校验 ==========
            resolved_size = _resolve_size(size, '1024x1024')
            requested_size = (size or '').strip() or '(未传)'
            ratio_label = _size_to_ratio_label(requested_size) or _size_to_ratio_label(resolved_size)
            actual_sizes: List[List[int]] = []
            for u in urls:
                s = _probe_image_actual_size(u)
                actual_sizes.append([s[0], s[1]] if s else [0, 0])
            all_match = True
            try:
                mw, mh = map(int, resolved_size.split('x'))
                target_ratio = mw / max(1, mh)
                for (aw, ah) in actual_sizes:
                    if aw and ah and abs((aw / max(1, ah)) - target_ratio) > 0.07:
                        all_match = False
                        break
            except Exception:
                all_match = False
            try:
                logger.info(
                    '[尺寸链路] 用户选择="%s"%s → resolved=%s → 本地模板像素=[%s] → 比例一致=%s',
                    requested_size,
                    f'(比例标签 {ratio_label})' if ratio_label else '',
                    resolved_size,
                    ', '.join(f'{w}×{h}' if w and h else '未知' for (w, h) in actual_sizes),
                    '✅' if all_match else '❌',
                )
            except Exception:
                pass
            # =================================
            rec = {
                'id': f'cv_{int(t0)}_{uuid.uuid4().hex[:6]}',
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'provider': 'local_fallback',
                'prompt': prompt[:400],
                'size': resolved_size,
                'requested_size': requested_size,
                'actual_sizes': actual_sizes,
                'size_match': all_match,
                'n': len(urls),
                'urls': urls,
                'seed': seed,
                'styles': styles,
                'cfg_scale': cfg_scale,
                'time_s': dt,
            }
            _append_history(rec)
            return jsonify({
                'code': 0,
                'msg': f'本地模板生成完成（后端未配置图像模型），{len(urls)} 张 · 耗时 {dt}s · CFG={cfg_scale:.1f}。⚠️ {fallback_reason}',
                'data': {
                    'urls': urls,
                    'time_s': dt,
                    'count': len(urls),
                    'size': resolved_size,
                    'requested_size': requested_size,
                    'ratio_label': ratio_label,
                    'actual_sizes': actual_sizes,
                    'all_size_match': all_match,
                    'provider': 'local_fallback',
                    'actually_used_provider': 'local_fallback',
                    'fallback_reason': fallback_reason,
                    'cfg_scale': cfg_scale,
                    'styles': styles,
                    'history_id': rec['id'],
                }
            })

        actually_used_provider = ''
        fallback_reason: Optional[str] = None
        try:
            urls, actually_used_provider, fallback_reason = _dispatch(
                provider, prompt, size, n, quality, style, seed, styles, cfg_scale
            )
        except Exception as e:
            logger.warning(f'封面生成派发异常，启用兜底: {e}')
            urls = _generate_fallback(prompt, size, n, styles or [], seed, cfg_scale)
            actually_used_provider = 'local_fallback'
            fallback_reason = f'内部派发异常: {e}'

        dt = round(time.time() - t0, 2)
        # ========== 尺寸一致性校验：请求 → resolved → 实际像素 ==========
        resolved_size = _resolve_size(size, '1024x1024')
        requested_size = (size or '').strip() or '(未传)'
        ratio_label = _size_to_ratio_label(requested_size) or _size_to_ratio_label(resolved_size)
        actual_sizes: List[List[int]] = []
        for u in urls:
            s = _probe_image_actual_size(u)
            actual_sizes.append([s[0], s[1]] if s else [0, 0])
        # 按比例判断是否匹配（不看绝对像素数，看宽高比浮点偏差是否<7%）
        all_match = True
        try:
            mw, mh = map(int, resolved_size.split('x'))
            target_ratio = mw / max(1, mh)
            for (aw, ah) in actual_sizes:
                if aw and ah:
                    if abs((aw / max(1, ah)) - target_ratio) > 0.07:
                        all_match = False
                        break
        except Exception:
            all_match = False
        try:
            parts = [f'[尺寸链路] 用户选择="{requested_size}"']
            if ratio_label: parts.append(f'(比例标签 {ratio_label})')
            parts.append(f'→ resolved={resolved_size}')
            parts.append('→ 实际图片像素=[' +
                         ', '.join(f'{w}×{h}' if w and h else '未知'
                                   for (w, h) in actual_sizes) + ']')
            parts.append('→ 比例一致=' + ('✅' if all_match else '❌(网关未按指定尺寸返回，请检查模型是否支持该尺寸或改选其他尺寸按钮)'))
            logger.info(' '.join(parts))
        except Exception:
            pass
        # =====================================================================
        # 记录历史
        try:
            from backend.config.ai_config import get_config_manager
            norm = get_config_manager().normalize_image_provider(provider)
        except Exception:
            norm = ''
        rec = {
            'id': f'cv_{int(t0)}_{uuid.uuid4().hex[:6]}',
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'provider': norm or provider,
            'actually_used_provider': actually_used_provider,
            'fallback_reason': fallback_reason,
            'prompt': prompt[:400],
            'size': resolved_size,
            'requested_size': requested_size,
            'actual_sizes': actual_sizes,
            'size_match': all_match,
            'n': len(urls),
            'urls': urls,
            'seed': seed,
            'styles': styles,
            'cfg_scale': cfg_scale,
            'time_s': dt,
        }
        _append_history(rec)

        if fallback_reason:
            msg = (f'⚠️ 实际使用【本地模板兜底】，没有走 {provider} 模型。原因：{fallback_reason}。'
                   f'共 {len(urls)} 张 · 耗时 {dt}s · CFG={cfg_scale:.1f}')
        else:
            msg = (f'✅ 真实调用【{actually_used_provider}】云端生成完成，{len(urls)} 张 · 耗时 {dt}s · CFG={cfg_scale:.1f}'
                   + ('' if all_match else ' · ⚠️ 图片实际比例与选择的 {0} 不一致（网关侧可能不支持该尺寸，建议改选 16:9 / 9:16 / 1:1）'.format(requested_size)))
        return jsonify({
            'code': 0,
            'msg': msg,
            'data': {
                'urls': urls,
                'time_s': dt,
                'count': len(urls),
                'size': resolved_size,
                'requested_size': requested_size,
                'ratio_label': ratio_label,
                'actual_sizes': actual_sizes,       # 每张图真实宽高 [[W,H],...]
                'all_size_match': all_match,        # 是否都跟选择的尺寸比例一致
                'provider': rec['provider'],
                'actually_used_provider': actually_used_provider,
                'fallback_reason': fallback_reason,
                'cfg_scale': cfg_scale,
                'styles': styles,
                'history_id': rec['id'],
            }
        })
    except Exception as e:
        logger.error(f'生成封面失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'生成失败: {e}', 'data': None}), 500


@cover_bp.route('/history', methods=['GET'])
def cover_history():
    """获取最近封面历史（GET limit=50）"""
    limit = max(1, min(200, int(request.args.get('limit', 50))))
    with _lock:
        data = list(_history[:limit])
    # 返回格式兼容：items/list/records 三个字段都指向同一数组，total 为总数
    # 避免不同前端实现因字段名不同取不到列表
    return jsonify({
        'code': 0,
        'msg': 'ok',
        'data': {
            'total': len(_history),
            'items': data,
            'list': data,
            'records': data,
        },
        # 顶层兜底：老代码若直接读 r.items/r.list 也能命中
        'items': data,
        'list': data,
    })


@cover_bp.route('/delete', methods=['POST'])
def cover_delete():
    """删除封面历史记录（按 id 删除最精确，同时删除磁盘上的图片文件）。

    请求 JSON 字段（任一命中即可，优先级 id > created_at > urls）：
    - id: str             推荐：封面历史记录的唯一 id（形如 cv_{ts}_{rand6}）
    - created_at: str     精确匹配 created_at 时间
    - urls: list[str]     匹配 urls 数组完全相等
    """
    try:
        data = request.get_json() or {}
        target_id = str(data.get('id', '') or '').strip()
        target_created_at = str(data.get('created_at', '') or '').strip()
        target_urls = data.get('urls', None)

        if not target_id and not target_created_at and not target_urls:
            return jsonify({'code': 1, 'msg': '缺少删除条件（请传入 id / created_at / urls 之一）'}), 400

        with _lock:
            matched_idx = -1
            matched_rec: Optional[Dict[str, Any]] = None
            for i, rec in enumerate(_history):
                if not isinstance(rec, dict):
                    continue
                if target_id and str(rec.get('id', '') or '') == target_id:
                    matched_idx, matched_rec = i, rec
                    break
                if matched_idx < 0 and target_created_at and str(rec.get('created_at', '') or '') == target_created_at:
                    matched_idx, matched_rec = i, rec
                    break
                if matched_idx < 0 and target_urls:
                    rec_urls = rec.get('urls', [])
                    if isinstance(rec_urls, list) and isinstance(target_urls, list) and rec_urls == target_urls:
                        matched_idx, matched_rec = i, rec
                        break

            if matched_idx < 0 or not matched_rec:
                return jsonify({'code': 1, 'msg': '未找到匹配的封面记录（id=' + target_id + '）'}), 404

            removed = _history.pop(matched_idx)
            urls_to_delete = removed.get('urls', []) if isinstance(removed, dict) else []

            # 删除磁盘上的图片文件（只处理本项目输出目录下的本地文件，不删除网络URL）
            deleted_files = 0
            for url in urls_to_delete or []:
                u = str(url or '')
                if u.startswith('http://') or u.startswith('https://') or u.startswith('blob:') or u.startswith('data:'):
                    continue
                try:
                    # 把本地 URL 转换成绝对路径，并限制在封面输出目录内
                    candidate = None
                    covers_base = (_project_root() / 'output' / 'covers').resolve()
                    if u.startswith('/api/cover/file/'):
                        rest = u[len('/api/cover/file/'):]
                        candidate = covers_base / rest
                    elif u.startswith('/static/'):
                        rest = u[len('/static/'):]
                        candidate = Path(current_app.static_folder) / rest
                    elif u.startswith('/'):
                        candidate = Path(current_app.root_path).parent / u.lstrip('/')
                    else:
                        candidate = covers_base / u
                    if candidate:
                        candidate = candidate.resolve()
                        try:
                            candidate.relative_to(covers_base)
                        except ValueError:
                            continue
                    if candidate and candidate.exists() and candidate.is_file():
                        try:
                            candidate.unlink()
                            deleted_files += 1
                        except Exception as ex:
                            logger.warning(f'删除封面图片 {candidate} 失败: {ex}')
                except Exception as ex2:
                    logger.warning(f'处理封面图片路径失败: {ex2}')

            _persist_history()

        return jsonify({
            'code': 0,
            'msg': f'删除成功（删除了{deleted_files}个本地图片文件）',
            'data': {'deleted_files': deleted_files, 'remaining': len(_history)},
        })
    except Exception as e:
        logger.error(f'❌ /api/cover/delete 失败: {e}', exc_info=True)
        return jsonify({'code': 1, 'msg': f'删除失败: {e}'}), 500


@cover_bp.route('/history/clear', methods=['POST'])
def cover_history_clear():
    """清空历史记录（不清文件）"""
    with _lock:
        _history.clear()
        _persist_history()
    return jsonify({'code': 0, 'msg': '已清空封面历史', 'data': None})


@cover_bp.route('/config', methods=['GET'])
def cover_config_simple():
    """简化接口：给解说页封面模块直接拉取厂商/默认参数"""
    try:
        from backend.config.ai_config import get_config_manager
        cm = get_config_manager()
        cfg = cm.image_config
        return jsonify({
            'code': 0,
            'msg': 'ok',
            'data': {
                'default_provider': cm.normalize_image_provider(),
                'default_size': cfg.default_size,
                'default_quality': cfg.default_quality,
                'default_style': cfg.default_style,
                'default_n': cfg.default_n,
                'has_key': bool(cm.get_image_api_key()),
            }
        })
    except Exception as e:
        logger.error(f'拉取封面配置失败: {e}')
        return jsonify({'code': 1, 'msg': str(e), 'data': None}), 500


@cover_bp.route('/sizes', methods=['GET'])
def cover_sizes():
    """返回支持的尺寸表给前端下拉"""
    items = [
        {'ratio': '16:9', 'size': '1280x720', 'label': '横屏 16:9（YouTube/B站/通用）'},
        {'ratio': '9:16', 'size': '720x1280', 'label': '竖屏 9:16（抖音/快手/视频号）'},
        {'ratio': '1:1',  'size': '1024x1024', 'label': '方图 1:1（Instagram/朋友圈）'},
        {'ratio': '4:3',  'size': '1024x768',  'label': '普屏 4:3'},
        {'ratio': '3:4',  'size': '900x1200',  'label': '小红书 3:4'},
        {'ratio': '21:9', 'size': '1792x768',  'label': '带鱼屏 21:9'},
    ]
    return jsonify({'code': 0, 'msg': 'ok', 'data': items})


@cover_bp.route('/test', methods=['POST'])
def cover_test_provider():
    """解说页内的快速连通性测试（复用 config/image/test 逻辑，兼容传参）"""
    data = request.get_json() or {}
    provider = (data.get('provider') or '').strip() or None
    # 转发到 config/image/test
    from flask import current_app
    # 直接走函数调用，不发 HTTP
    try:
        from backend.config.ai_config import get_config_manager
        import requests as _req
        import time as _time
        cm = get_config_manager()
        conn = cm.get_image_connection(provider)
        norm = cm.normalize_image_provider(provider)
        api_key = conn.get('api_key') or conn.get('secret_id')
        base_url = (conn.get('base_url') or '').rstrip('/')
        if any(_is_masked_secret(value) for value in (
            conn.get('api_key'), conn.get('secret_id'), conn.get('secret_key')
        )):
            return jsonify({
                'code': 1,
                'msg': '图片专属密钥是掩码污染值，真实 Key 无法恢复，请在图片区重新输入完整 Key 并保存',
                'reason': 'masked_key_corrupted',
                'data': {'ok': False, 'provider': norm, 'reason': 'masked_key_corrupted'},
            }), 422
        if not api_key:
            return jsonify({'code': 1, 'msg': f'{norm} 尚未配置密钥', 'data': {'ok': False}}), 422
        if norm not in ('baidu', 'tencent') and not base_url:
            return jsonify({'code': 1, 'msg': f'{norm} 缺少 Base URL', 'data': {'ok': False}}), 422
        t1 = _time.time()
        ok, info = False, ''
        if norm in ('openai', 'siliconflow', 'openrouter', 'doubao', 'chatglm',
                    'custom_openai', 'minimax', 'qwen'):
            r = _req.get(f'{base_url}/models',
                         headers={'Authorization': f'Bearer {api_key}'}, timeout=10)
            ok = 200 <= r.status_code < 400
            info = f'/models -> HTTP {r.status_code}'
        elif norm == 'baidu':
            r = _req.post('https://aip.baidubce.com/oauth/2.0/token',
                          params={'grant_type': 'client_credentials',
                                  'client_id': api_key,
                                  'client_secret': conn.get('secret_key') or ''},
                          timeout=10)
            ok = 200 <= r.status_code < 400 and 'access_token' in (r.text or '')
            info = f'百度token探测 HTTP {r.status_code}'
        else:
            ok, info = False, f'{norm} 暂不支持自动测试，请直接生成'
        dt = round(_time.time() - t1, 2)
        if ok:
            return jsonify({'code': 0, 'msg': f'{norm} 连接成功 · {info} · 耗时 {dt}s',
                            'data': {'ok': True, 'provider': norm, 'time_s': dt}})
        return jsonify({'code': 1, 'msg': f'{norm} 连接失败 · {info}',
                        'data': {'ok': False, 'provider': norm, 'time_s': dt}}), 502
    except Exception as e:
        return jsonify({'code': 1, 'msg': str(e), 'data': {'ok': False}}), 500


# =========================================================
# 兜底：import时保证历史加载
# =========================================================
try:
    _load_history()
except Exception:
    pass
