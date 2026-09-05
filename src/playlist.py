import re
from collections import defaultdict
from datetime import date
from math import log, sqrt
from random import Random
from statistics import median
from time import monotonic
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from requests.exceptions import HTTPError  # type: ignore[import-untyped]
from tidalapi import Track
from tidalapi.exceptions import ObjectNotFound
from tqdm import tqdm

from src.discogs import Discogs
from src.last_fm import LastFm, LastFmTrack
from src.mixes_db import MixesDb, MixTrack, Tracklist, searchable
from src.tidal import Tidal

HOTTEST_MIX_WEIGHT = 5.0
RECENCY_HALF_LIFE_DAYS = 180.0
MATCH_DEADLINE_SECONDS = 420
CONSECUTIVE_MISS_LIMIT = 40
PITCH_FADER_RANGE = 0.08
OCTAVE = sqrt(2.0)
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


def genre_fingerprint(*sources: Dict[str, float]) -> Dict[str, float]:
    fingerprint: Dict[str, float] = defaultdict(float)
    for source in sources:
        magnitude = sqrt(sum(weight ** 2 for weight in source.values()))
        if magnitude == 0.0:
            continue
        for name, weight in source.items():
            fingerprint[name] += weight / magnitude
    return dict(fingerprint)


def weight_per_artist(weights: Dict[MixTrack, float]) -> Dict[str, float]:
    mass: Dict[str, float] = defaultdict(float)
    for track, weight in weights.items():
        mass[track.artist] += weight
    return mass


def genre_profile(artist_tags: Iterable[Dict[str, float]]) -> Dict[str, float]:
    profile: Dict[str, float] = defaultdict(float)
    for tags in artist_tags:
        for tag, weight in tags.items():
            profile[tag] += weight
    return profile


def tag_rarity(fingerprints: List[Dict[str, float]]) -> Dict[str, float]:
    carrying: Dict[str, int] = defaultdict(int)
    for fingerprint in fingerprints:
        for tag in fingerprint:
            carrying[tag] += 1
    return {tag: max(0.0, log(len(fingerprints) / (1 + count))) for tag, count in carrying.items()}


def emphasise_rare(fingerprint: Dict[str, float], rarity: Dict[str, float]) -> Dict[str, float]:
    return {tag: weight * rarity.get(tag, 0.0) for tag, weight in fingerprint.items()}


def core_profile(fingerprints: List[Dict[str, float]]) -> Dict[str, float]:
    everything = genre_profile(fingerprints)
    scored = [(genre_affinity(fingerprint, everything), fingerprint)
              for fingerprint in fingerprints if fingerprint]
    if not scored:
        return everything
    typical = median(score for score, _ in scored)
    return genre_profile([fingerprint for score, fingerprint in scored if score >= typical])


def genre_affinity(tags: Dict[str, float], profile: Dict[str, float]) -> float:
    artist_magnitude = sqrt(sum(weight ** 2 for weight in tags.values()))
    profile_magnitude = sqrt(sum(weight ** 2 for weight in profile.values()))
    if artist_magnitude == 0.0 or profile_magnitude == 0.0:
        return 0.0
    shared = sum(weight * profile.get(tag, 0.0) for tag, weight in tags.items())
    return shared / (artist_magnitude * profile_magnitude)


def affordable_lookups(wanted: int, seconds_left: float, seconds_per_request: float) -> int:
    if seconds_per_request <= 0.0:
        return wanted
    return max(0, min(wanted, int((seconds_left - MATCH_DEADLINE_SECONDS) / seconds_per_request)))


def styles_while_time_allows(discogs: Discogs, artists: List[str],
                             seconds_left: Callable[[], float]) -> Dict[str, Dict[str, float]]:
    styles_by_artist: Dict[str, Dict[str, float]] = {}
    reachable = affordable_lookups(len(artists), seconds_left(), discogs.seconds_per_request)
    with tqdm(total=reachable, desc='Reading releases') as progress:
        for artist in artists:
            if seconds_left() - discogs.seconds_per_request < MATCH_DEADLINE_SECONDS:
                break
            styles_by_artist[artist] = discogs.styles(artist)
            progress.update(1)
    return styles_by_artist


def weigh_by_genre(last_fm: LastFm, discogs: Discogs, weights: Dict[MixTrack, float],
                   seconds_left: Callable[[], float]) -> Dict[MixTrack, float]:
    artists = sorted({track.artist for track in weights})
    tags_by_artist = {artist: last_fm.top_tags(artist) for artist in tqdm(artists, desc='Reading genres')}

    mass = weight_per_artist(weights)
    unknown_first = sorted(artists, key=lambda artist: (bool(tags_by_artist[artist]), -mass[artist]))
    styles_by_artist = styles_while_time_allows(discogs, unknown_first, seconds_left)

    fingerprints = {artist: genre_fingerprint(tags_by_artist[artist], styles_by_artist.get(artist, {}))
                    for artist in artists}
    rarity = tag_rarity(list(fingerprints.values()))
    distinctive = {artist: emphasise_rare(fingerprint, rarity)
                   for artist, fingerprint in fingerprints.items()}
    profile = core_profile(list(distinctive.values()))
    affinities = {artist: genre_affinity(fingerprint, profile)
                  for artist, fingerprint in distinctive.items() if fingerprint}
    print(f'genres: {len(affinities)} of {len(artists)} artists fingerprinted across {len(profile)} genres, '
          f'{len(styles_by_artist)} enriched from discogs')
    if not any(affinities.values()):
        return weights
    typical = median(affinities.values())
    return {track: weight * affinities.get(track.artist, typical) for track, weight in weights.items()}


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


def fold_to_octave(tempo: float, centre: float) -> float:
    while tempo < centre / OCTAVE:
        tempo *= 2.0
    while tempo > centre * OCTAVE:
        tempo /= 2.0
    return tempo


def mixable_tempo(tempos: List[float]) -> float:
    centre = median(tempos)
    return median([fold_to_octave(tempo, centre) for tempo in tempos])


def mixable_with(tempo: float, centre: float) -> bool:
    return abs(fold_to_octave(tempo, centre) - centre) <= centre * PITCH_FADER_RANGE


def mixable_selection(matched: List[Tuple[str, float]]) -> List[str]:
    if not matched:
        return []
    centre = mixable_tempo([tempo for _, tempo in matched])
    return [track_id for track_id, tempo in matched if mixable_with(tempo, centre)]


def find_tracks_on_tidal(tidal: Tidal, candidates: List[MixTrack], playlist_size: int) -> List[str]:
    matched: List[Tuple[str, float]] = []
    selected: List[str] = []
    deadline = monotonic() + MATCH_DEADLINE_SECONDS
    lookups = consecutive_misses = untimed = 0

    with tqdm(total=playlist_size, desc='Building playlist') as progress:
        for candidate in candidates:
            if len(selected) >= playlist_size or monotonic() > deadline:
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
            if any(track_id == already for already, _ in matched):
                continue
            tempo = tidal.beats_per_minute(found)
            if not tempo:
                untimed += 1
                progress.write(f'\033[90m✗ {found.name} - {candidate.artist} (no tempo)\033[0m')
                continue
            matched.append((track_id, float(tempo)))
            selected = mixable_selection(matched)
            progress.n = min(len(selected), playlist_size)
            progress.refresh()
            progress.write(f'\033[92m✓ {found.name} - {candidate.artist} ({tempo} bpm)\033[0m')
    centre = mixable_tempo([tempo for _, tempo in matched]) if matched else 0.0
    print(f'tidal: {lookups} lookups, {len(matched)} timed, {untimed} untimed, '
          f'{len(selected)} mixable around {centre:.0f} bpm')
    return selected[:playlist_size]


def rebuild(tidal: Tidal, mixes_db: MixesDb, last_fm: LastFm, discogs: Discogs, *, query: str,
            playlist_id: str, playlist_size: int, today: date,
            seconds_left: Callable[[], float]) -> None:
    tracklists = mixes_db.get_tracklists(query)
    weights = weigh_candidates(tracklists, today)
    print(f'mixesdb: {len(tracklists)} tracklists, {len(weights)} candidates')
    if len(weights) < playlist_size:
        raise RuntimeError(
            f'only {len(weights)} candidates from {len(tracklists)} tracklists for {playlist_size} tracks')

    weights = weigh_by_genre(last_fm, discogs, weights, seconds_left)
    track_ids = find_tracks_on_tidal(tidal, weighted_draw(weights, today.toordinal()), playlist_size)
    if len(track_ids) < max(1, playlist_size // 2):
        raise RuntimeError(f'only {len(track_ids)} tracks matched; leaving the playlist untouched')
    tidal.set_playlist_tracks(playlist_id, track_ids)
