from unittest import TestCase

from tidalapi import Track

from src.tidal import NullArtistTolerantSession


UNPLAYABLE_TRACK_WITHOUT_ARTIST = {
    'accessType': 'PUBLIC',
    'adSupportedStreamReady': False,
    'ai': False,
    'album': {
        'cover': 'fa6463f9-55f5-4a3a-ac09-32912d78bd8e',
        'id': 509390389,
        'releaseDate': '2026-03-31',
        'title': 'Bajo Control',
        'vibrantColor': '#eec26a',
        'videoCover': None,
    },
    'allowStreaming': False,
    'artist': None,
    'artists': [],
    'audioModes': ['STEREO'],
    'audioQuality': 'LOSSLESS',
    'bpm': None,
    'copyright': 'CARLO SANTANA',
    'description': None,
    'djReady': False,
    'duration': 243,
    'explicit': False,
    'id': 509390391,
    'isrc': 'GXJBV2635121',
    'key': None,
    'keyScale': None,
    'mediaMetadata': {
        'tags': ['LOSSLESS', 'HIRES_LOSSLESS'],
    },
    'mixes': {
        'TRACK_MIX': '001cd54fd80936407e6764e6530550',
    },
    'payToStream': False,
    'peak': 0.97558,
    'popularity': 64,
    'premiumStreamingOnly': False,
    'replayGain': -5.74,
    'spotlighted': False,
    'stemReady': False,
    'streamReady': False,
    'streamStartDate': None,
    'title': 'Código Negro',
    'trackNumber': 2,
    'upload': False,
    'url': 'http://www.tidal.com/track/509390391',
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
