from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Dict, List, Optional, Set, cast
from threading import Event
from unittest import TestCase

from tidalapi import Track

from src.discogs import Discogs
from src.genre import TagVector, Vouch
from src.last_fm import LastFm, LastFmTrack
from src.mixes_db import WIDENING_MONTHS, WINDOW_MONTHS, MixesDb, MixTrack, Tracklist
from src.playlist import (
    PITCH_FADER_RANGE,
    TagLane,
    TimedTrack,
    annealed_selection,
    artist_tags,
    candidates_from,
    corpus_the_clock_can_reach,
    gather_evidence,
    genre_confidences,
    is_same_recording,
    mixable_selection,
    most_confident,
    reachable_candidates,
    seconds_per_candidate,
    seconds_to_finish,
    time_to_read_again,
    vouches_for,
    widened_corpus
)
from src.tidal import Tidal

TODAY = date(2026, 9, 3)
PLAYLIST_SIZE = 100


def mix(*tracks: MixTrack) -> Tracklist:
    return Tracklist(recorded_on=TODAY, tracks=list(tracks))


def timed_tracks(**tempos: float) -> List[TimedTrack]:
    return [TimedTrack(track_id, tempo) for track_id, tempo in tempos.items()]


@dataclass
class Credit:
    name: Optional[str]


@dataclass
class FoundTrack:
    id: int
    name: str
    artists: List[Credit] = field(default_factory=list)


def tidal_id(title: str) -> int:
    return abs(hash(title))


def radio_of(*artists: str) -> List[Track]:
    return cast(List[Track], [FoundTrack(position, f'track {position}', [Credit(artist)])
                              for position, artist in enumerate(artists)])


class StubTidal:
    def __init__(self, radios: Dict[str, List[Track]], untimed: Set[str],
                 seconds_per_request: float) -> None:
        self.radios = radios
        self.untimed = untimed
        self.seconds_per_request = seconds_per_request
        self.radios_read: List[str] = []
        self.found: Dict[str, str] = {}

    def seconds_to_set_playlist(self, playlist_size: int) -> float:
        return playlist_size * self.seconds_per_request

    def find_timed_track(self, last_fm_track: LastFmTrack) -> Optional[FoundTrack]:
        title = last_fm_track.title
        if title not in self.radios:
            return None
        found = FoundTrack(tidal_id(title), title)
        self.found[str(found.id)] = title
        return found

    def beats_per_minute(self, track_id: str) -> Optional[int]:
        return None if self.found.get(track_id) in self.untimed else 126

    def track_radio(self, track: FoundTrack) -> List[Track]:
        self.radios_read.append(track.name)
        return self.radios[track.name]


def stub_tidal(radios: Dict[str, List[Track]], untimed: Optional[Set[str]] = None,
               seconds_per_request: float = 0.0) -> Tidal:
    return cast(Tidal, StubTidal(radios, untimed or set(), seconds_per_request))


class StubLastFm:
    def __init__(self, tags: Dict[str, Dict[str, float]], roster: List[str]) -> None:
        self.tags = tags
        self.roster = roster
        self.asked: List[str] = []
        self.seconds_per_request = 0.0

    def top_artists(self, _tag: str, limit: int) -> List[str]:
        return self.roster[:limit]

    def top_tags(self, artist: str) -> Dict[str, float]:
        self.asked.append(artist)
        return self.tags.get(artist, {})


def stub_last_fm(tags: Dict[str, Dict[str, float]], roster: Optional[List[str]] = None) -> LastFm:
    return cast(LastFm, StubLastFm(tags, roster or []))


class StubDiscogs:
    def __init__(self, styles: Dict[str, Dict[str, float]]) -> None:
        self.styles_by_artist = styles
        self.asked: List[str] = []
        self.seconds_per_request = 0.0

    def styles(self, artist: str) -> Dict[str, float]:
        self.asked.append(artist)
        return self.styles_by_artist.get(artist, {})


def stub_discogs(styles: Optional[Dict[str, Dict[str, float]]] = None) -> Discogs:
    return cast(Discogs, StubDiscogs(styles or {}))


class StubTagLane:
    def __init__(self, seconds_to_drain: float) -> None:
        self.asked: List[str] = []
        self.seconds_to_drain = seconds_to_drain

    def request(self, artist: str) -> None:
        self.asked.append(artist)


def stub_tags(seconds_to_drain: float = 0.0) -> TagLane:
    return cast(TagLane, StubTagLane(seconds_to_drain))


def no_deadline() -> float:
    return float('inf')


def clock_reading(*readings: float) -> Callable[[], float]:
    remaining = iter(readings)
    return lambda: next(remaining)


class RecordingMatching(TestCase):
    def test_rejects_a_title_extended_with_bare_words(self) -> None:
        self.assertFalse(is_same_recording('Home', 'Home on The Range'))
        self.assertFalse(is_same_recording('Free', 'Free From Desire'))
        self.assertFalse(is_same_recording('Drugs', '(Never Been To) Drugs With Friends'))

    def test_keeps_a_qualifier_tidal_adds_or_drops(self) -> None:
        self.assertTrue(is_same_recording('Mr. White', 'Mr. White [Mix Cut]'))
        self.assertTrue(is_same_recording('KMB2013', 'KMB2013 (10 Inch Version)'))
        self.assertTrue(is_same_recording('Ikigai (Orbe Remix)', 'Ikigai'))

    def test_keeps_a_numbered_ep_track(self) -> None:
        self.assertTrue(is_same_recording("You Don't Fool Me", "You Don't Fool Me 1"))


class MostConfident(TestCase):
    def test_the_most_confidently_identified_track_leads(self) -> None:
        confidence = {'doubtful': 1.0, 'certain': 3.0, 'likely': 2.0}

        self.assertEqual(['certain', 'likely', 'doubtful'], most_confident(confidence))

    def test_an_exact_tie_is_ordered_deterministically_rather_than_by_dict_order(self) -> None:
        forwards = most_confident({'b': 1.0, 'a': 1.0})
        backwards = most_confident({'a': 1.0, 'b': 1.0})

        self.assertEqual(forwards, backwards)
        self.assertEqual(['a', 'b'], forwards)

    def test_it_ranks_everything_so_the_anneal_can_backfill(self) -> None:
        confidence = {str(track_id): 1.0 for track_id in range(500)}

        self.assertEqual(500, len(most_confident(confidence)))

    def test_nothing_scored_ranks_nothing(self) -> None:
        self.assertEqual([], most_confident({}))


class VouchingForACandidate(TestCase):
    def test_the_candidates_own_artist_speaks_first_and_loudest(self) -> None:
        vouches = vouches_for('Yagya', radio_of(*[f'Neighbour {n}' for n in range(10)]))

        self.assertEqual(Vouch(1.0, 'Yagya'), vouches[0])

    def test_a_neighbour_returned_lower_vouches_less(self) -> None:
        vouches = vouches_for('Yagya', radio_of(*[f'Neighbour {n}' for n in range(20)]))

        self.assertGreater(vouches[1].weight, vouches[-1].weight)

    def test_only_the_head_of_the_radio_vouches(self) -> None:
        vouches = vouches_for('Yagya', radio_of(*[f'Neighbour {n}' for n in range(100)]))

        self.assertEqual(['Yagya', *[f'Neighbour {n}' for n in range(10)]],
                         [vouch.artist for vouch in vouches])

    def test_a_longer_radio_yields_proportionally_more_vouches(self) -> None:
        short = vouches_for('Yagya', radio_of(*[f'Neighbour {n}' for n in range(20)]))
        long = vouches_for('Yagya', radio_of(*[f'Neighbour {n}' for n in range(40)]))

        self.assertEqual(2 * (len(short) - 1), len(long) - 1)

    def test_rows_credited_to_the_candidates_own_artist_are_not_counted_twice(self) -> None:
        vouches = vouches_for('Yagya', radio_of('Yagya', 'Deepbass', 'yagya', 'Fluxion'))

        self.assertEqual(['Yagya'], [vouch.artist for vouch in vouches])

    def test_an_empty_radio_leaves_the_candidate_speaking_for_itself(self) -> None:
        self.assertEqual([Vouch(1.0, 'Yagya')], vouches_for('Yagya', []))


class ArtistTags(TestCase):
    def test_last_fm_tags_are_used_when_last_fm_knows_the_artist(self) -> None:
        last_fm = stub_last_fm({'Yagya': {'dub techno': 100.0}})
        discogs = stub_discogs({'Yagya': {'House': 4.0}})

        self.assertEqual({'dub techno': 1.0}, artist_tags(last_fm, discogs, 'Yagya'))
        self.assertEqual([], cast(StubDiscogs, discogs).asked)

    def test_discogs_styles_fill_in_only_when_last_fm_is_silent(self) -> None:
        last_fm = stub_last_fm({})
        discogs = stub_discogs({'Yagya': {'Dub Techno': 8.0, 'Ambient': 4.0}})

        self.assertEqual({'Dub Techno': 1.0, 'Ambient': 0.5}, artist_tags(last_fm, discogs, 'Yagya'))

    def test_an_artist_neither_source_knows_has_no_tags_rather_than_failing(self) -> None:
        self.assertEqual({}, artist_tags(stub_last_fm({}), stub_discogs(), 'Nobody'))


class BackgroundTagLane(TestCase):
    def test_an_artist_asked_for_twice_is_looked_up_once(self) -> None:
        asked: List[str] = []

        def record(artist: str) -> TagVector:
            asked.append(artist)
            return {}

        with ThreadPoolExecutor(max_workers=1) as pool:
            lane = TagLane(pool, record, 0.0)
            lane.request('Yagya')
            lane.request('Yagya')

            self.assertEqual({'Yagya': {}}, lane.drained())
        self.assertEqual(['Yagya'], asked)

    def test_what_it_still_owes_is_priced_at_its_own_rate(self) -> None:
        released = Event()

        def wait_to_be_released(_artist: str) -> TagVector:
            released.wait()
            return {}

        with ThreadPoolExecutor(max_workers=1) as pool:
            lane = TagLane(pool, wait_to_be_released, 2.0)
            lane.request('Yagya')
            lane.request('Deepbass')
            owed = lane.seconds_to_drain
            released.set()
            lane.drained()

        self.assertEqual(4.0, owed)
        self.assertEqual(0.0, lane.seconds_to_drain)

    def test_draining_returns_the_tags_of_every_artist_it_was_asked_for(self) -> None:
        known: Dict[str, TagVector] = {'Yagya': {'dub techno': 1.0}}

        with ThreadPoolExecutor(max_workers=1) as pool:
            lane = TagLane(pool, lambda artist: known.get(artist, {}), 0.0)
            lane.request('Yagya')
            lane.request('Nobody')

            self.assertEqual({'Yagya': {'dub techno': 1.0}, 'Nobody': {}}, lane.drained())


class GatheringEvidence(TestCase):
    def test_only_a_mixesdb_candidate_can_reach_the_playlist(self) -> None:
        candidate = MixTrack(artist='Basic Channel', title='Q1.1')
        tidal = stub_tidal({'Q1.1': radio_of('Rhythm & Sound', 'Maurizio')})

        evidence = gather_evidence(tidal, stub_tags(), [candidate], PLAYLIST_SIZE, no_deadline)

        self.assertEqual([str(tidal_id('Q1.1'))], [item.track_id for item in evidence])

    def test_a_candidate_is_vouched_for_by_its_own_artist_and_its_radio_neighbours(self) -> None:
        candidate = MixTrack(artist='Basic Channel', title='Q1.1')
        tidal = stub_tidal({'Q1.1': radio_of(*[f'Neighbour {n}' for n in range(10)])})

        evidence = gather_evidence(tidal, stub_tags(), [candidate], PLAYLIST_SIZE, no_deadline)

        self.assertEqual(['Basic Channel', 'Neighbour 0'],
                         [vouch.artist for vouch in evidence[0].vouches])

    def test_a_candidate_tidal_cannot_resolve_contributes_nothing(self) -> None:
        missing = MixTrack(artist='Nobody', title='Unfindable')
        found = MixTrack(artist='Yagya', title='Rigning')
        tidal = stub_tidal({'Rigning': radio_of('Deepbass')})

        evidence = gather_evidence(tidal, stub_tags(), [missing, found], PLAYLIST_SIZE, no_deadline)

        self.assertEqual([str(tidal_id('Rigning'))], [item.track_id for item in evidence])

    def test_a_candidate_without_a_tempo_is_skipped_before_its_radio_is_read(self) -> None:
        untimed = MixTrack(artist='Basement Dubs', title='Untimed')
        tidal = stub_tidal({'Untimed': radio_of('Deepbass')}, untimed={'Untimed'})

        evidence = gather_evidence(tidal, stub_tags(), [untimed], PLAYLIST_SIZE, no_deadline)

        self.assertEqual([], evidence)
        self.assertEqual([], cast(StubTidal, tidal).radios_read)

    def test_a_candidate_with_an_empty_radio_still_speaks_for_itself(self) -> None:
        silent = MixTrack(artist='Obscurity', title='Untitled')
        tidal = stub_tidal({'Untitled': []})

        evidence = gather_evidence(tidal, stub_tags(), [silent], PLAYLIST_SIZE, no_deadline)

        self.assertEqual([Vouch(1.0, 'Obscurity')], evidence[0].vouches)

    def test_it_asks_for_the_tags_of_every_artist_that_vouches(self) -> None:
        candidate = MixTrack(artist='Basic Channel', title='Q1.1')
        tidal = stub_tidal({'Q1.1': radio_of(*[f'Neighbour {n}' for n in range(20)])})
        tags = stub_tags()

        gather_evidence(tidal, tags, [candidate], PLAYLIST_SIZE, no_deadline)

        self.assertEqual(['Basic Channel', 'Neighbour 0', 'Neighbour 1'],
                         cast(StubTagLane, tags).asked)

    def test_reading_stops_when_the_time_left_is_needed_to_write_the_playlist(self) -> None:
        candidates = [MixTrack(artist=f'Artist {n}', title=f'Track {n}') for n in range(5)]
        tidal = stub_tidal({f'Track {n}': radio_of('Deepbass') for n in range(5)},
                           seconds_per_request=1.0)

        gather_evidence(tidal, stub_tags(), candidates, 1, clock_reading(6.0, 5.0, 4.0, 2.0))

        self.assertEqual(['Track 0', 'Track 1'], cast(StubTidal, tidal).radios_read)


class GenreConfidences(TestCase):
    def test_the_rarity_is_measured_over_the_evidence_and_never_over_the_style_roster(self) -> None:
        candidates = [MixTrack(artist='Deepbass', title='Ritual'),
                      MixTrack(artist='Luomo', title='Body Speaking')]
        tidal = stub_tidal({'Ritual': [], 'Body Speaking': []})
        last_fm = stub_last_fm({'Roster One': {'dub techno': 100.0}, 'Roster Two': {'dub techno': 100.0},
                                'Deepbass': {'dub techno': 100.0}, 'Luomo': {'deep house': 100.0}},
                               roster=['Roster One', 'Roster Two'])

        confidence = genre_confidences(tidal, last_fm, stub_discogs(), candidates, style='Dub Techno',
                                       playlist_size=PLAYLIST_SIZE, seconds_left=no_deadline)

        self.assertGreater(confidence[str(tidal_id('Ritual'))], 0.0)
        self.assertEqual(0.0, confidence[str(tidal_id('Body Speaking'))])


class ReadingBudget(TestCase):
    def test_there_is_time_while_a_candidate_costs_less_than_the_slack(self) -> None:
        self.assertTrue(time_to_read_again(100.0, 2.0, 1.0))
        self.assertTrue(time_to_read_again(3.0, 2.0, 1.0))
        self.assertFalse(time_to_read_again(2.0, 2.0, 1.0))

    def test_before_anything_is_read_a_candidate_is_priced_as_a_search_and_a_radio(self) -> None:
        self.assertEqual(2.0, seconds_per_candidate(stub_tidal({}, seconds_per_request=1.0), 0, 0))

    def test_a_candidate_costs_a_search_plus_a_radio_for_the_share_that_carried_a_tempo(self) -> None:
        tidal = stub_tidal({}, seconds_per_request=1.0)

        self.assertEqual(1.5, seconds_per_candidate(tidal, 1, 2))
        self.assertEqual(1.0, seconds_per_candidate(tidal, 0, 4))

    def test_the_reserve_covers_the_playlist_write_and_what_the_tag_lane_still_owes(self) -> None:
        tidal = stub_tidal({}, seconds_per_request=1.0)

        self.assertEqual(103.0, seconds_to_finish(tidal, stub_tags(3.0), PLAYLIST_SIZE))


class ReachingTheCorpus(TestCase):
    def test_the_playlist_write_is_reserved_before_anything_is_reached(self) -> None:
        tidal = stub_tidal({}, seconds_per_request=1.0)

        self.assertEqual(800.0, corpus_the_clock_can_reach(tidal, 900.0, PLAYLIST_SIZE))

    def test_an_endless_clock_reaches_everything(self) -> None:
        tidal = stub_tidal({}, seconds_per_request=1.0)

        self.assertEqual(float('inf'), corpus_the_clock_can_reach(tidal, float('inf'), PLAYLIST_SIZE))


class MixableSelection(TestCase):
    def test_an_untimed_track_is_dropped_however_well_recommended(self) -> None:
        tempos = {'timed': 126, 'untimed': None}

        selected = mixable_selection(['untimed', 'timed'], tempos.get, 2)

        self.assertEqual(['timed'], selected)

    def test_a_tempo_outlier_is_excluded_from_the_selection(self) -> None:
        tempos = {'a': 126, 'b': 127, 'c': 125, 'outlier': 165}

        selected = mixable_selection(['a', 'b', 'c', 'outlier'], tempos.get, 3)

        self.assertEqual(['a', 'b', 'c'], selected)

    def test_a_track_the_span_drops_is_backfilled_from_further_down(self) -> None:
        tempos = {'a': 126, 'b': 127, 'far': 165, 'backfill': 125}

        selected = mixable_selection(['a', 'b', 'far', 'backfill'], tempos.get, 3)

        self.assertEqual(['a', 'b', 'backfill'], selected)

    def test_it_keeps_the_recommendation_order(self) -> None:
        tempos = {'first': 127, 'second': 125}

        self.assertEqual(['first', 'second'], mixable_selection(['first', 'second'], tempos.get, 2))

    def test_a_zero_tempo_is_untimed(self) -> None:
        tempos = {'zero': 0, 'timed': 126}

        self.assertEqual(['timed'], mixable_selection(['zero', 'timed'], tempos.get, 2))

    def test_the_whole_selection_fits_inside_one_pitch_fader(self) -> None:
        tempos = {f't{n}': tempo for n, tempo in enumerate(
            [126, 122, 130, 118, 134, 127, 124, 129, 121, 131, 125, 128])}

        selected = mixable_selection(list(tempos), tempos.get, 6)
        chosen = [tempos[track_id] for track_id in selected]

        self.assertEqual(6, len(selected))
        self.assertLessEqual(max(chosen) / min(chosen), 1.0 + PITCH_FADER_RANGE)

    def test_nothing_timed_selects_nothing(self) -> None:
        untimed: Dict[str, Optional[int]] = {'a': None}

        self.assertEqual([], mixable_selection(['a'], untimed.get, 1))
        self.assertEqual([], mixable_selection([], untimed.get, 1))


class AnnealedSelection(TestCase):
    def test_the_most_recommended_are_kept_when_they_already_fit(self) -> None:
        timed = timed_tracks(a=126.0, b=124.0, c=128.0, d=130.0, e=200.0)

        self.assertEqual(['a', 'b', 'c', 'd'],
                         [track.track_id for track in annealed_selection(timed, 4)])

    def test_an_outlier_is_dropped_and_backfilled_from_further_down(self) -> None:
        timed = timed_tracks(a=126.0, wild=200.0, b=124.0, c=128.0)

        selected = [track.track_id for track in annealed_selection(timed, 3)]

        self.assertEqual(['a', 'b', 'c'], selected)

    def test_the_selection_never_exceeds_the_pitch_fader(self) -> None:
        timed = timed_tracks(a=120.0, b=140.0, c=121.0, d=122.0, e=123.0)

        selected = annealed_selection(timed, 4)
        tempos = [track.tempo for track in selected]

        self.assertEqual(4, len(selected))
        self.assertLessEqual(max(tempos) / min(tempos), 1.0 + PITCH_FADER_RANGE)

    def test_it_keeps_a_spread_rather_than_one_tempo(self) -> None:
        timed = timed_tracks(a=122.0, b=126.0, c=130.0, d=124.0)

        tempos = {track.tempo for track in annealed_selection(timed, 4)}

        self.assertEqual(4, len(tempos))

    def test_a_pool_that_cannot_fill_returns_what_fits(self) -> None:
        timed = timed_tracks(a=126.0, wild=300.0)

        self.assertEqual(['a'], [track.track_id for track in annealed_selection(timed, 2)])


class StubMixesDb:
    def __init__(self, by_months: Dict[int, int]) -> None:
        self.by_months = by_months
        self.asked: List[int] = []

    def get_tracklists(self, query: str) -> List[Tracklist]:
        months = int(query)
        self.asked.append(months)
        available = self.by_months[max(m for m in self.by_months if m <= months)]
        return [mix(*[MixTrack(artist=f'a{n}', title=f't{n}') for n in range(available)])]


def stub_mixes_db(by_months: Dict[int, int]) -> MixesDb:
    return cast(MixesDb, StubMixesDb(by_months))


class WideningCorpus(TestCase):
    def test_a_window_the_clock_cannot_walk_out_of_is_not_widened(self) -> None:
        mixes_db = stub_mixes_db({WINDOW_MONTHS: 250})

        _, candidates = widened_corpus(mixes_db, str, PLAYLIST_SIZE)

        self.assertEqual(250, len(candidates))
        self.assertEqual([WINDOW_MONTHS], cast(StubMixesDb, mixes_db).asked)

    def test_a_thin_window_widens_until_the_clock_could_not_walk_it_all(self) -> None:
        mixes_db = stub_mixes_db({WINDOW_MONTHS: 20, WINDOW_MONTHS + WIDENING_MONTHS: 60,
                                  WINDOW_MONTHS + 2 * WIDENING_MONTHS: 140})

        _, candidates = widened_corpus(mixes_db, str, PLAYLIST_SIZE)

        self.assertEqual(140, len(candidates))
        self.assertEqual([WINDOW_MONTHS, WINDOW_MONTHS + WIDENING_MONTHS,
                          WINDOW_MONTHS + 2 * WIDENING_MONTHS], cast(StubMixesDb, mixes_db).asked)

    def test_widening_stops_once_a_wider_window_adds_nothing(self) -> None:
        mixes_db = stub_mixes_db({WINDOW_MONTHS: 30})

        _, candidates = widened_corpus(mixes_db, str, PLAYLIST_SIZE)

        self.assertEqual(30, len(candidates))
        self.assertEqual([WINDOW_MONTHS, WINDOW_MONTHS + WIDENING_MONTHS], cast(StubMixesDb, mixes_db).asked)


class CorpusCandidates(TestCase):
    def test_a_track_two_mixes_played_is_one_candidate(self) -> None:
        shared = MixTrack(artist='Yagya', title='Sleepygirl 1')
        other = MixTrack(artist='Rrose', title='Triplicate')

        candidates = candidates_from([mix(shared, other), mix(shared)])

        self.assertEqual([shared, other], candidates)

    def test_it_takes_one_track_from_every_mix_before_taking_a_second(self) -> None:
        hottest = [MixTrack(artist='Basic Channel', title=f'Q{n}') for n in range(3)]
        coldest = [MixTrack(artist='Quantec', title=f'W{n}') for n in range(3)]

        candidates = candidates_from([mix(*hottest), mix(*coldest)])

        self.assertEqual([hottest[0], coldest[0], hottest[1], coldest[1], hottest[2], coldest[2]],
                         candidates)

    def test_the_hottest_mix_still_leads(self) -> None:
        hottest = MixTrack(artist='Basic Channel', title='Q1.1')
        coldest = MixTrack(artist='Quantec', title='Wintermute')

        self.assertEqual([hottest, coldest], candidates_from([mix(hottest), mix(coldest)]))

    def test_a_short_mix_does_not_cut_a_long_one_short(self) -> None:
        short = MixTrack(artist='Yagya', title='only')
        long = [MixTrack(artist='Rrose', title=f't{n}') for n in range(3)]

        candidates = candidates_from([mix(short), mix(*long)])

        self.assertEqual([short, *long], candidates)

    def test_no_tracklists_yield_no_candidates(self) -> None:
        self.assertEqual([], candidates_from([]))


class ReachableCandidates(TestCase):
    def test_the_rate_so_far_predicts_how_many_more_the_clock_allows(self) -> None:
        self.assertEqual(30, reachable_candidates(10, 100.0, 200.0, 500))

    def test_it_never_promises_more_than_the_corpus_holds(self) -> None:
        self.assertEqual(12, reachable_candidates(10, 1.0, 1000.0, 12))

    def test_before_anything_is_read_the_whole_corpus_is_the_estimate(self) -> None:
        self.assertEqual(500, reachable_candidates(0, 0.0, 900.0, 500))
        self.assertEqual(500, reachable_candidates(3, 0.0, 900.0, 500))

    def test_no_time_left_reaches_nothing_further(self) -> None:
        self.assertEqual(10, reachable_candidates(10, 100.0, 0.0, 500))

    def test_a_clock_that_never_runs_out_reaches_the_whole_corpus(self) -> None:
        endless = float('inf')

        self.assertEqual(500, reachable_candidates(10, endless - endless, endless, 500))
        self.assertEqual(500, reachable_candidates(10, 100.0, endless, 500))
