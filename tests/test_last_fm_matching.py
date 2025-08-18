from unittest import TestCase

from tidalapi import Track

from src.environment import Environment
from src.last_fm import LastFmTrack
from src.tidal import Tidal


class LastFmMatching(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tidal = Tidal(Environment())

    def test_kid_cudi_cant_shake_her(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Can't Shake Her (with Ty Dolla $ign)",
            {'Kid Cudi'}
        ))

        self.assertEqual(track.name, "Can't Shake Her")
        self.is_in_artists("Kid Cudi", track)
        self.is_in_artists("Ty Dolla $ign", track)

    def test_chase_and_status_baddadan(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Baddadan (feat. IRAH, Flowdan, Trigga & Takura)',
            {'Chase & Status'}
        ))

        self.assertEqual(track.name, 'Baddadan')
        self.is_in_artists("Chase & Status", track)
        self.is_in_artists("Bou", track)
        self.is_in_artists("Irah", track)
        self.is_in_artists("Flowdan", track)
        self.is_in_artists("Trigga", track)
        self.is_in_artists("Takura", track)

    def test_dfa1979_romantic_rights(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Romantic Rights (Album Version)',
            {'Death From Above 1979'}
        ))

        self.assertEqual(track.name, 'Romantic Rights')
        self.is_in_artists("Death From Above 1979", track)

    def test_not_various_artists_album(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Hey, Soul Sister',
            {'Train'}
        ))
        self.assertTrue('Save Me, San Francisco' in track.album.name, track.album.name)

    def test_use_various_artists_album_if_no_other_choice(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Don't Come Close",
            {'Yeasayer'}
        ))
        self.assertIsNotNone(track)
        self.assertTrue('Grand Theft Auto' in track.album.name)

    def test_use_og_selena_quintanilla_not_some_stupid_cover(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "I Could Fall In Love",
            {'Selena'}
        ))
        self.assertEqual(track.name, "I Could Fall In Love")
        self.is_in_artists("Selena", track)

    def test_matt_and_kim(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Daylight',
            {'Matt & Kim'}
        ))

        self.assertEqual(track.name, 'Daylight')
        self.is_in_artists("Matt & Kim", track)


    def is_in_artists(self, artist: str, tidal_track: Track):
        tidal_artists = {artist.name.lower() for artist in tidal_track.artists}
        self.assertIn(artist.lower(), tidal_artists)
