# -*- coding: utf-8 -*-
"""剪映专业版草稿目录检测与 JianyingPro 5.9 原生草稿导出。"""

import html
import json
import logging
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger('JJYB_AI智剪')
JIANYING_DRAFT_NAMES = ['JianyingDrafts', 'JianyingDraft', '草稿', '剪映草稿']
MICROSECONDS = 1_000_000


def detect_jianying_draft_info() -> Dict[str, Any]:
    """Locate a Jianying/CapCut draft root and report whether this process can write it.

    Detection and writeability are intentionally separate: Windows Controlled
    Folder Access or a sandbox may block this process while the Jianying draft
    root still exists. Returning the path lets the UI explain the real issue
    instead of incorrectly claiming that Jianying is not installed.
    """
    home = Path.home()
    candidates: List[Path] = []

    # A user-confirmed path is more reliable than filename heuristics, and is
    # persisted independently from browser localStorage for both workflows.
    try:
        from backend.config.ai_config import get_config_manager
        configured = str(getattr(get_config_manager().global_config, 'jianying_draft_path', '') or '').strip()
        if configured:
            candidates.append(Path(configured).expanduser())
    except Exception as exc:
        logger.debug('读取已保存的剪映草稿目录失败，将继续自动检测: %s', exc)

    if sys.platform.startswith('win'):
        local_appdata = Path(os.environ.get('LOCALAPPDATA') or str(home / 'AppData' / 'Local'))
        roaming_appdata = Path(os.environ.get('APPDATA') or str(home / 'AppData' / 'Roaming'))
        # 1) 注册表优先：读取 InstallPath / DraftFolder 等字段
        try:
            import winreg  # type: ignore
            for hkey_name, subkey in [
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\JianyingPro'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\JianyingPro'),
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\CapCut'),
                (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\CapCut'),
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Bytedance\JianyingPro'),
                (winreg.HKEY_CURRENT_USER, r'SOFTWARE\Bytedance\CapCut'),
            ]:
                try:
                    with winreg.OpenKey(hkey_name, subkey) as k:
                        for name in ('DraftRoot', 'DraftPath', 'DraftFolder', 'InstallPath', 'UserDataPath', 'User Data Path'):
                            try:
                                v, _ = winreg.QueryValueEx(k, name)
                                if isinstance(v, str) and v.strip():
                                    p = Path(v.strip().strip('"'))
                                    if p.name.lower() != 'com.lveditor.draft':
                                        p = p / 'User Data' / 'Projects' / 'com.lveditor.draft'
                                    candidates.append(p)
                            except OSError:
                                pass
                except OSError:
                    continue
        except Exception:
            pass

        # 2) 剪映专业版 JianyingPro 本地目录（多版本命名兜底）
        candidates += [
            local_appdata / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            local_appdata / 'JianyingPro' / 'Projects' / 'com.lveditor.draft',
            local_appdata / 'JianyingPro.UserData' / 'Projects' / 'com.lveditor.draft',
            home / 'AppData' / 'Local' / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            roaming_appdata / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            # 3) 国际版 CapCut
            local_appdata / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            local_appdata / 'CapCut' / 'Projects' / 'com.lveditor.draft',
            roaming_appdata / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft',
        ]

        # 4) 常见用户目录：文档/视频/图片/桌面 + OneDrive 同步目录
        user_common_parents: List[Path] = []
        try:
            import ctypes.wintypes  # type: ignore
            CSIDL_PERSONAL = 5        # Documents
            CSIDL_MYVIDEO = 14        # Videos
            CSIDL_MYPICTURES = 39     # Pictures
            CSIDL_DESKTOPDIRECTORY = 16
            SHGFP_TYPE_CURRENT = 0
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            for csidl in (CSIDL_PERSONAL, CSIDL_MYVIDEO, CSIDL_MYPICTURES, CSIDL_DESKTOPDIRECTORY):
                try:
                    ctypes.windll.shell32.SHGetFolderPathW(0, csidl, 0, SHGFP_TYPE_CURRENT, buf)
                    if buf.value: user_common_parents.append(Path(buf.value))
                except Exception:
                    pass
        except Exception:
            pass
        # 兜底（上面 shell32 失败时的环境退化路径）
        user_common_parents += [
            home / 'Documents', home / 'Document', home / '文档',
            home / 'Videos', home / '视频',
            home / 'Pictures', home / '图片',
            home / 'Desktop', home / '桌面',
            home / 'OneDrive' / 'Documents', home / 'OneDrive' / '图片', home / 'OneDrive' / '视频',
            home / 'OneDrive' / 'Desktop',
        ]
        for parent in list(dict.fromkeys(user_common_parents)):  # 去重保序
            for sub in (
                'JianyingPro', 'JianyingDrafts', 'JianyingDraft', '剪映草稿', '草稿',
                'CapCut', 'CapCutDrafts',
                '剪映专业版',
            ):
                candidates.append(parent / sub)
                candidates.append(parent / sub / 'com.lveditor.draft')

        # 5) 所有磁盘根目录下的常见命名（C/D/E/F/G/H/I/J）
        try:
            import string
            drives_root = [Path(f'{d}:\\') for d in string.ascii_uppercase if Path(f'{d}:\\').exists()]
        except Exception:
            drives_root = [Path(p) for p in ['C:\\','D:\\','E:\\','F:\\','G:\\'] if Path(p).exists()]
        for root in drives_root:
            # ProgramData 下的官方默认路径
            try:
                candidates.append(root / 'ProgramData' / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft')
                candidates.append(root / 'ProgramData' / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft')
            except Exception:
                pass
            # 其他常见命名目录
            for sub in (
                'JianyingPro', 'JianyingDrafts', '剪映草稿', '草稿',
                'CapCut', 'CapCut Drafts',
            ):
                try:
                    p = root / sub
                    candidates.append(p)
                    candidates.append(p / 'User Data' / 'Projects' / 'com.lveditor.draft')
                except Exception:
                    pass

    elif sys.platform == 'darwin':
        candidates += [
            home / 'Movies' / 'JianyingPro' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            home / 'Movies' / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft',
            home / 'Documents' / 'JianyingPro',
            home / 'Desktop' / 'JianyingPro',
        ]
    else:
        candidates += [
            home / '.jianying' / 'drafts', home / 'JianyingDrafts',
            home / 'JianyingPro', home / 'CapCut',
            Path('/opt/JianyingPro'), Path('/var/lib/jianying/drafts'),
        ]

    seen: set = set()
    for candidate in candidates:
        try:
            key = str(candidate.resolve()).lower() if candidate.exists() else str(candidate).lower()
        except Exception:
            key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        try:
            if not candidate.exists() or not candidate.is_dir():
                continue
        except OSError:
            continue
        writable = _is_writable_directory(candidate)
        if writable:
            logger.info('检测到可写剪映草稿目录: %s', candidate)
        else:
            logger.warning('检测到剪映草稿目录但当前进程不可写: %s', candidate)
        return {
            'draft_dir': str(candidate),
            'detected': True,
            'writable': writable,
            'message': '' if writable else '已找到剪映草稿目录，但当前应用进程没有写入权限。请以与剪映相同的 Windows 用户运行本工具，或授予该目录修改权限。',
        }
    return {'draft_dir': '', 'detected': False, 'writable': False, 'message': '未检测到剪映草稿目录'}


def detect_jianying_draft_dir(require_writable: bool = True) -> str:
    """Return the detected draft root, optionally requiring write permission."""
    info = detect_jianying_draft_info()
    if not info['detected'] or (require_writable and not info['writable']):
        return ''
    return str(info['draft_dir'])


def export_draft_package(
    draft_dir: str,
    project_id: str,
    timeline: List[Dict[str, Any]],
    video_path: str = '',
    audio_paths: Optional[List[str]] = None,
    subtitle_text: str = '',
    bgm_path: str = '',
    project_name: str = '',
    flower_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """导出可被 JianyingPro 5.9 扫描和打开的原生草稿目录。

    素材保留在原位置，draft_content.json 使用 POSIX 绝对路径引用，不复制素材也不生成 ZIP。
    """
    # 先校验真实视频时间线，禁止生成空草稿或仅字幕草稿。
    if not isinstance(timeline, list) or not timeline:
        raise ValueError('时间线为空，无法导出包含视频轨道的剪映草稿')
    if not any(isinstance(item, dict) and _existing_path(
        item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path') or video_path
    ) for item in timeline):
        raise ValueError('时间线没有合法视频片段，无法导出剪映草稿')

    requested_root = _resolve_path(draft_dir) if draft_dir else None
    if requested_root and requested_root.exists() and requested_root.is_dir() and not _is_writable_directory(requested_root):
        raise PermissionError(f'剪映草稿目录不可写: {requested_root}。请以与剪映相同的 Windows 用户运行本工具，或授予该目录“修改”权限。')
    native_jianying_project = bool(requested_root and _is_native_jianying_root(requested_root))
    if not native_jianying_project:
        requested_root = PROJECT_ROOT / 'output' / 'jianying_drafts'
        requested_root.mkdir(parents=True, exist_ok=True)
    draft_root = requested_root.resolve()
    draft_id = str(uuid.uuid4())
    safe_name = _safe_draft_name(project_name or f'JJYB原创解说_{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    draft_path = draft_root / safe_name
    suffix = 1
    while draft_path.exists():
        suffix += 1
        draft_path = draft_root / f'{safe_name}_{suffix}'
    draft_path.mkdir(parents=True, exist_ok=False)

    warnings: List[str] = []
    video_file = _existing_path(video_path)
    if not video_file:
        warnings.append('源视频不存在，草稿未创建视频素材。')
    video_info = _probe_media_info(video_file) if video_file else {}
    canvas_width = int(video_info.get('width') or 1920)
    canvas_height = int(video_info.get('height') or 1080)
    now_us = int(datetime.now().timestamp() * MICROSECONDS)
    materials = _empty_materials()
    tracks: List[Dict[str, Any]] = []
    video_material_id = _uuid()
    video_duration = _us(video_info.get('duration', 0.0))
    video_materials: Dict[str, Dict[str, Any]] = {}
    if video_file:
        video_materials[str(video_file)] = _video_material(video_material_id, video_file, video_duration, video_info)
        materials['videos'].append(video_materials[str(video_file)])

    voice_materials: Dict[str, Dict[str, Any]] = {}
    for audio_path in audio_paths or []:
        audio_file = _existing_path(audio_path)
        if not audio_file:
            warnings.append(f'配音素材不存在，已跳过: {audio_path}')
            continue
        voice_materials[str(audio_file)] = _audio_material(_uuid(), audio_file, _probe_media_info(audio_file))
        materials['audios'].append(voice_materials[str(audio_file)])
    bgm_file = _existing_path(bgm_path)
    bgm_material = None
    if bgm_file:
        bgm_material = _audio_material(_uuid(), bgm_file, _probe_media_info(bgm_file))
        materials['audios'].append(bgm_material)

    video_segments: List[Dict[str, Any]] = []
    voice_segments: List[Dict[str, Any]] = []
    original_segments: List[Dict[str, Any]] = []
    text_segments: List[Dict[str, Any]] = []
    subtitle_clips: List[Dict[str, Any]] = []
    fallback_voice_cursor: Dict[str, int] = {}
    fallback_audio_materials = list(voice_materials.values())
    has_explicit_voice_mapping = any(
        isinstance(item, dict) and any(item.get(field) for field in ('voice_paths', 'voice_path', 'audio_path', 'audio_url'))
        for item in timeline
    )
    fallback_subtitles: Dict[int, str] = {}
    if subtitle_text and not any(str(item.get('subtitle_text') or '').strip() for item in timeline if isinstance(item, dict)):
        narration_items = [index for index, item in enumerate(timeline) if isinstance(item, dict) and not (bool(item.get('original_audio')) or item.get('kind') == 'original_audio')]
        pieces = [piece.strip() for piece in str(subtitle_text).splitlines() if piece.strip()]
        if narration_items and pieces:
            for position, item_index in enumerate(narration_items):
                start = round(position * len(pieces) / len(narration_items))
                end = round((position + 1) * len(pieces) / len(narration_items))
                fallback_subtitles[item_index] = ' '.join(pieces[start:end]) or pieces[min(start, len(pieces) - 1)]
            warnings.append('时间线未提供 subtitle_text，已按非原声片段时长顺序分配传入字幕。')
        elif subtitle_text:
            warnings.append('没有可分配字幕的非原声时间线片段，传入字幕未写入草稿。')
    cursor = 0
    render_index = 11000
    for item_index, item in enumerate(timeline or []):
        item_video_file = _existing_path(
            item.get('source_video') or item.get('source_video_path') or item.get('video_path') or item.get('source_path') or video_path
        )
        item_video_info = _probe_media_info(item_video_file) if item_video_file else {}
        item_video_duration = _us(item_video_info.get('duration', 0.0))
        item_video_material = None
        if item_video_file:
            item_video_material = video_materials.get(str(item_video_file))
            if not item_video_material:
                item_video_material = _video_material(_uuid(), item_video_file, item_video_duration, item_video_info)
                video_materials[str(item_video_file)] = item_video_material
                materials['videos'].append(item_video_material)
        source_start = max(0, _us(item.get('source_start', 0)))
        source_end = max(source_start, _us(item.get('source_end', 0)))
        if item_video_duration:
            source_start = min(source_start, item_video_duration)
            source_end = min(source_end, item_video_duration)
        source_duration = source_end - source_start
        speed = _positive_float(item.get('speed_factor', 1.0), 1.0)
        requested_duration = _us(item.get('final_duration') or item.get('audio_duration') or 0)
        playable_duration = int(source_duration / speed) if source_duration else requested_duration
        target_duration = requested_duration or playable_duration
        if source_duration and (bool(item.get('freeze_tail')) or target_duration > playable_duration):
            if target_duration > playable_duration:
                warnings.append(f'时间线第 {item_index + 1} 段请求时长超过真实源片段，已限制为可播放时长。')
            target_duration = playable_duration
        if target_duration <= 0:
            warnings.append(f'时间线第 {item_index + 1} 段时长无效，已跳过。')
            continue
        if item_video_material:
            refs: List[str] = []
            if abs(speed - 1.0) > 0.0001:
                speed_id = _uuid()
                materials['speeds'].append({'curve_speed': None, 'id': speed_id, 'mode': 0, 'speed': speed, 'type': 'speed'})
                refs.append(speed_id)
            video_segments.append(_segment(item_video_material['id'], cursor, target_duration, source_start, source_duration, speed, refs))

        is_original = bool(item.get('original_audio')) or item.get('kind') == 'original_audio'
        if is_original and item_video_material and item_video_info.get('has_audio'):
            original_segments.append(_segment(
                item_video_material['id'], cursor, target_duration, source_start, source_duration, speed, [],
                volume=max(0.0, min(1.0, _positive_float(item.get('original_audio_volume', 1.0), 1.0))),
            ))
        elif not is_original:
            voice_cursor = cursor
            remaining = target_duration
            item_voice_values: List[Any] = []
            for field in ('voice_paths', 'voice_path', 'audio_path', 'audio_url'):
                value = item.get(field)
                item_voice_values.extend(value if isinstance(value, list) else [value])
            item_materials: List[Dict[str, Any]] = []
            for voice_path in item_voice_values:
                voice_file = _existing_path(voice_path)
                material = voice_materials.get(str(voice_file)) if voice_file else None
                if voice_file and not material:
                    material = _audio_material(_uuid(), voice_file, _probe_media_info(voice_file))
                    voice_materials[str(voice_file)] = material
                    materials['audios'].append(material)
                    fallback_audio_materials.append(material)
                if material and material not in item_materials:
                    item_materials.append(material)
            if not item_materials and not has_explicit_voice_mapping and len(fallback_audio_materials) == 1:
                item_materials = fallback_audio_materials
            elif not item_materials and not has_explicit_voice_mapping and len(fallback_audio_materials) > 1:
                warnings.append(f'时间线第 {item_index + 1} 段未指定配音，多个全局配音无法可靠同步，已跳过配音轨。')
            for material in item_materials:
                source_start = fallback_voice_cursor.get(material['id'], 0) if not item_voice_values else 0
                available = max(0, int(material['duration']) - source_start)
                duration = min(available, remaining)
                if duration <= 0:
                    continue
                voice_segments.append(_segment(material['id'], voice_cursor, duration, source_start, duration, 1.0, []))
                fallback_voice_cursor[material['id']] = source_start + duration
                voice_cursor += duration
                remaining -= duration
                if remaining <= 0:
                    break
            if item_materials and remaining > 0:
                warnings.append(f'时间线第 {item_index + 1} 段配音短于画面，剩余 {remaining / MICROSECONDS:.2f}s 不创建静音伪轨。')

        text = str(item.get('subtitle_text') or fallback_subtitles.get(item_index) or '').strip()
        if text:
            text_id = _uuid()
            materials['texts'].append(_text_material(text_id, text))
            text_segments.append(_segment(text_id, cursor, target_duration, None, None, 1.0, [text_id], render_index))
            subtitle_clips.append({'text': text, 'start': cursor / MICROSECONDS, 'end': (cursor + target_duration) / MICROSECONDS})
            render_index += 1
        cursor += target_duration

    if video_segments:
        tracks.append(_track('video', video_segments))
    if voice_segments:
        tracks.append(_track('audio', voice_segments))
    if original_segments:
        tracks.append(_track('audio', original_segments))
    if bgm_material and cursor > 0 and bgm_material['duration'] > 0:
        bgm_segments: List[Dict[str, Any]] = []
        bgm_cursor = 0
        while bgm_cursor < cursor:
            duration = min(int(bgm_material['duration']), cursor - bgm_cursor)
            bgm_segments.append(_segment(bgm_material['id'], bgm_cursor, duration, 0, duration, 1.0, [], volume=0.25))
            bgm_cursor += duration
        tracks.append(_track('audio', bgm_segments))
    if text_segments:
        tracks.append(_track('text', text_segments))
    flower_track = _build_flower_track_from_subtitles(subtitle_clips, flower_config, cursor)
    flower_segments = [segment for material, segment in flower_track['segments']]
    materials['texts'].extend(material for material, segment in flower_track['segments'])
    if flower_segments:
        tracks.append(_track('text', flower_segments))
    flower_sfx_segments: List[Dict[str, Any]] = []
    for sfx in flower_track.get('sfx') or []:
        sfx_file = _existing_path(sfx.get('asset_path') or sfx.get('sfx_path', ''))
        if not sfx_file:
            warnings.append(f'花字音效素材不存在，已跳过: {sfx.get("asset_path") or sfx.get("sfx_path", "")}')
            continue
        start = _us(sfx.get('start_seconds', 0))
        info = _probe_media_info(sfx_file)
        duration = min(_us(sfx.get('duration_seconds', 0)), _us(info.get('duration', 0)), max(0, cursor - start))
        if duration <= 0:
            warnings.append(f'花字音效时段无效或超出视频，已跳过: {sfx_file}')
            continue
        material = _audio_material(_uuid(), sfx_file, info)
        materials['audios'].append(material)
        flower_sfx_segments.append(_segment(material['id'], start, duration, 0, duration, 1.0, [], volume=max(0.0, min(1.0, _float_or(sfx.get('volume'), 0.18)))))
    if flower_sfx_segments:
        tracks.append(_track('audio', flower_sfx_segments))

    content = _draft_content(draft_id, cursor, canvas_width, canvas_height, now_us, materials, tracks)
    try:
        _validate_draft_content(content)
    except Exception:
        import shutil
        shutil.rmtree(draft_path, ignore_errors=True)
        raise
    meta = _draft_meta(draft_id, draft_path, draft_root, draft_path.name, cursor, now_us, materials)
    content_path = draft_path / 'draft_content.json'
    meta_path = draft_path / 'draft_meta_info.json'
    _write_json(content_path, content)
    _write_json(meta_path, meta)
    for filename in ('draft_virtual_store.json', 'draft_agency_config.json', 'attachment_pc_common.json', 'attachment_draft_enterprise_info.json'):
        _write_json(draft_path / filename, {})
    (draft_path / 'draft_settings').write_text('', encoding='utf-8')
    if subtitle_clips:
        (draft_path / 'subtitles.srt').write_text(_srt(subtitle_clips), encoding='utf-8')

    logger.info('原生剪映草稿导出完成: %s', draft_path)
    return {
        'draft_id': draft_id, 'draft_path': str(draft_path), 'draft_name': draft_path.name,
        'draft_root_path': draft_root.as_posix(), 'draft_content_path': str(content_path),
        'draft_meta_info_path': str(meta_path), 'native_jianying_project': native_jianying_project,
        'archive_path': '', 'warnings': warnings, 'track_count': len(tracks), 'tracks': tracks,
        'assets_count': len(materials['videos']) + len(materials['audios']),
        'video_segment_count': len(video_segments), 'voice_segment_count': len(voice_segments),
        'subtitle_segment_count': len(text_segments),
        'flower_config_applied': flower_track['applied'],
        'flower_count': flower_track['count'],
        'flower_sound_effect_count': len(flower_sfx_segments), 'flower_sfx_count': len(flower_sfx_segments),
        'total_duration': cursor / MICROSECONDS, 'project_name': project_name or draft_path.name,
    }


def _build_flower_track_from_subtitles(subtitle_clips: List[Dict[str, Any]], flower_config: Optional[Dict[str, Any]], total_duration: int) -> Dict[str, Any]:
    config = flower_config if isinstance(flower_config, dict) else {}
    if not config.get('enabled') or not config.get('jianying_track'):
        return {'segments': [], 'sfx': [], 'applied': False, 'count': 0}
    try:
        from backend.engine.subtitle_generator import SubtitleGenerator
        generator = SubtitleGenerator()
        narrations = [
            {'text': clip['text'], 'time_range': f"{clip['start']}s-{clip['end']}s"}
            for clip in subtitle_clips if clip.get('text') and clip.get('end', 0) > clip.get('start', 0)
        ]
        if not narrations:
            return {'segments': [], 'applied': True, 'count': 0}
        flower_data = generator.build_jianying_flower_track({'narrations': narrations}, config)
        segments = []
        render_index = 12000
        for item in flower_data.get('items') or []:
            start = _us(item.get('time_start_ms', 0) / 1000)
            end = _us(item.get('time_end_ms', 0) / 1000)
            duration = max(0, min(total_duration - start, end - start))
            if duration <= 0:
                continue
            text_id = _uuid()
            style = item.get('style') or {}
            material = _text_material(text_id, str(item.get('text') or ''))
            material.update({'font_name': style.get('fontname') or '', 'font_size': float(style.get('fontsize') or 9), 'text_color': style.get('primary_color') or '#FFFFFF', 'border_color': style.get('stroke_color') or '#000000'})
            segments.append((material, _segment(text_id, start, duration, None, None, 1.0, [text_id], render_index)))
            render_index += 1
        return {'segments': segments, 'sfx': flower_data.get('flower_sfx') or [], 'applied': True, 'count': len(segments)}
    except Exception as exc:
        logger.warning('花字轨道构建失败，已跳过: %s', exc)
        return {'segments': [], 'applied': False, 'count': 0}


def _validate_draft_content(content: Dict[str, Any]) -> None:
    duration = int(content.get('duration') or 0)
    tracks = content.get('tracks') or []
    videos = {item.get('id'): int(item.get('duration') or 0) for item in (content.get('materials') or {}).get('videos', [])}
    audios = {item.get('id'): int(item.get('duration') or 0) for item in (content.get('materials') or {}).get('audios', [])}
    video_segments = [segment for track in tracks if track.get('type') == 'video' for segment in track.get('segments') or []]
    if duration <= 0 or not video_segments:
        raise ValueError('草稿校验失败：必须包含时长大于零的视频轨道')
    video_segments.sort(key=lambda segment: int(segment['target_timerange']['start']))
    expected_start = 0
    for segment in video_segments:
        target = segment.get('target_timerange') or {}
        source = segment.get('source_timerange') or {}
        start, length = int(target.get('start') or 0), int(target.get('duration') or 0)
        if length <= 0 or start != expected_start:
            raise ValueError('草稿校验失败：视频片段必须连续且时段合法')
        material_duration = videos.get(segment.get('material_id'), 0)
        if int(source.get('start') or 0) < 0 or int(source.get('duration') or 0) <= 0 or int(source.get('start') or 0) + int(source.get('duration') or 0) > material_duration:
            raise ValueError('草稿校验失败：视频源时段超出素材范围')
        expected_start += length
    if abs(expected_start - duration) > 1:
        raise ValueError('草稿校验失败：总时长与最后视频片段不一致')
    for track in tracks:
        for segment in track.get('segments') or []:
            target = segment.get('target_timerange') or {}
            start, length = int(target.get('start') or 0), int(target.get('duration') or 0)
            if start < 0 or length <= 0 or start + length > duration:
                raise ValueError('草稿校验失败：目标时段非法')
            source = segment.get('source_timerange')
            if source is not None:
                material_duration = videos.get(segment.get('material_id'), audios.get(segment.get('material_id'), 0))
                if int(source.get('start') or 0) < 0 or int(source.get('duration') or 0) <= 0 or int(source.get('start') or 0) + int(source.get('duration') or 0) > material_duration:
                    raise ValueError('草稿校验失败：源时段超出素材范围')


def _build_flower_track(timeline: List[Dict[str, Any]], flower_config: Optional[Dict[str, Any]], total_duration: int) -> Dict[str, Any]:
    config = flower_config if isinstance(flower_config, dict) else {}
    if not config.get('enabled') or not config.get('jianying_track'):
        return {'segments': [], 'applied': False, 'count': 0}
    try:
        from backend.engine.subtitle_generator import SubtitleGenerator
        generator = SubtitleGenerator()
        narrations = []
        cursor = 0
        for item in timeline or []:
            if not isinstance(item, dict):
                continue
            duration = _us(item.get('final_duration') or item.get('audio_duration') or 0)
            text = str(item.get('subtitle_text') or '').strip()
            if text and duration > 0:
                narrations.append({'text': text, 'time_range': f'{cursor / MICROSECONDS}s-{(cursor + duration) / MICROSECONDS}s'})
            cursor += max(0, duration)
        if not narrations:
            return {'segments': [], 'applied': True, 'count': 0}
        flower_data = generator.build_jianying_flower_track({'narrations': narrations}, config)
        segments = []
        render_index = 12000
        for item in flower_data.get('items') or []:
            start = _us(item.get('time_start_ms', 0) / 1000)
            end = _us(item.get('time_end_ms', 0) / 1000)
            duration = max(0, min(total_duration - start, end - start))
            if duration <= 0:
                continue
            text_id = _uuid()
            style = item.get('style') or {}
            material = _text_material(text_id, str(item.get('text') or ''))
            material.update({'font_name': style.get('fontname') or '', 'font_size': float(style.get('fontsize') or 9), 'text_color': style.get('primary_color') or '#FFFFFF', 'border_color': style.get('stroke_color') or '#000000'})
            segments.append((material, _segment(text_id, start, duration, None, None, 1.0, [text_id], render_index)))
            render_index += 1
        return {'segments': segments, 'applied': True, 'count': len(segments)}
    except Exception as exc:
        logger.warning('花字轨道构建失败，已跳过: %s', exc)
        return {'segments': [], 'applied': False, 'count': 0}

def _resolve_path(value: str) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else PROJECT_ROOT / path


def _existing_path(value: str) -> Optional[Path]:
    if not value:
        return None
    path = _resolve_path(value)
    return path.resolve() if path.exists() and path.is_file() else None


def _is_native_jianying_root(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_dir():
            return False
        resolved = path.resolve()
        parts = [part.casefold() for part in resolved.parts]
        return (
            resolved.name.casefold() == 'com.lveditor.draft'
            and 'user data' in parts
            and 'projects' in parts
            and _is_writable_directory(resolved)
        )
    except OSError:
        return False


def _is_writable_directory(path: Path) -> bool:
    try:
        if not path.exists() or not path.is_dir():
            return False
        # 先做轻量权限检查：R_OK | W_OK
        try:
            if os.access(path, os.W_OK | os.R_OK):
                # 额外探测：创建子目录探测 (更轻，某些杀软不拦)
                probe = path / f'.jjyb_probe_{uuid.uuid4().hex[:6]}'
                made = False
                try:
                    probe.mkdir(exist_ok=False)
                    made = True
                    probe.rmdir()
                    return True
                except OSError:
                    if made:
                        try: probe.rmdir()
                        except OSError: pass
        except Exception:
            pass
        # 回退到写文件探测（兼容更严格的权限）
        probe = path / f'.jjyb_write_test_{uuid.uuid4().hex}'
        probe.write_text('', encoding='utf-8')
        probe.unlink()
        return True
    except OSError:
        return False


def _uuid() -> str:
    return str(uuid.uuid4()).upper()


def _us(value: Any) -> int:
    try:
        return max(0, int(round(float(value) * MICROSECONDS)))
    except (TypeError, ValueError):
        return 0


def _positive_float(value: Any, fallback: float) -> float:
    try:
        return max(0.0001, float(value))
    except (TypeError, ValueError):
        return fallback


def _float_or(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _safe_draft_name(name: str) -> str:
    name = ''.join('_' if char in '\\/:*?"<>|' else char for char in name).strip(' .')
    return (name or 'JJYB原创解说')[:100]


def _probe_media_info(path: Path) -> Dict[str, Any]:
    try:
        import subprocess
        command = ['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
        streams = data.get('streams') or []
        video = next((stream for stream in streams if stream.get('codec_type') == 'video'), {})
        return {'duration': float((data.get('format') or {}).get('duration') or 0), 'width': int(video.get('width') or 0), 'height': int(video.get('height') or 0), 'has_audio': any(stream.get('codec_type') == 'audio' for stream in streams)}
    except Exception:
        return {'duration': 0.0, 'width': 0, 'height': 0, 'has_audio': False}


def _probe_media_duration(path: Path) -> float:
    return float(_probe_media_info(path).get('duration') or 0.0)


def _empty_materials() -> Dict[str, List[Any]]:
    keys = ('audio_balances audio_effects audio_fades audios beats canvases chromas color_curves digital_humans drafts effects flowers green_screens handwrites hsl images log_color_wheels loudnesses manual_deformations masks material_animations material_colors placeholders plugin_effects primary_color_wheels realtime_denoises shapes smart_crops smart_relights sound_channel_mappings speeds stickers tail_leaders text_templates texts transitions video_effects video_trackings videos')
    return {key: [] for key in keys.split()}


def _video_material(material_id: str, path: Path, duration: int, info: Dict[str, Any]) -> Dict[str, Any]:
    posix = path.as_posix()
    return {'audio_fade': None, 'category_id': '', 'category_name': 'local', 'check_flag': 63487, 'crop': {'lower_left_x': 0.0, 'lower_left_y': 1.0, 'lower_right_x': 1.0, 'lower_right_y': 1.0, 'upper_left_x': 0.0, 'upper_left_y': 0.0, 'upper_right_x': 1.0, 'upper_right_y': 0.0}, 'crop_ratio': 'free', 'crop_scale': 1.0, 'duration': duration, 'extra_type_option': 0, 'freeze': None, 'has_audio': bool(info.get('has_audio')), 'height': int(info.get('height') or 1080), 'id': material_id, 'material_id': '', 'material_name': path.name, 'material_url': '', 'media_path': posix, 'name': path.name, 'path': posix, 'source': 0, 'source_platform': 0, 'type': 'video', 'video_algorithm': {'algorithms': [], 'deflicker': None, 'motion_blur_config': None, 'noise_reduction': None}, 'width': int(info.get('width') or 1920)}


def _audio_material(material_id: str, path: Path, info: Dict[str, Any]) -> Dict[str, Any]:
    posix = path.as_posix()
    return {'app_id': 0, 'category_id': '', 'category_name': 'local', 'check_flag': 1, 'duration': _us(info.get('duration', 0)), 'effect_id': '', 'formula_id': '', 'id': material_id, 'intensifies_path': '', 'is_ai_generate_content': False, 'local_id': '', 'material_id': '', 'material_name': path.name, 'music_id': '', 'name': path.name, 'path': posix, 'query': '', 'resource_id': '', 'source_platform': 0, 'team_id': '', 'type': 'audio', 'video_id': '', 'wave_points': []}


def _text_material(material_id: str, text: str) -> Dict[str, Any]:
    content = '<outline color=(0.0,0.0,0.0,1) width=2.0><size=9.0><font id="" path="">%s</font></size></outline>' % html.escape(text, quote=True)
    return {'add_type': 0, 'alignment': 1, 'background_alpha': 0.0, 'background_color': '', 'background_height': 0.14, 'background_horizontal_offset': 0.0, 'background_round_radius': 0.0, 'background_style': 0, 'background_vertical_offset': 0.0, 'background_width': 0.14, 'base_content': '', 'bold_width': 0.0, 'border_alpha': 1.0, 'border_color': '#000000', 'border_width': 2.0, 'caption_template_info': {'category_id': '', 'category_name': '', 'effect_id': '', 'is_new': False, 'path': '', 'request_id': '', 'resource_id': '', 'resource_name': '', 'source_platform': 0}, 'check_flag': 7, 'combo_info': {'text_templates': []}, 'content': content, 'fixed_height': -1.0, 'fixed_width': -1.0, 'font_id': '', 'font_name': '', 'font_path': '', 'font_size': 9.0, 'fonts': [], 'global_alpha': 1.0, 'id': material_id, 'is_rich_text': False, 'line_feed': 1, 'line_max_width': 0.82, 'line_spacing': 0.02, 'name': '', 'original_size': [], 'recognize_type': 0, 'shadow_alpha': 0.9, 'shadow_angle': -45.0, 'shadow_color': '', 'shadow_distance': 5.0, 'sub_type': 0, 'text_alpha': 1.0, 'text_color': '#FFFFFF', 'text_size': 30, 'type': 'text', 'typesetting': 0, 'underline': False, 'words': {'end_time': [], 'start_time': [], 'text': []}}


def _segment(material_id: str, target_start: int, target_duration: int, source_start: Optional[int], source_duration: Optional[int], speed: float, refs: List[str], render_index: int = 0, volume: float = 1.0) -> Dict[str, Any]:
    return {'cartoon': False, 'clip': {'alpha': 1.0, 'flip': {'horizontal': False, 'vertical': False}, 'rotation': 0.0, 'scale': {'x': 1.0, 'y': 1.0}, 'transform': {'x': 0.0, 'y': -0.8 if render_index >= 11000 else 0.0}}, 'common_keyframes': [], 'enable_adjust': render_index == 0, 'enable_color_curves': True, 'enable_color_match_adjust': False, 'enable_color_wheels': True, 'enable_lut': render_index == 0, 'enable_smart_color_adjust': False, 'extra_material_refs': refs, 'group_id': '', 'hdr_settings': None, 'id': _uuid(), 'intensifies_audio': False, 'is_placeholder': False, 'is_tone_modify': False, 'keyframe_refs': [], 'last_nonzero_volume': volume, 'material_id': material_id, 'render_index': render_index, 'responsive_layout': {'enable': False, 'horizontal_pos_layout': 0, 'size_layout': 0, 'target_follow': '', 'vertical_pos_layout': 0}, 'reverse': False, 'source_timerange': None if source_start is None else {'duration': int(source_duration or 0), 'start': int(source_start)}, 'speed': speed, 'target_timerange': {'duration': int(target_duration), 'start': int(target_start)}, 'template_id': '', 'template_scene': 'default', 'track_attribute': 0, 'track_render_index': 0, 'uniform_scale': None if render_index >= 11000 else {'on': True, 'value': 1.0}, 'visible': True, 'volume': volume}


def _track(track_type: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {'attribute': 0, 'flag': 0, 'id': _uuid(), 'is_default_name': True, 'name': '', 'segments': segments, 'type': track_type}


def _draft_content(draft_id: str, duration: int, width: int, height: int, now_us: int, materials: Dict[str, List[Any]], tracks: List[Dict[str, Any]]) -> Dict[str, Any]:
    platform = {'app_id': 3704, 'app_source': 'lv', 'app_version': '5.9.0', 'device_id': 'auto_generated', 'hard_disk_id': '', 'mac_address': '', 'os': 'windows', 'os_version': '10.0.22631'}
    return {'canvas_config': {'width': width, 'height': height, 'ratio': 'original'}, 'color_space': 0, 'config': {'adjust_max_index': 1, 'attachment_info': [], 'combination_max_index': 1, 'export_range': None, 'extract_audio_last_index': 1, 'lyrics_recognition_id': '', 'lyrics_sync': True, 'lyrics_taskinfo': [], 'maintrack_adsorb': True, 'material_save_mode': 0, 'original_sound_last_index': 1, 'record_audio_last_index': 1, 'sticker_max_index': 1, 'subtitle_recognition_id': '', 'subtitle_sync': True, 'subtitle_taskinfo': [], 'system_font_list': [], 'video_mute': False, 'zoom_info_params': None}, 'cover': None, 'create_time': now_us, 'duration': duration, 'extra_info': None, 'fps': 30.0, 'free_render_index_mode_on': False, 'group_container': None, 'id': draft_id, 'keyframe_graph_list': [], 'keyframes': {'adjusts': [], 'audios': [], 'effects': [], 'filters': [], 'handwrites': [], 'stickers': [], 'texts': [], 'videos': []}, 'last_modified_platform': platform, 'materials': materials, 'mutable_config': None, 'name': '', 'new_version': '164.0.0', 'platform': platform, 'relationships': [], 'render_index_track_mode_on': False, 'retouch_cover': None, 'source': 'default', 'static_cover_image_path': '', 'tracks': tracks}


def _draft_meta(draft_id: str, draft_path: Path, draft_root: Path, name: str, duration: int, now_us: int, materials: Dict[str, List[Any]]) -> Dict[str, Any]:
    entries = []
    for material in materials['videos']:
        entries.append({'create_time': now_us // MICROSECONDS, 'duration': material['duration'], 'extra_info': material['name'], 'file_Path': material['path'], 'height': material['height'], 'id': material['id'], 'import_time': now_us // MICROSECONDS, 'import_time_ms': now_us, 'item_source': 1, 'md5': '', 'metetype': 'video', 'roughcut_time_range': {'duration': material['duration'], 'start': 0}, 'sub_time_range': {'duration': -1, 'start': -1}, 'type': 0, 'width': material['width']})
    audio_entries = [{'create_time': now_us // MICROSECONDS, 'duration': material['duration'], 'extra_info': material['name'], 'file_Path': material['path'], 'id': material['id'], 'import_time': now_us // MICROSECONDS, 'import_time_ms': now_us, 'item_source': 1, 'md5': '', 'metetype': 'audio', 'roughcut_time_range': {'duration': material['duration'], 'start': 0}, 'sub_time_range': {'duration': -1, 'start': -1}, 'type': 1} for material in materials['audios']]
    return {'cloud_package_completed_time': '', 'draft_cloud_capcut_purchase_info': '', 'draft_cloud_last_action_download': False, 'draft_cloud_materials': [], 'draft_cloud_purchase_info': '', 'draft_cloud_template_id': '', 'draft_cloud_tutorial_info': '', 'draft_cloud_videocut_purchase_info': '', 'draft_cover': '', 'draft_deeplink_url': '', 'draft_enterprise_info': {'draft_enterprise_extra': '', 'draft_enterprise_id': '', 'draft_enterprise_name': '', 'enterprise_material': []}, 'draft_fold_path': draft_path.as_posix(), 'draft_id': draft_id, 'draft_is_article_video_draft': False, 'draft_is_from_deeplink': 'false', 'draft_materials': [{'type': 0, 'value': entries}, {'type': 1, 'value': audio_entries}, {'type': 2, 'value': []}, {'type': 3, 'value': []}, {'type': 6, 'value': []}, {'type': 7, 'value': []}, {'type': 8, 'value': []}], 'draft_materials_copied_info': [], 'draft_name': name, 'draft_new_version': '164.0.0', 'draft_removable_storage_device': '', 'draft_root_path': draft_root.as_posix(), 'draft_segment_extra_info': [], 'draft_timeline_materials_size_': 0, 'tm_draft_cloud_completed': '', 'tm_draft_cloud_modified': 0, 'tm_draft_create': now_us, 'tm_draft_modified': now_us, 'tm_draft_removed': 0, 'tm_duration': duration}


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _srt(clips: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    for index, clip in enumerate(clips, 1):
        lines.extend([str(index), f'{_format_srt_time(clip["start"])} --> {_format_srt_time(clip["end"])}', clip['text'], ''])
    return '\n'.join(lines)


def _format_srt_time(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}'
