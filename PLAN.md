# PLAN — Dub Techno playlist from MixesDB

## What and why

A second scheduled Lambda that rebuilds a Tidal "Dub Techno" playlist of 100 tracks, drawn from the
tracklists of the recently-hot Dub Techno DJ mixes on [MixesDB](https://www.mixesdb.com). It reproduces the
result set of the user's `Special:Search` URL — `style:"Dub Techno" -tracklist:none hasplayer` over a rolling
date window, sorted by hotness — reads each mix page's tracklist, and resolves the tracks on Tidal with the
matcher the daily blend already uses.

It mirrors `src/update_daily_blend.py` in shape and adds nothing to `src/tidal.py`. Everything below that is
stated as measured was re-verified against the live API, the live Tidal account, and the repo's own gates on
2026-09-03.

---

## Key decisions

| Decision | Rationale |
|---|---|
| **MediaWiki JSON API, never HTML scraping** | The `Special:Search` page renders results **client-side**: the served HTML contains `<div id="mixesdb-advanced-search-mount"></div>` and **zero** result rows. `api.php?action=query&list=search` honors MixesDB's custom keywords (`style:`, `date:`, `hasplayer`, `-tracklist:none`) and returns all 122 hits in one response. |
| **`srsort=hotness_desc` — hotness is NOT lost** | The stated ground truth is wrong. Bare `srsort=hotness` returns `badvalue`; **`hotness_desc` is an accepted value** (`action=paraminfo&modules=query+search` lists `hotness_asc`/`hotness_desc`). Verified live: 122 hits, no warning, and an ordering that differs from `relevance` (relevance leads with `Black Merlin - Monument 533`; hotness leads with `The Bug - RA Podcast (RA.1052)`). Never send bare `sort=hotness` to the custom UI modules — their `sortdir` defaults to `asc`, silently giving the *coldest* mixes. |
| **Page wikitext + our own parser, not `action=mixesdbsearchjsonld`** | The JSON-LD module returns pre-parsed tracks but emits `@type: Event` with **no `track[]` for 26 of 122 pages** (every `@ Venue` live set — 19% of the pool), strips ~99% of remix parentheticals, and leaks `[0??] Andy Stott`-shaped artists. It is also an undocumented, versionless custom module. `prop=revisions` is core MediaWiki and the parser below is exact. |
| **Differential playlist writes, so date-added survives** | `Tidal.set_playlist_tracks` no longer clears and re-adds. It removes only the tracks that are leaving and appends only the ones arriving, so a track that survives an update keeps its original date-added and the playlist can be sorted by it to see what is new versus what has been hanging around. Verified live: 87 of 87 survivors kept their timestamp while 13 newcomers took a fresh one. This applies to **every** playlist in the repo, the daily blend included. |
| **No caps anywhere in selection** | No per-mix, per-artist or per-style quota. Every cap that was proposed got replaced by a weight, because a cap is an arbitrary cliff and a weight is a smooth, explainable preference. The one bound left is the search API's own `srlimit`. |
| **One style, `Dub Techno`** | Adjacent tags (`Minimal`, `Techno`) were tried and reverted — see How it works §1. One style yields 2085 candidates for 100 slots, so the extra corpus bought nothing the playlist needed and cost a per-style search, a client-side rank merge and corpus-normalised premiums. |
| **A weighted lottery, and no quotas of any kind** | Tracks are drawn without replacement with probability proportional to the weight of the mix they came from, so hotter and more recent mixes surface more tracks *by likelihood* rather than by quota. **Both** `MAX_TRACKS_PER_MIX` and `MAX_TRACKS_PER_ARTIST` are deleted — see below. Selection is now entirely a function of the weights, which is the only thing left to tune. |
| **No artist cap either — but on evidence, not symmetry** | Removing the mix cap was safe because the weights *already encode the mix*; the cap was redundant. That argument does **not** transfer: nothing in `mix_weight` mentions artists, so dropping `MAX_TRACKS_PER_ARTIST` is a real, if small, loss of control justified only by the measured shape of the pool. It holds comfortably: the pool is 2085 tracks across **1416 credited artists, 78% of whom appear exactly once**, and the loop consumes only ~6% of it. Over **3000 simulated days**, dropping the cap moved distinct artists per 100 from 95.9 to 95.4 and produced a worst case of **7 tracks by one artist**, p99 of 4. |
| **Lazy resolution with early exit** | The pool is 2085 candidates for 100 slots. Resolving all of them costs ~30 min against a 15-minute Lambda ceiling. Measured live: 100 tracks land in ~130 lookups ≈ 2 minutes. |
| **Guards before the write, raising not returning** | `set_playlist_tracks` removes departing tracks **before** adding arriving ones, and `tidalapi`'s `list_validate` raises `ValueError('An empty list was provided.')` on an empty add. Worse, a typo'd or renamed keyword returns HTTP 200 with `totalhits: 0`, `error: None`, `warnings: None` — verified. Floors turn a silent empty playlist into a loud Lambda error. |
| **Module-scoped `# pylint: disable=duplicate-code`, not a `.pylintrc` change** | R0801 genuinely fails the build: a second `src/update_*.py` with the conventional `lambda_handler` + `__main__` tail scores **9.97/10** against `fail-under=10.0`, exit 8. Verified both fixes; the one-line module pragma restores **10.00/10** without loosening `min-similarity-lines` (repo default is **4**) for the whole repo, without a new `src/lambda_entrypoint.py` module, and without touching the deployed daily blend. |
| **`LastFmTrack` stays where it is** | `find_equivalent_track` takes `LastFmTrack(title, artists)`, which is really a generic track query. Renaming it to `TrackQuery` and moving it into `src/tidal.py` touches 13 sites in the matcher, flips a public signature, and inverts the coupling so a pure-HTTP module imports `tidalapi` — all for zero behaviour change. `src/mixes_db.py` imports `LastFmTrack` directly. If the name grates, that rename is a separate mechanical commit. |

---

## How it works

Four MixesDB requests, then a lazy Tidal resolve loop, then one write.

### 1. Search — `MixesDb.__search_titles`

One search, one style:

```
GET https://www.mixesdb.com/w/api.php
  ?action=query&list=search&format=json&formatversion=2
  &srlimit=max&srsort=hotness_desc
  &srsearch=style:"Dub Techno" -tracklist:none hasplayer date:2026,2025-10,2025-11,2025-12
```

Verified live: `error: None`, `warnings: None`, `totalhits: 122`, 122 results, no `continue`. `srlimit=max`
resolves to 500 (`highmax` 5000 requires `apihighlimits`, which anonymous clients do not have), so the whole
result set arrives in one call and no `sroffset` continuation loop is needed. Every returned title is kept —
there is no cap of ours anywhere in the pipeline.

`profile=mixes` from the UI URL is omitted — verified a no-op *for this query* (identical hit count with and
without). It is not a no-op in general.

**Adjacent styles were tried and removed.** Searching `Minimal` and `Techno` alongside Dub Techno grew the
corpus from 122 mixes to 704, but MixesDB has no OR syntax (`|`, `,` and `OR` all behave as AND), so it meant
one request per style merged client-side, plus corpus-normalised per-style premiums to stop Techno's 541
tagged mixes from taking 63% of a playlist called Dub Techno. That is a lot of machinery to buy pool size the
playlist does not need: one style already yields **2085 unique candidates for 100 slots**. The style set is
back to `STYLE = 'Dub Techno'` and the only style logic left is the Ambient/IDM penalty below.

**Guard:** raise if `totalhits < MINIMUM_SEARCH_HITS` (40). Grounded, not arbitrary: with the diversity caps
below, 40 mixes yield 115 selectable tracks and 30 mixes yield only 89, so below ~35 mixes a 100-track
playlist is mathematically unreachable and the run should fail loudly rather than short-fill.

### 2. The rolling date window — `date_window`

```python
def date_window(today: date) -> str:
    trailing_months = [f'{today.year - 1}-{month:02d}' for month in range(today.month + 1, 13)]
    return ','.join([str(today.year), *trailing_months])
```

`date:` accepts only a comma list of `YYYY` and `YYYY-MM` tokens — verified that `date:>2025-10`,
`date:2025-10-2026-09` and `date:2025-10-01-2026-09-03` all return `totalhits: 0` at HTTP 200, silently. At
`date(2026, 9, 3)` this emits `2026,2025-10,2025-11,2025-12`, which returns **122 hits and a title list
identical in order** to the user's hand-written `2026,2025-12,2025-11,2025-10` (token order is semantically
irrelevant). Keeping the bare year token is what reaches the year-only and fuzzy-month pages
(`2026 - Verschwender b2b…`, `2026-0X - AliA @ Ilian Tape`) that a pure `YYYY-MM` list cannot.

**Do not** use `f'{year},{year-1}-12,{year-1}-11,{year-1}-10'`. Verified live: on 2027-01-02 it emits
`2027,2026-12,2026-11,2026-10` → **0 hits**. It is constant within a calendar year and collapses every January.

### 3. Wikitext — `MixesDb.__get_wikitext`

```
GET .../api.php?action=query&prop=revisions&rvprop=content&rvslots=main
  &format=json&formatversion=2&titles=<up to 50 titles, pipe-joined>
```

50 titles is a hard cap for anonymous clients — 51 returns `{"code":"toomanyvalues","limit":50}`, an error not
a clamp. 122 titles = **3 requests**; measured 78 KB and 0.54 s per batch. Verified: **the response page order
is NOT the request order**, so build a `Dict[title, wikitext]` and iterate the *search* title list to preserve
hotness ordering. Skip pages with `missing: true` or no `revisions` key rather than indexing blindly.

Politeness: one `requests.Session` with `User-Agent: tidal-automation/1.0 (+https://github.com/amamparo/tidal-automation)`
and `Accept-Encoding: gzip`, `timeout=(5.0, 30.0)`, and `sleep(4)` before every request to honour
`robots.txt`'s `Crawl-delay: 4`. That is 16 s per run for 4 requests.

**Check `response.json().get('error')`, not just the HTTP status.** Every MixesDB API error observed —
`toomanyvalues`, `badvalue`, `missingparam` — arrives as HTTP 200 with an `error` object.

### 4. The tracklist parser — `parse_tracklist` / `tracklist_lines` / `parse_line`

Pure functions in `src/mixes_db.py`. This spec was reimplemented from scratch for this plan and run over all
122 pages: **2719 raw candidate lines → 2152 accepted → 2085 unique (artist, title) from 117 of 122 pages.**

```python
TRACKLIST_HEADING = re.compile(r'^==+\s*Tracklist\s*==+\s*$', re.MULTILINE | re.IGNORECASE)
SECTION_END = re.compile(r'^\[\[Category:|^==+\s*[^=]+\s*==+\s*$', re.MULTILINE)
LIST_MARKER = re.compile(r'^#+\s*')
LEADING_TIMESTAMP = re.compile(r'^\[[\d?]{1,2}(?::[\d?]{2}){1,2}\]\s*|^\[[\d?]{1,4}\]\s*')
TRAILING_LABEL = re.compile(r'\s*\[[^\[\]]*\]\s*$')
BRACKETED_ARTIST = re.compile(r'^[\[(](.*)\]$')
FILLER = re.compile(r'^(?:[?.\-…]+|intro|outro|interview|id)$', re.IGNORECASE)
```

**Section:** slice from `TRACKLIST_HEADING.end()` to `SECTION_END.start()`. All 122 pages have exactly one
`== Tracklist ==` heading and all 122 terminate on `[[Category:`; zero track lines fall outside the slice.

**Lines:** split with `re.split(r'\r?\n', section)` — **not `str.splitlines()`**, which also splits on the
U+2028 LINE SEPARATOR two pages carry. Walk with an `inside_list` flag: `<list` opens, `</list` closes, a
`#`-prefixed line is a candidate, and any non-empty line while inside a `<list>` block is a candidate.
**Detection is per-line, not per-page** — the census is 60 pages `#`-only, 57 `<list>`-only, **5 that use
both**. `;DJ Name` labels and bare `[https://… source]` lines are excluded by construction, so they need no
rejection rule.

**Per line, in this exact order:**

1. Strip the list marker, then `.strip()`.
2. `body.replace("''", '')` — plain removal, not an anchored unwrap: 6 of the 19 italic lines wrap only part
   of the line.
3. `LEADING_TIMESTAMP.sub('', body, count=1)`. **Once, not looped** — measured: a second pass fires on **0** of
   2719 lines, and a looser looped pattern would eat `[Moosdohmen]` and destroy step 5's recovery.
4. `TRAILING_LABEL.sub('', body)`. **Once, not looped** — a second pass also fires on **0** lines. This must
   precede the split: 19 labels contain a dash (`[mould.audio - mldcs025]`).
5. Reject on `FILLER.match(body)` (527 lines) or `' - ' not in body` (6 lines). `FILLER` is strictly
   redundant — no alternative in it can contain a space, so every line it matches would be dropped by the
   dash test anyway — but it is kept because it states the intent that `Intro`/`?`/`...` are not tracks.
   Then `body.split(' - ', 1)` —
   the **first** separator. Apply `BRACKETED_ARTIST` to the **artist only**; it recovers 15 tracks written as
   `[Moosdohmen] - Paddy Dub`. Collapse whitespace in both fields.
6. Reject if the artist is empty or starts with `?` (3 lines), or the title is empty or starts with `?` (11).
7. **Reject titles shorter than 3 alphanumeric characters** (20 unique pairs). `Tidal.__titles_match` is
   bidirectional substring containment, so a 1–2 character title matches almost anything by the right artist —
   live probes produced `Retouched - F` → *The Betrothal Feast* and `Donato Dozzy - B` → *Back*, and in the
   first case the false positive then blocked the correct track as a duplicate.

Emit `MixTrack(artist, title)` with the **artist string verbatim** and the **title including any remix
parenthetical**. `MixTrack` carries **no mix title** — identity is the normalised `(artist, title)` pair, which
is exactly what lets `weigh_candidates` sum one track's weight across every mix that played it. The mix title
lives on `Tracklist`, so the per-track progress line cannot name its source mix; `len(tracklists)` in the
summary line is the markup-drift canary instead.

- **Do not split multi-artist strings.** `Tidal.__artist_name_variants` already expands `,`, `&`, ` and `,
  `vs.` and `feat.`, and `Tidal.__search_query` concatenates *every* variant into one query, so adding a
  ` X ` / ` + ` splitter measurably makes the search worse. The unhandled forms are **7 of 2085 pairs**.
- **Do not strip remix parentheticals.** 309 of the accepted titles carry one and 116 say "Remix". They are
  load-bearing: the version a DJ played is the version that belongs in the playlist, and `Tidal`'s opt-in
  version matching compares them (see below).

### 4b. Version fidelity — `Tidal.__versions_match`

**A remix must not match the original, or vice versa.** A dub techno remix of a non-dub-techno record only
belongs here *because* of the remix; matching it to the original imports the wrong genre. The worked example
is `Nitzer Ebb - Join In The Chant (Surgeon Edit)` — 1987 EBM that qualifies solely through Surgeon.

`find_equivalent_track(track, match_version=True)` makes `__best_match` skip any result whose version
disagrees. Rules, in order:
- Any parenthetical or bracketed marker is a **distinct version** unless it is neutral (`Original Mix`,
  `Album Version`, `Remastered 2022`, `Explicit`) or a collaborator credit (`feat.`, `with`). This is
  deliberately an inverted default: a whitelist of version words cannot keep up with `Reshape`, `Reassembly`,
  `Retouch`, `Reprise`, `V2`, `A Capella`.
- **Tidal's separate `version` field is read too.** 11.9% of results populate it (`Original Mix`,
  `Adriana Lopez Re-edit`) and it is almost disjoint from parenthetical names — 521 of 4366 captured results
  carry one, only 20 of those also have a paren in `name`.
- **A remixer credited as an artist counts as the remix.** Tidal often lists
  `Dreaming Trees (Forest Drive West Remix)` as *Dreaming Trees* by "Polygonia, Forest Drive West"; rejecting
  that would throw away a correct match.
- **A "live" marker is not a version.** Every track in this corpus was played in a DJ set, so "live" carries
  no signal about whether a track belongs — `(Live)`, `(Live Mix)`, `(Live At Draaimolen 2023)` are all
  neutral. The marker must be *purely* live/venue/date to qualify: `Federsen Live Dub` and
  `Seconds To Forever Live Mix` stay distinct versions, because the name is the meaningful part.
  `LIVE_PARENTHETICAL` also joins `TITLE_NOISE_SUFFIXES` so the marker is stripped from the **search query** —
  without that, `Azu Tiwaline & Cinna Peyghamy - Canopée Imaginaire (Live At Draaimolen 2023)` returns
  **0 Tidal results**; with it the exact recording is the first hit, matched through Tidal's `version` field.
  This one part is not opt-in — it cleans the query for every caller — but stripping a venue-and-date clause
  can only widen a search, and the 23 last.fm tests show zero delta.

**It is opt-in and off by default**, so `update_daily_blend` is untouched. Verified: the 23 last.fm tests
show the same 2 pre-existing failures before and after, delta zero.

**Measured on a 200-candidate offline replay** that reproduces `__best_match` exactly (200/200 against the
live capture): winners go **151 → 143**. The check runs *inside* `__best_match`, not after it, which is worth
5 of those: for `Nacho Marco - Midnight Blue` the matcher was picking the Satoshi Tomiie Remix while plain
*Midnight Blue* sat in the same result set. The remaining 8 losses are cases where Tidal genuinely lacks the
version the DJ played — a miss, which is the intended outcome.

### 5. Candidate ordering — the weighted lottery

Because the loop stops at 100 matches it consumes only ~6% of the pool, so **the ordering is the selection.**
Every candidate gets a lottery weight from the mix it came from, and the whole pool is drawn without
replacement into one weighted random permutation.

**Weight per mix** — hotness leads because that is what the user's URL asked for, recency is a secondary tilt,
and an Ambient/IDM tag is a harsh discount that pushes the playlist toward rhythmic material:

```python
def mix_weight(rank: int, mix_count: int, age_days: int, categories: Set[str]) -> float:
    hotness = HOTTEST_MIX_WEIGHT ** (1 - rank / mix_count)
    recency = RECENCY_HALF_LIFE_DAYS / (RECENCY_HALF_LIFE_DAYS + max(age_days, 0))
    penalty = DISCOURAGED_STYLE_PENALTY ** len(DISCOURAGED_STYLES & categories)
    return hotness * recency * penalty
```

`rank` is the mix's position in the `hotness_desc` search result — the API exposes hotness only as an
ordering, never a score, so rank is all there is. `HOTTEST_MIX_WEIGHT = 5.0` makes the hottest mix's tracks 5x
as likely as the coldest; `RECENCY_HALF_LIFE_DAYS = 180.0` halves a mix's weight every six months.

**`age_days` is clamped at zero**, and it has to be. A bare-year or fuzzy-month title (`2026 - ...`,
`2026-0X - ...` — the pages the bare year token exists to reach) defaults to mid-year, which is in the
*future* for the first half of that year. Unclamped, `RECENCY_HALF_LIFE_DAYS + age_days` goes negative in
early January (inverting the lottery so that mix leads every draw), hits **exactly zero on 16 January**
(`ZeroDivisionError` out of `weigh_candidates`, before any guard), and stays a 1.3-11x unearned multiplier
until mid-year. `max(age_days, 0)` makes an undated mix weigh exactly as much as a same-day one, never more.

**Style tags cost no extra requests** — they are the `[[Category:...]]` lines already in the wikitext fetched
for the tracklists, read by `categories_of`. That returns *all* categories (year, artist, show, style); only
the two names in `DISCOURAGED_STYLES` are ever tested, so no style-vs-other-category classification is needed.

**A penalty, not a blacklist**, for `Ambient` / `IDM`: `DISCOURAGED_STYLE_PENALTY = 0.1` per matching tag, so
one tag is a 10x cut and both is a **100x** cut. Harshest-for-both falls out of the exponent with no special
case. Measured over the 122-mix corpus, 29 of which carry `Ambient` and 5 `IDM`:

| | Ambient/IDM tracks per 100 |
|---|---|
| no penalty | **18.25** (worst 28) |
| **penalty 0.1 (chosen)** | **2.18** (worst 8) |
| blacklist | 0 |

The tag describes the **mix, not the track**: a dub techno set with one beatless interlude is tagged exactly
like a genuinely ambient one, so blacklisting throws away that mix's rhythmic tracks on a noisy mix-level
signal. The penalty removes ~88% of the effect and degrades gracefully if the corpus shifts. Switching to a
blacklist is a one-line change and the pool has room for it.

**Weights sum across mixes.** A track played in three of the 122 mixes collects three contributions, so
cross-mix repetition — a genuine scene-favourite signal — falls out for free instead of needing its own tier.
Measured: such tracks are 3.0% of the pool but 5.6% of the selection, a ~2x enrichment at zero cost.

**The draw — `weighted_draw`** is one line, and it is the Efraimidis–Spirakis exponential race:

```python
def weighted_draw(weights: Dict[MixTrack, float], seed: int) -> List[MixTrack]:
    random = Random(seed)
    return sorted(weights, key=lambda track: -log(random.random()) / weights[track])
```

Assigning each item `-log(U) / w` and sorting ascending yields a weighted permutation without replacement in
one `O(n log n)` pass. **Verified empirically**: weights 1/2/7 produced a first-place distribution of
0.098 / 0.200 / 0.702 over 40,000 draws against the exact 0.10 / 0.20 / 0.70. This is the whole reason a
lottery costs nothing here — the lazy resolve loop already wants an *ordering*, and the race produces one
directly, so no draw-and-remove loop is needed. `seed = date.today().toordinal()` keeps freshness stateless.

**Deliberately no mix-length normalisation.** Weight attaches to the track, so a 59-track mix contributes 59
tickets and a 5-track mix contributes 5. That is the literal reading of "tracks from hotter mixes are more
likely", and it is the strongest on target. Measured alternatives, same weights, 500 simulated days:

| Per-track weight | Median hotness rank | Median age | Tracks from one mix (mean / p95 / worst) |
|---|---|---|---|
| **`mix_weight` (chosen)** | **26** | **113 d** | **8.3 / 12 / 17** |
| `mix_weight / sqrt(size)` | 26 | 118 d | 6.1 / 9 / 16 |
| `mix_weight / size` | 29 | 132 d | 5.0 / 7 / 9 |

If a run ever bunches harder than taste allows, dividing by `sqrt(len(tracklist.tracks))` is a one-token change
that halves the concentration for almost no loss of targeting.

### 6. Resolution — `find_track` / `find_tracks_on_tidal`

Walk the candidates; skip on either cap **before** spending a lookup; resolve; dedupe on `str(track.id)`.

```python
HOTTEST_MIX_WEIGHT = 5.0
RECENCY_HALF_LIFE_DAYS = 180.0
LOOKUP_BUDGET = 400
MATCH_DEADLINE_SECONDS = 420
MINIMUM_CANDIDATES = 400
CONSECUTIVE_MISS_LIMIT = 40
```

- **No caps at all.** The resolve loop just walks the drawn order; there is no per-artist or per-mix
  bookkeeping left in it. An earlier draft justified an artist cap with "one mix is 23 tracks of the DJ's own
  productions, uncapped it would take a quarter of the playlist" — **the premise is true and the conclusion is
  false.** Artist-dominated mixes are real (`moosdohmen - Stookcast 259` is 15/15, `dESUS, The Open Circle` is
  11/11, `Ruben Ganev - Reclaim Your City 678` is 23/49), but that reasoning belongs to the round-robin design
  the lottery replaced. Under the lottery, `moosdohmen` holds 37.8 of 3266.7 total weight — 1.2%, or ~1.5
  tracks expected in a 130-candidate walk. Stress-tested at the `MINIMUM_SEARCH_HITS = 40` floor (797-track
  pool) and again with the Tidal hit rate halved to 40%: worst case stayed at 6 tracks by one artist, p99 of 5,
  and **no run ever came up short of 100**.
- **Dedupe on `str(track.id)`, never a `Set[Track]`.** Verified: `tidalapi.media.Track` declares no `__eq__`
  and no `__hash__`, so a set of them dedupes by object identity, and `add()`'s server-side `onDupes: SKIP`
  would then silently return a short playlist.
- **Catch `ObjectNotFound`, plus `HTTPError` only when the status is 404.** Verified: `TooManyRequests` and
  `AuthenticationError` both subclass `TidalAPIError`, so catching the base would turn a revoked token into
  400 silent misses. `Tidal.__get_album` can raise `ObjectNotFound` on one bad candidate and would otherwise
  kill the run.
- **`CONSECUTIVE_MISS_LIMIT = 40`** is the exception-type-independent backstop: at the measured 76.7% hit rate
  the odds of 40 real consecutive misses are astronomically small, so 40 in a row means Tidal is broken.
- **Budget *and* deadline.** `LOOKUP_BUDGET` bounds a count (400 × 0.87 s ≈ 348 s); `MATCH_DEADLINE_SECONDS`
  checked with `monotonic()` at the top of each iteration bounds wall clock. Both are needed.
- tqdm progress in the repo's existing style — `progress.write` with `\033[92m✓` / `\033[91m✗`. A ✗ means the
  lookup genuinely found nothing; a track already in `track_ids` is skipped silently and does **not** count
  toward `CONSECUTIVE_MISS_LIMIT`, because a duplicate proves Tidal is answering.
- `find_track` swallows `ObjectNotFound` and 404-flavoured `HTTPError` and re-raises everything else.
  Without it a single dead album id anywhere in the walk aborts the run before the write —
  `Tidal.__get_album` is called for every title-and-artist-matching search result.

**Measured live today** against the real candidate ordering, using the repo's own `Tidal`: **46 hits in 60
lookups = 76.7%, 0.87 s per lookup**, projecting **~130 lookups and ~113 s** to fill 100. Sample hits:
`Zonal - Wrecked`, `Skee Mask - Session Add`, `Yagya - Sleepygirl 1`,
`Ryan Sadorus Feat. Simon Black - Hot In The D (Delano Smith Remix)`.

### 7. Write — `main`

```python
@inject
def main(environment: Environment, tidal: Tidal, mixes_db: MixesDb) -> None:
    playlist_id = environment.require('DUB_TECHNO_PLAYLIST_ID')
    playlist_size = int(environment.require('DUB_TECHNO_SIZE'))
    today = date.today()
    tracklists = mixes_db.get_tracklists(today)
    weights = weigh_candidates(tracklists, today)
    print(f'dub-techno mixesdb: {len(tracklists)} tracklists, {len(weights)} candidates')
    if len(weights) < MINIMUM_CANDIDATES:
        raise RuntimeError(f'only {len(weights)} candidates from {len(tracklists)} tracklists')
    track_ids = find_tracks_on_tidal(tidal, weighted_draw(weights, today.toordinal()), playlist_size)
    if len(track_ids) < playlist_size // 2:
        raise RuntimeError(f'only {len(track_ids)} tracks matched; leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
```

Both `environment.require` calls are **first**, so a missing or typo'd playlist id fails in milliseconds
rather than after 4 MixesDB requests and 400 Tidal lookups.

Three floors, each catching a different upstream failure:

| Floor | Catches |
|---|---|
| `totalhits < 40` (in `MixesDb`) | Renamed or typo'd keyword, a stale date window, a MixesDB reindex. Silent-zero is this API's *default* failure mode. |
| `len(weights) < 400` | Tracklist markup drift, all wikitext batches failing. Today's value is 2085. |
| `not track_ids or len(track_ids) < playlist_size // 2` | Tidal degradation, a deadline hit, an auth failure the breaker missed. The explicit `not track_ids` is load-bearing: at `DUB_TECHNO_SIZE` of 0 or 1 the `// 2` floor is `< 0` and never fires. **Covers the empty-list case** that would otherwise crash inside `add()` after `clear()` has already wiped the playlist. Relative to the configured size, so lowering `DUB_TECHNO_SIZE` does not make the guard unconditional. |

The two `print` lines are prefixed `dub-techno mixesdb:` / `dub-techno tidal:` for CloudWatch Logs Insights.
`len(tracklists)` is the markup-drift canary: it is 117 of 122 today, and a sustained drop means the parser
needs attention.

---

## File-by-file change list

| File | Change |
|---|---|
| `src/mixes_db.py` | **New, ~150 lines.** Constants, `MixTrack` (with `key()` + `__hash__`/`__eq__` on the normalised pair, mirroring `LastFmTrack`'s idiom) and `Tracklist` dataclasses, `date_window`, `search_query`, `searchable`, `recorded_on`, `tracklist_lines`, `parse_line`, `parse_tracklist`, and `@singleton class MixesDb` with `get_tracklists(today: date) -> List[Tracklist]`. Imports `requests` with the repo's `# type: ignore[import-untyped]` convention. |
| `src/update_dub_techno.py` | **New, ~110 lines.** Module-top `# pylint: disable=duplicate-code`, constants, `mix_weight`, `weigh_candidates`, `weighted_draw`, `find_track`, `find_tracks_on_tidal`, `@inject main`, `lambda_handler`, `__main__` timing block — same shape as `update_daily_blend.py`. |
| `tests/test_mixes_db.py` | **New.** Pure, offline parser and query tests. |
| `tests/fixtures/mixes_db/*.txt` | **New.** Three real mix pages: one `#`-list, one `<list>`, one that uses both. No `__init__.py`. |
| `aws/main.py` | Second `DockerImageFunction` + `secret.grant_read` + `Rule`. No new imports. |
| `justfile` | `dub-techno` recipe. |
| `README.md` | Two-playlist intro, the two new env vars, a note that the playlist must be created by hand, `just dub-techno`. |
| `CLAUDE.md` | Overview names both lambdas; a short "Data sources" section recording the API facts so no future session re-derives them. |
| `.env` | `DUB_TECHNO_PLAYLIST_ID`, `DUB_TECHNO_SIZE` for local runs. |

**Unchanged, deliberately:** `src/tidal.py`, `src/last_fm.py`, `src/update_daily_blend.py`, `src/environment.py`,
`.pylintrc`, `mypy.ini`, `Dockerfile` (`COPY src/` already picks up new modules), `.dockerignore` (already
excludes `tests`, so fixtures never enter the image), `.github/workflows/check.yml`, `pyproject.toml`,
`poetry.lock`.

Both new modules were written out and run through the repo's real gates for this plan:
`pylint src tests aws` → **10.00/10**, `mypy src tests aws` → **Success: no issues found in 13 source files**.

---

## Implementation checklist

1. Confirm `git status` is clean apart from the concurrent justfile/CI work — no implementation files from
   earlier sessions in `src/` or `tests/`.
2. Write `src/mixes_db.py`, pure functions first (`date_window`, `search_query`, `searchable`, `recorded_on`,
   `tracklist_lines`, `parse_line`, `parse_tracklist`), then the `MixesDb` client. `MixTrack.key()` must be
   **public** — pylint's `protected-access` fires on `other.__key()` inside `__eq__`.
3. Extract the three fixtures. Any three real pages work; pick one `#`-list page, one `<list>` page, and one
   of the five that use both. `MixesDb().get_tracklists(date.today())` from a throwaway script prints them, or
   fetch them with the two API calls in **How it works** §1 and §3.
4. Write `tests/test_mixes_db.py`. `just test` and `just types` green on the new file.
5. Sanity-check the parser against the live corpus once from a scratch script (not committed): expect ~117
   tracklists and ~2085 unique candidates.
6. Write `src/update_dub_techno.py`: `mix_weight`, `weigh_candidates`, `weighted_draw`, then the resolve loop.
   Keep the module-top `# pylint: disable=duplicate-code`, and keep `find_tracks_on_tidal` separate from
   `main` — a monolithic `main` trips `R0914 too-many-locals` (max 15).
7. Replay the lottery offline before spending any Tidal calls: build `weigh_candidates` over the live corpus
   and simulate a few hundred seeds at a 0.767 hit rate. Reference figures from 2000 simulated days:

   | Measure | Expected |
   |---|---|
   | source-mix hotness rank | median **26** (pool baseline 61) |
   | track age | median **118 d** (pool baseline 202 d) |
   | distinct artists / 100 | mean **95.4**, p5 92, min 88 |
   | tracks from one mix | mean **8.2**, p95 12, worst 18 |
   | tracks by one artist | mean **2.41**, p99 4, worst 7 |
   | lookups to fill 100 | mean **131**, p95 141, worst 155 |
   | day-over-day turnover | **93%** |

   A median rank near 61 means the weights are not being applied at all.
8. Create the playlist by hand in Tidal. Put its UUID in `.env` as `DUB_TECHNO_PLAYLIST_ID`, add
   `DUB_TECHNO_SIZE=100`.
9. Add the `justfile` recipe and run `just dub-techno` end to end against the real playlist. Expect ~130
   lookups, ~2 minutes, 100 tracks.
10. Add the CDK function, `grant_read` and `Rule` to `aws/main.py` with the real UUID. `just synth`.
11. Update `README.md` and `CLAUDE.md`.
12. `just check`. **`just test` is already red at HEAD** (see Risks) — confirm the new tests pass and that no
    *new* failure appears: `poetry run python -m unittest tests.test_mixes_db`.
13. `just deploy`. Invoke once by hand and read the two `dub-techno` summary lines in CloudWatch before
    trusting the schedule.

---

## Config

Two new environment variables. Everything else that defines the feature is a module constant — knobs that
change what the playlist *is* belong in a commit, not in console-editable function config, and every extra
`Environment.require` is another cold-start `KeyError`.

| Name | Value | Set in |
|---|---|---|
| `SECRET_ARN` | `secret.secret_arn` | `aws/main.py` (already the pattern) |
| `DUB_TECHNO_PLAYLIST_ID` | the UUID from the playlist's Tidal web URL | `aws/main.py` **and** `.env` |
| `DUB_TECHNO_SIZE` | `100` | `aws/main.py` **and** `.env` |

`TIDAL_REFRESH_TOKEN` is already supplied by the shared Secrets Manager secret; `grant_read` is per-function.

Module constants: `API_URL`, `USER_AGENT`, `REQUEST_TIMEOUT`, `CRAWL_DELAY_SECONDS`, `STYLE`,
`TITLES_PER_REQUEST`, `MINIMUM_SEARCH_HITS`, `MINIMUM_TITLE_LENGTH` in `src/mixes_db.py`;
`HOTTEST_MIX_WEIGHT`, `RECENCY_HALF_LIFE_DAYS`, `DISCOURAGED_STYLES`,
`DISCOURAGED_STYLE_PENALTY`, `LOOKUP_BUDGET`,
`MATCH_DEADLINE_SECONDS`, `MINIMUM_CANDIDATES`, `CONSECUTIVE_MISS_LIMIT` in `src/update_dub_techno.py`.

The style string contains a `"` and would be awkward and error-prone in a CDK environment block; changing it
changes what the playlist is.

---

## Testing

Everything new is pure, offline and deterministic. CI has no Tidal credentials, so **no new test may touch the
network.** All HTTP lives inside `MixesDb`; everything worth testing is a string → data function, so no
`responses` / `requests-mock` dependency is needed.

**Two type traps, both reproduced against this repo's config:**

- `mypy.ini` sets `check_untyped_defs = True` **globally**, so `tests/` is type-checked. Asserting on
  `parse_line(...).title` fails with `error: Item "None" of "MixTrack | None" has no attribute "title"
  [union-attr]`, and `assertIsNotNone` does **not** narrow. Test through `parse_tracklist`, which returns a
  `List[MixTrack]`, via a small helper that wraps lines in a synthetic section.
- `just test` runs `unittest discover -p '*.py'`, which **imports every `.py` under `tests/`**. Fixtures must
  therefore be `.txt` data files, never Python modules. Verified: `pylint tests` ignores non-`.py` files and
  the fixtures directory needs no `__init__.py`.

| Test | Guards |
|---|---|
| `test_parses_numbered_list_format` | Format A: `# [007] Oreste - Golden String [Indefinite Pitch]` |
| `test_parses_list_tag_format` | Format B: bare lines inside `<list>…</list>` |
| `test_parses_page_using_both_formats` | The 5 mixed pages — per-line, not per-page, detection |
| `test_strips_leading_timestamps` | `[000]`, `[??]`, `[0??]`, `[08?]`, `[56]`, `[00:43:58]`, `[0:38:25]` |
| `test_strips_trailing_record_label` | `[Insectorama]`, `[M]` |
| `test_splits_on_first_dash_after_stripping_label` | `Ruben Ganev - Condition [mould.audio - mldcs025]` — the ordering claim |
| `test_keeps_remix_parenthetical` | `Polygonia - Dreaming Trees (Forest Drive West Remix)` **survives**. Write this one first; stripping is the instinct most likely to be got wrong |
| `test_keeps_credited_artist_string_intact` | `Batu & Donato Dozzy` → `'Batu & Donato Dozzy'`. There is deliberately **no** `test_splits_multiple_artists` — the parser is designed not to split, and that test would fail against its own spec |
| `test_unwraps_bracketed_artist` | `[Moosdohmen] - Paddy Dub` |
| `test_strips_italic_markup` | Partial-line `''…''` |
| `test_drops_filler_and_dashless_and_unknown_lines` | `# Intro`, `...`, `[004] ?`, `? - Margin`, `Diego - ?` |
| `test_drops_short_titles` | `Retouched - F` never becomes a candidate |
| `test_ignores_content_outside_the_tracklist_section` | `[[Category:` and next-heading boundary |
| `test_returns_nothing_without_a_tracklist_heading` | Empty list, not a crash |
| `test_parses_fixture_corpus` | Floor assertion per fixture file — catches a regex edit that silently kills one whole format |
| `test_date_window` | `date(2026, 9, 3)` → `'2026,2025-10,2025-11,2025-12'` |
| `test_date_window_in_january` | `date(2027, 1, 2)` → 12 tokens, `'2027,2026-02,…,2026-12'` — the ≥12-month property. Never call `date.today()` in a test |
| `test_search_query` | The full `style:"Dub Techno" -tracklist:none hasplayer date:…` string |

Selection logic is worth four cheap offline tests too, since it decides what the playlist sounds like and no
gate would otherwise catch a regression. All are deterministic — seed `Random` explicitly, never call
`date.today()`:

| Test | Guards |
|---|---|
| `test_hotter_mixes_weigh_more` | `mix_weight(0, 100, 0) > mix_weight(99, 100, 0)`, and the ratio is `HOTTEST_MIX_WEIGHT` |
| `test_older_mixes_weigh_less` | Equal rank, `age_days=0` vs `=RECENCY_HALF_LIFE_DAYS` → exactly half |
| `test_weights_sum_across_mixes` | A track in two tracklists outweighs the same track in one |
| `test_weighted_draw_favours_heavier_tracks` | Over many seeds, the heavy track leads far more often than the light one — the property, not a fixed ordering |
| `test_weighted_draw_returns_every_candidate_once` | It is a permutation: no drops, no duplicates, empty pool → empty list |

---

## Deployment

Append inside `TidalAutomation.__init__`, after the existing `Rule`. No new imports.

```python
        update_dub_techno = DockerImageFunction(
            self,
            'UpdateDubTechno',
            memory_size=256,
            code=DockerImageCode.from_image_asset(
                directory=getcwd(),
                platform=Platform.LINUX_ARM64,
                cmd=['src.update_dub_techno.lambda_handler']
            ),
            architecture=Architecture.ARM_64,
            environment={
                'SECRET_ARN': secret.secret_arn,
                'DUB_TECHNO_PLAYLIST_ID': '<uuid of a playlist created by hand in Tidal>',
                'DUB_TECHNO_SIZE': '100',
            },
            reserved_concurrent_executions=1,
            retry_attempts=0,
            timeout=Duration.minutes(15)
        )
        secret.grant_read(update_dub_techno)

        Rule(
            self,
            'UpdateDubTechnoSchedule',
            schedule=Schedule.cron(hour='10', minute='15'),
            targets=[LambdaFunction(update_dub_techno)]
        )
```

- **The module name and the `cmd` string must agree.** Verified: `cdk synth` does **not** validate the handler
  path — a bogus one synths cleanly and dies at cold start with `Runtime.ImportModuleError`.
  `src/update_dub_techno.py` ↔ `src.update_dub_techno.lambda_handler`.
- **Every schedule is staggered at 15-minute intervals from 10:00 UTC.** The daily blend moves to 10:00 and
  Dub Techno takes 10:15; a third lambda would take 10:30. 10:00 UTC is the hour that makes **04:00 the
  earliest a job ever starts**: Chicago is UTC-6 in winter (04:00 CST) and UTC-5 in summer (05:00 CDT), so the
  jobs run an hour later for the half of the year DST is in effect. Verified with `zoneinfo`. Note the
  trade-off the 15-minute spacing accepts: both functions have a 15-minute timeout, so a worst-case daily
  blend run ends exactly as Dub Techno starts. `Tidal`'s 2 req/s limiter is per-process, so a genuine overlap
  would briefly drive 4 req/s at one account and trigger the backoff. Typical runs are 2-4 minutes, so this
  is a tail case, not the norm.
- **`reserved_concurrent_executions=1`, `retry_attempts=0`.** EventBridge is at-least-once and async Lambda
  invocations retry **twice by default** — without these, a guard that raises fires three full runs, making 12
  MixesDB requests on exactly the day MixesDB is misbehaving. Verified both synth correctly
  (`MaximumRetryAttempts: 0` on an `AWS::Lambda::EventInvokeConfig`).
- **`memory_size=256`.** The daily blend runs at 128 with the same import set; this one adds `re` and
  `requests` plus ~1 MB of wikitext. 256 doubles the CPU slice for the cold-start import and the regex pass.
  The run is ~90% sleep, so the difference is fractions of a cent per month.
- **Zero extra image build.** Verified by synth: both functions reference **one** docker image asset and differ
  only by `ImageConfig.Command`.

Add to `justfile`:

```make
dub-techno:
    {{ python }} -m src.update_dub_techno
```

---

## Risks and open questions

**The date window is a sawtooth, and the December end of it is the narrowest point.** `date_window` always
spans ≥12 calendar months, but the size of the reachable corpus swings with the month. Measured live today:
September's window → 122 hits, June's → 179, January's → 263, and December's collapses to the bare token
`date:2026` → 90. Those are all healthy today; the guard that matters is `MINIMUM_SEARCH_HITS = 40`, below
which the diversity caps make 100 tracks unreachable and the run raises instead of short-filling.

**Tidal match rate is measured at 76.7%, not assumed.** 46 hits in 60 live lookups on the real candidate
ordering, 0.87 s per lookup, projecting ~130 lookups for 100 tracks. `LOOKUP_BUDGET = 400` covers a hit rate
down to 25%, and `find_tracks_on_tidal` returns short rather than failing if the pool degrades further — the
write floor then decides whether that is publishable. The rate could drift; nothing about it is guaranteed.

**A `TooManyRequests` chain can still blow the 900 s ceiling, and this plan does not fix it.**
`Tidal.__call_api` retries 10 times sleeping up to 60 s each: **302 s** with no `Retry-After`, **549 s** with
`Retry-After: 60`, for a *single* call. Budget: ~25 s of MixesDB and startup + 420 s of matching leaves ~455 s
for the write, which absorbs the first case but not the second. If a hard kill lands between
`set_playlist_tracks`'s removal and its add, the playlist is short until the next day's run repairs it.
The real fix is a deadline inside `__call_api`, deliberately out of scope — see below.

**`tidalapi` sets no HTTP timeout anywhere** (verified: zero occurrences of `timeout` in `request.py`,
`session.py` and `playlist.py`; `request.py` calls `request_session.request(...)` bare). A hung socket burns
the full 15 minutes. Benign — no write happens — but silent, visible only as CloudWatch duration.

**A bodied 429 or 5xx escapes `Tidal.__call_api` as a raw `requests.HTTPError`.** Verified:
`tidalapi.exceptions.http_error_to_tidal_error` converts 404/429 **only when `response.content` is empty**;
otherwise it returns `None` and `request.py` re-raises the bare `HTTPError`, which `__call_api` does not catch.
`find_track` deliberately swallows only 404-flavoured `HTTPError` and re-raises the rest, so this kills the
run *before* the write — the safe direction, but it is a real limitation of the shared client.

**No alarm exists.** A raised guard increments the Lambda `Errors` metric, but nothing in this repo watches it,
so every failure mode above manifests as a playlist that quietly stops changing. A single CloudWatch `Alarm` on
the function's `Errors` metric in `aws/main.py` would convert silent staleness into a signal; it is not in this
plan because the daily blend has none either and adding alarms is a repo-wide decision.

**Artist repetition is now unbounded in principle.** Nothing structural prevents a playlist with six tracks by
one artist; only the measured shape of the pool does. That shape is a property of *this* search — 1416 artists
over 2085 tracks — and a future window that is far more concentrated (a narrower style, a much smaller corpus,
or a single artist dominating the hot mixes) would bunch harder than anything simulated here. The stress tests
covered the corpus shrinking (40 mixes) and Tidal degrading (40% hit rate), not the corpus becoming
*concentrated*. If a run ever comes back monotonous, the fix is one token — see Deliberately out of scope.

**The lottery constants are taste knobs, and only taste can tune them.** `HOTTEST_MIX_WEIGHT = 5.0` and
`RECENCY_HALF_LIFE_DAYS = 180.0` were chosen from measured distributions, not from listening: they move the
median source mix from rank 61 to 26 and the median track age from 202 to 118 days while leaving ~95 distinct
artists per 100 tracks. Raising either narrows the playlist toward the hot/new head (x8 + 120 d gives median
rank 24, age 109 d, but 5.8 mean tracks per mix); lowering both toward `1.0` and `∞` degenerates to a uniform
shuffle. Nothing here can tell you which sounds better — expect one round of adjustment after listening.

**Hotness rank is ordinal, so the weight curve is imposed, not measured.** The API exposes hotness only as a
sort order; there is no score to calibrate against. `HOTTEST_MIX_WEIGHT ** (1 - rank / mix_count)` asserts a
geometric falloff across the ranking that MixesDB's own notion of hotness may not match. It is a defensible
default, not a fitted curve.

**Recency partly double-counts hotness.** A mix is hot in part *because* it is recent, so the two factors are
correlated. Measured separately at the same target: hotness ×5 alone gives median rank 37 / age 171 d, recency
alone gives 49 / 160 d, and together 26 / 113 d — they compose further than either alone, so the redundancy is
real but not total.

**`style:` filters the *mix*, not the track.** DJ sets contain intros, ambient interludes and cross-genre
selections, so the playlist is honestly "100 tracks played in Dub Techno mixes", not "100 Dub Techno tracks".
Spot checks of the resolved output include ambient and electro alongside the dub techno core. This is inherent
to the source and is not fixable without per-track genre data.

**`just check` is red at HEAD, before any of this lands.** With credentials present, `just test` fails
`test_matt_and_kim` ('matt and kim' not found in {'matt', 'kim'}) and `test_not_various_artists_album`
('Save Me, San Francisco' not found in 'Hey, Soul Sister') — 2 of 25, both live-network assertions about Tidal
metadata that has drifted. In CI, where there is no `.env`, `LastFmMatching.setUpClass` raises
`KeyError: missing environment variable: TIDAL_REFRESH_TOKEN` and the whole class errors. **Fixing that is out
of scope**, and a `@skipUnless` guard would only green CI while leaving the real failures hidden. Verify the
new tests in isolation.

**`robots.txt` has `Disallow: /*?action=`**, which pattern-matches `api.php?action=query`. robots.txt governs
crawlers and MediaWiki's `api.php` is conventionally outside its scope, and no MixesDB page states API terms
either way — `MixesDB:API` is a 404. Four requests a day at `Crawl-delay: 4` with a descriptive User-Agent is
the polite reading, but this is a judgement call, not granted permission. **Worth the user's explicit sign-off.**

**`mixesdbsearchjsonld` is not used, and `list=search` + `prop=revisions` are stock MediaWiki** — the more
stable path. The fragile parts are the custom keywords (`style:`, `date:`, `hasplayer`, `tracklist:`); the
`totalhits` floor is what catches them being renamed.

**Corpus growth past `srlimit` 500** would silently truncate, since no `sroffset` continuation is implemented.
Today: 122 Dub Techno hits, no `continue`; Techno's 2785 hits are truncated to 500 by `srlimit=max`, which is
the one place the corpus is silently cut — by the API, not by us. Widening the window is
the change that would trip it — `date:2026,2025` already returns 279.

**`set_playlist_tracks` is remove-then-add and nothing can make it atomic.** The floors prevent *starting* a
bad write; they cannot cover a crash between the two calls. The differential write makes this strictly less
damaging than the old clear-then-add: a crash now loses only the departing tracks, not the whole playlist.

**`UserPlaylist.add(..., limit=len(track_ids))` sits exactly on tidalapi's documented 100-item ceiling** and
sends all ids in one POST with no chunking. Do not raise `DUB_TECHNO_SIZE` above 100 without chunking
`Tidal.set_playlist_tracks` first. `onArtifactNotFound: SKIP` also means region-unavailable tracks are dropped
server-side, so a run can legitimately land a few short of 100.

**Hotness may drift day to day.** Repeated calls minutes apart returned identical ordering; day-over-day drift
is unverified. The day-seeded shuffle means the playlist is expected to change daily regardless.

**Cloudflare fronts MixesDB** and its throttling behaviour under load was not tested. 429/503 are possible.

**Accepted parser losses, ~1.4% of accepted lines**, all measured, none worth code: 6 genuinely dash-less
lines, 3 with unbalanced source brackets, 2 pages with two tracks concatenated onto one line, 7 with
` X ` / ` + ` / ` ft. ` artist separators, and the 20 short titles deliberately dropped. Against a
2085-candidate pool for a 100-track target, none of these are reachable problems.

**Remix-version fidelity is best-effort.** `Tidal.__titles_match` is bidirectional, so a search for
`X (Kessell Remix)` can land on the original and vice versa. Right track family, sometimes wrong version —
acceptable for a genre playlist, and stripping the parenthetical would be strictly worse.

**All figures are a 2026-09-03 snapshot**: 122 hits, 2719 raw lines, 2152 accepted, 2085 unique candidates from
117 pages, 76.7% Tidal hit rate. The floors are what turn drift into a loud failure instead of a bad playlist.

---

## Deliberately out of scope

Each of these came out of the research or a review and does not earn its place here.

* **`action=mixesdbsearchjsonld`.** Loses 19% of the corpus and ~99% of remix credits; undocumented and
  versionless. The wikitext parser is the primary path, not a fallback.
* **Renaming `LastFmTrack` → `TrackQuery`.** 13 sites in the matcher, a public signature change, and an
  inverted import direction, for zero behaviour change. A separate mechanical commit if wanted.
* **Any change to `src/tidal.py`** — a run deadline inside `__call_api`, an `HTTPError` retry branch, an HTTP
  timeout patch, `get_playlist_track_ids`, paginating `get_playlist_tracks`. All are defensible improvements to
  the shared client the daily blend runs on; none belongs in a commit whose brief is "add a second playlist".
  Named individually in Risks so they are decisions, not omissions.
* **A rotation queue** (evict N, append N). See Key decisions.
* **A cross-mix repeat-count seed tier.** No longer needed as its own concept — summing lottery weights across
  mixes already enriches these tracks ~2× (3.0% of the pool, 5.6% of the selection).
* **A per-label diversity cap.** 708 distinct labels, absent on 38% of lines, and the artist cap already
  suppresses label clustering.
* **Preserving DJ set sequencing.** Resolution failures punch adjacency out anyway; measured run lengths in the
  final playlist are almost all 1 even when you try to preserve them. The lottery scatters by construction.
* **A per-mix cap.** Removed at the user's direction; the lottery makes it redundant (worst case 17 of 100).
* **A per-artist cap, and every soft replacement for it.** All four alternatives were simulated over the real
  corpus. Each *raises* diversity above what the lottery does naturally, which is adding a constraint rather
  than removing one — a playlist that may never feature an artist twice is its own artificial rule:

  | Mechanic | Distinct artists / 100 | Max per artist (mean / p99 / worst) | Cost |
  |---|---|---|---|
  | **none (chosen)** | **95.4** | **2.40 / 4 / 7** | — |
  | hard cap 2 (old) | 95.9 | 1.99 / 2 / 2 | a constant, a `Counter`, a branch |
  | `weight / sqrt(artist_count)` | 98.3 | 1.85 / 2 / 3 | one token, keeps the one-pass draw |
  | `weight / artist_count` | 99.3 | 1.51 / 2 / 3 | one token, keeps the one-pass draw |
  | decay 0.25 per pick | 99.7 | 1.24 / 2 / 2 | replaces the sort with a lazy-update heap |

  `weight / sqrt(artist_count)` is the one to reach for if repeats ever grate — it is a one-token static change
  that needs no new machinery. The decay variants buy almost nothing over it and cost the one-line draw.
* **A ` X ` / ` + ` / ` ft. ` artist splitter.** 7 of 2085 pairs, and it measurably *degrades*
  `Tidal.__search_query`, which concatenates every artist variant into one query string.
* **`src/lambda_entrypoint.py` or a `.pylintrc` change for R0801.** The module-scoped pragma is one line, local
  and reversible, and does not blind the linter repo-wide or force a diff in the deployed daily blend.
* **A new dependency.** stdlib `re` plus `requests` covers it. `mwparserfromhell` would build a node tree for
  templates and links these tracklists provably do not contain — 0 wikilinks, 0 templates, 0 tags across all
  2719 track lines.
* **Declaring `requests` in `pyproject.toml`.** It is imported directly by `src/last_fm.py` today and reaches
  the image via `tidalapi` (`poetry.lock` pins 2.32.5 in the `main` group, so `poetry export` already emits
  it). Declaring it is correct hygiene but forces a `poetry lock` regeneration in the same commit — the
  Dockerfile's `poetry export` hard-fails otherwise — plus a cold CI cache. A better standalone commit.
* **Fixing or skipping `tests/test_last_fm_matching.py`.** Already red; named in Risks.
* **A CloudWatch alarm or DLQ.** Named in Risks; a repo-wide decision, not this feature's.
