import random
from typing import Optional, List, Set

import requests
from injector import inject, Injector
from tidalapi import Session, Track
from tqdm import tqdm
from unidecode import unidecode

from src.environment import Environment

daily_blend_size = 100


@inject
def main(environment: Environment) -> None:
    session = Session()
    session.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
    session.load_oauth_session('Bearer', session.access_token)

    daily_blend = session.playlist(environment.get('DAILY_BLEND_PLAYLIST_ID'))
    existing_daily_blend_track_ids = {x.id for x in daily_blend.items()}

    new_daily_blend_track_ids = {x.id for x in session.mix(environment.get('DAILY_DISCOVER_MIX_ID')).items()}

    last_fm_recommendations = get_lastfm_playlist_tidal_track_ids(session, 'recommended')
    last_fm_mix = get_lastfm_playlist_tidal_track_ids(session, 'mix')
    last_fm_library = get_lastfm_playlist_tidal_track_ids(session, 'library')
    new_arrivals = {x.id for x in session.mix(environment.get('NEW_ARRIVALS_MIX_ID')).items()}

    new_daily_blend_track_ids |= (
                                         last_fm_recommendations | last_fm_mix | last_fm_library | new_arrivals
                                 ) - existing_daily_blend_track_ids

    if len(new_daily_blend_track_ids) < daily_blend_size:
        n_needed = daily_blend_size - len(new_daily_blend_track_ids)
        extras = list(new_arrivals - new_daily_blend_track_ids)
        random.shuffle(extras)
        extras = extras[:n_needed]
        print(f'Adding {len(extras)} duplicates from previous tracklist to fill out daily blend')
        new_daily_blend_track_ids |= set(extras)

    daily_blend.clear()
    daily_blend.add([str(x) for x in random.sample(list(new_daily_blend_track_ids), daily_blend_size)])


def get_lastfm_playlist_tidal_track_ids(session: Session, _type: str) -> Set[int]:
    tracks = set()
    playlist = requests.get(
        f'https://www.last.fm/player/station/user/amamparo/{_type}?page=1&ajax=1'
    ).json()['playlist']
    for x in tqdm(playlist):
        track = get_tidal_track(session, x['name'], [a['name'] for a in x['artists']])
        if track:
            tracks.add(track.id)
    return tracks


def get_tidal_track(session: Session, last_fm_title: str, last_fm_artists: List[str]) -> Optional[Track]:
    search_results = session.search(' '.join(last_fm_artists) + ' ' + last_fm_title, models=[Track])['tracks']
    for search_result in search_results:
        if norm(last_fm_title) not in norm(search_result.name):
            continue

        last_fm_artists = {norm(x) for x in last_fm_artists}
        tidal_artists = {norm(a.name) for a in search_result.artists}
        if not last_fm_artists <= tidal_artists:
            continue

        return search_result
    return None


def norm(text: str) -> str:
    return unidecode(text).lower().strip()


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    lambda_handler()
