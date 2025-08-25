from random import shuffle
from typing import Optional
import time

from injector import inject, Injector
from tqdm import tqdm

from src.environment import Environment
from src.last_fm import LastFm
from src.tidal import Tidal

daily_blend_size = 100


@inject
def main(environment: Environment, tidal: Tidal, last_fm: LastFm) -> None:
    new_arrivals_track_ids = tidal.get_mix_track_ids(environment.get('NEW_ARRIVALS_MIX_ID'))
    last_fm_track_ids = []
    for mix_type in ['recommended', 'mix', 'library']:
        last_fm_tracks = last_fm.get_mix(mix_type)
        with tqdm(total=len(last_fm_tracks), desc=f'Scanning last.fm {mix_type}') as progress:
            for last_fm_track in last_fm_tracks:
                progress.write(f'> {last_fm_track}')
                tidal_track = tidal.find_equivalent_track(last_fm_track)
                if tidal_track:
                    progress.write(f'\033[92m✓ {tidal_track}\033[0m')
                    last_fm_track_ids.append(str(tidal_track.id))
                else:
                    progress.write(f'\033[91m✗ Failed to find: {last_fm_track}\033[0m')
                progress.update(1)

    daily_blend_playlist_id = environment.get('DAILY_BLEND_PLAYLIST_ID')
    existing_daily_blend_track_ids = tidal.get_playlist_track_ids(daily_blend_playlist_id)
    roulette_wheel = []
    for track_id in list(set(new_arrivals_track_ids + last_fm_track_ids)):
        if track_id in existing_daily_blend_track_ids:
            roulette_wheel.append(track_id)
        else:
            roulette_wheel.extend([track_id] * 2)

    new_daily_blend_track_ids = tidal.get_mix_track_ids(environment.get('DAILY_DISCOVER_MIX_ID'))
    shuffle(roulette_wheel)
    while roulette_wheel and len(new_daily_blend_track_ids) < daily_blend_size:
        track_id = roulette_wheel.pop()
        roulette_wheel = [x for x in roulette_wheel if x != track_id]
        if track_id not in new_daily_blend_track_ids:
            new_daily_blend_track_ids.append(track_id)

    shuffle(new_daily_blend_track_ids)

    tidal.set_playlist_tracks(daily_blend_playlist_id, new_daily_blend_track_ids)


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time.time()
    lambda_handler()
    elapsed_time = time.time() - start_time
    print(f'\n\033[94mTotal time: {elapsed_time:.2f} seconds\033[0m')
