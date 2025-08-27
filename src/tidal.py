import re
import time

import unicodedata
from collections import deque
from threading import Lock
from time import sleep
from typing import Set, List, Optional, Dict

from injector import inject, singleton
from tidalapi import Session, Track, Album

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
        self.__album_cache: Dict[str, Album] = {}

        self.__max_requests_per_second = 1
        self.__request_times = deque(maxlen=self.__max_requests_per_second)
        self.__rate_limit_lock = Lock()

    def __rate_limit(self):
        """Enforce rate limiting - max 5 requests per second."""
        with self.__rate_limit_lock:
            now = time.time()

            # Remove timestamps older than 1 second
            while self.__request_times and self.__request_times[0] < now - 1.0:
                self.__request_times.popleft()

            # If we've made 5 requests in the last second, wait
            if len(self.__request_times) >= self.__max_requests_per_second:
                sleep_time = 1.0 - (now - self.__request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    now = time.time()

            # Record this request
            self.__request_times.append(now)

    def get_mix_track_ids(self, mix_id: str) -> Set[str]:
        return {str(x.id) for x in self.get_mix_tracks(mix_id)}

    def get_mix_tracks(self, mix_id: str) -> Set[Track]:
        self.__rate_limit()
        return set(self.__tidal.mix(mix_id).items())

    def get_playlist_tracks(self, playlist_id: str) -> Set[Track]:
        self.__rate_limit()
        return set(self.__tidal.playlist(playlist_id).items())

    def get_playlist_track_ids(self, playlist_id: str) -> List[str]:
        return [str(x.id) for x in self.get_playlist_tracks(playlist_id)]

    def set_playlist_tracks(self, playlist_id: str, track_ids: List[str]) -> None:
        playlist = self.__tidal.playlist(playlist_id)
        playlist.clear()
        sleep(1)
        playlist.add(track_ids, limit=len(track_ids))

    def find_equivalent_track(self, last_fm_track: LastFmTrack) -> Optional[Track]:
        if last_fm_track in self.__track_find_cache:
            return self.__track_find_cache[last_fm_track]

        fixed = self.__fix_last_fm_track(last_fm_track)

        # Build search query from artists and title
        search_artists = []
        for artist in fixed.artists:
            # Skip the original unsplit version if it contains "vs." or "versus"
            if ' vs. ' in artist.lower() or ' versus ' in artist.lower():
                continue
            # Normalize for search: remove diacritics and replace & with space
            artist_for_search = self.__remove_diacritics(artist.replace('&', ' '))
            # Keep the artist as-is mostly, just clean up for search
            if artist_for_search.lower().startswith('the '):
                search_artists.append(artist_for_search[4:])
            else:
                search_artists.append(artist_for_search)

        # Normalize title for search - remove diacritics
        title_for_search = self.__remove_diacritics(fixed.title)
        query = ' '.join(search_artists) + ' ' + title_for_search
        self.__rate_limit()
        results = self.__tidal.search(query, models=[Track])['tracks']
        various_artists_versions = []
        regular_versions = []

        for result in results:
            track_artists = {artist.name for artist in result.artists}
            if not any(self.__artists_match(artist, track_artists) for artist in fixed.artists):
                continue

            album = self.__get_album(str(result.album.id))

            album_artists = {artist.name for artist in album.artists}

            if not track_artists & album_artists:
                various_artists_versions.append(result)
                continue

            # Check if the album artist matches our search artist (prefer originals over covers)
            if any(self.__artists_match(artist, album_artists) for artist in fixed.artists):
                # This is likely the original version
                self.__track_find_cache[last_fm_track] = result
                return result
            else:
                # This might be a cover or tribute album
                regular_versions.append(result)

        # Return regular versions if we have them (non-Various Artists albums)
        if regular_versions:
            self.__track_find_cache[last_fm_track] = regular_versions[0]
            return regular_versions[0]

        # Otherwise return Various Artists compilations
        if various_artists_versions:
            self.__track_find_cache[last_fm_track] = various_artists_versions[0]
            return various_artists_versions[0]

        self.__track_find_cache[last_fm_track] = None
        return None

    def __get_album(self, album_id: str) -> Album:
        if album_id in self.__album_cache:
            return self.__album_cache[album_id]
        self.__rate_limit()
        album = self.__tidal.album(album_id)
        self.__album_cache[album_id] = album
        return album

    @staticmethod
    def __fix_last_fm_track(last_fm_track: LastFmTrack) -> LastFmTrack:
        title = last_fm_track.title
        artists = set()

        for artist in last_fm_track.artists:
            # Split on common separators, but also keep the original
            # This way we try both approaches during matching
            artists.add(artist)  # Always keep the original

            # Also try splitting on comma (for cases like "Bad Bunny, Chencho Corleone")
            if ',' in artist:
                for part in artist.split(','):
                    cleaned_part = part.strip()
                    if cleaned_part:
                        artists.add(cleaned_part)

            # Also try splitting on & (for cases like "Billy Bragg & Wilco") 
            if '&' in artist:
                for part in artist.split('&'):
                    cleaned_part = part.strip()
                    if cleaned_part:
                        artists.add(cleaned_part)
            
            # Also try splitting on "vs." or "versus" (for cases like "Mason vs. Princess Superstar")
            # But don't split if the whole artist name is just "Versus"
            if artist.lower() != 'versus' and (' vs. ' in artist.lower() or ' versus ' in artist.lower()):
                # Split on both "vs." and "versus" (case-insensitive)
                parts = re.split(r'\s+(?:vs\.?|versus)\s+', artist, flags=re.IGNORECASE)
                for part in parts:
                    cleaned_part = part.strip()
                    if cleaned_part:
                        artists.add(cleaned_part)

        # Extract artists from titles with patterns like "(Artist1 & Artist2)" or "(feat. Artist)" or "Artist1 vs. Artist2"
        collaboration_pattern = r'\s*\([^)]*(?:with|ft\.?|feat\.?|featuring|&)[^)]*\)'
        matches = re.findall(r'\(([^)]*(?:with|ft\.?|feat\.?|featuring|&)[^)]*)\)', title, re.IGNORECASE)

        for match in matches:
            # Remove collaboration keywords and extract artists
            cleaned_match = re.sub(r'(?:with|ft\.?|feat\.?|featuring)\s*', '', match, flags=re.IGNORECASE)
            artist_names = re.split(r'\s*[&,]\s*|\s+and\s+', cleaned_match)
            for artist in artist_names:
                artist = artist.strip()
                if artist:
                    artists.add(artist)

        # Remove collaboration parentheses from title
        cleaned_title = re.sub(collaboration_pattern, '', title, flags=re.IGNORECASE)
        
        # Extract artists from titles with "vs." or "versus" patterns (case-insensitive)
        # Match patterns like "Artist1 vs. Artist2" or "Artist1 versus Artist2" in the title
        vs_pattern = r'\b(\w[^()]*?)\s+(?:vs\.?|versus)\s+(\w[^()]*?)(?:\s*\(|$)'
        vs_matches = re.findall(vs_pattern, title, re.IGNORECASE)
        
        for match in vs_matches:
            # Add both artists found in the vs/versus pattern
            artist1 = match[0].strip()
            artist2 = match[1].strip()
            if artist1:
                artists.add(artist1)
            if artist2:
                artists.add(artist2)

        track_version_pattern = r'\s*\([^)]*(?:Album Version|Radio Edit|Single Version|Extended Version|Original Mix|Remix|Remastered|Explicit|Clean)\)'
        cleaned_title = re.sub(track_version_pattern, '', cleaned_title, flags=re.IGNORECASE)

        cleaned_title = cleaned_title.strip()

        return LastFmTrack(
            title=cleaned_title,
            artists=artists
        )

    @staticmethod
    def __remove_diacritics(text: str) -> str:
        nfd_form = unicodedata.normalize('NFD', text)
        return ''.join(char for char in nfd_form if unicodedata.category(char) != 'Mn')

    @staticmethod
    def __normalize_artist_name(name: str) -> str:
        if not name:
            return ''
        normalized = Tidal.__remove_diacritics(name.lower().strip())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        normalized = normalized.replace(' & ', ' and ')
        return normalized

    @staticmethod
    def __artists_match(artist: str, track_artists: Set[str]) -> bool:
        """Check if artist matches any in track_artists."""
        normalized_artist = Tidal.__normalize_artist_name(artist)

        # Also try without "the" prefix
        artist_variants = [normalized_artist]
        if normalized_artist.startswith('the '):
            artist_variants.append(normalized_artist[4:])
        else:
            artist_variants.append('the ' + normalized_artist)

        for track_artist in track_artists:
            normalized_track_artist = Tidal.__normalize_artist_name(track_artist)

            # Check if any variant matches
            if any(variant == normalized_track_artist for variant in artist_variants):
                return True
        return False
