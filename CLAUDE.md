# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Tidal music automation service that rebuilds Tidal playlists on a daily schedule. It deploys as AWS Lambda functions via AWS CDK:

* `src/update_daily_blend.py` — a "Daily Blend" from Tidal mixes plus last.fm recommendations.
* `src/update_darkroom.py` — a "Darkroom" playlist built from Tidal radio consensus over MixesDB mix
  tracklists.

`src/playlist.py` holds that pipeline; `update_darkroom.py` is a thin wrapper supplying a MixesDB search
query, a playlist id and a size.

Darkroom works by consensus rather than by scoring tracks. It widens a MixesDB date window from 12 months
until the corpus holds at least `playlist_size` distinct candidates, reads a Tidal radio for every
candidate, and ranks the returned tracks by **how strongly the radios vouch for them** — each radio casts a
vote of `1 - position/length`, since Tidal returns a radio in relevance order and a track returned only near
the bottom is weakly related. Candidates are taken round-robin across mixes rather than mix by mix, so when
the corpus is larger than the clock allows every mix still contributes seeds; consensus depends on radios
being *independent*, and 500 seeds spread over 118 mixes vouch far better than 500 drawn from the hottest 30. Tracks with
no Tidal bpm are dropped, and the top of that ranking is then annealed to a tempo span: while the widest
tempo ratio in the selection exceeds the ±8% a Technics pitch fader can bridge, the track furthest from the
selection's median is dropped — least-recommended first on ties — and replaced by the next most-recommended
track that keeps the span inside the fader.

Almost none of the final playlist comes from the mixes themselves; the mix tracklists are the *seeds*, and
what lands in the playlist is the material Tidal's radios agree is adjacent to them. Genre scoring was
tried and removed: weighting artists by last.fm/Discogs genre affinity actively promoted an out-of-place
Luomo track (1.31x the median) while demoting Vladislav Delay (0.86x) — the same person — because a
corpus-centroid profile rewards the genre's generic middle and punishes its distinctive edges. Track-level
metadata cannot separate these either: bpm, musical key, popularity, duration and replayGain were each
measured and each put the complaint dead centre or backwards. `src/discogs.py` was deleted with the genre
weighting; `src/last_fm.py` stays because the Daily Blend uses it and `LastFmTrack` is Tidal's search
interface.

A second hop — taking radios of the radio results — was measured and rejected: 95% of what it returns is
already in the first-hop pool, and none of the genuinely new tracks came close to the ranking cutoff.
Radios are roughly symmetric, so the best-corroborated tracks are exactly the ones whose neighbourhoods are
already mapped.

Both run on staggered 15-minute intervals from 10:00 UTC, which is 04:00 Chicago in winter and
05:00 in summer — the latest UTC hour that never starts a job before 4AM local.

## Data sources

MixesDB's `Special:Search` page renders its results **client-side**, so it cannot be scraped. Use the
MediaWiki JSON API at `https://www.mixesdb.com/w/api.php`, which honours MixesDB's custom search keywords
(`style:`, `date:`, `hasplayer`, `-tracklist:none`). `srsort=hotness_desc` works; bare `hotness` does not.
There is **no OR syntax between terms** — `|`, `,` and `OR` all behave as AND, so multiple `style:` terms are
an *intersection*. Darkroom asked for `style:"Dub Techno" style:Minimal` and no longer does: measured over the
same 12 months, the intersection is 15 mixes while `style:"Dub Techno"` alone is 123, and the larger corpus is
also the purer one. Of those 118 usable mixes only 19 carry any house tag, the rest co-tagging Deep Techno,
Techno and Ambient, and the artist head is Rhythm & Sound, Luigi Tozzi, Basic Channel, Amotik and Polygonia —
where the intersection corpus contained Bob Marley and "Is It Disco?". `minimal` was the less distinguishing
tag anyway (tag rarity 0.627 against 1.238 for `dub techno`) and was pulling in minimal-*house* mixes. A
genuine union across styles would still mean one request per style merged client-side; that was tried and
reverted. **Inside a single keyword the comma is a
value list, not AND**: `date:2026,2025-12,2025-11` matches a mix from any one of them, and token order does
not change the result set. **Negation works**: a leading `-` on `style:` excludes server-side, verified 0 leaks over 500 results.
`srlimit=max` caps anonymous results at 500, so a query with more hits is silently truncated to the 500
hottest. That cap is why the date window stops widening once a wider window returns no more candidates
than the last: past 500 results a wider window returns the same 500 hottest mixes.

Mix counts per window are steeply non-linear and the near end is the sparse end, because MixesDB
categorises and tracklists mixes well after they are posted. Measured on 2026-09-05: 3 months returned 1
mix, 6 returned 3, 9 returned 9, 12 returned 15, 18 returned 38, 24 returned 48, 36 returned 70. A fixed
lookback is therefore the wrong control — the window widens until the corpus is big enough instead.

The `MixesDB:Explorer` pages are server-rendered but only ever emit ~25 rows; the rest loads via JS. Every
Explorer query so far has an equivalent `list=search` query that is a strict superset, so use the API. The
Explorer's `style=` codes are groups, not categories — `TA` is "Techno / Acid".

`titles=` accepts 50 per request for anonymous clients. Errors arrive as HTTP 200 with an `error` object,
so check the body, not just the status. `robots.txt` sets `Crawl-delay: 4`.

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

### Simplification cadence
A `Stop` hook (`.claude/hooks/simplify-cadence.sh`, wired up in `.claude/settings.json`) counts the lines of
`src/`, `tests/` and `aws/` that have changed since the last simplifier pass. Once that crosses
`SIMPLIFY_CHURN_THRESHOLD` (default 80) it asks for a `code-simplifier` pass scoped to just those files, so
cleanup batches up instead of running after every edit. Deletions count toward the churn but are never sent
to the simplifier. Run the script with `--checkpoint` after a pass to absorb it into the baseline, or
`--status` to see what is pending.

## Committing

The git log is this project's ledger of work and its set of revert points, so commit and push without being
asked. Do not wait for permission, and do not leave finished work sitting in the working tree.

Commit when a coherent unit of work is green. Commit before starting anything long or risky — a broad
refactor, a dependency bump, a multi-agent run — so there is a known-good point to reset to if it goes
wrong or gets killed part-way. Commit a `code-simplifier` pass as its own commit, so a bad simplification
can be reverted without losing the functional change underneath.

Green means `just check` is no worse than you found it. `tests/test_last_fm_matching.py` has two failures
that hit the live last.fm API — `test_matt_and_kim` and `test_not_various_artists_album` — and they
reproduce on `main`. Anything beyond those is yours to fix before committing.

This is a solo project, so committing and pushing straight to `main` is fine and is the default. Cut a
kebab-case topic branch only when the work is genuinely exploratory and might be abandoned wholesale. Push
after every commit either way — an unpushed commit is not a durable revert point.

Match the existing log. Subjects are short, lowercase and imperative, with no scope prefix. Bodies are
prose wrapped at about 76 characters, and they carry what the diff cannot: why the change is shaped the way
it is, which alternatives were ruled out and on what evidence, the measurements behind any claim, and
anything left in a surprising state — a deployed stack that no longer matches the code, a pre-existing
failure, a follow-up deliberately deferred.
