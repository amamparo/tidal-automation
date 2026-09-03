import re
import time

import unicodedata
from collections import deque
from threading import Lock
from time import sleep
from typing import Callable, Deque, Iterable, Set, List, Optional, Dict, TypeVar, cast

from injector import inject, singleton
from requests.exceptions import (  # type: ignore[import-untyped]
    ConnectionError as RequestsConnectionError,
    HTTPError,
    Timeout,
)
from tidalapi import Session, Track, Album, Artist, UserPlaylist
from tidalapi.exceptions import TooManyRequests
from tidalapi.types import JsonObj

from src.environment import Environment
from src.last_fm import LastFmTrack


T = TypeVar('T')


MISSING_ARTIST: JsonObj = {'id': None, 'name': None}


UNSEARCHABLE_ARTIST_MARKERS = (' vs. ', ' versus ', ' feat.', ' featuring ')
ARTIST_LIST_SEPARATOR = re.compile(r'\s*[,&]\s*|\s+and\s+')
VERSUS_SEPARATOR = re.compile(r'\s+(?:vs\.?|versus)\s+', re.IGNORECASE)
FEATURING_SEPARATOR = re.compile(r'\s+(?:feat\.?|featuring)\s+', re.IGNORECASE)
COLLABORATION_PARENTHETICAL = re.compile(r'\s*\(([^)]*(?:with|ft\.?|feat\.?|featuring|&)[^)]*)\)', re.IGNORECASE)
COLLABORATION_KEYWORD = re.compile(r'(?:with|ft\.?|feat\.?|featuring)\s*', re.IGNORECASE)
TITLE_VERSUS_ARTISTS = re.compile(r'\b(\w[^()]*?)\s+(?:vs\.?|versus)\s+(\w[^()]*?)(?:\s*\(|$)', re.IGNORECASE)
TRACK_VERSION_SUFFIX = re.compile(
    r'\s*\((?:Album Version|Radio Edit|Single Version|Extended Version|Original Mix|Remastered|Explicit|Clean)\)',
    re.IGNORECASE,
)
GENERIC_REMIX_SUFFIX = re.compile(r'\s*\((?:Remix|Mix)\)', re.IGNORECASE)
DASH_REMASTER_SUFFIX = re.compile(r'\s*-\s*\d{4}\s+Remaster(?:ed)?', re.IGNORECASE)
TITLE_NOISE_SUFFIXES = (COLLABORATION_PARENTHETICAL, TRACK_VERSION_SUFFIX, GENERIC_REMIX_SUFFIX, DASH_REMASTER_SUFFIX)


class NullArtistTolerantSession(Session):
    def parse_artist(self, obj: JsonObj) -> Artist:
        return super().parse_artist(obj or MISSING_ARTIST)

    def parse_artists(self, obj: List[JsonObj]) -> List[Artist]:
        return super().parse_artists(obj or [MISSING_ARTIST])


@singleton
class Tidal:
    @inject
    def __init__(self, environment: Environment) -> None:
        self.__tidal = NullArtistTolerantSession()
        self.__tidal.token_refresh(environment.require('TIDAL_REFRESH_TOKEN'))
        self.__tidal.load_oauth_session('Bearer', cast(str, self.__tidal.access_token))
        self.__track_find_cache: Dict[LastFmTrack, Optional[Track]] = {}
        self.__album_cache: Dict[str, Album] = {}

        self.__max_requests_per_second = 2
        self.__request_times: Deque[float] = deque(maxlen=self.__max_requests_per_second)
        self.__rate_limit_lock = Lock()

    def __rate_limit(self) -> None:
        with self.__rate_limit_lock:
            now = time.time()
            while self.__request_times and self.__request_times[0] < now - 1.0:
                self.__request_times.popleft()
            if len(self.__request_times) >= self.__max_requests_per_second:
                sleep_time = 1.0 - (now - self.__request_times[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    now = time.time()
            self.__request_times.append(now)

    def __call_api(self, fn: Callable[[], T]) -> T:
        max_attempts = 10
        for attempt in range(max_attempts):
            self.__rate_limit()
            try:
                return fn()
            except TooManyRequests as e:
                if attempt == max_attempts - 1:
                    raise
                if e.retry_after > 0:
                    sleep_time = float(e.retry_after) + 1.0
                else:
                    sleep_time = min(60.0, 2 ** (attempt + 1))
                time.sleep(sleep_time)
            except (RequestsConnectionError, Timeout):
                if attempt == max_attempts - 1:
                    raise
                time.sleep(min(30.0, 2 ** attempt))
        raise RuntimeError('unreachable')

    def get_mix_tracks(self, mix_id: str) -> Set[Track]:
        items = self.__call_api(lambda: self.__tidal.mix(mix_id).items())
        return {item for item in items if isinstance(item, Track)}

    def get_playlist_tracks(self, playlist_id: str) -> Set[Track]:
        items = self.__call_api(lambda: self.__tidal.playlist(playlist_id).items())
        return {item for item in items if isinstance(item, Track)}

    def set_playlist_tracks(self, playlist_id: str, track_ids: List[str]) -> None:
        max_attempts = 5
        for attempt in range(max_attempts):
            playlist = cast(UserPlaylist, self.__call_api(lambda: self.__tidal.playlist(playlist_id)))
            try:
                self.__call_api(playlist.clear)
                break
            except HTTPError as e:
                if (e.response is None or e.response.status_code != 412
                        or attempt == max_attempts - 1):
                    raise
                sleep(min(10.0, 2 ** attempt))
        sleep(1)
        playlist = cast(UserPlaylist, self.__call_api(lambda: self.__tidal.playlist(playlist_id)))
        self.__call_api(lambda: playlist.add(track_ids, limit=len(track_ids)))

    def find_equivalent_track(self, last_fm_track: LastFmTrack) -> Optional[Track]:
        if last_fm_track in self.__track_find_cache:
            return self.__track_find_cache[last_fm_track]

        fixed = self.__fix_last_fm_track(last_fm_track)
        query = self.__search_query(fixed)
        results = self.__call_api(lambda: self.__tidal.search(query, models=[Track])['tracks'])
        match = self.__best_match(fixed, results)

        self.__track_find_cache[last_fm_track] = match
        return match

    def __best_match(self, searched: LastFmTrack, results: List[Track]) -> Optional[Track]:
        various_artists_versions: List[Track] = []
        alternate_versions: List[Track] = []

        for result in results:
            if not self.__titles_match(searched.title, result.name or ''):
                continue
            track_artists = {artist.name for artist in result.artists or []}
            if not self.__artists_match(searched.artists, track_artists):
                continue

            album = self.__get_album(str(cast(Album, result.album).id))
            album_artists = {artist.name for artist in album.artists or []}

            if not track_artists & album_artists:
                various_artists_versions.append(result)
            elif self.__is_original_version(searched.artists, result, album_artists):
                return result
            else:
                alternate_versions.append(result)

        if alternate_versions:
            return alternate_versions[0]
        if various_artists_versions:
            return various_artists_versions[0]
        return None

    @staticmethod
    def __is_original_version(
        searched_artists: Set[str], result: Track, album_artists: Set[Optional[str]],
    ) -> bool:
        if not Tidal.__artists_match(searched_artists, album_artists):
            return False
        if not result.artists:
            return False
        return Tidal.__artists_match(searched_artists, {result.artists[0].name})

    @staticmethod
    def __search_query(searched: LastFmTrack) -> str:
        search_artists = []
        for artist in searched.artists:
            artist_lower = artist.lower()
            if any(marker in artist_lower for marker in UNSEARCHABLE_ARTIST_MARKERS):
                continue
            searchable = Tidal.__remove_diacritics(artist.replace('&', ' '))
            search_artists.append(searchable[4:] if searchable.lower().startswith('the ') else searchable)
        return ' '.join(search_artists) + ' ' + Tidal.__remove_diacritics(searched.title)

    def __get_album(self, album_id: str) -> Album:
        if album_id in self.__album_cache:
            return self.__album_cache[album_id]
        album = self.__call_api(lambda: self.__tidal.album(album_id))
        self.__album_cache[album_id] = album
        return album

    @staticmethod
    def __fix_last_fm_track(last_fm_track: LastFmTrack) -> LastFmTrack:
        artists: Set[str] = set()
        for artist in last_fm_track.artists:
            artists |= Tidal.__artist_name_variants(artist)
        artists |= Tidal.__artists_named_in_title(last_fm_track.title)
        return LastFmTrack(
            title=Tidal.__clean_title(last_fm_track.title),
            artists=artists
        )

    @staticmethod
    def __artist_name_variants(artist: str) -> Set[str]:
        variants = {artist}
        for separator in (',', '&'):
            if separator in artist:
                variants |= Tidal.__stripped_parts(artist.split(separator))

        artist_lower = artist.lower()
        if ' vs. ' in artist_lower or ' versus ' in artist_lower:
            variants |= Tidal.__stripped_parts(VERSUS_SEPARATOR.split(artist))

        if FEATURING_SEPARATOR.search(artist):
            for part in FEATURING_SEPARATOR.split(artist):
                variants |= Tidal.__stripped_parts(ARTIST_LIST_SEPARATOR.split(part))
        return variants

    @staticmethod
    def __artists_named_in_title(title: str) -> Set[str]:
        artists = set()
        for collaboration in COLLABORATION_PARENTHETICAL.findall(title):
            named_artists = COLLABORATION_KEYWORD.sub('', collaboration)
            artists |= Tidal.__stripped_parts(ARTIST_LIST_SEPARATOR.split(named_artists))
        for versus_artists in TITLE_VERSUS_ARTISTS.findall(title):
            artists |= Tidal.__stripped_parts(versus_artists)
        return artists

    @staticmethod
    def __clean_title(title: str) -> str:
        cleaned = title
        for noise in TITLE_NOISE_SUFFIXES:
            cleaned = noise.sub('', cleaned)
        return cleaned.strip()

    @staticmethod
    def __stripped_parts(parts: Iterable[str]) -> Set[str]:
        return {stripped for stripped in (part.strip() for part in parts) if stripped}

    @staticmethod
    def __normalize_title(title: str) -> str:
        no_diacritics = Tidal.__remove_diacritics(title.lower())
        return re.sub(r'[^a-z0-9]+', ' ', no_diacritics).strip()

    @staticmethod
    def __titles_match(searched: str, candidate: str) -> bool:
        a = Tidal.__normalize_title(searched)
        b = Tidal.__normalize_title(candidate)
        if not a or not b:
            return False
        return a == b or a in b or b in a

    @staticmethod
    def __remove_diacritics(text: str) -> str:
        nfd_form = unicodedata.normalize('NFD', text)
        return ''.join(char for char in nfd_form if unicodedata.category(char) != 'Mn')

    @staticmethod
    def __normalize_artist_name(name: Optional[str]) -> str:
        if not name:
            return ''
        normalized = Tidal.__remove_diacritics(name.lower().strip())
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized.replace(' & ', ' and ')

    @staticmethod
    def __artists_match(searched_artists: Set[str], candidates: Set[Optional[str]]) -> bool:
        normalized_candidates = {Tidal.__normalize_artist_name(candidate) for candidate in candidates}
        for artist in searched_artists:
            normalized = Tidal.__normalize_artist_name(artist)
            toggled_the = normalized[4:] if normalized.startswith('the ') else 'the ' + normalized
            if {normalized, toggled_the} & normalized_candidates:
                return True
        return False
