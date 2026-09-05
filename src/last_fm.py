import re
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import sleep, time
from typing import Deque, Dict, List, Set

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

    def top_tags(self, artist: str) -> Dict[str, float]:
        cached = self.__tags.get(artist.lower())
        if cached is not None:
            return cached
        tags = self.__fetch_tags(artist)
        lead = CREDITED_GUEST.sub('', artist).strip()
        if not tags and lead and lead.lower() != artist.lower():
            tags = self.__fetch_tags(lead)
        self.__tags[artist.lower()] = tags
        return tags

    def __fetch_tags(self, artist: str) -> Dict[str, float]:
        self.__rate_limit()
        try:
            response = self.__session.get(API_URL, timeout=REQUEST_TIMEOUT, params={
                'method': 'artist.gettoptags', 'artist': artist, 'format': 'json', 'autocorrect': '1',
                'api_key': self.__environment.require('LASTFM_API_KEY'),
            })
            response.raise_for_status()
            tags = response.json().get('toptags', {}).get('tag', [])
        except (requests.RequestException, ValueError):
            return {}
        return {tag['name'].lower(): tag['count'] / TAG_COUNT_SCALE for tag in tags if tag.get('count')}

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
