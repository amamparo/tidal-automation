from random import shuffle
from time import time
from typing import List, Optional, Set

from injector import inject, Injector
from tidalapi import Track
from tqdm import tqdm

from src.environment import Environment
from src.last_fm import LastFm
from src.tidal import Tidal


def find_last_fm_tracks_on_tidal(tidal: Tidal, last_fm: LastFm) -> Set[Track]:
    found: Set[Track] = set()
    for mix_type in ['recommended', 'mix', 'library']:
        mix_tracks = last_fm.get_mix(mix_type)
        with tqdm(total=len(mix_tracks), desc=f'Scanning last.fm {mix_type}') as progress:
            for mix_track in mix_tracks:
                progress.write(f'> {mix_track}')
                tidal_track = tidal.find_equivalent_track(mix_track)
                if tidal_track:
                    artists = ', '.join(x.name or '' for x in (tidal_track.artists or []))
                    progress.write(f'\033[92m✓ {tidal_track.name} - {artists}\033[0m')
                    found.add(tidal_track)
                else:
                    progress.write(f'\033[91m✗ Failed to find: {mix_track}\033[0m')
                progress.update(1)
    return found


def pick_weighted_track(candidates: Set[Track], existing: Set[Track], chosen: Set[Track]) -> Track:
    seen_artists = {artist.name for track in (existing | chosen) for artist in (track.artists or [])}

    roulette_wheel: List[Track] = []
    for track in candidates:
        multiplier = 1
        if track not in existing:
            multiplier += 2
        if any(artist.name not in seen_artists for artist in (track.artists or [])):
            multiplier += 3
        roulette_wheel.extend([track] * multiplier)

    shuffle(roulette_wheel)
    return roulette_wheel.pop()


@inject
def main(environment: Environment, tidal: Tidal, last_fm: LastFm) -> None:
    daily_blend_size = int(environment.require('DAILY_BLEND_SIZE'))
    new_arrivals = tidal.get_mix_tracks(environment.require('NEW_ARRIVALS_MIX_ID'))
    candidate_tracks = new_arrivals | find_last_fm_tracks_on_tidal(tidal, last_fm)

    daily_blend_playlist_id = environment.require('DAILY_BLEND_PLAYLIST_ID')
    existing_blend_tracks = tidal.get_playlist_tracks(daily_blend_playlist_id)
    blend_tracks = tidal.get_mix_tracks(environment.require('DAILY_DISCOVER_MIX_ID'))

    while len(blend_tracks) < daily_blend_size:
        remaining_tracks = candidate_tracks - blend_tracks
        if not remaining_tracks:
            break
        blend_tracks.add(pick_weighted_track(remaining_tracks, existing_blend_tracks, blend_tracks))

    blend_track_ids = [str(x.id) for x in blend_tracks]
    shuffle(blend_track_ids)

    tidal.set_playlist_tracks(daily_blend_playlist_id, blend_track_ids)


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
