## Contribution Minesweeper

The profile README displays an autoplay, script-free Minesweeper SVG directly in GitHub. It has light and dark variants. Green tiles use the public contribution calendar; the animation reveals numbers, flags mines, clears the field, and loops. It is a choreographed animation, not a guessing-free solver.

Python 3.10+ generates the assets without packages, API keys, or a personal access token:

```sh
python3 scripts/generate.py --username jaydonkc --output assets
python3 -m unittest discover -s tests -p 'test_*.py'
```

Open either SVG in `assets/` to preview it. Use `--html path/to/calendar.html` to generate from a saved public-calendar response. Invalid or incomplete responses are rejected before overwriting assets.

The `Contribution Minesweeper` workflow refreshes the public calendar daily at 13:17 UTC and saves changed assets as the GitHub Actions bot. It also runs on source changes and supports manual refreshes. Branch rules must allow the workflow to update the generated files. A failed fetch leaves the previous animation in place.

The animation uses activity levels and counts from the logged-out public GitHub calendar. It does not change the native contribution graph. Reduced-motion visitors see a still, cleared board.
