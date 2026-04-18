import time
from typing import Optional

from injector import inject, Injector

from src.tidal import Tidal
from src.youtube import Audiotree, build_playlist

PLAYLIST_NAME = 'Audiotree'
TARGET_SIZE = 100


@inject
def main(tidal: Tidal, audiotree: Audiotree) -> None:
    build_playlist(tidal, audiotree, PLAYLIST_NAME, TARGET_SIZE)


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time.time()
    lambda_handler()
    elapsed_time = time.time() - start_time
    print(f'\n\033[94mTotal time: {elapsed_time:.2f} seconds\033[0m')
