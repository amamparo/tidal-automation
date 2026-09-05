import re
from collections import defaultdict
from datetime import date
from math import log, sqrt
from random import Random
from statistics import median
from time import monotonic
from typing import Callable, Dict, Iterable, List, Optional

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


def genre_affinity(tags: Dict[str, float], profile: Dict[str, float]) -> float:
    artist_magnitude = sqrt(sum(weight ** 2 for weight in tags.values()))
    profile_magnitude = sqrt(sum(weight ** 2 for weight in profile.values()))
    if artist_magnitude == 0.0 or profile_magnitude == 0.0:
        return 0.0
    shared = sum(weight * profile.get(tag, 0.0) for tag, weight in tags.items())
    return shared / (artist_magnitude * profile_magnitude)


def styles_while_time_allows(discogs: Discogs, artists: List[str],
                             seconds_left: Callable[[], float]) -> Dict[str, Dict[str, float]]:
    styles_by_artist: Dict[str, Dict[str, float]] = {}
    with tqdm(total=len(artists), desc='Reading releases') as progress:
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
    profile = genre_profile(fingerprints.values())
    affinities = {artist: genre_affinity(fingerprint, profile)
                  for artist, fingerprint in fingerprints.items() if fingerprint}
    typical = median(affinities.values()) if affinities else 1.0
    print(f'genres: {len(affinities)} of {len(artists)} artists fingerprinted across {len(profile)} genres, '
          f'{len(styles_by_artist)} enriched from discogs, the rest weigh {typical:.2f}')
    return {track: weight * affinities.get(track.artist, typical) for track, weight in weights.items()}


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
            if len(track_ids) >= playlist_size or monotonic() > deadline:
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
