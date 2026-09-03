from typing import Any, List, Optional, cast
from unittest import TestCase

from tidalapi import Track

from src.tidal import NullArtistTolerantSession, Tidal


def track(name: str, artists: List[str], version: Optional[str] = None) -> Track:
    return cast(Track, NullArtistTolerantSession().parse_media({
        'album': {'cover': None, 'id': 1, 'releaseDate': '2026-01-01', 'title': 'Album', 'videoCover': None},
        'artist': {'id': 1, 'name': artists[0] if artists else None},
        'artists': [{'id': index, 'name': artist} for index, artist in enumerate(artists)],
        'audioModes': ['STEREO'], 'audioQuality': 'LOSSLESS', 'copyright': '', 'duration': 300,
        'explicit': False, 'id': 99, 'isrc': 'X', 'mediaMetadata': {'tags': ['LOSSLESS']},
        'peak': 1.0, 'popularity': 50, 'replayGain': 0.0, 'streamReady': True,
        'title': name, 'trackNumber': 1, 'version': version, 'volumeNumber': 1,
    }))


def versions_match(searched_title: str, candidate: Track) -> bool:
    matcher = getattr(cast(Any, Tidal), '_Tidal__versions_match')
    return bool(matcher(searched_title, candidate))


def clean_title(title: str) -> str:
    cleaner = getattr(cast(Any, Tidal), '_Tidal__clean_title')
    return str(cleaner(title))


class TrackVersions(TestCase):
    def test_an_exact_version_matches(self) -> None:
        self.assertTrue(versions_match('Attribute 39 (Donato Dozzy Remix)',
                                       track('Attribute 39 (Donato Dozzy Remix)', ['Peter Van Hoesen'])))

    def test_a_remix_does_not_match_the_original(self) -> None:
        self.assertFalse(versions_match('Ikigai (Orbe Remix)', track('Ikigai', ['Vladw'])))
        self.assertFalse(versions_match('Join In The Chant (Surgeon Edit)',
                                        track('Join In The Chant', ['Nitzer Ebb'])))
        self.assertFalse(versions_match('Jupiter Jazz (Mark Broom Retouch)',
                                        track('Jupiter Jazz', ['Underground Resistance'])))

    def test_the_original_does_not_match_a_remix(self) -> None:
        self.assertFalse(versions_match('Midnight Blue',
                                        track('Midnight Blue (Satoshi Tomiie Remix)', ['Nacho Marco'])))

    def test_a_remixer_credited_as_an_artist_counts_as_the_remix(self) -> None:
        self.assertTrue(versions_match('Dreaming Trees (Forest Drive West Remix)',
                                       track('Dreaming Trees', ['Polygonia', 'Forest Drive West'])))
        self.assertFalse(versions_match('Dreaming Trees (Forest Drive West Remix)',
                                        track('Dreaming Trees', ['Polygonia'])))

    def test_tidals_separate_version_field_is_read(self) -> None:
        self.assertFalse(versions_match('Advanced', track('Advanced', ['Marcel Woods'], version='Short Mix')))
        self.assertTrue(versions_match('Advanced (Short Mix)',
                                       track('Advanced', ['Marcel Woods'], version='Short Mix')))

    def test_a_neutral_qualifier_is_the_same_recording(self) -> None:
        self.assertTrue(versions_match('Feel And Communicate',
                                       track('Feel And Communicate (Original Mix)', ['Quiem'])))
        self.assertTrue(versions_match('Summer In The City',
                                       track('Summer In The City (Remastered 2022)', ['Samuel L. Session'])))
        self.assertTrue(versions_match('Metodo', track('Metodo', ['Someone'], version='Original Mix')))

    def test_a_collaborator_credit_is_not_a_version(self) -> None:
        self.assertTrue(versions_match("Can't Shake Her (with Ty Dolla $ign)",
                                       track("Can't Shake Her", ['Kid Cudi'])))

    def test_an_unversioned_title_matches_an_unversioned_track(self) -> None:
        self.assertTrue(versions_match('Some Song', track('Some Song', ['Someone'])))

    def test_a_live_marker_is_not_a_version(self) -> None:
        self.assertTrue(versions_match('Canopee Imaginaire (Live At Draaimolen 2023)',
                                       track('Canopee Imaginaire', ['Azu Tiwaline'],
                                             version='Live at Draaimolen 2023')))
        self.assertTrue(versions_match('Seconds To Forever (Live Mix)',
                                       track('Seconds To Forever', ['cv313'])))
        self.assertTrue(versions_match('Some Track (Live)', track('Some Track', ['Someone'])))

    def test_a_credited_remixer_still_counts_when_the_marker_says_live(self) -> None:
        self.assertFalse(versions_match('Very Being (Federsen Live Dub)', track('Very Being', ['Mike Schommer'])))


class LiveMarkersInTheSearchQuery(TestCase):
    def test_a_live_marker_is_stripped_before_searching(self) -> None:
        self.assertEqual('Canopee Imaginaire', clean_title('Canopee Imaginaire (Live At Draaimolen 2023)'))
        self.assertEqual('Seconds To Forever', clean_title('Seconds To Forever (Live Mix)'))

    def test_a_named_remix_survives_the_search_query(self) -> None:
        self.assertEqual('Ikigai (Orbe Remix)', clean_title('Ikigai (Orbe Remix)'))
