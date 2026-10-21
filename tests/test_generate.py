import importlib.util
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
    def test_animation_completes_sparse_and_dense_boards(self):
        for level in [0, 1, 4]:
            data = calendar(level)
            width, cells, mines, numbers, events = generate.build_board(data)
            valid = {i for i, cell in enumerate(cells) if cell is not None}
            opened = {i for event in events if event['kind'] == 'reveal' for i in event['cells']}
            flagged = {i for event in events if event['kind'] == 'flag' for i in event['cells']}
            self.assertEqual(opened, valid - mines)
            self.assertEqual(flagged, mines)
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
