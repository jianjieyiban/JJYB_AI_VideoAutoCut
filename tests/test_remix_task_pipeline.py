import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import Mock

import pytest

from backend.engine.video_processor import VideoProcessor
from backend.services import task_service
from backend.api import remix_api
from flask import Flask
from backend.services.task_service import TaskService


@pytest.fixture
def workdir():
    # Never put generated media in the workspace (including pytest's basetemp).
    with tempfile.TemporaryDirectory(prefix='remix-pipeline-') as directory:
        yield Path(directory)


@pytest.fixture
def service(monkeypatch, workdir):
    instance = TaskService.__new__(TaskService)
    instance.base_dir = workdir
    instance.db_manager = Mock()
    instance.socketio = Mock()
    from backend.services import checkpoint_service
    monkeypatch.setattr(checkpoint_service, 'get_checkpoint_service', lambda: Mock())
    return instance


def completed_output(service):
    call = service.db_manager.update_task_status.call_args
    assert call.args[1] == 'completed', call
    return call.kwargs['output_data']


def beat_engine(monkeypatch, matches):
    engine = Mock(librosa_available=True, cv2_available=True)
    engine.create_beat_remix.return_value = {'beat_matches': matches}
    monkeypatch.setattr(task_service, 'get_beat_remix_engine', lambda: engine)


def test_music_timeline_preserves_export_speed(service, workdir, monkeypatch):
    source = workdir / 'source.mp4'
    source.touch()
    bgm = workdir / 'music.wav'
    bgm.touch()
    processor = Mock()
    processor.get_video_info.return_value = {'duration': 1.0, 'has_audio': True}

    def render(*args, **kwargs):
        Path(args[1]).touch()
        return True

    processor.cut_video_with_speed.side_effect = render
    processor.convert_video.side_effect = render
    service.video_processor = processor
    beat_engine(monkeypatch, [{
        'clip_path': str(source), 'source_start': 0, 'source_end': 1.5,
        'output_duration': 1.0, 'playback_speed': 1.5,
        'start_time': 0, 'end_time': 1.0,
    }])

    def fake_ffmpeg(command, **kwargs):
        Path(command[-1]).touch()
        return Mock(returncode=0)

    monkeypatch.setattr(task_service.subprocess, 'run', fake_ffmpeg)
    service._run_remix_task('speed', {'plan': {
        'mode': 'music', 'video_paths': [str(source)],
        'bgm_file': str(bgm), 'target_duration_seconds': 1,
    }})
    clip = completed_output(service)['timeline'][0]
    assert clip['final_duration'] == 1.0
    assert clip['speed_factor'] == 1.5
    assert clip['end'] - clip['start'] == clip['final_duration']
    output = completed_output(service)
    assert output['bgm_path'] == str(bgm)
    assert output['source_audio_replaced'] is True


@pytest.mark.parametrize('bgm_duration,has_audio,accepted', [
    (0, True, False), (2.2, True, False), (1.8, True, False),
    (2, False, False), (2.079, True, True), (1.921, True, True),
])
def test_general_bgm_requires_probe_audio_and_matching_duration(
        service, workdir, caplog, bgm_duration, has_audio, accepted):
    source = workdir / 'source.mp4'
    source.touch()
    bgm = workdir / 'music.wav'
    bgm.touch()
    processor = Mock()

    def info(path):
        if str(path).endswith('_with_bgm.mp4'):
            return {'duration': bgm_duration, 'has_audio': has_audio}
        return {'duration': 2, 'has_audio': True}

    def render(*args, **kwargs):
        Path(kwargs.get('output_path') or args[1]).touch()
        return True

    processor.get_video_info.side_effect = info
    processor.cut_video.side_effect = render
    processor.convert_video.side_effect = render
    processor.add_audio_to_video.side_effect = render
    service.video_processor = processor
    service._run_remix_task('bgm', {'plan': {
        'video_paths': [str(source)], 'auto_highlight': False,
        'bgm_file': str(bgm), 'target_duration_seconds': 2,
    }})
    output = completed_output(service)
    assert output['output_path'].endswith('_with_bgm.mp4') is accepted
    assert output['bgm_path'] == (str(bgm) if accepted else '')
    assert output['source_audio_replaced'] is accepted
    assert output['duration_tolerance_seconds'] == 0.35
    assert output['timeline'][0]['final_duration'] == 2
    assert output['timeline'][0]['speed_factor'] == 1
    if not accepted:
        assert 'BGM' in caplog.text and '弃用' in caplog.text


def test_automatically_selected_bgm_is_saved(service, workdir, monkeypatch):
    source = workdir / 'source.mp4'
    source.touch()
    audio_dir = workdir / 'audio'
    audio_dir.mkdir()
    bgm = audio_dir / 'default_bgm.mp3'
    bgm.touch()
    monkeypatch.setattr(task_service, 'AUDIO_DIR', audio_dir)
    monkeypatch.setattr(task_service.subprocess, 'run', lambda *args, **kwargs: Mock(
        returncode=0, stdout='{"format":{"duration":"20"}}'))
    processor = Mock()

    def render(*args, **kwargs):
        Path(kwargs.get('output_path') or args[1]).touch()
        return True

    processor.get_video_info.return_value = {'duration': 2, 'has_audio': True}
    processor.cut_video.side_effect = render
    processor.convert_video.side_effect = render
    processor.add_audio_to_video.side_effect = render
    service.video_processor = processor
    service._run_remix_task('auto-bgm', {'plan': {
        'video_paths': [str(source)], 'auto_highlight': False,
        'auto_bgm': True, 'target_duration_seconds': 2,
    }})
    output = completed_output(service)
    assert output['bgm_path'] == str(bgm)
    assert output['source_audio_replaced'] is True


def test_progress_exposes_completed_audio_metadata(monkeypatch):
    app = Flask(__name__)
    app.register_blueprint(remix_api.remix_bp, url_prefix='/api/remix')
    db = Mock()
    db.get_task.return_value = {'id': 'done', 'status': 'completed', 'output_data': {
        'bgm_path': 'rendered.mp3', 'source_audio_replaced': True,
    }}
    monkeypatch.setattr(remix_api, '_db_manager', db)
    result = app.test_client().get('/api/remix/progress/done').json['data']
    assert result['bgm_path'] == 'rendered.mp3'
    assert result['source_audio_replaced'] is True


def test_export_passes_replaced_audio_to_draft_timeline(monkeypatch, tmp_path):
    source = tmp_path / 'source.mp4'
    source.touch()
    app = Flask(__name__)
    app.register_blueprint(remix_api.remix_bp, url_prefix='/api/remix')
    service = Mock()
    service.export_jianying_draft.return_value = {}
    monkeypatch.setattr(remix_api, 'remix_service', service)
    response = app.test_client().post('/api/remix/export-jianying-draft', json={
        'project_id': 'A', 'timeline': [{'source_video': str(source), 'source_start': 0, 'source_end': 2}],
        'bgm_path': 'rendered.mp3', 'source_audio_replaced': True,
    })
    assert response.json['code'] == 0
    assert service.export_jianying_draft.call_args.kwargs['timeline'][0]['source_audio_replaced'] is True


def make_media(path, duration, audio=False, size='96x64', fps=30):
    command = ['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
               f'color=c=blue:s={size}:r={fps}']
    if audio:
        command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000']
    command += ['-t', str(duration), '-c:v', 'libx264', '-preset', 'ultrafast',
                '-pix_fmt', 'yuv420p']
    if audio:
        command += ['-c:a', 'aac']
    result = subprocess.run(command + [str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('with_audio', [False, True])
def test_concat_mixed_fps_hd_unicode_and_quote_path(workdir, monkeypatch, with_audio):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg and ffprobe are required')
    processor = VideoProcessor()
    monkeypatch.setattr(processor, '_merge_via_filter_complex',
                        Mock(side_effect=AssertionError('normalization must succeed without fallback')))
    folder = workdir / "中文 空格's"
    folder.mkdir()
    paths = [folder / '片段一.mp4', folder / '片段二.mp4']
    make_media(paths[0], 0.6, audio=with_audio, size='1920x1080', fps=24)
    make_media(paths[1], 0.6, audio=False, size='1280x720', fps=60)
    output = folder / '成片.mp4'
    assert processor.merge_videos_with_transitions(
        [str(path) for path in paths], str(output), transition='cut', durations=[0.517, 0.517])
    info = processor.get_video_info(str(output))
    assert abs(info['duration'] - 1.034) <= 0.08
    assert info['has_audio'] is True
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-f', 'null', '-'],
                             capture_output=True, text=True, timeout=60)
    assert decoded.returncode == 0, decoded.stderr


@pytest.mark.parametrize('mode', ['general', 'music'])
def test_run_remix_task_real_multisegment_pipeline(service, workdir, monkeypatch, mode):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg and ffprobe are required')
    processor = VideoProcessor()
    monkeypatch.setattr(processor, '_merge_via_filter_complex',
                        Mock(side_effect=AssertionError('cut must not fall back to multi-input filters')))
    service.video_processor = processor
    source = workdir / 'source.mp4'
    bgm = workdir / 'music.mp4'
    long_run = os.environ.get('REMIX_PIPELINE_LONG') == '1'
    count = 120 if long_run else 24
    segment_duration = 5.017 if long_run else 0.217
    target = count * segment_duration
    # Independently rounded clips would drift beyond the unchanged final gate.
    independent_frame_drift = count * (math.ceil(segment_duration * 30) / 30 - segment_duration)
    assert independent_frame_drift > 0.35
    make_media(source, 10 if long_run else 2, audio=True)
    make_media(bgm, 1, audio=True)
    plan = {
        'mode': mode, 'video_paths': [str(source)], 'target_duration_seconds': target,
        'auto_highlight': False, 'auto_bgm': False,
    }
    if mode == 'music':
        matches = []
        for index in range(count):
            speed = 1.5 if index % 2 == 0 else 0.75
            matches.append({
                'clip_path': str(source), 'source_start': 0,
                'source_end': segment_duration * speed,
                'output_duration': segment_duration, 'playback_speed': speed,
                'start_time': index * segment_duration,
                'end_time': (index + 1) * segment_duration, 'beat_index': index,
            })
        beat_engine(monkeypatch, matches)
        plan['bgm_file'] = str(bgm)
    else:
        plan['clips'] = [
            {'video_path': str(source), 'start_time': 0, 'end_time': segment_duration}
            for _ in range(count)
        ]
    service._run_remix_task('real-' + mode, {'plan': plan})
    output = completed_output(service)
    path = Path(output['output_path'])
    assert path.is_file() and path.stat().st_size > 0
    actual = processor.get_video_info(str(path))
    assert abs(actual['duration'] - target) <= 0.35
    assert output['actual_duration_seconds'] == actual['duration']
    assert output['duration_tolerance_seconds'] == 0.35
    assert output['duration_within_tolerance'] is True
    timeline = output['timeline']
    assert len(timeline) == count
    assert timeline[-1]['end'] == pytest.approx(target)
    for index, clip in enumerate(timeline):
        assert clip['start'] == pytest.approx(index * segment_duration)
        assert clip['final_duration'] == pytest.approx(segment_duration)
        assert clip['duration'] == pytest.approx(segment_duration)
        expected_speed = (1.5 if index % 2 == 0 else 0.75) if mode == 'music' else 1
        assert clip['speed_factor'] == pytest.approx(expected_speed)
        assert clip['source_end'] - clip['source_start'] == pytest.approx(
            clip['final_duration'] * clip['speed_factor'])
    if mode == 'music':
        assert actual['has_audio'] is True
        assert output['beat_remix_used'] is True
    print(f'{mode}: clips={count}, target={target:.3f}s, actual={actual["duration"]:.3f}s, '
          f'independent_frame_drift={independent_frame_drift:.3f}s, timeline={timeline[-1]["end"]:.3f}s')
