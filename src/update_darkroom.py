from datetime import date
from time import time
from typing import Callable, Optional

from injector import inject, Injector

from src.clock import deadline_clock
from src.environment import Environment
from src.mixes_db import MixesDb, date_window
from src.playlist import rebuild
from src.tidal import Tidal


def search_query(today: date, months: int) -> str:
    return f'style:"Dub Techno" style:Minimal -tracklist:none date:{date_window(today, months)}'


@inject
def main(environment: Environment, tidal: Tidal, mixes_db: MixesDb,
         *, seconds_left: Callable[[], float]) -> None:
    today = date.today()
    rebuild(
        tidal,
        mixes_db,
        query_for=lambda months: search_query(today, months),
        playlist_id=environment.require('DARKROOM_PLAYLIST_ID'),
        playlist_size=int(environment.require('DARKROOM_SIZE')),
        seconds_left=seconds_left
    )


def lambda_handler(event: Optional[dict] = None, context: Optional[object] = None) -> None:
    # pylint: disable=unused-argument
    Injector().call_with_injection(main, kwargs={'seconds_left': deadline_clock(context)})


if __name__ == '__main__':
    start_time = time()
    lambda_handler()
    print(f'\n\033[94mTotal time: {time() - start_time:.2f} seconds\033[0m')
