import unittest

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

    def test_coverage_planner_refuses_to_pad_insufficient_material(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 12, 'duration': 12, 'score': 0.9},
            {'video_path': 'source.mp4', 'start_time': 80, 'end_time': 90, 'duration': 10, 'score': 0.8},
        ]

        with self.assertRaisesRegex(RuntimeError, '少于目标'):
            self.service._select_coverage_remix_clips(candidates, 60, 'dynamic')

    def test_coverage_planner_reserves_capacity_for_a_short_early_shot(self):
        candidates = [
            {'video_path': 'source.mp4', 'start_time': 0, 'end_time': 7, 'duration': 7, 'score': 0.9},
            {'video_path': 'source.mp4', 'start_time': 20, 'end_time': 23, 'duration': 3, 'score': 0.8},
            {'video_path': 'source.mp4', 'start_time': 40, 'end_time': 50, 'duration': 10, 'score': 0.7},
        ]

        clips = self.service._select_coverage_remix_clips(candidates, 20, 'dynamic')

        self.assertAlmostEqual(sum(clip['duration'] for clip in clips), 20, places=3)
        for clip in clips:
            self.assertLessEqual(clip['end_time'], next(
                item['end_time'] for item in candidates
                if item['start_time'] == clip['start_time']
            ))

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
