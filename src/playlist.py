import re
from collections import defaultdict
from dataclasses import dataclass
from itertools import zip_longest
from math import isfinite
from statistics import median
from typing import Callable, Dict, List, Optional, Tuple

from requests.exceptions import HTTPError  # type: ignore[import-untyped]
from tidalapi import Track
from tidalapi.exceptions import ObjectNotFound
from tqdm import tqdm

from src.last_fm import LastFmTrack
from src.mixes_db import WIDENING_MONTHS, WINDOW_MONTHS, MixesDb, MixTrack, Tracklist, searchable
from src.tidal import Tidal

SEED_REQUESTS = 2
PITCH_FADER_RANGE = 0.08
MIXABLE_SPAN = 1.0 + PITCH_FADER_RANGE
TITLE_QUALIFIER = re.compile(r'\s+[(\[].*$|\s+\d{1,3}$')


@dataclass
class TimedTrack:
    track_id: str
    tempo: float


def candidates_from(tracklists: List[Tracklist]) -> List[MixTrack]:
    round_robin = zip_longest(*(tracklist.tracks for tracklist in tracklists))
    return list(dict.fromkeys(track for turn in round_robin for track in turn if track))


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


def reachable_candidates(read: int, seconds_spent: float, seconds_spare: float,
                         candidate_count: int) -> int:
    unhurried = not isfinite(seconds_spent) or not isfinite(seconds_spare)
    if read == 0 or seconds_spent <= 0.0 or unhurried:
        return candidate_count
    return min(candidate_count, read + int(seconds_spare * read / seconds_spent))


def gather_recommendations(tidal: Tidal, candidates: List[MixTrack], playlist_size: int,
                           seconds_left: Callable[[], float]) -> Dict[str, float]:
    recommended: Dict[str, float] = defaultdict(float)
    seeded = without_radio = 0
    began_with = seconds_left()

    with tqdm(total=len(candidates), desc='Reading radios') as progress:
        for candidate in candidates:
            remaining = seconds_left()
            if not time_to_seed_again(tidal, remaining, playlist_size):
                break
            progress.update(1)
            progress.total = reachable_candidates(
                progress.n, began_with - remaining,
                remaining - tidal.seconds_to_set_playlist(playlist_size), len(candidates))
            found = find_track(tidal, candidate)
            if not found:
                continue
            radio = tidal.track_radio(found)
            if not radio:
                without_radio += 1
                continue
            seeded += 1
            for position, track in enumerate(radio):
                recommended[str(track.id)] += 1.0 - position / len(radio)
    print(f'radios: {seeded} seeds, {without_radio} without a radio, {len(recommended)} tracks recommended')
    return recommended


def most_recommended(recommended: Dict[str, float]) -> List[str]:
    return sorted(recommended, key=lambda track_id: (-recommended[track_id], track_id))


def tempo_span(tempos: List[float]) -> float:
    return max(tempos) / min(tempos)


def fits_inside_one_pitch_fader(tracks: List[TimedTrack]) -> bool:
    tempos = [track.tempo for track in tracks]
    return not tempos or tempo_span(tempos) <= MIXABLE_SPAN


def without_the_least_recommended_outlier(selected: List[TimedTrack]) -> List[TimedTrack]:
    centre = median(track.tempo for track in selected)
    least_recommended_first = reversed(selected)
    dropped = max(least_recommended_first, key=lambda track: abs(track.tempo - centre))
    return [track for track in selected if track is not dropped]


def annealed_selection(timed: List[TimedTrack], playlist_size: int) -> List[TimedTrack]:
    selected = timed[:playlist_size]
    while not fits_inside_one_pitch_fader(selected):
        selected = without_the_least_recommended_outlier(selected)
    for candidate in timed[playlist_size:]:
        if len(selected) >= playlist_size:
            break
        if fits_inside_one_pitch_fader([*selected, candidate]):
            selected.append(candidate)
    return selected


def mixable_selection(ranked: List[str], tempo_of: Callable[[str], Optional[int]],
                      playlist_size: int) -> List[str]:
    timed = [TimedTrack(track_id, float(tempo)) for track_id in ranked
             if (tempo := tempo_of(track_id)) is not None and tempo > 0]
    selected = annealed_selection(timed, playlist_size)
    if not selected:
        return []
    tempos = sorted(track.tempo for track in selected)
    print(f'tempo: {len(timed)} of {len(ranked)} timed, {len(selected)} annealed between '
          f'{tempos[0]:.0f} and {tempos[-1]:.0f} bpm, {100 * (tempo_span(tempos) - 1):.1f}% span')
    return [track.track_id for track in selected]


def widened_corpus(mixes_db: MixesDb, query_for: Callable[[int], str],
                   playlist_size: int) -> Tuple[List[Tracklist], List[MixTrack]]:
    months = WINDOW_MONTHS
    tracklists = mixes_db.get_tracklists(query_for(months))
    candidates = candidates_from(tracklists)
    while len(candidates) < playlist_size:
        months += WIDENING_MONTHS
        wider = mixes_db.get_tracklists(query_for(months))
        widened = candidates_from(wider)
        if len(widened) <= len(candidates):
            break
        tracklists, candidates = wider, widened
    print(f'mixesdb: {len(tracklists)} tracklists over {months} months, {len(candidates)} candidates')
    return tracklists, candidates


def rebuild(tidal: Tidal, mixes_db: MixesDb, *, query_for: Callable[[int], str], playlist_id: str,
            playlist_size: int, seconds_left: Callable[[], float]) -> None:
    tracklists, candidates = widened_corpus(mixes_db, query_for, playlist_size)
    if len(candidates) < playlist_size:
        raise RuntimeError(
            f'only {len(candidates)} candidates from {len(tracklists)} tracklists for {playlist_size} tracks')

    recommended = gather_recommendations(tidal, candidates, playlist_size, seconds_left)
    ranked = most_recommended(recommended)
    track_ids = mixable_selection(ranked, tidal.beats_per_minute, playlist_size)
    if len(track_ids) < playlist_size:
        raise RuntimeError(f'only {len(track_ids)} mixable tracks of {len(ranked)} recommended; '
                           'leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
