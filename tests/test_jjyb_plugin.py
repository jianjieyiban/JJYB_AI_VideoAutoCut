import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


PLUGIN_PATH = Path(__file__).resolve().parents[1] / 'executas' / 'jjyb-ai-smartcut' / 'jjyb_plugin.py'
spec = importlib.util.spec_from_file_location('jjyb_plugin', PLUGIN_PATH)
plugin = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plugin)


class PluginTests(unittest.TestCase):
    def test_invoke_without_video_path_uses_demo(self):
        engine = AsyncMock(return_value='output.mp4')
        with patch.object(plugin, '_ensure_demo_clip', return_value='demo.mp4'), \
                patch.object(plugin, '_load_engine', return_value=engine):
            response = plugin._handle_invoke(1, {'tool': 'auto_clip', 'arguments': {}})

        self.assertEqual(response['result']['data'], {
            'output_video': 'output.mp4', 'video_path': 'demo.mp4',
        })
        engine.assert_awaited_once_with(video_path='demo.mp4', config={})

    def test_failed_ffmpeg_large_partial_output_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Path(directory) / 'jjyb_demo_clip.mp4'

            def fail_with_partial_output(*args, **kwargs):
                demo.write_bytes(b'x' * 100_001)
                return subprocess.CompletedProcess(args[0], 1, stderr='encoding failed')

            with patch.object(plugin.subprocess, 'run', side_effect=fail_with_partial_output) as run:
                for _ in range(2):
                    with self.assertRaisesRegex(RuntimeError, 'encoding failed'):
                        plugin._ensure_demo_clip({'temp_dir': directory})
                self.assertEqual(run.call_count, 2)

    def test_successful_ffmpeg_output_is_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            demo = Path(directory) / 'jjyb_demo_clip.mp4'

            def succeed(*args, **kwargs):
                demo.write_bytes(b'x' * 100_001)
                return subprocess.CompletedProcess(args[0], 0, stderr='')

            with patch.object(plugin.subprocess, 'run', side_effect=succeed) as run:
                self.assertEqual(plugin._ensure_demo_clip({'temp_dir': directory}), str(demo))
                self.assertEqual(plugin._ensure_demo_clip({'temp_dir': directory}), str(demo))
                run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
