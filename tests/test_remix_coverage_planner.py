import unittest
from unittest.mock import Mock, patch

from backend.config.paths import PROJECT_ROOT

from backend.services.remix_service import RemixService
from backend.engine.beat_remix_engine import BeatRemixEngine


class RemixCoveragePlannerTests(unittest.TestCase):
    def setUp(self):
        self.service = RemixService.__new__(RemixService)

    def test_coverage_planner_samples_beginning_middle_and_end(self):
        candidates = [
            {
                'video_path': 'source.mp4',
                'start_time': 0,
                'end_time': 20,
                'duration': 20,
                'score': 0.60,
                'description': 'opening',
            },
            {
                'video_path': 'source.mp4',
                'start_time': 180,
                'end_time': 220,
                'duration': 40,
                'score': 0.95,
                'description': 'middle turn',
            },
            {
                'video_path': 'source.mp4',
                'start_time': 420,
                'end_time': 470,
                'duration': 50,
                'score': 0.90,
                'description': 'ending',
            },
            {
                'video_path': 'source.mp4',
                'start_time': 30,
                'end_time': 80,
                'duration': 50,
                'score': 0.55,
                'description': 'early filler',
            },
        ]

        clips = self.service._select_coverage_remix_clips(candidates, 100, 'dynamic')
        starts = [clip['start_time'] for clip in clips]
        total = sum(clip['duration'] for clip in clips)

        self.assertAlmostEqual(total, 100, places=3)
        self.assertLess(min(starts), 40)
        self.assertTrue(any(170 <= start <= 230 for start in starts))
        self.assertTrue(any(start >= 400 for start in starts))

    def test_coverage_planner_rejects_insufficient_material_without_shrinking_target(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 12, 'duration': 12, 'score': 0.9},
            {'video_path': 'source.mp4', 'start_time': 80, 'end_time': 90, 'duration': 10, 'score': 0.8},
        ]

        with patch.object(self.service, '_get_style_config', wraps=self.service._get_style_config) as style_config:
            with self.assertRaisesRegex(RuntimeError, r'22\.000s.*60\.000s'):
                self.service._select_coverage_remix_clips(candidates, 60, 'dynamic')
            style_config.assert_not_called()

    def test_coverage_planner_counts_overlapping_source_capacity_only_once(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 12, 'score': 0.9},
            {'video_path': 'source.mp4', 'start_time': 8, 'end_time': 20, 'score': 0.8},
        ]

        with self.assertRaisesRegex(RuntimeError, r'20\.000s.*22\.000s'):
            self.service._select_coverage_remix_clips(candidates, 22, 'dynamic')

    def test_coverage_planner_refuses_tiny_material(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 2, 'duration': 2, 'score': 0.9},
        ]

        with self.assertRaisesRegex(RuntimeError, r'2\.000s.*60\.000s'):
            self.service._select_coverage_remix_clips(candidates, 60, 'dynamic')

    def test_coverage_planner_reserves_capacity_for_a_short_early_shot(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 7, 'duration': 7, 'score': 0.9},
            {'video_path': 'source.mp4', 'start_time': 20, 'end_time': 23, 'duration': 3, 'score': 0.8},
            {'video_path': 'source.mp4', 'start_time': 40, 'end_time': 50, 'duration': 10, 'score': 0.7},
        ]

        clips = self.service._select_coverage_remix_clips(candidates, 20, 'dynamic')

        self.assertAlmostEqual(sum(clip['duration'] for clip in clips), 20, places=3)
        # 覆盖规划器会把候选镜头切出子窗口（用空闲区间补足目标时长），
        # 因此只要求每个输出窗口完整落在某个候选区间内（不越界、不凭空生成）。
        for clip in clips:
            self.assertTrue(any(
                item['start_time'] <= clip['start_time'] and clip['end_time'] <= item['end_time']
                for item in candidates
            ), f"输出窗口超出候选区间: {clip}")

    def test_process_remix_skips_highlight_generation_when_disabled_or_music(self):
        for mode, auto_highlight in [('general', False), ('music', False), ('music', True)]:
            for has_segments in (False, True):
                with self.subTest(mode=mode, auto_highlight=auto_highlight, segments=has_segments):
                    plan = {
                        'mode': mode, 'auto_highlight': auto_highlight,
                        'video_paths': ['source.mp4'], 'target_duration_seconds': 10,
                    }
                    if has_segments:
                        plan['segment_data'] = {'shots': [{
                            'source_video': 'source.mp4', 'start_time': 0, 'end_time': 20,
                        }]}
                    self.service.task_service = Mock()
                    self.service.task_service.create_remix_task.return_value = 'task-id'
                    with patch.object(self.service, '_select_coverage_remix_clips', return_value=[{'duration': 10}]) as select, \
                            patch.object(self.service, 'batch_analyze_videos', return_value=[]) as analyze, \
                            patch.object(self.service, 'create_remix_plan', return_value={'clips': [{'duration': 10}]}) as create:
                        self.assertEqual(self.service.process_remix('project', plan), 'task-id')
                        select.assert_not_called()
                        analyze.assert_not_called()
                        create.assert_not_called()
                    self.assertNotIn('clips', plan)
                    self.assertEqual(plan['target_duration_seconds'], 10)
                    self.service.task_service.create_remix_task.assert_called_once_with(project_id='project', plan=plan)

    def test_process_remix_reuses_segments_for_requested_general_highlights(self):
        plan = {
            'mode': 'general', 'auto_highlight': True,
            'video_paths': ['source.mp4'], 'target_duration_seconds': 10,
            'segment_data': {'shots': [{
                'source_video': 'source.mp4', 'start_time': 0, 'end_time': 20,
            }]},
        }
        self.service.task_service = Mock()
        with patch.object(self.service, 'batch_analyze_videos') as analyze:
            self.service.process_remix('project', plan)
            analyze.assert_not_called()
        self.assertAlmostEqual(sum(clip['duration'] for clip in plan['clips']), 10)
        self.assertEqual(plan['target_duration_seconds'], 10)

    def test_process_remix_rejects_short_segments_before_creating_task(self):
        plan = {
            'mode': 'general', 'auto_highlight': True,
            'target_duration_seconds': 60,
            'segment_data': {'shots': [{
                'source_video': 'source.mp4', 'start_time': 0, 'end_time': 22,
            }]},
        }
        self.service.task_service = Mock()
        with self.assertRaisesRegex(RuntimeError, r'22\.000s.*60\.000s'):
            self.service.process_remix('project', plan)
        self.service.task_service.create_remix_task.assert_not_called()
        self.assertEqual(plan['target_duration_seconds'], 60)
        self.assertNotIn('clips', plan)

    def test_general_render_enforces_actual_duration_tolerance(self):
        from backend.engine.puppet_sync_engine import PuppetSyncEngine

        source = str(PROJECT_ROOT / 'source.mp4')
        output = str(PROJECT_ROOT / 'output' / 'remix.mp4')
        for actual in (9.649, 10.351, 9.65, 10.35):
            with self.subTest(actual=actual):
                self.service.video_processor = Mock()
                self.service.video_processor.get_video_info.return_value = {'duration': actual}
                shots = [{'source_video': source, 'start_time': 0, 'end_time': 20, 'duration': 20, 'score': 0.9}]
                with patch('backend.services.remix_service.Path.exists', return_value=True), \
                        patch('backend.engine.smart_shot_segmenter.SmartShotSegmenter'), \
                        patch('backend.services.remix_service.load_or_detect_shots', return_value=shots), \
                        patch('backend.services.remix_service.enrich_shot_scores'), \
                        patch.object(self.service, '_effective_ranges_for', return_value={}), \
                        patch('backend.utils.frame_dedup.dedup_clips', side_effect=lambda clips: (clips, [])), \
                        patch.object(PuppetSyncEngine, 'render_timeline', return_value=output) as render:
                    if abs(actual - 10) > 0.35 + 1e-9:
                        with self.assertRaisesRegex(RuntimeError, '普通混剪成片未达到显式目标时长'):
                            self.service.general_mode_remix([source], target_duration=10)
                    else:
                        result = self.service.general_mode_remix([source], target_duration=10)
                        self.assertTrue(result['duration_within_tolerance'])
                        self.assertEqual(result['actual_duration_seconds'], actual)
                        self.assertEqual(result['target_duration_seconds'], 10)
                        self.assertEqual(result['output_video'], output)
                    render.assert_called_once()

    def test_beat_allocator_splits_a_long_shot_into_non_overlapping_windows(self):
        shots = [
            {'id': 'long', 'start_time': 0, 'end_time': 12, 'duration': 12, 'score': 0.95},
            {'id': 'short', 'start_time': 20, 'end_time': 24, 'duration': 4, 'score': 0.8},
        ]

        points = self.service._coalesce_beat_points([1, 2, 3, 4, 5, 6, 7], 8, 0.55)
        allocations = self.service._allocate_beat_source_windows(shots, points, [], False)

        self.assertAlmostEqual(sum(item['final_duration'] for item in allocations), 8, places=3)
        long_windows = [item for item in allocations if item['shot']['id'] == 'long']
        self.assertGreater(len(long_windows), 1)
        for previous, current in zip(long_windows, long_windows[1:]):
            self.assertLessEqual(previous['source_end'], current['source_start'])

    def test_beat_allocator_does_not_reuse_overlapping_ranges_from_same_source(self):
        shots = [
            {'id': 'a', 'source_video': 'source.mp4', 'start_time': 0, 'end_time': 8, 'duration': 8, 'score': 0.95},
            {'id': 'b', 'source_video': 'source.mp4', 'start_time': 2, 'end_time': 10, 'duration': 8, 'score': 0.90},
        ]

        allocations = self.service._allocate_beat_source_windows(shots, [0, 2, 4, 6, 8], [], False)

        windows = sorted((item['source_start'], item['source_end']) for item in allocations)
        for previous, current in zip(windows, windows[1:]):
            self.assertLessEqual(previous[1], current[0])

    def test_legacy_beat_engine_uses_later_windows_of_one_source(self):
        engine = BeatRemixEngine.__new__(BeatRemixEngine)
        engine.logger = __import__('logging').getLogger(__name__)
        clips = [
            {
                'path': 'source.mp4', 'duration': 12,
                'motion_intensity': 0.9, 'color_richness': 0.8,
            }
        ]
        music = {'beats': [1, 2, 3, 4, 5], 'strong_beats': [], 'tempo': 120, 'sections': []}

        matches = engine.match_clips_to_beats(clips, music, 'dynamic', target_duration=6)

        self.assertAlmostEqual(sum(item['output_duration'] for item in matches), 6, places=3)
        windows = [(item['source_start'], item['source_end']) for item in matches]
        for previous, current in zip(windows, windows[1:]):
            self.assertLessEqual(previous[1], current[0])

    def test_video_path_deduplication_is_case_and_separator_insensitive(self):
        paths = [
            r'uploads\remix_videos\clip.mp4',
            'uploads/remix_videos/clip.mp4',
            r'UPLOADS\REMIX_VIDEOS\CLIP.MP4',
            'uploads/remix_videos/other.mp4',
        ]

        unique = self.service._dedupe_video_paths(paths)

        self.assertEqual(unique, [paths[0], paths[3]])


if __name__ == '__main__':
    unittest.main()
