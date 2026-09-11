from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, cast
from unittest import TestCase

from tidalapi import Track

from src.tidal import moves_to_reorder, newest_first

MONDAY = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)


@dataclass
class AddedTrack:
    id: int
    user_date_added: Optional[datetime]


def date_added(day: Optional[int]) -> Optional[datetime]:
    if day is None:
        return None
    return MONDAY + timedelta(days=day)


def added(*days: Optional[int]) -> List[Track]:
    return cast(List[Track], [AddedTrack(n, date_added(day)) for n, day in enumerate(days)])


def ids(tracks: List[Track]) -> List[Optional[int]]:
    return [track.id for track in tracks]


def reordered(current: List[str], wanted: List[str]) -> List[str]:
    order = list(current)
    for index, position in moves_to_reorder(current, wanted):
        order.insert(position, order.pop(index))
    return order


class NewestFirst(TestCase):
    def test_the_most_recently_added_track_leads(self) -> None:
        self.assertEqual([2, 1, 0], ids(newest_first(added(0, 1, 2))))

    def test_tracks_added_together_keep_their_order(self) -> None:
        self.assertEqual([2, 3, 0, 1], ids(newest_first(added(0, 0, 1, 1))))

    def test_an_already_ordered_playlist_is_left_as_it_is(self) -> None:
        self.assertEqual([0, 1, 2, 3], ids(newest_first(added(3, 3, 2, 1))))

    def test_a_track_with_no_added_date_goes_last(self) -> None:
        self.assertEqual([1, 2, 0], ids(newest_first(added(None, 1, 0))))


class MovesToReorder(TestCase):
    def test_an_ordered_playlist_needs_no_moves(self) -> None:
        self.assertEqual([], moves_to_reorder(['a', 'b', 'c'], ['a', 'b', 'c']))

    def test_each_move_is_the_index_the_track_holds_at_that_moment(self) -> None:
        self.assertEqual([(2, 0), (2, 1)], moves_to_reorder(['a', 'b', 'c'], ['c', 'b', 'a']))

    def test_the_moves_arrive_at_the_wanted_order(self) -> None:
        current = ['a', 'b', 'c', 'd', 'e', 'f']
        wanted = ['e', 'f', 'd', 'a', 'b', 'c']

        self.assertEqual(wanted, reordered(current, wanted))

    def test_a_block_already_in_place_costs_nothing(self) -> None:
        current = ['a', 'b', 'c', 'd', 'e']
        wanted = ['d', 'e', 'a', 'b', 'c']

        self.assertEqual([(3, 0), (4, 1)], moves_to_reorder(current, wanted))
