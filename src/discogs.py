from collections import Counter
from threading import Lock
from time import monotonic, sleep
from typing import Dict

import requests  # type: ignore[import-untyped]
from injector import inject, singleton

from src.environment import Environment

API_URL = 'https://api.discogs.com/database/search'
USER_AGENT = 'tidal-automation/1.0 (+https://github.com/amamparo/tidal-automation)'
REQUEST_TIMEOUT = (5.0, 30.0)
MASTERS_PER_ARTIST = 10
ANONYMOUS_REQUESTS_PER_MINUTE = 25
AUTHENTICATED_REQUESTS_PER_MINUTE = 60


@singleton
class Discogs:
    @inject
    def __init__(self, environment: Environment) -> None:
        token = environment.get('DISCOGS_TOKEN')
        self.__session = requests.Session()
        self.__session.headers.update({'User-Agent': USER_AGENT})
        if token:
            self.__session.headers.update({'Authorization': f'Discogs token={token}'})
        requests_per_minute = AUTHENTICATED_REQUESTS_PER_MINUTE if token else ANONYMOUS_REQUESTS_PER_MINUTE
        self.seconds_per_request = 60.0 / requests_per_minute
        self.__styles: Dict[str, Dict[str, float]] = {}
        self.__next_request_at = 0.0
        self.__rate_limit_lock = Lock()

    def styles(self, artist: str) -> Dict[str, float]:
        cache_key = artist.lower()
        if cache_key not in self.__styles:
            self.__styles[cache_key] = self.__fetch_styles(artist)
        return self.__styles[cache_key]

    def __fetch_styles(self, artist: str) -> Dict[str, float]:
        self.__rate_limit()
        try:
            response = self.__session.get(API_URL, timeout=REQUEST_TIMEOUT, params={
                'artist': artist, 'type': 'master', 'per_page': MASTERS_PER_ARTIST,
            })
            response.raise_for_status()
            masters = response.json().get('results', [])
        except (requests.RequestException, ValueError):
            return {}
        counts = Counter(style for master in masters for style in (master.get('style') or []))
        return {style.lower(): float(count) for style, count in counts.items()}

    def __rate_limit(self) -> None:
        with self.__rate_limit_lock:
            pause = self.__next_request_at - monotonic()
            if pause > 0:
                sleep(pause)
            self.__next_request_at = monotonic() + self.seconds_per_request
