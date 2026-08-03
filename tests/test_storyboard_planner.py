# -*- coding: utf-8 -*-
import unittest

from backend.engine.puppet_sync_engine import PuppetSyncEngine
from backend.engine.storyboard_planner import StoryboardPlanner


class StoryboardPlannerTests(unittest.TestCase):
    def test_long_scene_is_windowed_across_the_full_source(self):
        shots = [
            {'id': 'opening', 'start_time': 0, 'end_time': 12, 'duration': 12, 'description': 'opening room'},
            {'id': 'middle', 'start_time': 12, 'end_time': 272, 'duration': 260, 'description': 'middle chase twist'},
            {'id': 'ending', 'start_time': 272, 'end_time': 300, 'duration': 28, 'description': 'ending farewell'},
        ]
        voices = [
            {'index': 0, 'text': 'opening room story begins', 'duration': 4},
            {'index': 1, 'text': 'middle chase conflict rises', 'duration': 5},
            {'index': 2, 'text': 'ending truth and farewell', 'duration': 4},
        ]
        planned = StoryboardPlanner().plan(shots, voices)
        self.assertEqual(3, len(planned))
        self.assertGreater(max(item['end_time'] for item in planned), 250)
        timeline = PuppetSyncEngine().match_shots_to_voices(planned, voices)
        self.assertEqual(3, len(timeline))
        self.assertEqual(3, len([item for item in timeline if item['subtitle_text']]))
        self.assertAlmostEqual(13.0, timeline[-1]['timeline_end'], places=2)

    def test_windows_do_not_overlap(self):
        shots = [{'id': 'long', 'start_time': 0, 'end_time': 80, 'duration': 80, 'description': 'scene action'}]
        voices = [{'index': i, 'text': 'scene action segment %d' % i, 'duration': 5} for i in range(6)]
        planned = StoryboardPlanner().plan(shots, voices)
        ranges = sorted((item['start_time'], item['end_time']) for item in planned)
        self.assertTrue(all(right <= next_left for (_, right), (next_left, _) in zip(ranges, ranges[1:])))

    def test_storyboard_moves_forward_even_when_semantics_are_messy(self):
        shots = [
            {'id': 'a', 'start_time': 0, 'end_time': 8, 'duration': 8, 'description': 'ending truth'},
            {'id': 'b', 'start_time': 40, 'end_time': 48, 'duration': 8, 'description': 'opening room'},
            {'id': 'c', 'start_time': 80, 'end_time': 88, 'duration': 8, 'description': 'ending truth'},
            {'id': 'd', 'start_time': 120, 'end_time': 128, 'duration': 8, 'description': 'middle chase'},
        ]
        voices = [
            {'index': 0, 'text': 'opening room', 'duration': 4},
            {'index': 1, 'text': 'middle chase', 'duration': 4},
            {'index': 2, 'text': 'ending truth', 'duration': 4},
        ]
        planned = StoryboardPlanner().plan(shots, voices)
        starts = [item['start_time'] for item in planned]
        self.assertEqual(starts, sorted(starts))
        self.assertGreaterEqual(starts[-1], 80)

    def test_puppet_sync_rebuilds_near_match_windows_to_audio_duration(self):
        shots = [{
            'id': 'near_match',
            'start_time': 10.0,
            'end_time': 14.2,
            'duration': 4.2,
            'description': 'dialogue closeup',
        }]
        voices = [{'index': 0, 'text': 'dialogue closeup', 'duration': 4.0, 'voice_path': 'voice.wav'}]
        timeline = PuppetSyncEngine().match_shots_to_voices(shots, voices)
        self.assertEqual(1, len(timeline))
        item = timeline[0]
        self.assertAlmostEqual(4.0, item['final_duration'], places=3)
        self.assertAlmostEqual(4.0, item['source_end'] - item['source_start'], places=3)
        self.assertEqual('cut_highlight', item['cut_strategy'])

    def test_long_scene_is_spread_by_narrative_anchors(self):
        shots = [{'id': 'long', 'start_time': 0, 'end_time': 120, 'duration': 120, 'description': 'generic scene'}]
        voices = [{'index': i, 'text': 'generic narration segment', 'duration': 4} for i in range(4)]
        planned = StoryboardPlanner().plan(shots, voices)
        starts = [item['start_time'] for item in planned]
        self.assertLess(starts[0], 5)
        self.assertGreater(starts[-1], 90)
        self.assertEqual(starts, sorted(starts))


if __name__ == '__main__':
    unittest.main()
