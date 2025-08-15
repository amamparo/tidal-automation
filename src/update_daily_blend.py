from random import shuffle
from typing import Optional

from injector import inject, Injector
from tidalapi import Session

from src.environment import Environment

max_track_duration_minutes = 20


@inject
def main(environment: Environment) -> None:
    session = Session()
    session.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
    session.load_oauth_session('Bearer', session.access_token)

    daily_blend = session.playlist(environment.get('DAILY_BLEND_PLAYLIST_ID'))

    daily_discover_tracks = session.mix(environment.get('DAILY_DISCOVER_MIX_ID')).items()
    new_arrivals_tracks = session.mix(environment.get('NEW_ARRIVALS_MIX_ID')).items()

    daily_blend_tracks = daily_discover_tracks + new_arrivals_tracks
    shuffle(daily_blend_tracks)
    daily_blend.clear()
    daily_blend.add([str(x.id) for x in daily_blend_tracks])


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    lambda_handler()
