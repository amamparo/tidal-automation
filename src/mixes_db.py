import re
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from time import sleep
from typing import Dict, List, Optional, Tuple

import requests  # type: ignore[import-untyped]
from injector import singleton

API_URL = 'https://www.mixesdb.com/w/api.php'
USER_AGENT = 'tidal-automation/1.0 (+https://github.com/amamparo/tidal-automation)'
REQUEST_TIMEOUT = (5.0, 30.0)
CRAWL_DELAY_SECONDS = 4
TITLES_PER_REQUEST = 50
WINDOW_YEARS = 1
MINIMUM_TITLE_LENGTH = 3
MID_YEAR_MONTH = 7
MID_MONTH_DAY = 15

TRACKLIST_HEADING = re.compile(r'^==+\s*Tracklist\s*==+\s*$', re.MULTILINE | re.IGNORECASE)
SECTION_END = re.compile(r'^\[\[Category:|^==+\s*[^=]+\s*==+\s*$', re.MULTILINE)
LIST_MARKER = re.compile(r'^#+\s*')
LEADING_TIMESTAMP = re.compile(r'^\[[\d?]{1,2}(?::[\d?]{2}){1,2}\]\s*|^\[[\d?]{1,4}\]\s*')
TRAILING_LABEL = re.compile(r'\s*\[[^\[\]]*\]\s*$')
BRACKETED_ARTIST = re.compile(r'^[\[(](.*)\]$')
FILLER = re.compile(r'^(?:[?.\-…]+|intro|outro|interview|id)$', re.IGNORECASE)
TITLE_DATE = re.compile(r'^(\d{4})(?:-([\dX?]{2}))?(?:-([\dX?]{2}))?')


def searchable(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


@dataclass
class MixTrack:
    artist: str
    title: str

    def key(self) -> Tuple[str, str]:
        return searchable(self.artist), searchable(self.title)

    def __hash__(self) -> int:
        return hash(self.key())

    def __eq__(self, other: object) -> bool:
        return isinstance(other, MixTrack) and self.key() == other.key()


@dataclass
class Tracklist:
    recorded_on: date
    tracks: List[MixTrack]


def date_window(today: date) -> str:
    earliest_year = today.year - WINDOW_YEARS
    whole_years = [str(year) for year in range(today.year, earliest_year, -1)]
    trailing_months = [f'{earliest_year}-{month:02d}' for month in reversed(range(today.month, 13))]
    return ','.join([*whole_years, *trailing_months])


def recorded_on(mix_title: str) -> Optional[date]:
    match = TITLE_DATE.match(mix_title)
    if not match:
        return None
    year_token, month_token, day_token = match.groups()
    year = int(year_token)
    stated_month = int(month_token) if month_token and month_token.isdigit() else MID_YEAR_MONTH
    stated_day = int(day_token) if day_token and day_token.isdigit() else MID_MONTH_DAY
    month = min(max(stated_month, 1), 12)
    return date(year, month, min(max(stated_day, 1), monthrange(year, month)[1]))


def tracklist_lines(wikitext: str) -> List[str]:
    heading = TRACKLIST_HEADING.search(wikitext)
    if not heading:
        return []
    after_heading = wikitext[heading.end():]
    end = SECTION_END.search(after_heading)
    section = after_heading[:end.start()] if end else after_heading
    lines: List[str] = []
    inside_list = False
    for raw_line in re.split(r'\r?\n', section):
        line = raw_line.strip()
        if line.startswith('<list'):
            inside_list = True
        elif line.startswith('</list'):
            inside_list = False
        elif line.startswith('#') or (inside_list and line):
            lines.append(line)
    return lines


def parse_line(line: str) -> Optional[MixTrack]:
    body = LIST_MARKER.sub('', line).strip().replace("''", '')
    body = LEADING_TIMESTAMP.sub('', body, count=1)
    body = TRAILING_LABEL.sub('', body).strip()
    if FILLER.match(body) or ' - ' not in body:
        return None
    artist, title = body.split(' - ', 1)
    bracketed = BRACKETED_ARTIST.match(artist.strip())
    if bracketed:
        artist = bracketed.group(1)
    artist = re.sub(r'\s+', ' ', artist).strip()
    title = re.sub(r'\s+', ' ', title).strip()
    if not artist or artist.startswith('?') or not title or title.startswith('?'):
        return None
    if len(re.sub(r'[^a-zA-Z0-9]', '', title)) < MINIMUM_TITLE_LENGTH:
        return None
    return MixTrack(artist=artist, title=title)


def parse_tracklist(wikitext: str) -> List[MixTrack]:
    parsed = (parse_line(line) for line in tracklist_lines(wikitext))
    return [track for track in parsed if track]


@singleton
class MixesDb:
    def __init__(self) -> None:
        self.__session = requests.Session()
        self.__session.headers.update({'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip'})

    def get_tracklists(self, query: str) -> List[Tracklist]:
        titles = self.__search_titles(query)
        wikitext = self.__get_wikitext(titles)
        tracklists = []
        for title in titles:
            recorded = recorded_on(title)
            tracks = parse_tracklist(wikitext.get(title, ''))
            if recorded and tracks:
                tracklists.append(Tracklist(recorded_on=recorded, tracks=tracks))
        return tracklists

    def __search_titles(self, query: str) -> List[str]:
        response = self.__get({
            'action': 'query', 'list': 'search', 'srlimit': 'max', 'srsort': 'hotness_desc',
            'srsearch': query,
        })
        return [result['title'] for result in response['query']['search']]

    def __get_wikitext(self, titles: List[str]) -> Dict[str, str]:
        wikitext = {}
        for start in range(0, len(titles), TITLES_PER_REQUEST):
            response = self.__get({
                'action': 'query', 'prop': 'revisions', 'rvprop': 'content', 'rvslots': 'main',
                'titles': '|'.join(titles[start:start + TITLES_PER_REQUEST]),
            })
            query_result = response['query']
            requested_title = {entry['to']: entry['from'] for entry in query_result.get('normalized', [])}
            for page in query_result['pages']:
                if page.get('missing') or not page.get('revisions'):
                    continue
                title = page['title']
                wikitext[requested_title.get(title, title)] = page['revisions'][0]['slots']['main']['content']
        return wikitext

    def __get(self, params: Dict[str, str]) -> dict:
        sleep(CRAWL_DELAY_SECONDS)
        response = self.__session.get(
            API_URL, params={**params, 'format': 'json', 'formatversion': '2'}, timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        body = response.json()
        error = body.get('error')
        if error:
            raise RuntimeError(f'mixesdb api error: {error}')
        return body
