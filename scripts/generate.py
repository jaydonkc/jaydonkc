#!/usr/bin/env python3
"""Generate a script-free Minesweeper SVG from GitHub's public calendar."""
import argparse
from datetime import date, timedelta
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import random
import re
from urllib.request import Request, urlopen


class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}
        self.ids = {}
        self.tooltip = None
        self.text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'td' and 'data-date' in attrs and 'data-level' in attrs:
            day = attrs['data-date']
            self.days[day] = {'date': day, 'level': int(attrs['data-level']), 'count': None}
            self.ids[attrs['id']] = day
        if tag == 'tool-tip':
            self.tooltip = attrs.get('for')
            self.text = []

    def handle_data(self, data):
        if self.tooltip:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag == 'tool-tip' and self.tooltip:
            day = self.ids.get(self.tooltip)
            content = ''.join(self.text).strip()
            match = re.match(r'([\d,]+) contributions?\b', content)
            if day and (match or content.startswith('No contributions')):
                self.days[day]['count'] = int(match[1].replace(',', '')) if match else 0
            self.tooltip = None


def parse_calendar(html, username):
    parser = CalendarParser()
    parser.feed(html)
    days = sorted(parser.days.values(), key=lambda item: item['date'])
    if not 350 <= len(days) <= 371:
        raise ValueError(f'Expected a full contribution calendar; received {len(days)} days')
    for index, day in enumerate(days):
        current = date.fromisoformat(day['date'])
        if index and current != date.fromisoformat(days[index - 1]['date']) + timedelta(days=1):
            raise ValueError('Contribution calendar has missing dates')
        if day['count'] is None or not 0 <= day['level'] <= 4:
            raise ValueError(f'Invalid contribution cell: {day["date"]}')
    return {'username': username, 'from': days[0]['date'], 'to': days[-1]['date'],
            'total': sum(day['count'] for day in days), 'days': days}


def neighbors(index, width, height):
    x, y = index % width, index // width
    return [ny * width + nx for ny in range(max(0, y - 1), min(height, y + 2))
            for nx in range(max(0, x - 1), min(width, x + 2)) if (nx, ny) != (x, y)]


def build_board(calendar):
    days = calendar['days']
    first = date.fromisoformat(days[0]['date'])
    offset = (first.weekday() + 1) % 7
    width = (len(days) + offset + 6) // 7
    cells = [None] * (width * 7)
    for i, day in enumerate(days):
        position = i + offset
        cells[(position % 7) * width + position // 7] = day
    valid = {i for i, cell in enumerate(cells) if cell is not None}
    seed = int(sha256(json.dumps(days, sort_keys=True).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    # Keep the first click and its neighborhood safe, as in the playable game.
    start = min(valid, key=lambda i: (cells[i]['level'], i))
    safe = {start, *neighbors(start, width, 7)}
    candidates = sorted(valid - safe)
    weighted = sorted(candidates, key=lambda i: rng.random() ** (1 / (1 + cells[i]['level'])))
    mines = set(weighted[-round(len(valid) * .16):])
    numbers = [sum(n in mines for n in neighbors(i, width, 7)) for i in range(len(cells))]
    revealed, flagged, events = set(), set(), []

    def reveal(index):
        queue, opened = [index], set()
        while queue:
            item = queue.pop()
            if item in revealed or item not in valid or item in mines:
                continue
            revealed.add(item)
            opened.add(item)
            if numbers[item] == 0:
                queue.extend(neighbors(item, width, 7))
        if opened:
            events.append({'kind': 'reveal', 'index': index, 'cells': sorted(opened)})

    reveal(start)
    while valid - revealed - mines:
        # Animate local flags and a sweep across the remaining safe tiles.
        eligible = [i for i in mines - flagged if any(n in revealed for n in neighbors(i, width, 7))]
        for i in sorted(eligible):
            flagged.add(i)
            events.append({'kind': 'flag', 'index': i, 'cells': [i]})
        frontier = valid - revealed - mines
        index = min(frontier, key=lambda i: (not any(n in revealed for n in neighbors(i, width, 7)), i % width, i // width))
        reveal(index)
    for i in sorted(mines - flagged):
        events.append({'kind': 'flag', 'index': i, 'cells': [i]})
    return width, cells, mines, numbers, events


THEMES = {
    'light': {'bg': '#ffffff', 'border': '#d1d9e0', 'text': '#1f2328', 'muted': '#59636e',
              'open': '#f6f8fa', 'grid': '#d8dee4', 'greens': ['#ebedf0', '#9be9a8', '#40c463', '#30a14e', '#216e39'],
              'numbers': ['#0969da', '#1a7f37', '#cf222e', '#8250df', '#9a6700', '#0550ae', '#1f2328', '#59636e']},
    'dark': {'bg': '#0d1117', 'border': '#30363d', 'text': '#e6edf3', 'muted': '#8b949e',
             'open': '#161b22', 'grid': '#30363d', 'greens': ['#161b22', '#0e4429', '#006d32', '#26a641', '#39d353'],
             'numbers': ['#79c0ff', '#7ee787', '#ff7b72', '#d2a8ff', '#ffa657', '#56d4dd', '#e6edf3', '#8b949e']},
}


def render_svg(calendar, theme):
    palette = THEMES[theme]
    width, cells, mines, numbers, events = build_board(calendar)
    step, size, left, top = 15, 12, 26, 76
    svg_width, svg_height = width * step + 49, 224
    duration, first, last = 24, 2.2, 19
    times = [first + (last - first) * i / max(1, len(events) - 1) for i in range(len(events))]
    css = ['text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif}',
           '.digit{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:700}',
           '@media(prefers-reduced-motion:reduce){.reveal{animation:none!important;opacity:1!important}.cursor,.live{display:none}.complete{animation:none!important;opacity:1!important}}']
    reveals = {}
    flags = {}
    for event, time in zip(events, times):
        percentage = time / duration * 100
        name = f's{len(css)}'
        css.append(f'@keyframes {name}{{0%,{percentage:.3f}%{{opacity:0}}{percentage+.01:.3f}%,99.999%{{opacity:1}}100%{{opacity:0}}}}')
        for index in event['cells']:
            (flags if event['kind'] == 'flag' else reveals)[index] = name
    css.append('@keyframes finish{0%,80%{opacity:0}81%,99.999%{opacity:1}100%{opacity:0}}')
    css.append('@keyframes running{0%,80%{opacity:1}81%,99.999%{opacity:0}100%{opacity:1}}')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(calendar["username"])} contribution Minesweeper</title>',
             '<desc id="desc">An autoplay Minesweeper animation using the public GitHub contribution calendar. Green tiles reveal numbers and mines are flagged.</desc>',
             f'<style>{"".join(css)}</style>',
             f'<rect x=".5" y=".5" width="{svg_width-1}" height="{svg_height-1}" rx="12" fill="{palette["bg"]}" stroke="{palette["border"]}"/>',
             f'<text x="26" y="31" font-size="13" font-weight="650" fill="{palette["text"]}">MINESWEEPER</text>',
             f'<text x="26" y="51" font-size="11" fill="{palette["muted"]}">A year of contributions. One minefield.</text>',
             f'<circle cx="{svg_width-114}" cy="27" r="3" fill="#3fb950"/>',
             f'<text x="{svg_width-104}" y="31" font-size="10" fill="{palette["muted"]}" class="live" style="animation:running {duration}s steps(1,end) infinite">SWEEPING</text>',
             f'<text x="{svg_width-104}" y="31" font-size="10" fill="#3fb950" class="complete" opacity="0" style="animation:finish {duration}s steps(1,end) infinite">CLEARED</text>']
    for i, cell in enumerate(cells):
        if cell is None:
            continue
        x, y = left + i % width * step, top + i // width * step
        parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{palette["greens"][cell["level"]]}" stroke="{palette["border"]}" stroke-width=".35"/>')
        if i in mines:
            name = flags[i]
            content = f'<path d="M{x+4} {y+10}V{y+2}l5 2-5 2M{x+2} {y+10}h5" fill="#f85149" stroke="#f85149" stroke-width="1.2" stroke-linejoin="round"/>'
        else:
            name = reveals[i]
            content = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{palette["open"]}" stroke="{palette["grid"]}" stroke-width=".5"/>'
            if numbers[i]:
                content += f'<text x="{x+6}" y="{y+9.5}" text-anchor="middle" class="digit" font-size="10" fill="{palette["numbers"][numbers[i]-1]}">{numbers[i]}</text>'
        parts.append(f'<g class="reveal" opacity="0" style="animation:{name} {duration}s steps(1,end) infinite">{content}</g>')
    positions = [f'{left+e["index"]%width*step+6} {top+e["index"]//width*step+6}' for e in events]
    keytimes = [0, *[time / duration for time in times], 1]
    values = [positions[0], *positions, positions[-1]]
    parts.append(f'<g class="cursor" style="animation:running {duration}s steps(1,end) infinite"><animateTransform attributeName="transform" type="translate" values="{";".join(values)}" keyTimes="{";".join(f"{t:.6f}" for t in keytimes)}" dur="{duration}s" repeatCount="indefinite" calcMode="discrete"/><path d="M0 0v12l3-3 3 5 2-1-3-5h5z" fill="{palette["text"]}" stroke="{palette["bg"]}" stroke-width="1.4" stroke-linejoin="round"/></g>')
    period = f'{calendar["from"]} — {calendar["to"]}'
    parts.extend([f'<text x="26" y="207" font-size="10" fill="{palette["muted"]}">{calendar["total"]:,} public contributions · {period}</text>',
                  f'<text x="{svg_width-26}" y="207" text-anchor="end" font-size="10" fill="{palette["muted"]}">{len(mines):03} MINES</text>', '</svg>'])
    return ''.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--username', default='jaydonkc')
    parser.add_argument('--output', type=Path, default=Path('assets'))
    parser.add_argument('--html', type=Path, help='Use a saved public calendar response for offline preview')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', args.username):
        parser.error('Invalid GitHub username')
    if args.html:
        html = args.html.read_text()
    else:
        request = Request(f'https://github.com/users/{args.username}/contributions',
                          headers={'User-Agent': 'contribution-minesweeper', 'Accept-Language': 'en-US'})
        with urlopen(request, timeout=30) as response:
            html = response.read().decode('utf-8')
    calendar = parse_calendar(html, args.username)
    # Fetch/validation happens before writes so failed refreshes retain the previous board.
    args.output.mkdir(parents=True, exist_ok=True)
    for theme in THEMES:
        name = 'minesweeper.svg' if theme == 'light' else 'minesweeper-dark.svg'
        (args.output / name).write_text(render_svg(calendar, theme))
    (args.output / 'contributions.json').write_text(json.dumps(calendar, separators=(',', ':')) + '\n')
    print(f'Generated {len(calendar["days"])} days / {calendar["total"]:,} public contributions for @{args.username}')


if __name__ == '__main__':
    main()
