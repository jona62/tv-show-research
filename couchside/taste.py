"""What a whole list says about someone's taste, beyond closeness to single shows.

The engine scores a show by how close it sits to each show you rated. That misses
patterns spread across a list: you watch British shows, you like them short, you
seldom go back before 2000, you steer clear of reality TV. This learns them from the
list itself.

Every show carries attributes in families: language, format, network country,
network, decade, episode length, how well known and how well rated it is, and its
genres and themes (TVmaze's, plus Wikidata's finer subgenres when the model has
them). For each attribute it compares how often your liked shows carry it with how
often shows in general do, as a smoothed log ratio: naive Bayes, your list against
the catalogue. PRIOR pseudo-shows of plain catalogue taste sit in every list, so one
or two ratings barely move anything while ten liked British shows move a lot.
Disliked shows count against what they carry, at DISLIKE strength.

A show's taste score adds up its families, each measured from a typical catalogue
show, so a show with no data in a family scores zero there rather than being guessed
at. Each family is weighted and clipped so no single one decides. The engine then
multiplies a pick's closeness by exp(STRENGTH x taste). Nothing about a person
outlives the request.
"""
from array import array
import math

REFERENCE_MIN = 40   # base rates come from recommendable shows at least this well known
PRIOR = 12.0         # pseudo-shows of catalogue taste mixed into every list
DISLIKE = 0.5        # how hard a disliked show counts against what it carries
STRENGTH = 0.7       # a pick's closeness is multiplied by exp(STRENGTH x taste)
QUALITY = 0.4        # a pull toward well-rated shows that is the same for everyone

# family: (weight, clip). A family adds weight x its score, clipped to plus or minus clip.
# Tuned on scripts/bench (see its README). Themes carry no weight: the regex themes are
# noisy, already count toward closeness, and the bench ranked better without them here;
# they still describe a list's leanings.
FAMILIES = {
    'language': (1.0, 2.0), 'format': (1.0, 2.0), 'country': (0.5, 1.5), 'network': (0.4, 1.5),
    'decade': (0.5, 1.5), 'length': (0.4, 1.0), 'fame': (0.8, 1.5), 'acclaim': (0.5, 1.0),
    'genre': (0.5, 2.5), 'theme': (0.0, 1.5), 'subgenre': (0.5, 2.5),
}
CATEGORICAL = ('language', 'format', 'country', 'network', 'decade', 'length', 'fame', 'acclaim')
SETS = ('genre', 'theme', 'subgenre')
COMMON = 0.3      # an attribute this share of shows carries is too common to explain a pick
# A long list's leaning: this many liked shows, this share of the list and this lift at least.
WIDE_LEAN = (20, 0.1, 2.0)
# How well known and how well rated a list's shows are shape its picks, but they describe the
# list more than the taste, so a summary leaves them out; nor is a length or a decade avoided.
UNSAID = ('fame', 'acclaim')
AVOIDABLE = ('format', 'genre', 'subgenre', 'language', 'country', 'network')

COUNTRIES = {
    'US': 'American', 'GB': 'British', 'JP': 'Japanese', 'KR': 'South Korean', 'RU': 'Russian',
    'AU': 'Australian', 'CN': 'Chinese', 'CA': 'Canadian', 'TH': 'Thai', 'FR': 'French', 'TR': 'Turkish',
    'UA': 'Ukrainian', 'NL': 'Dutch', 'DE': 'German', 'NO': 'Norwegian', 'NZ': 'New Zealand',
    'SE': 'Swedish', 'BE': 'Belgian', 'ES': 'Spanish', 'IN': 'Indian', 'IE': 'Irish', 'IT': 'Italian',
    'BR': 'Brazilian', 'MX': 'Mexican', 'TW': 'Taiwanese', 'PL': 'Polish', 'DK': 'Danish',
    'HU': 'Hungarian', 'IL': 'Israeli', 'FI': 'Finnish', 'PT': 'Portuguese', 'HK': 'Hong Kong',
    'PH': 'Filipino', 'AR': 'Argentine', 'SG': 'Singaporean', 'GR': 'Greek', 'AT': 'Austrian',
    'CZ': 'Czech', 'ZA': 'South African', 'EG': 'Egyptian', 'CO': 'Colombian', 'RS': 'Serbian',
    'CH': 'Swiss', 'IS': 'Icelandic', 'CL': 'Chilean', 'RO': 'Romanian', 'PK': 'Pakistani',
}


def decade(year):
    if not year:
        return None
    return 'before 1960' if year < 1960 else f'{year // 10 * 10}s'


def length(runtime):
    if not runtime:
        return None
    return ('short' if runtime <= 20 else 'half-hour' if runtime <= 40
            else 'hour-long' if runtime <= 75 else 'feature-length')


def fame(popularity):
    return ('household names' if popularity >= 95 else 'well known' if popularity >= 85
            else 'fairly known' if popularity >= 70 else 'lesser known' if popularity >= 50
            else 'little known')


def acclaim(rating):
    if not rating:
        return None
    return ('acclaimed' if rating >= 8.5 else 'well rated' if rating >= 7.5
            else 'middling' if rating >= 6.5 else 'poorly rated')


def clamp(value, limit):
    return limit if value > limit else -limit if value < -limit else value


class Attributes:
    """Every show's attributes as small integers, and how common each one is among the
    shows people actually come across. Worked out once per model."""

    def __init__(self, engine, subgenres=None):
        """subgenres, when the model has Wikidata's, is (labels, masks): a label per
        bit and one int bitmask per show in catalog order."""
        shows, n = engine.shows, engine.n
        self.engine, self.n = engine, n
        readers = {
            'language': lambda i, s: s['language'],
            'format': lambda i, s: s['type'],
            'country': lambda i, s: s['country'],
            'network': lambda i, s: s['channel'],
            'decade': lambda i, s: decade(s['year']),
            'length': lambda i, s: length(s['runtime']),
            'fame': lambda i, s: fame(engine.popularity[i]),
            'acclaim': lambda i, s: acclaim(s['rating']),
        }
        reference = [i for i, s in enumerate(shows)
                     if s['recommendable'] and engine.popularity[i] >= REFERENCE_MIN]
        self.values, self.labels, self.base = {}, {}, {}
        for family, read in readers.items():
            ids, labels, column = {}, [None], array('I', bytes(4 * n))
            for i, s in enumerate(shows):
                value = read(i, s)
                if value is not None:
                    if value not in ids:
                        ids[value] = len(labels)
                        labels.append(value)
                    column[i] = ids[value]
            counts = [0] * len(labels)
            for i in reference:
                counts[column[i]] += 1
            known = sum(counts[1:]) or 1
            self.values[family], self.labels[family] = column, labels
            self.base[family] = [0.0] + [max(c, 0.5) / known for c in counts[1:]]

        self.masks, self.known = {}, {}
        self.masks['genre'] = [s['genre_bits'] for s in shows]
        self.labels['genre'] = list(engine.genres)
        self.known['genre'] = bytes(1 if s['genre_bits'] else 0 for s in shows)
        self.masks['theme'] = [s['theme_bits'] for s in shows]
        self.labels['theme'] = list(engine.themes)
        self.known['theme'] = bytes(1 if s['summary_words'] >= 15 else 0 for s in shows)
        if subgenres:
            labels, masks = subgenres
            self.masks['subgenre'], self.labels['subgenre'] = masks, list(labels)
            self.known['subgenre'] = bytes(1 if m else 0 for m in masks)
        for family in self.masks:
            size, masks, known = len(self.labels[family]), self.masks[family], self.known[family]
            counts, total = [0] * size, 0
            for i in reference:
                if known[i]:
                    total += 1
                    mask = masks[i]
                    while mask:
                        low = mask & -mask
                        counts[low.bit_length() - 1] += 1
                        mask ^= low
            total = total or 1
            floor = 0.5 / total
            self.base[family] = [min(max(c / total, floor), 1 - floor) for c in counts]

    @property
    def families(self):
        return [f for f in (*CATEGORICAL, *SETS) if f in self.values or f in self.masks]

    def label(self, family, value):
        text = self.labels[family][value]
        return COUNTRIES.get(text, text) if family == 'country' else text


class Taste:
    """One list's leanings: for every attribute, how much more (or less) your liked
    shows carry it than a typical show does, and a score for any show built from them."""

    def __init__(self, attributes, liked, disliked):
        """liked: [(index, weight)] with weight above zero; disliked: [index]."""
        a = self.a = attributes
        self.liked, self.disliked = liked, disliked
        self.tables, self.sets, self.stats = [], [], {}
        if not liked and not disliked:
            return
        for family in CATEGORICAL:
            weight, limit = FAMILIES[family]
            column, base = a.values[family], a.base[family]
            mass, total, shows = {}, 0.0, {}
            for i, w in liked:
                v = column[i]
                if v:
                    mass[v] = mass.get(v, 0.0) + w
                    shows[v] = shows.get(v, 0) + 1
                    total += w
            bad, count = {}, 0
            for i in disliked:
                v = column[i]
                if v:
                    bad[v] = bad.get(v, 0) + 1
                    count += 1

            def ratio(v, b):
                p = (mass.get(v, 0.0) + PRIOR * b) / (total + PRIOR)
                q = (bad.get(v, 0) + PRIOR * b) / (count + PRIOR)
                return math.log(p / b) - DISLIKE * math.log(q / b)
            seen = set(mass) | set(bad)
            unseen = math.log(PRIOR / (total + PRIOR)) - DISLIKE * math.log(PRIOR / (count + PRIOR))
            ratios = {v: ratio(v, base[v]) for v in seen}
            typical = sum(base[v] * r for v, r in ratios.items()) + (1 - sum(base[v] for v in seen)) * unseen
            contributions = [0.0] + [weight * clamp(ratios.get(v, unseen) - typical, limit)
                                     for v in range(1, len(base))]
            self.tables.append((column, contributions))
            self.stats[family] = (mass, total, bad, count, shows)

        for family in SETS:
            if family not in a.masks:
                continue
            weight, limit = FAMILIES[family]
            masks, known, base = a.masks[family], a.known[family], a.base[family]
            size = len(base)
            mass, total, shows = [0.0] * size, 0.0, [0] * size
            for i, w in liked:
                if known[i]:
                    total += w
                    for bit in bits(masks[i]):
                        mass[bit] += w
                        shows[bit] += 1
            bad, count = [0] * size, 0
            for i in disliked:
                if known[i]:
                    count += 1
                    for bit in bits(masks[i]):
                        bad[bit] += 1
            delta, offset = [0.0] * size, 0.0
            for bit in range(size):
                b = base[bit]
                p = (mass[bit] + PRIOR * b) / (total + PRIOR)
                q = (bad[bit] + PRIOR * b) / (count + PRIOR)
                present = math.log(p / b) - DISLIKE * math.log(q / b)
                absent = math.log((1 - p) / (1 - b)) - DISLIKE * math.log((1 - q) / (1 - b))
                delta[bit] = present - absent
                # Measured from a typical show: what it would carry, less what it lacks.
                offset += absent - (b * present + (1 - b) * absent)
            self.sets.append((family, masks, known, delta, offset, weight, limit, {}))
            self.stats[family] = ({b: m for b, m in enumerate(mass) if m}, total,
                                  {b: d for b, d in enumerate(bad) if d}, count,
                                  {b: c for b, c in enumerate(shows) if c})

    def family_score(self, family_entry, i):
        family, masks, known, delta, offset, weight, limit, cache = family_entry
        if not known[i]:
            return 0.0
        mask = masks[i]
        hit = cache.get(mask)
        if hit is None:
            hit = weight * clamp(offset + sum(delta[bit] for bit in bits(mask)), limit)
            cache[mask] = hit
        return hit

    def score(self, i):
        """How well show i fits the list's leanings, from zero for a typical show. It is
        family_score for each set family, written out: a long list's ranking asks for it
        tens of thousands of times."""
        total = 0.0
        for column, contributions in self.tables:
            total += contributions[column[i]]
        for _family, masks, known, delta, offset, weight, limit, cache in self.sets:
            if known[i]:
                mask = masks[i]
                hit = cache.get(mask)
                if hit is None:
                    hit = cache[mask] = weight * clamp(offset + sum(delta[bit] for bit in bits(mask)), limit)
                total += hit
        return total

    def quality(self, i):
        """How far show i's public rating sits from an ordinary one, from -1.5 to 1.5;
        zero when it has none, so a new show is not held back for being new."""
        rating = self.a.engine.shows[i]['rating']
        return clamp((rating - 7.2) / 1.2, 1.5) if rating else 0.0

    def factor(self, i):
        """What a pick's closeness is multiplied by: its fit with the list, and a pull
        toward well-rated shows that is the same for everyone."""
        return math.exp(STRENGTH * self.score(i) + QUALITY * self.quality(i))

    def reasons(self, i, limit=3):
        """The attributes of show i that fit the list best, strongest first. Ones most
        shows share, such as English or scripted, explain nothing, so they are left out."""
        a, found = self.a, []
        for family, (column, contributions) in zip(CATEGORICAL, self.tables):
            v = column[i]
            if v and contributions[v] > 0.15 and a.base[family][v] < COMMON and family not in ('fame', 'acclaim'):
                found.append((contributions[v], family, a.label(family, v)))
        for family, masks, known, delta, _offset, weight, _limit, _cache in self.sets:
            if known[i]:
                for bit in bits(masks[i]):
                    if weight * delta[bit] > 0.3 and a.base[family][bit] < COMMON:
                        found.append((weight * delta[bit], family, a.labels[family][bit]))
        found.sort(key=lambda f: -f[0])
        out, seen = [], set()
        subgenres = 0
        for _score, family, label in found:
            # TVmaze's Crime, the Crime / illicit enterprise theme and Wikidata's crime
            # are one reason, and one Wikidata subgenre says enough: the next is usually
            # its parent (mockumentary, then pseudo documentary).
            key = label.split(' / ')[0].casefold()
            if key in seen or (family == 'subgenre' and subgenres):
                continue
            seen.add(key)
            subgenres += family == 'subgenre'
            out.append({'family': family, 'label': label})
        return out[:limit]

    def summary(self, limit=6):
        """What the list leans toward and away from, in plain attributes, for showing a
        person their own taste. A leaning needs at least two liked shows behind it and
        must be something most shows are not (English and scripted say little); an
        avoidance comes from two or more dislikes, or from something common a long list
        never includes."""
        a, leans, avoids = self.a, [], []
        for family, (mass, total, bad, count, shows) in self.stats.items():
            if family in UNSAID:
                continue
            base = a.base[family]
            name = (lambda v: a.label(family, v)) if family in CATEGORICAL else (lambda v: a.labels[family][v])
            for v, support in shows.items():
                share = mass[v] / total
                lift = share / base[v]
                # A list of thousands spreads over many kinds, so a leaning there may be a
                # smaller share with more shows behind it (WIDE_LEAN).
                wide = support >= WIDE_LEAN[0] and share >= WIDE_LEAN[1] and lift >= WIDE_LEAN[2]
                if support >= 2 and (share >= 0.25 and lift >= 1.5 or wide) and base[v] < COMMON:
                    leans.append((share * math.log(lift), {
                        'family': family, 'label': name(v), 'share': round(share * 100),
                        'base': round(base[v] * 100, 1), 'shows': support},
                        (family, self._backers(family, v)) if family == 'subgenre' else (family, v)))
            for v, disliked in bad.items() if family in AVOIDABLE else ():
                share = mass.get(v, 0.0) / total if total else 0.0
                if disliked >= 2 and share < base[v] and disliked / count >= 0.5:
                    avoids.append((disliked + 1 - share, {'family': family, 'label': name(v),
                                                          'why': 'disliked', 'shows': disliked}))
            if family in ('format', 'genre', 'language') and len(self.liked) >= 8 and total:
                for v in range(1 if family in CATEGORICAL else 0, len(base)):
                    if base[v] >= 0.12 and v not in mass and v not in bad:
                        avoids.append((base[v], {'family': family, 'label': name(v), 'why': 'never', 'shows': 0}))
        leans.sort(key=lambda f: -f[0])
        avoids.sort(key=lambda f: -f[0])
        # Wikidata tags the same two sitcoms mockumentary, pseudo documentary and parody
        # (a genre with its parents): one pattern under three names, so a subgenre backed
        # by exactly the shows of a stronger one is left out.
        seen, kept = set(), []
        for entry in leans:
            if entry[2] not in seen:
                seen.add(entry[2])
                kept.append(entry[:2])
        return {'leans': distinct(kept, limit), 'avoids': distinct(avoids, limit)}

    def _backers(self, family, v):
        """The liked shows that carry value v of a family."""
        a = self.a
        if family in CATEGORICAL:
            column = a.values[family]
            return frozenset(i for i, _w in self.liked if column[i] == v)
        masks, known = a.masks[family], a.known[family]
        return frozenset(i for i, _w in self.liked if known[i] and masks[i] >> v & 1)


def distinct(ranked, limit):
    """The first limit entries of a ranked list with one entry per label, whatever its
    case or family: TVmaze's Crime and Wikidata's crime are one leaning."""
    out, seen = [], set()
    for _rank, entry in ranked:
        key = entry['label'].split(' / ')[0].casefold()
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out[:limit]


def bits(mask):
    """The positions of mask's set bits, lowest first. Shows share far fewer masks than
    there are shows, so each is worked out once and kept (up to BITS_KEPT of them)."""
    found = _BITS.get(mask)
    if found is None:
        out, rest = [], mask
        while rest:
            low = rest & -rest
            out.append(low.bit_length() - 1)
            rest ^= low
        found = tuple(out)
        if len(_BITS) < BITS_KEPT:
            _BITS[mask] = found
    return found


_BITS = {}
BITS_KEPT = 100_000
