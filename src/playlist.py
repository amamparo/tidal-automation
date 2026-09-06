import re
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass
from functools import partial
from itertools import zip_longest
from math import isfinite
from statistics import median
from threading import Lock
from typing import Callable, Dict, List, Optional, Set, Tuple

from tidalapi import Track
from tqdm import tqdm

from src.discogs import Discogs
from src.genre import TagVector, Vouch, genre_confidence, normalised, style_profile, tag_rarity
from src.last_fm import LastFm, LastFmTrack
from src.mixes_db import WIDENING_MONTHS, WINDOW_MONTHS, MixesDb, MixTrack, Tracklist, searchable
from src.tidal import Tidal

PITCH_FADER_RANGE = 0.08
MIXABLE_SPAN = 1.0 + PITCH_FADER_RANGE
VOUCHING_RADIO_SHARE = 0.1
TITLE_QUALIFIER = re.compile(r'\s+[(\[].*$|\s+\d{1,3}$')


@dataclass
class TimedTrack:
    track_id: str
    tempo: float


@dataclass
class CandidateEvidence:
    track_id: str
    vouches: List[Vouch]


class TagLane:
    def __init__(self, pool: Executor, fetch: Callable[[str], TagVector],
                 seconds_per_request: float) -> None:
        self.__pool = pool
        self.__fetch = fetch
        self.__seconds_per_request = seconds_per_request
        self.__asked: Dict[str, Future[TagVector]] = {}
        self.__outstanding = 0
        self.__lock = Lock()

    def request(self, artist: str) -> None:
        if artist in self.__asked:
            return
        with self.__lock:
            self.__outstanding += 1
        self.__asked[artist] = self.__pool.submit(self.__fetch, artist)
        self.__asked[artist].add_done_callback(self.__answered)

    def __answered(self, _: Future[TagVector]) -> None:
        with self.__lock:
            self.__outstanding -= 1

    @property
    def seconds_to_drain(self) -> float:
        return self.__outstanding * self.__seconds_per_request

    def drained(self) -> Dict[str, TagVector]:
        return {artist: asked.result() for artist, asked in self.__asked.items()}


def candidates_from(tracklists: List[Tracklist]) -> List[MixTrack]:
    turns = zip_longest(*(tracklist.tracks for tracklist in tracklists))
    round_robin = (track for turn in turns for track in turn if track is not None)
    return list(dict.fromkeys(round_robin))


def is_same_recording(mix_title: str, found_name: str) -> bool:
    searched = searchable(mix_title)
    return searchable(found_name) in searched or searchable(TITLE_QUALIFIER.sub('', found_name)) in searched


def find_track(tidal: Tidal, track: MixTrack) -> Optional[Track]:
    found = tidal.find_timed_track(LastFmTrack(title=track.title, artists={track.artist}))
    return found if found and is_same_recording(track.title, found.name or '') else None


def artist_tags(last_fm: LastFm, discogs: Discogs, artist: str) -> TagVector:
    return normalised(last_fm.top_tags(artist)) or normalised(discogs.styles(artist))


def style_profile_of(last_fm: LastFm, style: str, roster_size: int) -> TagVector:
    roster = last_fm.top_artists(style, roster_size)
    return style_profile(normalised(last_fm.top_tags(artist)) for artist in roster)


def vouching_depth(radio_length: int) -> int:
    return round(radio_length * VOUCHING_RADIO_SHARE)


def credited_artists(track: Track) -> Set[str]:
    return {(artist.name or '').lower() for artist in track.artists or []}


def lead_artist(track: Track) -> str:
    credited = track.artists or []
    return (credited[0].name or '') if credited else ''


def vouches_for(artist: str, radio: List[Track]) -> List[Vouch]:
    head = radio[:vouching_depth(len(radio))]
    neighbours = [Vouch(1.0 - position / len(radio), lead_artist(track))
                  for position, track in enumerate(head)
                  if artist.lower() not in credited_artists(track)]
    return [Vouch(1.0, artist), *(vouch for vouch in neighbours if vouch.artist)]


def corpus_the_clock_can_reach(tidal: Tidal, seconds_left: float, playlist_size: int) -> float:
    return (seconds_left - tidal.seconds_to_set_playlist(playlist_size)) / tidal.seconds_per_request


def seconds_per_candidate(tidal: Tidal, timed: int, attempted: int) -> float:
    radios_per_candidate = timed / attempted if attempted else 1.0
    return tidal.seconds_per_request * (1.0 + radios_per_candidate)


def seconds_to_finish(tidal: Tidal, tags: TagLane, playlist_size: int) -> float:
    return tidal.seconds_to_set_playlist(playlist_size) + tags.seconds_to_drain


def time_to_read_again(seconds_left: float, seconds_per_read: float, seconds_to_spare: float) -> bool:
    return seconds_left - seconds_per_read >= seconds_to_spare


def reachable_candidates(read: int, seconds_spent: float, seconds_spare: float,
                         candidate_count: int) -> int:
    unmeasured = read == 0 or seconds_spent <= 0.0
    endless_clock = not isfinite(seconds_spent) or not isfinite(seconds_spare)
    if unmeasured or endless_clock:
        return candidate_count
    return min(candidate_count, read + int(seconds_spare * read / seconds_spent))


def evidence_for(tidal: Tidal, tags: TagLane, candidate: MixTrack) -> Optional[CandidateEvidence]:
    found = find_track(tidal, candidate)
    if not found or not tidal.beats_per_minute(str(found.id)):
        return None
    vouches = vouches_for(candidate.artist, tidal.track_radio(found))
    for vouch in vouches:
        tags.request(vouch.artist)
    return CandidateEvidence(track_id=str(found.id), vouches=vouches)


def gather_evidence(tidal: Tidal, tags: TagLane, candidates: List[MixTrack], playlist_size: int,
                    seconds_left: Callable[[], float]) -> List[CandidateEvidence]:
    evidence: List[CandidateEvidence] = []
    attempted = 0
    began_with = seconds_left()

    with tqdm(total=len(candidates), desc='Reading candidates') as progress:
        for candidate in candidates:
            remaining = seconds_left()
            reserved = seconds_to_finish(tidal, tags, playlist_size)
            if not time_to_read_again(remaining, seconds_per_candidate(tidal, len(evidence), attempted), reserved):
                break
            attempted += 1
            progress.update(1)
            progress.total = reachable_candidates(
                read=progress.n,
                seconds_spent=began_with - remaining,
                seconds_spare=remaining - reserved,
                candidate_count=len(candidates))
            found = evidence_for(tidal, tags, candidate)
            if found:
                evidence.append(found)
    vouched = sum(1 for item in evidence if len(item.vouches) > 1)
    print(f'evidence: {attempted} candidates attempted, {len(evidence)} timed, {vouched} with a radio')
    return evidence


def genre_confidences(tidal: Tidal, last_fm: LastFm, discogs: Discogs, candidates: List[MixTrack],
                      *, style: str, playlist_size: int,
                      seconds_left: Callable[[], float]) -> Dict[str, float]:
    with ThreadPoolExecutor(max_workers=1) as lookups:
        profile = lookups.submit(style_profile_of, last_fm, style, playlist_size)
        tags = TagLane(lookups, partial(artist_tags, last_fm, discogs),
                       last_fm.seconds_per_request + discogs.seconds_per_request)
        evidence = gather_evidence(tidal, tags, candidates, playlist_size, seconds_left)
        gathered = tags.drained()
    anchor = profile.result()
    rarity = tag_rarity(gathered.values())
    print(f'genres: {len(anchor)} tags anchor {style}, {sum(1 for vector in gathered.values() if vector)} '
          f'of {len(gathered)} vouching artists tagged')
    return {item.track_id: genre_confidence(item.vouches, gathered, anchor, rarity) for item in evidence}


def most_confident(confidence: Dict[str, float]) -> List[str]:
    return sorted(confidence, key=lambda track_id: (-confidence[track_id], track_id))


def tempo_span(tempos: List[float]) -> float:
    return max(tempos) / min(tempos)


def fits_inside_one_pitch_fader(tracks: List[TimedTrack]) -> bool:
    tempos = [track.tempo for track in tracks]
    return not tempos or tempo_span(tempos) <= MIXABLE_SPAN


def without_the_least_confident_outlier(selected: List[TimedTrack]) -> List[TimedTrack]:
    centre = median(track.tempo for track in selected)
    least_confident_first = reversed(selected)
    dropped = max(least_confident_first, key=lambda track: abs(track.tempo - centre))
    return [track for track in selected if track is not dropped]


def annealed_selection(timed: List[TimedTrack], playlist_size: int) -> List[TimedTrack]:
    selected = timed[:playlist_size]
    while not fits_inside_one_pitch_fader(selected):
        selected = without_the_least_confident_outlier(selected)
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
                   reachable: float) -> Tuple[List[Tracklist], List[MixTrack]]:
    months = WINDOW_MONTHS
    tracklists = mixes_db.get_tracklists(query_for(months))
    candidates = candidates_from(tracklists)
    while len(candidates) < reachable:
        wider = mixes_db.get_tracklists(query_for(months + WIDENING_MONTHS))
        widened = candidates_from(wider)
        if len(widened) <= len(candidates):
            break
        months += WIDENING_MONTHS
        tracklists, candidates = wider, widened
    print(f'mixesdb: {len(tracklists)} tracklists over {months} months, {len(candidates)} candidates')
    return tracklists, candidates


def corpus_candidates(mixes_db: MixesDb, query_for: Callable[[int], str], reachable: float,
                      playlist_size: int) -> List[MixTrack]:
    tracklists, candidates = widened_corpus(mixes_db, query_for, reachable)
    if len(candidates) < playlist_size:
        raise RuntimeError(
            f'only {len(candidates)} candidates from {len(tracklists)} tracklists for {playlist_size} tracks')
    return candidates


def rebuild(tidal: Tidal, mixes_db: MixesDb, last_fm: LastFm, discogs: Discogs, *, style: str,
            query_for: Callable[[int], str], playlist_id: str, playlist_size: int,
            seconds_left: Callable[[], float]) -> None:
    reachable = corpus_the_clock_can_reach(tidal, seconds_left(), playlist_size)
    candidates = corpus_candidates(mixes_db, query_for, reachable, playlist_size)

    confidence = genre_confidences(tidal, last_fm, discogs, candidates, style=style,
                                   playlist_size=playlist_size, seconds_left=seconds_left)
    track_ids = mixable_selection(most_confident(confidence), tidal.beats_per_minute, playlist_size)
    if len(track_ids) < playlist_size:
        raise RuntimeError(f'only {len(track_ids)} mixable tracks of {len(confidence)} scored; '
                           'leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
