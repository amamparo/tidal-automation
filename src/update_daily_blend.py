from random import shuffle
from typing import Optional, List

import requests
from injector import inject, Injector
from tidalapi import Session, Track
from tqdm import tqdm
from unidecode import unidecode

from src.environment import Environment

max_track_duration_minutes = 20


@inject
def main(environment: Environment) -> None:
    session = Session()
    session.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
    session.load_oauth_session('Bearer', session.access_token)

    last_fm_recommendations = get_lastfm_recommendations(session)
    last_fm_mix = get_lastfm_mix(session)
    last_fm_library = get_lastfm_library(session)

    daily_discover_tracks = session.mix(environment.get('DAILY_DISCOVER_MIX_ID')).items()
    new_arrivals_tracks = session.mix(environment.get('NEW_ARRIVALS_MIX_ID')).items()

    daily_blend_tracks = (daily_discover_tracks + new_arrivals_tracks + last_fm_recommendations + last_fm_mix +
                          last_fm_library)
    daily_blend_tracks = list({(x.id, x): x for x in daily_blend_tracks}.values())
    shuffle(daily_blend_tracks)
    daily_blend_tracks = daily_blend_tracks[:100]
    daily_blend = session.playlist(environment.get('DAILY_BLEND_PLAYLIST_ID'))
    daily_blend.clear()
    daily_blend.add([str(x.id) for x in daily_blend_tracks])


def get_lastfm_library(session: Session) -> List[Track]:
    return get_lastfm_playlist(session, 'https://www.last.fm/player/station/user/amamparo/library?page=1&ajax=1')

def get_lastfm_recommendations(session: Session) -> List[Track]:
    return get_lastfm_playlist(session, 'https://www.last.fm/player/station/user/amamparo/recommended?page=1&ajax=1')

def get_lastfm_mix(session: Session) -> List[Track]:
    return get_lastfm_playlist(session, 'https://www.last.fm/player/station/user/amamparo/mix?page=1&ajax=1')

def get_lastfm_playlist(session: Session, url: str) -> List[Track]:
    tracks = []
    playlist = requests.get(url).json()['playlist']
    for x in tqdm(playlist):
        track = get_tidal_track(session, x['name'], [a['name'] for a in x['artists']])
        if track:
            tracks.append(track)
    return tracks


def get_tidal_track(session: Session, last_fm_title: str, last_fm_artists: List[str]) -> Optional[Track]:
    search_results = session.search(' '.join(last_fm_artists) + ' ' + last_fm_title, models=[Track])['tracks']
    for search_result in search_results:
        if unidecode(last_fm_title.lower()) not in unidecode(search_result.name.lower()):
            continue
        if any(x for x in last_fm_artists if unidecode(x.lower()) not in [unidecode(a.name.lower()) for a in search_result.artists]):
            continue
        return search_result
    return None


# pylint: disable=unused-argument
def lambda_handler(event: Optional[dict] = None, context: Optional[dict] = None) -> None:
    Injector().call_with_injection(main)


if __name__ == '__main__':
    lambda_handler()
