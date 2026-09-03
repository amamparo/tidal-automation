from typing import cast
from unittest import TestCase

from tidalapi import Track

from src.environment import Environment
from src.last_fm import LastFmTrack
from src.tidal import Tidal


def track_name(track: Track) -> str:
    assert track.name is not None
    return track.name


def album_name(track: Track) -> str:
    assert track.album is not None and track.album.name is not None
    return track.album.name


def artist_names(track: Track) -> list[str]:
    assert track.artists is not None
    names = [artist.name for artist in track.artists]
    assert all(name is not None for name in names), f'unnamed artist in {names}'
    return cast(list[str], names)


class LastFmMatching(TestCase):
    tidal: Tidal

    @classmethod
    def setUpClass(cls) -> None:
        cls.tidal = Tidal(Environment())

    def test_kid_cudi_cant_shake_her(self) -> None:
        track = self.find_track("Can't Shake Her (with Ty Dolla $ign)", {'Kid Cudi'})

        self.assertEqual("Can't Shake Her", track.name)
        self.assert_in_artists('Kid Cudi', track)
        self.assert_in_artists('Ty Dolla $ign', track)

    def test_chase_and_status_baddadan(self) -> None:
        track = self.find_track('Baddadan (feat. IRAH, Flowdan, Trigga & Takura)', {'Chase & Status'})

        self.assertEqual('Baddadan', track.name)
        self.assert_in_artists('Chase & Status', track)
        self.assert_in_artists('Bou', track)
        self.assert_in_artists('Irah', track)
        self.assert_in_artists('Flowdan', track)
        self.assert_in_artists('Trigga', track)
        self.assert_in_artists('Takura', track)

    def test_dfa1979_romantic_rights(self) -> None:
        track = self.find_track('Romantic Rights (Album Version)', {'Death From Above 1979'})

        self.assertEqual('Romantic Rights', track.name)
        self.assert_in_artists('Death From Above 1979', track)

    def test_not_various_artists_album(self) -> None:
        track = self.find_track('Hey, Soul Sister', {'Train'})

        self.assertIn('Save Me, San Francisco', album_name(track))

    def test_use_various_artists_album_if_no_other_choice(self) -> None:
        track = self.find_track("Don't Come Close", {'Yeasayer'})

        self.assertIn('Grand Theft Auto', album_name(track))

    def test_use_og_selena_quintanilla_not_some_stupid_cover(self) -> None:
        track = self.find_track('I Could Fall In Love', {'Selena'})

        self.assertEqual('I Could Fall In Love', track.name)
        self.assert_in_artists('Selena', track)

    def test_matt_and_kim(self) -> None:
        track = self.find_track('Daylight', {'Matt & Kim'})

        self.assertEqual('Daylight', track.name)
        self.assert_in_artists('Matt and Kim', track)

    def test_comma_separated_multiple_artists(self) -> None:
        track = self.find_track('Me Porto Bonito', {'Bad Bunny, Chencho Corleone'})

        self.assertEqual('Me Porto Bonito', track.name)
        self.assert_in_artists('Bad Bunny', track)
        self.assert_in_artists('Chencho Corleone', track)

    def test_the_prefix_normalization(self) -> None:
        track = self.find_track('Today', {'The Smashing Pumpkins'})

        self.assertIn('Today', track_name(track))
        self.assert_in_artists('Smashing Pumpkins', track)

    def test_diacritical_characters_in_artist_names(self) -> None:
        track = self.find_track('James Bonde', {'Bonde do Rolê'})

        self.assertEqual('James Bonde', track.name)
        self.assert_in_artists('Bonde do Role', track)

    def test_ampersand_separated_multiple_artists(self) -> None:
        track = self.find_track('Ingrid Bergman', {'Billy Bragg & Wilco'})

        self.assertEqual('Ingrid Bergman', track.name)
        self.assert_in_artists('Wilco', track)
        self.assert_in_artists('Billy Bragg', track)

    def test_comma_punctuation_in_single_artist_name(self) -> None:
        track = self.find_track('Battle Royale', {'Does It Offend You, Yeah?'})

        self.assertIn('Battle Royale', track_name(track))
        self.assert_in_artists('Does It Offend You, Yeah?', track)

    def test_slash_in_song_title(self) -> None:
        track = self.find_track('One Night/All Night', {'Justice'})

        self.assertEqual('One Night/All Night', track.name)
        self.assert_in_artists('Justice', track)
        self.assert_in_artists('Tame Impala', track)

    def test_apostrophes_in_artist_name(self) -> None:
        track = self.find_track('Human', {"Rag'n'Bone Man"})

        self.assertEqual('Human', track.name)
        self.assert_in_artists("Rag'n'Bone Man", track)

    def test_extract_artists_from_title_parentheses(self) -> None:
        track = self.find_track('Anywhere Away From Here (Rag’n’Bone Man & P!nk)', {"Rag'n'Bone Man"})

        self.assertEqual('Anywhere Away from Here', track.name)
        self.assert_in_artists("Rag'n'Bone Man", track)
        self.assert_in_artists('P!Nk', track)

    def test_prefer_original_artist_album_over_covers(self) -> None:
        track = self.find_track('Como La Flor', {'Selena'})

        self.assertEqual('Como La Flor', track.name)
        self.assert_in_artists('Selena', track)

    def test_versus_blade_of_grass(self) -> None:
        track = self.find_track('Blade of Grass', {'Versus'})

        self.assertEqual('Blade of Grass', track.name)
        self.assert_in_artists('Versus', track)

    def test_artist_vs_artist(self) -> None:
        track = self.find_track('Perfect (Exceeder)', {'Mason vs. Princess Superstar'})

        self.assertEqual('Perfect (Exceeder)', track.name)
        self.assert_in_artists('Mason', track)
        self.assert_in_artists('Princess Superstar', track)

    def test_artist_versus_artist(self) -> None:
        track = self.find_track('Perfect (Exceeder)', {'Mason versus Princess Superstar'})

        self.assertEqual('Perfect (Exceeder)', track.name)
        self.assert_in_artists('Mason', track)
        self.assert_in_artists('Princess Superstar', track)

    def test_joy_division_wilderness_2019_remaster(self) -> None:
        track = self.find_track('Wilderness - 2019 Remaster', {'Joy Division'})

        name = track_name(track)
        self.assertTrue(name.startswith('Wilderness'), name)
        self.assert_in_artists('Joy Division', track)

    def test_scream_and_shout(self) -> None:
        track = self.find_track('Scream & Shout', {'Will.I.Am feat. Britney Spears'})

        self.assertEqual('Scream & Shout', track.name)
        self.assert_in_artists('Will.I.Am', track)
        self.assert_in_artists('Britney Spears', track)

    def test_raise_your_weapon(self) -> None:
        track = self.find_track('Raise Your Weapon', {'deadmau5'})

        name = track_name(track)
        self.assertTrue(name.startswith('Raise Your Weapon'), name)
        self.assertEqual('deadmau5', artist_names(track)[0])

    def test_soul_purge_current_value_remix(self) -> None:
        track = self.find_track('Soul Purge (Current Value Remix)', {'Noisia'})

        self.assertEqual('Soul Purge', track.name)
        self.assertEqual('Current Value Remix', track.version)
        self.assert_in_artists('Noisia', track)

    def find_track(self, title: str, artists: set[str]) -> Track:
        track = self.tidal.find_equivalent_track(LastFmTrack(title, artists))
        assert track is not None, f'no Tidal match for {title}'
        return track

    def assert_in_artists(self, expected: str, track: Track) -> None:
        self.assertIn(expected.lower(), {name.lower() for name in artist_names(track)})
