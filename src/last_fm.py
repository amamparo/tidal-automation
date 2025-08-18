from dataclasses import dataclass
from typing import Set

import requests
from injector import inject


@dataclass
class LastFmTrack:
    title: str
    artists: Set[str]

    def __hash__(self):
        return hash((self.title, tuple(sorted(self.artists))))
    
    def __eq__(self, other):
        if not isinstance(other, LastFmTrack):
            return False
        return self.title == other.title and self.artists == other.artists


class LastFm:
    @inject
    def __init__(self):
        pass

    def get_mix(self, _type: str) -> Set[LastFmTrack]:
        playlist = requests.get(
            f'https://www.last.fm/player/station/user/amamparo/{_type}?page=1&ajax=1'
        ).json()['playlist']
        return {LastFmTrack(title=x['name'], artists={a['name'] for a in x['artists']}) for x in playlist}
