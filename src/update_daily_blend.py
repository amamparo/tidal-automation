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
    daily_blend_track_ids = tidal.get_mix_track_ids(environment.get('NEW_ARRIVALS_MIX_ID'))
    for mix_type in ['recommended', 'mix', 'library']:
        last_fm_tracks = last_fm.get_mix(mix_type)
        with tqdm(total=len(last_fm_tracks), desc=f'Scanning last.fm {mix_type}') as progress:
            for last_fm_track in last_fm_tracks:
                tidal_track = tidal.find_equivalent_track(last_fm_track)
                if tidal_track:
                    progress.write(f'\033[92m✓ {last_fm_track}\033[0m')
                    daily_blend_track_ids.append(str(tidal_track.id))
                else:
                    progress.write(f'\033[91m✗ Failed to find: {last_fm_track}\033[0m')
                progress.update(1)

    shuffle(daily_blend_track_ids)

    daily_discover_track_ids = tidal.get_mix_track_ids(environment.get('DAILY_DISCOVER_MIX_ID'))
    daily_blend_track_ids = daily_blend_track_ids[:daily_blend_size - len(daily_discover_track_ids)]
    daily_blend_track_ids += daily_discover_track_ids

    shuffle(daily_blend_track_ids)

    tidal.set_playlist_tracks(environment.get('DAILY_BLEND_PLAYLIST_ID'), daily_blend_track_ids)


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time.time()
    lambda_handler()
    elapsed_time = time.time() - start_time
    print(f'\n\033[94mTotal time: {elapsed_time:.2f} seconds\033[0m')
