from collections import Counter
from datetime import date, timedelta
from typing import Dict, cast
from unittest import TestCase

from src.last_fm import LastFm
from src.mixes_db import MixTrack, Tracklist
from src.playlist import (
    HOTTEST_MIX_WEIGHT,
    RECENCY_HALF_LIFE_DAYS,
    genre_affinity,
    genre_profile,
    is_same_recording,
    mix_weight,
    weigh_by_genre,
    weigh_candidates,
    weighted_draw
)

TODAY = date(2026, 9, 3)
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


def mix(recorded_on: date, *tracks: MixTrack) -> Tracklist:
    return Tracklist(recorded_on=recorded_on, tracks=list(tracks))


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
        leaders = Counter(weighted_draw({HEAVY: 10.0, LIGHT: 1.0}, seed)[0] for seed in range(LEADER_SEEDS))

        self.assertEqual(LEADER_SEEDS, leaders[HEAVY] + leaders[LIGHT])
        self.assertGreater(leaders[HEAVY], 3 * leaders[LIGHT])

    def test_weighted_draw_matches_the_exponential_race_marginals(self) -> None:
        weights = {LIGHT: 1.0, MEDIUM: 2.0, HEAVY: 7.0}
        leaders = Counter(weighted_draw(weights, seed)[0] for seed in range(MARGINAL_SEEDS))

        self.assertAlmostEqual(0.1, leaders[LIGHT] / MARGINAL_SEEDS, delta=0.03)
        self.assertAlmostEqual(0.2, leaders[MEDIUM] / MARGINAL_SEEDS, delta=0.03)
        self.assertAlmostEqual(0.7, leaders[HEAVY] / MARGINAL_SEEDS, delta=0.03)


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


def stub_last_fm(tags: Dict[str, Dict[str, float]]) -> LastFm:
    class Stub:
        def top_tags(self, artist: str) -> Dict[str, float]:
            return tags.get(artist, {})

    return cast(LastFm, Stub())


TECHNO_CORPUS = {
    'Basic Channel': {'dub techno': 1.0, 'techno': 0.8, 'minimal': 0.4},
    'Rrose': {'techno': 1.0, 'minimal': 0.7, 'dub techno': 0.3},
    'Quantec': {'dub techno': 1.0, 'minimal': 0.6, 'ambient': 0.4},
    'Grace Jones': {'disco': 1.0, 'pop': 0.9, 'new wave': 0.8},
}


class GenreAffinity(TestCase):
    def test_the_profile_sums_tag_weights_across_artists(self) -> None:
        profile = genre_profile([{'techno': 1.0, 'dub': 0.5}, {'techno': 0.8, 'pop': 0.2}])

        self.assertEqual({'techno': 1.8, 'dub': 0.5, 'pop': 0.2}, dict(profile))

    def test_an_artist_who_is_the_profile_scores_one(self) -> None:
        profile = genre_profile([{'techno': 1.0, 'minimal': 0.5}])

        self.assertAlmostEqual(1.0, genre_affinity({'techno': 1.0, 'minimal': 0.5}, profile))

    def test_sharing_no_tags_with_the_profile_scores_zero(self) -> None:
        self.assertEqual(0.0, genre_affinity({'disco': 1.0}, {'techno': 1.0}))

    def test_an_untagged_artist_scores_zero_rather_than_dividing_by_zero(self) -> None:
        self.assertEqual(0.0, genre_affinity({}, {'techno': 1.0}))
        self.assertEqual(0.0, genre_affinity({'techno': 1.0}, {}))

    def test_the_profile_is_derived_from_the_corpus_not_declared(self) -> None:
        profile = genre_profile(TECHNO_CORPUS.values())

        self.assertEqual('dub techno', max(profile, key=lambda tag: profile[tag]))


class GenreWeighting(TestCase):
    def test_an_off_genre_artist_is_weighed_down(self) -> None:
        core = MixTrack(artist='Basic Channel', title='Q1.1')
        outlier = MixTrack(artist='Grace Jones', title='Private Life')
        corpus = {MixTrack(artist=name, title='x'): 1.0 for name in TECHNO_CORPUS}

        weighed = weigh_by_genre({**corpus, core: 1.0, outlier: 1.0}, stub_last_fm(TECHNO_CORPUS))

        self.assertGreater(weighed[core], weighed[outlier])

    def test_the_pool_itself_is_what_sinks_the_outlier(self) -> None:
        core = MixTrack(artist='Basic Channel', title='Q1.1')
        outlier = MixTrack(artist='Grace Jones', title='Private Life')
        corpus = {MixTrack(artist=name, title='x'): 1.0 for name in TECHNO_CORPUS}

        alone = weigh_by_genre({core: 1.0, outlier: 1.0}, stub_last_fm(TECHNO_CORPUS))
        crowded = weigh_by_genre({**corpus, core: 1.0, outlier: 1.0}, stub_last_fm(TECHNO_CORPUS))

        self.assertLess(crowded[outlier] / crowded[core], alone[outlier] / alone[core])

    def test_an_artist_last_fm_does_not_know_is_treated_as_typical(self) -> None:
        unknown = MixTrack(artist='Critical Digital', title="It's House")
        outlier = MixTrack(artist='Grace Jones', title='Private Life')
        known = {MixTrack(artist=name, title='x'): 1.0 for name in TECHNO_CORPUS}

        weighed = weigh_by_genre({**known, unknown: 1.0, outlier: 1.0}, stub_last_fm(TECHNO_CORPUS))

        self.assertGreater(weighed[unknown], weighed[outlier])
        self.assertLess(weighed[unknown], weighed[MixTrack(artist='Basic Channel', title='x')])

    def test_genre_weighting_preserves_the_relative_weight_of_one_artist(self) -> None:
        hotter = MixTrack(artist='Rrose', title='Hotter')
        colder = MixTrack(artist='Rrose', title='Colder')

        weighed = weigh_by_genre({hotter: 2.0, colder: 1.0}, stub_last_fm(TECHNO_CORPUS))

        self.assertAlmostEqual(2.0, weighed[hotter] / weighed[colder])
