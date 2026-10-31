import asyncio
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from backend.engine.auto_clip_controller import AutoClipController


def _ffmpeg() -> str:
    exe = shutil.which('ffmpeg')
    if not exe:
        pytest.skip('需要 ffmpeg 在 PATH 中')
    return exe


@pytest.fixture(scope='module')
def real_video(tmp_path_factory):
    """1 秒 320x240@30fps 真实测试视频（规范化环节需要真实媒体文件）。"""
    path = tmp_path_factory.mktemp('media') / 'clip.mp4'
    subprocess.run(
        [_ffmpeg(), '-hide_banner', '-loglevel', 'error',
         '-f', 'lavfi', '-i', 'testsrc=duration=1:size=320x240:rate=30',
         '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(path)],
        check=True)
    return str(path)


@pytest.fixture(scope='module')
def real_audio(tmp_path_factory):
    """1 秒 48kHz 立体声静音 MP3（ffprobe 时长探测需要真实音频）。"""
    path = tmp_path_factory.mktemp('media') / 'silence.mp3'
    subprocess.run(
        [_ffmpeg(), '-hide_banner', '-loglevel', 'error',
         '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', '1',
         '-y', str(path)],
        check=True)
    return str(path)


@pytest.fixture
def controller(tmp_path):
    instance = AutoClipController.__new__(AutoClipController)
    instance.temp_dir = tmp_path
    instance.output_dir = tmp_path
    instance.config = {'tts_voice': 'test', 'subtitle_enabled': False}
    instance.tts_engine = Mock()
    instance.audio_normalizer = Mock()
    instance.audio_processor = Mock()
    instance.audio_processor.ffmpeg_path = _ffmpeg()
    instance.clipper = Mock()
    instance.composer = Mock()
    return instance


def test_tts_failure_stops_workflow_instead_of_dropping_narration(controller):
    controller.tts_engine.synthesize.return_value = False
    with pytest.raises(RuntimeError, match='音频生成失败'):
        asyncio.run(controller._step3_generate_voiceover({'narrations': [{'text': 'hello'}]}))


def test_empty_video_clips_report_failure(controller):
    with pytest.raises(ValueError, match='视频片段'):
        asyncio.run(controller._step5_compose_final_video([], [], None, 'out.mp4'))


def test_partial_clip_failure_stops_workflow(controller):
    controller.clipper.batch_clip_videos.return_value = ['one.mp4']
    script = {'narrations': [{'time_range': '0s-1s'}, {'time_range': '1s-2s'}]}
    with pytest.raises(RuntimeError, match='剪辑'):
        asyncio.run(controller._step4_clip_videos('source.mp4', script))


def test_mismatched_audio_count_reports_failure(controller, real_video, real_audio):
    """提供了配音但数量与片段不齐 → 明确报错，不静默丢弃缺段。"""
    with pytest.raises(ValueError, match='配音数量不一致'):
        asyncio.run(controller._step5_compose_final_video(
            [real_video, real_video], [{'audio_path': real_audio}], None, 'out.mp4'))


def test_missing_export_is_not_reported_as_success(controller, real_video, tmp_path):
    """合成器返回了路径但文件未落盘 → 必须报"最终视频导出失败"，不误报成功。"""
    controller.composer.merge_materials.return_value = str(tmp_path / 'out.mp4')
    with pytest.raises(RuntimeError, match='最终视频'):
        asyncio.run(controller._step5_compose_final_video([real_video], [], None, 'out.mp4'))


def test_successful_export_without_narration_does_not_use_stale_audio(
        controller, real_video, tmp_path):
    """无配音导出：不残留旧音轨（audio_path 必须为 None），正常返回输出路径。"""
    (tmp_path / 'merged_audio.mp3').write_bytes(b'old audio')

    def compose(**kwargs):
        assert kwargs['audio_path'] is None
        (tmp_path / 'out.mp4').write_bytes(b'video')
        return kwargs['output_path']

    controller.composer.merge_materials.side_effect = compose
    result = asyncio.run(controller._step5_compose_final_video([real_video], [], None, 'out.mp4'))
    assert result == str(tmp_path / 'out.mp4')


def test_later_missing_audio_is_not_silently_dropped(
        controller, real_video, real_audio, tmp_path):
    """第1段配音存在、第2段缺失 → 在第2段处明确报错，不静默跳过继续导出。"""
    first = tmp_path / 'first.mp3'
    shutil.copy(real_audio, first)
    second = tmp_path / 'missing.mp3'
    with pytest.raises(RuntimeError, match='第2段配音文件不存在'):
        asyncio.run(controller._step5_compose_final_video(
            [real_video, real_video],
            [{'audio_path': str(first)}, {'audio_path': str(second)}],
            None, 'out.mp4'))
