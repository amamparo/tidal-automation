import re
from collections import defaultdict
from datetime import date
from math import log
from random import Random
from time import monotonic
from typing import Dict, List, Optional, Set

from requests.exceptions import HTTPError  # type: ignore[import-untyped]
from tidalapi import Track
from tidalapi.exceptions import ObjectNotFound
from tqdm import tqdm

from src.last_fm import LastFmTrack
from src.mixes_db import MixesDb, MixTrack, Tracklist, searchable
from src.tidal import Tidal

HOTTEST_MIX_WEIGHT = 5.0
RECENCY_HALF_LIFE_DAYS = 180.0
DISCOURAGED_STYLES = frozenset({'Ambient', 'IDM'})
DISCOURAGED_STYLE_PENALTY = 0.1
LOOKUP_BUDGET = 400
MATCH_DEADLINE_SECONDS = 420
MINIMUM_CANDIDATES = 400
CONSECUTIVE_MISS_LIMIT = 40
TITLE_QUALIFIER = re.compile(r'\s+[(\[].*$|\s+\d{1,3}$')


def mix_weight(rank: int, mix_count: int, age_days: int, categories: Set[str]) -> float:
    hotness = HOTTEST_MIX_WEIGHT ** (1 - rank / mix_count)
    recency = RECENCY_HALF_LIFE_DAYS / (RECENCY_HALF_LIFE_DAYS + max(age_days, 0))
    penalty = DISCOURAGED_STYLE_PENALTY ** len(DISCOURAGED_STYLES & categories)
    return hotness * recency * penalty


def weigh_candidates(tracklists: List[Tracklist], today: date) -> Dict[MixTrack, float]:
    weights: Dict[MixTrack, float] = defaultdict(float)
    for rank, tracklist in enumerate(tracklists):
        weight = mix_weight(rank, len(tracklists), (today - tracklist.recorded_on).days,
                            tracklist.categories)
        for track in tracklist.tracks:
            weights[track] += weight
    return weights


def weighted_draw(weights: Dict[MixTrack, float], seed: int) -> List[MixTrack]:
    random = Random(seed)
    return sorted(weights, key=lambda track: -log(random.random()) / weights[track])


def is_same_recording(mix_title: str, found_name: str) -> bool:
    searched = searchable(mix_title)
    return searchable(found_name) in searched or searchable(TITLE_QUALIFIER.sub('', found_name)) in searched


def find_track(tidal: Tidal, track: MixTrack) -> Optional[Track]:
    searched = LastFmTrack(title=track.title, artists={track.artist})
    try:
        found = tidal.find_equivalent_track(searched, match_version=True)
    except ObjectNotFound:
        return None
    except HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise
        return None
    return found if found and is_same_recording(track.title, found.name or '') else None


def find_tracks_on_tidal(tidal: Tidal, candidates: List[MixTrack], playlist_size: int) -> List[str]:
    track_ids: List[str] = []
    deadline = monotonic() + MATCH_DEADLINE_SECONDS
    lookups = consecutive_misses = 0

    with tqdm(total=playlist_size, desc='Building playlist') as progress:
        for candidate in candidates:
            if len(track_ids) >= playlist_size or lookups >= LOOKUP_BUDGET or monotonic() > deadline:
                break
            lookups += 1
            found = find_track(tidal, candidate)
            if not found:
                consecutive_misses += 1
                if consecutive_misses >= CONSECUTIVE_MISS_LIMIT:
                    raise RuntimeError(f'{consecutive_misses} consecutive lookups found nothing on tidal')
                progress.write(f'\033[91m✗ {candidate.artist} - {candidate.title}\033[0m')
                continue
            consecutive_misses = 0
            track_id = str(found.id)
            if track_id in track_ids:
                continue
            track_ids.append(track_id)
            progress.write(f'\033[92m✓ {found.name} - {candidate.artist}\033[0m')
            progress.update(1)
    print(f'tidal: {lookups} lookups, {len(track_ids)} tracks')
    return track_ids


def rebuild(tidal: Tidal, mixes_db: MixesDb, *, query: str, playlist_id: str,
            playlist_size: int, today: date) -> None:
    tracklists = mixes_db.get_tracklists(query)
    weights = weigh_candidates(tracklists, today)
    print(f'mixesdb: {len(tracklists)} tracklists, {len(weights)} candidates')
    if len(weights) < MINIMUM_CANDIDATES:
        raise RuntimeError(f'only {len(weights)} candidates from {len(tracklists)} tracklists')

    track_ids = find_tracks_on_tidal(tidal, weighted_draw(weights, today.toordinal()), playlist_size)
    if not track_ids or len(track_ids) < playlist_size // 2:
        raise RuntimeError(f'only {len(track_ids)} tracks matched; leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
