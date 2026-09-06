# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Tidal music automation service that rebuilds Tidal playlists on a daily schedule. It deploys as AWS Lambda functions via AWS CDK:

* `src/update_daily_blend.py` — a "Daily Blend" from Tidal mixes plus last.fm recommendations.
* `src/update_darkroom.py` — a "Darkroom" playlist of MixesDB mix tracklist entries, ranked by a genre
  confidence that Tidal radios supply the evidence for.

`src/playlist.py` holds that pipeline; `update_darkroom.py` is a thin wrapper supplying a declared style, a
MixesDB search query, a playlist id and a size. The style string is used twice — it searches MixesDB and it
anchors the genre profile — so the two can never drift apart.

**Every track in the playlist comes from a MixesDB tracklist. Nothing a radio returns can enter it.**
Darkroom widens a MixesDB date window from 12 months until the corpus is larger than the clock could walk,
takes candidates round-robin across mixes, and resolves each on Tidal with a single search. Only candidates
that come back carrying a bpm get a radio read, because the tempo anneal discards the rest anyway and a
timed candidate is three times likelier to have a radio at all (60.7% against 20.0%). The radio is read as
**testimony, never as contents**: the candidate's own artist vouches at weight 1.0, and each artist in the
radio's head decile vouches at `1 - position/length`, since Tidal returns a radio in relevance order.
A vouch is worth the cosine between that artist's last.fm tags — or Discogs styles where last.fm is silent —
and a profile built from the 100 artists last.fm's own `Dub Techno` tag names. Both vectors are scaled by
tag rarity measured over the artists *this run* gathered. A candidate's confidence is the weighted **mean**
of its vouches, which puts a one-vouch and a nine-vouch candidate on the same axis with no tiering; an
untagged artist is dropped from the mean rather than scored zero, so no evidence means abstain, not
rejection. The top of that ranking is then annealed to a tempo span: while the widest tempo ratio in the
selection exceeds the ±8% a Technics pitch fader can bridge, the track furthest from the selection's median
is dropped — least-confident first on ties — and replaced by the next most-confident track that keeps the
span inside the fader. Round-robin survives the redesign for a different reason than it arrived with: the
clock cuts the corpus at roughly 70%, and round-robin spreads the missing part evenly across every mix
rather than amputating the coldest ones.

Graded on 22 probe radios, canon (11) against **all** 11 non-canon — a harder test than canon-against-
intruders, which almost anything passes — the neighbourhood scores **AUC 1.000**, worst canon 0.2365 minus
best non-canon 0.1416 = **gap +0.0949**, and the eleven canon probes occupy the top eleven slots exactly.
Own-artist tags alone score **AUC 0.843, gap −0.2124**, ranking four generic-techno corpus samples (Jonas
Kopp, Oscar Mulero, Luke Slater, Luca Agnelli) *above* Vladislav Delay and Rhythm & Sound. Those four are
what the radio is for. Two of eleven canon probes carry `dub techno` at 0.00 on their own tags — Deepbass
and Juan Atkins — and are recovered entirely by their neighbourhoods.

This is not the genre scoring deleted at `6148041`, and the difference is the **reference**, not the signal.
That version weighted artists by affinity to a *corpus centroid*, which promoted an out-of-place Luomo track
(1.31x the median) while demoting Vladislav Delay (0.86x) — the same person — because a centroid rewards the
genre's generic middle and punishes its distinctive edges. Discogs reproduces the inversion on demand: at 0%
house mass in the reference, Body Speaking 0.230 against Vladislav Delay 0.288 (correct); at **5%**, 0.312
against 0.287 (inverted). Five percent of house flips it, same data, same cosine. The reference here is the
declared style's own last.fm roster and nothing else — it assigns `house` and `deep house` 0.021 each
against `dub techno` 0.875, so the house penalty is earned rather than written down, and it picks up `deep
techno` and `ambient techno` unprompted, which matters because Deepbass and Luigi Tozzi are canon but tagged
`deep techno`. The corpus now enters the score in exactly one place, the rarity denominator, where a per-tag
scalar cannot rotate the direction. Track-level Tidal metadata still cannot separate these: bpm, musical
key, popularity, duration and replayGain were each measured and each put the complaint dead centre or
backwards, and Tidal exposes **no genre field at all** — 36 fields on a track and the only genre-shaped path
is `mediaMetadata.tags = ["LOSSLESS"]`, while `GET genres` is a 20-name browse taxonomy with no reverse
lookup and no Techno in it.

**Never build the rarity correction from the style roster.** Inside a dub-techno roster `dub techno` sits in
nearly every vector, its IDF collapses to zero, and the correction erases the one tag that matters: AUC
1.000 → 0.785, gap +0.0949 → −0.1815, and Luomo goes back above Vladislav Delay at 0.71x. Any broad
population works — the run's own evidence artists give gap +0.0949, the 805 corpus artists +0.0817. The
defence is structural: the roster's tag vectors go into `LastFm`'s own cache but never into `TagLane`, and a
test pins it. Removing the rarity altogether also fails (AUC 0.967, gap −0.0635).

`src/discogs.py` was deleted at `6148041` and is back for one narrow job: filling in artists last.fm has
never tagged, scored through the same profile so it needs no anchor of its own. It recovers 35% (14 of 40)
of the last.fm-silent corpus artists. Discogs as a *ranker* stays rejected — a hand-free anchor derived from
`style=Dub Techno` is so narrow (`Dub Techno 0.987, Techno 0.395, Dub 0.317`) that Discogs' coarse `Techno`
dominates the cosine and generic techno outranks the canon (AUC 0.934, gap −0.0414). last.fm
`album.getTopTags` covers 33.2% of neighbours and fails alone (AUC 0.926); `track.getTopTags` returned 0 of
250 and is dead for this genre at every popularity level.

The clock is the binding constraint and the budget only closes because of two things. Radios are bought only
for timed candidates, and Darkroom resolves with `find_timed_track`, which takes the first surviving search
result instead of fetching each candidate album to prefer the original pressing. Measured over 50 fresh
candidates, `find_equivalent_track` costs 1.70 Tidal requests — exactly 2 on 33 of 33 resolutions, one of
which is the album — so the first survivor *was* the answer in every measured resolution. That takes a
candidate from 0.979s to 0.629s, 855 walked to 1331, and a timed pool of 221 to 343 against the ~350 the
anneal needs for P(100 tracks) ≈ 0.98. `find_equivalent_track` is left alone because the Daily Blend uses
it. Serial lookups do not close either (0.829s per candidate, P(100) ≈ 0.05), so last.fm and Discogs run on
a single background worker; 289s of lookups alongside 837s of Tidal is never the critical path.

A second hop — taking radios of the radio results — was measured and rejected: 95% of what it returns is
already in the first-hop pool, and none of the genuinely new tracks came close to the ranking cutoff.

Both run on staggered 15-minute intervals from 10:00 UTC, which is 04:00 Chicago in winter and
05:00 in summer — the latest UTC hour that never starts a job before 4AM local.

## Data sources

MixesDB's `Special:Search` page renders its results **client-side**, so it cannot be scraped. Use the
MediaWiki JSON API at `https://www.mixesdb.com/w/api.php`, which honours MixesDB's custom search keywords
(`style:`, `date:`, `hasplayer`, `tracklist:`). `srsort=hotness_desc` works; bare `hotness` does not.
There is **no OR syntax between terms** — `|`, `,` and `OR` all behave as AND, so multiple `style:` terms are
an *intersection*. Darkroom asked for `style:"Dub Techno" style:Minimal` and no longer does: measured over the
same 12 months, the intersection is 15 mixes while `style:"Dub Techno"` alone is 123, and the larger corpus is
also the purer one. Of those 118 usable mixes only 19 carry any house tag, the rest co-tagging Deep Techno,
Techno and Ambient, and the artist head is Rhythm & Sound, Luigi Tozzi, Basic Channel, Amotik and Polygonia —
where the intersection corpus contained Bob Marley and "Is It Disco?". `minimal` was the less distinguishing
tag anyway (tag rarity 0.627 against 1.238 for `dub techno`) and was pulling in minimal-*house* mixes. A
genuine union across styles would still mean one request per style merged client-side; that was tried and
reverted. The query also asks for `tracklist:complete` rather than merely `-tracklist:none`, which over the
same window is 46 mixes and 1053 candidates against 118 and 2128. That now *does* cost candidates — the
clock reaches about 1331 and the 12-month `tracklist:complete` corpus holds 1053, so the window widens one
step to compensate — and it is kept anyway, because the candidates *are* the playlist now and an incomplete
tracklist lists only the tracks somebody could identify, which skews toward the recognisable. `hasplayer` was measured and not adopted: it takes 123 mixes to 122. **Inside a single keyword the comma is a
value list, not AND**: `date:2026,2025-12,2025-11` matches a mix from any one of them, and token order does
not change the result set. **Negation works**: a leading `-` on `style:` excludes server-side, verified 0 leaks over 500 results.
`srlimit=max` caps anonymous results at 500, so a query with more hits is silently truncated to the 500
hottest. That cap is why the date window stops widening once a wider window returns no more candidates
than the last: past 500 results a wider window returns the same 500 hottest mixes.

Mix counts per window are steeply non-linear and the near end is the sparse end, because MixesDB
categorises and tracklists mixes well after they are posted. Measured on 2026-09-05: 3 months returned 1
mix, 6 returned 3, 9 returned 9, 12 returned 15, 18 returned 38, 24 returned 48, 36 returned 70. A fixed
lookback is therefore the wrong control — the window widens until the corpus is big enough instead. "Big
enough" is what the clock could reach, `(seconds_left - seconds_to_set_playlist) / seconds_per_request`, not
a fixed count: 12 months = 1053 candidates against a target of 1754, so the live query widens to 18 months
and costs one extra MixesDB request.

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
