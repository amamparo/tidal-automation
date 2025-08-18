from typing import Set, List, Optional, Dict

from injector import inject
from tidalapi import Session, Track

from src.environment import Environment
from src.last_fm import LastFmTrack


class Tidal:
    @inject
    def __init__(self, environment: Environment):
        self.__tidal = Session()
        self.__tidal.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
        self.__tidal.load_oauth_session('Bearer', self.__tidal.access_token)
        self.__track_find_cache: Dict[LastFmTrack, Optional[Track]] = {}

    def get_mix_track_ids(self, mix_id: str) -> List[str]:
        return [str(x.id) for x in self.__tidal.mix(mix_id).items()]

    def set_playlist_tracks(self, playlist_id: str, track_ids: List[str]) -> None:
        playlist = self.__tidal.playlist(playlist_id)
        playlist.clear()
        playlist.add(track_ids)

    def find_equivalent_track(self, last_fm_track: LastFmTrack) -> Optional[Track]:
        if last_fm_track in self.__track_find_cache:
            return self.__track_find_cache[last_fm_track]

        query = ' '.join(last_fm_track.artists) + ' ' + last_fm_track.title
        results = self.__tidal.search(query, models=[Track])['tracks']
        for result in results:
            self.__track_find_cache[last_fm_track] = result
            return result

        self.__track_find_cache[last_fm_track] = None
        return None
