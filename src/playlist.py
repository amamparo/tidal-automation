import re
from collections import defaultdict
from datetime import date
from math import log
from random import Random
from typing import Callable, Dict, List, Optional

from requests.exceptions import HTTPError  # type: ignore[import-untyped]
from tidalapi import Track
from tidalapi.exceptions import ObjectNotFound
from tqdm import tqdm

from src.last_fm import LastFmTrack
from src.mixes_db import MixesDb, MixTrack, Tracklist, searchable
from src.tidal import Tidal

HOTTEST_MIX_WEIGHT = 5.0
RECENCY_HALF_LIFE_DAYS = 180.0
SEED_REQUESTS = 2
TITLE_QUALIFIER = re.compile(r'\s+[(\[].*$|\s+\d{1,3}$')


def mix_weight(rank: int, mix_count: int, age_days: int) -> float:
    hotness = HOTTEST_MIX_WEIGHT ** (1 - rank / mix_count)
    recency = RECENCY_HALF_LIFE_DAYS / (RECENCY_HALF_LIFE_DAYS + max(age_days, 0))
    return hotness * recency


def weigh_candidates(tracklists: List[Tracklist], today: date) -> Dict[MixTrack, float]:
    weights: Dict[MixTrack, float] = defaultdict(float)
    for rank, tracklist in enumerate(tracklists):
        weight = mix_weight(rank, len(tracklists), (today - tracklist.recorded_on).days)
        for track in tracklist.tracks:
            weights[track] += weight
    return weights


def weighted_draw(weights: Dict[MixTrack, float], seed: int) -> List[MixTrack]:
    random = Random(seed)
    drawable = {track: weight for track, weight in weights.items() if weight > 0.0}
    return sorted(drawable, key=lambda track: -log(random.random()) / drawable[track])


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


def time_to_seed_again(tidal: Tidal, seconds_left: float, playlist_size: int) -> bool:
    seeding = SEED_REQUESTS * tidal.seconds_per_request
    return seconds_left - seeding >= tidal.seconds_to_set_playlist(playlist_size)


def gather_recommendations(tidal: Tidal, candidates: List[MixTrack], weights: Dict[MixTrack, float],
                           playlist_size: int, seconds_left: Callable[[], float]) -> Dict[str, List[float]]:
    recommended: Dict[str, List[float]] = defaultdict(list)
    seeded = unplayable = 0

    with tqdm(total=len(candidates), desc='Reading radios') as progress:
        for candidate in candidates:
            if not time_to_seed_again(tidal, seconds_left(), playlist_size):
                break
            progress.update(1)
            found = find_track(tidal, candidate)
            if not found:
                continue
            radio = tidal.track_radio(found)
            if not radio:
                unplayable += 1
                continue
            seeded += 1
            for track in radio:
                recommended[str(track.id)].append(weights[candidate])
    print(f'radios: {seeded} seeds, {unplayable} without a radio, {len(recommended)} tracks recommended')
    return recommended


def most_recommended(recommended: Dict[str, List[float]], playlist_size: int) -> List[str]:
    def consensus(track_id: str) -> tuple:
        seeds = recommended[track_id]
        return -len(seeds), -sum(seeds), track_id

    return sorted(recommended, key=consensus)[:playlist_size]


def rebuild(tidal: Tidal, mixes_db: MixesDb, *, query: str, playlist_id: str, playlist_size: int,
            today: date, seconds_left: Callable[[], float]) -> None:
    tracklists = mixes_db.get_tracklists(query)
    weights = weigh_candidates(tracklists, today)
    print(f'mixesdb: {len(tracklists)} tracklists, {len(weights)} candidates')
    if len(weights) < playlist_size:
        raise RuntimeError(
            f'only {len(weights)} candidates from {len(tracklists)} tracklists for {playlist_size} tracks')

    seeds = weighted_draw(weights, today.toordinal())
    recommended = gather_recommendations(tidal, seeds, weights, playlist_size, seconds_left)
    track_ids = most_recommended(recommended, playlist_size)
    if len(track_ids) < playlist_size:
        raise RuntimeError(f'only {len(track_ids)} tracks recommended; leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
