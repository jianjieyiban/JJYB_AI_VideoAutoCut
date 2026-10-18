# -*- coding: utf-8 -*-
"""
Anna 平台宿主 LLM 桥接模块。

Executa 插件在 JSON-RPC initialize 握手时协商 sampling 能力，成功后把
反向 RPC（sampling/createMessage）实现注入本模块；引擎的模型适配器在
用户未配置任何模型密钥时，通过本模块调用 Anna 平台内置大模型，
实现 AI 能力（文案生成 + 画面理解）全新安装开箱即用。

用户若在设置页配置了自己的模型密钥，则用户配置优先。
"""
from __future__ import annotations

import base64
import logging
import mimetypes
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger('JJYB_AI智剪')

# 回调签名: (messages: List[dict], max_tokens: int) -> dict(MCP sampling result)
SamplingFn = Callable[[List[Dict[str, Any]], int], Dict[str, Any]]

_sampling_fn: Optional[SamplingFn] = None
# 视觉熔断器：宿主首次图像调用失败后置位，后续直接走降级描述，
# 避免逐帧重试（11+ 次 base64 大包）拖垮整条剪辑管线
_vision_disabled = False


def register_sampling_provider(fn: SamplingFn) -> None:
    """由 Executa 插件调用：注入 sampling/createMessage 反向 RPC 实现。"""
    global _sampling_fn
    _sampling_fn = fn
    logger.info("✅ Anna 宿主 LLM sampling 通道已注册")


def unregister_sampling_provider() -> None:
    """注销宿主 LLM 通道（如宿主未授权 sampling 时由插件调用）。"""
    global _sampling_fn
    _sampling_fn = None


def is_host_llm_available() -> bool:
    """宿主 LLM 是否已协商可用（插件注入了反向 RPC 回调）。"""
    return _sampling_fn is not None


def _require_sampling_fn() -> SamplingFn:
    if _sampling_fn is None:
        raise RuntimeError(
            "Anna 平台宿主 LLM 未协商成功（sampling 能力不可用）。"
            "请在 Anna 平台重新安装本工具，或在设置页配置自己的模型密钥。"
        )
    return _sampling_fn


def _extract_text(result: Any) -> str:
    """从 MCP sampling 响应 result 中稳健提取文本。"""
    if not isinstance(result, dict):
        return ''
    content = result.get('content')
    if isinstance(content, dict):
        if content.get('type') == 'text':
            return str(content.get('text', '') or '')
        return ''
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                parts.append(str(block.get('text', '') or ''))
        return '\n'.join(p for p in parts if p)
    if isinstance(result.get('text'), str):
        return result['text']
    return ''


def sample_text(prompt: str, max_tokens: int = 4000, system: str = '') -> str:
    """调用宿主 LLM 生成文本（失败抛异常，由上层适配器转换）。"""
    fn = _require_sampling_fn()
    messages: List[Dict[str, Any]] = []
    if system:
        messages.append({
            'role': 'user',
            'content': {'type': 'text', 'text': f'[System instructions]\n{system}'},
        })
    messages.append({'role': 'user', 'content': {'type': 'text', 'text': prompt}})
    result = fn(messages, int(max_tokens))
    text = _extract_text(result)
    if not text.strip():
        raise RuntimeError('宿主 LLM 返回了空文本')
    return text


# 视觉分析不可用时的降级描述：保证剪辑管线不中断，仅画面理解质量下降
_VISION_FALLBACK = (
    '[AI vision unavailable for this shot] Keyframe visual details are missing. '
    'Write generic, natural narration based on the shot order and the overall '
    'video theme; do not invent specific on-screen details.'
)


def sample_vision(image_path: str, prompt: str, max_tokens: int = 2000) -> str:
    """调用宿主多模态模型分析图像。

    宿主模型可能不支持图像输入（sampling 常为纯文本），任何失败都返回
    降级描述而不是抛异常，确保整条剪辑管线不因视觉分析中断。
    """
    global _vision_disabled
    if _vision_disabled:
        return _VISION_FALLBACK
    try:
        fn = _require_sampling_fn()
        p = Path(image_path)
        data = base64.b64encode(p.read_bytes()).decode('ascii')
        mime = mimetypes.guess_type(image_path)[0] or 'image/jpeg'
        messages = [{
            'role': 'user',
            'content': [
                {'type': 'image', 'data': data, 'mimeType': mime},
                {'type': 'text', 'text': prompt},
            ],
        }]
        result = fn(messages, int(max_tokens))
        text = _extract_text(result)
        if text.strip():
            return text
        logger.warning('宿主多模态返回空结果，使用降级画面描述: %s', image_path)
        return _VISION_FALLBACK
    except Exception as exc:  # noqa: BLE001
        # 首次失败即熔断：宿主大概率不支持图像输入，后续帧不再重试
        _vision_disabled = True
        logger.warning('宿主 LLM 图像分析不可用（已熔断后续调用），使用降级画面描述: %s (%s)', image_path, exc)
        return _VISION_FALLBACK
