from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, cast
from unittest import TestCase

from src.last_fm import LastFmTrack
from src.mixes_db import MixTrack, Tracklist
from src.playlist import (
    HOTTEST_MIX_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    gather_recommendations,
    is_same_recording,
    mix_weight,
    most_recommended,
    time_to_seed_again,
    weigh_candidates,
    weighted_draw
)
from src.tidal import Tidal

TODAY = date(2026, 9, 3)
HALF_LIFE_DAYS = int(RECENCY_HALF_LIFE_DAYS)

SHARED = MixTrack(artist='Yagya', title='Sleepygirl 1')
ONLY_IN_HOTTER = MixTrack(artist='Zonal', title='Wrecked')
ONLY_IN_COLDER = MixTrack(artist='Skee Mask', title='Session Add')

POOL = {MixTrack(artist=f'Artist {n}', title=f'Track {n}'): 1.0 + n for n in range(8)}

LIGHT = MixTrack(artist='Deepchord', title='Vantage Point')
MEDIUM = MixTrack(artist='Polygonia', title='Dreaming Trees')
HEAVY = MixTrack(artist='Rod Modell', title='Incense And Black Light')

LEADER_DRAWS = 300
MARGINAL_DRAWS = 10000

PLAYLIST_SIZE = 100


def mix(recorded_on: date, *tracks: MixTrack) -> Tracklist:
    return Tracklist(recorded_on=recorded_on, tracks=list(tracks))


@dataclass
class FoundTrack:
    id: int
    name: str


class StubTidal:
    def __init__(self, radios: Dict[str, List[int]], seconds_per_request: float) -> None:
        self.radios = radios
        self.seconds_per_request = seconds_per_request
        self.seeded: List[str] = []

    def seconds_to_set_playlist(self, playlist_size: int) -> float:
        return playlist_size * self.seconds_per_request

    def find_equivalent_track(self, last_fm_track: LastFmTrack, **_: object) -> Optional[FoundTrack]:
        title = last_fm_track.title
        return FoundTrack(hash(title), title) if title in self.radios else None

    def track_radio(self, track: FoundTrack) -> List[FoundTrack]:
        self.seeded.append(track.name)
        return [FoundTrack(recommended, f'track {recommended}') for recommended in self.radios[track.name]]


def stub_tidal(radios: Dict[str, List[int]], seconds_per_request: float = 0.0) -> Tidal:
    return cast(Tidal, StubTidal(radios, seconds_per_request))


def no_deadline() -> float:
    return float('inf')


def clock_reading(*readings: float) -> Callable[[], float]:
    remaining = iter(readings)
    return lambda: next(remaining)


class CandidateSelection(TestCase):
    def test_hotter_mixes_weigh_more(self) -> None:
        hottest, coldest = mix_weight(0, 100, 0), mix_weight(99, 100, 0)

        self.assertGreater(hottest, coldest)
        self.assertAlmostEqual(HOTTEST_MIX_WEIGHT ** 0.99, hottest / coldest)

    def test_an_undated_mix_dated_into_the_future_never_outweighs_a_fresh_one(self) -> None:
        fresh = mix_weight(0, 122, 0)

        self.assertEqual(fresh, mix_weight(0, 122, -1))
        self.assertEqual(fresh, mix_weight(0, 122, -HALF_LIFE_DAYS))
        self.assertEqual(fresh, mix_weight(0, 122, -365))

    def test_weigh_candidates_handles_a_mix_recorded_in_the_future(self) -> None:
        undated = date(TODAY.year, 7, 15)
        zero_division_day = undated - timedelta(days=HALF_LIFE_DAYS)
        weights = weigh_candidates([mix(undated, SHARED), mix(TODAY, ONLY_IN_HOTTER)], zero_division_day)

        self.assertTrue(all(weight > 0 for weight in weights.values()))

    def test_older_mixes_weigh_less(self) -> None:
        self.assertAlmostEqual(mix_weight(3, 10, 0) / 2, mix_weight(3, 10, HALF_LIFE_DAYS))
        self.assertGreater(mix_weight(3, 10, 0), mix_weight(3, 10, 1))

    def test_weights_sum_across_mixes(self) -> None:
        weights = weigh_candidates([
            mix(date(2026, 8, 1), SHARED, ONLY_IN_HOTTER),
            mix(date(2026, 7, 1), SHARED, ONLY_IN_COLDER)
        ], TODAY)

        self.assertGreater(weights[SHARED], weights[ONLY_IN_HOTTER])
        self.assertGreater(weights[SHARED], weights[ONLY_IN_COLDER])
        self.assertAlmostEqual(weights[ONLY_IN_HOTTER] + weights[ONLY_IN_COLDER], weights[SHARED])

    def test_weigh_candidates_deduplicates(self) -> None:
        weights = weigh_candidates([
            mix(date(2026, 8, 1), SHARED),
            mix(date(2026, 7, 1), SHARED),
            mix(date(2026, 6, 1), SHARED)
        ], TODAY)

        self.assertEqual(1, len(weights))
        self.assertEqual([SHARED], list(weights))

    def test_weighted_draw_returns_every_candidate_once(self) -> None:
        drawn = weighted_draw(POOL, 7)

        self.assertEqual(len(POOL), len(drawn))
        self.assertEqual(len(drawn), len(set(drawn)))
        self.assertEqual(set(POOL), set(drawn))
        self.assertEqual([], weighted_draw({}, 7))

    def test_weighted_draw_is_deterministic_for_a_seed(self) -> None:
        self.assertEqual(weighted_draw(POOL, 7), weighted_draw(POOL, 7))
        self.assertNotEqual(weighted_draw(POOL, 7), weighted_draw(POOL, 8))

    def test_weighted_draw_favours_heavier_tracks(self) -> None:
        weights = {HEAVY: 10.0, LIGHT: 1.0}
        leaders = Counter(weighted_draw(weights, random_seed)[0] for random_seed in range(LEADER_DRAWS))

        self.assertEqual(LEADER_DRAWS, leaders[HEAVY] + leaders[LIGHT])
        self.assertGreater(leaders[HEAVY], 3 * leaders[LIGHT])

    def test_weighted_draw_matches_the_exponential_race_marginals(self) -> None:
        weights = {LIGHT: 1.0, MEDIUM: 2.0, HEAVY: 7.0}
        leaders = Counter(weighted_draw(weights, random_seed)[0] for random_seed in range(MARGINAL_DRAWS))

        self.assertAlmostEqual(0.1, leaders[LIGHT] / MARGINAL_DRAWS, delta=0.03)
        self.assertAlmostEqual(0.2, leaders[MEDIUM] / MARGINAL_DRAWS, delta=0.03)
        self.assertAlmostEqual(0.7, leaders[HEAVY] / MARGINAL_DRAWS, delta=0.03)


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


class MostRecommended(TestCase):
    def test_the_most_widely_recommended_track_leads(self) -> None:
        recommended = {'rare': [1.0], 'everywhere': [1.0, 1.0, 1.0], 'common': [1.0, 1.0]}

        self.assertEqual(['everywhere', 'common', 'rare'], most_recommended(recommended, 3))

    def test_a_tie_on_seed_count_is_broken_by_the_weight_behind_it(self) -> None:
        recommended = {'light': [1.0, 1.0], 'heavy': [5.0, 5.0]}

        self.assertEqual(['heavy', 'light'], most_recommended(recommended, 2))

    def test_an_exact_tie_is_ordered_deterministically_rather_than_by_dict_order(self) -> None:
        forwards = most_recommended({'b': [1.0], 'a': [1.0]}, 2)
        backwards = most_recommended({'a': [1.0], 'b': [1.0]}, 2)

        self.assertEqual(forwards, backwards)
        self.assertEqual(['a', 'b'], forwards)

    def test_it_never_returns_more_than_the_playlist_holds(self) -> None:
        recommended = {str(track_id): [1.0] for track_id in range(500)}

        self.assertEqual(PLAYLIST_SIZE, len(most_recommended(recommended, PLAYLIST_SIZE)))

    def test_nothing_recommended_returns_nothing(self) -> None:
        self.assertEqual([], most_recommended({}, PLAYLIST_SIZE))


class GatheringRecommendations(TestCase):
    def test_every_seed_that_resolves_votes_for_its_whole_radio(self) -> None:
        seed = MixTrack(artist='Basic Channel', title='Q1.1')
        tidal = stub_tidal({'Q1.1': [10, 11, 12]})

        recommended = gather_recommendations(tidal, [seed], {seed: 2.0}, PLAYLIST_SIZE, no_deadline)

        self.assertEqual({'10', '11', '12'}, set(recommended))
        self.assertEqual([2.0], recommended['10'])

    def test_a_track_two_seeds_recommend_carries_both_their_weights(self) -> None:
        hotter = MixTrack(artist='Rrose', title='Triplicate')
        colder = MixTrack(artist='Quantec', title='Wintermute')
        tidal = stub_tidal({'Triplicate': [10, 11], 'Wintermute': [10, 12]})

        recommended = gather_recommendations(
            tidal, [hotter, colder], {hotter: 3.0, colder: 1.0}, PLAYLIST_SIZE, no_deadline)

        self.assertEqual([3.0, 1.0], recommended['10'])
        self.assertEqual([3.0], recommended['11'])

    def test_a_seed_tidal_cannot_resolve_is_skipped_rather_than_failing(self) -> None:
        missing = MixTrack(artist='Nobody', title='Unfindable')
        found = MixTrack(artist='Yagya', title='Rigning')
        tidal = stub_tidal({'Rigning': [10]})

        recommended = gather_recommendations(
            tidal, [missing, found], {missing: 1.0, found: 1.0}, PLAYLIST_SIZE, no_deadline)

        self.assertEqual({'10'}, set(recommended))

    def test_a_seed_with_an_empty_radio_contributes_nothing(self) -> None:
        silent = MixTrack(artist='Obscurity', title='Untitled')
        tidal = stub_tidal({'Untitled': []})

        self.assertEqual({}, gather_recommendations(tidal, [silent], {silent: 1.0}, PLAYLIST_SIZE, no_deadline))

    def test_seeding_stops_when_the_time_left_is_needed_to_write_the_playlist(self) -> None:
        seeds = [MixTrack(artist=f'Artist {n}', title=f'Track {n}') for n in range(5)]
        tidal = stub_tidal({f'Track {n}': [n] for n in range(5)}, seconds_per_request=1.0)

        gather_recommendations(tidal, seeds, {seed: 1.0 for seed in seeds}, 1, clock_reading(5.0, 4.0, 2.0))

        self.assertEqual(['Track 0', 'Track 1'], cast(StubTidal, tidal).seeded)


class SeedingBudget(TestCase):
    def test_there_is_time_while_seeding_costs_less_than_the_slack(self) -> None:
        tidal = stub_tidal({}, seconds_per_request=1.0)

        self.assertTrue(time_to_seed_again(tidal, 100.0, 1))
        self.assertTrue(time_to_seed_again(tidal, 3.0, 1))
        self.assertFalse(time_to_seed_again(tidal, 2.0, 1))

    def test_a_free_request_always_leaves_time(self) -> None:
        self.assertTrue(time_to_seed_again(stub_tidal({}), 0.0, PLAYLIST_SIZE))
