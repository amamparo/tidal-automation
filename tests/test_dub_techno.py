from collections import Counter
from datetime import date, timedelta
from typing import Optional, Set
from unittest import TestCase

from src.mixes_db import MixTrack, Tracklist
from src.update_dub_techno import (
    DISCOURAGED_STYLE_PENALTY,
    HOTTEST_MIX_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    is_same_recording,
    mix_weight,
    weigh_candidates,
    weighted_draw
)

TODAY = date(2026, 9, 3)
NO_STYLES: Set[str] = set()
HALF_LIFE_DAYS = int(RECENCY_HALF_LIFE_DAYS)

SHARED = MixTrack(artist='Yagya', title='Sleepygirl 1')
ONLY_IN_HOTTER = MixTrack(artist='Zonal', title='Wrecked')
ONLY_IN_COLDER = MixTrack(artist='Skee Mask', title='Session Add')

POOL = {MixTrack(artist=f'Artist {n}', title=f'Track {n}'): 1.0 + n for n in range(8)}

LIGHT = MixTrack(artist='Deepchord', title='Vantage Point')
MEDIUM = MixTrack(artist='Polygonia', title='Dreaming Trees')
HEAVY = MixTrack(artist='Rod Modell', title='Incense And Black Light')

LEADER_SEEDS = 300
MARGINAL_SEEDS = 10000


def unstyled_weight(rank: int, mix_count: int, age_days: int) -> float:
    return mix_weight(rank, mix_count, age_days, NO_STYLES)


def mix(recorded_on: date, *tracks: MixTrack, categories: Optional[Set[str]] = None) -> Tracklist:
    return Tracklist(mix_title=f'{recorded_on} - Mix', recorded_on=recorded_on, tracks=list(tracks),
                     categories=set(categories or ()))


class DubTechnoSelection(TestCase):
    def test_hotter_mixes_weigh_more(self) -> None:
        self.assertGreater(unstyled_weight(0, 100, 0), unstyled_weight(99, 100, 0))
        hottest, coldest = unstyled_weight(0, 100, 0), unstyled_weight(99, 100, 0)

        self.assertAlmostEqual(HOTTEST_MIX_WEIGHT ** 0.99, hottest / coldest)

    def test_an_undated_mix_dated_into_the_future_never_outweighs_a_fresh_one(self) -> None:
        fresh = unstyled_weight(0, 122, 0)

        self.assertEqual(fresh, unstyled_weight(0, 122, -1))
        self.assertEqual(fresh, unstyled_weight(0, 122, -HALF_LIFE_DAYS))
        self.assertEqual(fresh, unstyled_weight(0, 122, -365))

    def test_weigh_candidates_handles_a_mix_recorded_in_the_future(self) -> None:
        undated = date(TODAY.year, 7, 15)
        zero_division_day = undated - timedelta(days=HALF_LIFE_DAYS)
        weights = weigh_candidates([mix(undated, SHARED), mix(TODAY, ONLY_IN_HOTTER)], zero_division_day)

        self.assertTrue(all(weight > 0 for weight in weights.values()))

    def test_older_mixes_weigh_less(self) -> None:
        self.assertAlmostEqual(unstyled_weight(3, 10, 0) / 2, unstyled_weight(3, 10, HALF_LIFE_DAYS))
        self.assertGreater(unstyled_weight(3, 10, 0), unstyled_weight(3, 10, 1))

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
        leaders = Counter(weighted_draw({HEAVY: 10.0, LIGHT: 1.0}, seed)[0] for seed in range(LEADER_SEEDS))

        self.assertEqual(LEADER_SEEDS, leaders[HEAVY] + leaders[LIGHT])
        self.assertGreater(leaders[HEAVY], 3 * leaders[LIGHT])

    def test_weighted_draw_matches_the_exponential_race_marginals(self) -> None:
        weights = {LIGHT: 1.0, MEDIUM: 2.0, HEAVY: 7.0}
        leaders = Counter(weighted_draw(weights, seed)[0] for seed in range(MARGINAL_SEEDS))

        self.assertAlmostEqual(0.1, leaders[LIGHT] / MARGINAL_SEEDS, delta=0.03)
        self.assertAlmostEqual(0.2, leaders[MEDIUM] / MARGINAL_SEEDS, delta=0.03)
        self.assertAlmostEqual(0.7, leaders[HEAVY] / MARGINAL_SEEDS, delta=0.03)

    def test_discouraged_styles_are_penalised_hardest_in_combination(self) -> None:
        plain = mix_weight(0, 10, 0, NO_STYLES)

        self.assertAlmostEqual(plain * DISCOURAGED_STYLE_PENALTY, mix_weight(0, 10, 0, {'Ambient'}))
        self.assertAlmostEqual(plain * DISCOURAGED_STYLE_PENALTY, mix_weight(0, 10, 0, {'IDM'}))
        self.assertAlmostEqual(plain * DISCOURAGED_STYLE_PENALTY ** 2,
                               mix_weight(0, 10, 0, {'Ambient', 'IDM'}))

    def test_an_unrelated_tag_costs_nothing(self) -> None:
        self.assertEqual(mix_weight(0, 10, 0, NO_STYLES), mix_weight(0, 10, 0, {'Dub', 'Reggae'}))

    def test_the_penalty_reaches_weigh_candidates(self) -> None:
        rhythmic = MixTrack(artist='Yagya', title='Rhythmic')
        ambient = MixTrack(artist='Loscil', title='Beatless')
        weights = weigh_candidates([
            mix(TODAY, rhythmic, categories={'Dub Techno'}),
            mix(TODAY, ambient, categories={'Dub Techno', 'Ambient'})
        ], TODAY)

        self.assertGreater(weights[rhythmic], weights[ambient])

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
