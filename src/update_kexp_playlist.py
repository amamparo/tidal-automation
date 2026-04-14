import time
from random import shuffle
from typing import Optional

from injector import inject, Injector
from tqdm import tqdm

from src.tidal import Tidal
from src.youtube import Kexp

PLAYLIST_NAME = 'KEXP'
TARGET_SIZE = 100


@inject
def main(tidal: Tidal, kexp: Kexp) -> None:
    selected_track_ids: list[str] = []
    seen_track_ids: set[str] = set()

    with tqdm(total=TARGET_SIZE, desc='Building KEXP playlist') as progress:
        progress.write('Fetching KEXP channel listing...')
        for performance in kexp.iter_performances():
            if len(selected_track_ids) >= TARGET_SIZE:
                break
            progress.write(f'> {performance.artist} — searching {len(performance.songs)} songs')
            track = tidal.pick_track_by_popularity(performance.artist, performance.songs)
            if track is None:
                progress.write(f'\033[91m✗ No Tidal match for {performance.artist}\033[0m')
                continue
            track_id = str(track.id)
            if track_id in seen_track_ids:
                continue
            seen_track_ids.add(track_id)
            selected_track_ids.append(track_id)
            progress.write(
                f'\033[92m✓ {track.name} - {", ".join(a.name for a in track.artists)} '
                f'(popularity {track.popularity})\033[0m'
            )
            progress.update(1)

    shuffle(selected_track_ids)
    playlist_id = tidal.get_or_create_playlist_id(PLAYLIST_NAME)
    tidal.set_playlist_tracks(playlist_id, selected_track_ids)


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time.time()
    lambda_handler()
    elapsed_time = time.time() - start_time
    print(f'\n\033[94mTotal time: {elapsed_time:.2f} seconds\033[0m')
