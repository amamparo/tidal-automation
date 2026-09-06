from collections import Counter, defaultdict
from dataclasses import dataclass
from math import log, sqrt
from typing import Dict, Iterable, Mapping, Sequence

TagVector = Dict[str, float]


@dataclass(frozen=True)
class Vouch:
    weight: float
    artist: str


def normalised(counts: Mapping[str, float]) -> TagVector:
    loudest = max(counts.values(), default=0.0)
    if loudest <= 0.0:
        return {}
    return {tag: count / loudest for tag, count in counts.items()}


def style_profile(vectors: Iterable[TagVector]) -> TagVector:
    tagged = [vector for vector in vectors if vector]
    profile: TagVector = defaultdict(float)
    for vector in tagged:
        for tag, weight in vector.items():
            profile[tag] += weight / len(tagged)
    return dict(profile)


def tag_rarity(vectors: Iterable[TagVector]) -> TagVector:
    tagged = [vector for vector in vectors if vector]
    carrying = Counter(tag for vector in tagged for tag in vector)
    return {tag: log(len(tagged) / carrying[tag]) for tag in carrying}


def scaled_by_rarity(vector: Mapping[str, float], rarity: Mapping[str, float]) -> TagVector:
    return {tag: weight * rarity.get(tag, 0.0) for tag, weight in vector.items()}


def cosine(one: Mapping[str, float], other: Mapping[str, float]) -> float:
    magnitude = sqrt(sum(weight ** 2 for weight in one.values()))
    other_magnitude = sqrt(sum(weight ** 2 for weight in other.values()))
    if magnitude == 0.0 or other_magnitude == 0.0:
        return 0.0
    shared = sum(weight * other.get(tag, 0.0) for tag, weight in one.items())
    return shared / (magnitude * other_magnitude)


def genre_confidence(vouches: Sequence[Vouch], tags: Mapping[str, TagVector],
                     profile: Mapping[str, float], rarity: Mapping[str, float]) -> float:
    anchor = scaled_by_rarity(profile, rarity)
    vouched = [(vouch.weight, cosine(scaled_by_rarity(tagged, rarity), anchor))
               for vouch in vouches if (tagged := tags.get(vouch.artist))]
    if not vouched:
        return 0.0
    return sum(weight * likeness for weight, likeness in vouched) / sum(weight for weight, _ in vouched)
