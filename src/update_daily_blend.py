from random import shuffle
from typing import Optional
import time

from injector import inject, Injector
from tqdm import tqdm

from src.environment import Environment
from src.last_fm import LastFm
from src.tidal import Tidal

@inject
def main(environment: Environment, tidal: Tidal, last_fm: LastFm) -> None:
    daily_blend_size = int(environment.get('DAILY_BLEND_SIZE'))
    new_arrivals = tidal.get_mix_tracks(environment.get('NEW_ARRIVALS_MIX_ID'))
    last_fm_tracks = set()
    for mix_type in ['recommended', 'mix', 'library']:
        mix_tracks = last_fm.get_mix(mix_type)
        with tqdm(total=len(mix_tracks), desc=f'Scanning last.fm {mix_type}') as progress:
            for mix_track in mix_tracks:
                progress.write(f'> {mix_track}')
                tidal_track = tidal.find_equivalent_track(mix_track)
                if tidal_track:
                    progress.write(
                        f'\033[92m✓ {tidal_track.name} - {", ".join([x.name for x in tidal_track.artists])}\033[0m'
                    )
                    last_fm_tracks.add(tidal_track)
                else:
                    progress.write(f'\033[91m✗ Failed to find: {mix_track}\033[0m')
                progress.update(1)

    daily_blend_playlist_id = environment.get('DAILY_BLEND_PLAYLIST_ID')
    existing_daily_blend_tracks = tidal.get_playlist_tracks(daily_blend_playlist_id)

    new_daily_blend_tracks = tidal.get_mix_tracks(environment.get('DAILY_DISCOVER_MIX_ID'))
    while len(new_daily_blend_tracks) < daily_blend_size:
        remaining_tracks = (new_arrivals | last_fm_tracks) - new_daily_blend_tracks
        if not remaining_tracks:
            break

        seen_artists = {
            artist.name for track in (existing_daily_blend_tracks | new_daily_blend_tracks) for artist in track.artists
        }

        roulette_wheel = []
        for track in remaining_tracks:
            multiplier = 1
            if track not in existing_daily_blend_tracks:
                multiplier += 2
            if any(artist.name not in seen_artists for artist in track.artists):
                multiplier += 3
            roulette_wheel.extend([track] * multiplier)

        shuffle(roulette_wheel)
        new_daily_blend_tracks.add(roulette_wheel.pop())

    new_daily_blend_track_ids = [str(x.id) for x in new_daily_blend_tracks]
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
