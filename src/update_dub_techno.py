# pylint: disable=duplicate-code
from collections import Counter, defaultdict
from datetime import date
from math import log
from random import Random
from time import monotonic, time
from typing import Dict, List, Optional, Set

from injector import inject, Injector
from requests.exceptions import HTTPError  # type: ignore[import-untyped]
from tidalapi import Track
from tidalapi.exceptions import ObjectNotFound
from tqdm import tqdm

from src.environment import Environment
from src.last_fm import LastFmTrack
from src.mixes_db import MixesDb, MixTrack, Tracklist
from src.tidal import Tidal

HOTTEST_MIX_WEIGHT = 5.0
RECENCY_HALF_LIFE_DAYS = 180.0
STYLE_PRIORITIES = {'Dub Techno': 4.0, 'Minimal': 2.0, 'Techno': 1.0}
DISCOURAGED_STYLES = frozenset({'Ambient', 'IDM'})
DISCOURAGED_STYLE_PENALTY = 0.1
LOOKUP_BUDGET = 400
MATCH_DEADLINE_SECONDS = 420
MINIMUM_CANDIDATES = 400
CONSECUTIVE_MISS_LIMIT = 40


def style_premiums(tracklists: List[Tracklist]) -> Dict[str, float]:
    tagged = Counter(style for tracklist in tracklists for style in STYLE_PRIORITIES
                     if style in tracklist.categories)
    return {style: priority * len(tracklists) / tagged[style]
            for style, priority in STYLE_PRIORITIES.items() if tagged[style]}


def style_multiplier(categories: Set[str], premiums: Dict[str, float]) -> float:
    premium = sum(premium for style, premium in premiums.items() if style in categories)
    return (premium or 1.0) * DISCOURAGED_STYLE_PENALTY ** len(DISCOURAGED_STYLES & categories)


def mix_weight(rank: int, mix_count: int, age_days: int, categories: Set[str],
               premiums: Dict[str, float]) -> float:
    hotness = HOTTEST_MIX_WEIGHT ** (1 - rank / mix_count)
    recency = RECENCY_HALF_LIFE_DAYS / (RECENCY_HALF_LIFE_DAYS + max(age_days, 0))
    return hotness * recency * style_multiplier(categories, premiums)


def weigh_candidates(tracklists: List[Tracklist], today: date) -> Dict[MixTrack, float]:
    weights: Dict[MixTrack, float] = defaultdict(float)
    premiums = style_premiums(tracklists)
    for rank, tracklist in enumerate(tracklists):
        weight = mix_weight(rank, len(tracklists), (today - tracklist.recorded_on).days,
                            tracklist.categories, premiums)
        for track in tracklist.tracks:
            weights[track] += weight
    return weights


def weighted_draw(weights: Dict[MixTrack, float], seed: int) -> List[MixTrack]:
    random = Random(seed)
    return sorted(weights, key=lambda track: -log(random.random()) / weights[track])


def find_track_id(tidal: Tidal, track: MixTrack) -> Optional[Track]:
    try:
        return tidal.find_equivalent_track(LastFmTrack(title=track.title, artists={track.artist}))
    except ObjectNotFound:
        return None
    except HTTPError as error:
        if error.response is None or error.response.status_code != 404:
            raise
        return None


def find_tracks_on_tidal(tidal: Tidal, candidates: List[MixTrack], playlist_size: int) -> List[str]:
    track_ids: List[str] = []
    deadline = monotonic() + MATCH_DEADLINE_SECONDS
    lookups = consecutive_misses = 0

    with tqdm(total=playlist_size, desc='Building Dub Techno playlist') as progress:
        for candidate in candidates:
            if len(track_ids) >= playlist_size or lookups >= LOOKUP_BUDGET or monotonic() > deadline:
                break
            lookups += 1
            found = find_track_id(tidal, candidate)
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
    print(f'dub-techno tidal: {lookups} lookups, {len(track_ids)} tracks')
    return track_ids


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
    if not track_ids or len(track_ids) < playlist_size // 2:
        raise RuntimeError(f'only {len(track_ids)} tracks matched; leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)


def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    # pylint: disable=unused-argument
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
