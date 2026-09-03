from collections import Counter
from datetime import date, timedelta
from typing import Dict, Optional, Set
from unittest import TestCase

from src.mixes_db import MixTrack, Tracklist
from src.update_dub_techno import (
    DISCOURAGED_STYLE_PENALTY,
    STYLE_PRIORITIES,
    style_premiums,
    HOTTEST_MIX_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    mix_weight,
    style_multiplier,
    weigh_candidates,
    weighted_draw
)

TODAY = date(2026, 9, 3)
NO_STYLES: Set[str] = set()
NO_PREMIUMS: Dict[str, float] = {}
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


STYLED_CORPUS = [
    Tracklist('a', date(2026, 8, 1), [MixTrack('A', 'One')],
              {'Dub Techno', 'Minimal'}),
    Tracklist('b', date(2026, 8, 1), [MixTrack('B', 'Two')], {'Dub Techno', 'Techno'}),
    Tracklist('c', date(2026, 8, 1), [MixTrack('C', 'Three')], {'Minimal', 'Techno'}),
    Tracklist('d', date(2026, 8, 1), [MixTrack('D', 'Four')], {'Techno'})
]


def unstyled_weight(rank: int, mix_count: int, age_days: int) -> float:
    return mix_weight(rank, mix_count, age_days, NO_STYLES, NO_PREMIUMS)


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

    def test_premiums_cascade_with_dub_techno_ranked_highest(self) -> None:
        premiums = style_premiums(STYLED_CORPUS)
        ranked = [
            {'Dub Techno', 'Minimal', 'Techno'},
            {'Dub Techno', 'Minimal'},
            {'Dub Techno', 'Techno'},
            {'Dub Techno'},
            {'Minimal', 'Techno'},
            {'Minimal'},
            {'Techno'}
        ]
        multipliers = [style_multiplier(categories, premiums) for categories in ranked]

        self.assertEqual(multipliers, sorted(multipliers, reverse=True))
        self.assertEqual(len(set(multipliers)), len(multipliers))

    def test_dub_techno_outweighs_any_combination_without_it(self) -> None:
        premiums = style_premiums(STYLED_CORPUS)

        self.assertGreater(style_multiplier({'Dub Techno'}, premiums),
                           style_multiplier({'Minimal', 'Techno'}, premiums))

    def test_an_untagged_mix_gets_no_premium(self) -> None:
        self.assertEqual(1.0, style_multiplier({'House'}, style_premiums(STYLED_CORPUS)))

    def test_a_common_style_is_worth_less_per_mix_than_a_rare_one(self) -> None:
        premiums = style_premiums(STYLED_CORPUS)

        self.assertGreater(premiums['Dub Techno'], premiums['Techno'])
        expected = STYLE_PRIORITIES['Dub Techno'] * len(STYLED_CORPUS) / 2

        self.assertAlmostEqual(expected, premiums['Dub Techno'])

    def test_discouraged_styles_are_penalised_hardest_in_combination(self) -> None:
        self.assertEqual(DISCOURAGED_STYLE_PENALTY, style_multiplier({'Ambient'}, NO_PREMIUMS))
        self.assertEqual(DISCOURAGED_STYLE_PENALTY, style_multiplier({'IDM'}, NO_PREMIUMS))
        self.assertAlmostEqual(DISCOURAGED_STYLE_PENALTY ** 2,
                               style_multiplier({'Ambient', 'IDM'}, NO_PREMIUMS))
        self.assertGreater(style_multiplier({'Ambient'}, NO_PREMIUMS),
                           style_multiplier({'Ambient', 'IDM'}, NO_PREMIUMS))

    def test_a_premium_and_a_penalty_compose(self) -> None:
        premiums = style_premiums(STYLED_CORPUS)
        expected = (premiums['Dub Techno'] + premiums['Minimal']) * DISCOURAGED_STYLE_PENALTY

        self.assertAlmostEqual(expected, style_multiplier({'Dub Techno', 'Minimal', 'Ambient'}, premiums))

    def test_style_weighting_reaches_weigh_candidates(self) -> None:
        rhythmic = MixTrack(artist='Yagya', title='Rhythmic')
        ambient = MixTrack(artist='Loscil', title='Beatless')
        weights = weigh_candidates([
            mix(TODAY, rhythmic, categories={'Dub Techno', 'Minimal'}),
            mix(TODAY, ambient, categories={'Dub Techno', 'Ambient'})
        ], TODAY)

        self.assertGreater(weights[rhythmic], weights[ambient])

    def test_techno_only_mixes_are_outweighed_by_dub_techno_ones(self) -> None:
        dub = MixTrack(artist='Yagya', title='Dubby')
        techno = MixTrack(artist='Surgeon', title='Banger')
        weights = weigh_candidates([
            mix(TODAY, techno, categories={'Techno'}),
            mix(TODAY, dub, categories={'Dub Techno'})
        ], TODAY)

        self.assertGreater(weights[dub], weights[techno])
