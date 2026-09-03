from unittest import TestCase

from tidalapi import Track

from src.tidal import NullArtistTolerantSession


UNPLAYABLE_TRACK_WITHOUT_ARTIST = {
    'album': {
        'cover': 'fa6463f9-55f5-4a3a-ac09-32912d78bd8e',
        'id': 509390389,
        'releaseDate': '2026-03-31',
        'title': 'Bajo Control',
        'videoCover': None,
    },
    'artist': None,
    'artists': [],
    'audioModes': ['STEREO'],
    'audioQuality': 'LOSSLESS',
    'copyright': 'CARLO SANTANA',
    'duration': 243,
    'explicit': False,
    'id': 509390391,
    'isrc': 'GXJBV2635121',
    'mediaMetadata': {'tags': ['LOSSLESS', 'HIRES_LOSSLESS']},
    'peak': 0.97558,
    'popularity': 64,
    'replayGain': -5.74,
    'streamReady': False,
    'title': 'Código Negro',
    'trackNumber': 2,
    'version': None,
    'volumeNumber': 1,
}


class NullArtistTrack(TestCase):
    def test_parses_instead_of_raising(self) -> None:
        track = NullArtistTolerantSession().parse_media(UNPLAYABLE_TRACK_WITHOUT_ARTIST)

        self.assertIsInstance(track, Track)
        self.assertEqual(509390391, track.id)
        self.assertEqual('Código Negro', track.name)
        self.assertFalse(track.available)

    def test_stands_in_for_the_missing_artist(self) -> None:
        track = NullArtistTolerantSession().parse_media(UNPLAYABLE_TRACK_WITHOUT_ARTIST)

        assert track.artists is not None
        self.assertEqual([None], [artist.name for artist in track.artists])
