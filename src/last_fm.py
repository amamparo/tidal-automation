from dataclasses import dataclass
from typing import Set, List

import requests  # type: ignore[import-untyped]


@dataclass
class LastFmTrack:
    title: str
    artists: Set[str]

    def __hash__(self) -> int:
        return hash((self.title, tuple(sorted(self.artists))))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, LastFmTrack) and self.title == other.title and self.artists == other.artists


class LastFm:
    def get_mix(self, mix_type: str) -> List[LastFmTrack]:
        url = f'https://www.last.fm/player/station/user/amamparo/{mix_type}?page=1&ajax=1'
        playlist = requests.get(url, timeout=None).json()['playlist']
        return [LastFmTrack(title=x['name'], artists={a['name'] for a in x['artists']}) for x in playlist]
