import re
from collections import defaultdict
from datetime import date
from math import log, sqrt
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
OUTLIER_FENCE = 2.0
BPM_RESOLUTION = 1.0
OCTAVE = 2.0
HALF_OCTAVE = sqrt(OCTAVE)
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


def fold_to_octave(tempo: float, centre: float) -> float:
    while tempo < centre / HALF_OCTAVE:
        tempo *= OCTAVE
    while tempo > centre * HALF_OCTAVE:
        tempo /= OCTAVE
    return tempo


def centre_of_gravity(tempos: List[float]) -> float:
    centre = median(tempos)
    return median([fold_to_octave(tempo, centre) for tempo in tempos])


def mixable_with(tempo: float, centre: float) -> bool:
    return abs(fold_to_octave(tempo, centre) - centre) <= centre * PITCH_FADER_RANGE


def outlier_fence(tempos: List[float]) -> Tuple[float, float]:
    centre = median(tempos)
    deviation = median([abs(tempo - centre) for tempo in tempos]) or BPM_RESOLUTION
    return centre - OUTLIER_FENCE * deviation, centre + OUTLIER_FENCE * deviation


def focused_selection(folded: List[Tuple[str, float]], playlist_size: int) -> List[str]:
    selected = folded[:playlist_size]
    considered = len(selected)
    while selected:
        low, high = outlier_fence([tempo for _, tempo in selected])
        inliers = [(track_id, tempo) for track_id, tempo in selected if low <= tempo <= high]
        refilled = False
        while len(inliers) < playlist_size and considered < len(folded):
            track_id, tempo = folded[considered]
            considered += 1
            if low <= tempo <= high:
                inliers.append((track_id, tempo))
                refilled = True
        if len(inliers) == len(selected) and not refilled:
            break
        selected = inliers
    return [track_id for track_id, _ in selected]


def mixable_selection(ranked: List[str], tempo_of: Callable[[str], Optional[int]],
                      playlist_size: int) -> List[str]:
    timed = [(track_id, float(tempo)) for track_id in ranked
             if (tempo := tempo_of(track_id)) is not None and tempo > 0]
    if not timed:
        return []
    centre = centre_of_gravity([tempo for _, tempo in timed])
    beatmatchable = [(track_id, fold_to_octave(tempo, centre)) for track_id, tempo in timed
                     if mixable_with(tempo, centre)]
    if not beatmatchable:
        return []
    selected = focused_selection(beatmatchable, playlist_size)
    tempos = sorted(dict(beatmatchable)[track_id] for track_id in selected)
    print(f'tempo: {len(timed)} of {len(ranked)} timed, {len(beatmatchable)} beatmatchable, '
          f'{len(selected)} focused between {tempos[0]:.0f} and {tempos[-1]:.0f} bpm')
    return selected


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
