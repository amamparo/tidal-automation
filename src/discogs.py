from collections import Counter
from threading import Lock
from time import monotonic, sleep
from typing import Callable, Dict, Optional

import requests  # type: ignore[import-untyped]
from injector import inject, singleton

from src.environment import Environment

API_URL = 'https://api.discogs.com/database/search'
USER_AGENT = 'tidal-automation/1.0 (+https://github.com/amamparo/tidal-automation)'
REQUEST_TIMEOUT = (5.0, 30.0)
RELEASES_PER_ARTIST = 10
ANONYMOUS_REQUESTS_PER_MINUTE = 25
AUTHENTICATED_REQUESTS_PER_MINUTE = 60
LAMBDA_CEILING_SECONDS = 900.0


@singleton
class Discogs:
    @inject
    def __init__(self, environment: Environment) -> None:
        self.__token = environment.get('DISCOGS_TOKEN')
        self.__session = requests.Session()
        self.__session.headers.update({'User-Agent': USER_AGENT})
        if self.__token:
            self.__session.headers.update({'Authorization': f'Discogs token={self.__token}'})
        self.__styles: Dict[str, Dict[str, float]] = {}
        self.__next_request_at = 0.0
        self.__rate_limit_lock = Lock()

    @property
    def seconds_per_request(self) -> float:
        per_minute = AUTHENTICATED_REQUESTS_PER_MINUTE if self.__token else ANONYMOUS_REQUESTS_PER_MINUTE
        return 60.0 / per_minute

    def styles(self, artist: str) -> Dict[str, float]:
        cached = self.__styles.get(artist.lower())
        if cached is not None:
            return cached
        found = self.__fetch_styles(artist)
        self.__styles[artist.lower()] = found
        return found

    def __fetch_styles(self, artist: str) -> Dict[str, float]:
        self.__rate_limit()
        try:
            response = self.__session.get(API_URL, timeout=REQUEST_TIMEOUT, params={
                'artist': artist, 'type': 'release', 'per_page': RELEASES_PER_ARTIST,
            })
            response.raise_for_status()
            releases = response.json().get('results', [])
        except (requests.RequestException, ValueError):
            return {}
        counts = Counter(style for release in releases for style in (release.get('style') or []))
        return {style.lower(): float(count) for style, count in counts.items()}

    def __rate_limit(self) -> None:
        with self.__rate_limit_lock:
            pause = self.__next_request_at - monotonic()
            if pause > 0:
                sleep(pause)
            self.__next_request_at = monotonic() + self.seconds_per_request


def deadline_clock(context: Optional[object]) -> Callable[[], float]:
    lambda_clock = getattr(context, 'get_remaining_time_in_millis', None)
    if lambda_clock:
        return lambda: float(lambda_clock()) / 1000.0
    started = monotonic()
    return lambda: LAMBDA_CEILING_SECONDS - (monotonic() - started)
