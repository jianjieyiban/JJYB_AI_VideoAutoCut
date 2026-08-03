# -*- coding: utf-8 -*-
"""通用时间线草稿包导出接口（不生成剪映私有工程文件）。"""

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

from backend.config.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.aac', '.m4a', '.ogg', '.flac', '.opus'}
VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.mkv', '.flv', '.wmv', '.webm'}
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


def register_jianying_draft_routes(app, db_manager):
    """注册通用时间线草稿包导出路由。"""

    def resolve_project_file(raw_path):
        """只接受项目根目录内的现有文件，避免导出接口读取任意本机文件。"""
        if not raw_path or not isinstance(raw_path, str):
            return None
        normalized = raw_path.split('?', 1)[0].lstrip('/').replace('/', '\\')
        source = Path(normalized)
        if not source.is_absolute():
            source = PROJECT_ROOT / source
        try:
            source = source.resolve()
            source.relative_to(PROJECT_ROOT.resolve())
        except (OSError, ValueError):
            return None
        return source if source.is_file() else None

    def parse_json(value, fallback):
        if isinstance(value, dict) or isinstance(value, list):
            return value
        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback

    def sanitize_filename(name, fallback):
        stem = re.sub(r'[^\w.\-\u4e00-\u9fff]+', '_', Path(name or fallback).name).strip('._')
        return stem or fallback

    def format_srt_time(seconds):
        milliseconds = max(0, int(round(float(seconds) * 1000)))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        secs, milliseconds = divmod(remainder, 1000)
        return f'{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}'

    def collect_project_assets(project, request_assets):
        """合并数据库素材与请求中的当前音频/素材，并按传入顺序去重。"""
        candidates = []
        for item in request_assets or []:
            if isinstance(item, str):
                candidates.append({'path': item})
            elif isinstance(item, dict):
                candidates.append(item)

        if project:
            for material in project.get('materials', []):
                metadata = parse_json(material.get('metadata'), {})
                candidates.append({
                    'path': material.get('path'),
                    'name': material.get('name'),
                    'type': material.get('type'),
                    'duration': material.get('duration'),
                    'metadata': metadata,
                })
            config = parse_json(project.get('config'), {})
            for key in ('audio_path', 'audio_url', 'material_path'):
                if config.get(key):
                    candidates.append({'path': config[key]})

        assets = []
        seen = set()
        for item in candidates:
            source = resolve_project_file(item.get('path'))
            if not source or source in seen:
                continue
            seen.add(source)
            suffix = source.suffix.lower()
            asset_type = item.get('type') or (
                'audio' if suffix in AUDIO_EXTENSIONS else
                'video' if suffix in VIDEO_EXTENSIONS else
                'image' if suffix in IMAGE_EXTENSIONS else 'file'
            )
            assets.append({
                'source': source,
                'name': item.get('name') or source.name,
                'type': asset_type,
                'duration': item.get('duration'),
                'metadata': item.get('metadata') or {},
            })
        return assets

    def normalize_subtitles(raw_subtitles, fallback_text, total_duration):
        subtitles = []
        if isinstance(raw_subtitles, list):
            for item in raw_subtitles:
                if not isinstance(item, dict) or not str(item.get('text') or '').strip():
                    continue
                start = float(item.get('start', item.get('start_sec', 0)) or 0)
                end = float(item.get('end', item.get('end_sec', start + 1)) or start + 1)
                subtitles.append({'text': str(item['text']).strip(), 'start': max(0, start), 'end': max(start + 0.01, end)})
        if subtitles or not fallback_text:
            return subtitles

        lines = [line.strip() for line in re.split(r'[\n。！？!?]+', str(fallback_text)) if line.strip()]
        if not lines:
            return []
        duration = max(float(total_duration or 0), len(lines) * 2.0)
        interval = duration / len(lines)
        return [
            {'text': text, 'start': round(index * interval, 3), 'end': round((index + 1) * interval, 3)}
            for index, text in enumerate(lines)
        ]

    @app.route('/api/jianying-drafts/export', methods=['POST'])
    def export_jianying_draft_package():
        """导出可复用媒体、JSON 时间线和可选 SRT 的通用草稿包。"""
        data = request.get_json(silent=True) or {}
        project_id = data.get('project_id')
        project = db_manager.get_project(project_id) if project_id else None
        if project_id and not project:
            return jsonify({'code': 1, 'msg': '项目不存在', 'data': None}), 404

        request_assets = data.get('assets') or []
        assets = collect_project_assets(project, request_assets)
        if not assets:
            return jsonify({'code': 1, 'msg': '没有可导出的有效音频或素材文件', 'data': None}), 400

        draft_id = f"draft_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        draft_dir = PROJECT_ROOT / 'output' / 'jianying_drafts' / draft_id
        assets_dir = draft_dir / 'assets'
        assets_dir.mkdir(parents=True, exist_ok=False)

        copied_assets = []
        try:
            for index, asset in enumerate(assets, start=1):
                source = asset['source']
                target_name = f'{index:03d}_{sanitize_filename(asset["name"], source.name)}'
                if not target_name.lower().endswith(source.suffix.lower()):
                    target_name += source.suffix
                target = assets_dir / target_name
                shutil.copy2(source, target)
                copied_assets.append({
                    'id': f'asset_{index:03d}',
                    'type': asset['type'],
                    'name': asset['name'],
                    'source_path': str(source.relative_to(PROJECT_ROOT)).replace('\\', '/'),
                    'path': f'assets/{target_name}',
                    'size': target.stat().st_size,
                    'duration': asset['duration'],
                    'metadata': asset['metadata'],
                })

            timeline_input = data.get('timeline') if isinstance(data.get('timeline'), dict) else {}
            tracks = timeline_input.get('tracks') if isinstance(timeline_input.get('tracks'), list) else []

            # 优先复用项目 config.tracks（三大功能写入的统一时间线），
            # 避免每次都从 assets 简单拼接。
            if not tracks and project:
                project_config = parse_json(project.get('config'), {}) or {}
                project_tracks = project_config.get('tracks') if isinstance(project_config, dict) else None
                if isinstance(project_tracks, list) and project_tracks:
                    tracks = project_tracks
                    logger.info('使用项目 config.tracks 构建草稿包时间线')

            if not tracks:
                tracks = [{'id': 'media', 'type': 'media', 'clips': []}]
                current_time = 0.0
                for asset in copied_assets:
                    duration = float(asset['duration'] or 0)
                    tracks[0]['clips'].append({
                        'asset_id': asset['id'], 'start': round(current_time, 3),
                        'duration': duration if duration > 0 else None,
                        'type': asset['type'],
                    })
                    if duration > 0:
                        current_time += duration
            total_duration = timeline_input.get('duration') or max(
                [float(asset['duration'] or 0) for asset in copied_assets] + [0]
            )
            subtitles = normalize_subtitles(data.get('subtitles'), data.get('subtitle_text'), total_duration)
            if subtitles:
                tracks.append({'id': 'subtitles', 'type': 'subtitle', 'clips': subtitles})

            timeline = {
                'format': 'jjyb-generic-timeline/v1',
                'project_id': project_id,
                'project_name': (project or {}).get('name') or data.get('project_name') or '未命名项目',
                'duration': total_duration,
                'assets': copied_assets,
                'tracks': tracks,
            }
            manifest = {
                'format': 'jjyb-jianying-import-package/v1',
                'draft_id': draft_id,
                'created_at': datetime.now(timezone.utc).astimezone().isoformat(),
                'project_id': project_id,
                'project_name': timeline['project_name'],
                'asset_count': len(copied_assets),
                'subtitle_count': len(subtitles),
                'files': ['manifest.json', 'timeline.json', 'instructions.json', 'assets/'] + (['subtitles.srt'] if subtitles else []),
                'compatibility': 'generic_timeline_package',
            }
            instructions = {
                'package_type': '通用时间线草稿包',
                'direct_jianying_project': False,
                'limitation': '未使用已验证的剪映私有工程 schema；此包不能保证被剪映直接打开。请在剪映中导入 assets/ 内媒体，并按 timeline.json 的时间线放置；如有 subtitles.srt，可导入字幕。',
                'import_steps': [
                    '在剪映中新建项目。',
                    '导入 assets/ 中按序号排列的媒体文件。',
                    '参考 timeline.json 的 tracks 和 clips 放置媒体。',
                    '存在 subtitles.srt 时，在剪映中导入该字幕文件。',
                ],
            }
            for filename, content in (
                ('manifest.json', manifest), ('timeline.json', timeline), ('instructions.json', instructions),
            ):
                (draft_dir / filename).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
            if subtitles:
                srt_lines = []
                for index, subtitle in enumerate(subtitles, start=1):
                    srt_lines.extend([
                        str(index),
                        f'{format_srt_time(subtitle["start"])} --> {format_srt_time(subtitle["end"])}',
                        subtitle['text'],
                        '',
                    ])
                (draft_dir / 'subtitles.srt').write_text('\n'.join(srt_lines), encoding='utf-8')
            archive_path = Path(shutil.make_archive(
                str(draft_dir.parent / draft_id), 'zip', root_dir=str(draft_dir)
            ))
        except Exception as exc:
            shutil.rmtree(draft_dir, ignore_errors=True)
            logger.exception('导出通用时间线草稿包失败')
            return jsonify({'code': 1, 'msg': f'导出失败: {exc}', 'data': None}), 500

        relative_dir = str(draft_dir.relative_to(PROJECT_ROOT)).replace('\\', '/')
        manifest_url = f'/output/jianying_drafts/{draft_id}/manifest.json'
        return jsonify({
            'code': 0,
            'msg': '已导出通用时间线草稿包，需在剪映中导入媒体',
            'data': {
                'draft_id': draft_id,
                'directory': relative_dir,
                'directory_url': f'/output/jianying_drafts/{draft_id}/',
                'download_url': f'/output/jianying_drafts/{archive_path.name}',
                'manifest_url': manifest_url,
                'timeline_url': f'/output/jianying_drafts/{draft_id}/timeline.json',
                'instructions_url': f'/output/jianying_drafts/{draft_id}/instructions.json',
                'subtitles_url': f'/output/jianying_drafts/{draft_id}/subtitles.srt' if subtitles else None,
                'compatibility': 'generic_timeline_package',
                'limitation': '通用时间线草稿包，需在剪映中导入媒体，不能保证直接打开为剪映工程。',
            },
        })

    logger.info('✅ 通用时间线草稿包导出路由注册完成')
