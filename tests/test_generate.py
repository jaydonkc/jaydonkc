import importlib.util
import random
import unittest
from datetime import date, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('generate', Path(__file__).parents[1] / 'scripts/generate.py')
generate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate)


def calendar(level=0):
    start = date(2025, 10, 19)
    days = [{'date': (start + timedelta(days=i)).isoformat(), 'count': level, 'level': level} for i in range(368)]
    return {'username': 'test', 'from': days[0]['date'], 'to': days[-1]['date'], 'total': level * len(days), 'days': days}


class GeneratorTests(unittest.TestCase):
    def test_recorded_moves_follow_visible_clues_on_sparse_and_dense_boards(self):
        for level in [0, 1, 4]:
            data = calendar(level)
            width, cells, mines, numbers, events = generate.build_board(data)
            valid = {i for i, cell in enumerate(cells) if cell is not None}
            opened = {i for event in events if event['kind'] == 'reveal' for i in event['cells']}
            flagged = {i for event in events if event['kind'] == 'flag' for i in event['cells']}
            if events[-1]['kind'] == 'hit':
                self.assertIn(events[-1]['index'], mines)
                self.assertEqual(events[-1]['reason'], 'guess')
                self.assertEqual(set(events[-1]['cells']), mines - flagged)
            else:
                self.assertEqual(opened, valid - mines)
                self.assertEqual(flagged, mines)
            visible, known_mines = {}, set()
            for event in events:
                safe, inferred_mines, _ = generate.deductions(width, valid, visible, known_mines)
                if event['kind'] == 'flag':
                    self.assertTrue(event['index'] in inferred_mines or set(visible) == valid - mines)
                    known_mines.add(event['index'])
                elif event['kind'] == 'reveal':
                    self.assertFalse(set(event['cells']) & mines)
                    if event['reason'] == 'deduction': self.assertIn(event['index'], safe)
                    visible.update({i: numbers[i] for i in event['cells']})
            self.assertEqual(sum(cell is not None for cell in cells), 368)
            for mine in mines: self.assertIn(mine, valid)
            for i in valid: self.assertEqual(numbers[i], sum(n in mines for n in generate.neighbors(i, width, 7)))

    def test_deterministic_and_script_free_svg(self):
        data = calendar(2)
        for theme in ['dark', 'light']:
            svg = generate.render_svg(data, theme)
            self.assertEqual(svg, generate.render_svg(data, theme))
            root = ET.fromstring(svg)
            self.assertIn('prefers-reduced-motion', svg)
            self.assertNotIn('<script', svg)
            self.assertNotIn('foreignObject', svg)
            self.assertEqual(root.attrib['role'], 'img')
            self.assertEqual(root.attrib['height'], '126')
            text_nodes = root.findall('.//{http://www.w3.org/2000/svg}text')
            self.assertTrue(all(node.attrib.get('class') == 'digit' for node in text_nodes))
            self.assertNotIn('calcMode="discrete"', svg)
            self.assertIn('calcMode="spline"', svg)

    def test_deductions_only_need_revealed_numbers(self):
        safe, mines, _ = generate.deductions(5, set(range(35)), {0: 1, 1: 1}, set())
        self.assertTrue({2, 7} <= safe)
        self.assertFalse(mines)
        safe, mines, _ = generate.deductions(5, {0, 5}, {0: 1}, set())
        self.assertEqual(mines, {5})
        self.assertFalse(safe)
        kind, index, reason = generate.choose_move(5, set(range(35)), {0: 1, 1: 1}, set(), 1, random.Random(42), 5)
        self.assertEqual(kind, 'reveal')
        self.assertIn(index, {2, 7})
        self.assertEqual(reason, 'deduction')

    def test_cursor_timing_is_varied_synchronized_and_bounded(self):
        width, _, _, _, events = generate.build_board(calendar(1))
        times, motion, duration = generate.build_timeline(events, width)
        intervals = [b - a for a, b in zip(times, times[1:])]
        self.assertTrue(all(interval > .1 for interval in intervals))
        self.assertGreater(max(intervals) - min(intervals), .08)
        self.assertAlmostEqual(duration, times[-1] + 4)
        self.assertLessEqual(duration, 60)
        self.assertTrue(all(a[0] < b[0] for a, b in zip(motion, motion[1:])))
        for time, event in zip(times, events):
            click = next(point for point in motion if point[0] == time)
            self.assertLess(abs(click[1] - event['index'] % width), .11)
            self.assertLess(abs(click[2] - event['index'] // width), .11)

    def test_layout_is_fixed_for_a_snapshot_and_changes_with_activity(self):
        original = calendar(1)
        changed = calendar(1)
        changed['days'][0]['count'] += 1
        self.assertEqual(generate.build_board(original)[2], generate.build_board(original)[2])
        self.assertNotEqual(generate.build_board(original)[2], generate.build_board(changed)[2])

    def test_rotation_uses_distinct_layouts_and_moves(self):
        rounds = generate.build_rounds(calendar(1))
        self.assertEqual(len(rounds), 8)
        self.assertEqual(len({frozenset(board[2]) for board in rounds}), 8)
        self.assertGreater(len({board[4][0]['index'] for board in rounds}), 1)
        self.assertEqual(len({tuple((event['kind'], event['index']) for event in board[4]) for board in rounds}), 8)
        for width, cells, mines, numbers, events in rounds:
            self.assertEqual(cells, rounds[0][1])
            self.assertFalse({events[0]['index'], *generate.neighbors(events[0]['index'], width, 7)} & mines)
            self.assertLessEqual(generate.build_timeline(events, width)[2], 60)

    def test_svg_round_windows_and_cursor_timeline_are_synchronized(self):
        root = ET.fromstring(generate.render_svg(calendar(1), 'dark'))
        ns = {'svg': 'http://www.w3.org/2000/svg'}
        rounds = [group for group in root.findall('svg:g', ns) if 'data-round' in group.attrib]
        motion = root.find('.//svg:animateTransform', ns)
        total = float(motion.attrib['dur'].rstrip('s'))
        self.assertEqual(len(rounds), 8)
        self.assertEqual(len({group.attrib['data-layout'] for group in rounds}), 8)
        offset = 0
        for group in rounds:
            self.assertAlmostEqual(float(group.attrib['data-start']), offset, places=3)
            offset += float(group.attrib['data-duration'])
        self.assertAlmostEqual(total, offset, places=3)
        times = [float(time) for time in motion.attrib['keyTimes'].split(';')]
        self.assertEqual(times[0], 0)
        self.assertEqual(times[-1], 1)
        self.assertTrue(all(a < b for a, b in zip(times, times[1:])))
        self.assertEqual(len(times), len(motion.attrib['values'].split(';')))
        self.assertEqual(len(times) - 1, len(motion.attrib['keySplines'].split(';')))

    def test_parser_counts_dates_and_no_contributions(self):
        html = ''.join(f'<td id="d{i}" data-date="{day["date"]}" data-level="1"></td><tool-tip for="d{i}">{"1,200 contributions" if i == 0 else "No contributions"} on a date.</tool-tip>' for i, day in enumerate(calendar()['days']))
        parsed = generate.parse_calendar(html, 'test')
        self.assertEqual(parsed['total'], 1200)
        self.assertEqual(len(parsed['days']), 368)
        self.assertEqual(parsed['days'][1]['count'], 0)

    def test_parser_rejects_missing_and_unreadable_calendar(self):
        for html in ['', '<html>Rate limited</html>', '<td id="d" data-date="2026-10-21" data-level="1"></td>']:
            with self.assertRaises(ValueError): generate.parse_calendar(html, 'test')


if __name__ == '__main__':
    unittest.main()
