"""Regression tests for Jianying/CapCut draft root detection."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config.ai_config import AIConfigManager
from backend.utils import jianying_detector


class JianyingDraftDetectionTests(unittest.TestCase):
    def test_confirmed_draft_root_survives_config_manager_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / 'config'
            draft_root = r'C:\Users\Editor\AppData\Local\JianyingPro\User Data\Projects\com.lveditor.draft'
            manager = AIConfigManager(str(config_dir))
            manager.global_config.jianying_draft_path = draft_root
            self.assertTrue(manager.save_config())

            reloaded = AIConfigManager(str(config_dir))
            self.assertEqual(reloaded.global_config.jianying_draft_path, draft_root)

    def test_windows_default_draft_root_is_reported_as_detected_and_writable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = Path(temp_dir)
            draft_root = (
                local_appdata
                / 'JianyingPro'
                / 'User Data'
                / 'Projects'
                / 'com.lveditor.draft'
            )
            draft_root.mkdir(parents=True)
            environment = {
                'LOCALAPPDATA': str(local_appdata),
                'APPDATA': str(local_appdata / 'Roaming'),
            }
            with patch.dict(os.environ, environment, clear=False), patch.object(jianying_detector.sys, 'platform', 'win32'), patch.object(
                jianying_detector.Path, 'home', return_value=local_appdata.parent
            ), patch('backend.config.ai_config.get_config_manager', side_effect=RuntimeError('no configured path')):
                info = jianying_detector.detect_jianying_draft_info()

        self.assertTrue(info['detected'])
        self.assertTrue(info['writable'])
        self.assertEqual(Path(info['draft_dir']), draft_root)
        self.assertEqual(info['message'], '')

    def test_detected_read_only_root_keeps_path_and_explains_permission_issue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = Path(temp_dir)
            draft_root = (
                local_appdata
                / 'JianyingPro'
                / 'User Data'
                / 'Projects'
                / 'com.lveditor.draft'
            )
            draft_root.mkdir(parents=True)
            environment = {
                'LOCALAPPDATA': str(local_appdata),
                'APPDATA': str(local_appdata / 'Roaming'),
            }
            with patch.dict(os.environ, environment, clear=False), patch.object(jianying_detector.sys, 'platform', 'win32'), patch.object(
                jianying_detector.Path, 'home', return_value=local_appdata.parent
            ), patch('backend.config.ai_config.get_config_manager', side_effect=RuntimeError('no configured path')), patch.object(
                jianying_detector, '_is_writable_directory', return_value=False
            ):
                info = jianying_detector.detect_jianying_draft_info()
                strict_path = jianying_detector.detect_jianying_draft_dir()

        self.assertTrue(info['detected'])
        self.assertFalse(info['writable'])
        self.assertEqual(Path(info['draft_dir']), draft_root)
        self.assertIn('没有写入权限', info['message'])
        self.assertEqual(strict_path, '')

    def test_version_major_parsing_tolerates_bad_input(self) -> None:
        self.assertEqual(jianying_detector._parse_version_major('6.1.0.1024'), 6)
        self.assertEqual(jianying_detector._parse_version_major(' 5.9.1 '), 5)
        self.assertEqual(jianying_detector._parse_version_major('unknown'), 0)
        self.assertEqual(jianying_detector._parse_version_major(''), 0)
        self.assertEqual(jianying_detector._parse_version_major(None), 0)

    def test_jianying_version_does_not_prove_draft_compatibility(self) -> None:
        exe = Path(r'C:\Apps\JianyingPro.exe')
        with patch.object(jianying_detector, '_find_jianying_client_executables', return_value=[('jianying', exe)]), \
                patch.object(jianying_detector, '_read_exe_file_version', return_value='6.1.0.1024'):
            info = jianying_detector.detect_jianying_client_version()

        self.assertTrue(info['checked'])
        self.assertEqual(info['client'], 'jianying')
        self.assertEqual(info['major'], 6)
        self.assertIsNone(info['draft_encrypted'])
        self.assertEqual(info['compatibility_status'], 'unverified')
        self.assertIn('未验证', info['message'])

    def test_capcut_and_jianying_5_9_remain_plaintext(self) -> None:
        for client, version, exe_name in (
            ('capcut', '13.9.0', r'C:\Apps\CapCut.exe'),
            ('jianying', '5.9.1', r'C:\Apps\JianyingPro.exe'),
        ):
            with self.subTest(client=client, version=version):
                with patch.object(jianying_detector, '_find_jianying_client_executables',
                                  return_value=[(client, Path(exe_name))]), \
                        patch.object(jianying_detector, '_read_exe_file_version', return_value=version):
                    info = jianying_detector.detect_jianying_client_version()

                self.assertTrue(info['checked'])
                self.assertIsNone(info['draft_encrypted'])
                self.assertIn('未验证', info['message'])

    def test_unreadable_version_falls_back_to_apps_folder_name(self) -> None:
        exe = Path(r'C:\Apps\6.2.5\JianyingPro.exe')
        with patch.object(jianying_detector, '_find_jianying_client_executables', return_value=[('jianying', exe)]), \
                patch.object(jianying_detector, '_read_exe_file_version', return_value=''):
            info = jianying_detector.detect_jianying_client_version()

        self.assertTrue(info['checked'])
        self.assertEqual(info['version'], '6.2.5')
        self.assertIsNone(info['draft_encrypted'])

    def test_client_detection_matches_selected_capcut_root(self):
        candidates = [('jianying', Path('JianyingPro.exe')), ('capcut', Path('CapCut.exe'))]
        with patch.object(jianying_detector, '_find_jianying_client_executables', return_value=candidates), patch.object(
            jianying_detector, '_read_exe_file_version', return_value='12.0.0'
        ):
            info = jianying_detector.detect_jianying_client_version('C:/Users/test/CapCut/User Data/Projects/com.lveditor.draft')
        self.assertEqual(info['client'], 'capcut')

    def test_export_reports_client_compatibility_and_encrypted_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_root = root / 'User Data' / 'Projects' / 'com.lveditor.draft'
            draft_root.mkdir(parents=True)
            video = root / 'video.mp4'
            video.touch()
            audio = root / 'voice.mp3'
            audio.touch()
            timeline = [{
                'source_video': str(video), 'source_start': 0, 'source_end': 2,
                'final_duration': 2, 'audio_duration': 2, 'subtitle_text': '你好',
            }]
            media = {'duration': 10.0, 'width': 1920, 'height': 1080, 'has_audio': True}
            encrypted = {
                'checked': True, 'client': 'jianying', 'version': '6.1.0', 'major': 6,
                'draft_encrypted': True, 'message': '检测到剪映客户端 6.1.0：非常规路径',
            }
            with patch.object(jianying_detector, '_probe_media_info', return_value=media), \
                    patch.object(jianying_detector, 'detect_jianying_client_version', return_value=encrypted):
                result = jianying_detector.export_draft_package(
                    str(draft_root), 'compat', timeline,
                    video_path=str(video), audio_paths=[str(audio)],
                )
                self.assertTrue(result['client_version_info']['draft_encrypted'])
                self.assertIsNone(result['draft_openable_in_detected_client'])
                self.assertTrue(any('非常规路径' in warning for warning in result['warnings']))
                self.assertTrue((Path(result['draft_path']) / 'draft_content.json').is_file())
                self.assertTrue((Path(result['draft_path']) / 'subtitles.srt').is_file())

    def test_export_without_client_detection_keeps_result_usable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            draft_root = root / 'User Data' / 'Projects' / 'com.lveditor.draft'
            draft_root.mkdir(parents=True)
            video = root / 'video.mp4'
            video.touch()
            timeline = [{
                'source_video': str(video), 'source_start': 0, 'source_end': 2,
                'final_duration': 2, 'audio_duration': 2,
            }]
            media = {'duration': 10.0, 'width': 1920, 'height': 1080, 'has_audio': False}
            with patch.object(jianying_detector, '_probe_media_info', return_value=media), \
                    patch.object(jianying_detector, 'detect_jianying_client_version',
                                 side_effect=RuntimeError('detection crashed')):
                result = jianying_detector.export_draft_package(
                    str(draft_root), 'no-client', timeline, video_path=str(video),
                )
                self.assertEqual(result['client_version_info'], {})
                self.assertIsNone(result['draft_openable_in_detected_client'])
                self.assertEqual(result['warnings'], [])


class DraftTimelineRegressionTests(unittest.TestCase):
    def _export(self, root, timeline, audio_paths=None):
        video = root / 'video.mp4'
        video.touch()
        for item in timeline:
            item['source_video'] = str(video)
        media = {'duration': 20.0, 'width': 1920, 'height': 1080, 'has_audio': True}
        with patch.object(jianying_detector, '_probe_media_info', return_value=media), patch.object(
            jianying_detector, 'detect_jianying_client_version', return_value={}
        ):
            return jianying_detector.export_draft_package(
                str(root), 'regression', timeline, video_path=str(video), audio_paths=audio_paths,
            )

    def test_explicit_custom_directory_is_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = self._export(root, [{'source_start': 0, 'source_end': 2}])
            self.assertEqual(Path(result['draft_path']).parent, root)

    def test_global_voice_continues_across_segments_and_video_is_muted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            audio = root / 'voice.wav'
            audio.touch()
            result = self._export(root, [
                {'source_start': 0, 'source_end': 2},
                {'source_start': 2, 'source_end': 4},
            ], [str(audio)])
            video_track = next(t for t in result['tracks'] if t['type'] == 'video')
            voice_track = next(t for t in result['tracks'] if t['type'] == 'audio')
            self.assertEqual([s['volume'] for s in video_track['segments']], [0, 0])
            self.assertEqual([s['source_timerange']['start'] for s in voice_track['segments']], [0, 2000000])

    def test_original_audio_uses_video_track_once_and_zero_volume_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._export(Path(temp), [
                {'source_start': 0, 'source_end': 2, 'original_audio': True, 'original_audio_volume': 0},
            ])
            self.assertEqual([t['type'] for t in result['tracks']], ['video'])
            self.assertEqual(result['tracks'][0]['segments'][0]['volume'], 0)

    def test_remix_without_voice_preserves_source_audio(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._export(Path(temp), [{'source_start': 0, 'source_end': 2}])
            self.assertEqual(result['tracks'][0]['segments'][0]['volume'], 1)

    def test_shortened_target_trims_source_at_speed(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self._export(Path(temp), [
                {'source_start': 1, 'source_end': 9, 'speed_factor': 2, 'final_duration': 2},
            ])
            segment = result['tracks'][0]['segments'][0]
            self.assertEqual(segment['source_timerange']['duration'], 4000000)
            self.assertEqual(segment['target_timerange']['duration'], 2000000)


if __name__ == '__main__':
    unittest.main()
