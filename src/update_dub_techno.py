# pylint: disable=duplicate-code
from datetime import date
from time import time
from typing import Optional

from injector import inject, Injector

from src.environment import Environment
from src.mixes_db import MixesDb, date_window
from src.playlist import rebuild
from src.tidal import Tidal


def search_query(today: date) -> str:
    return f'style:"Dub Techno" -tracklist:none hasplayer date:{date_window(today)}'


@inject
def main(environment: Environment, tidal: Tidal, mixes_db: MixesDb) -> None:
    today = date.today()
    rebuild(
        tidal,
        mixes_db,
        query=search_query(today),
        playlist_id=environment.require('DUB_TECHNO_PLAYLIST_ID'),
        playlist_size=int(environment.require('DUB_TECHNO_SIZE')),
        today=today
    )


def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    # pylint: disable=unused-argument
    Injector().call_with_injection(main)


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
