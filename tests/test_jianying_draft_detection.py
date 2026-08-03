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


if __name__ == '__main__':
    unittest.main()
