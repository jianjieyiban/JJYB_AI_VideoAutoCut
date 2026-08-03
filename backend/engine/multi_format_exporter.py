#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project: JJYB_AI智剪
@File   : multi_format_exporter.py
@Desc   : 多格式时间线导出引擎 - 融入JJYB-ZJ的导出能力
          支持：Premiere Pro XML / FCPXML / SRT字幕 / CapCut国际剪映草稿 / EDL / ASS
          将统一时间线转换为不同剪辑软件可识别的格式
"""

import os
import json
import logging
import xml.etree.ElementTree as ET
from xml.dom import minidom
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger('JJYB_AI智剪')

# 时间基准（Premiere使用ticks，1秒=2540160000 ticks）
TICKS_PER_SECOND = 2540160000
# FCPXML使用分数，默认1/30秒
FCP_TIMEBASE = 30


def _to_timecode(seconds: float, fps: int = 30) -> str:
    """将秒转换为 HH:MM:SS:FF 时间码"""
    if seconds < 0:
        seconds = 0
    total_frames = int(round(seconds * fps))
    hours, remainder = divmod(total_frames, fps * 3600)
    minutes, remainder = divmod(remainder, fps * 60)
    secs, frames = divmod(remainder, fps)
    return f'{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}'


def _to_ticks(seconds: float) -> int:
    """将秒转换为Premiere ticks"""
    return int(round(seconds * TICKS_PER_SECOND))


def _to_rational(seconds: float, timebase: int = FCP_TIMEBASE) -> str:
    """将秒转换为FCPXML分数格式 (s/30000s)"""
    total = int(round(seconds * timebase))
    return f'{total}/{timebase}s'


def _format_srt_time(seconds: float) -> str:
    """SRT时间格式 HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f'{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03}'


def _format_ass_time(seconds: float) -> str:
    """ASS时间格式 H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0
    centiseconds = int(round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    secs, centiseconds = divmod(remainder, 100)
    return f'{hours:d}:{minutes:02d}:{secs:02d}.{centiseconds:02d}'


@dataclass
class TimelineClip:
    """统一的时间线片段"""
    clip_id: str
    track_type: str  # video / audio / subtitle / text
    source_path: str
    source_start: float = 0.0  # 源素材入点
    source_end: float = 0.0    # 源素材出点
    timeline_start: float = 0.0  # 时间线入点
    timeline_end: float = 0.0    # 时间线出点
    duration: float = 0.0
    # 文本属性（字幕/文字）
    text: str = ''
    # 视觉属性
    scale: float = 1.0
    position_x: float = 0.0
    position_y: float = 0.0
    rotation: float = 0.0
    opacity: float = 1.0
    # 音频属性
    volume: float = 1.0
    # 转场
    transition_in: str = ''
    transition_out: str = ''
    transition_duration: float = 0.5


@dataclass
class TimelineTrack:
    """统一的时间线轨道"""
    track_id: str
    track_type: str  # video / audio / subtitle / text
    name: str = ''
    clips: List[TimelineClip] = field(default_factory=list)


@dataclass
class TimelineProject:
    """统一时间线项目"""
    project_name: str = '未命名项目'
    duration: float = 0.0
    fps: int = 30
    width: int = 1920
    height: int = 1080
    tracks: List[TimelineTrack] = field(default_factory=list)
    assets: List[Dict] = field(default_factory=list)


class MultiFormatExporter:
    """多格式时间线导出器"""

    def __init__(self):
        logger.info("多格式时间线导出引擎初始化完成")

    def export_premiere_xml(self, project: TimelineProject, output_path: str) -> str:
        """导出 Premiere Pro XML 格式（xmeml）"""
        try:
            # 创建 xmeml 根元素
            xmeml = ET.Element('xmeml', version='4')
            sequence = ET.SubElement(xmeml, 'sequence')

            # 序列基本信息
            ET.SubElement(sequence, 'uuid').text = _generate_uuid()
            ET.SubElement(sequence, 'duration').text = str(int(project.duration * project.fps))
            ET.SubElement(sequence, 'rate', {
                'timebase': str(project.fps),
                'ntsc': 'FALSE'
            })
            ET.SubElement(sequence, 'name').text = project.project_name
            media = ET.SubElement(sequence, 'media')
            video = ET.SubElement(media, 'video')
            ET.SubElement(video, 'format')
            vformat = ET.SubElement(video, 'format')
            vchars = ET.SubElement(vformat, 'samplecharacteristics')
            ET.SubElement(vchars, 'rate', {'timebase': str(project.fps), 'ntsc': 'FALSE'})
            ET.SubElement(vchars, 'width').text = str(project.width)
            ET.SubElement(vchars, 'height').text = str(project.height)
            ET.SubElement(vchars, 'pixelaspectratio').text = 'square'
            ET.SubElement(vchars, 'fielddominance').text = 'none'

            # 视频轨道
            video_tracks = [t for t in project.tracks if t.track_type == 'video']
            for track in video_tracks:
                self._add_premiere_video_track(video, track, project.fps)

            # 音频轨道
            audio = ET.SubElement(media, 'audio')
            audio_tracks = [t for t in project.tracks if t.track_type == 'audio']
            for track in audio_tracks:
                self._add_premiere_audio_track(audio, track, project.fps)

            # 美化并写入
            rough = ET.tostring(xmeml, encoding='unicode')
            dom = minidom.parseString(rough)
            pretty = dom.toprettyxml(indent='  ', encoding='UTF-8').decode('UTF-8')

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(pretty)

            logger.info(f'Premiere XML 导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'Premiere XML 导出失败: {e}', exc_info=True)
            raise

    def _add_premiere_video_track(self, parent: ET.Element, track: TimelineTrack, fps: int):
        """添加Premiere视频轨道"""
        trackel = ET.SubElement(parent, 'track')
        for clip in track.clips:
            clipitem = ET.SubElement(trackel, 'clipitem', {'id': f'clip-{clip.clip_id}'})
            ET.SubElement(clipitem, 'name').text = os.path.basename(clip.source_path) or clip.text or 'clip'
            ET.SubElement(clipitem, 'enabled').text = 'TRUE'
            ET.SubElement(clipitem, 'duration').text = str(int(clip.duration * fps))
            ET.SubElement(clipitem, 'rate', {'timebase': str(fps), 'ntsc': 'FALSE'})
            ET.SubElement(clipitem, 'start').text = str(int(clip.timeline_start * fps))
            ET.SubElement(clipitem, 'end').text = str(int(clip.timeline_end * fps))
            ET.SubElement(clipitem, 'in').text = str(int(clip.source_start * fps))
            ET.SubElement(clipitem, 'out').text = str(int(clip.source_end * fps))

            # 文件引用
            fileelem = ET.SubElement(clipitem, 'file', {'id': f'file-{clip.clip_id}'})
            ET.SubElement(fileelem, 'name').text = os.path.basename(clip.source_path) or 'asset'
            ET.SubElement(fileelem, 'pathurl').text = _to_file_url(clip.source_path)

            # 滤镜链（变换）
            if clip.scale != 1.0 or clip.opacity != 1.0:
                filterel = ET.SubElement(clipitem, 'filter')
                ET.SubElement(filterel, 'effect')
                effect = ET.SubElement(filterel, 'effect')
                ET.SubElement(effect, 'name').text = 'Transform'
                # 简化参数
                if clip.opacity != 1.0:
                    paramel = ET.SubElement(effect, 'parameter')
                    ET.SubElement(paramel, 'name').text = 'Opacity'
                    ET.SubElement(paramel, 'value').text = str(int(clip.opacity * 100))

    def _add_premiere_audio_track(self, parent: ET.Element, track: TimelineTrack, fps: int):
        """添加Premiere音频轨道"""
        trackel = ET.SubElement(parent, 'track')
        for clip in track.clips:
            clipitem = ET.SubElement(trackel, 'clipitem', {'id': f'clip-{clip.clip_id}'})
            ET.SubElement(clipitem, 'name').text = os.path.basename(clip.source_path) or 'audio'
            ET.SubElement(clipitem, 'enabled').text = 'TRUE'
            ET.SubElement(clipitem, 'duration').text = str(int(clip.duration * fps))
            ET.SubElement(clipitem, 'rate', {'timebase': str(fps), 'ntsc': 'FALSE'})
            ET.SubElement(clipitem, 'start').text = str(int(clip.timeline_start * fps))
            ET.SubElement(clipitem, 'end').text = str(int(clip.timeline_end * fps))
            ET.SubElement(clipitem, 'in').text = str(int(clip.source_start * fps))
            ET.SubElement(clipitem, 'out').text = str(int(clip.source_end * fps))
            ET.SubElement(clipitem, 'file').set('id', f'file-{clip.clip_id}')

            sels = ET.SubElement(clipitem, 'sourcetrack')
            ET.SubElement(sels, 'mediatype').text = 'audio'
            ET.SubElement(sels, 'trackindex').text = '1'

            # 音量
            if clip.volume != 1.0:
                filterel = ET.SubElement(clipitem, 'filter')
                effect = ET.SubElement(filterel, 'effect')
                ET.SubElement(effect, 'name').text = 'Audio Levels'
                paramel = ET.SubElement(effect, 'parameter')
                ET.SubElement(paramel, 'name').text = 'Level'
                ET.SubElement(paramel, 'value').text = str(_linear_to_db(clip.volume))

    def export_fcpxml(self, project: TimelineProject, output_path: str) -> str:
        """导出 Final Cut Pro X XML (FCPXML) 格式"""
        try:
            fcpxml = ET.Element('fcpxml', version='1.9')
            resources = ET.SubElement(fcpxml, 'resources')

            # 资源
            for asset in project.assets:
                fmt = ET.SubElement(resources, 'format',
                    {'id': f'f-{asset.get("id", "default")}',
                     'frameDuration': _to_rational(1 / project.fps),
                     'width': str(asset.get('width', project.width)),
                     'height': str(asset.get('height', project.height))})
                asset_el = ET.SubElement(resources, 'asset',
                    {'id': f'a-{asset.get("id", "default")}',
                     'name': asset.get('name', 'asset'),
                     'src': _to_file_url(asset.get('path', '')),
                     'format': f'f-{asset.get("id", "default")}',
                     'duration': _to_rational(asset.get('duration', project.duration))})
                media_rep = ET.SubElement(asset_el, 'media-rep',
                    {'kind': 'original-media'})

            # 事件与序列
            library = ET.SubElement(fcpxml, 'library')
            event = ET.SubElement(library, 'event', {'name': project.project_name})
            seq = ET.SubElement(event, 'project', {'name': project.project_name})
            sequence = ET.SubElement(seq, 'sequence',
                {'duration': _to_rational(project.duration),
                 'format': f'f-default',
                 'tcStart': '0s',
                 'tcFormat': 'NDF'})

            spine = ET.SubElement(sequence, 'spine')

            # 视频片段
            for track in project.tracks:
                if track.track_type == 'video':
                    for clip in track.clips:
                        asset_clip = ET.SubElement(spine, 'asset-clip',
                            {'name': os.path.basename(clip.source_path) or 'clip',
                             'ref': f'a-{clip.clip_id}',
                             'offset': _to_rational(clip.timeline_start),
                             'duration': _to_rational(clip.duration),
                             'start': _to_rational(clip.source_start),
                             'tcFormat': 'NDF'})
                        if clip.scale != 1.0:
                            params = ET.SubElement(asset_clip, 'adjust-transform')
                            ET.SubElement(params, 'param', {'name': 'Scale', 'value': str(clip.scale)})
                        if clip.opacity != 1.0:
                            params = ET.SubElement(asset_clip, 'adjust-opacity')
                            ET.SubElement(params, 'param', {'name': 'Opacity', 'value': str(clip.opacity)})

            # 音频片段（添加到spine外层）
            for track in project.tracks:
                if track.track_type == 'audio':
                    for clip in track.clips:
                        ET.SubElement(spine, 'asset-clip',
                            {'name': os.path.basename(clip.source_path) or 'audio',
                             'role': 'dialogue',
                             'ref': f'a-{clip.clip_id}',
                             'offset': _to_rational(clip.timeline_start),
                             'duration': _to_rational(clip.duration),
                             'start': _to_rational(clip.source_start)})

            # 字幕
            for track in project.tracks:
                if track.track_type in ('subtitle', 'text'):
                    for clip in track.clips:
                        title = ET.SubElement(spine, 'title',
                            {'name': '字幕',
                             'offset': _to_rational(clip.timeline_start),
                             'duration': _to_rational(clip.duration),
                             'ref': 'r1'})
                        text = ET.SubElement(title, 'text')
                        ET.SubElement(text, 'text-style',
                            {'ref': 'ts1'})
                        title.text = clip.text

            # 美化
            rough = ET.tostring(fcpxml, encoding='unicode')
            dom = minidom.parseString(rough)
            pretty = dom.toprettyxml(indent='  ', encoding='UTF-8').decode('UTF-8')

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(pretty)

            logger.info(f'FCPXML 导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'FCPXML 导出失败: {e}', exc_info=True)
            raise

    def export_srt(self, project: TimelineProject, output_path: str) -> str:
        """导出 SRT 字幕文件"""
        try:
            srt_lines = []
            index = 1
            for track in project.tracks:
                if track.track_type in ('subtitle', 'text'):
                    for clip in track.clips:
                        if not clip.text.strip():
                            continue
                        srt_lines.append(str(index))
                        srt_lines.append(
                            f'{_format_srt_time(clip.timeline_start)} --> {_format_srt_time(clip.timeline_end)}'
                        )
                        srt_lines.append(clip.text.strip())
                        srt_lines.append('')
                        index += 1

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(srt_lines))

            logger.info(f'SRT 字幕导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'SRT 导出失败: {e}', exc_info=True)
            raise

    def export_ass(self, project: TimelineProject, output_path: str,
                   style_name: str = 'Default',
                   font_name: str = 'Microsoft YaHei',
                   font_size: int = 48,
                   primary_color: str = '&H00FFFFFF') -> str:
        """导出 ASS 字幕文件（带样式）"""
        try:
            header = f"""[Script Info]
Script Type: v4.00+
PlayResX: {project.width}
PlayResY: {project.height}
Aspect Ratio: {project.width}:{project.height}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: {style_name},{font_name},{font_size},{primary_color},&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,80,80,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
            lines = [header]
            for track in project.tracks:
                if track.track_type in ('subtitle', 'text'):
                    for clip in track.clips:
                        if not clip.text.strip():
                            continue
                        start = _format_ass_time(clip.timeline_start)
                        end = _format_ass_time(clip.timeline_end)
                        text = clip.text.strip().replace('\n', '\\N')
                        lines.append(
                            f'Dialogue: 0,{start},{end},{style_name},,0,0,0,,{text}'
                        )

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            logger.info(f'ASS 字幕导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'ASS 导出失败: {e}', exc_info=True)
            raise

    def export_edl(self, project: TimelineProject, output_path: str, title: str = '') -> str:
        """导出 EDL (Edit Decision List) 格式"""
        try:
            lines = [
                f'TITLE: {title or project.project_name}',
                f'FCM: NON-DROP FRAME',
                ''
            ]
            event_num = 1
            for track in project.tracks:
                if track.track_type != 'video':
                    continue
                for clip in track.clips:
                    src_tc_in = _to_timecode(clip.source_start, project.fps)
                    src_tc_out = _to_timecode(clip.source_end, project.fps)
                    rec_tc_in = _to_timecode(clip.timeline_start, project.fps)
                    rec_tc_out = _to_timecode(clip.timeline_end, project.fps)
                    src_name = os.path.basename(clip.source_path).upper().split('.')[0]
                    lines.append(
                        f'{event_num:03d}  AX       AA/V  C        {src_tc_in} {src_tc_out} {rec_tc_in} {rec_tc_out}'
                    )
                    lines.append(f'FROM CLIP NAME: {os.path.basename(clip.source_path)}')
                    lines.append(f'SOURCE FILE: {src_name}')
                    lines.append('')
                    event_num += 1

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            logger.info(f'EDL 导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'EDL 导出失败: {e}', exc_info=True)
            raise

    def export_capcut_draft(self, project: TimelineProject, output_path: str,
                            draft_dir: Optional[str] = None) -> str:
        """
        导出国际版剪映（CapCut）草稿格式

        CapCut草稿结构：
        - draft_info.json (主入口)
        - /material_IO/ (素材目录)
        """
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            draft = {
                'version': '1.0.0',
                'create_time': int(datetime.now(timezone.utc).astimezone().timestamp()),
                'last_modified': int(datetime.now(timezone.utc).astimezone().timestamp()),
                'draft_name': project.project_name,
                'duration': int(project.duration * 1_000_000),  # 微秒
                'fps': project.fps,
                'canvas_config': {
                    'width': project.width,
                    'height': project.height,
                    'ratio': 'original'
                },
                'materials': {
                    'videos': [],
                    'audios': [],
                    'texts': [],
                    'stickers': [],
                    'effects': [],
                    'transitions': [],
                    'video_effects': [],
                    'sound_channels': []
                },
                'tracks': [],
                'id': _generate_uuid(),
                'canvas_id': _generate_uuid(),
                'last_tx_asset_id': '',
                'source': 'JJYB_AI智剪'
            }

            # 构建素材列表
            material_map = {}  # path -> material_id
            for asset in project.assets:
                mat_id = _generate_uuid()
                material_map[asset.get('path', '')] = mat_id
                mat_type = asset.get('type', 'video')
                if mat_type in ('video', 'image'):
                    draft['materials']['videos'].append({
                        'id': mat_id,
                        'type': mat_type,
                        'path': asset.get('path', ''),
                        'name': asset.get('name', 'asset'),
                        'duration': int(asset.get('duration', 0) * 1_000_000),
                        'width': asset.get('width', project.width),
                        'height': asset.get('height', project.height),
                        'stable_level': 0,
                        'intensifies_path': '',
                        'intensifies_audio_path': '',
                        'source_platform': 0,
                        'request_id': '',
                        'extra_material_refs': []
                    })
                elif mat_type == 'audio':
                    draft['materials']['audios'].append({
                        'id': mat_id,
                        'type': 'audio',
                        'path': asset.get('path', ''),
                        'name': asset.get('name', 'audio'),
                        'duration': int(asset.get('duration', 0) * 1_000_000),
                        'source_platform': 0,
                        'request_id': '',
                        'team_id': '',
                        'name_pinyin': '',
                        'text_id': '',
                        'tone_category_id': '',
                        'text_path': '',
                        'category_id': '',
                        'category_ids': [],
                        'init_text': '',
                        'language': '',
                        'local_id': '',
                        'local_material_id': '',
                        'extra_material_refs': []
                    })

            # 构建轨道
            for track in project.tracks:
                track_type_map = {
                    'video': 'video',
                    'audio': 'audio',
                    'subtitle': 'text',
                    'text': 'text'
                }
                capcut_track_type = track_type_map.get(track.track_type, 'video')
                capcut_track = {
                    'id': _generate_uuid(),
                    'type': capcut_track_type,
                    'segments': [],
                    'attribute': 0,
                    'flag': 0,
                    'render': {
                        'id': _generate_uuid(),
                        'canvas_id': draft['canvas_id'],
                        'type': 0,
                        'alpha': 1.0,
                        'transform': {
                            'x': 0,
                            'y': 0
                        }
                    }
                }

                for clip in track.clips:
                    mat_id = material_map.get(clip.source_path, '')
                    segment = {
                        'id': _generate_uuid(),
                        'track_id': capcut_track['id'],
                        'source_timerange': {
                            'start': int(clip.source_start * 1_000_000),
                            'duration': int(clip.duration * 1_000_000)
                        },
                        'target_timerange': {
                            'start': int(clip.timeline_start * 1_000_000),
                            'duration': int(clip.duration * 1_000_000)
                        },
                        'material_id': mat_id,
                        'extra_material_refs': [],
                        'source': ' jjyb',
                        'scale': {'x': clip.scale, 'y': clip.scale},
                        'transform': {'x': clip.position_x, 'y': clip.position_y},
                        'rotation': clip.rotation,
                        'clip': {
                            'alpha': clip.opacity,
                            'transform': {'x': 0, 'y': 0},
                            'scale': {'x': 1.0, 'y': 1.0}
                        },
                        'common_keyframes': [],
                        'volume': clip.volume,
                        'render_index': 0,
                        'is_placeholder': False,
                        'is_tone_parse': False,
                        'responsive_layout': {'enable': False, 'target_follow': None, 'origin_pos': []},
                        'responsive_layout_enabled': False,
                        'source_platform': 0
                    }

                    if capcut_track_type == 'text' and clip.text:
                        # 文本素材
                        text_mat_id = _generate_uuid()
                        draft['materials']['texts'].append({
                            'id': text_mat_id,
                            'type': 'subtitle',
                            'text': clip.text,
                            'duration': int(clip.duration * 1_000_000),
                            'text_style': {
                                'content': clip.text,
                                'font_family': '',
                                'font_size': 48,
                                'font_color': '#FFFFFFFF',
                                'background_color': '#00000000',
                                'alignment': 1,
                                'bold': False,
                                'italic': False,
                                'underline': False
                            },
                            'text_source': 'jjyb_subtitle',
                            'extra_material_refs': []
                        })
                        segment['material_id'] = text_mat_id

                    capcut_track['segments'].append(segment)

                draft['tracks'].append(capcut_track)

            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(draft, f, ensure_ascii=False, indent=2)

            logger.info(f'CapCut 草稿导出完成: {output_path}')
            return output_path
        except Exception as e:
            logger.error(f'CapCut 草稿导出失败: {e}', exc_info=True)
            raise

    def export_all_formats(self, project: TimelineProject, output_dir: str,
                           formats: Optional[List[str]] = None) -> Dict[str, str]:
        """批量导出所有格式"""
        if formats is None:
            formats = ['premiere_xml', 'fcpxml', 'srt', 'ass', 'edl', 'capcut']

        os.makedirs(output_dir, exist_ok=True)
        results = {}
        safe_name = _sanitize_filename(project.project_name)

        for fmt in formats:
            try:
                if fmt == 'premiere_xml':
                    path = os.path.join(output_dir, f'{safe_name}.xml')
                    results[fmt] = self.export_premiere_xml(project, path)
                elif fmt == 'fcpxml':
                    path = os.path.join(output_dir, f'{safe_name}.fcpxml')
                    results[fmt] = self.export_fcpxml(project, path)
                elif fmt == 'srt':
                    path = os.path.join(output_dir, f'{safe_name}.srt')
                    results[fmt] = self.export_srt(project, path)
                elif fmt == 'ass':
                    path = os.path.join(output_dir, f'{safe_name}.ass')
                    results[fmt] = self.export_ass(project, path)
                elif fmt == 'edl':
                    path = os.path.join(output_dir, f'{safe_name}.edl')
                    results[fmt] = self.export_edl(project, path)
                elif fmt == 'capcut':
                    path = os.path.join(output_dir, f'{safe_name}_capcut.json')
                    results[fmt] = self.export_capcut_draft(project, path)
            except Exception as e:
                logger.error(f'导出 {fmt} 失败: {e}')
                results[fmt] = f'ERROR: {e}'

        return results

    @staticmethod
    def from_universal_timeline(timeline_data: Dict) -> TimelineProject:
        """从通用时间线数据构建TimelineProject"""
        project = TimelineProject(
            project_name=timeline_data.get('project_name', '未命名项目'),
            duration=float(timeline_data.get('duration', 0)),
            fps=int(timeline_data.get('fps', 30)),
            width=int(timeline_data.get('width', 1920)),
            height=int(timeline_data.get('height', 1080)),
        )

        # 资产列表
        project.assets = timeline_data.get('assets', [])

        # 轨道
        for track_data in timeline_data.get('tracks', []):
            track = TimelineTrack(
                track_id=track_data.get('id', _generate_uuid()),
                track_type=track_data.get('type', 'video'),
                name=track_data.get('name', '')
            )
            for clip_data in track_data.get('clips', []):
                clip = TimelineClip(
                    clip_id=clip_data.get('id', _generate_uuid()),
                    track_type=track.track_type,
                    source_path=clip_data.get('source', clip_data.get('path', '')),
                    source_start=float(clip_data.get('source_start', 0)),
                    source_end=float(clip_data.get('source_end', clip_data.get('source_start', 0) + clip_data.get('duration', 0))),
                    timeline_start=float(clip_data.get('start', clip_data.get('timeline_start', 0))),
                    timeline_end=float(clip_data.get('end', clip_data.get('timeline_start', 0) + clip_data.get('duration', 0))),
                    duration=float(clip_data.get('duration', 0)),
                    text=str(clip_data.get('text', '')),
                    scale=float(clip_data.get('scale', 1.0)),
                    position_x=float(clip_data.get('position_x', 0)),
                    position_y=float(clip_data.get('position_y', 0)),
                    rotation=float(clip_data.get('rotation', 0)),
                    opacity=float(clip_data.get('opacity', 1.0)),
                    volume=float(clip_data.get('volume', 1.0)),
                    transition_in=str(clip_data.get('transition_in', '')),
                    transition_out=str(clip_data.get('transition_out', '')),
                    transition_duration=float(clip_data.get('transition_duration', 0.5))
                )
                track.clips.append(clip)
            project.tracks.append(track)

        return project


def _generate_uuid() -> str:
    """生成UUID（不带横线）"""
    import uuid as _uuid
    return _uuid.uuid4().hex


def _to_file_url(path: str) -> str:
    """转换为file:// URL"""
    if not path:
        return ''
    abs_path = os.path.abspath(path)
    return 'file://localhost/' + abs_path.replace('\\', '/').lstrip('/')


def _linear_to_db(linear: float) -> float:
    """线性音量转换为dB（1.0=0dB，0.5≈-6dB，2.0=+6dB）"""
    if linear <= 0:
        return -999.0
    return _safe_log(linear)


def _safe_log(value: float) -> float:
    """安全的对数计算"""
    import math
    if value <= 0:
        return -999.0
    return round(20 * math.log10(value), 2)


def _sanitize_filename(name: str) -> str:
    """清理文件名"""
    import re
    cleaned = re.sub(r'[\\/:*?"<>|]', '_', name or 'project')
    return cleaned.strip(' .')[:100] or 'project'
