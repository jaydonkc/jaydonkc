#!/usr/bin/env python3
"""Generate a script-free Minesweeper SVG from GitHub's public calendar."""
import argparse
from datetime import date, timedelta
from hashlib import sha256
from html import escape
from html.parser import HTMLParser
import json
import math
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


def deductions(width, valid, visible, flagged):
    """Infer moves using revealed numbers only, including simple subset patterns."""
    constraints = []
    safe, mines = set(), set()
    for index, number in sorted(visible.items()):
        nearby = set(neighbors(index, width, 7)) & valid
        unknown = nearby - visible.keys() - flagged
        remaining = number - len(nearby & flagged)
        if unknown:
            constraints.append((unknown, remaining))
            if remaining == 0:
                safe.update(unknown)
            elif remaining == len(unknown):
                mines.update(unknown)
    for smaller, count in constraints:
        for larger, other_count in constraints:
            if smaller < larger:
                difference = larger - smaller
                if other_count == count:
                    safe.update(difference)
                elif other_count - count == len(difference):
                    mines.update(difference)
    return safe, mines, constraints


def choose_move(width, valid, visible, flagged, cursor, rng, mine_count):
    safe, mines, constraints = deductions(width, valid, visible, flagged)
    def distance(index):
        return math.hypot(index % width - cursor % width,
                          index // width - cursor // width)
    options = [(index, 'reveal') for index in sorted(safe)]
    options += [(index, 'flag') for index in sorted(mines)]
    if options:
        index, kind = min(options, key=lambda move: distance(move[0]) + rng.uniform(0, .65))
        return kind, index, 'deduction'
    unknown = valid - visible.keys() - flagged
    baseline = (mine_count - len(flagged)) / len(unknown)
    def risk(index):
        estimates = [remaining / len(cells) for cells, remaining in constraints if index in cells]
        return max(estimates) if estimates else baseline
    index = min(sorted(unknown), key=lambda i: (round(risk(i), 6), distance(i) + rng.uniform(0, 1.5)))
    return 'reveal', index, 'guess'


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
    start = min(valid, key=lambda i: (cells[i]['level'], i))
    safe = {start, *neighbors(start, width, 7)}
    candidates = sorted(valid - safe)
    best = None
    # Curate one recorded game at generation time, then replay it unchanged.
    # Each candidate is played using visible clues, with genuine guesses if stuck.
    for attempt in range(32):
        rng = random.Random(seed + attempt * 0x9e3779b9)
        weighted = sorted(candidates, key=lambda i: rng.random() ** (1 / (1 + cells[i]['level'])))
        mines = set(weighted[-round(len(valid) * .16):])
        numbers = [sum(n in mines for n in neighbors(i, width, 7)) for i in range(len(cells))]
        events, opened = play_board(width, valid, mines, numbers, start, rng)
        candidate = (width, cells, mines, numbers, events)
        if events[-1]['kind'] != 'hit':
            return candidate
        if best is None or opened > best[0]:
            best = (opened, candidate)
    return best[1]


def play_board(width, valid, mines, numbers, start, rng):
    revealed, flagged, events = set(), set(), []

    def reveal(index, reason):
        if index in mines:
            events.append({'kind': 'hit', 'index': index, 'cells': sorted(mines - flagged), 'reason': reason})
            return False
        queue, opened = [index], set()
        while queue:
            item = queue.pop()
            if item in revealed or item in flagged or item not in valid or item in mines:
                continue
            revealed.add(item)
            opened.add(item)
            if numbers[item] == 0:
                queue.extend(neighbors(item, width, 7))
        if opened:
            events.append({'kind': 'reveal', 'index': index, 'cells': sorted(opened), 'reason': reason})
        return True

    reveal(start, 'first')
    cursor = start
    while valid - revealed - mines:
        visible = {i: numbers[i] for i in revealed}
        kind, index, reason = choose_move(width, valid, visible, flagged, cursor, rng, len(mines))
        if kind == 'flag':
            flagged.add(index)
            events.append({'kind': kind, 'index': index, 'cells': [index], 'reason': reason})
        elif not reveal(index, reason):
            break
        cursor = index
    if events[-1]['kind'] != 'hit':
        for i in sorted(valid - revealed - flagged):
            events.append({'kind': 'flag', 'index': i, 'cells': [i], 'reason': 'deduction'})
    return events, len(revealed)


def build_timeline(events, width):
    """Plan eased pointer travel, varied thinking time, and a settled click."""
    rng = random.Random(sha256(json.dumps(events, sort_keys=True).encode()).digest())
    first_index = events[0]['index']
    previous = (first_index % width - .8, first_index // width - .8)
    now, times = .8, []
    motion = [(0, *previous)]
    for index, event in enumerate(events):
        target = (event['index'] % width + rng.uniform(-.10, .10),
                  event['index'] // width + rng.uniform(-.10, .10))
        think = rng.uniform(.22, .58)
        if event['reason'] == 'guess':
            think += rng.uniform(1.1, 2.1)
        elif index and index % 9 == 0:
            think += rng.uniform(.7, 1.4)
        if index and len(events[index - 1]['cells']) > 5:
            think += rng.uniform(.4, .8)
        travel = .22 + min(.75, math.dist(previous, target) * .025)
        depart = now + think
        arrive = depart + travel
        click = arrive + rng.uniform(.12, .25)
        motion.extend([(depart, *previous), (arrive, *target), (click, *target)])
        times.append(click)
        now, previous = click, target
    # Keep the uneven rhythm, but fit longer games into a one-minute replay.
    speed = min(1, 56 / now)
    times = [time * speed for time in times]
    motion = [(time * speed, x, y) for time, x, y in motion]
    duration = now * speed + 4
    motion.append((duration, *previous))
    return times, motion, duration


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
    step, size, left, top = 15, 12, 12, 12
    svg_width, svg_height = width * step + 21, 126
    times, motion, duration = build_timeline(events, width)
    css = ['.digit{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-weight:700}',
           '@media(prefers-reduced-motion:reduce){.reveal{animation:none!important;opacity:1!important}.cursor{display:none}}']
    overlays = {}
    for event, time in zip(events, times):
        percentage = time / duration * 100
        name = f's{len(css)}'
        css.append(f'@keyframes {name}{{0%,{percentage:.5f}%{{opacity:0}}{percentage+.0001:.5f}%,99.9999%{{opacity:1}}100%{{opacity:0}}}}')
        for index in event['cells']:
            overlays[index] = (name, event['kind'], index == event['index'])
    fade = (times[-1] + 1) / duration * 100
    css.append(f'@keyframes cursor{{0%,{fade:.5f}%{{opacity:1}}{fade+.01:.5f}%,100%{{opacity:0}}}}')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}" height="{svg_height}" viewBox="0 0 {svg_width} {svg_height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(calendar["username"])} contribution Minesweeper</title>',
             '<desc id="desc">A Minesweeper animation on the public GitHub contribution grid, with deliberate cursor movement and pauses. Moves follow revealed clues; uncertain guesses can hit a mine. The same recorded board replays until the contribution snapshot changes.</desc>',
             f'<style>{"".join(css)}</style>']
    for i, cell in enumerate(cells):
        if cell is None:
            continue
        x, y = left + i % width * step, top + i // width * step
        parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{palette["greens"][cell["level"]]}" stroke="{palette["border"]}" stroke-width=".35"/>')
        if i not in overlays:
            continue
        name, kind, hit = overlays[i]
        if kind == 'flag':
            content = f'<path d="M{x+4} {y+10}V{y+2}l5 2-5 2M{x+2} {y+10}h5" fill="#f85149" stroke="#f85149" stroke-width="1.2" stroke-linejoin="round"/>'
        elif kind == 'hit':
            content = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{"#b6232f" if hit else palette["open"]}"/><path d="M{x+6} {y+2}v8M{x+2} {y+6}h8M{x+3} {y+3}l6 6M{x+3} {y+9}l6-6" stroke="#ff7b72" stroke-width=".9"/><circle cx="{x+6}" cy="{y+6}" r="2.6" fill="{"#ffffff" if hit else "#ff7b72"}"/>'
        else:
            content = f'<rect x="{x}" y="{y}" width="{size}" height="{size}" rx="2" fill="{palette["open"]}" stroke="{palette["grid"]}" stroke-width=".5"/>'
            if numbers[i]:
                content += f'<text x="{x+6}" y="{y+9.5}" text-anchor="middle" class="digit" font-size="10" fill="{palette["numbers"][numbers[i]-1]}">{numbers[i]}</text>'
        parts.append(f'<g class="reveal" opacity="0" style="animation:{name} {duration:.4f}s steps(1,end) infinite">{content}</g>')
    keytimes = ';'.join(f'{time / duration:.8f}' for time, _, _ in motion)
    positions = ';'.join(f'{left+x*step+6:.2f} {top+y*step+6:.2f}' for _, x, y in motion)
    splines = ';'.join(['.35 0 .2 1'] * (len(motion) - 1))
    parts.append(f'<g class="cursor" style="animation:cursor {duration:.4f}s steps(1,end) infinite"><animateTransform attributeName="transform" type="translate" values="{positions}" keyTimes="{keytimes}" keySplines="{splines}" dur="{duration:.4f}s" repeatCount="indefinite" calcMode="spline"/><path d="M0 0v12l3-3 3 5 2-1-3-5h5z" fill="{palette["text"]}" stroke="{palette["bg"]}" stroke-width="1.4" stroke-linejoin="round"/></g>')
    parts.append('</svg>')
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
