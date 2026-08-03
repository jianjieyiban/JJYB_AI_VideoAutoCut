"""原创程序化花字音效；仅使用 Python 标准库生成项目内 WAV 资产。"""
from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path
from typing import Any, Dict, Iterable, List

from backend.config.paths import AUDIO_DIR

FLOWER_SFX_DIR = AUDIO_DIR / 'flower_sfx'
SFX_DURATIONS = {
    'pop': 0.12, 'bounce': 0.16, 'whoosh': 0.24, 'sparkle': 0.32,
    'neon': 0.20, 'hit': 0.18, 'paper': 0.11, 'chime': 0.28,
}
SFX_MANIFEST = {
    'license': 'JJYB-generated',
    'effects': [
        {'id': 'pop', 'name': 'Pop', 'category': 'bubble', 'templates': ['pop', 'bubble'], 'keyword_types': ['number', 'keyword'], 'default_volume': 0.18, 'duration': 0.12},
        {'id': 'bounce', 'name': 'Bounce', 'category': 'motion', 'templates': ['pop', 'bubble'], 'keyword_types': ['number'], 'default_volume': 0.18, 'duration': 0.16},
        {'id': 'whoosh', 'name': 'Sweep', 'category': 'motion', 'templates': [], 'keyword_types': ['proper'], 'default_volume': 0.16, 'duration': 0.24},
        {'id': 'sparkle', 'name': 'Glow', 'category': 'light', 'templates': ['gradient', 'glow'], 'keyword_types': ['keyword'], 'default_volume': 0.16, 'duration': 0.32},
        {'id': 'neon', 'name': 'Neon Tech', 'category': 'tech', 'templates': ['neon', 'tech'], 'keyword_types': ['proper'], 'default_volume': 0.16, 'duration': 0.20},
        {'id': 'hit', 'name': 'Impact', 'category': 'impact', 'templates': ['simple', 'hot'], 'keyword_types': ['emotion'], 'default_volume': 0.18, 'duration': 0.18},
        {'id': 'paper', 'name': 'Ink Paper', 'category': 'paper', 'templates': ['ink', 'guochao', 'vintage'], 'keyword_types': ['keyword'], 'default_volume': 0.15, 'duration': 0.11},
        {'id': 'chime', 'name': 'Gold Chime', 'category': 'chime', 'templates': ['gold'], 'keyword_types': ['gold'], 'default_volume': 0.16, 'duration': 0.28},
    ],
}
DEFAULT_SFX_MAPPING = {
    'type': {'emotion': 'hit', 'number': 'pop', 'proper': 'neon', 'gold': 'chime', 'keyword': 'sparkle'},
    'template': {'neon': 'neon', 'tech': 'neon', 'gold': 'chime', 'gradient': 'sparkle', 'glow': 'sparkle', 'pop': 'pop', 'bubble': 'pop', 'ink': 'paper', 'guochao': 'paper', 'vintage': 'paper', 'simple': 'hit', 'hot': 'hit'},
    'animation': {'sweep': 'whoosh'},
}


def _samples(key: str, sample_rate: int = 44100) -> Iterable[int]:
    duration = SFX_DURATIONS[key]
    count = int(duration * sample_rate)
    for index in range(count):
        t = index / sample_rate
        progress = index / max(1, count - 1)
        decay = (1 - progress) ** 2
        noise = math.sin(index * 12.9898) * .5 + math.sin(index * 78.233) * .5
        if key == 'pop': value = math.sin(2 * math.pi * (180 - 80 * progress) * t) * decay
        elif key == 'bounce': value = math.sin(2 * math.pi * (240 - 120 * progress) * t) * (1 - progress) ** 1.5
        elif key == 'whoosh': value = noise * math.sin(math.pi * progress) * (.3 + .7 * progress)
        elif key == 'sparkle': value = (math.sin(2 * math.pi * 1760 * t) + .42 * math.sin(2 * math.pi * 2637 * t)) * decay
        elif key == 'neon': value = (math.sin(2 * math.pi * 660 * t) + .22 * math.sin(2 * math.pi * 1320 * t)) * decay
        elif key == 'hit': value = (math.sin(2 * math.pi * 85 * t) + .28 * math.sin(2 * math.pi * 170 * t)) * decay
        elif key == 'paper': value = noise * (1 if progress < .45 else 0) * (1 - progress)
        else: value = (math.sin(2 * math.pi * 1046.5 * t) + .45 * math.sin(2 * math.pi * 1568 * t)) * decay
        yield int(max(-1, min(1, value * .22)) * 32767)


def ensure_flower_sfx_assets() -> Dict[str, Path]:
    """若缺失则生成原创短音效及 manifest，返回绝对路径；不下载或复制媒体。"""
    FLOWER_SFX_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = FLOWER_SFX_DIR / 'manifest.json'
    manifest_path.write_text(json.dumps(SFX_MANIFEST, ensure_ascii=False, indent=2), encoding='utf-8')
    paths: Dict[str, Path] = {}
    for key in SFX_DURATIONS:
        path = FLOWER_SFX_DIR / f'{key}.wav'
        if not path.exists() or path.stat().st_size < 44:
            with wave.open(str(path), 'wb') as writer:
                writer.setnchannels(1); writer.setsampwidth(2); writer.setframerate(44100)
                writer.writeframes(b''.join(struct.pack('<h', sample) for sample in _samples(key)))
        paths[key] = path.resolve()
    return paths


def resolve_sfx_key(span_type: str, template: str = '', animation: str = '', overrides: Dict[str, Any] | None = None) -> str:
    mapping = {group: dict(values) for group, values in DEFAULT_SFX_MAPPING.items()}
    for group, values in (overrides or {}).items():
        if group in mapping and isinstance(values, dict):
            mapping[group].update({str(k): str(v) for k, v in values.items() if str(v) in SFX_DURATIONS})
    return mapping['animation'].get(str(animation).lower()) or mapping['template'].get(str(template).lower()) or mapping['type'].get(str(span_type).lower(), 'sparkle')


def build_flower_sfx_items(flower_items: List[Dict[str, Any]], config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """为花字分配本地原创音效，按至少 600ms 冷却窗口消重。"""
    enabled = config.get('sound_effects_enabled', config.get('flower_sfx_enabled', False))
    if not enabled:
        return []
    assets = ensure_flower_sfx_assets()
    cooldown = max(600, int(config.get('sound_effect_cooldown_ms', config.get('flower_sfx_cooldown_ms', 600)))) / 1000.0
    volume = min(1.0, max(0.0, float(config.get('sound_effect_volume', config.get('flower_sfx_volume', .18)))))
    last_start = -float('inf')
    output: List[Dict[str, Any]] = []
    for item in sorted(flower_items, key=lambda value: value.get('time_start_ms', 0)):
        start = max(0.0, float(item.get('time_start_ms', 0)) / 1000.0)
        if start - last_start < cooldown:
            continue
        effect_id = resolve_sfx_key(item.get('type', ''), item.get('template', ''), (item.get('style') or {}).get('animation', ''), config.get('flower_sfx_mapping'))
        path = assets.get(effect_id)
        if not path or not path.is_file():
            continue
        duration = SFX_DURATIONS[effect_id]
        data = {'effect_id': effect_id, 'asset_path': str(path), 'sfx_path': str(path), 'volume': volume, 'start_seconds': start, 'end_seconds': start + duration, 'duration_seconds': duration}
        item['sound_effect'] = data
        output.append(data)
        last_start = start
    return output
