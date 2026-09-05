import re
import time
import unicodedata
from collections import deque
from functools import partial
from threading import Lock
from typing import Callable, Deque, Dict, Iterable, List, Optional, Set, Tuple, TypeVar, cast

from injector import inject, singleton
from requests.exceptions import (  # type: ignore[import-untyped]
    ConnectionError as RequestsConnectionError,
    HTTPError,
    Timeout,
)
from tidalapi import Session, Track, Album, Artist, Playlist, UserPlaylist
from tidalapi.exceptions import TooManyRequests
from tidalapi.types import JsonObj

from src.environment import Environment
from src.last_fm import LastFmTrack


T = TypeVar('T')


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
VERSION_MARKER = re.compile(r'[\(\[]([^)\]]*)[\)\]]')
NEUTRAL_VERSION_MARKER = re.compile(
    r'^(?:original(?:\s+(?:mix|version))?|album\s+version|single\s+version|'
    r'(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?|explicit|clean|stereo|mono|'
    r'feat\.?|ft\.?|featuring|with|w/)\b',
    re.IGNORECASE,
)
LIVE_PARENTHETICAL = re.compile(
    r'\s*[\(\[]live\b(?:\s*(?:at|from|in|@)\b[^)\]]*|\s*(?:pa|set|mix|dub|version|edit|take|recording)\b\s*)?[\)\]]',
    re.IGNORECASE,
)
LIVE_MARKER = re.compile(
    r'^live\b\s*(?:(?:at|from|in|@)\b.*|(?:pa|set|mix|dub|version|edit|take|recording)\b\s*)?$',
    re.IGNORECASE,
)
VERSION_NOUN = re.compile(
    r'\b(?:remix|rmx|edit|dub|mix|version|rework|refix|reshape|retouch|reassembly|reprise|'
    r'revision|interpretation|flip|treatment|remake|vip|bootleg|instrumental|acapella|live|'
    r'extended|radio)\b',
    re.IGNORECASE,
)
DASH_REMASTER_SUFFIX = re.compile(r'\s*-\s*\d{4}\s+Remaster(?:ed)?', re.IGNORECASE)
TITLE_NOISE_SUFFIXES = (COLLABORATION_PARENTHETICAL, TRACK_VERSION_SUFFIX, GENERIC_REMIX_SUFFIX,
                        DASH_REMASTER_SUFFIX, LIVE_PARENTHETICAL)
MINIMUM_REMIXER_NAME_LENGTH = 3


PLAYLIST_PAGE_SIZE = 100

MISSING_ARTIST: JsonObj = {'id': None, 'name': None}


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
        self.__track_find_cache: Dict[Tuple[LastFmTrack, bool], Optional[Track]] = {}
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
        playlist = self.__call_api(lambda: self.__tidal.playlist(playlist_id))
        return set(self.__playlist_tracks(playlist))

    def __playlist_tracks(self, playlist: Playlist) -> List[Track]:
        tracks: List[Track] = []
        offset = 0
        while True:
            page = self.__call_api(partial(playlist.items, limit=PLAYLIST_PAGE_SIZE, offset=offset))
            tracks.extend(item for item in page if isinstance(item, Track))
            offset += len(page)
            if len(page) < PLAYLIST_PAGE_SIZE:
                return tracks

    def set_playlist_tracks(self, playlist_id: str, track_ids: List[str]) -> None:
        wanted = set(track_ids)
        max_attempts = 5
        for attempt in range(max_attempts):
            playlist = cast(UserPlaylist, self.__call_api(lambda: self.__tidal.playlist(playlist_id)))
            existing = [str(track.id) for track in self.__playlist_tracks(playlist)]
            departing = [index for index, track_id in enumerate(existing) if track_id not in wanted]
            try:
                if departing:
                    self.__call_api(partial(playlist.remove_by_indices, departing))
                break
            except HTTPError as e:
                precondition_failed = e.response is not None and e.response.status_code == 412
                if not precondition_failed or attempt == max_attempts - 1:
                    raise
                time.sleep(min(10.0, 2 ** attempt))
        time.sleep(1)
        playlist = cast(UserPlaylist, self.__call_api(lambda: self.__tidal.playlist(playlist_id)))
        surviving = {str(track.id) for track in self.__playlist_tracks(playlist)}
        arriving = [track_id for track_id in track_ids if track_id not in surviving]
        if arriving:
            self.__call_api(lambda: playlist.add(arriving, limit=len(arriving)))

    def find_equivalent_track(self, last_fm_track: LastFmTrack, match_version: bool = False) -> Optional[Track]:
        cache_key = (last_fm_track, match_version)
        if cache_key in self.__track_find_cache:
            return self.__track_find_cache[cache_key]

        fixed = self.__fix_last_fm_track(last_fm_track)
        query = self.__search_query(fixed)
        results = self.__call_api(lambda: self.__tidal.search(query, models=[Track])['tracks'])
        match = self.__best_match(fixed, results, last_fm_track.title if match_version else None)

        self.__track_find_cache[cache_key] = match
        return match

    def __best_match(self, searched: LastFmTrack, results: List[Track],
                     versioned_title: Optional[str]) -> Optional[Track]:
        various_artists_versions: List[Track] = []
        alternate_versions: List[Track] = []

        for result in results:
            if versioned_title is not None and not self.__versions_match(versioned_title, result):
                continue
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
    def __is_original_version(searched_artists: Set[str], result: Track, album_artists: Set[Optional[str]]) -> bool:
        if not Tidal.__artists_match(searched_artists, album_artists):
            return False
        if not result.artists:
            return False
        return Tidal.__artists_match(searched_artists, {result.artists[0].name})

    def __get_album(self, album_id: str) -> Album:
        if album_id in self.__album_cache:
            return self.__album_cache[album_id]
        album = self.__call_api(lambda: self.__tidal.album(album_id))
        self.__album_cache[album_id] = album
        return album

    @staticmethod
    def __search_query(searched: LastFmTrack) -> str:
        search_artists = []
        for artist in searched.artists:
            artist_lower = artist.lower()
            if any(marker in artist_lower for marker in UNSEARCHABLE_ARTIST_MARKERS):
                continue
            searchable = Tidal.__remove_diacritics(artist.replace('&', ' '))
            if searchable.lower().startswith('the '):
                searchable = searchable[4:]
            search_artists.append(searchable)
        return ' '.join(search_artists) + ' ' + Tidal.__remove_diacritics(searched.title)

    @staticmethod
    def __fix_last_fm_track(last_fm_track: LastFmTrack) -> LastFmTrack:
        artists: Set[str] = set()
        for artist in last_fm_track.artists:
            artists |= Tidal.__artist_name_variants(artist)
        artists |= Tidal.__artists_named_in_title(last_fm_track.title)
        return LastFmTrack(title=Tidal.__clean_title(last_fm_track.title), artists=artists)

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
        artists: Set[str] = set()
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
    def __remove_diacritics(text: str) -> str:
        nfd_form = unicodedata.normalize('NFD', text)
        return ''.join(char for char in nfd_form if unicodedata.category(char) != 'Mn')

    @staticmethod
    def __normalize_title(title: str) -> str:
        no_diacritics = Tidal.__remove_diacritics(title.lower())
        return re.sub(r'[^a-z0-9]+', ' ', no_diacritics).strip()

    @staticmethod
    def __titles_match(searched: str, candidate: str) -> bool:
        normalized_searched = Tidal.__normalize_title(searched)
        normalized_candidate = Tidal.__normalize_title(candidate)
        if not normalized_searched or not normalized_candidate:
            return False
        return normalized_searched in normalized_candidate or normalized_candidate in normalized_searched

    @staticmethod
    def __version_markers(title: str) -> Set[str]:
        markers = (marker.strip() for marker in VERSION_MARKER.findall(title))
        return {Tidal.__normalize_title(marker) for marker in markers
                if marker and not NEUTRAL_VERSION_MARKER.match(marker) and not LIVE_MARKER.match(marker)}

    @staticmethod
    def __versions_match(searched_title: str, result: Track) -> bool:
        searched = Tidal.__version_markers(searched_title)
        candidate = Tidal.__version_markers(result.name or '')
        if result.version:
            candidate |= Tidal.__version_markers(f'({result.version})')
        if searched == candidate:
            return True
        if candidate - searched:
            return False
        credited = {Tidal.__normalize_artist_name(artist.name) for artist in (result.artists or [])}
        remixers = {Tidal.__normalize_title(VERSION_NOUN.sub(' ', marker)) for marker in searched - candidate}
        remixers = {remixer for remixer in remixers if len(remixer) >= MINIMUM_REMIXER_NAME_LENGTH}
        return bool(remixers) and all(
            any(remixer in artist for artist in credited) for remixer in remixers
        )

    @staticmethod
    def __normalize_artist_name(name: Optional[str]) -> str:
        if not name:
            return ''
        without_diacritics = Tidal.__remove_diacritics(name.lower())
        normalized = re.sub(r'\s+', ' ', without_diacritics).strip()
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
