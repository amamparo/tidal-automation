import re
from typing import Set, List, Optional, Dict

from injector import inject, singleton
from tidalapi import Session, Track

from src.environment import Environment
from src.last_fm import LastFmTrack

@singleton
class Tidal:
    @inject
    def __init__(self, environment: Environment):
        self.__tidal = Session()
        self.__tidal.token_refresh(environment.get('TIDAL_REFRESH_TOKEN'))
        self.__tidal.load_oauth_session('Bearer', self.__tidal.access_token)
        self.__track_find_cache: Dict[LastFmTrack, Optional[Track]] = {}
        self.__album_artists_cache: Dict[str, Set[str]] = {}

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

        # Replace & with space in artists for search query
        search_artists = [artist.replace('&', ' ') for artist in fixed.artists]
        query = ' '.join(search_artists) + ' ' + fixed.title
        results = self.__tidal.search(query, models=[Track])['tracks']
        various_artists_versions = []
        for result in results:
            track_artists = {artist.name for artist in result.artists}
            if not any(self.__artists_match(artist, track_artists) for artist in fixed.artists):
                continue

            album_artists = self.__get_album_artists(str(result.album.id))
            if 'Various Artists' in album_artists:
                various_artists_versions.append(result)
                continue

            self.__track_find_cache[last_fm_track] = result
            return result

        if various_artists_versions:
            self.__track_find_cache[last_fm_track] = various_artists_versions[0]
            return various_artists_versions[0]

        self.__track_find_cache[last_fm_track] = None
        return None

    def __get_album_artists(self, album_id: str) -> Set[str]:
        if album_id in self.__album_artists_cache:
            return self.__album_artists_cache[album_id]
        album = self.__tidal.album(album_id)
        result = {artist.name for artist in album.artists}
        self.__album_artists_cache[album_id] = result
        return result

    @staticmethod
    def __fix_last_fm_track(last_fm_track: LastFmTrack) -> LastFmTrack:
        title = last_fm_track.title
        artists = set()
        
        for artist in last_fm_track.artists:
            if ',' in artist:
                for split_artist in artist.split(','):
                    artists.add(split_artist.strip())
            else:
                artists.add(artist)

        with_or_featuring_pattern = r'\s*\([^)]*(?:with|ft.|feat\.?|featuring)\s+([^)]+)\)'
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

    @staticmethod
    def __artists_match(artist: str, track_artists: Set[str]) -> bool:
        """Check if artist matches any in track_artists, treating 'and' and '&' as equivalent."""
        # Normalize the artist name by replacing '&' with 'and'
        normalized_artist = artist.replace('&', 'and').lower().strip()
        
        for track_artist in track_artists:
            # Normalize the track artist name
            normalized_track_artist = track_artist.replace('&', 'and').lower().strip()
            if normalized_artist == normalized_track_artist:
                return True
        return False
