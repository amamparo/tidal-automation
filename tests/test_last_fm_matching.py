from unittest import TestCase

from src.environment import Environment
from src.last_fm import LastFmTrack
from src.tidal import Tidal, TidalTrack


class LastFmMatching(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tidal = Tidal(Environment())

    def test_kid_cudi_cant_shake_her(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Can't Shake Her (with Ty Dolla $ign)",
            {'Kid Cudi'}
        ))

        self.assertEqual(track.title, "Can't Shake Her")
        self.is_in_artists("Kid Cudi", track)
        self.is_in_artists("Ty Dolla $ign", track)

    def test_chase_and_status_baddadan(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Baddadan (feat. IRAH, Flowdan, Trigga & Takura)',
            {'Chase & Status'}
        ))

        self.assertEqual(track.title, 'Baddadan')
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

        self.assertEqual(track.title, 'Romantic Rights')
        self.is_in_artists("Death From Above 1979", track)

    def test_not_various_artists_album(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Hey, Soul Sister',
            {'Train'}
        ))
        self.assertTrue('Save Me, San Francisco' in track.album, track.album)

    def test_use_various_artists_album_if_no_other_choice(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Don't Come Close",
            {'Yeasayer'}
        ))
        self.assertIsNotNone(track)
        self.assertTrue('Grand Theft Auto' in track.album)

    def test_use_og_selena_quintanilla_not_some_stupid_cover(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "I Could Fall In Love",
            {'Selena'}
        ))
        self.assertEqual(track.title, "I Could Fall In Love")
        self.is_in_artists("Selena", track)

    def test_matt_and_kim(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Daylight',
            {'Matt & Kim'}
        ))

        self.assertEqual(track.title, 'Daylight')
        self.is_in_artists("Matt and Kim", track)

    def test_idk_why_last_fm_reggaeton_artists_are_always_comma_separated(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Me Porto Bonito',
            {'Bad Bunny, Chencho Corleone'}
        ))

        self.assertEqual(track.title, 'Me Porto Bonito')
        self.is_in_artists("Bad Bunny", track)
        self.is_in_artists("Chencho Corleone", track)

    def test_the_the(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Today',
            {'The Smashing Pumpkins'}
        ))

        self.assertTrue('Today' in track.title)
        self.is_in_artists("Smashing Pumpkins", track)

    def test_weird_brazillian_characters(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'James Bonde',
            {'Bonde do Rolê'}
        ))

        self.assertEqual('James Bonde', track.title)
        self.is_in_artists("Bonde do Role", track)

    def test_ampersand_in_last_fm_artist(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Ingrid Bergman',
            {'Billy Bragg & Wilco'}
        ))

        self.assertEqual('Ingrid Bergman', track.title)
        self.is_in_artists("Wilco", track)
        self.is_in_artists("Billy Bragg", track)

    def test_comma_in_single_artist_name(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Battle Royale',
            {'Does It Offend You, Yeah?'}
        ))

        self.assertTrue('Battle Royale' in track.title)
        self.is_in_artists("Does It Offend You, Yeah?", track)

    def test_fixme_1(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'One Night/All Night',
            {'Justice'}
        ))

        self.assertEqual('One Night/All Night', track.title)
        self.is_in_artists("Justice", track)
        self.is_in_artists("Tame Impala", track)

    def test_fixme_2(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Human',
            {"Rag'n'Bone Man"}
        ))

        self.assertEqual('Human', track.title)
        self.is_in_artists("Rag'n'Bone Man", track)

    def test_fixme_3(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Anywhere Away From Here (Rag’n’Bone Man & P!nk)",
            {"Rag'n'Bone Man"}
        ))
        self.assertEqual('Anywhere Away from Here', track.title)
        self.is_in_artists("Rag'n'Bone Man", track)
        self.is_in_artists("P!Nk", track)

    def is_in_artists(self, artist: str, tidal_track: TidalTrack):
        tidal_artists = {artist.lower() for artist in tidal_track.artists}
        self.assertIn(artist.lower(), tidal_artists)
