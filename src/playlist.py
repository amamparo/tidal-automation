import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from math import log
from random import Random
from statistics import median
from typing import Callable, Dict, List, Optional, Tuple

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
PITCH_FADER_RANGE = 0.08
MIXABLE_SPAN = 1.0 + PITCH_FADER_RANGE
TITLE_QUALIFIER = re.compile(r'\s+[(\[].*$|\s+\d{1,3}$')


@dataclass
class TimedTrack:
    track_id: str
    tempo: float


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


def weighted_draw(weights: Dict[MixTrack, float], random_seed: int) -> List[MixTrack]:
    random = Random(random_seed)
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
    seconds_to_seed = SEED_REQUESTS * tidal.seconds_per_request
    return seconds_left - seconds_to_seed >= tidal.seconds_to_set_playlist(playlist_size)


def gather_recommendations(tidal: Tidal, candidates: List[MixTrack], weights: Dict[MixTrack, float],
                           playlist_size: int, seconds_left: Callable[[], float]) -> Dict[str, List[float]]:
    recommended: Dict[str, List[float]] = defaultdict(list)
    seeded = without_radio = 0

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
                without_radio += 1
                continue
            seeded += 1
            for track in radio:
                recommended[str(track.id)].append(weights[candidate])
    print(f'radios: {seeded} seeds, {without_radio} without a radio, {len(recommended)} tracks recommended')
    return recommended


def most_recommended(recommended: Dict[str, List[float]]) -> List[str]:
    def consensus(track_id: str) -> Tuple[int, float, str]:
        seed_weights = recommended[track_id]
        return -len(seed_weights), -sum(seed_weights), track_id

    return sorted(recommended, key=consensus)


def tempo_span(tempos: List[float]) -> float:
    return max(tempos) / min(tempos)


def keeps_the_span(tempo: float, tempos: List[float]) -> bool:
    return tempo_span([*tempos, tempo]) <= MIXABLE_SPAN


def annealed_selection(timed: List[TimedTrack], playlist_size: int) -> List[TimedTrack]:
    selected = timed[:playlist_size]
    considered = len(selected)
    while True:
        tempos = [track.tempo for track in selected]
        if tempos and tempo_span(tempos) > MIXABLE_SPAN:
            centre = median(tempos)
            furthest = max(reversed(selected), key=lambda track: abs(track.tempo - centre))
            selected = [track for track in selected if track is not furthest]
            continue
        if len(selected) >= playlist_size or considered >= len(timed):
            return selected
        candidate = timed[considered]
        considered += 1
        if keeps_the_span(candidate.tempo, tempos):
            selected.append(candidate)


def mixable_selection(ranked: List[str], tempo_of: Callable[[str], Optional[int]],
                      playlist_size: int) -> List[str]:
    timed = [TimedTrack(track_id, float(tempo)) for track_id in ranked
             if (tempo := tempo_of(track_id)) is not None and tempo > 0]
    if not timed:
        return []
    selected = annealed_selection(timed, playlist_size)
    if not selected:
        return []
    tempos = sorted(track.tempo for track in selected)
    print(f'tempo: {len(timed)} of {len(ranked)} timed, {len(selected)} annealed between '
          f'{tempos[0]:.0f} and {tempos[-1]:.0f} bpm, {100 * (tempo_span(tempos) - 1):.1f}% span')
    return [track.track_id for track in selected]


def rebuild(tidal: Tidal, mixes_db: MixesDb, *, query: str, playlist_id: str, playlist_size: int,
            today: date, seconds_left: Callable[[], float]) -> None:
    tracklists = mixes_db.get_tracklists(query)
    weights = weigh_candidates(tracklists, today)
    print(f'mixesdb: {len(tracklists)} tracklists, {len(weights)} candidates')
    if len(weights) < playlist_size:
        raise RuntimeError(
            f'only {len(weights)} candidates from {len(tracklists)} tracklists for {playlist_size} tracks')

    candidates = weighted_draw(weights, today.toordinal())
    recommended = gather_recommendations(tidal, candidates, weights, playlist_size, seconds_left)
    ranked = most_recommended(recommended)
    track_ids = mixable_selection(ranked, tidal.beats_per_minute, playlist_size)
    if len(track_ids) < playlist_size:
        raise RuntimeError(f'only {len(track_ids)} mixable tracks of {len(ranked)} recommended; '
                           'leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
