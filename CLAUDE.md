# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Tidal music automation service that rebuilds Tidal playlists on a daily schedule. It deploys as AWS Lambda functions via AWS CDK:

* `src/update_daily_blend.py` — a "Daily Blend" from Tidal mixes plus last.fm recommendations.
* `src/update_dub_techno.py` — a "Dub Techno" playlist from MixesDB mix tracklists.

`src/playlist.py` holds the weighted-lottery selection and Tidal resolution; `update_dub_techno.py` is a
thin wrapper supplying a MixesDB search query, a playlist id and a size.

Both run on staggered 15-minute intervals from 10:00 UTC, which is 04:00 Chicago in winter and
05:00 in summer — the latest UTC hour that never starts a job before 4AM local.

## Data sources

MixesDB's `Special:Search` page renders its results **client-side**, so it cannot be scraped. Use the
MediaWiki JSON API at `https://www.mixesdb.com/w/api.php`, which honours MixesDB's custom search keywords
(`style:`, `date:`, `hasplayer`, `-tracklist:none`). `srsort=hotness_desc` works; bare `hotness` does not.
There is **no OR syntax** — `|`, `,` and `OR` all behave as AND — so a multi-style search would mean one
request per style merged client-side. That was tried and reverted; one style is plenty for a 100-track
playlist. **Negation works**: a leading `-` on `style:` excludes server-side, verified 0 leaks over 500 results.
`srlimit=max` caps anonymous results at 500, so a query with more hits is silently truncated to the 500
hottest.

The `MixesDB:Explorer` pages are server-rendered but only ever emit ~25 rows; the rest loads via JS. Every
Explorer query so far has an equivalent `list=search` query that is a strict superset, so use the API. The
Explorer's `style=` codes are groups, not categories — `TA` is "Techno / Acid".

`titles=` accepts 50 per request for anonymous clients. Errors arrive as HTTP 200 with an `error` object,
so check the body, not just the status. `robots.txt` sets `Crawl-delay: 4`. See `PLAN.md` for the details.

## Development Commands

### Setup & Dependencies
```bash
just install        # Install Python dependencies via Poetry
```

### Testing
```bash
just test          # Run all unit tests
poetry run python -m unittest tests.test_last_fm_matching.LastFmMatching.test_specific_test  # Run specific test
```

### Code Quality
```bash
just lint          # Run pylint on src, tests, and aws directories
just types         # Run mypy type checking
just check         # Run lint, types, test, and synth (full quality check)
```

### Coding guidelines
* do not add code comments. instead, make the code expressive enough as to not need code
* de-duplication: as much as possible, put repeated code into well-named helper methods.
  * however, we don't have to be DRY for DRY's sake
  * for e.g., if the helper method only has one line of code, and/or it's only used in two or three places, we don't need a new function