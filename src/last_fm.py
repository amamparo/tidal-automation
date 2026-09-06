import re
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import sleep, time
from typing import Any, Deque, Dict, List, Set

import requests  # type: ignore[import-untyped]
from injector import inject, singleton

from src.environment import Environment

API_URL = 'https://ws.audioscrobbler.com/2.0/'
REQUEST_TIMEOUT = (5.0, 30.0)
REQUESTS_PER_SECOND = 5
TAG_COUNT_SCALE = 100.0
CREDITED_GUEST = re.compile(r'\s+(?:feat\.?|featuring|ft\.?|vs\.?|versus|with|&)\s+.*$', re.IGNORECASE)


@dataclass
class LastFmTrack:
    title: str
    artists: Set[str]

    def __hash__(self) -> int:
        return hash((self.title, tuple(sorted(self.artists))))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LastFmTrack) and self.title == other.title and self.artists == other.artists


@singleton
class LastFm:
    @inject
    def __init__(self, environment: Environment) -> None:
        self.__environment = environment
        self.__session = requests.Session()
        self.__tags: Dict[str, Dict[str, float]] = {}
        self.__request_times: Deque[float] = deque(maxlen=REQUESTS_PER_SECOND)
        self.__rate_limit_lock = Lock()

    def get_mix(self, mix_type: str) -> List[LastFmTrack]:
        url = f'https://www.last.fm/player/station/user/amamparo/{mix_type}?page=1&ajax=1'
        playlist = requests.get(url, timeout=None).json()['playlist']
        return [LastFmTrack(title=x['name'], artists={a['name'] for a in x['artists']}) for x in playlist]

    @property
    def seconds_per_request(self) -> float:
        return 1.0 / REQUESTS_PER_SECOND

    def top_artists(self, tag: str, limit: int) -> List[str]:
        artists = self.__get('tag.gettopartists', tag=tag, limit=str(limit)).get('topartists', {}).get('artist', [])
        return [artist['name'] for artist in artists if artist.get('name')]

    def top_tags(self, artist: str) -> Dict[str, float]:
        cache_key = artist.lower()
        if cache_key not in self.__tags:
            self.__tags[cache_key] = self.__fetch_tags(artist) or self.__fetch_lead_artist_tags(artist)
        return self.__tags[cache_key]

    def __fetch_lead_artist_tags(self, artist: str) -> Dict[str, float]:
        lead = CREDITED_GUEST.sub('', artist).strip()
        if not lead or lead.lower() == artist.lower():
            return {}
        return self.__fetch_tags(lead)

    def __fetch_tags(self, artist: str) -> Dict[str, float]:
        tags = self.__get('artist.gettoptags', artist=artist, autocorrect='1').get('toptags', {}).get('tag', [])
        return {tag['name'].lower(): tag['count'] / TAG_COUNT_SCALE for tag in tags if tag.get('count')}

    def __get(self, method: str, **params: str) -> Dict[str, Any]:
        self.__rate_limit()
        try:
            response = self.__session.get(API_URL, timeout=REQUEST_TIMEOUT, params={
                'method': method, 'format': 'json',
                'api_key': self.__environment.require('LASTFM_API_KEY'), **params,
            })
            response.raise_for_status()
            body: Dict[str, Any] = response.json()
        except (requests.RequestException, ValueError):
            return {}
        return body

    def __rate_limit(self) -> None:
        with self.__rate_limit_lock:
            now = time()
            while self.__request_times and self.__request_times[0] < now - 1.0:
                self.__request_times.popleft()
            if len(self.__request_times) >= REQUESTS_PER_SECOND:
                pause = 1.0 - (now - self.__request_times[0])
                if pause > 0:
                    sleep(pause)
                    now = time()
            self.__request_times.append(now)
