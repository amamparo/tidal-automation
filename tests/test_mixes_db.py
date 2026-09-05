from datetime import date
from pathlib import Path
from typing import List, Tuple
from unittest import TestCase

from src.mixes_db import WINDOW_YEARS, MixTrack, date_window, parse_tracklist, recorded_on
from src.update_darkroom import search_query

FIXTURES = Path(__file__).parent / 'fixtures' / 'mixes_db'


def parse_lines(*lines: str) -> List[MixTrack]:
    return parse_tracklist('\n'.join(['== Tracklist ==', '', *lines, '', '[[Category:Dub Techno]]']))


def parse_one(line: str) -> MixTrack:
    tracks = parse_lines(line)
    assert len(tracks) == 1, f'expected exactly one track from {line!r}, got {tracks}'
    return tracks[0]


def pairs(tracks: List[MixTrack]) -> List[Tuple[str, str]]:
    return [(track.artist, track.title) for track in tracks]


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding='utf-8')


class TracklistParsing(TestCase):
    def test_keeps_remix_parenthetical(self) -> None:
        track = parse_one('# Polygonia - Dreaming Trees (Forest Drive West Remix)')

        self.assertEqual('Polygonia', track.artist)
        self.assertEqual('Dreaming Trees (Forest Drive West Remix)', track.title)

    def test_parses_numbered_list_format(self) -> None:
        tracks = parse_lines(
            '# [007] Oreste - Golden String [Indefinite Pitch]',
            '# DeepChord - Point Reyes [Soma]'
        )

        self.assertEqual([('Oreste', 'Golden String'), ('DeepChord', 'Point Reyes')], pairs(tracks))

    def test_parses_list_tag_format(self) -> None:
        tracks = parse_lines(
            '<list>',
            '[005] Marco Shuttle - AfA [Incienso]',
            'Rrose - The Illuminating Glass [Eaux]',
            '</list>'
        )

        self.assertEqual([('Marco Shuttle', 'AfA'), ('Rrose', 'The Illuminating Glass')], pairs(tracks))

    def test_parses_page_using_both_formats(self) -> None:
        tracks = parse_lines(
            ';dESUS',
            '# SoulParlor - Dub Tube [Insectorama]',
            ';Apjok Csaba',
            '<list>',
            'Frenk Dublin - Into The Void [Moonshine]',
            '</list>',
            '# Schulz Audio - Riddim Room [Axaminer]'
        )

        self.assertEqual(
            [('SoulParlor', 'Dub Tube'), ('Frenk Dublin', 'Into The Void'), ('Schulz Audio', 'Riddim Room')],
            pairs(tracks)
        )

    def test_strips_leading_timestamps(self) -> None:
        for timestamp in ['[000]', '[??]', '[0??]', '[08?]', '[56]', '[00:43:58]', '[0:38:25]']:
            with self.subTest(timestamp=timestamp):
                track = parse_one(f'# {timestamp} Zonal - Wrecked')

                self.assertEqual('Zonal', track.artist)
                self.assertEqual('Wrecked', track.title)

    def test_strips_trailing_record_label(self) -> None:
        self.assertEqual('Dub Tube', parse_one('# SoulParlor - Dub Tube [Insectorama]').title)
        self.assertEqual('Dub Tube', parse_one('# SoulParlor - Dub Tube [M]').title)

    def test_splits_on_first_dash_after_stripping_label(self) -> None:
        track = parse_one('# Ruben Ganev - Condition [mould.audio - mldcs025]')
        reprise = parse_one('# Ruben Ganev - Condition - Reprise [mould.audio - mldcs025]')

        self.assertEqual(('Ruben Ganev', 'Condition'), (track.artist, track.title))
        self.assertEqual(('Ruben Ganev', 'Condition - Reprise'), (reprise.artist, reprise.title))
        self.assertEqual([], parse_lines('# Deepchord Presents Echospace [Modern Love - ml001]'))

    def test_keeps_credited_artist_string_intact(self) -> None:
        self.assertEqual('Batu & Donato Dozzy', parse_one('# Batu & Donato Dozzy - Track').artist)
        self.assertEqual(
            'Neel & Natural/Electronic.System.',
            parse_one('# Neel & Natural/Electronic.System. - Mira [Tikita]').artist
        )

    def test_unwraps_bracketed_artist(self) -> None:
        track = parse_one('# [Moosdohmen] - Paddy Dub')

        self.assertEqual('Moosdohmen', track.artist)
        self.assertEqual('Paddy Dub', track.title)

    def test_strips_italic_markup(self) -> None:
        partly_italic = parse_one("# Deadbeat - Rock ''The'' Dub")

        self.assertEqual('Deadbeat', partly_italic.artist)
        self.assertEqual('Rock The Dub', partly_italic.title)
        self.assertEqual(('Deadbeat', 'Rock The Dub'), pairs(parse_lines("# ''Deadbeat - Rock The Dub''"))[0])

    def test_drops_filler_and_dashless_and_unknown_lines(self) -> None:
        dropped = [
            '# Intro',
            '# Outro',
            '# ID',
            '# ...',
            '...',
            '# [004] ?',
            '# ? - Margin',
            '# Diego - ?',
            '# Sunday Morning Mix No Separator'
        ]

        for line in dropped:
            with self.subTest(line=line):
                self.assertEqual([], parse_lines(line))

    def test_drops_short_titles(self) -> None:
        self.assertEqual([], parse_lines('# Retouched - F'))
        self.assertEqual([], parse_lines('# Retouched - F [Insectorama]'))
        self.assertEqual([], parse_lines('# Donato Dozzy - B'))
        self.assertEqual([], parse_lines('# Donato Dozzy - A B'))
        self.assertEqual('A.B.C', parse_one('# Donato Dozzy - A.B.C').title)

    def test_ignores_content_outside_the_tracklist_section(self) -> None:
        before_and_after_categories = parse_tracklist('\n'.join([
            '# Above Heading - Not A Track',
            '== Tracklist ==',
            '# Yagya - Sleepygirl 1',
            '[[Category:Dub Techno]]',
            '# Below Categories - Not A Track'
        ]))
        before_next_heading = parse_tracklist('\n'.join([
            '== Tracklist ==',
            '# Yagya - Sleepygirl 1',
            '== Comments ==',
            '# Below Heading - Not A Track',
            '[[Category:Dub Techno]]'
        ]))

        self.assertEqual([('Yagya', 'Sleepygirl 1')], pairs(before_and_after_categories))
        self.assertEqual([('Yagya', 'Sleepygirl 1')], pairs(before_next_heading))

    def test_returns_nothing_without_a_tracklist_heading(self) -> None:
        self.assertEqual([], parse_tracklist(''))
        self.assertEqual([], parse_tracklist('== File details ==\n# Yagya - Sleepygirl 1\n[[Category:Dub Techno]]'))

    def test_parses_fixture_corpus(self) -> None:
        hash_tracks = parse_tracklist(read_fixture('hash_format.txt'))
        list_tracks = parse_tracklist(read_fixture('list_format.txt'))
        both_tracks = parse_tracklist(read_fixture('both_format.txt'))

        self.assertEqual([17, 17, 6], [len(hash_tracks), len(list_tracks), len(both_tracks)])
        self.assertIn(MixTrack('DeepChord', 'Point Reyes'), hash_tracks)
        self.assertIn(MixTrack('Korridor', 'Binocular Observer (Ness Remix)'), list_tracks)
        self.assertIn(MixTrack('Schulz Audio', 'Riddim Room'), both_tracks)


class DateWindow(TestCase):
    def test_date_window(self) -> None:
        self.assertEqual('2026,2025,2024-12,2024-11,2024-10,2024-09', date_window(date(2026, 9, 3)))

    def test_date_window_in_january(self) -> None:
        tokens = date_window(date(2027, 1, 2)).split(',')

        self.assertEqual(14, len(tokens))
        self.assertEqual(['2027', '2026'], tokens[:2])
        self.assertEqual([f'2025-{month:02d}' for month in reversed(range(1, 13))], tokens[2:])

    def test_date_window_is_whole_years_then_trailing_months(self) -> None:
        for month in range(1, 13):
            with self.subTest(month=month):
                tokens = date_window(date(2027, month, 1)).split(',')

                self.assertEqual([str(2027 - back) for back in range(WINDOW_YEARS)], tokens[:WINDOW_YEARS])
                self.assertEqual([f'{2027 - WINDOW_YEARS}-{trailing:02d}'
                                  for trailing in reversed(range(month, 13))], tokens[WINDOW_YEARS:])


class SearchQuery(TestCase):
    def test_search_query(self) -> None:
        self.assertEqual(
            'style:"Dub Techno" style:Minimal -tracklist:none date:2026,2025,2024-12,2024-11,2024-10,2024-09',
            search_query(date(2026, 9, 3))
        )


class TrackIdentity(TestCase):
    def test_spellings_that_normalise_the_same_are_one_track(self) -> None:
        canonical = MixTrack('Basic Channel', 'Q1.1')
        scruffy = MixTrack('basic  channel', 'q1.1')

        self.assertEqual(canonical, scruffy)
        self.assertEqual(hash(canonical), hash(scruffy))
        self.assertEqual(1, len({canonical, scruffy}))
        self.assertEqual(1.0, {canonical: 1.0}[scruffy])

    def test_different_tracks_stay_distinct(self) -> None:
        track = MixTrack('Basic Channel', 'Q1.1')

        self.assertNotEqual(track, MixTrack('Basic Channel', 'Q1.2'))
        self.assertNotEqual(track, MixTrack('Rhythm & Sound', 'Q1.1'))
        self.assertNotEqual(track, 'Basic Channel - Q1.1')
        self.assertEqual(3, len({track, MixTrack('Basic Channel', 'Q1.2'), MixTrack('Rhythm & Sound', 'Q1.1')}))


class RecordedOn(TestCase):
    def test_reads_a_full_date(self) -> None:
        self.assertEqual(date(2025, 12, 21), recorded_on('2025-12-21 - Charis - The Sphère Chair'))

    def test_reads_a_fuzzy_month(self) -> None:
        self.assertEqual(date(2026, 7, 15), recorded_on('2026-0X - AliA @ Ilian Tape'))

    def test_reads_a_bare_year(self) -> None:
        self.assertEqual(date(2026, 7, 15), recorded_on('2026 - Verschwender b2b Kwartz @ Tresor'))

    def test_ignores_an_undated_title(self) -> None:
        self.assertIsNone(recorded_on('Charis - The Sphère Chair'))

    def test_keeps_the_real_day_of_month(self) -> None:
        self.assertEqual(date(2026, 7, 31), recorded_on('2026-07-31 - Lukas Sawicki - Off The Record'))
        self.assertEqual(date(2025, 11, 30), recorded_on('2025-11-30 - Yard One - The Alta Chair'))

    def test_clamps_an_impossible_day_to_the_month_length(self) -> None:
        self.assertEqual(date(2025, 2, 28), recorded_on('2025-02-31 - Nonexistent Day'))
        self.assertEqual(date(2024, 2, 29), recorded_on('2024-02-31 - Leap Year'))
