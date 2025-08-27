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
        self.is_in_artists("Matt and Kim", track)

    def test_comma_separated_multiple_artists(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Me Porto Bonito',
            {'Bad Bunny, Chencho Corleone'}
        ))

        self.assertEqual(track.name, 'Me Porto Bonito')
        self.is_in_artists("Bad Bunny", track)
        self.is_in_artists("Chencho Corleone", track)

    def test_the_prefix_normalization(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Today',
            {'The Smashing Pumpkins'}
        ))

        self.assertTrue('Today' in track.name)
        self.is_in_artists("Smashing Pumpkins", track)

    def test_diacritical_characters_in_artist_names(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'James Bonde',
            {'Bonde do Rolê'}
        ))

        self.assertEqual('James Bonde', track.name)
        self.is_in_artists("Bonde do Role", track)

    def test_ampersand_separated_multiple_artists(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Ingrid Bergman',
            {'Billy Bragg & Wilco'}
        ))

        self.assertEqual('Ingrid Bergman', track.name)
        self.is_in_artists("Wilco", track)
        self.is_in_artists("Billy Bragg", track)

    def test_comma_punctuation_in_single_artist_name(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Battle Royale',
            {'Does It Offend You, Yeah?'}
        ))

        self.assertTrue('Battle Royale' in track.name)
        self.is_in_artists("Does It Offend You, Yeah?", track)

    def test_slash_in_song_title(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'One Night/All Night',
            {'Justice'}
        ))

        self.assertEqual('One Night/All Night', track.name)
        self.is_in_artists("Justice", track)
        self.is_in_artists("Tame Impala", track)

    def test_apostrophes_in_artist_name(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            'Human',
            {"Rag'n'Bone Man"}
        ))

        self.assertEqual('Human', track.name)
        self.is_in_artists("Rag'n'Bone Man", track)

    def test_extract_artists_from_title_parentheses(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Anywhere Away From Here (Rag’n’Bone Man & P!nk)",
            {"Rag'n'Bone Man"}
        ))
        self.assertEqual('Anywhere Away from Here', track.name)
        self.is_in_artists("Rag'n'Bone Man", track)
        self.is_in_artists("P!Nk", track)

    def test_prefer_original_artist_album_over_covers(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Como La Flor",
            {"Selena"}
        ))
        self.assertEqual('Como La Flor', track.name)
        self.is_in_artists("Selena", track)

    def test_versus_blade_of_grass(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Blade of Grass",
            {"Versus"}
        ))
        self.assertEqual('Blade of Grass', track.name)
        self.is_in_artists("Versus", track)

    def test_artist_vs_artist(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Perfect (Exceeder)",
            {"Mason vs. Princess Superstar"}
        ))
        self.assertEqual('Perfect (Exceeder)', track.name)
        self.is_in_artists("Mason", track)
        self.is_in_artists("Princess Superstar", track)

    def test_artist_versus_artist(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Perfect (Exceeder)",
            {"Mason versus Princess Superstar"}
        ))
        self.assertEqual('Perfect (Exceeder)', track.name)
        self.is_in_artists("Mason", track)
        self.is_in_artists("Princess Superstar", track)

    def test_joy_division_wilderness_2019_remaster(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Wilderness - 2019 Remaster",
            {"Joy Division"}
        ))
        self.assertTrue(track.name.startswith('Wilderness'), track.name)
        self.is_in_artists("Joy Division", track)

    def test_scream_and_shout(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Scream & Shout",
            {"Will.I.Am feat. Britney Spears"}
        ))
        self.assertEqual('Scream & Shout', track.name)
        self.is_in_artists("Will.I.Am", track)
        self.is_in_artists("Britney Spears", track)

    def test_raise_your_weapon(self):
        track = self.tidal.find_equivalent_track(LastFmTrack(
            "Raise Your Weapon",
            {"deadmau5"}
        ))
        self.assertTrue(track.name.startswith('Raise Your Weapon'), track.name)
        self.assertEqual("deadmau5", track.artists[0].name)

    def is_in_artists(self, artist: str, track: Track):
        tidal_artists = {artist.name.lower() for artist in track.artists}
        self.assertIn(artist.lower(), tidal_artists)
