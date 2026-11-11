import importlib.util
import json
from fractions import Fraction
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / 'backend/engine/multi_format_exporter.py'
spec = importlib.util.spec_from_file_location('multi_format_exporter_under_test', MODULE_PATH)
exporter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = exporter
spec.loader.exec_module(exporter)


def make_project(fps=30, speed=1):
    video = exporter.TimelineClip('v1', 'video', '素材 #1.mov', 3, 3 + 2 * speed, 1, 3, 2, opacity=0.5)
    audio = exporter.TimelineClip('a1', 'audio', '配音 #1.wav', 4, 6, 0, 2, 2)
    return exporter.TimelineProject(duration=4, fps=fps, tracks=[
        exporter.TimelineTrack('v', 'video', clips=[video]),
        exporter.TimelineTrack('a', 'audio', clips=[audio]),
    ])


def seconds(value):
    return Fraction(value.removesuffix('s'))


@pytest.mark.parametrize('clip, expected', [
    ({'start': 5, 'duration': 2}, (5, 7, 2)),
    ({'start': 5, 'end': 8}, (5, 8, 3)),
    ({'timeline_start': 5, 'timeline_end': 9}, (5, 9, 4)),
    ({'start': 5, 'source_start': 2, 'source_end': 6}, (5, 9, 4)),
])
def test_universal_timing_is_consistent(clip, expected):
    project = exporter.MultiFormatExporter.from_universal_timeline({'tracks': [{'clips': [clip]}]})
    item = project.tracks[0].clips[0]
    assert (item.timeline_start, item.timeline_end, item.duration) == expected
    assert item.source_end - item.source_start == expected[2]
    assert project.duration == expected[1]


def test_windows_source_paths_use_valid_file_uris():
    assert exporter._to_file_url(r'C:\素材\剪辑 #1.mp4') == 'file://localhost/C:/%E7%B4%A0%E6%9D%90/%E5%89%AA%E8%BE%91%20%231.mp4'


def test_universal_rejects_conflicting_timeline_end_and_duration():
    with pytest.raises(ValueError, match='时长|duration|结束'):
        exporter.MultiFormatExporter.from_universal_timeline({
            'tracks': [{'clips': [{'start': 0, 'end': 5, 'duration': 2}]}]
        })


def test_premiere_has_child_rates_and_no_empty_nodes(tmp_path):
    path = tmp_path / 'edit.xml'
    exporter.MultiFormatExporter().export_premiere_xml(make_project(), str(path))
    root = ET.parse(path)
    for rate in root.findall('.//rate'):
        assert not rate.attrib
        assert rate.findtext('timebase') == '30'
        assert rate.findtext('ntsc') == 'FALSE'
    assert len(root.findall('.//video/format')) == 1
    assert all(len(node) for node in root.findall('.//effect'))
    for file in root.findall('.//clipitem/file'):
        assert '%23' in file.findtext('pathurl', '')
        assert '%20' in file.findtext('pathurl', '')


@pytest.mark.parametrize('track_type', ['video', 'audio'])
def test_premiere_writes_timeremap(tmp_path, track_type):
    project = make_project(speed=2)
    project.tracks[1].clips[0].source_end = 8
    path = tmp_path / 'speed.xml'
    exporter.MultiFormatExporter().export_premiere_xml(project, str(path))
    clip = ET.parse(path).find(f'.//media/{track_type}/track/clipitem')
    effect = clip.find("filter/effect[effectid='timeremap']")
    assert effect is not None
    assert effect.find("parameter[parameterid='speed']/value").text == '200.0'


@pytest.mark.parametrize('fps', [24, 30, 60])
def test_fcpxml_resources_resolve_and_use_project_fps(tmp_path, fps):
    project = make_project(fps)
    project.assets = [{'id': 'unrelated', 'path': project.tracks[0].clips[0].source_path, 'duration': 10}]
    path = tmp_path / 'edit.fcpxml'
    exporter.MultiFormatExporter().export_fcpxml(project, str(path))
    root = ET.parse(path).getroot()
    ids = {node.get('id'): node for node in root.iter() if node.get('id')}
    for node in root.iter():
        if node.get('ref'):
            assert node.get('ref') in ids
        if node.get('format'):
            assert node.get('format') in ids
    fmt = ids[root.find('.//sequence').get('format')]
    assert seconds(fmt.get('frameDuration')) == Fraction(1, fps)
    assert len(root.findall('resources/asset')) == 2
    for asset in root.findall('resources/asset'):
        assert '%23' in asset.find('media-rep').get('src', '')
    clips = root.findall('.//asset-clip')
    assert len(clips) == 2
    assert {seconds(c.get('start')) for c in clips} == {3, 4}
    gap = root.find('.//spine/gap')
    assert gap is not None and seconds(gap.get('duration')) == 4
    assert all(c.get('lane') for c in clips)
    assert next(c for c in clips if c.get('audioRole') == 'dialogue').get('lane').startswith('-')


def test_fcpxml_reuses_source_path_and_encodes_speed(tmp_path):
    project = make_project(speed=2)
    project.tracks[0].clips.append(exporter.TimelineClip('v2', 'video', project.tracks[0].clips[0].source_path, 0, 1, 3, 4, 1))
    path = tmp_path / 'speed.fcpxml'
    exporter.MultiFormatExporter().export_fcpxml(project, str(path))
    root = ET.parse(path)
    videos = [c for c in root.findall('.//asset-clip') if not c.get('audioRole')]
    assert videos[0].get('ref') == videos[1].get('ref')
    clip = videos[0]
    assert seconds(clip.get('start')) == 0
    points = clip.findall('timeMap/timept')
    assert [(seconds(p.get('time')), seconds(p.get('value'))) for p in points] == [(0, 3), (2, 7)]


def test_fcpxml_rejects_unsupported_titles_without_writing(tmp_path):
    project = make_project()
    project.tracks.append(exporter.TimelineTrack('s', 'subtitle', clips=[exporter.TimelineClip('s1', 'subtitle', '', text='字幕')]))
    path = tmp_path / 'title.fcpxml'
    with pytest.raises(ValueError, match='字幕|title|subtitle'):
        exporter.MultiFormatExporter().export_fcpxml(project, str(path))
    assert not path.exists()


def test_edl_rejects_speed_instead_of_silently_losing_it(tmp_path):
    with pytest.raises(ValueError, match='变速|speed'):
        exporter.MultiFormatExporter().export_edl(make_project(speed=2), str(tmp_path / 'edit.edl'))


@pytest.mark.parametrize('method,suffix', [
    ('export_fcpxml', 'fcpxml'), ('export_capcut_draft', 'json')
])
def test_export_rejects_source_window_beyond_known_asset_duration(tmp_path, method, suffix):
    project = make_project()
    project.assets = [{'path': project.tracks[0].clips[0].source_path, 'duration': 2}]
    path = tmp_path / f'invalid.{suffix}'
    with pytest.raises(ValueError, match='素材时长|源区间'):
        getattr(exporter.MultiFormatExporter(), method)(project, str(path))
    assert not path.exists()


def test_capcut_reference_materials_and_speed(tmp_path):
    project = make_project(speed=2)
    project.tracks.append(exporter.TimelineTrack('s', 'subtitle', clips=[exporter.TimelineClip('s1', 'subtitle', '', duration=1, timeline_end=1)]))
    path = tmp_path / 'reference.json'
    exporter.MultiFormatExporter().export_capcut_draft(project, str(path))
    draft = json.loads(path.read_text(encoding='utf-8'))
    ids = {m['id'] for group in draft['materials'].values() for m in group}
    for track in draft['tracks']:
        for segment in track['segments']:
            assert segment['material_id'] in ids
    video = draft['tracks'][0]['segments'][0]
    assert video['source_timerange'] == {'start': 3000000, 'duration': 4000000}
    assert video['target_timerange']['duration'] == 2000000
    assert video['speed'] == 2


def test_ass_does_not_interpret_user_override_tags(tmp_path):
    project = exporter.TimelineProject(tracks=[exporter.TimelineTrack('s', 'subtitle', clips=[
        exporter.TimelineClip('s1', 'subtitle', '', text=r'{\b1}hello' + '\nnext', duration=1, timeline_end=1)
    ])])
    path = tmp_path / 'subtitle.ass'
    exporter.MultiFormatExporter().export_ass(project, str(path))
    text = path.read_text(encoding='utf-8')
    assert r'{\b1}' not in text
    assert r'\Nnext' in text


@pytest.mark.parametrize('method,suffix', [
    ('export_premiere_xml', 'xml'), ('export_fcpxml', 'fcpxml'),
    ('export_srt', 'srt'), ('export_ass', 'ass'),
    ('export_edl', 'edl'), ('export_capcut_draft', 'json'),
])
def test_filename_only_output(tmp_path, monkeypatch, method, suffix):
    monkeypatch.chdir(tmp_path)
    path = f'output.{suffix}'
    assert getattr(exporter.MultiFormatExporter(), method)(make_project(), path) == path
    assert Path(path).is_file()
