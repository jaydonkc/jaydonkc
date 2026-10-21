## Contribution Minesweeper

The profile README displays a compact, script-free Minesweeper SVG directly in GitHub, with light and dark variants. It shows only the contribution grid and cursor. Smooth pointer movement, uneven pauses, and local moves make the recorded game easier to follow.

Moves use revealed-number deductions, including simple subset patterns. When no logical move is available, the player estimates risk from visible clues and pauses before guessing. The generator tries up to 32 seeded boards and records the first successful game, or the game with the most safe tiles revealed if none succeeds. It never uses hidden mine locations to select a move or flag. A losing guess reveals the mines before the loop restarts.

The layout and replay are deterministic for each public contribution snapshot. Refreshing the profile or restarting the animation repeats the same game. Changed contribution data produces a new seed when the daily refresh runs. It is a curated replay rather than a live game.

Python 3.10+ generates the assets without packages, API keys, or a personal access token:

```sh
python3 scripts/generate.py --username jaydonkc --output assets
python3 -m unittest discover -s tests -p 'test_*.py'
```

Open either SVG in `assets/` to preview it. Use `--html path/to/calendar.html` to generate from a saved public-calendar response. Invalid or incomplete responses are rejected before overwriting assets.

The `Contribution Minesweeper` workflow refreshes the public calendar daily at 13:17 UTC and saves changed assets as the GitHub Actions bot. It also runs on source changes and supports manual refreshes. Branch rules must allow the workflow to update the generated files. A failed fetch leaves the previous animation in place.

The animation uses activity levels and counts from the logged-out public GitHub calendar. It does not change the native contribution graph. Reduced-motion visitors see a still board.
