"""Couchside's shelves: rows, title pages and match scores over the shared engine.

The engine answers one question, what to watch next. A streaming front page asks
several at once (top picks, more like each show you loved, the best of a genre for
you, what is new), so this works out how close everything sits to each rated show
once per request and cuts every row from that. Nothing about a person is kept
between requests.

The home page (Page) follows what Netflix, Prime Video, YouTube and Spotify have
published about theirs. It weighs many candidate rows: more like each favourite,
micro-genres named from what an interest leans toward, creators, casts and franchises
a list shares, hidden gems, limited series. It then chooses and orders rows one at a
time for relevance, less what a row would repeat of the rows above it, and gives each
interest in the list rows in proportion to its weight (Steck's calibration). Past
today's rows the page goes on without a set end, tier by tier: more from the list
itself, each interest's own rows, exploring and browsing, until the last tier is spent.
Pages arrive eight rows at a time and are rebuilt the same from the same request, so a
browser asking for more says which rows it already shows. fresh.py turns the day and
the browser's memory of what it showed into the day's order, cards and hero.
"""
from array import array
from bisect import bisect_left
from collections import Counter
from datetime import date
from functools import lru_cache
from operator import itemgetter
import gzip
import heapq
import math
import re
import statistics
import struct
import sys

from engine import FORMAT_GROUPS, TIE_COMMON, Closeness, Wide
from fresh import dither, pick_one, spread, shuffle_rows, ROW_EPSILON, ROW_KEY
from starters import Starters
from taste import COUNTRIES, decade as decade_of

IMAGE = 'https://static.tvmaze.com/uploads/images/{size}/{bucket}/{image}.jpg'
ROW = 20            # cards in a row
SHORTEST = 8        # a row with fewer cards than this is left out
MORE = 12           # cards under More like this
GLANCE = 6          # cards a row shows before scrolling, kept distinct across rows
MAX_SAVED = 200     # My List, the same ceiling the transfer code carries
FALLBACK = 12       # first-visit posters the page carries for when it cannot ask for starters

GENRE_ROWS = {
    'Action': 'Action shows', 'Adventure': 'Adventures', 'Anime': 'Anime', 'Children': 'For the kids',
    'Comedy': 'Comedies', 'Crime': 'Crime TV shows', 'DIY': 'DIY and makeovers', 'Drama': 'Dramas',
    'Espionage': 'Spy shows', 'Family': 'Family watching', 'Fantasy': 'Fantasy shows', 'Food': 'Food shows',
    'History': 'History shows', 'Horror': 'Horror', 'Legal': 'Legal dramas', 'Medical': 'Medical shows',
    'Music': 'Music shows', 'Mystery': 'Mysteries', 'Nature': 'Nature shows', 'Romance': 'Romance',
    'Science-Fiction': 'Sci-fi shows', 'Sports': 'Sports shows', 'Supernatural': 'Supernatural shows',
    'Thriller': 'Thrillers', 'Travel': 'Travel shows', 'War': 'War stories', 'Western': 'Westerns',
}
THEME_ROWS = {
    'Crime / illicit enterprise': 'Crime and the underworld', 'Money / class': 'Money and class',
    'Family ties': 'Family ties', 'Power / ambition': 'Power and ambition',
    'Deception / secrets': 'Secrets and lies', 'Danger / survival': 'Survival stories',
    'Adventure / quest': 'Quests and adventures', 'Law / investigation': 'Cases to crack',
    'Friendship / youth': 'Friendship and growing up', 'Romance': 'Love stories',
    'Supernatural / fantasy': 'Otherworldly stories', 'Humor': 'Shows that make you laugh',
    'Science / technology': 'Science and technology', 'Space / other worlds': 'Other worlds',
    'Medicine / health': 'Life and death in medicine', 'War / military': 'War and the military',
    'History / period setting': 'Period pieces', 'Work / business': 'Workplace stories',
    'School / education': 'School stories', 'Identity / self-discovery': 'Finding yourself',
    'Revenge / redemption': 'Revenge and redemption', 'Psychology / mental health': 'Minds under pressure',
    'Competition / achievement': 'Winners and contenders', 'Sport / athletics': 'Sporting lives',
    'Music / performance': 'Music and performance', 'Food / cooking': 'Food and cooking',
    'Nature / wildlife': 'Nature and wildlife', 'Travel / cultures': 'Travel and cultures',
    'Relationships / dating': 'Love and dating', 'Home / design': 'Home and design',
    'Belief / spirituality': 'Faith and belief', 'Mystery / puzzles': 'Mysteries to solve',
}
# Rows for a first visit, before anything is rated: best known first.
COLD_ROWS = [('genre', 'Drama'), ('genre', 'Comedy'), ('genre', 'Crime'), ('genre', 'Science-Fiction'),
             ('format', 'animation'), ('genre', 'Thriller'), ('format', 'documentary'),
             ('genre', 'Fantasy'), ('format', 'unscripted'), ('genre', 'Anime')]
FORMAT_ROWS = {'animation': 'Animated series', 'documentary': 'Documentaries', 'unscripted': 'Reality and competition'}
NEW_DAYS = 150      # a show premiered this recently before the snapshot wears a New badge
DESCRIPTION = 'Rows of TV shows picked for your taste, with trailers, where to watch and My List.'

# ------------------------------------------------------------------ the home page
FIRST_PAGE = 8          # rows in the first answer
NEXT_PAGE = 6           # rows in each answer after it, asked for as the reader nears the end
MOST_ROWS = 30          # today's rows (tier 0) are at most this many
FEWEST_ROWS = 20        # and, when there is enough to show, at least this many
TIERS = 4               # tiers past today's rows: the list itself, each interest, exploring, browsing
LONGEST = 300           # a page without a set end still stops here, which bounds what a request carries
RECENT = 12             # a deeper tier is judged by its own rows, or this many rows above while it has fewer
WEAK = 0.5              # and is weak once its best row falls below this share of their median
PINNED = 2              # cards at the front of a row that keep their places from day to day
LIST_ROW = 20           # My List's row holds the most recently added
CREATOR_SHORTEST = 6    # one creator seldom has eight shows, so their row may hold six
TOP_POOL = 100          # Top picks are calibrated from this many of the plain ranking
# Steck's lambda for pulling Top picks toward the list's mix of interests. The engine's
# ranking already gives each interest its share (engine.Ranking), and on the bench any
# further pull only moved the best picks off the first cards, so it is off.
CALIBRATION = 0.0
SIMILAR = 0.3           # closeness at which a show counts as similar to a seed
NEIGHBOURS = 12         # similar shows a seed needs before it can lead a row
NOT_FOR_ME = 0.5        # closeness to a show marked Not for me that keeps a show off the page
NICHE = 12              # shows a micro-genre needs before it is a row
DEPTH_POOL = 3000       # how far down the ranking, overall or in an interest, a filtered row looks
FILTER_POOL = 150       # matches a filtered row weighs before cutting to a row
SEED_POOL = 80          # the cards a seed's row keeps, from every similar show it weighs
LIKE_POOL = 600         # the shows closest to My List that its row weighs
FITTING = 3000          # a seed's row looks among the best this many fits, overall and in its interest
ROTATE = 3              # a day's seed rotates among an interest's best this many
WIDE_SEEDS = 60         # a long list's liked shows that rows of their own are cut for, loves and then the newest
INTEREST_FLOOR = 0.08   # an interest this heavy gets at least one row
INTEREST_CAP = 0.4      # and none, with three or more interests, holds more of the rows
MOST_INTERESTS = 8      # interests weighed for rows of their own
INTEREST_ROWS = 0.55    # the share of a page planned for rows that serve one interest
SEED_ROWS = (2, 8)      # "Because you loved" rows among today's, fewest and most; tier 1 has one for each
LIGHT_LIST = 10         # below this many liked shows, personal rows are at most half of today's
REAPPEAR = 0.7          # a show that opened an earlier row counts this much again
TAG_SPREAD = 0.3        # how hard the first cards of a row avoid looking alike
PLACE_SHARE = 0.15      # a language or country this share of liked shows is a row
HIDDEN = (0.4, 0.75, 0.2)   # hidden gems: popularity percentile at most, rating quantile, top taste share
CALLOUTS = 10           # cards in a row that may carry a call-out
POSITION = [1 / math.log2(k + 2) for k in range(GLANCE)]     # how much each of the first cards counts
SHARP = 8               # a card's fit for weighing rows: the share of the pool it outranks, to this power
# Rating to interest weight, with recent ratings counting more than old ones.
INTEREST_WEIGHT = {1: 1.0, .7: 0.6, .35: 0.2}
# How much a row's evidence counts: rows seeded by a loved show say most about a person,
# rows that serve one interest more than rows cut across the whole list, and rows that
# are not personal least.
EVIDENCE = {'top': 1.0, 'loved': 1.0, 'liked': 0.8, 'niche': 0.9, 'cast': 0.9, 'acclaimed': 0.85, 'place': 0.85,
            'creators': 0.8, 'gems': 0.8, 'limited': 0.8, 'new': 0.8, 'like-list': 0.8, 'genre': 0.75,
            'theme': 0.7, 'plain': 0.7, 'language': 0.75, 'different': 0.6}
# Row kinds whose places are set rather than chosen.
FIXED_KINDS = ('top', 'list', 'top10')
# Rows whose order is their point: Top picks and Because you loved keep the ranking's
# order past franchise and creator limits, without spreading a network's shows apart,
# since a big streamer's shows are many and alike only in where they stream.
PRECISE_KINDS = ('top', 'seed')

# How an interest's leanings read in a row's name ("Dark British crime dramas",
# "Mockumentaries from the 2000s"): an adjective, a country or language, a subgenre and
# an era, five words at most. A noun is a whole plural. A topic takes the form most of
# the interest's shows share (crime dramas, crime anime, crime documentaries). Leanings
# not listed are left out of names rather than guessed at.
NOUNS = {
    'sitcom': 'sitcoms', 'animated sitcom': 'animated sitcoms', 'teen sitcom': 'teen sitcoms',
    'mockumentary': 'mockumentaries', 'pseudo documentary': 'mockumentaries', 'panel game': 'panel games',
    'game show': 'game shows', 'police procedural': 'police procedurals', 'procedural': 'procedurals',
    'police drama': 'police dramas', 'medical drama': 'medical dramas', 'legal drama': 'legal dramas',
    'political drama': 'political dramas', 'historical drama': 'period dramas', 'period drama': 'period dramas',
    'teen drama': 'teen dramas', 'family drama': 'family dramas', 'romantic drama': 'romantic dramas',
    'comedy drama': 'comedy dramas', 'musical drama': 'musical dramas', 'romantic comedy': 'romantic comedies',
    'animated comedy': 'animated comedies', 'black comedy': 'dark comedies', 'soap opera': 'soaps',
    'telenovela': 'telenovelas', 'sketch show': 'sketch shows', 'cooking show': 'cooking shows',
    'talent show': 'talent shows', 'variety show': 'variety shows', 'late night talk show': 'late-night talk shows',
    'talk show': 'talk shows', 'nature documentary': 'nature documentaries', 'true crime': 'true crime',
    'popular science': 'science documentaries', 'space opera': 'space operas', 'anthology': 'anthology series',
    'action thriller': 'action thrillers', 'psychological thriller': 'psychological thrillers',
    'thriller': 'thrillers', 'espionage': 'spy thrillers', 'spy': 'spy thrillers', 'western': 'Westerns',
    'docudrama': 'docudramas', 'docu soap': 'docusoaps', 'melodrama': 'melodramas', 'superhero': 'superhero shows',
    'zombie': 'zombie shows', 'vampire': 'vampire shows', 'time travel': 'time-travel stories',
    'coming of age': 'coming-of-age stories', 'mystery': 'mysteries', 'detective and mystery': 'mysteries',
    'detective': 'detective shows', 'competition': 'reality competitions', 'documentary': 'documentaries',
    'adult animation': 'adult animation', 'parody': 'parodies', 'biography': 'biopics',
    "children's": "children's shows", 'educational': 'educational shows', 'slice of life': 'slice-of-life stories',
    'survival': 'survival stories', 'musical': 'musicals', 'post apocalyptic': 'post-apocalyptic stories',
    'dystopian': 'dystopian stories', 'satire': 'satires', 'neo noir': 'neo-noir', 'isekai': 'isekai anime',
    'mecha': 'mecha anime', 'magical girl': 'magical girl anime', 'iyashikei': 'iyashikei anime',
    'tokusatsu': 'tokusatsu shows', 'nordic noir': 'Nordic noir', 'korean drama': 'K-dramas',
    'sageuk': 'Korean period dramas', 'indian soap opera': 'Indian soaps', 'telenarconovela': 'narco dramas',
    # TVmaze's genres and formats
    'Mystery': 'mysteries', 'Thriller': 'thrillers', 'Comedy': 'comedies', 'Legal': 'legal dramas',
    'Medical': 'medical dramas', 'Espionage': 'spy thrillers', 'Western': 'Westerns', 'Food': 'food shows',
    'Travel': 'travel shows', 'DIY': 'DIY shows', 'Children': "children's shows",
    'Panel Show': 'panel shows', 'Talk Show': 'talk shows', 'Game Show': 'game shows', 'Variety': 'variety shows',
    'Anime': 'anime', 'Animation': 'animated shows', 'Documentary': 'documentaries', 'Reality': 'reality shows',
}
# A core that says no more than its form ("anime" for an anime interest) leads last.
GENERIC = ('anime', 'animated shows', 'documentaries', 'reality shows', 'dramas', 'comedies')
SINGULAR = {'slice of life': 'slice-of-life', 'coming of age': 'coming-of-age', 'post apocalyptic': 'post-apocalyptic',
            'time travel': 'time-travel', 'magical girl': 'magical girl'}
TOPICS = {
    'crime': 'crime', 'Crime': 'crime', 'fantasy': 'fantasy', 'Fantasy': 'fantasy', 'dark fantasy': 'fantasy',
    'science fiction': 'sci-fi', 'Science-Fiction': 'sci-fi', 'adventure': 'adventure', 'Adventure': 'adventure',
    'action and adventure': 'action', 'action': 'action', 'Action': 'action', 'horror': 'horror',
    'Horror': 'horror', 'supernatural': 'supernatural', 'Supernatural': 'supernatural', 'historical': 'period',
    'History': 'period', 'political': 'political', 'medical': 'medical', 'war': 'war', 'War': 'war',
    'sports': 'sports', 'Sports': 'sports', 'music': 'music', 'Music': 'music', 'nature': 'nature',
    'Nature': 'nature', 'family': 'family', 'Family': 'family', 'teen': 'teen', 'youth': 'teen',
    'school': 'school', 'romance': 'romance', 'Romance': 'romance', 'Drama': 'drama',
}
# Nouns that already name where their shows come from, so no country goes in front.
REGIONAL = ('Nordic noir', 'K-dramas', 'Korean period dramas', 'Indian soaps', 'telenovelas', 'narco dramas')
# (word, whether it goes before the country, and the leanings behind it). "Dark British
# crime dramas" but "British period dramas".
ADJECTIVES = [
    ('Dark', True, ('dark fantasy', 'black comedy', 'neo noir', 'noir', 'psychological thriller', 'psychological horror')),
    ('Dystopian', True, ('dystopian',)), ('Post-apocalyptic', True, ('post apocalyptic',)),
    ('Satirical', True, ('satire', 'political satire')), ('Psychological', False, ('psychological',)),
    ('Supernatural', False, ('supernatural', 'paranormal', 'Supernatural')), ('Political', False, ('political',)),
    ('Period', False, ('historical', 'period drama', 'historical drama', 'History')),
    ('Romantic', False, ('romance', 'romantic comedy', 'romantic drama', 'Romance')),
    ('Teen', False, ('teen', 'youth', 'coming of age', 'teen drama')),
]
# The forms a topic takes, and what a show needs to have that form.
FORMS = {
    'anime': (('genre', 'Anime'), ('subgenre', 'anime')), 'animated': (('format', 'Animation'),),
    'documentaries': (('format', 'Documentary'),), 'reality': (('format', 'Reality'),),
    'dramas': (('genre', 'Drama'),), 'comedies': (('genre', 'Comedy'),),
}
# The browser's language, from its tag, as the catalogue names languages.
LANGUAGES = {
    'es': 'Spanish', 'fr': 'French', 'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch',
    'sv': 'Swedish', 'no': 'Norwegian', 'nb': 'Norwegian', 'nn': 'Norwegian', 'da': 'Danish', 'fi': 'Finnish',
    'is': 'Icelandic', 'pl': 'Polish', 'cs': 'Czech', 'sk': 'Slovak', 'hu': 'Hungarian', 'ro': 'Romanian',
    'el': 'Greek', 'tr': 'Turkish', 'ru': 'Russian', 'uk': 'Ukrainian', 'ja': 'Japanese', 'ko': 'Korean',
    'zh': 'Chinese', 'th': 'Thai', 'hi': 'Hindi', 'ar': 'Arabic', 'he': 'Hebrew', 'id': 'Indonesian',
    'ms': 'Malay', 'vi': 'Vietnamese', 'tl': 'Tagalog', 'fil': 'Tagalog', 'ta': 'Tamil', 'te': 'Telugu',
    'bn': 'Bengali', 'mr': 'Marathi', 'ml': 'Malayalam', 'kn': 'Kannada', 'pa': 'Punjabi', 'ur': 'Urdu',
    'fa': 'Persian', 'ca': 'Catalan', 'eu': 'Basque', 'gl': 'Galician', 'hr': 'Croatian', 'sr': 'Serbian',
    'sl': 'Slovenian', 'bg': 'Bulgarian', 'et': 'Estonian', 'lv': 'Latvian', 'lt': 'Lithuanian',
    'af': 'Afrikaans', 'sq': 'Albanian', 'ka': 'Georgian', 'kk': 'Kazakh', 'mn': 'Mongolian', 'cy': 'Welsh',
}
LANG_TAG = re.compile(r'[A-Za-z]{2,3}(?:-[A-Za-z0-9]{1,8}){0,3}$')
# A limited series says so: in its summary, in Wikidata's genres, or in the awards it won.
LIMITED_WORDS = re.compile(r'\b(?:limited[- ]series|mini[- ]?series|(?:two|three|four|five|six|seven|eight|nine|ten|'
                           r'\d{1,2})[- ]part (?:drama|series|thriller|miniseries|documentary|adaptation|story|event)|'
                           r'limited (?:drama|event series|run))\b', re.I)
LIMITED_GENRES = ('miniseries', 'limited run')
LIMITED_AWARDS = ('Primetime Emmy Award for Outstanding Limited Miniseries',
                  'Primetime Emmy Award for Outstanding Miniseries or Movie',
                  'Golden Globe Award for Best Limited or Anthology Series or Television Film',
                  'Satellite Award for Best Miniseries', 'Satellite Award for Best Miniseries or Television Film',
                  "Critics' Choice Television Award for Best Movie/Miniseries")


def lower_first(label):
    """'Crime TV shows' as 'crime TV shows', leaving 'DIY and makeovers' alone."""
    return label[0].lower() + label[1:] if label[1:2].islower() else label


def upper_first(text):
    return text[:1].upper() + text[1:]


def slug(text, most=40):
    return re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')[:most].strip('-') or 'row'


def fans_of(names):
    """'For fans of Breaking Bad and The Wire', from up to two names."""
    names = [n for n in names if n][:2]
    return f'For fans of {" and ".join(names)}' if names else ''


class Rows:
    """Rows being cut for one page. The first cards of a row are the ones a screen shows
    at a glance, so those skip anything an earlier row already opened with. The rest
    keep their own order: a row about Breaking Bad should still hold the shows closest
    to it. With a day and a seed, each row after its first two cards is the day's."""

    def __init__(self, library, taste, fresh=None):
        self.lib, self.taste, self.fresh, self.used, self.rows = library, taste, fresh, set(), []

    def add(self, key, title, items, kind='row', fresh=True):
        if self.fresh:
            today = self.lib.daily(items, self.fresh, f'browse-{key}', ROW, PINNED)
            items = today + [i for i in items if i not in set(today)]
        if fresh:
            head = [i for i in items if i not in self.used][:GLANCE]
            items = head + [i for i in items if i not in head][:ROW - len(head)]
            self.used.update(head)
        else:
            items = items[:ROW]
        if len(items) >= SHORTEST:
            self.fixed(key, title, items, kind)

    def fixed(self, key, title, items, kind='row'):
        self.rows.append({'key': key, 'title': title, 'kind': kind,
                          'items': [self.lib.card(i, self.taste) for i in items]})


class Taste:
    """One request's view of a list: how close every show sits to each rated show, and
    the scores the plain ranking gives. Built once and cut into every row."""

    def __init__(self, library, positives, negatives, settings, candidates):
        self.lib, self.e = library, library.e
        self.positives, self.negatives, self.settings = positives, negatives, settings
        self.candidates = candidates
        # Worked out as the ranking asks: all of them for a short list, a few for a long one.
        self.affinities = Closeness(self.e, settings)
        # Kept for the request, so a show scored later (score_others) sits on the same scale.
        self.ranking = self.e.ranking(positives, negatives, self.affinities, settings)
        self.wide = isinstance(self.ranking, Wide)
        self.scores = self.ranking.score(candidates)
        self.best = max((self.scores[i] for i in candidates), default=0.0)
        self.extra = {}

    def ranked(self, scoring=None):
        """Candidates in order for the whole list, or for a few of its shows. A few are
        still judged by the taste of the interest they belong to across the whole list."""
        scores = self.scores if scoring is None else self.e.rank(
            self.candidates, scoring, self.negatives, self.affinities, self.settings, self.positives)
        return sorted((i for i in self.candidates if scores[i] > 0), key=lambda i: (-scores[i], self.e.shows[i]['id']))

    def score_others(self, indices):
        """Scores for shows outside the pool (rated, obscure, filtered out), worked out
        in one pass so a match can be shown for anything on screen."""
        missing = [i for i in dict.fromkeys(indices) if i not in self.extra]
        if missing and self.positives:
            scores = self.ranking.score(missing)
            self.extra.update((i, scores[i]) for i in missing)

    def match(self, i):
        """The same scale Next Watch uses: 99 is your best pick, and everything else is
        measured against it. None when a show scores nothing at all."""
        score = self.extra.get(i, self.scores[i]) if self.positives else 0.0
        if score <= 0 or self.best <= 0:
            return None
        return max(1, min(99, round(score / self.best * 99)))

    def unit(self, i):
        """The match as a share of the best pick, from 0 to 1."""
        score = self.extra.get(i, self.scores[i])
        return min(1.0, score / self.best) if score > 0 and self.best > 0 else 0.0

    def closest(self, i):
        """The liked show a title sits nearest to, with the signals they share."""
        source = self.ranking.source(i, self.positives)
        mine, theirs = self.e.signals(i), self.e.signals(self.e.by_id[source['id']])
        shared = [t.split(' / ')[0] for t in mine[0] if t in theirs[0]] + [g for g in mine[1] if g in theirs[1]]
        seen, labels = set(), []
        for label in shared:
            if label.lower() not in seen:
                seen.add(label.lower())
                labels.append(label)
        return {'id': source['id'], 'name': self.e.shows[self.e.by_id[source['id']]]['name'],
                'loved': source['weight'] == 1, 'shared': labels[:3],
                'fits': self.ranking.fits(i),
                'ties': self.e.ties(i, self.e.by_id[source['id']])}


class Shelf:
    """A candidate row: its cards in order before today's freshness, and what the page
    builder weighs it by. kind_of says what sort of row it is (a seed, a micro-genre,
    a creator), for keeping two of a sort apart; interest is the interest it serves."""

    def __init__(self, key, title, kind_of, items, score=None, *, kind='row', interest=None, personal=True,
                 evidence=0.85, subtitle='', shortest=SHORTEST, seed=None, callouts=True, diverse=True, proto=None,
                 tier=0):
        self.key, self.title, self.kind_of, self.kind = key, title, kind_of, kind
        self.tier = tier
        self.items = list(dict.fromkeys(items))
        if proto is not None:
            # The clearest example of the row's theme goes first, from its best five.
            best = max(self.items[:5], key=lambda i: (proto(i), -self.items.index(i)), default=None)
            if best is not None:
                self.items.remove(best)
                self.items.insert(0, best)
        self.score = score if score is not None else {i: 1 / (n + 1) for n, i in enumerate(self.items)}
        if proto is not None and self.items:
            self.score = {**self.score, self.items[0]: max(self.score.values()) + 1}
        self.interest, self.personal, self.evidence = interest, personal, evidence
        self.subtitle, self.shortest, self.seed = subtitle, shortest, seed
        self.callouts, self.diverse = callouts, diverse
        self.top12 = frozenset(self.items[:12])
        self.relevance = 0.0

    def glance(self, heads, count):
        """The cards this row would open with, given what the rows above opened with."""
        if self.kind != 'row':
            return self.items[:GLANCE]
        out = []
        for i in self.items:
            if i not in heads and count[i] < 2:
                out.append(i)
                if len(out) == GLANCE:
                    break
        return out


class Pinned:
    """A row the browser already shows, known by its key and first cards."""

    def __init__(self, key, head, shelf=None):
        self.key, self.head, self.shelf = key, head, shelf
        self.kind_of = shelf.kind_of if shelf else None
        self.interest = shelf.interest if shelf else None
        self.personal = shelf.personal if shelf else False
        self.kind = shelf.kind if shelf else 'row'
        self.tier = shelf.tier if shelf else 0
        self.top12 = shelf.top12 if shelf else frozenset(head)
        self.relevance = shelf.relevance if shelf else 0.0


class Page:
    """One person's home page: every candidate row, the rows chosen and their order, the
    cards in each and the hero. Everything comes from the request, so the same request
    on the same day gives the same page."""

    def __init__(self, lib, profile, settings, positives, negatives, rated, candidates, saved, fresh, lang=None):
        self.lib, self.e = lib, lib.e
        self.profile, self.positives, self.negatives = profile, positives, negatives
        self.rated, self.saved, self.fresh, self.lang = rated, saved, fresh, lang
        self.taste = taste = Taste(lib, positives, negatives, settings, candidates)
        self.ranking = taste.ranking
        self.stats = lib.pool_stats(settings)
        e = self.e
        ranked = taste.ranked()
        # Anything very close to a show marked Not for me stays off the page. A long list
        # has so many that this would clear whole genres, so there it goes only when the
        # disliked shows it sits near outweigh the liked ones.
        self.excluded = set()
        if negatives and candidates and taste.wide:
            groups, taken, _closest = taste.ranking.gathered or taste.ranking.gather()
            pool = set(candidates)
            for p in negatives:
                index, close, _evidence = taste.ranking.row(e.by_id[p['id']])
                self.excluded.update(i for i, v in zip(index, close) if v >= NOT_FOR_ME and i in pool
                                     and taken.get(i, 0.0) >= max((found.get(i, 0.0) for found in groups), default=0.0))
        elif negatives and candidates:
            gather = itemgetter(*candidates) if len(candidates) > 1 else (lambda values: (values[candidates[0]],))
            for p in negatives:
                values = gather(taste.affinities[p['id']])
                self.excluded.update(i for i, v in zip(candidates, values) if v >= NOT_FOR_ME)
        self.usable = [i for i in ranked if i not in self.excluded]
        self.depth = self.usable[:DEPTH_POOL]
        # The list's interests, each weighed by its ratings (love 1, like 0.6, OK 0.2),
        # recent ones counting up to two thirds more than old ones.
        self.order = {p['id']: n for n, p in enumerate(profile)}
        n = len(profile)
        self.weight = {p['id']: INTEREST_WEIGHT.get(p['weight'], 0.0) * (0.6 + 0.4 * 0.5 ** ((n - 1 - self.order[p['id']]) / 15))
                       for p in positives}
        self.interests = self.ranking.interests
        weights = [sum(self.weight[p['id']] for p in interest) for interest in self.interests]
        total = sum(weights) or 1.0
        self.share = [w / total for w in weights]
        # The engine scales each interest's scores by its share, so a row for a small
        # interest orders its cards by that interest's own scale.
        top = max(self.ranking.share, default=1.0) or 1.0
        self.relshare = [s / top for s in self.ranking.share]
        whole = [[] for _ in self.interests]
        group = self.ranking.group
        for i in self.usable:
            k = group.get(i)
            if k is not None and k < len(whole):
                whole[k].append(i)
        self.by_interest = [items[:DEPTH_POOL] for items in whole]
        # Where each show ranks, overall and within the interest it was scored for.
        self.place_of = {i: n for n, i in enumerate(self.usable)}
        self.place_in = [({i: n for n, i in enumerate(items)}, len(items)) for items in whole]
        self.ascending = sorted(taste.scores[i] for i in self.usable)
        self.significant = [k for k, s in enumerate(self.share) if s >= INTEREST_FLOOR]
        # Netflix builds about 40 rows and Prime Video about 20. Today's rows (tier 0) are
        # 20 or, with more interests to serve, up to 30, fewer only when they run out; the
        # tiers past them (Deeper) carry the page on from there.
        self.cap = min(MOST_ROWS, max(FEWEST_ROWS, 14 + 3 * len(self.significant)))
        self.light = len(positives) < LIGHT_LIST
        self.day = date.fromisoformat(fresh.day).toordinal() if fresh.day else 0
        self.names = {p['id']: e.shows[e.by_id[p['id']]]['name'] for p in positives}
        self.dropped = {}   # rows left out, and why
        self.tier_of = {}   # the tier each row past today's was placed in
        self._matching = {}
        countries = Counter(e.shows[e.by_id[p['id']]]['country'] for p in positives)
        self.usual_country = countries.most_common(1)[0][0] if countries else None
        self._near, self._fitting = {}, {}

    # ------------------------------------------------------------ scales

    def taste_of(self, i, k=None):
        """How well show i fits the list, from 0 to 1; for an interest's own rows, on that
        interest's scale."""
        value = self.taste.unit(i)
        if k is not None and k < len(self.relshare) and self.relshare[k] > 0:
            value = min(1.0, value / self.relshare[k])
        return value

    def fit(self, i, k=None):
        """How well show i fits the list, for weighing rows: the share of the pool it
        outranks (on its interest's own ranking for an interest's row), to the SHARP
        power, so the top few percent count most without the steep fall of the match."""
        if k is not None and k < len(self.place_in) and i in self.place_in[k][0]:
            places, size = self.place_in[k]
            share = 1 - places[i] / size
        elif i in self.place_of:
            share = 1 - self.place_of[i] / len(self.usable)
        else:
            score = self.taste.extra.get(i, self.taste.scores[i])
            share = bisect_left(self.ascending, score) / len(self.ascending) if self.ascending and score > 0 else 0.0
        return share ** SHARP

    def pop(self, i):
        return self.stats['popularity'][self.e.popularity[i]]

    def quality(self, i):
        rating = self.e.shows[i]['rating']
        if not rating:
            return 0.5
        return (max(-1.5, min(1.5, (rating - 7.2) / 1.2)) + 1.5) / 3

    def default(self, items, k=None):
        """The usual order for a row: 0.65 taste, 0.2 popularity and 0.15 quality, taste
        as a place among the row's shows and popularity as a percentile of the pool."""
        taste = ranks({i: self.taste_of(i, k) for i in items})
        score = {i: 0.65 * taste[i] + 0.2 * self.pop(i) + 0.15 * self.quality(i) for i in items}
        return sorted(score, key=lambda i: (-score[i], self.e.shows[i]['id'])), score

    def take(self, test, pool=None, most=FILTER_POOL):
        out = []
        for i in self.depth if pool is None else pool:
            if test(i):
                out.append(i)
                if len(out) >= most:
                    break
        return out

    def near(self, show_id, k=None):
        """Every show similar to one rated show among those that fit the list, as (how
        many, and (closeness, index) closest first). Closeness to a show marked Not for
        me is taken off, as the engine takes it off its ranking."""
        if (show_id, k) not in self._near:
            if self.taste.wide:
                # A long list's shows are matched from their closest shows alone.
                if k not in self._fitting:
                    self._fitting[k] = set(self.usable[:FITTING]) | set(self.by_interest[k][:FITTING] if k is not None else ())
                pool = self._fitting[k]
                index, near, _evidence = self.ranking.row(self.e.by_id[show_id])
                close = [(v, i) for i, v in zip(index, near) if v >= SIMILAR and i in pool]
            else:
                affinity = self.taste.affinities.get(show_id) or self.e.blend(self.e.by_id[show_id], self.taste.settings)
                pool = list(dict.fromkeys(self.usable[:FITTING] + (self.by_interest[k][:FITTING] if k is not None else [])))
                close = [(v, i) for v, i in zip(itemgetter(*pool)(affinity) if len(pool) > 1 else
                                                [affinity[i] for i in pool], pool) if v >= SIMILAR]
            self._near[show_id, k] = (len(close), self.penalised(close))
        return self._near[show_id, k]

    def penalised(self, close):
        if self.negatives and self.taste.wide:
            penalty = self.ranking.penalty
            close = [(v - penalty(i), i) for v, i in close]
        elif self.negatives:
            share = self.taste.settings['dislike'] / len(self.negatives)
            arrays = [self.taste.affinities[p['id']] for p in self.negatives]
            close = [(v - share * sum(a[i] for a in arrays), i) for v, i in close]
        return sorted(close, reverse=True)

    def closeness_row(self, close, k=None):
        """Cards weighed 0.5 on closeness, 0.35 on taste and 0.15 on popularity, closeness
        and taste as places among every similar show, so a well-known show a little
        less close still counts: (the best SEED_POOL in order, their scores)."""
        near, taste = ranks({i: v for v, i in close}), ranks({i: self.taste_of(i, k) for _v, i in close})
        score = {i: 0.5 * near[i] + 0.35 * taste[i] + 0.15 * self.pop(i) for _v, i in close}
        items = sorted(score, key=lambda i: (-score[i], self.e.shows[i]['id']))[:SEED_POOL]
        return items, {i: score[i] for i in items}

    def seed_order(self, close, k=None):
        """A seed's row as the engine ranks more like one show: closeness to the seed, less
        the pull of anything disliked, times how well each show fits the taste of the
        interest the seed belongs to (engine.Ranking with one scoring show). On the bench
        this kept the strongest matches on a row's first cards, where a blend of places
        pushed them past it."""
        tastes = self.ranking.interest_tastes
        taste = tastes[k] if k is not None and k < len(tastes) else None
        score = {i: v * (taste.factor(i) if taste else 1.0) for v, i in close if v > 0}
        items = sorted(score, key=lambda i: (-score[i], self.e.shows[i]['id']))[:SEED_POOL]
        return items, {i: score[i] for i in items}

    # ------------------------------------------------------------ candidate rows

    def members(self, k):
        """An interest's liked shows, loves first and then newest first."""
        return sorted(self.interests[k], key=lambda p: (-p['weight'], -self.order[p['id']]))

    def telling(self, shows):
        """Liked shows loves first and then newest first, and for a long list only the first
        WIDE_SEEDS of them: the ones rows of their own are cut for."""
        ordered = sorted(shows, key=lambda p: (-p['weight'], -self.order[p['id']]))
        return ordered[:WIDE_SEEDS] if self.taste.wide else ordered

    def seeds(self, k):
        """The interest's seeds for the day: loves before likes, each with enough similar
        shows, the best three taking turns to lead."""
        found = []
        for p in self.members(k):
            if p['weight'] < .7:
                continue
            if self.near(p['id'], k)[0] >= NEIGHBOURS:
                found.append(p)
            if len(found) == ROTATE:
                break
        if len(found) > 1:
            turn = self.day % len(found)
            found = found[turn:] + found[:turn]
        return found

    def seed_row(self, p, k):
        _count, close = self.near(p['id'], k)
        if not close:
            return None
        items, score = self.seed_order(close, k)
        loved = p['weight'] == 1
        verb = 'loved' if loved else 'liked'
        return Shelf(f'seed-{p["id"]}', f'Because you {verb} {self.names[p["id"]]}', 'seed', items, score,
                     interest=k, evidence=EVIDENCE['loved' if loved else 'liked'], seed=self.e.by_id[p['id']],
                     diverse=False)

    def recipes(self, k):
        """Micro-genres for interest k, strongest first, each as a list of parts."""
        lib = self.lib
        taste = self.ranking.interest_tastes[k]
        leans = [(f['family'], f['label']) for f in taste.summary(limit=8)['leans']]
        members = [self.e.by_id[p['id']] for p in self.interests[k]]
        if not leans:
            leans = lib.traits(members)
        form = lib.form(members)
        cores, used = [], set()
        for family, label in leans:
            core = lib.core(family, label, form)
            if core and core['words'] not in used:
                used.add(core['words'])
                cores.append(core)
        # A core that only restates the form, or a format, says the least, so it leads
        # only when nothing else does.
        cores.sort(key=lambda c: (phrase_of([c] + ([c['form']] if c.get('form') else [])) in GENERIC,
                                  c['family'] == 'format'))
        place = next((lib.place(family, label) for family, label in leans if family in ('country', 'language')
                      and lib.place(family, label)), None)
        era = next((lib.era(label) for family, label in leans if family == 'decade'), None)
        adjective = next((a for a in (lib.adjective(label) for _family, label in leans) if a), None)
        out = []

        def recipe(core, place, adjective, era):
            parts = [core]
            if core.get('form'):
                parts.append(core['form'])
            if place and not core.get('regional') and not (core.get('anime') and place['label'] == 'Japanese'):
                parts.append(place)
            if adjective and adjective['words'].lower() not in phrase_of(parts).lower():
                parts.append(adjective)
            if era:
                parts.append(era)
            while len(name_of(parts).split()) > 5 and any(p['role'] != 'core' for p in parts):
                parts.remove(next(p for role in ('era', 'adjective', 'place', 'form') for p in parts if p['role'] == role))
            if name_of(parts) not in [name_of(r) for r in out]:
                out.append(parts)
        for core in cores[:2]:
            recipe(core, place, adjective, era)
        # The interest's main subject split by the decades and countries two or more of
        # its shows come from: distinct rows even for a list with one taste.
        if cores:
            shows = self.e.shows
            decades = Counter(decade_of(shows[i]['year']) for i in members if shows[i]['year'])
            for label, n in decades.most_common(2):
                if n >= 2 and lib.era(label):
                    recipe(cores[0], None, None, lib.era(label))
            places = Counter(shows[i]['country'] for i in members if shows[i]['country'])
            for code, n in places.most_common(2):
                found = lib.place('country', COUNTRIES.get(code, code))
                if n >= 2 and found and code != self.usual_country:
                    recipe(cores[0], found, None, None)
        return out

    def matching(self, k, part):
        """Where in interest k's ranking the shows with a part are, as a set of places,
        worked out once per part and request."""
        key = (k, part['role'], part['words'])
        if key not in self._matching:
            test = self.lib.recipe_test([part])
            self._matching[key] = frozenset(n for n, i in enumerate(self.by_interest[k]) if test(i))
        return self._matching[key]

    def niche_row(self, k, parts):
        """A micro-genre row, dropping its most specific word until twelve shows qualify."""
        pool = self.by_interest[k]
        parts = list(parts)
        while True:
            places = frozenset.intersection(*(self.matching(k, part) for part in parts))
            if len(places) >= NICHE:
                break
            droppable = [p for p in parts if p['role'] != 'core']
            if not droppable:
                return None
            parts.remove(min(droppable, key=lambda p: len(self.matching(k, p))))
        items, score = self.default([pool[n] for n in sorted(places)[:FILTER_POOL]], k)
        name = name_of(parts)
        core = parts[0]
        return Shelf(f'niche-{slug(name, 50)}', name, 'niche', items, score, interest=k, evidence=EVIDENCE['niche'],
                     subtitle=fans_of(self.interest_names(k)), proto=self.lib.proto(core))

    def interest_names(self, k):
        return [self.names[p['id']] for p in self.members(k)]

    def acclaimed_row(self, k, parts):
        core = parts[0]
        subject = [core] + ([core['form']] if core.get('form') else [])
        words = phrase_of(subject)
        pool = self.by_interest[k]
        places = frozenset.intersection(*(self.matching(k, part) for part in subject))
        rating = lambda i: self.e.shows[i]['rating'] or 0
        found = [pool[n] for n in sorted(places) if rating(pool[n]) >= 8][:FILTER_POOL]
        items, score = self.default(found, k)
        return Shelf(f'acclaimed-{slug(words)}', f'Critically acclaimed {words}', 'acclaimed', items, score,
                     interest=k, evidence=EVIDENCE['acclaimed'], subtitle=fans_of(self.interest_names(k)))

    def people_rows(self):
        """More from the world of a liked show, from its creator, and starring someone in
        two or more liked shows. Returns {interest: [shelves]} and the pooled creators row."""
        lib, e = self.lib, self.e
        usable = set(self.usable)
        owner = {p['id']: k for k, interest in enumerate(self.interests) for p in interest}
        found = {k: [] for k in range(len(self.interests))}
        pooled, pooled_from = set(), {}
        liked = self.telling(self.positives)
        worlds = set()
        for p in liked:
            if p['weight'] < .7:
                continue
            j, k = e.by_id[p['id']], owner.get(p['id'])
            franchises, creators, _makers, _cast = lib.facet_sets(j)
            shared = lib.holders('franchise', franchises) & usable
            key = frozenset(shared)
            if len(shared) >= SHORTEST and key not in worlds and k is not None:
                worlds.add(key)
                items, score = self.default(shared, k)
                strength = lambda i, j=j: lib.overlap(i, j, 'franchise')
                found[k].append(Shelf(f'world-{p["id"]}', f'More from the world of {self.names[p["id"]]}', 'people',
                                      items, score, interest=k, evidence=EVIDENCE['loved' if p['weight'] == 1 else 'liked'],
                                      callouts=False, proto=strength))
            made = lib.holders('maker', creators) & usable
            if len(made) >= CREATOR_SHORTEST and k is not None:
                items, score = self.default(made, k)
                found[k].append(Shelf(f'creator-{p["id"]}', f'From the creator of {self.names[p["id"]]}', 'people',
                                      items, score, interest=k, shortest=CREATOR_SHORTEST, callouts=False,
                                      evidence=EVIDENCE['loved' if p['weight'] == 1 else 'liked'],
                                      proto=lambda i, c=creators: len(lib.facet_sets(i)[1] & c)))
            elif made:
                pooled |= made
                for i in made:
                    pooled_from.setdefault(i, self.names[p['id']])
        creators_row = None
        if len(pooled) >= SHORTEST:
            items, score = self.default(pooled)
            behind = list(dict.fromkeys(pooled_from[i] for i in items[:GLANCE]))
            creators_row = Shelf('creators', 'From creators you love', 'people', items, score, evidence=EVIDENCE['creators'],
                                 subtitle=fans_of(behind), callouts=False)
        # Someone in two or more liked shows.
        cast = Counter()
        holders = {}
        for p in self.positives:
            for c in lib.facet_sets(e.by_id[p['id']])[3]:
                cast[c] += 1
                holders.setdefault(c, []).append(p)
        stars = sorted((c for c, n in cast.items() if n >= 2), key=lambda c: (-cast[c], c))
        for c in stars[:4]:
            shared = lib.holders('cast', [c]) & usable
            if len(shared) < SHORTEST:
                continue
            ks = Counter(owner.get(p['id']) for p in holders[c])
            k = ks.most_common(1)[0][0]
            if k is None:
                continue
            items, score = self.default(shared, k)
            label = e.facets.labels[c]
            found[k].append(Shelf(f'cast-{slug(e.facets.keys[c])}', f'Starring {label}', 'people', items, score,
                                  interest=k, evidence=EVIDENCE['cast'], callouts=False,
                                  subtitle=fans_of([self.names[p['id']] for p in holders[c]])))
        return found, creators_row

    # ------------------------------------------------------------ tier 1: more from the list

    # How much a tier 1 row's evidence counts, on EVIDENCE's scale; seed rows keep tier 0's.
    # In the order of the held-out loves a row of each kind holds on the bench's personas.
    PERSONAL_EVIDENCE = {'fans': 0.85, 'fans-liked': 0.7, 'cast-shared': 0.85, 'cast': 0.7, 'subject': 0.8,
                         'setting': 0.7, 'decade': 0.75, 'channel': 0.7}
    CAST_PER_SHOW = 2       # Starring rows one liked show may give, so an ensemble does not flood the page
    # How well a row cut from a few shows (one actor's, one subject's) must open: the fit
    # of its first cards, which a row from the best fits of a genre reaches with ease.
    OPENING_FIT = 0.85
    REGULARS = 20           # a cast list this short names only a show's regulars
    REGULAR_SHARE = 0.5     # an actor with this share of their credits in such lists is a regular
    NOT_CHANNELS = ('Syndication',)     # TVmaze's networks that are not a channel anyone tunes to
    CLASSICS = 1980         # liked shows from before this year share one decade row
    SUBJECT_ROWS = 4        # subject rows at most
    SUBJECT_WORDS = 6       # words in a subject row's title at most
    # Subjects that read better named another way than their Wikidata label.
    SUBJECT_NAMES = {'New York City Police Department': 'the NYPD', 'Los Angeles Police Department': 'the LAPD',
                     'Federal Bureau of Investigation': 'the FBI', 'Central Intelligence Agency': 'the CIA',
                     'Chicago Police Department': 'the Chicago police', 'police': 'the police',
                     'LGBTQ': 'LGBTQ lives', 'supernatural': 'the supernatural', 'paranormal': 'the paranormal',
                     'mafia': 'the mafia', 'universe': 'the universe', 'unidentified flying object': 'UFOs'}
    EVENT = re.compile(r'\b(?:War|Wars|Holocaust|attacks|disaster|Revolution|Rebellion|Crisis|Troubles|Battle|'
                       r'Crusades?|pandemic)\b')
    ORGANISATION = re.compile(r'\b(?:Department|Bureau|Agency|Service|Police|Office|Army|Navy|Corps|Party)\b')
    PERIOD = re.compile(r'\d{3}0s|\d{1,2}(?:st|nd|rd|th) century(?: BC)?')
    # Nouns that name a whole, not one of many ("shows about revenge", not "revenges").
    UNCOUNTED = re.compile(r'(?:ing|ism|ics|ence|ance|tion|sion|ment|ship|logy|phy|ness|cy|ia|s)$')
    ABSTRACT = {'music', 'revenge', 'travel', 'crime', 'love', 'sport', 'food', 'money', 'nature', 'murder',
                'incest', 'homicide', 'football', 'baseball', 'basketball', 'hockey', 'dance', 'war', 'life', 'art',
                'magic', 'fashion', 'death', 'time', 'space', 'law', 'justice', 'sex', 'history', 'slavery', 'poetry',
                'faith', 'religion', 'health', 'grief', 'destiny', 'change', 'technology', 'society', 'surgery',
                'mythology', 'cannabis', 'liberty', 'philosophy', 'comedy', 'satire', 'evolution', 'ecology'}
    # Places that take "the": the United States, the Russian Empire, the Arctic.
    THE_FIRST = ('United', 'Republic', "People's", 'Soviet', 'Russian', 'Roman', 'Ottoman', 'Holy', 'Czech')
    THE_LAST = ('Empire', 'Union', 'Republic', 'Kingdom', 'Islands', 'Isles', 'Ocean', 'Sea', 'Mountains', 'Alps',
                'Valley', 'Desert', 'Netherlands', 'Philippines', 'Bahamas', 'Arctic', 'Antarctic', 'Caribbean',
                'Outback', 'Moon', 'Internet', 'Underground', 'States', 'Emirates', 'Midlands', 'Highlands')

    def personal_rows(self):
        """Tier 1: more rows from the list itself, for when the first page's run out: more
        like each liked show past the few the first page queues, what its fans also look up,
        more of the casts, and the channels, subjects and decades liked shows share. Each
        kind comes best first, and a key or a title only once."""
        e = self.e
        liked = self.telling(p for p in self.positives if p['weight'] >= .7)
        owner = {p['id']: k for k, interest in enumerate(self.interests) for p in interest}
        usable = set(self.usable)
        seeds = {p['id']: self.seed_row(p, owner[p['id']]) for p in liked
                 if p['id'] in owner and self.near(p['id'], owner[p['id']])[0] >= NEIGHBOURS}
        top = self.calibrated()
        mine = self.more_seeds(liked, seeds)
        rows, seeds = list(mine.values()), {**seeds, **mine}
        if e.co:
            rows += self.fans_rows(liked, owner, usable, seeds, top)
        if e.facets:
            rows += self.cast_rows(liked, owner, usable)
            rows += self.subject_rows(liked, owner, usable, top)
            rows += self.channel_rows(liked, owner, top)
        rows += self.decade_rows(liked, owner, top)
        out, keys, titles = [], set(), set()
        for row in rows:
            if row and len(row.items) >= row.shortest and row.key not in keys and row.title.casefold() not in titles:
                keys.add(row.key)
                titles.add(row.title.casefold())
                out.append(row)
        return out

    def more_seeds(self, liked, seeds):
        """Because you loved or liked each liked show with enough close matches, past the
        three seeds shelves() queues for each interest heavy enough for rows of its own, as
        {show id: row}. Favourites of one interest open their rows with much the same shows,
        and the page drops a row that repeats half of one above, so a seed row that would is
        cut apart from the seed rows before it (the first page's, then this tier's), and every
        liked show keeps a row of its own."""
        queued = {p['id'] for k in self.heavy_interests() for p in self.seeds(k)[:3]}
        before = [seeds[i].items for i in sorted(queued) if seeds.get(i)]
        out = {}
        for p in liked:
            row = seeds.get(p['id'])
            if not row or p['id'] in queued:
                continue
            if any(self.repeats(row.items, other) >= 0.5 for other in before):
                # No scores: the page would sort by them, undoing apart()'s order.
                row = Shelf(row.key, row.title, row.kind_of, self.apart(row.items, before), interest=row.interest,
                            evidence=row.evidence, seed=row.seed, diverse=row.diverse)
            before.append(row.items)
            out[p['id']] = row
        return out

    def heavy_interests(self):
        """The interests heavy enough for rows of their own on the first page, heaviest
        first, as shelves() takes them."""
        return sorted((k for k, s in enumerate(self.share) if s >= INTEREST_FLOOR / 2),
                      key=lambda k: -self.share[k])[:MOST_INTERESTS]

    def fans_rows(self, liked, owner, usable, seeds, top):
        """<Show> fans also look up: the shows that readers of a liked show's Wikipedia
        article also look up (engine.cointerest, which leaves out the show's own franchise),
        award ceremonies aside, weighed half on how strong the link is and half on taste.
        Closeness already counts these links, so a show's seed row mostly opens with the
        same shows; a fans row is made only where it would not repeat half of that row's
        first twelve cards, or Top picks', which the page would drop as a repeat. Cut apart
        from its seed row instead, it keeps the weakest links and seldom a show the list
        loves."""
        e = self.e
        out = []
        for p in liked:
            j, k = e.by_id[p['id']], owner.get(p['id'])
            links = {i: s for i, s in e.cointerest(j) if i in usable and e.shows[i]['type'] != 'Award Show'}
            if len(links) < SHORTEST:
                continue
            strength, taste = ranks(links), ranks({i: self.taste_of(i, k) for i in links})
            score = {i: 0.5 * strength[i] + 0.5 * taste[i] for i in links}
            items = sorted(score, key=lambda i: (-score[i], e.shows[i]['id']))
            above = [top] + ([seeds[p['id']].items] if seeds.get(p['id']) else [])
            if any(self.repeats(items, other) >= 0.5 for other in above):
                continue
            out.append(Shelf(f'fans-{p["id"]}', f'{self.names[p["id"]]} fans also look up', 'fans', items, score,
                             interest=k, seed=j,
                             evidence=self.PERSONAL_EVIDENCE['fans' if p['weight'] == 1 else 'fans-liked'],
                             subtitle='What readers of its Wikipedia page also look up'))
        return out

    @staticmethod
    def repeats(items, other):
        """The share of items' first twelve cards among other's first twelve, as arrange()
        measures a row against the rows above it."""
        head = set(items[:12])
        return len(head & set(other[:12])) / max(1, min(12, len(head)))

    @staticmethod
    def apart(items, others):
        """items less the cards any of the other rows opens with, and with fewer than half of
        any one's first twelve among their own first twelve. Cards past that go after the
        twelfth or, in a row too short to reach it, are left out."""
        opening = {i for other in others for i in other[:GLANCE]}
        tops = [set(other[:12]) for other in others]
        head, rest, count = [], [], [0] * len(tops)
        for i in items:
            if i in opening:
                continue
            hits = [n for n, top in enumerate(tops) if i in top]
            if len(head) < 12 and all(count[n] < 5 for n in hits):
                head.append(i)
                for n in hits:
                    count[n] += 1
            else:
                rest.append(i)
        if len(head) == 12:
            return head + rest
        # Short of twelve, a row is measured against its own length.
        while any(2 * c >= len(head) > 0 for c in count):
            n = next(n for n, c in enumerate(count) if 2 * c >= len(head))
            drop = next(i for i in reversed(head) if i in tops[n])
            head.remove(drop)
            count = [c - (drop in top) for c, top in zip(count, tops)]
        return head

    def past_top(self, items, score, top):
        """A filtered row's cards and scores, or, when half or more of its first twelve are
        Top picks' (a decade most of the list is from), the cards past what Top picks shows,
        in order: the page would drop the row as a repeat of Top picks."""
        if self.repeats(items, top) < 0.5:
            return items, score
        return self.apart(items, [top]), None

    def cast_rows(self, liked, owner, usable):
        """Starring rows past the four people_rows() makes: first anyone else in two or more
        liked shows, then the regulars of each loved show, newest first, whose other shows
        fit the list well. A regular is mostly credited in cast lists short enough to hold
        only regulars; a guest actor is mostly credited in the long lists of long-running
        shows, and a row would not be starring them. One liked show gives CAST_PER_SHOW rows
        at most, so an ensemble does not flood the page."""
        lib, e = self.lib, self.e
        count, backers = Counter(), {}
        for p in self.positives:
            for c in sorted(lib.facet_sets(e.by_id[p['id']])[3]):
                count[c] += 1
                backers.setdefault(c, []).append(p)
        shared = sorted((c for c, n in count.items() if n >= 2), key=lambda c: (-count[c], c))
        if self.taste.wide:
            # A long list shares hundreds of actors; the most shared are enough for rows.
            shared = shared[:4 + WIDE_SEEDS]
        wanted = [(c, 'cast-shared') for c in shared[4:] if self.regular(c) >= self.REGULAR_SHARE]
        for p in liked:
            if p['weight'] < 1:
                continue
            mine = []
            for c in lib.facet_sets(e.by_id[p['id']])[3]:
                if count[c] == 1:
                    regular = self.regular(c)
                    if regular >= self.REGULAR_SHARE:
                        mine.append((-regular, c))
            wanted += [(c, 'cast') for _r, c in sorted(mine)]
        given, out = Counter(), []
        for c, kind in wanted:
            behind = backers[c]
            if any(given[p['id']] >= self.CAST_PER_SHOW for p in behind):
                continue
            found = lib.holders('cast', [c]) & usable
            if len(found) < SHORTEST:
                continue
            k = self.lead_interest(owner, behind)
            items, score = self.default(found, k)
            row = Shelf(f'cast-{slug(e.facets.keys[c])}', f'Starring {e.facets.labels[c]}', 'cast', items, score,
                        interest=k, evidence=self.PERSONAL_EVIDENCE[kind], callouts=False,
                        subtitle=fans_of([self.names[p['id']] for p in behind]))
            if kind == 'cast' and not self.opens_well(row):
                continue
            given.update(p['id'] for p in behind)
            out.append(row)
        return out

    def regular(self, c):
        """The share of actor c's credits in cast lists of REGULARS names or fewer."""
        f = self.e.facets
        start, end = f.family_ranges[f.families.index('cast')]
        shows = [f.post_rows[n] for n in range(f.col_ptr[c], f.col_ptr[c + 1])]
        short = 0
        for i in shows:
            lo, hi = f.row_ptr[i], f.row_ptr[i + 1]
            short += bisect_left(f.columns, end, lo, hi) - bisect_left(f.columns, start, lo, hi) <= self.REGULARS
        return short / len(shows) if shows else 0.0

    def opens_well(self, row):
        """Whether a row's first cards fit the list at least OPENING_FIT, on its interest's scale."""
        return self.relevance(row, set(), Counter()) >= self.OPENING_FIT * row.evidence

    def shared_by(self, liked, family):
        """The facet columns of a family that liked shows carry, with the shows behind each."""
        f = self.e.facets
        start, end = f.family_ranges[f.families.index(family)]
        backers = {}
        for p in liked:
            for c, _v in f.row(self.e.by_id[p['id']]):
                if start <= c < end:
                    backers.setdefault(c, []).append(p)
        return backers

    @staticmethod
    def key_slug(label, key):
        """A row key from a name, or from its facet key when the name has no letters a key
        can hold, as with Россия 1."""
        text = slug(label)
        return text if re.search('[a-z]', text) and text != 'row' else slug(key)

    def lead_interest(self, owner, behind):
        """The interest most of a row's liked shows are in."""
        return Counter(owner.get(p['id']) for p in behind).most_common(1)[0][0]

    def subject_rows(self, liked, owner, usable, top):
        """Shows about what two or more liked shows are about: Wikidata's main subjects, with
        the places and periods shows are set in, for those with enough shows that fit and
        whose best fit well. The most shared come first, then topics before times and
        places, the narrowest first. A subject only one liked show has seldom led to another
        show the list loves."""
        f = self.e.facets
        backers = self.shared_by(liked, 'subject')
        found = []
        for c, behind in backers.items():
            if len(behind) < 2:
                continue
            title, rank = self.subject_title(f.labels[c])
            if not title or len(title.split()) > self.SUBJECT_WORDS:
                continue
            shows = self.lib.holders('subject', [c]) & usable
            if len(shows) >= SHORTEST:
                found.append(((-len(behind), rank, len(shows), c), c, title, shows))
        out = []
        for _order, c, title, shows in sorted(found, key=itemgetter(0)):
            k = self.lead_interest(owner, backers[c])
            items, score = self.past_top(*self.default(shows, k), top)
            row = Shelf(f'subject-{self.key_slug(f.labels[c], f.keys[c])}', title, 'subject', items, score,
                        interest=k, subtitle=fans_of([self.names[p['id']] for p in backers[c]]),
                        evidence=self.PERSONAL_EVIDENCE['setting' if title.startswith('Shows set') else 'subject'])
            if self.opens_well(row):
                out.append(row)
                if len(out) == self.SUBJECT_ROWS:
                    break
        return out

    def subject_title(self, label):
        """A subject row's title and how specific the subject is, 0 for a topic, 1 for a
        time, an event or an agency and 2 for a place; no title for what cannot be said.
        Wikidata keeps common nouns in lower case and proper nouns as they are."""
        if label in self.SUBJECT_NAMES:
            return f'Shows about {self.SUBJECT_NAMES[label]}', 0 if label[:1].islower() else 1
        if label == 'future' or self.PERIOD.fullmatch(label):
            return f'Shows set in the {label}', 1
        if re.fullmatch(r'\d{3,4}', label):
            return f'Shows set in {label}', 1
        if label[:1].islower():
            if label in NOUNS:
                return upper_first(NOUNS[label]), 0
            return f'Shows about {self.plural(label)}', 0
        if not label[:1].isalpha():
            return None, 3
        if self.EVENT.search(label):
            if label.startswith('The '):
                return f'Shows about the {label[4:]}', 1
            return f'Shows about {"" if label.startswith("World War") else "the "}{label}', 1
        if self.ORGANISATION.search(label):
            return f'Shows about the {label}', 1
        words = label.split()
        the = 'the ' if words[0] in self.THE_FIRST or words[-1] in self.THE_LAST else ''
        return f'Shows set in {the}{label}', 2

    def plural(self, label):
        """'serial killers' from 'serial killer', leaving 'organized crime' as it is."""
        words = label.split()
        last = words[-1]
        if last in self.ABSTRACT or self.UNCOUNTED.search(last):
            return label
        if last.endswith(('x', 'z', 'ch', 'sh')):
            last += 'es'
        elif last.endswith('y') and last[-2:-1] not in 'aeiou':
            last = last[:-1] + 'ies'
        elif last.endswith('man'):
            last = last[:-3] + 'men'
        else:
            last += 's'
        return ' '.join(words[:-1] + [last])

    def channel_rows(self, liked, owner, top):
        """A row for each channel behind two or more liked shows (TVmaze's network or web
        channel), for the interest most of them are in."""
        f = self.e.facets
        backers = self.shared_by(liked, 'network')
        out = []
        for c in sorted((c for c in backers if len(backers[c]) >= 2), key=lambda c: (-len(backers[c]), c)):
            label = f.labels[c]
            if label in self.NOT_CHANNELS:
                continue
            shows = self.lib.holders('network', [c])
            k = self.lead_interest(owner, backers[c])
            items, score = self.past_top(*self.default(self.take(lambda i: i in shows), k), top)
            name = f'Channel {label}' if label.isdigit() else label
            out.append(Shelf(f'channel-{self.key_slug(label, f.keys[c])}', f'{name} shows for you', 'channel', items,
                             score, interest=k, evidence=self.PERSONAL_EVIDENCE['channel'],
                             subtitle=fans_of([self.names[p['id']] for p in backers[c]])))
        return out

    def decade_rows(self, liked, owner, top):
        """A row for each decade two or more liked shows premiered in, those before
        CLASSICS together as classics. The first page already cuts an interest's main
        subject by its decades ("Crime dramas from the 2010s"), so a decade row that would
        repeat one of those goes past it, to the rest of the decade for the list."""
        shows, by_id = self.e.shows, self.e.by_id
        backers = {}
        for p in liked:
            year = shows[by_id[p['id']]]['year']
            if year:
                backers.setdefault(self.era_of(year), []).append(p)
        cuts = self.decade_cuts()
        out = []
        for era in sorted((d for d in backers if len(backers[d]) >= 2), key=lambda d: (-len(backers[d]), d)):
            first, last = (1, self.CLASSICS) if not era else (era, era + 10)
            k = self.lead_interest(owner, backers[era])
            found = self.take(lambda i: first <= (shows[i]['year'] or 0) < last)
            items, score = self.past_top(*self.default(found, k), top)
            if any(self.repeats(items, other) >= 0.5 for other in cuts.get(era, ())):
                items, score = self.apart(items, cuts[era]), None
            if era:
                title = f'{era % 100:02d}s shows for you' if era < 2000 else f'{era}s shows for you'
                key = f'decade-{era}'
            else:
                title, key = f'Classics before {self.CLASSICS}', f'decade-before-{self.CLASSICS}'
            out.append(Shelf(key, title, 'decade', items, score, interest=k, evidence=self.PERSONAL_EVIDENCE['decade'],
                             subtitle=fans_of([self.names[p['id']] for p in backers[era]])))
        return out

    def era_of(self, year):
        """A premiere year's decade row: its decade, or 0 for the classics before CLASSICS."""
        return 0 if year < self.CLASSICS else year // 10 * 10

    def decade_cuts(self):
        """The cards of the first page's micro-genres that are cut by a decade (recipes()),
        as {decade row: [cards of each]}."""
        cuts = {}
        for k in self.heavy_interests():
            for parts in self.recipes(k):
                era = next((part for part in parts if part['role'] == 'era'), None)
                row = self.niche_row(k, parts) if era else None
                # A micro-genre too small for its decade leaves the decade out of its name.
                if row and row.title.endswith(era['words']):
                    year = int(re.search(r'\d{4}', era['words']).group())
                    cuts.setdefault(self.era_of(year), []).append(row.items)
        return cuts

    def shelves(self):
        """Every candidate row: those that belong to an interest, queued in the order an
        interest adds them, and the rest."""
        e, lib = self.e, self.lib
        rows, queues = [], [[] for _ in self.interests]
        top = self.calibrated()
        if top:
            rows.append(Shelf('top', 'Top picks for you', 'top', top, evidence=EVIDENCE['top'], diverse=False))
        people, creators = self.people_rows() if e.facets else ({}, None)
        # Rows for the interests with enough weight to hold one, heaviest first.
        heavy = sorted((k for k, s in enumerate(self.share) if s >= INTEREST_FLOOR / 2),
                       key=lambda k: -self.share[k])[:MOST_INTERESTS]
        names = set()
        for k in heavy:
            seeds = [row for row in (self.seed_row(p, k) for p in self.seeds(k)[:3]) if row]
            recipes = self.recipes(k)
            niches = list({row.key: row for row in (self.niche_row(k, parts) for parts in recipes)
                           if row and row.key not in names}.values())
            names.update(row.key for row in niches)
            queue = seeds[:1] + niches[:1]
            ranked_people = sorted(people.get(k, []), key=lambda s: (-self.relevance(s, set(), Counter()), s.key))
            queue += ranked_people[:1] + seeds[1:2]
            if recipes:
                queue.append(self.acclaimed_row(k, recipes[0]))
            queue += niches[1:] + seeds[2:3] + ranked_people[1:]
            queues[k] = [s for s in queue if len(s.items) >= s.shortest]
        if creators:
            rows.append(creators)
        year = lib.year
        found, score = self.default(self.take(lambda i: e.shows[i]['year'] >= year - 1))
        rows.append(Shelf('new', 'New for you', 'new', found, score, evidence=EVIDENCE['new']))
        genre_weight, theme_weight = Counter(), Counter()
        for p in self.positives:
            themes, genres = e.signals(e.by_id[p['id']])
            for g in genres:
                if g in GENRE_ROWS:
                    genre_weight[g] += p['weight']
            for t in themes:
                theme_weight[t] += p['weight']
        for g in sorted(genre_weight, key=lambda g: (-genre_weight[g], g))[:5]:
            found, score = self.default(self.take(lambda i, g=g: g in e.shows[i]['genres']))
            rows.append(Shelf(f'genre-{g}'.lower(), GENRE_ROWS[g], 'genre', found, score, evidence=EVIDENCE['genre']))
        for t in sorted(theme_weight, key=lambda t: (-theme_weight[t], t))[:3]:
            bit = 1 << e.themes.index(t)
            found, score = self.default(self.take(lambda i, bit=bit: e.shows[i]['theme_bits'] & bit))
            rows.append(Shelf(f'theme-{slug(THEME_ROWS[t])}', THEME_ROWS[t], 'genre', found, score,
                              evidence=EVIDENCE['theme']))
        rows.append(self.gems())
        found, score = self.default(self.take(lambda i: i in lib.limited))
        rows.append(Shelf('limited', 'Limited series for you', 'limited', found, score, evidence=EVIDENCE['limited']))
        for place in self.places():
            if place.interest in heavy:
                queues[place.interest].append(place)
            else:
                place.interest = None
                rows.append(place)
        like = self.like_list()
        if like:
            rows.append(like)
        rows.append(Shelf('top10', 'Top 10 shows today', 'top10', lib.top10, kind='top10', personal=False,
                          evidence=EVIDENCE['plain'], callouts=False, diverse=False))
        rows.append(self.popular())
        # A first visit's rows: half the page for a short list, and for any list a
        # fallback when its own rows run out.
        rows += self.plain_rows()
        different = self.different()
        # One row to a key: a first visit's genre row gives way to the list's own.
        keys = {s.key for queue in queues for s in queue}
        kept = []
        for r in rows:
            if r and len(r.items) >= r.shortest and r.key not in keys:
                keys.add(r.key)
                kept.append(r)
        return kept, queues, different

    def calibrated(self):
        """Top picks: the best hundred re-ranked so their mix of interests matches the
        list's (Steck, 2018), greedily, trading score for closeness to that mix."""
        pool = self.usable[:TOP_POOL]
        group = self.ranking.group
        target = self.share
        if len(target) < 2 or not pool or not CALIBRATION:
            return pool[:3 * ROW]
        alpha = 0.01
        counts = [0] * len(target)
        chosen, left = [], list(pool)

        def divergence(extra):
            n = len(chosen) + 1
            total = 0.0
            for k, p in enumerate(target):
                if p <= 0:
                    continue
                q = (counts[k] + (1 if k == extra else 0)) / n
                total += p * math.log(p / ((1 - alpha) * q + alpha * p))
            return total
        while left and len(chosen) < 3 * ROW:
            best, value = None, None
            for i in left:
                k = group.get(i)
                v = (1 - CALIBRATION) * self.taste.unit(i) - CALIBRATION * divergence(k)
                if value is None or v > value:
                    best, value = i, v
            chosen.append(best)
            left.remove(best)
            k = group.get(best)
            if k is not None and k < len(counts):
                counts[k] += 1
        return chosen

    def gems(self):
        """Hidden gems: little known, well rated and among the best fits for the list."""
        most_pop, rating_q, share = HIDDEN
        cut = self.usable[:max(1, int(len(self.usable) * share))]
        floor = self.stats['rating_q75']
        found = [i for i in cut if self.pop(i) <= most_pop and (self.e.shows[i]['rating'] or 0) >= floor][:FILTER_POOL]
        taste = ranks({i: self.taste_of(i) for i in found})
        score = {i: 0.6 * taste[i] + 0.4 * self.quality(i) for i in found}
        items = sorted(score, key=lambda i: (-score[i], self.e.shows[i]['id']))
        return Shelf('gems', 'Hidden gems for you', 'gems', items, score, evidence=EVIDENCE['gems'])

    def places(self):
        """A row for a language or country a good share of the liked shows come from,
        when it is not the list's usual one. It belongs to the interest most of those
        shows are in."""
        e, out = self.e, []
        liked = [e.by_id[p['id']] for p in self.positives]
        owner = {e.by_id[p['id']]: k for k, interest in enumerate(self.interests) for p in interest}
        for family in ('language', 'country'):
            tally = Counter(e.shows[i][family] for i in liked if e.shows[i][family])
            if not tally:
                continue
            usual = tally.most_common(1)[0][0]
            for value, n in tally.most_common():
                if value == usual or n / len(liked) < PLACE_SHARE:
                    continue
                if family == 'country' and any(r.key.startswith('lang-') for r in out):
                    continue
                label = COUNTRIES.get(value, value) if family == 'country' else value
                k = Counter(owner.get(i) for i in liked if e.shows[i][family] == value).most_common(1)[0][0]
                found, score = self.default(self.take(lambda i, v=value: e.shows[i][family] == v), k)
                key = f'lang-{slug(value)}' if family == 'language' else f'country-{slug(value)}'
                out.append(Shelf(key, f'{label} shows for you', 'place', found, score, interest=k,
                                 evidence=EVIDENCE['place']))
                break
        return out

    def like_list(self):
        """More like the shows waiting on My List, by closeness to the newest five."""
        saved = [i for i in reversed(self.saved) if self.e.shows[i]['id'] not in self.rated][:5]
        pool = self.usable[:FITTING]
        if not saved or len(pool) < 2:
            return None
        keep = set(saved)
        if self.taste.wide:
            # A long list's page takes the saved shows' closest shows, as it takes its seeds'.
            allowed, sums = set(pool), {}
            for i in saved:
                index, near, _evidence = self.ranking.row(i)
                for j, v in zip(index, near):
                    if j in allowed and j not in keep:
                        sums[j] = sums.get(j, 0.0) + v
            close = self.penalised(heapq.nlargest(LIKE_POOL, ((v / len(saved), j) for j, v in sums.items())))
        else:
            arrays = [self.e.blend(i, self.taste.settings) for i in saved]
            gather = itemgetter(*pool)
            sums = [0.0] * len(pool)
            for affinity in arrays:
                sums = [a + b for a, b in zip(sums, gather(affinity))]
            close = self.penalised(heapq.nlargest(LIKE_POOL, ((v / len(arrays), i) for v, i in zip(sums, pool)
                                                            if i not in keep)))
        if not close:
            return None
        items, score = self.closeness_row(close)
        names = [self.e.shows[i]['name'] for i in saved[:2]]
        return Shelf('like-list', 'More like your list', 'like-list', items, score, evidence=EVIDENCE['like-list'],
                     subtitle=f'Like {" and ".join(names)} on your list')

    def popular(self):
        """Popular right now, blended with taste to choose which, ordered by popularity."""
        lib, e = self.lib, self.e
        usable = self.taste.scores
        found = [i for i in lib.popular_pool if usable[i] > 0 and i not in self.excluded]
        blend = {i: 0.5 * self.taste_of(i) + 0.5 * self.pop(i) for i in found}
        found = sorted(blend, key=lambda i: (-blend[i], e.shows[i]['id']))[:3 * ROW]
        items = sorted(found, key=lambda i: (-e.popularity[i], -(e.shows[i]['rating'] or 0), e.shows[i]['id']))
        return Shelf('popular', 'Popular right now', 'popular', items, personal=False, evidence=EVIDENCE['plain'],
                     callouts=False, diverse=False)

    def plain_rows(self):
        """For a list still short of ten liked shows, the rows a first visit sees."""
        out, scores = [], self.taste.scores
        fits = lambda items: [i for i in items if scores[i] > 0 and i not in self.excluded]
        if self.lang and self.lang in self.lib.by_language:
            out.append(Shelf(f'popular-{slug(self.lang)}', f'Popular in {self.lang}', 'language',
                             fits(self.lib.by_language[self.lang]), personal=False, evidence=EVIDENCE['language'],
                             callouts=False, diverse=False))
        for key, title, items in self.lib.plain_rows():
            out.append(Shelf(key, title, 'plain', fits(items), personal=False, evidence=EVIDENCE['plain'],
                             callouts=False, diverse=False))
        return out

    def different(self):
        """Something different: a genre or format the list has nothing of, from the ones
        it would take to best, with the day choosing among the closest few."""
        e, lib = self.e, self.lib
        liked = [e.by_id[p['id']] for p in self.positives]
        disliked = [e.by_id[p['id']] for p in self.negatives]
        options = []
        for key, label in [*GENRE_ROWS.items(), *FORMAT_ROWS.items()]:
            if key in ('Drama', 'Comedy'):
                continue
            if any(lib._fits(key, i) for i in liked + disliked):
                continue
            found = [i for i in lib.shelf_by_key.get(key, ()) if self.taste.scores[i] > 0 and i not in self.excluded]
            if len(found) < SHORTEST:
                continue
            fit = statistics.fmean(self.taste_of(i) for i in found[:10])
            options.append((fit, key, label, found))
        if not options:
            return None
        options.sort(key=lambda o: (-o[0], o[1]))
        options = options[:4]
        _fit, key, label, found = max(options, key=lambda o: (self.fresh.z('different', o[1]) - 0.5 * options.index(o), o[1]))
        taste = ranks({i: self.taste_of(i) for i in found})
        score = {i: 0.5 * self.quality(i) + 0.3 * taste[i] + 0.2 * self.pop(i) for i in found}
        items = sorted(score, key=lambda i: (-score[i], e.shows[i]['id']))
        return Shelf('different', 'Something different', 'different', items, score, personal=False,
                     evidence=EVIDENCE['different'], callouts=False,
                     subtitle=f'Well-loved {label if label == "Westerns" else lower_first(label)}, a change from your usual')

    # ------------------------------------------------------------ rows past the first page

    # Rows past the first page say less about a person than the first page's rows of
    # the same sort (its gems, new and limited rows weigh 0.8, its genre rows 0.75 and
    # Something different 0.6), so each weighs less.
    INTEREST_EVIDENCE = {'gems': 0.7, 'new': 0.7, 'short': 0.65, 'popular': 0.6}
    EXPLORE_EVIDENCE = {'language': 0.65, 'format': 0.55, 'genre': 0.5}
    BROWSE_EVIDENCE = {'genre': 0.6, 'theme': 0.55, 'format': 0.55}
    FIT_FLOOR = 0.6         # the mean fit a chosen row's first cards need (fit())
    OWN_SHARE = 0.6         # an interest with this share of its shows in one language or format keeps to it
    HALF_HOUR = 35          # minutes: an episode this long or shorter is a half-hour one
    EXPLORE_LANGUAGES = 4   # language rows at most
    EXPLORE_FEW = 0.2       # a format this share of the liked shows or less is one to explore
    # A genre as it reads in "Westerns to try", where GENRE_ROWS' title does not.
    EXPLORE_NOUNS = {'Children': "children's shows", 'Crime': 'crime shows', 'DIY': 'DIY shows',
                     'Family': 'family shows', 'Horror': 'horror shows', 'Romance': 'romances'}
    # A format as it reads in "Documentaries to try" and "Documentaries for you", apart from the
    # first-visit rows' titles (FORMAT_ROWS).
    FORMAT_NAMES = {'animation': 'Animated series', 'documentary': 'Documentaries', 'unscripted': 'Reality TV'}

    def head_fits(self, items, k=None):
        """Whether a row's first cards fit the list, or interest k, well enough for the
        row to be chosen for it."""
        head = items[:GLANCE]
        return bool(head) and statistics.fmean(self.fit(i, k) for i in head) >= self.FIT_FLOOR

    def subject_of(self, k, taken=()):
        """What interest k is about, for its own rows: the core of its strongest
        micro-genre, as Critically acclaimed rows name it ("crime dramas"), or of the next
        when too few of its shows are that or a heavier interest has the name. An interest
        mostly of one format keeps to it, and one mostly in a language other than English
        keeps to that and says so ("Korean thrillers"): TVmaze's popularity leans English
        and toward anime, and without them a K-drama interest's popular romantic dramas
        were Poldark and Doc Martin, a Japanese drama interest's were anime. Returns (the
        name, the interest's shows it fits, best first), or (None, [])."""
        e = self.e
        pool = self.by_interest[k]
        members = [e.shows[e.by_id[p['id']]] for p in self.interests[k]]
        own, count = Counter(s['language'] for s in members).most_common(1)[0]
        if own in (None, 'English') or count < self.OWN_SHARE * len(members):
            own = None
        kinds = Counter(next((g for g, types in FORMAT_GROUPS.items() if s['type'] in types), None) for s in members)
        form, count = kinds.most_common(1)[0]
        types = FORMAT_GROUPS[form] if form and count >= self.OWN_SHARE * len(members) else None
        for parts in self.recipes(k):
            core = parts[0]
            subject = [core] + ([core['form']] if core.get('form') else [])
            words = phrase_of(subject)
            if own and not core.get('regional') and not (own == 'Japanese' and words.endswith('anime')):
                words = f'{own} {words}'
            if words in taken:
                continue
            places = frozenset.intersection(*(self.matching(k, part) for part in subject))
            shows = [pool[m] for m in sorted(places) if (own is None or e.shows[pool[m]]['language'] == own)
                     and (types is None or e.shows[pool[m]]['type'] in types)]
            if len(shows) >= 2 * SHORTEST:
                return words, shows
        return None, []

    def interest_rows(self):
        """Tier 2: each interest's own hidden gems, popular, new and half-hour shows,
        named for what it is about ("Hidden gem crime dramas") and cut from its shows that
        are that. Finished series to binge were tried and left out: three in four shows
        have ended, so the row was the interest's micro-genre again."""
        e, lib = self.e, self.lib
        heavy = sorted((k for k, s in enumerate(self.share) if s >= INTEREST_FLOOR / 2),
                       key=lambda k: -self.share[k])[:MOST_INTERESTS]
        popular = frozenset(lib.popular_pool)
        floor = self.stats['rating_q75']
        short = lambda i: 0 < (e.shows[i]['runtime'] or 0) <= self.HALF_HOUR
        # An interest that is most of the list would only repeat the first page's own
        # gems, New for you and Popular right now; theirs are worked out when first needed.
        across = {}

        def repeats(kind, items):
            if kind not in across:
                head = (self.gems().items if kind == 'gems' else self.popular().items if kind == 'popular' else
                        self.default(self.take(lambda i: e.shows[i]['year'] >= lib.year - 1))[0])
                across[kind] = frozenset(head[:12])
            top = frozenset(items[:12])
            return len(top & across[kind]) >= 0.5 * min(12, len(top))
        out, taken = [], set()
        for k in heavy:
            words, shows = self.subject_of(k, taken)
            if not words:
                continue
            taken.add(words)
            rows = []
            # Hidden gems as gems() finds them, among the interest's own best fits.
            places, size = self.place_in[k]
            cut = max(1, int(size * HIDDEN[2]))
            found = [i for i in shows if places[i] < cut and self.pop(i) <= HIDDEN[0]
                     and (e.shows[i]['rating'] or 0) >= floor][:FILTER_POOL]
            taste = ranks({i: self.taste_of(i, k) for i in found})
            score = {i: 0.6 * taste[i] + 0.4 * self.quality(i) for i in found}
            rows.append(('gems', f'Hidden gem {words}', sorted(score, key=lambda i: (-score[i], e.shows[i]['id'])), score))
            # Popular as popular() orders it, taste choosing which and popularity the order,
            # from the interest's best fits in the popular pool.
            found = [i for i in shows if i in popular][:FILTER_POOL]
            blend = {i: 0.5 * self.taste_of(i, k) + 0.5 * self.pop(i) for i in found}
            found = sorted(blend, key=lambda i: (-blend[i], e.shows[i]['id']))[:3 * ROW]
            found.sort(key=lambda i: (-e.popularity[i], -(e.shows[i]['rating'] or 0), e.shows[i]['id']))
            rows.append(('popular', f'Popular {words}', found, None))
            found = [i for i in shows if e.shows[i]['year'] >= lib.year - 1][:FILTER_POOL]
            rows.append(('new', f'New {words}', *self.default(found, k)))
            members = [e.by_id[p['id']] for p in self.interests[k]]
            if 2 * sum(map(short, members)) < len(members):
                found = [i for i in shows if short(i)][:FILTER_POOL]
                rows.append(('short', f'Half-hour {words}', *self.default(found, k)))
            subtitle = fans_of(self.interest_names(k))
            for kind, title, items, score in rows:
                if len(items) < SHORTEST or not self.head_fits(items, k) or (kind != 'short' and repeats(kind, items)):
                    continue
                out.append(Shelf(f'{kind}-{slug(words)}', title, f'interest-{kind}', items, score, interest=k,
                                 evidence=self.INTEREST_EVIDENCE[kind], subtitle=subtitle,
                                 callouts=kind != 'popular', diverse=kind != 'popular'))
        return out

    def explore_rows(self):
        """Tier 3: a handful of languages the list has nothing in, genres it has not
        touched and formats it has few of, each only where its best shows fit the list,
        the best fitting first. Something different is one of these a day and says so
        already, and a genre may be a format again (anime and animation, nature and
        documentaries), so a row that repeats one before it is left out."""
        before = [row.top12 for row in [self.different()] if row]
        out = []
        for row in self.explore_languages() + self.explore_genres() + self.explore_formats():
            if all(len(row.top12 & other) < 0.5 * min(12, len(row.top12)) for other in before):
                out.append(row)
                before.append(row.top12)
        return out

    def explore_languages(self):
        """Languages nothing liked is in, from the list's best fits, ordered as places()
        orders the languages it likes."""
        e = self.e
        liked = {e.shows[e.by_id[p['id']]]['language'] for p in self.positives}
        # A row for a country the list likes may already carry a language's name.
        near = {row.title for row in self.places()}
        found = {}
        for i in self.depth:
            language = e.shows[i]['language']
            if language and language != 'English' and language not in liked:
                found.setdefault(language, []).append(i)
        options = []
        for language, items in found.items():
            title = f'{language} shows for you'
            if len(items) < SHORTEST or title in near:
                continue
            items, score = self.default(items[:FILTER_POOL])
            if self.head_fits(items):
                options.append((statistics.fmean(self.fit(i) for i in items[:GLANCE]), language, title, items, score))
        options.sort(key=lambda o: (-o[0], o[1]))
        return [Shelf(f'lang-{slug(language)}', title, 'explore-language', items, score, personal=False,
                      evidence=self.EXPLORE_EVIDENCE['language'])
                for _fit, language, title, items, score in options[:self.EXPLORE_LANGUAGES]]

    def explore_formats(self):
        """Documentaries, animation and reality for a list with few of them."""
        e, lib = self.e, self.lib
        liked = [e.by_id[p['id']] for p in self.positives]
        rows = (self.explore_row(key, f'{label} to try', 'format') for key, label in self.FORMAT_NAMES.items()
                if sum(lib._fits(key, i) for i in liked) <= self.EXPLORE_FEW * len(liked))
        return sorted((row for row in rows if row), key=lambda row: -statistics.fmean(self.fit(i) for i in row.items[:GLANCE]))

    def explore_genres(self):
        """Every genre the list has not touched, liked or not, as Something different
        chooses among them (different() makes one of these a day)."""
        e, lib = self.e, self.lib
        rated = [e.by_id[p['id']] for p in self.positives + self.negatives]
        rows = (self.explore_row(key, f'{upper_first(self.EXPLORE_NOUNS.get(key, lower_first(title)))} to try', 'genre')
                for key, title in GENRE_ROWS.items()
                if key not in ('Drama', 'Comedy') and not any(lib._fits(key, i) for i in rated))
        return sorted((row for row in rows if row), key=lambda row: -statistics.fmean(self.fit(i) for i in row.items[:GLANCE]))

    def explore_row(self, key, title, sort):
        """A genre or format to explore: its well-known shows among the list's best fits,
        the well loved first as Something different orders them, or None when too few fit
        or its first cards do not fit well enough."""
        e = self.e
        found = sorted((i for i in self.lib.shelf_by_key.get(key, ()) if self.place_of.get(i, DEPTH_POOL) < DEPTH_POOL),
                       key=self.place_of.get)[:FILTER_POOL]
        if len(found) < SHORTEST:
            return None
        taste = ranks({i: self.taste_of(i) for i in found})
        score = {i: 0.5 * self.quality(i) + 0.3 * taste[i] + 0.2 * self.pop(i) for i in found}
        items = sorted(score, key=lambda i: (-score[i], e.shows[i]['id']))
        if not self.head_fits(items):
            return None
        return Shelf(f'explore-{slug(key)}', title, f'explore-{sort}', items, score, personal=False,
                     evidence=self.EXPLORE_EVIDENCE[sort], callouts=False, subtitle='A change from your usual')

    def browse_rows(self):
        """Tier 4: every genre, theme and format row with enough shows among the list's
        best fits, each cut and ordered as the first page's genre and theme rows are
        (default(take())). Genres and themes keep the first page's keys, so none shows
        twice; formats take keys and names of their own, since the first-visit rows hold
        theirs ("Documentaries for you", not "Documentaries"). A micro-genre cut down to
        its subject may have a row's name ("Mysteries") and stands in for it, and a row
        that repeats a tier 3 row or Something different is left to that."""
        e = self.e
        named = set()
        for k in sorted((k for k, s in enumerate(self.share) if s >= INTEREST_FLOOR / 2),
                        key=lambda k: -self.share[k])[:MOST_INTERESTS]:
            for parts in self.recipes(k):
                core = parts[0]
                named.add(upper_first(phrase_of([core])))
                if core.get('form'):
                    named.add(upper_first(phrase_of([core, core['form']])))
        group = {kind: key for key, kinds in FORMAT_GROUPS.items() if key in FORMAT_ROWS for kind in kinds}
        # What take() finds for each of the 62 rows, in one pass rather than 62.
        found = {}
        for i in self.depth:
            s = e.shows[i]
            tags = [('genre', g) for g in s['genres']] + [('format', group.get(s['type']))]
            bits = s['theme_bits']
            while bits:
                low = bits & -bits
                tags.append(('theme', e.themes[low.bit_length() - 1]))
                bits ^= low
            for tag in tags:
                items = found.setdefault(tag, [])
                if len(items) < FILTER_POOL:
                    items.append(i)
        rows = [(f'genre-{g}'.lower(), title, 'genre', g) for g, title in GENRE_ROWS.items()]
        rows += [(f'theme-{slug(title)}', title, 'theme', t) for t, title in THEME_ROWS.items()]
        rows += [(f'browse-{f}', f'{self.FORMAT_NAMES[f]} for you', 'format', f) for f in FORMAT_ROWS]
        # A genre or format the list has not touched has its row in tier 3, from the same
        # shows ("Legal dramas to try"), and is not browsed again under its plain name.
        explored = [row for row in self.explore_formats() + self.explore_genres() if row]
        tried = {row.key for row in explored}
        before = [row.top12 for row in explored + [self.different()] if row]
        out = []
        for key, title, sort, value in rows:
            if len(found.get((sort, value), ())) < SHORTEST or title in named or f'explore-{slug(value)}' in tried:
                continue
            items, score = self.default(found[sort, value])
            top = frozenset(items[:12])
            if any(len(top & other) >= 0.5 * min(12, len(top)) for other in before):
                continue
            out.append(Shelf(key, title, f'browse-{sort}', items, score, personal=False,
                             evidence=self.BROWSE_EVIDENCE[sort]))
        return out

    def list_row(self):
        """My List, most recently added first, when it holds a show not yet rated."""
        saved = list(reversed(self.saved))[:LIST_ROW]
        if not any(self.e.shows[i]['id'] not in self.rated for i in saved):
            return None
        return Shelf('list', 'My List', 'list', saved, kind='list', personal=False, shortest=1, callouts=False,
                     diverse=False)

    # ------------------------------------------------------------ choosing rows

    def tier_rows(self, tier):
        """The candidate rows of a tier past the first page's (tier 0): 1 more from the
        list itself, 2 each interest's own, 3 exploring, 4 browsing. Each is marked with
        its tier, and rows too short to show are left out."""
        rows = {1: self.personal_rows, 2: self.interest_rows, 3: self.explore_rows, 4: self.browse_rows}[tier]()
        for row in rows:
            if row:
                row.tier = tier
        return [row for row in rows if row and len(row.items) >= row.shortest]

    def relevance(self, shelf, heads, count):
        head = shelf.glance(heads, count)
        if not head:
            return 0.0
        weights = POSITION[:len(head)]
        k = shelf.interest
        return shelf.evidence * sum(w * self.fit(i, k) for w, i in zip(weights, head)) / sum(weights)

    def arrange(self, shelves, queues, different, pinned=()):
        """The rows in order. Each next row is the candidate with the most relevance less
        penalties for what it repeats: overlap with a row above, the same interest or the
        same sort of row in the two rows above, and taking its interest past its share.
        Penalties count half in the first eight rows and half again more below."""
        placed = list(pinned)
        heads, count = self.reserved()
        for row in pinned:
            heads.update(row.head)
            count.update(row.head)
        by_key = {s.key: s for s in shelves}
        for queue in queues:
            for s in queue:
                by_key.setdefault(s.key, s)
        taken = {row.key for row in pinned}
        interest_rows = Counter(row.interest for row in pinned if row.interest is not None)
        seeds = sum(1 for row in pinned if row.kind_of == 'seed')
        personal = sum(1 for row in pinned if row.personal)
        dropped = set()
        top10 = by_key.get('top10')
        tired = self.fresh.tired
        cap = self.cap - (1 if different else 0)
        relevances = [row.relevance for row in placed if row.relevance]
        quota = self.quota = self.quotas(cap)

        def queue_head(k):
            for s in queues[k]:
                if s.key not in taken and s.key not in dropped:
                    return s
            return None
        while len(placed) < cap:
            p = len(placed) + 1
            options = []
            if p == 1 and 'top' in by_key and 'top' not in taken:
                options = [by_key['top']]
            elif p == 2 and 'list' in by_key and 'list' not in taken:
                options = [by_key['list']]
            elif p == 10 and top10 and 'top10' not in taken and 'top10' not in tired:
                options = [top10]
            else:
                options = [s for s in shelves if s.key not in taken and s.key not in dropped
                           and s.kind_of not in ('top', 'list') and s.interest is None]
                options += [s for s in (queue_head(k) for k in range(len(queues))) if s]
                options = [s for s in options if not (s.key == 'top10' and p < 3)
                           and not (s.kind_of == 'popular' and p < 11)]
                if seeds >= SEED_ROWS[1]:
                    options = [s for s in options if s.kind_of != 'seed']
                if self.light and personal >= self.cap // 2:
                    options = [s for s in options if not s.personal]
                options = [s for s in options if s.interest is None or interest_rows[s.interest] < quota[s.interest]]
                # Every interest heavy enough has a row before the page fills up.
                unserved = [k for k in self.significant if not interest_rows[k] and queue_head(k)]
                if unserved and cap - len(placed) <= len(unserved):
                    options = [queue_head(k) for k in unserved]
                elif seeds < SEED_ROWS[0] and cap - len(placed) <= SEED_ROWS[0] - seeds:
                    options = [s for s in options if s.kind_of == 'seed'] or options
            scored = []
            scale = 0.5 if p <= FIRST_PAGE else 1.5
            above = placed[-2:]
            interest_total = sum(interest_rows.values())
            beyond = lambda k: max(0.0, (interest_rows[k] + 1) / (interest_total + 1) - self.share[k])
            least = min((beyond(s.interest) for s in options if s.interest is not None
                         and s.interest < len(self.share)), default=0.0)
            # Rows already shown come back as keys; their names are the candidates'.
            titles = {(getattr(row, 'title', None) or getattr(by_key.get(row.key), 'title', '')).casefold()
                      for row in placed} - {''}
            for s in options:
                if s.title.casefold() in titles:
                    # Two rows may reach one name (a genre row and a micro-genre both
                    # called Thrillers); a page shows it once.
                    dropped.add(s.key)
                    self.dropped[s.key] = 'same title as a row above'
                    continue
                rel = self.relevance(s, heads, count)
                if len(s.glance(heads, count)) < min(GLANCE, s.shortest) and s.kind == 'row':
                    dropped.add(s.key)
                    self.dropped[s.key] = 'too few cards left to open with'
                    continue
                # More like a favourite overlaps Top picks by nature when the favourite is from
                # the list's main interest; its first cards still differ, so only other rows count.
                overlap, like = max(((len(s.top12 & row.top12) / max(1, min(12, len(s.top12))), row.key)
                                     for row in placed if row.top12 and row.kind == 'row'
                                     and not (s.kind_of == 'seed' and row.kind_of == 'top')), default=(0.0, None))
                if overlap >= 0.5 and s.kind_of not in FIXED_KINDS:
                    dropped.add(s.key)
                    self.dropped[s.key] = f'repeats {like}'
                    continue
                same_interest = s.interest is not None and any(row.interest == s.interest for row in above)
                same_kind = any(row.kind_of == s.kind_of for row in above)
                excess = 0.0
                if s.interest is not None and s.interest < len(self.share):
                    excess = beyond(s.interest) - least
                penalty = 0.5 * overlap + 0.3 * same_interest + 0.3 * same_kind + 0.4 * excess
                scored.append((rel - scale * penalty, rel, s.key, s))
            if not scored:
                break
            value, rel, _key, best = max(scored, key=lambda x: (x[0], x[1], x[2]))
            unserved = [k for k in self.significant if not interest_rows[k] and queue_head(k)]
            overweight = self.light and 2 * personal > len(placed) + bool(different)
            if overweight and best.personal:
                # Past the plan, a short list's page takes only rows that are not personal.
                plain = [x for x in scored if not x[3].personal]
                if not plain:
                    break
                value, rel, _key, best = max(plain, key=lambda x: (x[0], x[1], x[2]))
            if len(placed) >= FEWEST_ROWS and relevances and not unserved and not overweight \
                    and best.kind_of not in FIXED_KINDS and max(x[1] for x in scored) < 0.5 * statistics.median(relevances):
                if not top10 or 'top10' in taken or 'top10' in tired:
                    break
                best, rel = top10, self.relevance(top10, heads, count)
            best.relevance = rel
            placed.append(best)
            taken.add(best.key)
            head = best.glance(heads, count)
            if best.kind == 'row':
                heads.update(head)
                count.update(i for i in best.items[:ROW] if count[i] < 2)
            if rel and best.kind_of != 'list':
                relevances.append(rel)
            if best.interest is not None:
                interest_rows[best.interest] += 1
            seeds += best.kind_of == 'seed'
            personal += best.personal
        # With fewer than ten liked shows, personal rows are at most half the page: when
        # rows that are not personal ran out first, the last personal ones go.
        while self.light and 2 * sum(row.personal for row in placed) > len(placed) + bool(different):
            last = max((n for n, row in enumerate(placed) if row.personal and n >= len(pinned) and row.kind_of != 'top'),
                       default=None)
            if last is None:
                break
            placed.pop(last)
        # Today's order: the first rows stay, the rest reorder a little from day to day,
        # and rows passed over lately rest at the end.
        if pinned:
            fixed = len(pinned)
        else:
            fixed, seen = 0, 0
            for n, row in enumerate(placed):
                if row.personal and row.kind_of not in ('list', 'top10'):
                    seen += 1
                if row.kind_of in ('top', 'list') or seen <= 2:
                    fixed = n + 1
                if seen >= 2:
                    break
        order = shuffle_rows(placed, self.fresh, key_of=lambda row: row.key, fixed=fixed)
        order = self.repair(order, fixed)
        if different and 'different' not in taken and len(order) > FIRST_PAGE:
            order.insert(max(12, fixed + 1) - 1 if len(order) >= 11 else len(order), different)
        return order

    def quotas(self, cap):
        """How many rows each interest may hold: its share of the rows planned for
        interests, at least one when it is heavy enough, and with three or more heavy
        interests no more than INTEREST_CAP of them; rows a capped interest cannot take go
        to the interests furthest below their share (Steck's calibration, by quota)."""
        significant = self.significant
        planned = max(len(significant), round(cap * INTEREST_ROWS))
        ceiling = max(1, int(INTEREST_CAP * planned)) if len(significant) >= 3 else planned
        exact = [share * planned for share in self.share]
        quota = Counter({k: min(ceiling, max(1 if k in significant else 0, int(x))) for k, x in enumerate(exact)})
        while sum(quota.values()) < planned:
            open_ = [k for k in range(len(exact)) if quota[k] < ceiling
                     and (k in significant or exact[k] - quota[k] >= 0.5)]
            if not open_:
                break
            quota[max(open_, key=lambda k: (exact[k] - quota[k], -k))] += 1
        return quota

    def repair(self, order, fixed):
        """Part two neighbours that serve the same interest or are the same sort of row,
        then keep the Top 10 within the first ten rows and Popular below them."""
        order = list(order)
        tired = self.fresh.tired
        placed = ('top10', 'popular')

        def clash(a, b):
            return (a.interest is not None and a.interest == b.interest) or \
                (a.kind_of == b.kind_of and a.kind_of != 'plain')
        for n in range(max(1, fixed), len(order)):
            if not clash(order[n - 1], order[n]) or order[n].key in placed:
                continue
            for m in range(n + 1, min(len(order), n + 4)):
                row = order[m]
                if not clash(order[n - 1], row) and row.key not in placed and row.key not in tired:
                    order.insert(n, order.pop(m))
                    break
        where = {row.key: n for n, row in enumerate(order)}
        if 'top10' in where and 'top10' not in tired and where['top10'] >= 10 and where['top10'] >= fixed:
            order.insert(max(9, fixed), order.pop(where['top10']))
        where = {row.key: n for n, row in enumerate(order)}
        if 'popular' in where and where['popular'] < 10 and where['popular'] >= fixed:
            order.insert(min(10, len(order) - 1), order.pop(where['popular']))
        return order

    def settle(self, rows, fixed=0):
        """Once rows that could not fill are gone, Popular still sits below the tenth
        row (or is left out of a shorter page) and Something different below the
        first eight (or is left out)."""
        rows = list(rows)
        for key, first in (('popular', 10), ('different', FIRST_PAGE)):
            where = next((n for n, (shelf, _items) in enumerate(rows) if shelf.key == key), None)
            if where is None or where >= first or where < fixed:
                continue
            row = rows.pop(where)
            if len(rows) >= first:
                rows.insert(first, row)
        return rows

    def reserved(self):
        """What My List opens with, held back from every other row's first cards and counted
        as shown once. The Top 10 is not held back: it always shows all ten, and a show
        trending today may still open Top picks, as it does on Netflix."""
        heads, count = set(), Counter()
        items = list(reversed(self.saved))[:LIST_ROW]
        heads.update(items[:GLANCE])
        count.update(items)
        return heads, count

    # ------------------------------------------------------------ cards

    def fill(self, order, pinned=()):
        """Cards for each row in order: the first two keep their places, the rest are the
        day's, no two rows open with the same show, no show appears more than twice, and a
        row opens with at most one show from a franchise and two from a creator."""
        heads, count = self.reserved()
        out = []
        for n, shelf in enumerate(order):
            if n < len(pinned):
                row = pinned[n]
                heads.update(row.head)
                count.update(row.head)
                if row.shelf:
                    count.update([i for i in row.shelf.items if i not in row.head][:ROW - len(row.head)])
                out.append((row, None))
                continue
            items = self.cards(shelf, heads, count)
            if items is not None:
                out.append((shelf, items))
        return out

    def cards(self, shelf, heads, count):
        """A row's cards (draw), counted as shown."""
        items = self.draw(shelf, heads, count)
        if items is not None and shelf.kind == 'row':
            heads.update(items[:GLANCE])
            count.update(items)
        return items

    def draw(self, shelf, heads, count, deep=False):
        """A row's cards given the cards the rows above opened with (heads) and how often
        each show is on the page (count), or None when too few are left: no show opens
        two rows or is on the page more than twice. Past today's rows (deep) each show the
        page already has goes behind those it has not, the further the more often it is
        there, so a long page keeps bringing shows it has not had rather than repeating."""
        if shelf.kind != 'row':
            return list(shelf.items)
        pool = [i for i in shelf.items if count[i] < 2]
        if len(pool) < shelf.shortest:
            return None
        score = shelf.score
        if deep:
            pool.sort(key=lambda i: -score.get(i, 0.0) * REAPPEAR ** (count[i] + (i in heads)))
        elif heads.intersection(pool):
            pool.sort(key=lambda i: -score.get(i, 0.0) * (REAPPEAR if i in heads else 1.0))
        order = self.lib.daily(pool, self.fresh, f'row-{shelf.key}', ROW, PINNED)
        groups = self.lib.groups
        if shelf.kind_of in PRECISE_KINDS:
            groups = lambda i: [g for g in self.lib.groups(i) if g[0] != 'network']
        order = spread(order, groups, keep=PINNED)
        chosen = set(order)
        head = self.opening(shelf, order + [i for i in pool if i not in chosen], heads)
        if len(head) < min(GLANCE, shelf.shortest):
            return None
        opened = set(head)
        items = head + [i for i in order if i not in opened][:ROW - len(head)]
        if len(items) < shelf.shortest:
            return None
        return items

    def opening(self, shelf, ordered, heads):
        """A row's first cards: none another row opened with, one per franchise, two per
        creator, no two neighbours from one network past the pinned cards, and, when the
        row allows, not alike: each next card is the best of the next eight that qualify,
        less TAG_SPREAD times its likeness to the cards already chosen."""
        lib = self.lib
        network = lambda i: self.e.shows[i]['channel']
        head, franchises, creators = [], set(), Counter()
        candidates = [i for i in ordered if i not in heads]
        allowed = lambda i: not (lib.facet_sets(i)[0] & franchises) and \
            not any(creators[c] >= 2 for c in lib.facet_sets(i)[1])
        precise = shelf.kind_of in PRECISE_KINDS
        while len(head) < GLANCE:
            pinned = len(head) < PINNED
            last = network(head[-1]) if head and not pinned and not precise else None
            best, value, weighed = None, None, 0
            for n, i in enumerate(candidates):
                if not allowed(i) or (last and network(i) == last):
                    continue
                v = -0.05 * n
                if shelf.diverse and not pinned:
                    v -= TAG_SPREAD * max((lib.alike(i, j) for j in head), default=0.0)
                if value is None or v > value:
                    best, value = i, v
                weighed += 1
                if pinned or weighed == 8:
                    break
            if best is None:
                # Only a neighbour from the same network is left: better that than a gap.
                best = next((i for i in candidates if allowed(i)), None)
                if best is None:
                    break
            candidates.remove(best)
            fr, cr = lib.facet_sets(best)[:2]
            franchises |= fr
            creators.update(cr)
            head.append(best)
        return head

    def callout(self, shelf, i):
        """One concrete tie a card has with a liked show: a world, a creator or a star."""
        lib, e = self.lib, self.e
        franchises, _creators, makers, cast = lib.facet_sets(i)
        if shelf.seed is not None:
            j = shelf.seed
            theirs = lib.facet_sets(j)
            name = e.shows[j]['name']
            if franchises & theirs[0]:
                return f'Same world as {name}'
            if makers & theirs[1]:
                return f'Same creator as {name}'
            stars = sorted(cast & theirs[3])
            return f'Stars {e.facets.labels[stars[0]]}' if stars else None
        owners = self.owners()
        for family, tokens in (('franchise', franchises), ('maker', makers), ('cast', cast)):
            for c in sorted(tokens):
                j = owners.get((family, c))
                if j is None or j == i:
                    continue
                if family == 'franchise':
                    return f'Same world as {e.shows[j]["name"]}'
                if family == 'maker':
                    return f'Same creator as {e.shows[j]["name"]}'
                return f'Stars {e.facets.labels[c]}'
        return None

    def owners(self):
        """For each rare franchise, creator and cast token of the liked shows, the liked
        show it came from, loves first and newest first."""
        if not hasattr(self, '_owners'):
            lib, e = self.lib, self.e
            common = TIE_COMMON * e.n
            self._owners = {}
            for p in sorted(self.positives, key=lambda p: (-p['weight'], -self.order[p['id']])):
                j = e.by_id[p['id']]
                franchises, creators, _makers, cast = lib.facet_sets(j)
                for family, tokens in (('franchise', franchises), ('maker', creators), ('cast', cast)):
                    for c in tokens:
                        if e.facets.df[c] <= common:
                            self._owners.setdefault((family, c), j)
        return self._owners

    def row(self, shelf, items):
        taste, lib = self.taste, self.lib
        cards = [lib.card(i, taste) for i in items]
        if shelf.callouts and self.e.facets:
            for n, (i, card) in enumerate(zip(items, cards)):
                if n >= CALLOUTS:
                    break
                said = self.callout(shelf, i)
                if said:
                    card['callout'] = said
        out = {'key': shelf.key, 'title': shelf.title, 'kind': shelf.kind, 'items': cards}
        if shelf.subtitle:
            out['subtitle'] = shelf.subtitle
        # A row past today's says which tier it was placed in, for the browser to send
        # back when it asks for more (Deeper.replay).
        if self.tier_of.get(shelf.key):
            out['tier'] = self.tier_of[shelf.key]
        return out

    # ------------------------------------------------------------ the page

    def layout(self, shown, want=None):
        """(rows the browser does not show yet, filled; every row so far). Today's rows
        (tier 0) are laid out whole, as they always were, and the rows past them one at a
        time (Deeper): to the page's end without want, else until want + 1 follow the
        shown ones, enough to say whether more could follow, so a tier is built only once
        the page reaches it. The same request gives the same rows; when the list changed
        since the browser's rows were built, those stay as they are and only the rows
        after them are rebuilt."""
        shelves, queues, different = self.shelves()
        # Matches for the shows the fixed rows carry from outside the pool.
        self.taste.score_others(self.lib.top10 + list(self.saved))
        listed = self.list_row()
        if listed:
            shelves.append(listed)
        order = self.arrange(shelves, queues, different)
        rows = self.settle(self.fill(order))
        # The shown rows from today's come first; each row below them carries its tier.
        cut = next((n for n, (_key, _ids, tier) in enumerate(shown) if tier), len(shown))
        today, below = shown[:cut], shown[cut:]
        keys = [shelf.key for shelf, _items in rows]
        if [key for key, _ids, _tier in today] != keys[:len(today)] or (below and len(today) != len(rows)):
            rows = self.pin(today, shelves, queues, different, whole=bool(below))
        new = rows[len(today):]
        if want is not None and len(new) > want:
            return new, rows
        # What is left of today's rows goes on to the tiers below.
        on_page = {row.key for row, _items in rows}
        pool = [s for s in shelves if s.key not in on_page]
        pool += [s for queue in queues for s in queue if s.key not in on_page]
        if different and different.key not in on_page:
            pool.append(different)
        deeper = Deeper(self, rows, pool)
        deeper.replay(below)
        new += deeper.more(None if want is None else want + 1 - len(new))
        return new, deeper.rows

    def pin(self, today, shelves, queues, different, whole=False):
        """Today's rows when the browser's no longer match them (the list changed since,
        or the day did): the browser's stay as they are and the rest of today's are built
        after them, unless the browser's rows already go past today's (whole)."""
        known = {s.key: s for s in shelves}
        for queue in queues:
            for s in queue:
                known.setdefault(s.key, s)
        if different:
            known.setdefault('different', different)
        pinned = [Pinned(key, [self.e.by_id[i] for i in ids if i in self.e.by_id], known.get(key))
                  for key, ids, _tier in today]
        if whole:
            return [(row, None) for row in pinned]
        shown = {key for key, _ids, _tier in today}
        left = [s for s in shelves if s.key not in shown]
        queues = [[s for s in queue if s.key not in shown] for queue in queues]
        if different and 'different' in shown:
            different = None
        order = self.arrange(left, queues, different, pinned)
        return self.settle(self.fill(order, pinned), len(pinned))

    def hero(self, rows):
        """The day's hero: drawn from the ten best picks not on My List and not a hero in
        the last week, preferring one the first rows do not already open with."""
        e = self.e
        saved = set(self.saved)
        eligible = [e.shows[i]['id'] for i in self.usable if i not in saved]
        eligible = [i for i in eligible if i not in self.fresh.resting][:10] or eligible[:1]
        visible = {e.shows[i]['id'] for shelf, items in rows[:3] if items for i in items[:GLANCE]}
        chosen = pick_one(eligible, self.fresh, 'hero', top=10, avoid=visible)
        return e.by_id[chosen] if chosen is not None else None


class Deeper:
    """The page past today's rows. Tier 1 opens where today's rows end and its rows join
    what is left of today's; each next row is the best of them less the penalties today's
    rows pay, and when the rows left run out or turn weak the next tier opens, until the
    last is spent and the page ends. A row gets its cards as it is placed, so the page can
    be taken up wherever a request left it: the rows the browser shows are replayed, not
    chosen again, and come out the same.

    A tier turns weak against its own rows, not the whole page's: relevance falls as a
    page goes deeper and each tier starts below the one before, so a bar set by the first
    page would close every tier within a row or two. Nor against the last few rows alone:
    a tier whose rows fall away slowly would pull that bar down with it, and run on into
    rows far weaker than the next tier's. The bar is half the median relevance of the
    rows since the tier opened, and of the last RECENT rows while it has fewer; once the
    last tier is open, the same drop ends the page."""

    def __init__(self, page, rows, pool):
        self.page = page
        self.rows, self.placed = [], []
        self.heads, self.count = page.reserved()
        self.titles, self.served, self.relevances, self.personal = set(), Counter(), [], 0
        self.pool, self.seen, self.dropped = {}, set(), set()
        self.glances, self.overlaps, self.nudges, self.quotas = {}, {}, {}, {}
        self.tier = self.opened = 0
        for row, items in rows:
            self.place(row, items, row.relevance, 0)
        for shelf in pool:
            self.join(shelf)
        self.open()

    def open(self):
        """The next tier's rows join those left, and the bar is set by its rows from here.
        Exploring opens with browsing: on its own it put fifteen rows to try in a row
        before the first row to browse, while together the penalty for repeating a sort of
        row spreads the rows to try among the rows to browse."""
        self.opened = len(self.relevances)
        for tier in (TIERS - 1, TIERS) if self.tier == TIERS - 2 else (self.tier + 1,):
            self.tier = tier
            for shelf in self.page.tier_rows(tier):
                self.join(shelf)

    def bar(self):
        """The relevance a row needs to be weighed: WEAK times the median of the rows since
        the deepest tier opened, and of the last RECENT rows while it has fewer."""
        if not self.relevances:
            return 0.0
        return WEAK * statistics.median(self.relevances[min(self.opened, max(0, len(self.relevances) - RECENT)):])

    def join(self, shelf):
        """One row to a key: a row waits to be placed unless one with its key already is,
        or is placed, as a browsing row is whose genre today's rows had. A first visit's
        row left over from today's gives way to a later tier's row with its key, cut for
        the list, as it gives way to the list's own among today's (shelves)."""
        waiting = self.pool.get(shelf.key)
        if shelf.key in self.seen and not (waiting and waiting.kind_of == 'plain' and shelf.kind_of != 'plain'):
            return
        self.seen.add(shelf.key)
        self.pool[shelf.key] = shelf
        self.dropped.discard(shelf.key)
        self.glances.pop(shelf.key, None)
        found = [(self.overlap(shelf, row), row.key) for row in self.placed]
        self.overlaps[shelf.key] = max((x for x in found if x[0]), default=(0.0, None))

    @staticmethod
    def overlap(shelf, row):
        """How much of a row's top twelve a row above holds already. More like a favourite
        may overlap Top picks, as it may among today's rows."""
        if not row.top12 or row.kind != 'row' or (shelf.kind_of == 'seed' and row.kind_of == 'top'):
            return 0.0
        return len(shelf.top12 & row.top12) / max(1, min(12, len(shelf.top12)))

    def place(self, row, items, rel, tier):
        """A row on the page with its cards, or, for a row the browser shows that did not
        come out the same (items None), with its first cards as the browser has them,
        counted as Page.fill counts them."""
        self.pool.pop(row.key, None)
        self.glances.pop(row.key, None)
        self.overlaps.pop(row.key, None)
        self.seen.add(row.key)
        self.rows.append((row, items))
        self.placed.append(row)
        row.relevance = rel
        if tier:
            self.page.tier_of[row.key] = tier
        if rel and row.kind_of != 'list':
            self.relevances.append(rel)
        shelf = row if isinstance(row, Shelf) else row.shelf
        if shelf is not None:
            self.titles.add(shelf.title.casefold())
        if row.interest is not None:
            self.served[row.interest] += 1
        self.personal += bool(row.personal)
        if items is None:
            head, shown = list(row.head), list(row.head)
            if row.shelf:
                shown += [i for i in row.shelf.items if i not in row.head][:ROW - len(row.head)]
        elif row.kind == 'row':
            head, shown = items[:GLANCE], items
        else:
            return
        self.heads.update(head)
        self.count.update(shown)
        # A waiting row keeps its first cards and relevance until a row placed takes one.
        taken = set(head) | {i for i in shown if self.count[i] >= 2}
        for key in [key for key, (glance, _rel) in self.glances.items() if not taken.isdisjoint(glance)]:
            del self.glances[key]
        if row.top12 and row.kind == 'row':
            for key, shelf in self.pool.items():
                value = self.overlap(shelf, row)
                if value > self.overlaps[key][0]:
                    self.overlaps[key] = (value, row.key)

    def glanced(self, shelf):
        """A waiting row's first cards as the page stands, and its relevance (Page.relevance)."""
        found = self.glances.get(shelf.key)
        if found is None:
            head, rel = shelf.glance(self.heads, self.count), 0.0
            if head:
                weights = POSITION[:len(head)]
                fit = self.page.fit
                rel = shelf.evidence * sum(w * fit(i, shelf.interest) for w, i in zip(weights, head)) / sum(weights)
            found = self.glances[shelf.key] = (head, rel)
        return found

    def nudge(self, key):
        """The day's nudge to a row's relevance, so rows past today's reorder a little from
        day to day as today's do (fresh.shuffle_rows); none without a day."""
        if key not in self.nudges:
            self.nudges[key] = math.exp(ROW_EPSILON * self.page.fresh.z('rows', key))
        return self.nudges[key]

    def quota(self, p):
        """Rows each interest may hold on a page p rows long: its share of them, planned
        as today's are (Page.quotas), so the quotas grow with the page."""
        if p not in self.quotas:
            self.quotas[p] = self.page.quotas(max(self.page.cap, p))
        return self.quotas[p]

    def options(self, p):
        """The rows that may come next, as (row, relevance, held back). A row that repeats
        a title above, has too few cards left to open with or half repeats a row above is
        left out for good; one resting (tired) or whose interest holds its share of a page
        this long is held back. Popular stays below row 10, the Top 10 below row 2 and
        Something different past the first page, as among today's rows. A first visit's
        row left over from today's waits for the last tier, where a row to browse by taste
        may take its key (join)."""
        page = self.page
        quota, tired = self.quota(p), page.fresh.tired
        out = []
        for key, shelf in self.pool.items():
            if key in self.dropped or (shelf.kind_of == 'popular' and p < 11) or (key == 'top10' and p < 3) \
                    or (shelf.kind_of == 'different' and p <= FIRST_PAGE) or (shelf.kind_of == 'plain' and self.tier < TIERS):
                continue
            why = None
            if shelf.title.casefold() in self.titles:
                why = 'same title as a row above'
            else:
                head, rel = self.glanced(shelf)
                if len(head) < min(GLANCE, shelf.shortest) and shelf.kind == 'row':
                    why = 'too few cards left to open with'
                elif self.overlaps[key][0] >= 0.5 and shelf.kind_of not in FIXED_KINDS:
                    why = f'repeats {self.overlaps[key][1]}'
            if why:
                self.dropped.add(key)
                page.dropped[key] = why
                continue
            held = key in tired or (shelf.interest is not None and self.served[shelf.interest] >= quota[shelf.interest])
            out.append((shelf, rel, held))
        return out

    def best(self, options, p):
        """The row with the most relevance, nudged for the day, less the penalties today's
        rows pay (Page.arrange). With fewer than ten liked shows, while the page would be
        more than half personal, a row that is not personal comes first if there is one."""
        page = self.page
        scale = 0.5 if p <= FIRST_PAGE else 1.5
        above = self.placed[-2:]
        total = sum(self.served.values())
        beyond = lambda k: max(0.0, (self.served[k] + 1) / (total + 1) - page.share[k])
        mine = lambda shelf: shelf.interest is not None and shelf.interest < len(page.share)
        least = min((beyond(shelf.interest) for shelf, _rel, _held in options if mine(shelf)), default=0.0)
        scored = []
        for shelf, rel, _held in options:
            same_interest = shelf.interest is not None and any(row.interest == shelf.interest for row in above)
            same_kind = any(row.kind_of == shelf.kind_of for row in above)
            excess = beyond(shelf.interest) - least if mine(shelf) else 0.0
            penalty = 0.5 * self.overlaps[shelf.key][0] + 0.3 * same_interest + 0.3 * same_kind + 0.4 * excess
            scored.append((rel * self.nudge(shelf.key) - scale * penalty, rel, shelf.key, shelf))
        best = max(scored, key=lambda x: (x[0], x[1], x[2]))
        if page.light and best[3].personal and 2 * (self.personal + 1) > p:
            plain = [x for x in scored if not x[3].personal]
            if plain:
                best = max(plain, key=lambda x: (x[0], x[1], x[2]))
        return best[3], best[1]

    def next(self):
        """The next row and its cards, or None where the page ends. Only rows that hold up
        against the rows above are weighed: this deep, a penalty of a few tenths is more
        than a weak row's whole relevance, and would let it in ahead of good ones. Rows
        held back have their turn once the rest are spent, before the next tier opens, so
        a tier's strong rows stay in it (as today's rows rest a tired row at their foot)."""
        while len(self.placed) < LONGEST:
            p = len(self.placed) + 1
            bar = self.bar()
            options = [option for option in self.options(p) if option[1] >= bar]
            ready = [option for option in options if not option[2]] or options
            if ready:
                shelf, rel = self.best(ready, p)
            elif self.tier < TIERS:
                self.open()
                continue
            else:
                return None
            items = self.page.draw(shelf, self.heads, self.count, deep=True)
            if items is None:
                self.dropped.add(shelf.key)
                self.page.dropped[shelf.key] = 'too few cards'
                continue
            self.place(shelf, items, rel, self.tier)
            return shelf, items
        return None

    def more(self, want=None):
        """Up to want more rows, or every row to the page's end, as (row, cards)."""
        out = []
        while want is None or len(out) < want:
            found = self.next()
            if found is None:
                break
            out.append(found)
        return out

    def replay(self, shown):
        """Place the rows the browser shows below today's as they were placed, in the
        tiers they were placed in: with the same cards when they come out the same, as
        they do while the list and the day stay the same, else with the browser's."""
        page, e = self.page, self.page.e
        for key, ids, tier in shown:
            while self.tier < min(tier, TIERS):
                self.open()
            head = [e.by_id[i] for i in ids if i in e.by_id]
            shelf = self.pool.get(key)
            if shelf is None:
                self.place(Pinned(key, head), None, 0.0, self.tier)
                continue
            _head, rel = self.glanced(shelf)
            items = page.draw(shelf, self.heads, self.count, deep=True)
            if items is not None and (shelf.kind != 'row' or [e.shows[i]['id'] for i in items[:GLANCE]] == ids):
                self.place(shelf, items, rel, self.tier)
            else:
                self.place(Pinned(key, head, shelf), None, rel, self.tier)


def ranks(values):
    """Each key's place among the values as a share, 1 for the highest and 0 for the
    lowest, so terms on different scales can be weighed against each other."""
    order = sorted(values, key=lambda i: -values[i])
    last = max(1, len(order) - 1)
    return {i: 1 - n / last for n, i in enumerate(order)}


def phrase_of(parts):
    """The subject of a micro-genre as it reads mid-sentence: "crime dramas", "Nordic noir"."""
    role = {p['role']: p for p in parts}
    core, form = role['core'], role.get('form')
    if core['kind'] != 'noun':
        return topic_phrase(core, form)
    if form and form['words'] == 'anime' and not core.get('anime'):
        return f'{core["singular"]} anime'
    return core['words']


def name_of(parts):
    """A micro-genre's name from its parts: [adjective] [country] [subgenre] [era]."""
    role = {p['role']: p for p in parts}
    phrase = phrase_of(parts)
    adjective = role.get('adjective')
    words = []
    if adjective and adjective['before']:
        words.append(adjective['words'])
    if 'place' in role:
        words.append(role['place']['words'])
    if adjective and not adjective['before']:
        words.append(adjective['words'].lower() if words else adjective['words'])
    words.append(phrase)
    if 'era' in role:
        words.append(role['era']['words'])
    return upper_first(' '.join(words))


def topic_phrase(core, form):
    topic = core['words']
    kind = form['words'] if form else None
    if kind == 'anime':
        return f'{topic} anime'
    if kind == 'animated':
        return f'animated {topic} shows'
    if kind == 'documentaries':
        return f'{topic} documentaries'
    if kind == 'reality':
        return f'{topic} reality shows'
    word = 'romantic' if topic == 'romance' else topic
    if kind == 'dramas':
        return 'dramas' if topic == 'drama' else f'{word} dramas'
    if kind == 'comedies':
        return f'{word} comedies'
    return {'romance': 'romances', 'drama': 'dramas'}.get(topic, f'{topic} shows')


def read_lang(body):
    """The browser's language, as the catalogue names it, when it is not English."""
    tags = body.get('lang', [])
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list) or len(tags) > 8 or any(not isinstance(t, str) or not LANG_TAG.match(t) for t in tags):
        raise ValueError('Send lang as up to 8 language tags, such as en-GB.')
    if not tags:
        return None
    primary = tags[0].split('-')[0].lower()
    return None if primary == 'en' else LANGUAGES.get(primary)


def read_shown(body):
    """The rows the browser already shows, in order, as (key, first show ids, tier): the
    tier a row past today's was placed in, and 0 for today's rows and for rows kept from
    before rows carried one."""
    shown = body.get('shown', [])
    if not isinstance(shown, list) or len(shown) > LONGEST:
        raise ValueError(f'Send shown as a list of up to {LONGEST} rows.')
    out, keys = [], set()
    for row in shown:
        if not isinstance(row, dict) or not isinstance(row.get('key'), str) or not ROW_KEY.match(row['key']):
            raise ValueError('Each shown row needs a key of lower-case letters, digits and hyphens.')
        ids = row.get('ids', [])
        if not isinstance(ids, list) or len(ids) > GLANCE or any(type(i) is not int or i < 0 for i in ids):
            raise ValueError(f'Send up to {GLANCE} show ids for each shown row.')
        tier = row.get('tier', 0)
        if type(tier) is not int or not 0 <= tier <= TIERS:
            raise ValueError(f'A shown row\'s tier is a whole number from 0 to {TIERS}.')
        if row['key'] in keys:
            raise ValueError('Each shown row should appear only once.')
        keys.add(row['key'])
        out.append((row['key'], ids, tier))
    return out


def read_count(body, shown):
    count = body.get('count', NEXT_PAGE if shown else FIRST_PAGE)
    if type(count) is not int or not 0 <= count <= FIRST_PAGE:
        raise ValueError(f'Ask for 0 to {FIRST_PAGE} rows.')
    return count


class Library:
    def __init__(self, engine, art_path):
        self.e = e = engine
        with gzip.open(art_path, 'rb') as f:
            data = f.read()
        if data[:4] != b'ART1':
            raise ValueError('Not a Couchside art file.')
        (count,) = struct.unpack('<I', data[4:8])
        if count != e.n or len(data) != 8 + 6 * count:
            raise ValueError('Art track does not match the catalog.')
        self.images = array('I')
        self.images.frombytes(data[8:8 + 4 * count])
        self.ended = array('H')
        self.ended.frombytes(data[8 + 4 * count:])
        if sys.byteorder != 'little':
            self.images.byteswap()
            self.ended.byteswap()
        self.year = int(e.date[:4])

        # Everything below is the same for everyone, so it is worked out once.
        rating = lambda i: e.shows[i]['rating'] or 0
        shelf = [i for i, s in enumerate(e.shows) if s['recommendable'] and self.images[i] and e.popularity[i] >= 85]
        shelf.sort(key=lambda i: (-e.popularity[i], -rating(i), e.shows[i]['id']))
        self.shelf = shelf
        current = [i for i in shelf if e.shows[i]['year'] >= self.year - 1
                   or (e.shows[i]['status'] == 'Running' and e.shows[i]['year'] >= self.year - 5)]
        self.top10 = current[:10]
        self.top10_set = set(self.top10)
        today = date.fromisoformat(e.date)
        self.recent = {i for i in shelf if e.shows[i]['premiered']
                       and 0 <= (today - date.fromisoformat(e.shows[i]['premiered'])).days <= NEW_DAYS}
        self.popular = [i for i in shelf if i not in set(self.top10)][:ROW]
        self.acclaimed = sorted((i for i in shelf if rating(i) >= 8.5), key=lambda i: (-rating(i), e.shows[i]['id']))
        self.fresh = [i for i in shelf if e.shows[i]['year'] == self.year]
        soon = [i for i, s in enumerate(e.shows)
                if (s['premiered'] or '') > e.date and self.images[i] and e.popularity[i] >= 90]
        self.soon = sorted(soon, key=lambda i: (e.shows[i]['premiered'], -e.popularity[i]))[:ROW]
        self.cold = []
        for kind, value in COLD_ROWS:
            if kind == 'genre':
                items = [i for i in shelf if value in e.shows[i]['genres']]
                title = GENRE_ROWS[value]
            else:
                allowed = FORMAT_GROUPS[value]
                items = [i for i in shelf if e.shows[i]['type'] in allowed]
                title = FORMAT_ROWS[value]
            self.cold.append((f'{kind}-{value}'.lower(), title, items))
        # First-visit posters: drawn per visitor by /api/starters from shows with posters.
        self.starting = Starters(e, lambda i: self.images[i] != 0)
        self.starters = self._starters()
        # Everything a person can browse by, each fronted by its best-known show that no
        # earlier tile already uses, so the grid does not repeat one poster.
        self.genres, fronted = [], set()
        for key, label in [*GENRE_ROWS.items(), *FORMAT_ROWS.items()]:
            fits = [i for i in shelf if self._fits(key, i)]
            top = next((i for i in fits if i not in fronted), fits[0] if fits else None)
            if top is not None:
                fronted.add(top)
                self.genres.append({'key': key, 'label': label, 'poster': self.poster(top)})
        self._home_setup()

    def _home_setup(self):
        """What the home page needs that is the same for everyone."""
        e = self.e
        shelf = self.shelf
        rating = lambda i: e.shows[i]['rating'] or 0
        # All-time favourites: premiered before 2010, well known and well rated.
        self.classics = sorted((i for i in shelf if e.shows[i]['year'] and e.shows[i]['year'] < 2010 and rating(i) >= 8),
                               key=lambda i: (-(e.popularity[i] + 10 * rating(i)), e.shows[i]['id']))
        # Popular right now weighs the well known that are not in the Top 10.
        self.popular_pool = [i for i in shelf if i not in self.top10_set]
        self.shelf_by_key = {key: [i for i in shelf if self._fits(key, i)] for key in [*GENRE_ROWS, *FORMAT_ROWS]}
        known = set(e.metadata['language'])
        self.languages = {code: name for code, name in LANGUAGES.items() if name in known}
        self.by_language = {}
        for i in sorted((i for i, s in enumerate(e.shows) if s['recommendable'] and self.images[i]
                         and e.popularity[i] >= 70 and s['language'] in self.languages.values()),
                        key=lambda i: (-e.popularity[i], -rating(i), e.shows[i]['id'])):
            self.by_language.setdefault(e.shows[i]['language'], []).append(i)
        # Limited series, from their summaries, Wikidata's genres and the awards they won.
        self.limited = {i for i, s in enumerate(e.shows) if s['recommendable'] and LIMITED_WORDS.search(s['summary'] or '')}
        f = e.facets
        self.facet_column = {}
        if f:
            for family_index, family in enumerate(f.families):
                start, end = f.family_ranges[family_index]
                for c in range(start, end):
                    self.facet_column.setdefault((family, f.labels[c]), c)
            for family, labels in (('genre', LIMITED_GENRES), ('award', LIMITED_AWARDS)):
                for c in (self.facet_column.get((family, label)) for label in labels):
                    if c is not None:
                        self.limited.update(f.post_rows[p] for p in range(f.col_ptr[c], f.col_ptr[c + 1])
                                            if e.shows[f.post_rows[p]]['recommendable'])
        # Leanings as the values the taste model keeps, for testing shows against them.
        a = e.attributes
        self.values = {}
        for family in ('language', 'format', 'country', 'decade', 'network'):
            for v, label in enumerate(a.labels[family]):
                if label is not None:
                    self.values[(family, label)] = v
                    if family == 'country':
                        self.values[(family, COUNTRIES.get(label, label))] = v
        for family in ('genre', 'theme', 'subgenre'):
            for bit, label in enumerate(a.labels.get(family, ())):
                self.values[(family, label)] = bit
        self._pools = {}

    # ------------------------------------------------------------ shapes

    def poster(self, i, size='medium_portrait'):
        image = self.images[i]
        return IMAGE.format(size=size, bucket=image // 2500, image=image) if image else None

    def card(self, i, taste=None):
        s = self.e.shows[i]
        return {'id': s['id'], 'name': s['name'], 'year': s['year'], 'poster': self.poster(i),
                'genres': s['genres'][:3], 'runtime': s['runtime'], 'type': s['type'],
                'match': taste.match(i) if taste else None,
                'badge': 'top10' if i in self.top10_set else 'new' if i in self.recent else None}

    def _fits(self, key, i):
        """Whether show i belongs under a genre, or under a format such as animation."""
        if key in FORMAT_ROWS:
            return self.e.shows[i]['type'] in FORMAT_GROUPS[key]
        return key in self.e.shows[i]['genres']

    def detail(self, i, taste=None):
        themes, _genres = self.e.signals(i)
        return {**self.e.full(i), 'ended': self.ended[i] or None, 'premiered': self.e.shows[i]['premiered'],
                'poster': self.poster(i), 'art': self.poster(i, 'original_untouched'),
                'themes': [t.split(' / ')[0] for t in themes], 'match': taste.match(i) if taste else None}

    def _starters(self):
        """A few posters for a first visit, for when the page cannot ask for starters: the
        plain screen, drawn without a visitor's seed."""
        return [self.card(slot.index) for slot in self.starting.choose(count=FALLBACK)]

    def starters_for(self, seed, rnd, picked, lang, count):
        """First-visit posters for a visitor, each with why it is there (starters.py)."""
        return [{**self.card(slot.index), 'why': slot.why}
                for slot in self.starting.choose(seed, rnd, picked, lang, count)]

    def daily(self, items, fresh, surface, length, pinned):
        """The day's order for a row of catalog indices (fresh.dither), which, like the
        browser's counts of what it showed, speaks TVmaze's show ids."""
        shows, by_id = self.e.shows, self.e.by_id
        return [by_id[i] for i in dither([shows[i]['id'] for i in items], fresh, surface, length, pinned=pinned)]

    # ------------------------------------------------------------ what shows share

    @lru_cache(maxsize=20000)
    def facet_sets(self, i):
        """Show i's franchise tokens, creators (Wikidata's creators, told apart from its
        writers, producers and directors by weight), every maker and its cast."""
        f = self.e.facets
        if not f:
            return frozenset(), frozenset(), frozenset(), frozenset()
        franchise, makers, cast = set(), {}, set()
        families = f.families
        for c, value in f.row(i):
            family = families[f.token_family[c]]
            if family == 'franchise':
                franchise.add(c)
            elif family == 'maker':
                # A creator weighs 1 and anyone else 0.6 before scaling, so a creator's
                # value over the token's rarity stands above the rest.
                makers[c] = value / max(math.log(self.e.n / max(f.df[c], 1)), 1e-6)
            elif family == 'cast':
                cast.add(c)
        creators = frozenset()
        if makers:
            top = max(makers.values())
            lead = {c for c, r in makers.items() if r >= 0.9 * top}
            if len(makers) <= 2 or (len(lead) < len(makers) and len(lead) <= 3):
                creators = frozenset(lead)
        return frozenset(franchise), creators, frozenset(makers), frozenset(cast)

    def holders(self, family, tokens):
        """Every show carrying any of the tokens (maker tokens match any maker)."""
        f = self.e.facets
        out = set()
        for c in tokens:
            out.update(f.post_rows[p] for p in range(f.col_ptr[c], f.col_ptr[c + 1]))
        return out

    def overlap(self, i, j, family):
        mine = self.facet_sets(i)[0] if family == 'franchise' else self.facet_sets(i)[2]
        theirs = self.facet_sets(j)[0] if family == 'franchise' else self.facet_sets(j)[2]
        return len(mine & theirs)

    def groups(self, i):
        """What a show's neighbours should not all share: its network and franchises."""
        channel = self.e.shows[i]['channel']
        return ([('network', channel)] if channel else []) + [('franchise', c) for c in self.facet_sets(i)[0]]

    @lru_cache(maxsize=20000)
    def tags(self, i):
        s, a = self.e.shows[i], self.e.attributes
        sub = a.masks['subgenre'][i] if 'subgenre' in a.masks else 0
        return s['genre_bits'] | s['theme_bits'] << 32 | sub << 64

    def alike(self, i, j):
        a, b = self.tags(i), self.tags(j)
        union = (a | b).bit_count()
        return (a & b).bit_count() / union if union else 0.0

    def pool_stats(self, settings):
        """For the pool a request's settings allow: each popularity's percentile and the
        rating a quarter of rated shows reach. The same for everyone with those settings."""
        key = tuple(sorted((k, v) for k, v in settings.items() if k in (
            'language', 'type', 'status', 'year_min', 'runtime_min', 'rating_min', 'known_min')))
        if key not in self._pools:
            e = self.e
            kind = settings['type']
            formats = None if kind == 'all' else set(FORMAT_GROUPS.get(kind, (kind,)))
            pool = [i for i in range(e.n) if e.eligible(i, settings, formats)]
            counts = Counter(e.popularity[i] for i in pool)
            table, below = [], 0
            for v in range(256):
                table.append((below + counts[v] / 2) / len(pool) if pool else 0.0)
                below += counts[v]
            ratings = sorted(e.shows[i]['rating'] for i in pool if e.shows[i]['rating'])
            q75 = ratings[int(0.75 * (len(ratings) - 1))] if ratings else 10.0
            if len(self._pools) > 16:
                self._pools.clear()
            self._pools[key] = {'popularity': table, 'rating_q75': q75, 'pool': pool}
        return self._pools[key]

    # ------------------------------------------------------------ micro-genres

    def form(self, members):
        """The form most of an interest's shows take, for naming a topic."""
        if not members:
            return None
        shows = self.e.shows
        share = lambda test: sum(1 for i in members if test(i)) / len(members)
        if share(lambda i: 'Anime' in shows[i]['genres'] or (shows[i]['type'] == 'Animation'
                                                              and shows[i]['language'] == 'Japanese')) >= 0.6:
            return 'anime'
        for words, kind in (('animated', 'Animation'), ('documentaries', 'Documentary'), ('reality', 'Reality')):
            if share(lambda i, kind=kind: shows[i]['type'] == kind) >= 0.6:
                return words
        comedy = share(lambda i: 'Comedy' in shows[i]['genres'])
        drama = share(lambda i: 'Drama' in shows[i]['genres'])
        if comedy >= 0.6 and comedy > drama:
            return 'comedies'
        if drama >= 0.6:
            return 'dramas'
        return None

    def traits(self, members):
        """Leanings for an interest too small to have any: what its shows all share,
        rarest first."""
        a, e = self.e.attributes, self.e
        found = []
        for family in ('subgenre', 'genre'):
            if family not in a.masks:
                continue
            common = ~0
            for i in members:
                common &= a.masks[family][i]
            bits = [b for b in range(len(a.labels[family])) if common >> b & 1 and a.base[family][b] < 0.3]
            found += sorted(((a.base[family][b], family, a.labels[family][b]) for b in bits))
        for family in ('country', 'language', 'decade', 'format'):
            values = {a.values[family][i] for i in members}
            if len(values) == 1:
                v = values.pop()
                if v and a.base[family][v] < 0.3:
                    found.append((a.base[family][v], family, a.label(family, v)))
        found.sort(key=lambda f: f[0])
        return [(family, label) for _base, family, label in found]

    def core(self, family, label, form):
        """What a leaning names as a row's subject, or None."""
        if family not in ('subgenre', 'genre', 'format'):
            return None
        tests = self.attr_tests([(family, label)])
        if not tests:
            return None
        anime_form = form == 'anime'
        form_part = None
        if form and form in FORMS:
            form_tests = self.attr_tests(FORMS[form])
            if form_tests:
                form_part = {'role': 'form', 'words': form, 'tests': form_tests}
        if label in NOUNS:
            words = NOUNS[label]
            core = {'role': 'core', 'kind': 'noun', 'words': words, 'tests': tests, 'family': family, 'source': label,
                    'regional': words in REGIONAL, 'anime': words.endswith('anime'),
                    'singular': SINGULAR.get(label, label.lower())}
            if anime_form and not words.endswith('anime') and family == 'subgenre':
                core['form'] = form_part
            return core
        if label in TOPICS:
            topic = TOPICS[label]
            return {'role': 'core', 'kind': 'topic', 'words': topic, 'tests': tests, 'family': family,
                    'source': label, 'form': form_part, 'anime': anime_form}
        return None

    def place(self, family, label):
        if (family, label) not in self.values or label == 'English':
            return None
        return {'role': 'place', 'words': label, 'label': label, 'tests': self.attr_tests([(family, label)])}

    def era(self, label):
        if ('decade', label) not in self.values:
            return None
        words = f'from {label}' if label.startswith('before') else f'from the {label}'
        return {'role': 'era', 'words': words, 'tests': self.attr_tests([('decade', label)])}

    def adjective(self, label):
        for word, before, sources in ADJECTIVES:
            if label in sources:
                tests = self.attr_tests([('subgenre' if s[:1].islower() else 'genre', s) for s in sources])
                if tests:
                    return {'role': 'adjective', 'words': word, 'before': before, 'tests': tests, 'sources': sources}
        return None

    def attr_tests(self, attributes):
        """(family, value) pairs for leanings the catalogue knows, skipping any it does not."""
        out = []
        for family, label in attributes:
            if family == 'genre' and label[:1].islower():
                family = 'subgenre'
            key = (family, label)
            if key in self.values and (family != 'subgenre' or 'subgenre' in self.e.attributes.masks):
                out.append((family, self.values[key]))
        return tuple(out)

    def recipe_test(self, parts):
        """A test for shows that have every part (and, within a part, any of its leanings)."""
        checks = [self.part_test(part) for part in parts]
        if len(checks) == 1:
            return checks[0]
        return lambda i: all(check(i) for check in checks)

    def part_test(self, part):
        """A test for one part: a show has it when it has any of the part's leanings."""
        a = self.e.attributes
        masks, values = {}, {}
        for family, value in part['tests']:
            if family in ('subgenre', 'genre', 'theme'):
                masks[family] = masks.get(family, 0) | 1 << value
            else:
                values.setdefault(family, set()).add(value)
        checks = [(lambda column, mask: lambda i: column[i] & mask)(a.masks[f], m) for f, m in masks.items()]
        checks += [(lambda column, allowed: lambda i: column[i] in allowed)(a.values[f], frozenset(v))
                   for f, v in values.items()]
        if not checks:
            return lambda i: False
        if len(checks) == 1:
            return checks[0]
        return lambda i: any(check(i) for check in checks)

    def proto(self, core):
        """How clearly a show stands for a core subgenre: its weight among its genres."""
        f = self.e.facets
        column = self.facet_column.get(('genre', core.get('source', ''))) if f else None
        if column is None:
            return lambda i: 1 / max(1, len(self.e.shows[i]['genres']))
        return lambda i: next((v for c, v in f.row(i) if c == column), 0.0)

    # ------------------------------------------------------------ rows for everyone

    def plain_rows(self):
        """The rows a first visit sees after the Top 10 and Popular, as (key, title, items)
        in the order they are tried."""
        out = [('classics', 'All-time favourites', self.classics),
               ('this-year', 'New this year', self.fresh)]
        out += self.cold
        return out

    # ------------------------------------------------------------ requests

    def read_list(self, body):
        """My List as ids, most recently added last. Unknown ids are dropped, which is
        what a list saved against an older snapshot needs."""
        ids = body.get('list', [])
        if not isinstance(ids, list) or len(ids) > MAX_SAVED:
            raise ValueError(f'My List can hold up to {MAX_SAVED} shows.')
        if any(type(i) is not int for i in ids):
            raise ValueError('Show ids must be whole numbers.')
        return [self.e.by_id[i] for i in dict.fromkeys(ids) if i in self.e.by_id]

    def prepare(self, body):
        """The request checked: its list split by rating, its settings, the pool those
        settings allow less what is rated, and what the browser has shown (fresh.py)."""
        profile, settings, _chosen, fresh = self.e.read(body)
        rated = {p['id'] for p in profile}
        profile = self.e.focus(profile)
        positives = [p for p in profile if p['weight'] > 0]
        negatives = [p for p in profile if p['weight'] < 0]
        pool = self.pool_stats(settings)['pool']
        candidates = [i for i in pool if self.e.shows[i]['id'] not in rated]
        return profile, settings, positives, negatives, rated, candidates, fresh

    def home(self, body):
        """The home page, or the next rows of it. A first request gets the hero and the
        first eight rows; one that says which rows it shows (shown) gets the next six."""
        profile, settings, positives, negatives, rated, candidates, fresh = self.prepare(body)
        saved = self.read_list(body)
        lang = read_lang(body)
        shown = read_shown(body)
        count = read_count(body, shown)
        e = self.e
        if not positives:
            return self._cold(saved, rated, fresh, lang, shown, count)
        page = Page(self, profile, settings, positives, negatives, rated, candidates, saved, fresh, lang)
        new, rows = page.layout(shown, count)
        taste = page.taste
        answer = {
            'personal': True, 'date': e.date, 'day': fresh.day,
            'rows': [page.row(shelf, items) for shelf, items in new[:count]],
            'more': len(new) > count,
            # What the list leans toward and away from, and the interests it holds, for
            # showing a person their own taste.
            'taste': e.taste(profile).summary(),
            'interests': [{**interest, 'names': [page.names[i] for i in interest['shows']]}
                          for interest in page.ranking.describe()],
            # My List is drawn by the page, which keeps it instant; these carry its matches.
            'list': [self.card(i, taste) for i in saved],
            'message': '' if page.usable else 'Nothing matches these settings. Widen the catalogue in your profile menu.',
        }
        if not shown:
            hero = page.hero(rows) if page.usable else self.top10[0]
            if hero is None:
                hero = self.top10[0]
            taste.score_others([hero])
            popular = next((items for shelf, items in rows if shelf.key == 'popular'), None)
            by_taste = lambda items: sorted(items, key=lambda i: (-(taste.match(i) or 0), e.shows[i]['id']))
            unrated = [i for i in self.fresh if e.shows[i]['id'] not in rated]
            answer.update({
                'hero': {**self.detail(hero, taste), 'because': taste.closest(hero) if page.usable else None},
                'top10': [self.card(i, taste) for i in self.top10],
                'fresh': [self.card(i, taste) for i in by_taste(unrated)[:ROW]],
                'soon': [{**self.card(i), 'premiered': e.shows[i]['premiered']} for i in self.soon],
                'popular': [self.card(i, taste) for i in (popular or page.popular().items[:ROW])],
            })
        return answer

    def _cold(self, saved, rated, fresh, lang, shown, count):
        """A page before anything is rated: what is popular now, all-time favourites, new
        this year, and a row for each of the best-known genres and formats, no show twice.
        A browser in another language than English also gets that language's most popular."""
        e = self.e
        rows = self._cold_rows(saved, rated, fresh, lang, [])
        keys = [key for key, *_rest in rows]
        if [key for key, _ids, _tier in shown] != keys[:len(shown)]:
            rows = self._cold_rows(saved, rated, fresh, lang, shown)
        new = rows[len(shown):]
        card = lambda i: self.card(i)
        answer = {
            'personal': False, 'date': e.date, 'day': fresh.day,
            'rows': [{'key': key, 'title': title, 'kind': kind, 'items': [card(i) for i in items]}
                     for key, title, kind, items in new[:count]],
            'more': len(new) > count,
            'list': [card(i) for i in saved], 'message': '',
            'taste': {'leans': [], 'avoids': []}, 'interests': [],
        }
        if not shown:
            ranked = [e.shows[i]['id'] for i in self.top10]
            hero = e.by_id[pick_one(ranked, fresh, 'hero', top=10)]
            popular = next((items for key, _t, _k, items in rows if key == 'popular'), self.popular)
            answer.update({
                'hero': {**self.detail(hero), 'because': None},
                'top10': [card(i) for i in self.top10],
                'fresh': [card(i) for i in self.fresh[:ROW]],
                'soon': [{**card(i), 'premiered': e.shows[i]['premiered']} for i in self.soon],
                'popular': [card(i) for i in popular],
            })
        return answer

    def _cold_rows(self, saved, rated, fresh, lang, shown):
        """The first-visit rows as (key, title, kind, items). Rows the browser shows keep
        their places and their shows stay off the rows after them."""
        e = self.e
        shown_keys = {key for key, _ids, _tier in shown}
        used = {e.by_id[i] for _key, ids, _tier in shown for i in ids if i in e.by_id}
        rows, fixed = [], 0
        rows.append(('top10', 'Top 10 shows today', 'top10', self.top10))
        used.update(self.top10)
        listed = list(reversed(saved))[:LIST_ROW]
        if any(e.shows[i]['id'] not in rated for i in listed):
            rows.append(('list', 'My List', 'list', listed))
            used.update(listed)

        def take(source):
            return [i for i in source if i not in used and e.shows[i]['id'] not in rated]

        def add(key, title, source, fix=False):
            nonlocal fixed
            pool = take(source)
            items = self.daily(pool, fresh, f'row-{key}', ROW, PINNED)
            if len(items) >= SHORTEST:
                used.update(items)
                rows.append((key, title, 'row', items))
                if fix:
                    fixed = len(rows)
        add('popular', 'Popular right now', self.popular_pool, fix=True)
        if lang and lang in self.by_language:
            add(f'popular-{slug(lang)}', f'Popular in {lang}', self.by_language[lang], fix=True)
        add('classics', 'All-time favourites', self.classics)
        add('this-year', 'New this year', self.fresh)
        genres = 0
        for key, title, items in self.cold:
            if genres == 8:
                break
            before = len(rows)
            add(key, title, items)
            genres += len(rows) > before
        fixed = max(fixed, 1)
        order = rows[:fixed] + shuffle_rows(rows[fixed:], fresh, key_of=lambda row: row[0], fixed=0)
        if shown:
            prefix = [row for row in order if row[0] in shown_keys]
            rest = [row for row in order if row[0] not in shown_keys]
            by_key = {row[0]: row for row in prefix}
            order = [by_key.get(key, (key, '', 'row', [])) for key, _ids, _tier in shown] + rest
        return order

    def browse(self, body):
        """Rows for one genre or format: ranked for you once you have rated something,
        by popularity before that."""
        key = body.get('genre') if isinstance(body, dict) else None
        if not isinstance(key, str) or (key not in GENRE_ROWS and key not in FORMAT_ROWS):
            raise ValueError('Choose a genre to browse.')
        profile, settings, positives, negatives, rated, candidates, fresh = self.prepare(body)
        e = self.e
        label = GENRE_ROWS.get(key) or FORMAT_ROWS[key]
        noun = lower_first(label)
        shelf = [i for i in self.shelf if self._fits(key, i) and e.shows[i]['id'] not in rated]
        taste = Taste(self, positives, negatives, settings, candidates) if positives else None
        out = Rows(self, taste, fresh)
        rating = lambda i: e.shows[i]['rating'] or 0
        acclaimed = [i for i in shelf if rating(i) >= 8]
        if taste:
            taste.score_others(shelf)
            top = [i for i in taste.ranked() if self._fits(key, i)]
            out.add('top', f'Top {noun} for you', top)
            out.add('new', f'New {noun} for you', [i for i in top if e.shows[i]['year'] >= self.year - 1])
            out.add('acclaimed', f'Acclaimed {noun}', sorted(acclaimed, key=lambda i: (-(taste.match(i) or 0), e.shows[i]['id'])))
            out.add('popular', f'Popular {noun}', shelf)
            out.add('more', f'More {noun} you might like', top[ROW:])
        else:
            out.add('popular', f'Popular {noun}', shelf)
            out.add('new', f'New {noun}', [i for i in shelf if e.shows[i]['year'] >= self.year - 1])
            out.add('acclaimed', f'Acclaimed {noun}', sorted(acclaimed, key=lambda i: (-rating(i), e.shows[i]['id'])))
            out.add('more', f'More {noun}', shelf[ROW:])
        return {'genre': key, 'title': label, 'personal': bool(taste), 'rows': out.rows}

    def title(self, body):
        show_id = body.get('id') if isinstance(body, dict) else None
        if type(show_id) is not int or show_id not in self.e.by_id:
            raise ValueError('That show is not in this catalog.')
        profile, settings, positives, negatives, rated, candidates, fresh = self.prepare(body)
        e, i = self.e, self.e.by_id[show_id]
        taste = Taste(self, positives, negatives, settings, candidates) if positives else None
        # More like this: closeness to this one show, less the pull of anything disliked,
        # and when the show is one you liked, the taste of the interest it belongs to.
        affinities = Closeness(e, settings)
        affinities[show_id] = e.blend(i, settings)
        if taste:
            affinities.update(taste.affinities)
        pool = [j for j in candidates if j != i]
        near = e.rank(pool, [{'id': show_id, 'weight': 1}], negatives, affinities, settings, positives or None)
        ranked = sorted((j for j in pool if near[j] > 0), key=lambda j: (-near[j], e.shows[j]['id']))
        # The closest few stay put; the rest of the twelve are the day's.
        more = self.daily(ranked, fresh, f'more-{show_id}', MORE, GLANCE)
        if taste:
            taste.score_others([i, *more])
        show = self.detail(i, taste)
        show['because'] = taste.closest(i) if taste and show_id not in rated else None
        show['summary'] = show['summary'] or ''
        return {'show': show, 'more': [{**self.card(j, taste), 'summary': e.shows[j]['summary'] or ''} for j in more]}

    def cards(self, ids):
        return [self.card(self.e.by_id[i]) for i in ids if i in self.e.by_id]
