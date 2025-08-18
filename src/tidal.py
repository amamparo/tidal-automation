import re
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

        fixed = self.__fix_last_fm_track(last_fm_track)

        query = ' '.join(fixed.artists) + ' ' + fixed.title
        results = self.__tidal.search(query, models=[Track])['tracks']
        for result in results:
            self.__track_find_cache[last_fm_track] = result
            return result

        self.__track_find_cache[last_fm_track] = None
        return None

    @staticmethod
    def __fix_last_fm_track(last_fm_track: LastFmTrack) -> LastFmTrack:
        title = last_fm_track.title
        artists = set(last_fm_track.artists)
        
        with_or_featuring_pattern = r'\s*\([^)]*(?:with|feat\.?|featuring)\s+([^)]+)\)'
        matches = re.findall(with_or_featuring_pattern, title, re.IGNORECASE)

        for match in matches:
            artist_names = re.split(r'\s*[&,]\s*|\s+and\s+', match)
            for artist in artist_names:
                artist = artist.strip()
                if artist:
                    artists.add(artist)
        
        cleaned_title = re.sub(with_or_featuring_pattern, '', title, flags=re.IGNORECASE)

        track_version_pattern = r'\s*\([^)]*(?:Album Version|Radio Edit|Single Version|Extended Version|Original Mix|Remix|Remastered|Explicit|Clean)\)'
        cleaned_title = re.sub(track_version_pattern, '', cleaned_title, flags=re.IGNORECASE)
        
        cleaned_title = cleaned_title.strip()
        
        return LastFmTrack(
            title=cleaned_title,
            artists=artists
        )
