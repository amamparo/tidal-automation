from typing import Any, cast
from unittest import TestCase

from src.tidal import Tidal


def clean_title(title: str) -> str:
    cleaner = getattr(cast(Any, Tidal), '_Tidal__clean_title')
    return str(cleaner(title))


class LiveMarkersInTheSearchQuery(TestCase):
    def test_a_live_marker_is_stripped_before_searching(self) -> None:
        self.assertEqual('Canopee Imaginaire', clean_title('Canopee Imaginaire (Live At Draaimolen 2023)'))
        self.assertEqual('Seconds To Forever', clean_title('Seconds To Forever (Live Mix)'))

    def test_a_named_remix_survives_the_search_query(self) -> None:
        self.assertEqual('Ikigai (Orbe Remix)', clean_title('Ikigai (Orbe Remix)'))
