from random import shuffle
from typing import Optional

from injector import inject, Injector
from tidalapi import Session

from src.environment import Environment


@inject
def main(environment: Environment) -> None:
    session = Session()
    session.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
    session.load_oauth_session('Bearer', session.access_token)

    daily_discover_tracks = session.mix(environment.get('DAILY_DISCOVER_MIX_ID')).items()

    already_seen_artist_ids = []
    for t in daily_discover_tracks:
        already_seen_artist_ids.extend([a.id for a in t.artists])

    additional_tracks = []
    for track in session.mix(environment.get('NEW_ARRIVALS_MIX_ID')).items():
        if track.id in [x.id for x in daily_discover_tracks]:
            continue
        track_artist_ids = [a.id for a in track.artists]
        if any(x in already_seen_artist_ids for x in track_artist_ids):
            continue
        additional_tracks.append(track)
        already_seen_artist_ids.extend(track_artist_ids)

    additional_tracks_target_size = len(additional_tracks) * 2

    my_most_listened_tracks = session.mix(environment.get('MY_MOST_LISTENED_MIX_ID')).items()
    shuffle(my_most_listened_tracks)
    for track in my_most_listened_tracks:
        if len(additional_tracks) == additional_tracks_target_size:
            break
        track_artist_ids = [a.id for a in track.artists]
        if any(x in already_seen_artist_ids for x in track_artist_ids):
            continue
        additional_tracks.append(track)
        already_seen_artist_ids.extend(track_artist_ids)

    shuffle(additional_tracks)

    n_tracks_to_add_from_additional = int(environment.get('DAILY_BLEND_SIZE')) - len(daily_discover_tracks)

    playlist_tracks = daily_discover_tracks + additional_tracks[:n_tracks_to_add_from_additional]

    shuffle(playlist_tracks)
    daily_blend = session.playlist(environment.get('DAILY_BLEND_PLAYLIST_ID'))
    daily_blend.clear()
    daily_blend.add([str(x.id) for x in playlist_tracks])


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    lambda_handler()
