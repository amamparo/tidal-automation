# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Tidal music automation service that rebuilds a Tidal playlist on a daily schedule. It deploys as an
AWS Lambda function via AWS CDK: `src/update_daily_blend.py` builds a "Daily Blend" from Tidal mixes plus
last.fm recommendations.

The playlist is rewritten differentially, so a surviving track keeps its date-added, and then kept in
newest-first position order: arrivals are inserted at the top and `Tidal.set_playlist_tracks` reconciles the
rest with in-place moves, which preserve date-added where a remove-and-re-add would reset it. The sort is
stable because a day's arrivals share one timestamp — measured 75 of 100 on one run — and an unstable sort
would reshuffle that block every day. Once ordered, a daily run makes no moves; the first run over a
100-track playlist made 96 and took 50 seconds.

It runs at 10:00 UTC, which is 04:00 Chicago in winter and 05:00 in summer — the latest UTC
hour that never starts the job before 4AM local.

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
