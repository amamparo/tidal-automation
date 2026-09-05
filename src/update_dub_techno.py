# pylint: disable=duplicate-code
from datetime import date
from time import time
from typing import Callable, Optional

from injector import inject, Injector

from src.clock import deadline_clock
from src.discogs import Discogs
from src.environment import Environment
from src.last_fm import LastFm
from src.mixes_db import MixesDb, date_window
from src.playlist import rebuild
from src.tidal import Tidal


def search_query(today: date) -> str:
    return f'style:"Dub Techno" style:Minimal -tracklist:none date:{date_window(today)}'


@inject
def main(environment: Environment, tidal: Tidal, mixes_db: MixesDb, last_fm: LastFm, discogs: Discogs,
         *, seconds_left: Callable[[], float]) -> None:
    today = date.today()
    rebuild(
        tidal,
        mixes_db,
        last_fm,
        discogs,
        query=search_query(today),
        playlist_id=environment.require('DUB_TECHNO_PLAYLIST_ID'),
        playlist_size=int(environment.require('DUB_TECHNO_SIZE')),
        today=today,
        seconds_left=seconds_left
    )


def lambda_handler(event: Optional[dict] = None, context: Optional[object] = None) -> None:
    # pylint: disable=unused-argument
    Injector().call_with_injection(main, kwargs={'seconds_left': deadline_clock(context)})


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
