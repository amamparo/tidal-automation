import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from random import shuffle
from typing import Dict, Iterator, List, Optional, Tuple

import requests  # type: ignore[import-untyped]
from injector import inject
from tqdm import tqdm

from src.environment import Environment
from src.tidal import Tidal, TidalTrack


TIMESTAMP_PATTERN = re.compile(r'\(?\d{1,2}(?::\d{2}){1,2}\)?')
LEADING_NUMBER = re.compile(r'^\s*\d+\.\s*')


@dataclass
class VideoTracks:
    video_url: str
    artist: str
    tidal_tracks: List[TidalTrack]


def parse_songs(description: str) -> List[str]:
    songs: List[str] = []
    for raw in description.splitlines():
        line = raw.strip()
        if not TIMESTAMP_PATTERN.search(line):
            continue
        song = TIMESTAMP_PATTERN.sub('', line)
        song = LEADING_NUMBER.sub('', song)
        song = song.strip(' -\u2013\u2014:"\u201c\u201d\'\t')
        song = re.sub(r'\s+ft\.?\s.*$', '', song, flags=re.IGNORECASE)
        song = re.sub(r'\s+feat\.?\s.*$', '', song, flags=re.IGNORECASE)
        song = song.strip()
        if song:
            songs.append(song)
    return songs


class YoutubeChannel(ABC):
    API_BASE = 'https://www.googleapis.com/youtube/v3'
    PAGE_SIZE = 50
    CHANNEL_HANDLE: str = ''
    REJECT_TITLE_PATTERN: Optional[re.Pattern] = None

    @inject
    def __init__(self, environment: Environment, tidal: Tidal) -> None:
        self._api_key = environment.get('YOUTUBE_API_KEY')
        self._tidal = tidal

    @abstractmethod
    def _extract(self, title: str, description: str) -> Optional[Tuple[str, List[str]]]:
        ...

    def fetch(self) -> Iterator[VideoTracks]:
        uploads_id = self._get_uploads_playlist_id()
        page_token: Optional[str] = None
        while True:
            params = {
                'part': 'snippet',
                'playlistId': uploads_id,
                'maxResults': self.PAGE_SIZE,
                'key': self._api_key,
            }
            if page_token:
                params['pageToken'] = page_token
            response = self._get('/playlistItems', params)
            for item in response.get('items', []):
                snippet = item.get('snippet') or {}
                extracted = self._extract(
                    snippet.get('title') or '',
                    snippet.get('description') or '',
                )
                if extracted is None:
                    continue
                artist, songs = extracted
                video_id = (snippet.get('resourceId') or {}).get('videoId') or ''
                if not video_id:
                    continue
                tidal_tracks = [
                    t for t in (
                        self._tidal.find_tidal_track(artist, song, reject_title=self.REJECT_TITLE_PATTERN)
                        for song in songs
                    )
                    if t is not None
                ]
                yield VideoTracks(
                    video_url=f'https://www.youtube.com/watch?v={video_id}',
                    artist=artist,
                    tidal_tracks=tidal_tracks,
                )
            page_token = response.get('nextPageToken')
            if not page_token:
                break

    def _get_uploads_playlist_id(self) -> str:
        response = self._get('/channels', {
            'part': 'contentDetails',
            'forHandle': self.CHANNEL_HANDLE,
            'key': self._api_key,
        })
        return response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    def _get(self, path: str, params: dict) -> dict:
        response = requests.get(f'{self.API_BASE}{path}', params=params, timeout=30)
        response.raise_for_status()
        return response.json()


class Kexp(YoutubeChannel):
    CHANNEL_HANDLE = '@kexp'

    def _extract(self, title: str, description: str) -> Optional[Tuple[str, List[str]]]:
        songs = parse_songs(description)
        if len(songs) < 2:
            return None
        artist = title.split(' - ', 1)[0].strip()
        if not artist:
            return None
        return artist, songs


class Kcrw(YoutubeChannel):
    CHANNEL_HANDLE = '@kcrw'
    TITLE_SEP = re.compile(r'\s+-\s+|\s*[:|\u2013]\s*')
    SUFFIX_PATTERN = re.compile(
        r"'?s?\s+(?:Amazing|Stunning|Powerful|Captivating|Full|Special|KCRW|Live|\d{4})\b.*$",
        re.IGNORECASE,
    )
    POSSESSIVE = re.compile(r"['\u2019`]s?$")

    def _extract(self, title: str, description: str) -> Optional[Tuple[str, List[str]]]:
        if 'Live' not in title and 'Performance' not in title:
            return None
        songs = parse_songs(description)
        if len(songs) < 2:
            return None
        artist = self.__parse_artist(title)
        if not artist:
            return None
        return artist, songs

    @classmethod
    def __parse_artist(cls, title: str) -> str:
        head = cls.TITLE_SEP.split(title, maxsplit=1)[0]
        head = cls.SUFFIX_PATTERN.sub('', head).strip()
        head = cls.POSSESSIVE.sub('', head).strip()
        head = head.strip(' \t-\u2013\u2014:;|.,!?')
        return head


class Colors(YoutubeChannel):
    CHANNEL_HANDLE = '@COLORSxSTUDIOS'
    TITLE_PATTERN = re.compile(r'^(.+?)\s+-\s+(.+?)\s*\|\s*A COLORS\b', re.IGNORECASE)
    REJECT_TITLE_PATTERN = re.compile(r'\bA COLORS\b', re.IGNORECASE)

    def _extract(self, title: str, description: str) -> Optional[Tuple[str, List[str]]]:
        match = self.TITLE_PATTERN.match(title)
        if not match:
            return None
        artist = match.group(1).strip()
        song = match.group(2).strip()
        if not artist or not song:
            return None
        return artist, [song]


def build_playlist(
    tidal: Tidal, channel: YoutubeChannel, playlist_name: str, target_size: int,
    pool_by_artist: bool = True,
) -> None:
    selected_track_ids: List[str] = []
    seen_track_ids: set[str] = set()
    artist_pool: Dict[str, List[TidalTrack]] = {}

    with tqdm(total=target_size, desc=f'Building {playlist_name} playlist') as progress:
        progress.write(f'Fetching {playlist_name} channel listing...')
        for video_tracks in channel.fetch():
            if len(selected_track_ids) >= target_size:
                break
            if pool_by_artist:
                key = video_tracks.artist.strip().lower()
                pool = artist_pool.get(key, []) + video_tracks.tidal_tracks
                artist_pool[key] = pool
            else:
                pool = video_tracks.tidal_tracks
            progress.write(
                f'> {video_tracks.artist} ({len(video_tracks.tidal_tracks)} new, {len(pool)} total) '
                f'{video_tracks.video_url}'
            )
            picked = tidal.pick_by_popularity(pool)
            if picked is None:
                progress.write(f'\033[91m✗ No Tidal match for {video_tracks.video_url}\033[0m')
                continue
            if picked.track_id in seen_track_ids:
                progress.write(f'\033[93m· duplicate pick, skipping: {picked.title}\033[0m')
                continue
            seen_track_ids.add(picked.track_id)
            selected_track_ids.append(picked.track_id)
            progress.write(
                f'\033[92m✓ {picked.title} - {picked.artist} (popularity {picked.popularity})\033[0m'
            )
            progress.update(1)

    shuffle(selected_track_ids)
    playlist_id = tidal.get_or_create_playlist_id(playlist_name)
    tidal.set_playlist_tracks(playlist_id, selected_track_ids)
