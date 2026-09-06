from math import log
from unittest import TestCase

from src.genre import (
    Vouch,
    cosine,
    genre_confidence,
    normalised,
    scaled_by_rarity,
    style_profile,
    tag_rarity
)

DUB_TECHNO = {'dub techno': 1.0, 'techno': 0.4, 'ambient': 0.2}


class Normalising(TestCase):
    def test_a_tag_count_and_a_style_count_reach_the_same_scale(self) -> None:
        last_fm = normalised({'dub techno': 1.0, 'techno': 0.5})
        discogs = normalised({'dub techno': 8.0, 'techno': 4.0})

        self.assertEqual(last_fm, discogs)

    def test_an_untagged_artist_normalises_to_nothing_rather_than_failing(self) -> None:
        self.assertEqual({}, normalised({}))
        self.assertEqual({}, normalised({'dub techno': 0.0}))


class StyleProfile(TestCase):
    def test_the_profile_is_the_mean_of_the_rosters_tag_vectors(self) -> None:
        profile = style_profile([{'dub techno': 1.0}, {'dub techno': 0.5}])

        self.assertAlmostEqual(0.75, profile['dub techno'])

    def test_a_tag_one_roster_artist_carries_still_reaches_the_profile(self) -> None:
        profile = style_profile([{'dub techno': 1.0}, {'dub techno': 1.0, 'ambient': 1.0}])

        self.assertAlmostEqual(0.5, profile['ambient'])

    def test_an_untagged_roster_artist_does_not_pull_the_profile_toward_zero(self) -> None:
        self.assertEqual(style_profile([{'dub techno': 1.0}]),
                         style_profile([{'dub techno': 1.0}, {}]))

    def test_a_roster_nobody_has_tagged_profiles_nothing(self) -> None:
        self.assertEqual({}, style_profile([{}, {}]))
        self.assertEqual({}, style_profile([]))


class TagRarity(TestCase):
    def test_a_tag_every_artist_carries_is_worth_nothing(self) -> None:
        rarity = tag_rarity([{'techno': 1.0}, {'techno': 1.0}])

        self.assertEqual(0.0, rarity['techno'])

    def test_a_tag_one_artist_in_four_carries_outweighs_one_that_two_do(self) -> None:
        rarity = tag_rarity([{'dub techno': 1.0, 'techno': 1.0}, {'techno': 1.0},
                             {'house': 1.0}, {'house': 1.0}])

        self.assertAlmostEqual(log(4 / 1), rarity['dub techno'])
        self.assertGreater(rarity['dub techno'], rarity['house'])

    def test_an_untagged_artist_does_not_count_toward_the_denominator(self) -> None:
        self.assertEqual(tag_rarity([{'techno': 1.0}, {'house': 1.0}]),
                         tag_rarity([{'techno': 1.0}, {'house': 1.0}, {}]))


class ScalingByRarity(TestCase):
    def test_a_tag_nothing_in_the_evidence_carries_cannot_speak(self) -> None:
        self.assertEqual({'house': 0.0}, scaled_by_rarity({'house': 1.0}, {'techno': 0.5}))


class Cosine(TestCase):
    def test_an_empty_vector_is_alike_to_nothing(self) -> None:
        self.assertEqual(0.0, cosine({}, DUB_TECHNO))
        self.assertEqual(0.0, cosine(DUB_TECHNO, {}))

    def test_a_vector_is_wholly_alike_to_itself(self) -> None:
        self.assertAlmostEqual(1.0, cosine(DUB_TECHNO, DUB_TECHNO))

    def test_the_scale_of_a_vector_does_not_change_how_alike_it_is(self) -> None:
        self.assertAlmostEqual(cosine(DUB_TECHNO, DUB_TECHNO),
                               cosine(DUB_TECHNO, {tag: 8 * weight for tag, weight in DUB_TECHNO.items()}))


class GenreConfidence(TestCase):
    profile = {'dub techno': 1.0, 'house': 0.1}
    rarity = {'dub techno': 1.0, 'house': 1.0, 'techno': 0.5}
    tags = {'deep': {'dub techno': 1.0}, 'housey': {'house': 1.0}, 'unknown': {}}

    def confidence(self, *vouches: Vouch) -> float:
        return genre_confidence(vouches, self.tags, self.profile, self.rarity)

    def test_a_candidate_whose_neighbours_are_on_genre_outranks_one_whose_are_not(self) -> None:
        on_genre = self.confidence(Vouch(1.0, 'deep'), Vouch(0.9, 'deep'))
        off_genre = self.confidence(Vouch(1.0, 'deep'), Vouch(0.9, 'housey'))

        self.assertGreater(on_genre, off_genre)

    def test_one_vouch_and_nine_land_on_the_same_scale(self) -> None:
        alone = self.confidence(Vouch(1.0, 'deep'))
        crowded = self.confidence(*[Vouch(1.0 - n / 10, 'deep') for n in range(9)])

        self.assertAlmostEqual(alone, crowded)

    def test_a_neighbour_returned_higher_vouches_more_strongly(self) -> None:
        leading = self.confidence(Vouch(1.0, 'housey'), Vouch(0.9, 'deep'))
        trailing = self.confidence(Vouch(1.0, 'housey'), Vouch(0.1, 'deep'))

        self.assertGreater(leading, trailing)

    def test_an_artist_nobody_has_tagged_is_dropped_rather_than_scored_zero(self) -> None:
        self.assertAlmostEqual(self.confidence(Vouch(1.0, 'deep')),
                               self.confidence(Vouch(1.0, 'deep'), Vouch(1.0, 'unknown')))

    def test_a_candidate_with_no_tagged_evidence_abstains_at_zero(self) -> None:
        self.assertEqual(0.0, self.confidence(Vouch(1.0, 'unknown')))
        self.assertEqual(0.0, self.confidence())

    def test_a_rare_tag_the_style_owns_outweighs_one_everybody_carries(self) -> None:
        everywhere = {'dub techno': 1.0, 'techno': 0.0}
        confidence = genre_confidence([Vouch(1.0, 'generic')], {'generic': {'techno': 1.0}},
                                      {'dub techno': 1.0, 'techno': 1.0}, everywhere)

        self.assertEqual(0.0, confidence)
