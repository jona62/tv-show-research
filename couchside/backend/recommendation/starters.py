"""First-visit shows: which titles a newcomer is asked about, and in what order.

A fixed list of famous titles is easy to recognise but teaches little, and it starts
every newcomer from the same few shows (MovieLens: Rashid et al. 2002 and 2008;
Golbandi et al. 2011). So the first screen comes from a pool that is familiar and
covers distinct kinds of show, drawn a little differently for each browser and day,
and it adapts as shows are picked. Couchside's build.py copies this file, like
engine.py.

The pool, built whenever a model loads:

- Eligible shows are recommendable, have a poster where the app needs one, are not
  sexual content (TVmaze's adult genre, or Wikidata's erotic ones), and are rated 6.5
  or more, or carry no rating but a popularity of 95 or more.
- Candidates are the 2,000 most popular of them and the 50 most popular in each of
  the 15 languages with the most eligible shows.
- One title per franchise. Shows sharing a Wikidata franchise, or a name before a
  colon, form one group, which its anchor stands for if it has one, else its oldest
  title within two points of the group's best popularity.
- Candidates split by format (scripted, animation, anime, documentary, unscripted),
  genre cluster (TVmaze's and Wikidata's genres) and language family: English, or the
  rest of the world, whose languages have about fifty candidates each, too few to
  split by fine genres. A cell under ten titles merges upward, into a broader cluster
  and then across its format, which leaves about 35 facets.
- A title scores S = 2FR / (F + R). F is its popularity percentile within its language,
  rating breaking the many ties of TVmaze's 0 to 100 scale; R is its mean Jaccard
  similarity to the rest of its facet over genre, subgenre, format and decade tokens,
  scaled so the facet's most typical title is 1, since a raw mean Jaccard rarely
  passes 0.5 and would drown F. Each facet keeps its best ten, and a world facet no
  more than two from one language group while others can fill it.
- Anchors are the long-standing quick picks and the most popular title of each format.
- For the visitor's language and country, the best known forty of each, one per
  franchise. Most shows beyond English carry no rating, so only a low one rules a show
  out of these.

A screen of 24 holds three anchors (two in the first row), seventeen facet slots and
four flexible ones. Facets are drawn with probability proportional to the square root
of their summed popularity, subject to quotas: at least four formats, three decades,
one animation or anime title, one unscripted title and two not in English. A facet's
title comes from its best five by S with a softmax at temperature 0.15. The flexible
slots follow the visitor's language: a primary language other than English takes
seven slots from that language, ranked by popularity within it, and English with a
region such as en-GB takes four from that country. Otherwise they explore facets not
yet on screen. The most familiar titles go top left, the quick picks first among the
anchors, and no two of one facet sit side by side.

Each pick swaps three unpicked slots: a contrast from the pick's facet (another era,
language or subgenre), a title from the nearest other facet, and one from the likeliest
facet not yet explored. A facet never holds more than three titles on screen, and at
least 60% of the unpicked titles come from facets with no pick yet.

Everything is a function of (seed, round, language, picks), so the server keeps
nothing about a visitor and caches each screen. The seed comes from the browser
(fresh.js); without one the screen is the plain, noiseless one. Round r starts each
facet's ranking for that seed at its r-th title, so asking for different shows changes
every unpicked slot. A pick on the screen stays where it is; one that is not (found by
search, or picked in an earlier round) stays off it but still shapes it.
"""
from collections import namedtuple
from functools import lru_cache
from itertools import permutations
import bisect
import math
import re

from .engine import FORMAT_GROUPS, QUICK_PICKS
from .fresh import uniform

COUNT = 24              # titles on a screen
MIN_COUNT, MAX_COUNT = 6, 48
MAX_ROUND = 50
MAX_PICKED = 20
TOP = 2000              # candidates: the most popular eligible shows,
LANGUAGES = 15          # and the most popular in each of this many languages
PER_LANGUAGE = 50
MIN_RATING = 6.5
UNRATED_POPULARITY = 95
FRANCHISE_SLACK = 2     # a franchise's oldest title stands for it within this much of its best popularity
MIN_FACET = 10          # a smaller cell merges upward
PER_FACET = 10          # titles a facet keeps,
PER_GROUP = 2           # and at most this many from one language group while others can fill it
DRAW_FROM = 5           # a facet's title is drawn from its best this many
TEMPERATURE = 0.15
FACET_CAP = 3           # titles of one facet on screen at once
UNEXPLORED = 0.6        # share of the unpicked titles from facets with no pick yet
SWAPS = 3               # unpicked slots each pick swaps
LOCALE_TOP = 40         # titles kept for each language and each country
QUOTAS = {'formats': 4, 'decades': 3, 'cartoons': 1, 'unscripted': 1, 'foreign': 2}
# For a browser in English, or one that names no language, world facets are drawn at this
# share of their weight: at full weight about six of 24 titles came from languages such
# a visitor seldom knows, and a starter nobody recognises teaches nothing. The foreign
# quota still puts two on every screen.
WORLD_SHARE = 0.3
# Wikidata's genres for sexual content, which TVmaze does not always file as adult.
EXPLICIT = frozenset({'erotic', 'erotica', 'erotic thriller', 'ecchi', 'hentai', 'lot of sex scenes drama',
                      'sex comedy', 'softcore pornography'})

Slot = namedtuple('Slot', 'index why facet')

UNSCRIPTED = frozenset(FORMAT_GROUPS['unscripted'])
FORMATS = ('scripted', 'animation', 'anime', 'documentary', 'unscripted')

# Genre clusters for each format, first match wins: (cluster, broader cluster, TVmaze
# genres or types, Wikidata genres). Anything else takes the format's fallback.
STORY = (
    ('horror', 'speculative', {'Horror'}, {'horror', 'supernatural horror', 'zombie', 'vampire', 'werewolf', 'slasher'}),
    ('sci-fi', 'speculative', {'Science-Fiction'}, {'science fiction', 'cyberpunk', 'space opera', 'dystopian'}),
    ('fantasy', 'speculative', {'Fantasy', 'Supernatural'}, {'fantasy', 'superhero', 'paranormal', 'urban fantasy'}),
    ('procedural', 'crime and mystery', {'Legal', 'Medical'},
     {'police procedural', 'procedural', 'legal drama', 'medical drama'}),
    ('crime', 'crime and mystery', {'Crime', 'Espionage'}, {'crime', 'crime drama', 'spy', 'espionage', 'noir', 'neo noir'}),
    ('thriller', 'crime and mystery', {'Thriller', 'Mystery'}, {'thriller', 'mystery', 'psychological thriller'}),
    ('period', 'drama and adventure', {'History', 'War', 'Western'}, {'historical drama', 'period drama', 'western', 'war'}),
    ('action', 'drama and adventure', {'Action', 'Adventure'}, {'action', 'adventure', 'action and adventure'}),
    ('comedy-drama', 'comedy', set(), {'comedy drama', 'dramedy'}),
    ('sitcom', 'comedy', {'Comedy'}, {'sitcom', 'comedy', 'satire', 'parody', 'mockumentary'}),
    ('romance', 'drama and adventure', {'Romance'}, {'romance', 'romantic comedy', 'melodrama', 'telenovela', 'soap opera'}),
    ('family', 'drama and adventure', {'Family', 'Children'}, {"children's", 'family', 'teen', 'teen drama', 'youth'}),
)
CARTOON = (
    ('kids', 'all ages', {'Children', 'Family'}, {"children's", 'family', "children's animation", 'preschool'}),
    ('comedy', 'grown-up', {'Comedy'}, {'animated sitcom', 'animated comedy', 'adult animation', 'sitcom'}),
    ('adventure', 'grown-up', {'Science-Fiction', 'Fantasy', 'Horror', 'Supernatural', 'Action', 'Adventure',
                               'Crime', 'Thriller'}, {'science fiction', 'fantasy', 'superhero', 'action'}),
)
ANIME = (
    ('dark', 'dark and sci-fi', {'Horror', 'Thriller', 'Mystery', 'Crime', 'Supernatural'},
     {'dark fantasy', 'horror', 'psychological'}),
    ('sci-fi', 'dark and sci-fi', {'Science-Fiction'}, {'science fiction', 'cyberpunk', 'mecha'}),
    ('isekai', 'adventure', set(), {'isekai', 'portal fantasy', 'progression fantasy'}),
    ('action', 'adventure', {'Action', 'Adventure'}, {'action', 'adventure', 'martial arts'}),
    ('fantasy', 'adventure', {'Fantasy'}, {'fantasy'}),
    ('slice of life', 'everyday', {'Comedy', 'Romance', 'Drama', 'Sports', 'Music', 'Family'},
     {'slice of life', 'romance', 'comedy', 'sports'}),
)
FACTUAL = (
    ('nature', 'factual', {'Nature', 'Travel'}, {'nature documentary', 'popular science', 'travel documentary', 'nature'}),
    ('history', 'factual', {'History', 'War'}, {'history', 'historical', 'war'}),
    ('true crime', 'factual', {'Crime', 'Legal'}, {'true crime', 'crime'}),
    ('culture', 'factual', {'Sports', 'Music', 'Food'}, {'music', 'sports', 'biography'}),
)
ENTERTAINMENT = (
    ('competition', 'entertainment', {'Game Show', 'Panel Show'},
     {'game show', 'competition', 'reality competition', 'talent show', 'panel game'}),
    ('talk', 'entertainment', {'Talk Show', 'News', 'Variety', 'Award Show'},
     {'talk show', 'late night talk show', 'variety show', 'news', 'sketch comedy'}),
    ('sports', 'entertainment', {'Sports'}, {'professional wrestling', 'sports'}),
    ('lifestyle', 'entertainment', {'Food', 'DIY', 'Travel'}, {'cooking show', 'makeover'}),
)
RULES = {'scripted': (STORY, ('drama', 'drama and adventure')), 'animation': (CARTOON, ('comedy', 'grown-up')),
         'anime': (ANIME, ('action', 'adventure')), 'documentary': (FACTUAL, ('society', 'factual')),
         'unscripted': (ENTERTAINMENT, ('reality', 'entertainment'))}

# Language groups, which keep a world facet's best ten from all coming from one of them.
GROUPS = {
    'Korean': ('Korean',), 'Japanese': ('Japanese',), 'Chinese': ('Chinese',), 'Thai': ('Thai',),
    'Southeast Asian': ('Tagalog', 'Indonesian', 'Malay', 'Vietnamese', 'Burmese', 'Central Khmer', 'Lao', 'Javanese'),
    'Spanish and Portuguese': ('Spanish', 'Portuguese', 'Catalan', 'Galician', 'Basque'),
    'French and Italian': ('French', 'Italian', 'Romanian'),
    'German and Dutch': ('German', 'Dutch', 'Luxembourgish', 'Afrikaans'),
    'Nordic': ('Swedish', 'Norwegian', 'Danish', 'Finnish', 'Icelandic'),
    'Slavic': ('Russian', 'Ukrainian', 'Polish', 'Czech', 'Slovak', 'Serbian', 'Croatian', 'Bosnian', 'Bulgarian',
               'Slovenian', 'Belarusian'),
    'Turkish': ('Turkish', 'Azerbaijani'),
    'South Asian': ('Hindi', 'Tamil', 'Telugu', 'Malayalam', 'Kannada', 'Bengali', 'Marathi', 'Panjabi', 'Gujarati',
                    'Urdu', 'Sinhalese'),
    'Middle Eastern': ('Arabic', 'Hebrew', 'Persian', 'Pashto'),
}
GROUP_OF = {language: group for group, languages in GROUPS.items() for language in languages}

# BCP 47 primary subtags, as navigator.languages gives them, to TVmaze's language names.
LANGUAGE_TAGS = {
    'en': 'English', 'ja': 'Japanese', 'ko': 'Korean', 'zh': 'Chinese', 'th': 'Thai', 'ru': 'Russian', 'es': 'Spanish',
    'fr': 'French', 'de': 'German', 'tr': 'Turkish', 'sv': 'Swedish', 'no': 'Norwegian', 'nb': 'Norwegian',
    'nn': 'Norwegian', 'da': 'Danish', 'it': 'Italian', 'nl': 'Dutch', 'pt': 'Portuguese', 'hi': 'Hindi',
    'uk': 'Ukrainian', 'ar': 'Arabic', 'pl': 'Polish', 'tl': 'Tagalog', 'fil': 'Tagalog', 'hu': 'Hungarian',
    'fi': 'Finnish', 'he': 'Hebrew', 'iw': 'Hebrew', 'cs': 'Czech', 'el': 'Greek', 'cy': 'Welsh', 'ga': 'Irish',
    'id': 'Indonesian', 'ms': 'Malay', 'vi': 'Vietnamese', 'fa': 'Persian', 'ur': 'Urdu', 'ta': 'Tamil', 'te': 'Telugu',
    'ml': 'Malayalam', 'kn': 'Kannada', 'bn': 'Bengali', 'mr': 'Marathi', 'pa': 'Panjabi', 'gu': 'Gujarati',
    'ro': 'Romanian', 'bg': 'Bulgarian', 'hr': 'Croatian', 'sr': 'Serbian', 'bs': 'Bosnian', 'sk': 'Slovak',
    'sl': 'Slovenian', 'is': 'Icelandic', 'et': 'Estonian', 'lv': 'Latvian', 'lt': 'Lithuanian', 'ca': 'Catalan',
    'eu': 'Basque', 'gl': 'Galician', 'af': 'Afrikaans', 'ka': 'Georgian', 'hy': 'Armenian', 'az': 'Azerbaijani',
    'kk': 'Kazakh', 'mn': 'Mongolian', 'be': 'Belarusian', 'sq': 'Albanian', 'si': 'Sinhalese', 'my': 'Burmese',
    'km': 'Central Khmer', 'lo': 'Lao', 'sw': 'Swahili', 'lb': 'Luxembourgish', 'gd': 'Scottish Gaelic',
}
TAG = re.compile(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*')
REGION = re.compile(r'[A-Za-z]{2}')
SEED = re.compile(r'[0-9a-f]{16}')
DIGITS = re.compile(r'[0-9]{1,9}')


def locale(tag):
    """(TVmaze language, ISO country) for a BCP 47 tag such as ko, en-GB or zh-Hant-TW;
    either may be None."""
    if not tag or len(tag) > 35 or not TAG.fullmatch(tag):
        return None, None
    parts = tag.split('-')
    region = next((p.upper() for p in parts[1:] if REGION.fullmatch(p)), None)
    return LANGUAGE_TAGS.get(parts[0].lower()), region


def parse(query, accept=''):
    """(seed, round, picked ids, language tag, count) from a request's parsed query, with
    the Accept-Language header standing in for a missing lang. Raises ValueError with a
    message fit to show. A well-formed id the catalogue lacks is left for choose to drop,
    since a list can outlive a show."""
    def one(name):
        values = query.get(name, [])
        if len(values) > 1:
            raise ValueError(f'Send {name} once.')
        return values[0] if values else None
    seed = one('seed')
    if seed is not None and not SEED.fullmatch(seed):
        raise ValueError('Send the seed as 16 hexadecimal digits.')
    rnd = one('round') or '0'
    if not DIGITS.fullmatch(rnd) or int(rnd) > MAX_ROUND:
        raise ValueError(f'Send a round from 0 to {MAX_ROUND}.')
    raw = one('picked')
    picked = raw.split(',') if raw else []
    if len(picked) > MAX_PICKED:
        raise ValueError(f'Send up to {MAX_PICKED} picked shows.')
    if not all(DIGITS.fullmatch(p) for p in picked):
        raise ValueError('Send picked shows as ids separated by commas.')
    picked = [int(p) for p in picked]
    if len(set(picked)) != len(picked):
        raise ValueError('Send each picked show once.')
    lang = one('lang')
    if lang is None:
        tags = (part.split(';')[0].strip() for part in accept.split(','))
        lang = next((tag for tag in tags if len(tag) <= 35 and TAG.fullmatch(tag)), '')
    elif len(lang) > 35 or not TAG.fullmatch(lang):
        raise ValueError('Send lang as a language tag such as en-GB, of 35 characters or fewer.')
    count = one('count') or str(COUNT)
    if not DIGITS.fullmatch(count) or not MIN_COUNT <= int(count) <= MAX_COUNT:
        raise ValueError(f'Ask for {MIN_COUNT} to {MAX_COUNT} shows.')
    return seed, int(rnd), picked, lang, int(count)


def gumbel(seed, surface, key):
    """A Gumbel deviate fixed by the seed, the surface and the key; zero without a seed."""
    return -math.log(-math.log(uniform(seed, surface, key))) if seed else 0.0


def stem(name):
    """A name before any colon, as a franchise key: Star Trek: Discovery is Star Trek."""
    return ' '.join(re.split('[:：]', name, maxsplit=1)[0].casefold().split())


def decade(year):
    return year // 10 * 10 if year else None


def percentile(values, value):
    """Where value sits in sorted values, ties sharing their middle rank, from 0 to 1."""
    below = bisect.bisect_left(values, value)
    return (below + (bisect.bisect_right(values, value) - below + 1) / 2) / len(values)


def anchor_places(n, count):
    """Where anchors go: the first two places, then one every six."""
    return [p for p in [0, 1] + [6 * k for k in range(1, n)] if p < count][:n]


def quotas(count):
    """What a screen must span: the full quotas from 12 titles up, about half below."""
    return QUOTAS if count >= 12 else {k: max(1, v // 2) for k, v in QUOTAS.items()}


FORMAT_WORDS = {'scripted': '', 'animation': 'animation', 'anime': 'anime', 'documentary': 'documentaries',
                'unscripted': 'unscripted'}


def label(cells):
    """A facet's name from its titles' cells, such as 'English crime', 'World drama and
    adventure' or 'Anime, isekai': the narrowest cluster and family three in four share."""
    form = cells[0][0]

    def shared(k):
        values = [c[k] for c in cells]
        top = max(sorted(set(values)), key=values.count)
        return top if values.count(top) >= 0.75 * len(values) else ''
    cluster = shared(1) or shared(2)
    head = 'Anime' if form == 'anime' else ' '.join(w for w in (shared(3) or 'Any language', FORMAT_WORDS[form]) if w)
    if form == 'scripted':
        return f'{head} {cluster or "series"}'
    return f'{head}, {cluster}' if cluster else head


class Starters:
    """The pool for one model, and the screens drawn from it. usable(i) says whether a
    show can be offered at all, such as whether the app has a poster for it."""

    def __init__(self, engine, usable=None):
        self.e = e = engine
        shows, popularity = e.shows, e.popularity
        usable = usable or (lambda i: True)
        f = e.facets
        self.genre_cols = f.family_ranges[f.families.index('genre')] if f and 'genre' in f.families else None
        self.franchise_cols = f.family_ranges[f.families.index('franchise')] if f and 'franchise' in f.families else None
        self._keys = {}
        # Shows Wikidata files under an explicit genre, read from those columns' postings.
        self.flagged = frozenset(f.post_rows[k] for c in range(*self.genre_cols) if f.labels[c] in EXPLICIT
                                 for k in range(f.col_ptr[c], f.col_ptr[c + 1])) if self.genre_cols else frozenset()
        self.familiar = lambda i: (-popularity[i], -(shows[i]['rating'] or 0), shows[i]['id'])
        self.known = lambda i: (popularity[i], shows[i]['rating'] or 0)
        offered = [i for i, s in enumerate(shows) if s['recommendable'] and usable(i) and not self.explicit(i)]
        eligible = sorted((i for i in offered if (shows[i]['rating'] or 0) >= MIN_RATING
                           or (shows[i]['rating'] is None and popularity[i] >= UNRATED_POPULARITY)), key=self.familiar)
        by_language = {}
        for i in eligible:
            by_language.setdefault(shows[i]['language'], []).append(i)
        largest = sorted((lang for lang in by_language if lang), key=lambda lang: (-len(by_language[lang]), lang))
        candidates = list(dict.fromkeys(eligible[:TOP] + [
            i for lang in largest[:LANGUAGES] for i in by_language[lang][:PER_LANGUAGE]]))

        anchors = [e.by_id[x] for x in QUICK_PICKS if x in e.by_id and shows[e.by_id[x]]['recommendable']
                   and usable(e.by_id[x])]
        kept = sorted(self._one_per_franchise(candidates, anchors), key=self.familiar)
        self._facets(kept)
        # The most popular title of each format joins the quick picks as an anchor.
        for form in FORMATS:
            top = next((i for i in kept if self.format_of(i) == form), None)
            if top is not None and top not in anchors and not any(self.keys(top) & self.keys(a) for a in anchors):
                anchors.append(top)
        self.anchors = tuple(anchors)
        self.quick = frozenset(e.by_id[x] for x in QUICK_PICKS if x in e.by_id)
        self.everyone = sorted(self.known(i) for i in kept)
        self.size = len(kept)
        # What the flexible slots draw on: the best known in each language and country.
        # Most shows beyond English carry no rating, so here only a low one rules a show out.
        local = sorted((i for i in offered if shows[i]['rating'] is None or shows[i]['rating'] >= MIN_RATING),
                       key=self.familiar)
        groups = {}
        for i in local:
            for kind in ('language', 'country'):
                if shows[i][kind]:
                    groups.setdefault((kind, shows[i][kind]), []).append(i)
        self.locales = {key: self._locale_list(members) for key, members in groups.items()}

    # ------------------------------------------------------------ the pool

    def keys(self, i):
        """The franchise groups a show belongs to: Wikidata's and its name's."""
        found = self._keys.get(i)
        if found is None:
            out = {'n:' + stem(self.e.shows[i]['name'])}
            if self.franchise_cols:
                f, (a, b) = self.e.facets, self.franchise_cols
                out.update(f.columns[k] for k in range(f.row_ptr[i], f.row_ptr[i + 1]) if a <= f.columns[k] < b)
            found = self._keys[i] = frozenset(out)
        return found

    def _one_per_franchise(self, candidates, anchors):
        """Candidates with each franchise down to one title. An anchor sharing a franchise
        with an earlier one stops being an anchor."""
        parent = {}

        def find(x):
            while parent.setdefault(x, x) != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x
        members = list(dict.fromkeys(anchors + candidates))
        for i in members:
            first, *rest = sorted(self.keys(i), key=str)
            for k in rest:
                parent[find(k)] = find(first)
        groups = {}
        for i in members:
            groups.setdefault(find(min(self.keys(i), key=str)), []).append(i)
        shows, popularity = self.e.shows, self.e.popularity
        order = {a: n for n, a in enumerate(anchors)}
        wanted, kept = set(candidates), []
        for group in groups.values():
            held = sorted((i for i in group if i in order), key=order.get)
            if held:
                best = held[0]
                for a in held[1:]:
                    anchors.remove(a)
            else:
                top = max(popularity[i] for i in group)
                best = min((i for i in group if popularity[i] >= top - FRANCHISE_SLACK),
                           key=lambda i: (shows[i]['year'] or 9999, -(shows[i]['rating'] or 0), shows[i]['id']))
            if best in wanted:
                kept.append(best)
        return kept

    def format_of(self, i):
        s = self.e.shows[i]
        kind = s['type']
        if kind == 'Animation':
            japanese = s['language'] == 'Japanese' or ('Anime' in s['genres'] and s['language'] in (None, 'English'))
            return 'anime' if japanese else 'animation'
        if kind == 'Documentary':
            return 'documentary'
        return 'unscripted' if kind in UNSCRIPTED else 'scripted'

    def explicit(self, i):
        """Whether a show is sexual content, which has no place on a first screen."""
        return i in self.flagged or 'Adult' in self.e.shows[i]['genres']

    def subgenres(self, i):
        """Wikidata's genres for a show; none when the model has no facets."""
        if not self.genre_cols:
            return set()
        f, (a, b) = self.e.facets, self.genre_cols
        return {f.labels[f.columns[k]] for k in range(f.row_ptr[i], f.row_ptr[i + 1]) if a <= f.columns[k] < b}

    def cell(self, i):
        """(format, cluster, broader cluster, family) for any show."""
        s = self.e.shows[i]
        form = self.format_of(i)
        rules, (cluster, broader) = RULES[form]
        marks, words = set(s['genres']) | {s['type']}, self.subgenres(i)
        for name, parent, genres, wikidata in rules:
            if marks & genres or words & wikidata:
                cluster, broader = name, parent
                break
        family = 'English' if s['language'] == 'English' else 'World'
        # The world's languages are too thin for fine genres, so they start broader; anime
        # is nearly all Japanese and keeps its own.
        if family == 'World' and form != 'anime':
            cluster = broader
        return form, cluster, broader, family

    def _facets(self, kept):
        """Split the candidates into facets, merging small cells upward, and score them."""
        shows, popularity = self.e.shows, self.e.popularity
        cells = {i: self.cell(i) for i in kept}
        # The key a cell goes by at each level of merging, narrowest first.
        levels = (lambda c: (c[0], c[1], c[3]), lambda c: (c[0], c[2], c[3]), lambda c: (c[0], '', c[3]),
                  lambda c: (c[0], '', ''))
        groups = {}
        for i in kept:
            groups.setdefault(levels[0](cells[i]), []).append(i)
        facets = [[key, members] for key, members in groups.items()]
        for level in levels[1:]:
            small = [fc for fc in facets if len(fc[1]) < MIN_FACET]
            big = [fc for fc in facets if len(fc[1]) >= MIN_FACET]
            pooled = {}
            for fc in sorted(small, key=lambda fc: fc[0]):
                pooled.setdefault(level(cells[fc[1][0]]), []).extend(fc[1])
            for key, members in sorted(pooled.items()):
                # A pooled cell takes no key already in use, and one still too small joins
                # the biggest facet that shares its key at this level.
                home = next((fc for fc in big if fc[0] == key), None) or (max(
                    (fc for fc in big if level(cells[fc[1][0]]) == key), key=lambda fc: (len(fc[1]), fc[0]),
                    default=None) if len(members) < MIN_FACET else None)
                if home is not None:
                    home[1].extend(members)
                else:
                    big.append([key, members])
            facets = big
        facets.sort(key=lambda fc: fc[0])
        self.facet_keys = [key for key, _members in facets]
        self.labels = [label([cells[i] for i in members]) for _key, members in facets]
        self.weights = [math.sqrt(sum(popularity[i] for i in members)) for _key, members in facets]
        self.members = [len(members) for _key, members in facets]
        self.facet = {i: n for n, (_key, members) in enumerate(facets) for i in members}
        # Any other show's facet: the one holding most of its cell at the narrowest level that has one.
        self.places = []
        for level in levels:
            tally = {}
            for i in kept:
                votes = tally.setdefault(level(cells[i]), {})
                votes[self.facet[i]] = votes.get(self.facet[i], 0) + 1
            self.places.append((level, {key: max(sorted(votes), key=votes.get) for key, votes in tally.items()}))
        self.biggest = max(range(len(facets)), key=lambda n: (self.members[n], -n))

        by_language = {}
        for i in kept:
            by_language.setdefault(shows[i]['language'], []).append(self.known(i))
        for values in by_language.values():
            values.sort()
        vocabulary = {}

        def tokens(i):
            s = shows[i]
            mask = 0
            for w in ['g:' + g for g in s['genres']] + ['w:' + w for w in sorted(self.subgenres(i))] + [
                    't:' + s['type'], f'd:{decade(s["year"])}']:
                mask |= 1 << vocabulary.setdefault(w, len(vocabulary))
            return mask
        masks = {i: tokens(i) for i in kept}
        self.score, self.pool = {}, []
        for _key, members in facets:
            mine = [masks[i] for i in members]
            typical = [sum((m & o).bit_count() / (m | o).bit_count() for b, o in enumerate(mine) if b != a and m | o)
                       / max(1, len(members) - 1) for a, m in enumerate(mine)]
            top = max(typical) or 1.0
            for i, r in zip(members, typical):
                f, r = percentile(by_language[shows[i]['language']], self.known(i)), r / top
                self.score[i] = 2 * f * r / (f + r) if f + r else 0.0
            ranked = sorted(members, key=lambda i: (-self.score[i], *self.familiar(i)))
            # Two from each language group, then four, and so on, so no group crowds out
            # the rest; anime is Japanese by nature and simply keeps its best.
            cap = PER_GROUP if _key[0] != 'anime' else PER_FACET
            best, per = [], {}
            while len(best) < min(PER_FACET, len(ranked)):
                for i in ranked:
                    group = GROUP_OF.get(shows[i]['language'], shows[i]['language'])
                    if len(best) < PER_FACET and i not in best and per.get(group, 0) < cap:
                        per[group] = per.get(group, 0) + 1
                        best.append(i)
                cap += PER_GROUP
            self.pool.append(sorted(best, key=ranked.index))

        # How alike two facets are: the cosine of their members' token counts, family included.
        vectors = []
        for _key, members in facets:
            counts = {}
            for i in members:
                counts['family:' + cells[i][3]] = counts.get('family:' + cells[i][3], 0) + 1
                mask = masks[i]
                while mask:
                    low = mask & -mask
                    counts[low] = counts.get(low, 0) + 1
                    mask ^= low
            norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
            vectors.append({k: v / norm for k, v in counts.items()})
        self.near = [[m for _alike, m in sorted(((sum(v * other.get(k, 0.0) for k, v in mine.items()), m)
                                                 for m, other in enumerate(vectors) if m != n),
                                                key=lambda pair: (-pair[0], pair[1]))]
                     for n, mine in enumerate(vectors)]

    def facet_of(self, i):
        """The facet a show belongs to, or would sit in, whether or not it is in the pool."""
        n = self.facet.get(i)
        if n is not None:
            return n
        c = self.cell(i)
        for level, found in self.places:
            if level(c) in found:
                return found[level(c)]
        return self.biggest

    def _locale_list(self, members):
        """The best known eligible shows of a language or country, one per franchise, each
        with its percentile among them."""
        values = sorted(self.known(i) for i in members)
        taken, out = set(), []
        for i in members:
            keys = self.keys(i)
            if keys & taken:
                continue
            taken |= keys
            out.append((i, percentile(values, self.known(i))))
            if len(out) == LOCALE_TOP:
                break
        return tuple(out)

    def locale_items(self, kind, name):
        """A locale list: a language's, a country's, or a language's within a country."""
        if kind == 'both':
            language, country = name
            return tuple(pair for pair in self.locales.get(('country', country), ())
                         if self.e.shows[pair[0]]['language'] == language)
        return self.locales.get((kind, name), ())

    def familiarity(self, i):
        """A title's popularity percentile across the whole pool."""
        return percentile(self.everyone, self.known(i))

    # ------------------------------------------------------------ drawing

    @lru_cache(maxsize=1024)
    def ranking(self, seed, n):
        """Facet n's titles in the order this seed draws them: each from the best five by
        S still left, with a softmax at the set temperature."""
        return self._draw(seed, f'facet-{self.facet_keys[n]}', [(i, self.score[i]) for i in self.pool[n]])

    @lru_cache(maxsize=256)
    def locale_ranking(self, seed, kind, name):
        """A locale list in this seed's order, drawn the same way by percentile."""
        return self._draw(seed, f'{kind}-{name}', self.locale_items(kind, name))

    @lru_cache(maxsize=256)
    def anchor_ranking(self, seed):
        """Anchors in this seed's order, each as likely as any other to lead."""
        return tuple(sorted(self.anchors, key=lambda i: (-gumbel(seed, 'anchor', self.e.shows[i]['id']),
                                                         self.anchors.index(i))))

    def _draw(self, seed, surface, scored):
        left = sorted(scored, key=lambda pair: (-pair[1], *self.familiar(pair[0])))
        noise = {i: gumbel(seed, surface, self.e.shows[i]['id']) for i, _score in left}
        out = []
        while left:
            window = left[:DRAW_FROM]
            k = max(range(len(window)), key=lambda k: (window[k][1] / TEMPERATURE + noise[window[k][0]], -k))
            out.append(left.pop(k)[0])
        return tuple(out)

    @lru_cache(maxsize=1024)
    def facet_order(self, seed, rnd, surface='facets', world=1.0):
        """Facets in a round's order: a Gumbel draw weighted by the square root of each
        facet's summed popularity, world facets at ``world`` times that weight."""
        keyed = {n: math.log(self.weights[n] * (world if self.facet_keys[n][2] == 'World' else 1.0))
                 + gumbel(seed, f'{surface}-{rnd}', repr(self.facet_keys[n]))
                 for n in range(len(self.pool))}
        return tuple(sorted(keyed, key=lambda n: (-keyed[n], n)))

    def plan(self, lang, count):
        """How a screen is shared out: (anchors, facet slots, flexible slots, sources),
        each source a locale list and how many titles it gives."""
        language, region = locale(lang)
        anchors = min(len(self.anchors), max(1, round(count * 3 / COUNT)))
        flexible = max(1, round(count * 4 / COUNT))
        sources = []
        if language and language != 'English' and self.locale_items('language', language):
            wanted = round(count * 7 / COUNT)
            if region and self.locale_items('both', (language, region)):
                sources = [('both', (language, region), flexible), ('language', language, wanted - flexible)]
            else:
                sources = [('language', language, wanted)]
        elif language == 'English' and region and region != 'US' and self.locale_items('country', region):
            sources = [('country', region, flexible)]
        flexible = max(flexible, sum(n for _kind, _name, n in sources))
        world = WORLD_SHARE if language in (None, 'English') else 1.0
        return anchors, count - anchors - flexible, flexible, tuple(sources), world

    def choose(self, seed=None, rnd=0, picked=(), lang='', count=COUNT):
        """The screen for a seed, a round, the ids picked so far and a language tag, as
        Slot(index, why, facet label) in order. Deterministic, and cached."""
        if not MIN_COUNT <= count <= MAX_COUNT:
            raise ValueError(f'Ask for {MIN_COUNT} to {MAX_COUNT} shows.')
        if not 0 <= rnd <= MAX_ROUND:
            raise ValueError(f'Ask for a round from 0 to {MAX_ROUND}.')
        known = tuple(dict.fromkeys(self.e.by_id[x] for x in picked if x in self.e.by_id))[:MAX_PICKED]
        return self._choose(seed or None, rnd, known, lang or '', count)

    @lru_cache(maxsize=4096)
    def _choose(self, seed, rnd, picked, lang, count):
        screen = Screen(self, seed, rnd, count)
        screen.fill(self.plan(lang, count))
        for i in picked:
            screen.pick(i)
        return tuple(Slot(i, why, self.labels[n]) for i, why, n in screen.slots)


class Screen:
    """One screen being drawn: its slots in order, each [index, why, facet]."""

    def __init__(self, starters, seed, rnd, count):
        self.s, self.seed, self.rnd, self.count = starters, seed, rnd, count
        self.slots = []
        self.warm = {}          # a locale title's percentile within its locale
        self.pinned = set()     # places holding picks
        self.recent = set()     # places the last pick filled
        self.gone = set()       # titles leaving in the swap under way
        self.picks = {}         # facet: picks in it
        self.blocked = set()    # franchise keys of the picks

    def fits(self, i, without=()):
        """Whether a title can join: not on screen, picked or leaving, sharing no franchise
        with anything on screen or picked, and its facet under the cap. The places in
        without are being vacated, so they do not count."""
        s = self.s
        keys = s.keys(i)
        if i in self.gone or keys & self.blocked:
            return False
        n, same = s.facet_of(i), 0
        for q, slot in enumerate(self.slots):
            if q in without:
                continue
            if slot[0] == i or keys & s.keys(slot[0]):
                return False
            same += slot[2] == n
        return same < FACET_CAP

    def first_fit(self, ranking, start=0, test=None, without=()):
        """The first title of a ranking, from a place onward and around, that can join."""
        for k in range(len(ranking)):
            i = ranking[(start + k) % len(ranking)]
            if (test is None or test(i)) and self.fits(i, without):
                return i
        return None

    def tally(self, without=()):
        """What the screen spans, for the quotas, leaving out the places in without."""
        s = self.s
        kept = [slot for q, slot in enumerate(self.slots) if q not in without]
        forms = [s.format_of(slot[0]) for slot in kept]
        shows = [s.e.shows[slot[0]] for slot in kept]
        return {'formats': len(set(forms)), 'decades': len({decade(x['year']) for x in shows if x['year']}),
                'cartoons': sum(form in ('animation', 'anime') for form in forms),
                'unscripted': forms.count('unscripted'),
                'foreign': sum(x['language'] not in (None, 'English') for x in shows)}

    # ------------------------------------------------------------ the draw

    def fill(self, plan):
        s, seed, rnd = self.s, self.seed, self.rnd
        n_anchors, n_facets, _flexible, sources, world = plan
        order = s.anchor_ranking(seed)
        for k in range(len(order)):
            if len(self.slots) == n_anchors:
                break
            i = order[(n_anchors * rnd + k) % len(order)]
            if self.fits(i):
                self.slots.append([i, 'anchor', s.facet_of(i)])
        # The visitor's language or country next, so the facets leave room for it; what one
        # list cannot give passes to the next, and what none can give goes to exploring.
        short = 0
        for kind, name, wanted in sources:
            wanted += short
            ranking, items = s.locale_ranking(seed, kind, name), dict(s.locale_items(kind, name))
            got = 0
            for k in range(len(ranking)):
                if got == wanted:
                    break
                i = ranking[(wanted * rnd + k) % len(ranking)]
                if self.fits(i):
                    self.slots.append([i, 'locale', s.facet_of(i)])
                    self.warm[i] = items[i]
                    got += 1
            short = wanted - got
        order, need, taken, left = s.facet_order(seed, rnd, world=world), quotas(self.count), set(), n_facets

        def take(n, why='facet'):
            i = self.first_fit(s.ranking(seed, n), rnd)
            if i is None:
                return False
            taken.add(n)
            self.slots.append([i, why, n])
            return True

        def reserve(test):
            nonlocal left
            if left > 0 and any(n not in taken and test(n) and take(n) for n in order):
                left -= 1
                return True
            return False
        # Quotas first, each met by the likeliest facet that meets it; then the rest in order.
        if self.tally()['cartoons'] < need['cartoons']:
            reserve(lambda n: s.facet_keys[n][0] in ('animation', 'anime'))
        if self.tally()['unscripted'] < need['unscripted']:
            reserve(lambda n: s.facet_keys[n][0] == 'unscripted')
        while self.tally()['formats'] < need['formats']:
            have = {s.format_of(slot[0]) for slot in self.slots}
            if not reserve(lambda n: s.facet_keys[n][0] not in have):
                break
        while self.tally()['foreign'] < need['foreign']:
            if not reserve(lambda n: s.facet_keys[n][2] == 'World'):
                break
        for n in order:
            if left <= 0:
                break
            if n not in taken and take(n):
                left -= 1
        # Whatever is left explores facets not on screen yet, drawn afresh.
        explore = s.facet_order(seed, rnd, 'explore', world)
        for n in explore:
            if len(self.slots) >= self.count:
                break
            if n not in taken:
                take(n, 'explore')
        for n in explore:
            while len(self.slots) < self.count and take(n, 'explore'):
                pass
        self.decades()
        self.arrange()

    def decades(self):
        """Swap facet titles for others of their facet from decades not yet on screen,
        weakest facet first, until the screen spans enough of them."""
        s, need = self.s, quotas(self.count)['decades']
        for q in range(len(self.slots) - 1, -1, -1):
            if self.tally()['decades'] >= need:
                return
            if self.slots[q][1] not in ('facet', 'explore'):
                continue
            present = {decade(s.e.shows[slot[0]]['year']) for slot in self.slots} | {None}
            other = self.first_fit(s.ranking(self.seed, self.slots[q][2]), self.rnd, without={q},
                                   test=lambda j: decade(s.e.shows[j]['year']) not in present)
            if other is not None:
                self.slots[q][0] = other

    def arrange(self):
        """Anchors first, two in the first row and the quick picks leading; the rest most
        familiar first, a locale title by how well its own locale knows it, and never two
        of one facet side by side."""
        s = self.s
        anchors = sorted((slot for slot in self.slots if slot[1] == 'anchor'),
                         key=lambda slot: (slot[0] not in s.quick, *s.familiar(slot[0])))
        warm = lambda slot: max(s.familiarity(slot[0]), self.warm.get(slot[0], 0.0))
        rest = sorted((slot for slot in self.slots if slot[1] != 'anchor'),
                      key=lambda slot: (-warm(slot), *s.familiar(slot[0])))
        if len(anchors) > 2 and anchors[0][2] == anchors[1][2]:
            anchors[1], anchors[2] = anchors[2], anchors[1]
        out = [None] * len(self.slots)
        for place, slot in zip(anchor_places(len(anchors), len(out)), anchors):
            out[place] = slot
        for place in range(len(out)):
            if out[place] is None:
                beside = {out[q][2] for q in (place - 1, place + 1) if 0 <= q < len(out) and out[q] is not None}
                out[place] = rest.pop(next((k for k, slot in enumerate(rest) if slot[2] not in beside), 0))
        self.slots = out
        self.untangle()

    def untangle(self):
        """Where two of one facet still sit side by side, swap the second with the nearest
        title that can take its place without making another such pair."""
        slots = self.slots

        def clear(q):
            return all(slots[r][2] != slots[q][2] for r in (q - 1, q + 1) if 0 <= r < len(slots))
        for q in range(1, len(slots)):
            if slots[q][2] != slots[q - 1][2]:
                continue
            for r in sorted(range(len(slots)), key=lambda r: (abs(r - q), r)):
                if r == q or 'anchor' in (slots[q][1], slots[r][1]) or q in self.pinned or r in self.pinned:
                    continue
                slots[q], slots[r] = slots[r], slots[q]
                if clear(q) and clear(r):
                    break
                slots[q], slots[r] = slots[r], slots[q]

    # ------------------------------------------------------------ adapting

    def pick(self, i):
        """A pick stays where it is, or off the screen if it was not on it, and swaps three
        unpicked slots for a contrast, a neighbour and an unexplored facet."""
        s = self.s
        n = s.facet_of(i)
        self.picks[n] = self.picks.get(n, 0) + 1
        self.blocked |= s.keys(i)
        at = next((q for q, slot in enumerate(self.slots) if slot[0] == i and q not in self.pinned), None)
        if at is not None:
            self.pinned.add(at)
            self.slots[at] = [i, 'picked', n]
        # Anything sharing a franchise with a pick goes.
        for q, slot in enumerate(self.slots):
            if q not in self.pinned and s.keys(slot[0]) & self.blocked:
                self.place([q], [self.unexplored({q}) or self.nearest(n, {q})])
        self.swap(i, n, at)
        self.balance()

    def swap(self, i, n, at):
        leaving = self.leaving(at)
        without, arrivals = set(leaving), []
        self.gone = {self.slots[q][0] for q in leaving}
        for choose in (lambda: self.contrast(i, n, without), lambda: self.nearest(n, without),
                       *[lambda: self.unexplored(without)] * SWAPS):
            if len(arrivals) == len(leaving):
                break
            got = choose()
            if got is not None:
                arrivals.append(got)
                # Held on screen until placed, so no later choice repeats it or its franchise.
                self.slots.append([got[0], got[1], self.s.facet_of(got[0])])
        del self.slots[len(self.slots) - len(arrivals):]
        self.gone = set()
        self.place(leaving[:len(arrivals)], arrivals)
        self.recent = set(leaving[:len(arrivals)])

    def leaving(self, at):
        """The unpicked places a pick swaps: titles from facets that already have a pick,
        then from facets with more than one title on screen; anchors and the last pick's
        arrivals last, and nearest the pick among equals. None goes whose loss would take
        the screen below a quota it meets."""
        counts = {}
        for slot in self.slots:
            counts[slot[2]] = counts.get(slot[2], 0) + 1
        where = at if at is not None else len(self.slots)

        def cost(q):
            _i, why, n = self.slots[q]
            return (why == 'anchor', q in self.recent, -self.picks.get(n, 0), -min(counts[n] - 1, 2),
                    abs(q - where), q)
        out = []
        for q in sorted((q for q in range(len(self.slots)) if q not in self.pinned), key=cost):
            if len(out) == SWAPS:
                break
            if self.keeps_quotas(set(out) | {q}):
                out.append(q)
        return out

    def keeps_quotas(self, without):
        """Whether the screen still meets every quota it meets now without these places."""
        need, now, then = quotas(self.count), self.tally(), self.tally(without)
        return all(then[k] >= need[k] for k in need if now[k] >= need[k])

    def contrast(self, i, n, without):
        """A title from the pick's facet that differs from it in era, language or subgenre."""
        s, shows = self.s, self.s.e.shows
        mine = shows[i]
        words = s.subgenres(i) or set(mine['genres'])

        def differs(j):
            other = shows[j]
            theirs = s.subgenres(j) or set(other['genres'])
            overlap = len(words & theirs) / len(words | theirs) if words | theirs else 1.0
            return decade(other['year']) != decade(mine['year']) or other['language'] != mine['language'] \
                or overlap < 0.5
        j = self.first_fit(s.ranking(self.seed, n), self.rnd, test=differs, without=without)
        return None if j is None else (j, 'contrast')

    def nearest(self, n, without):
        """A title from the facet most like the pick's."""
        for m in self.s.near[n]:
            j = self.first_fit(self.s.ranking(self.seed, m), self.rnd, without=without)
            if j is not None:
                return j, 'nearest'
        return None

    def unexplored(self, without):
        """A title from the likeliest facet with no pick and nothing on screen, a facet
        just vacated counting as on screen; failing that, from the facet with no pick and
        the fewest titles on screen."""
        s = self.s
        counts = {}
        for slot in self.slots:
            counts[slot[2]] = counts.get(slot[2], 0) + 1
        for m in sorted((m for m in s.facet_order(self.seed, self.rnd) if not self.picks.get(m)),
                        key=lambda m: counts.get(m, 0)):
            j = self.first_fit(s.ranking(self.seed, m), self.rnd, without=without)
            if j is not None:
                return j, 'unexplored'
        return None

    def place(self, places, arrivals):
        """Put arrivals into places, in the order that leaves fewest facets side by side."""
        arrivals = [a for a in arrivals if a is not None]
        places = places[:len(arrivals)]
        if not arrivals:
            return
        facet_of = self.s.facet_of

        def clashes(order):
            trial = [slot[2] for slot in self.slots]
            for q, (i, _why) in zip(places, order):
                trial[q] = facet_of(i)
            return sum(trial[q] == trial[r] for q in places for r in (q - 1, q + 1) if 0 <= r < len(trial))
        best = min(permutations(arrivals), key=clashes)
        for q, (i, why) in zip(places, best):
            self.slots[q] = [i, why, facet_of(i)]

    def balance(self):
        """Keep at least 60% of the unpicked titles from facets with no pick yet."""
        free = [q for q in range(len(self.slots)) if q not in self.pinned]
        for _ in free:
            explored = [q for q in free if self.picks.get(self.slots[q][2])]
            if len(free) - len(explored) >= UNEXPLORED * len(free):
                return
            spare = [q for q in explored if self.keeps_quotas({q})]
            if not spare:
                return
            q = max(spare, key=lambda q: (self.slots[q][1] not in ('contrast', 'anchor'), q))
            got = self.unexplored({q})
            if got is None:
                return
            self.place([q], [got])
