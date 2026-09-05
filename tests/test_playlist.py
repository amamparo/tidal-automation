from collections import Counter
from datetime import date, timedelta
from math import sqrt
from typing import Dict, cast
from unittest import TestCase

from src.discogs import Discogs
from src.last_fm import LastFm
from src.mixes_db import MixTrack, Tracklist
from src.playlist import (
    HOTTEST_MIX_WEIGHT,
    MATCH_DEADLINE_SECONDS,
    RECENCY_HALF_LIFE_DAYS,
    genre_affinity,
    affordable_lookups,
    core_profile,
    emphasise_rare,
    genre_fingerprint,
    tag_rarity,
    genre_profile,
    is_same_recording,
    mix_weight,
    weigh_by_genre,
    weigh_candidates,
    weight_per_artist,
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


def stub_discogs(styles_by_artist: Dict[str, Dict[str, float]], seconds_per_request: float = 0.0) -> Discogs:
    class Stub:
        def __init__(self) -> None:
            self.seconds_per_request = seconds_per_request

        def styles(self, artist: str) -> Dict[str, float]:
            return styles_by_artist.get(artist, {})

    return cast(Discogs, Stub())


def no_deadline() -> float:
    return float('inf')


def barely_enough_time() -> float:
    return MATCH_DEADLINE_SECONDS + 5.0


TECHNO_CORPUS = {
    'Basic Channel': {'dub techno': 1.0, 'minimal': 0.6},
    'Rrose': {'techno': 1.0, 'minimal': 0.7},
    'Quantec': {'dub techno': 1.0, 'ambient': 0.5},
    'DeepChord': {'dub techno': 0.9, 'dub': 0.4},
    'Efdemin': {'techno': 1.0, 'minimal techno': 0.5},
    'Yagya': {'ambient techno': 0.9, 'minimal': 0.4},
    'Vainqueur': {'techno': 0.8, 'dub': 0.5},
    'Grace Jones': {'disco': 1.0, 'pop': 0.9, 'new wave': 0.8},
}

CORPUS_TRACKS = {MixTrack(artist=name, title='x'): 1.0 for name in TECHNO_CORPUS}
IN_GENRE = MixTrack(artist='Basic Channel', title='Q1.1')
OFF_GENRE = MixTrack(artist='Grace Jones', title='Private Life')
UNTAGGED = MixTrack(artist='Critical Digital', title="It's House")


class GenreAffinity(TestCase):
    def test_the_profile_sums_tag_weights_across_artists(self) -> None:
        profile = genre_profile([{'techno': 1.0, 'dub': 0.5}, {'techno': 0.8, 'pop': 0.2}])

        self.assertEqual({'techno': 1.8, 'dub': 0.5, 'pop': 0.2}, profile)

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


class GenreFingerprint(TestCase):
    def test_each_source_contributes_equally_whatever_its_scale(self) -> None:
        fingerprint = genre_fingerprint({'techno': 100.0, 'dub techno': 50.0}, {'house': 2.0})

        self.assertAlmostEqual(1.0, fingerprint['house'])
        self.assertAlmostEqual(1.0, sqrt(fingerprint['techno'] ** 2 + fingerprint['dub techno'] ** 2))

    def test_the_sources_add_where_they_agree(self) -> None:
        self.assertAlmostEqual(2.0, genre_fingerprint({'techno': 1.0}, {'techno': 5.0})['techno'])

    def test_an_empty_source_is_skipped_rather_than_dividing_by_zero(self) -> None:
        self.assertEqual({'techno': 1.0}, genre_fingerprint({'techno': 3.0}, {}))
        self.assertEqual({}, genre_fingerprint({}, {}))


class ArtistWeight(TestCase):
    def test_weight_sums_over_an_artists_tracks(self) -> None:
        per_artist = weight_per_artist({
            MixTrack(artist='Rrose', title='a'): 1.0,
            MixTrack(artist='Rrose', title='b'): 2.0,
            MixTrack(artist='Quantec', title='c'): 5.0
        })

        self.assertEqual({'Rrose': 3.0, 'Quantec': 5.0}, per_artist)


class GenreWeighting(TestCase):
    def test_an_off_genre_artist_is_weighed_down(self) -> None:
        pool = {**CORPUS_TRACKS, IN_GENRE: 1.0, OFF_GENRE: 1.0}

        weighed = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}), pool, no_deadline)

        self.assertGreater(weighed[IN_GENRE], weighed[OFF_GENRE])

    def test_the_pool_itself_is_what_sinks_the_outlier(self) -> None:
        pair = {IN_GENRE: 1.0, OFF_GENRE: 1.0}

        alone = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}), pair, no_deadline)
        crowded = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}),
                                 {**CORPUS_TRACKS, **pair}, no_deadline)

        self.assertLess(crowded[OFF_GENRE] / crowded[IN_GENRE], alone[OFF_GENRE] / alone[IN_GENRE])

    def test_an_artist_last_fm_does_not_know_is_treated_as_typical(self) -> None:
        pool = {**CORPUS_TRACKS, IN_GENRE: 1.0, UNTAGGED: 1.0, OFF_GENRE: 1.0}

        weighed = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}), pool, no_deadline)

        self.assertGreater(weighed[UNTAGGED], weighed[OFF_GENRE])
        self.assertLess(weighed[UNTAGGED], weighed[IN_GENRE])

    def test_genre_weighting_preserves_the_relative_weight_of_one_artist(self) -> None:
        hotter = MixTrack(artist='Rrose', title='Hotter')
        colder = MixTrack(artist='Rrose', title='Colder')

        weighed = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}), {hotter: 2.0, colder: 1.0}, no_deadline)

        self.assertAlmostEqual(2.0, weighed[hotter] / weighed[colder])


class DiscogsEnrichment(TestCase):
    def test_discogs_reaches_an_artist_last_fm_cannot(self) -> None:
        pool = {**CORPUS_TRACKS, IN_GENRE: 1.0, UNTAGGED: 1.0}
        off_genre_styles = stub_discogs({'Critical Digital': {'house': 3.0, 'disco': 2.0}})

        blind = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), stub_discogs({}), pool, no_deadline)
        seeing = weigh_by_genre(stub_last_fm(TECHNO_CORPUS), off_genre_styles, pool, no_deadline)

        self.assertLess(seeing[UNTAGGED] / seeing[IN_GENRE], blind[UNTAGGED] / blind[IN_GENRE])

    def test_enrichment_stops_rather_than_eating_the_matching_deadline(self) -> None:
        last_fm = stub_last_fm(TECHNO_CORPUS)
        pool = {**CORPUS_TRACKS, UNTAGGED: 1.0}
        styles = {'Critical Digital': {'house': 3.0}}

        unasked = weigh_by_genre(last_fm, stub_discogs({}), pool, barely_enough_time)
        affordable = weigh_by_genre(last_fm, stub_discogs(styles, seconds_per_request=1.0),
                                    pool, barely_enough_time)
        unaffordable = weigh_by_genre(last_fm, stub_discogs(styles, seconds_per_request=10.0),
                                      pool, barely_enough_time)

        self.assertNotAlmostEqual(unasked[UNTAGGED], affordable[UNTAGGED])
        self.assertAlmostEqual(unasked[UNTAGGED], unaffordable[UNTAGGED])


class AffordableLookups(TestCase):
    def test_the_budget_caps_the_count(self) -> None:
        self.assertEqual(50, affordable_lookups(500, MATCH_DEADLINE_SECONDS + 100.0, 2.0))

    def test_it_never_promises_more_than_was_asked_for(self) -> None:
        self.assertEqual(3, affordable_lookups(3, MATCH_DEADLINE_SECONDS + 1000.0, 2.0))

    def test_no_budget_left_reaches_nobody(self) -> None:
        self.assertEqual(0, affordable_lookups(500, MATCH_DEADLINE_SECONDS, 2.0))
        self.assertEqual(0, affordable_lookups(500, MATCH_DEADLINE_SECONDS - 60.0, 2.0))

    def test_a_free_request_is_unbounded_rather_than_dividing_by_zero(self) -> None:
        self.assertEqual(500, affordable_lookups(500, 0.0, 0.0))


class TagRarity(TestCase):
    def test_a_tag_on_every_artist_carries_no_weight(self) -> None:
        rarity = tag_rarity([{'electronic': 1.0, 'dub techno': 1.0},
                             {'electronic': 1.0},
                             {'electronic': 1.0}])

        self.assertLess(rarity['electronic'], rarity['dub techno'])
        self.assertEqual(0.0, rarity['electronic'])

    def test_emphasising_rarity_reorders_an_artists_own_tags(self) -> None:
        rarity = tag_rarity([{'techno': 1.0, 'jungle': 1.0}] + [{'techno': 1.0} for _ in range(8)])
        k65 = emphasise_rare({'techno': 1.0, 'jungle': 0.5}, rarity)

        self.assertGreater(k65['jungle'], k65['techno'])

    def test_an_unseen_tag_contributes_nothing_rather_than_raising(self) -> None:
        self.assertEqual({'grime': 0.0}, emphasise_rare({'grime': 1.0}, {'techno': 2.0}))

    def test_rarity_is_never_negative(self) -> None:
        rarity = tag_rarity([{'ubiquitous': 1.0} for _ in range(20)] + [{'ubiquitous': 1.0, 'rare': 1.0}])

        self.assertEqual(0.0, rarity['ubiquitous'])
        self.assertGreater(rarity['rare'], 0.0)


class CoreProfile(TestCase):
    def test_the_profile_is_drawn_from_the_typical_half(self) -> None:
        core = [{'dub techno': 1.0, 'minimal': 1.0} for _ in range(4)]
        outliers = [{'disco': 1.0}, {'jungle': 1.0}]

        profile = core_profile(core + outliers)

        self.assertNotIn('disco', profile)
        self.assertNotIn('jungle', profile)
        self.assertIn('dub techno', profile)

    def test_an_outlier_scores_lower_against_the_core_than_against_everything(self) -> None:
        everything = [{'dub techno': 1.0} for _ in range(4)] + [{'disco': 1.0}, {'disco': 1.0}]
        outlier = {'disco': 1.0}

        self.assertLess(genre_affinity(outlier, core_profile(everything)),
                        genre_affinity(outlier, genre_profile(everything)))

    def test_it_survives_a_corpus_with_nothing_in_it(self) -> None:
        self.assertEqual({}, core_profile([]))
        self.assertEqual({}, core_profile([{}, {}]))


class ZeroWeightCandidates(TestCase):
    def test_a_candidate_sharing_nothing_with_the_corpus_is_never_drawn(self) -> None:
        kept = MixTrack(artist='Rrose', title='kept')
        dropped = MixTrack(artist='Grace Jones', title='dropped')

        drawn = weighted_draw({kept: 1.0, dropped: 0.0}, 7)

        self.assertEqual([kept], drawn)

    def test_an_all_zero_pool_draws_nobody_rather_than_dividing_by_zero(self) -> None:
        self.assertEqual([], weighted_draw({MixTrack(artist='a', title='b'): 0.0}, 7))
