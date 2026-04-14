import re
from dataclasses import dataclass
from typing import Iterator, List, Optional

import requests  # type: ignore[import-untyped]
from injector import inject

from src.environment import Environment


@dataclass
class KexpPerformance:
    artist: str
    songs: List[str]


class Kexp:
    API_BASE = 'https://www.googleapis.com/youtube/v3'
    CHANNEL_HANDLE = '@kexp'
    PAGE_SIZE = 50

    @inject
    def __init__(self, environment: Environment) -> None:
        self.__api_key = environment.get('YOUTUBE_API_KEY')

    def iter_performances(self) -> Iterator[KexpPerformance]:
        uploads_playlist_id = self.__get_uploads_playlist_id()
        page_token: Optional[str] = None
        while True:
            params = {
                'part': 'snippet',
                'playlistId': uploads_playlist_id,
                'maxResults': self.PAGE_SIZE,
                'key': self.__api_key,
            }
            if page_token:
                params['pageToken'] = page_token
            response = self.__get('/playlistItems', params)
            for item in response.get('items', []):
                snippet = item.get('snippet') or {}
                songs = self.__parse_songs(snippet.get('description') or '')
                if not songs:
                    continue
                title = snippet.get('title') or ''
                artist = title.split(' - ', 1)[0].strip()
                if artist:
                    yield KexpPerformance(artist=artist, songs=songs)
            page_token = response.get('nextPageToken')
            if not page_token:
                break

    def __get_uploads_playlist_id(self) -> str:
        response = self.__get('/channels', {
            'part': 'contentDetails',
            'forHandle': self.CHANNEL_HANDLE,
            'key': self.__api_key,
        })
        return response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

    def __get(self, path: str, params: dict) -> dict:
        response = requests.get(f'{self.API_BASE}{path}', params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def __parse_songs(description: str) -> List[str]:
        timestamp_pattern = re.compile(r'\(?\d{1,2}(?::\d{2}){1,2}\)?')
        songs: List[str] = []
        for raw in description.splitlines():
            line = raw.strip()
            if not timestamp_pattern.search(line):
                continue
            song = timestamp_pattern.sub('', line).strip(' -–—\t')
            song = re.sub(r'\s+ft\.?\s.*$', '', song, flags=re.IGNORECASE)
            song = re.sub(r'\s+feat\.?\s.*$', '', song, flags=re.IGNORECASE)
            if song:
                songs.append(song)
        return songs if len(songs) >= 2 else []
