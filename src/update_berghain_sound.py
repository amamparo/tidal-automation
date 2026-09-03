# pylint: disable=duplicate-code
from datetime import date
from time import time
from typing import Optional

from injector import inject, Injector

from src.environment import Environment
from src.mixes_db import MixesDb
from src.playlist import rebuild
from src.tidal import Tidal

PLAYLIST_NAME = 'berghain-sound'
SEARCH_QUERY = 'style:Techno tracklist:complete intitle:Berlin'


@inject
def main(environment: Environment, tidal: Tidal, mixes_db: MixesDb) -> None:
    today = date.today()
    rebuild(
        tidal,
        mixes_db,
        name=PLAYLIST_NAME,
        query=SEARCH_QUERY,
        playlist_id=environment.require('BERGHAIN_SOUND_PLAYLIST_ID'),
        playlist_size=int(environment.require('BERGHAIN_SOUND_SIZE')),
        today=today
    )


def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    # pylint: disable=unused-argument
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
