"""Find a show by any of its titles, however it is typed.

Every show is indexed under its TVmaze name and, when the model carries
search.json.gz, under its other titles from Wikidata: labels and aliases in every
language, such as La casa de papel or Shingeki no Kyojin. Titles and queries are
read the same way. Case and accents go; an apostrophe joins its word (Grey's reads
greys) unless it elides an article (l'amour reads l amour); & reads as and; any
other punctuation separates words. Titles are also compared with every space
removed and with spelled-out numbers as digits, so sponge bob finds SpongeBob
SquarePants, 911 finds 9-1-1 and brooklyn 99 finds Brooklyn Nine-Nine.

A query is matched in tiers, and each tier is looked at only while fewer than a
page of shows has turned up:

  1. exact     the whole title, with or without a leading article: office is The Office
  2. prefix    the title starts with the query: breaking b, the last of
  3. words     every word of the query starts a word of the title, in any order
  4. inside    every word starts a word of the title or sits inside one: bob
  5. typos     every word matches, some with one slip: stranger thigns, sucession
  6. initials  a word stands for consecutive words of the title: law and order svu
  7. part      the query holds all or most of the title and more besides:
               Demon Slayer: Kimetsu no Yaiba finds Demon Slayer

Within a tier the best-known show comes first, by TVmaze's popularity, then the
public rating, then the year. Typos go by how few there are, and part matches by
how much of the title the query covers and how much of the query the title
covers, each word weighted by how rare it is. A year at the end of a query, as in
doctor who 2005, puts the show that premiered that year first rather than asking
for the year as a word. A show found only through another of its titles carries
that title as aka.

A quarter of a million titles are held as flat arrays and byte strings rather than
a Python object each, which keeps them to tens of megabytes:

  text   every title's words, one title per line in UTF-8, each show's name followed
         by its other titles, best-known show first, so a line's number is its rank
  vocab  every distinct word, sorted; post holds the lines using each word in one run,
         so the words sharing a prefix share one slice of it
  order  the titles' compact forms, sorted: spaces removed, and also without a
         leading article or with number words as digits; each is read back from text
"""
from array import array
from bisect import bisect_left, bisect_right
from collections import defaultdict
from itertools import accumulate, chain
from operator import itemgetter
import gzip
import json
import math
import re
import sys
import unicodedata
import zlib

LIMIT = 12
STRONG = 3              # the loosest tier that answers a search by itself: every word starts a title's word
MOST_ALIASES = 100      # other titles kept per show
LONGEST = 150           # characters in the longest other title worth keeping
MOST_WORDS = 16         # words of a query that count
WIDE = 5000             # lines a tier weighs to find a year's show before settling
BROAD = 3000            # lines weighed for part matches, best-known first
YEAR = re.compile(r'(?:19|20)\d\d')
ARTICLES = frozenset(w.encode() for w in 'the a an la le les l el los las il lo der die das'.split())
UNITS = {w.encode(): n for n, w in enumerate(
    'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen '
    'seventeen eighteen nineteen'.split())}
TENS = {w.encode(): n for n, w in zip(range(20, 100, 10), 'twenty thirty forty fifty sixty seventy eighty ninety'.split())}
TOP = b'\xff'           # after any UTF-8, so the keys starting with p end before p + TOP
LETTERS = 'abcdefghijklmnopqrstuvwxyz0123456789'


def _class(points):
    """A regular expression character class for sorted code points."""
    runs, start = [], None
    for a, b in zip(points, points[1:] + [None]):
        start = a if start is None else start
        if b != a + 1:
            runs.append(re.escape(chr(start)) + ('-' + re.escape(chr(a)) if a > start else ''))
            start = None
    return ''.join(runs)


def _marks():
    # Combining marks go with the accents, except those that are part of a letter's
    # spelling, such as the vowel signs of Devanagari and Thai, which stay inside their
    # word. No mark lies beyond the first two planes.
    drop, keep = [], []
    for point in range(0x20000):
        c = chr(point)
        if unicodedata.combining(c):
            drop.append(point)
        elif unicodedata.category(c)[0] == 'M':
            keep.append(point)
    return [p for p in drop if p < 0x10000], _class(keep)


_DROP, _KEEP = _marks()
# Checked in two parts: a class of basic-plane marks is a quick table lookup, while one
# reaching into the next plane makes the engine test every range for every character.
COMBINING = re.compile(f'[{_class(_DROP)}]')
ASTRAL = re.compile('[\U00010000-\U0001ffff]')
SEPARATOR = re.compile(f'[^\\w \\n{_KEEP}]|_')
SPACES = re.compile(' {2,}')
APOSTROPHE = re.compile("['’‘ʼ`′]")
# An apostrophe after a lone letter or qu at the start of a word, before another word,
# elides an article or pronoun: l'amour, d'Artagnan, qu'il.
ELISION = re.compile(r"['’‘ʼ`′](?<=(?<![^\W_])[cdjlmnst].)(?=[^\W_])|['’‘ʼ`′](?<=(?<![^\W_])qu.)(?=[^\W_])")


def _astral(m):
    return '' if unicodedata.combining(m[0]) else m[0]


def normalize(texts):
    """Each text as its words, one space apart. Titles and queries both come through
    here, so they always agree. No text may hold a newline."""
    # Decomposed before folding, so styled letters such as 𝕏 fold as plain ones do.
    blob = unicodedata.normalize('NFKD', '\n'.join(texts)).casefold()
    blob = ASTRAL.sub(_astral, COMBINING.sub('', blob))
    blob = APOSTROPHE.sub('', ELISION.sub(' ', blob)).replace('&', ' and ')
    return list(map(str.strip, SPACES.sub(' ', SEPARATOR.sub(' ', blob)).split('\n')))


def numbered(words):
    """Number words as digits, tens joined to units: nine nine as 9 9, twenty one as 21."""
    out, tens = [], False
    for w in words:
        unit = UNITS.get(w)
        if tens and unit is not None and 0 < unit < 10:
            out[-1] = str(int(out[-1]) + unit).encode()
            tens = False
            continue
        tens = w in TENS
        out.append(str(TENS[w]).encode() if tens else w if unit is None else str(unit).encode())
    return out


def forms(words):
    """The compact forms of a query's words, by kind: 0 plain, 1 without a leading
    article, 2 with numbers as digits, 3 both. A form that repeats an earlier one is
    left out."""
    found = {b''.join(words): 0}
    if len(words) > 1 and words[0] in ARTICLES:
        found.setdefault(b''.join(words[1:]), 1)
    digits = numbered(words)
    if digits != words:
        found.setdefault(b''.join(digits), 2)
        if len(digits) > 1 and digits[0] in ARTICLES:
            found.setdefault(b''.join(digits[1:]), 3)
    return found


def form(words, kind):
    """One compact form of a title's words, by the kinds forms() names."""
    if kind & 2:
        words = numbered(words)
    return b''.join(words[1:] if kind & 1 else words)


def edits(word):
    """Every string one slip from word: a character dropped, swapped with the next,
    changed or added. Changes and additions use plain letters and digits, and word's own.
    The commonest pair of slips counts as one: two letters typed once that should be
    doubled, or doubled that should be single, as in sucesion for succession."""
    letters = set(LETTERS) | set(word)
    splits = [(word[:k], word[k:]) for k in range(len(word) + 1)]
    out = {a + b[1:] for a, b in splits if b}
    out |= {a + b[1] + b[0] + b[2:] for a, b in splits if len(b) > 1}
    out |= {a + c + b[1:] for a, b in splits if b for c in letters}
    out |= {a + c + b for a, b in splits for c in letters}
    n = len(word)
    out |= {word[:i] + word[i] + word[i:j] + word[j] + word[j:] for i in range(n) for j in range(i + 1, n)}
    twins = [k for k in range(n - 1) if word[k] == word[k + 1]]
    out |= {word[:i] + word[i + 1:j] + word[j + 1:] for i in twins for j in twins if i + 1 < j}
    out.discard(word)
    return out


def load_aliases(path):
    """Show id to its other titles, from search.json.gz. Empty, never an error, when
    the file is missing or cannot be read."""
    try:
        with gzip.open(path, 'rt', encoding='utf-8') as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, EOFError, ValueError, RecursionError, zlib.error) as exc:
        print(f'Ignoring {path}: {exc}', file=sys.stderr, flush=True)
        return {}
    aliases = raw.get('aliases') if isinstance(raw, dict) and raw.get('version') == 1 else None
    if not isinstance(aliases, dict):
        print(f'Ignoring {path}: it is not version 1 with a map of aliases', file=sys.stderr, flush=True)
        return {}
    found = {}
    for key, names in aliases.items():
        if isinstance(key, str) and key.isdigit() and len(key) < 10 and isinstance(names, list):
            kept = [n.replace('\n', ' ') for n in names if isinstance(n, str) and 0 < len(n) <= LONGEST]
            if kept:
                found[int(key)] = kept[:MOST_ALIASES]
    return found


class Found:
    """What a search turned up: (show index, aka) pairs, best first, and whether the
    best of them matched well enough that looking further afield would add nothing."""

    def __init__(self, hits, strong):
        self.hits, self.strong = hits, strong


class Titles:
    """Every show's titles, indexed once; find() answers a search."""

    def __init__(self, shows, popularity, aliases=None):
        aliases = aliases or {}
        self.shows = shows
        n = len(shows)
        # Best known first: popularity, then rating, then year, packed into one number
        # because sorting ninety thousand tuples is slow.
        ranked = sorted(range(n), key=lambda i: (100 - popularity[i]) << 48 | (100 - round(10 * (shows[i]['rating'] or 0))) << 40
                        | (4095 - (shows[i]['year'] or 0)) << 28 | shows[i]['id'])
        self.rank = array('I', bytes(4 * n))
        self.first = array('I', bytes(4 * n))
        raw, owners = [], array('i')
        for r, i in enumerate(ranked):
            self.rank[i] = r
            raw.append(shows[i]['name'].replace('\n', ' '))
            owners.append(i)
            more = aliases.get(shows[i]['id'])
            if more:
                raw += more
                owners.extend([~i] * len(more))
        lines = normalize(raw)

        # One line per distinct title, and the lines using each word, in line order. A
        # show's name always has a line; another title that reads the same as the name,
        # or as an earlier title, adds nothing. What lasts is flat, and the few small
        # objects that last are made once the scaffolding is gone, so the memory it
        # borrowed is not pinned between them.
        kept, akas, post, seen = [], [], defaultdict(list), set()
        owner, first = [], self.first
        for line, who, title in zip(lines, owners, raw):
            if who >= 0:
                seen = {line}
                first[who] = len(kept)
            elif not line or line in seen:
                continue
            else:
                seen.add(line)
                akas.append(title)
                who = ~who
            d = len(kept)
            kept.append(line)
            owner.append(who)
            for w in line.split():
                post[w].append(d)
        del lines, raw, owners, seen
        self.n = len(kept)
        self.owner = array('I', owner)
        del owner
        encoded = list(map(str.encode, kept))
        del kept
        self.text = b'\n'.join(encoded) + b'\n'
        self.start = array('I', list(accumulate(map((1).__add__, map(len, encoded)), initial=0)))
        akas = list(map(str.encode, akas))
        self.aka = b'\n'.join(akas)
        self.aka_start = array('I', list(accumulate(map((1).__add__, map(len, akas)), initial=0)))
        del akas

        # A word twice in one title lists that title twice; nothing downstream minds.
        vocab = sorted(post)
        runs = list(map(post.__getitem__, vocab))
        self.post_start = array('I', list(accumulate(map(len, runs), initial=0)))
        self.post = array('I', list(chain.from_iterable(runs)))
        counted = set(chain.from_iterable(post.get(w.decode(), ()) for w in (*UNITS, *TENS)))
        del runs, post
        words = '\n'.join(vocab).encode()
        del vocab

        # Compact forms: every line's plain form, then the forms without a leading
        # article (kind 1) and with number words as digits (kinds 2 and 3). Entries are
        # line << 2 | kind, and key() reads each back from the text.
        keyed = list(zip(self.text.replace(b' ', b'').split(b'\n'), range(0, 4 * self.n, 4)))
        led = tuple(a + b' ' for a in ARTICLES)
        keyed += [(e.split(b' ', 1)[1].replace(b' ', b''), d << 2 | 1)
                  for d, e in enumerate(encoded) if e.startswith(led)]
        for d in counted:
            digits = numbered(encoded[d].split())
            keyed.append((b''.join(digits), d << 2 | 2))
            if len(digits) > 1 and digits[0] in ARTICLES:
                keyed.append((b''.join(digits[1:]), d << 2 | 3))
        del encoded, counted
        keyed.sort()
        self.order = array('I', list(map(itemgetter(1), keyed)))
        del keyed
        self.vocab = words.split(b'\n') if words else []

    # ------------------------------------------------------------ reading

    def line(self, d):
        return self.text[self.start[d]:self.start[d + 1] - 1]

    def key(self, entry):
        return form(self.line(entry >> 2).split(), entry & 3)

    def aka_of(self, d):
        show = self.owner[d]
        if self.first[show] == d:
            return None
        k = d - self.rank[show] - 1
        return ' '.join(self.aka[self.aka_start[k]:self.aka_start[k + 1] - 1].decode().split())

    def compact(self, target, prefix=False):
        """Lines with a compact form equal to target, or starting with it."""
        lo = bisect_left(self.order, target, key=self.key)
        hi = (bisect_left(self.order, target + TOP, lo, key=self.key) if prefix
              else bisect_right(self.order, target, lo, key=self.key))
        return {e >> 2 for e in self.order[lo:hi]}

    def span(self, word):
        """The run of vocab words that start with word."""
        return bisect_left(self.vocab, word), bisect_left(self.vocab, word + TOP)

    def word_id(self, word):
        k = bisect_left(self.vocab, word)
        return k if k < len(self.vocab) and self.vocab[k] == word else None

    def using(self, lo, hi):
        """Lines using any of the vocab words lo to hi."""
        return self.post[self.post_start[lo]:self.post_start[hi]]

    def inside(self, part):
        """Lines where part appears anywhere, inside a word or not."""
        found, text, start = set(), self.text, self.start
        at = text.find(part)
        while at >= 0:
            d = bisect_right(start, at) - 1
            found.add(d)
            at = text.find(part, start[d + 1])
        return found

    # ------------------------------------------------------------ search

    def find(self, q, limit=LIMIT):
        words = normalize([q.replace('\n', ' ')])[0].split()[:MOST_WORDS]
        if not words:
            return Found([], True)
        tokens = [w.encode() for w in words]
        best = {}
        if len(words) > 1 and YEAR.fullmatch(words[-1]):
            # Either the year is part of the title (Space: 1999) or it picks one of
            # several shows of a name (Doctor Who, 2005). Both are weighed.
            year = int(words[-1])
            self.match(words, tokens, year, best, limit, deep=False)
            self.match(words[:-1], tokens[:-1], year, best, limit, deep=True)
        else:
            self.match(words, tokens, None, best, limit, deep=True)
        top = sorted(best.values())[:limit]
        return Found([(self.owner[d], self.aka_of(d)) for _key, d in top], bool(top) and top[0][0][0] <= STRONG)

    def match(self, words, tokens, year, best, limit, deep):
        """Add the shows the tokens match to best, tier by tier, until a page is full."""
        shows, owner, line = self.shows, self.owner, self.line
        stamp = str(year).encode() if year else None

        def take(tier, found):
            """found is lines in order, or (sub, line) pairs in order; sub ranks within the tier."""
            weighed = 0
            for item in found:
                sub, d = item if isinstance(item, tuple) else (0, item)
                show = owner[d]
                dated = bool(year) and (shows[show]['year'] == year or stamp in line(d).split())
                key = (tier, not dated, sub, d)
                held = best.get(show)
                if held is None or key < held[0]:
                    best[show] = (key, d)
                weighed += 1
                if len(best) >= limit and (not year or weighed >= WIDE):
                    break
            return sum(1 for key, _d in best.values() if key[0] <= tier) >= limit

        # A single character could be the start of anything, so it finds only a title
        # of that one character, such as V.
        shapes = forms(tokens)
        if take(1, sorted(set().union(*(self.compact(f) for f in shapes)))) or len(''.join(words)) < 2:
            return
        typed = [f for f, kind in shapes.items() if kind in (0, 2)]
        if take(2, sorted(set().union(*(self.compact(f, prefix=True) for f in typed)))):
            return

        spans = [self.span(t) for t in tokens]
        counts = [self.post_start[hi] - self.post_start[lo] for lo, hi in spans]
        if all(counts):
            order = sorted(range(len(tokens)), key=counts.__getitem__)
            found = set(self.using(*spans[order[0]]))
            for k in order[1:]:
                found.intersection_update(self.using(*spans[k]))
            if take(3, sorted(found)):
                return

        def fits(t, ws):
            return any(w.startswith(t) or (len(t) > 2 and t in w) for w in ws)

        long = [k for k, t in enumerate(tokens) if len(t) > 2]
        if long:
            # Anchored on the rarest word, so the text is read once and few lines follow.
            anchor = tokens[min(long, key=lambda k: (counts[k], -len(tokens[k])))]
            rest = [t for t in tokens if t is not anchor]
            found = (d for d in sorted(self.inside(anchor)) if all(fits(t, line(d).split()) for t in rest))
            if take(4, found):
                return
        if not deep:
            return

        # Typos: each word starts a word of the title, or is one slip from a whole word,
        # or, for the last word, one slip from the start of one it is still typing.
        last = len(words) - 1
        slips = [self.slips(w) for w in words]
        typing = self.slips(words[-1], typing=True)
        if any(slips) or typing:
            exact = [set(self.using(*s)) for s in spans]
            near = [exact[k].union(*(self.using(lo, hi) for lo, hi in slips[k] + (typing if k == last else [])))
                    for k in range(len(tokens))]
            pool = set.intersection(*sorted(near, key=len))
            counted = sorted((sum(d not in e for e in exact), d) for d in pool)
            if take(5, [(n, d) for n, d in counted if n]):
                return

        # Initials: a word of three to six letters stands for as many consecutive words
        # of the title, and every other word starts one.
        for k, t in enumerate(tokens):
            if not 3 <= len(t) <= 6 or not t.isalnum() or not t.isascii():
                continue
            rest = tokens[:k] + tokens[k + 1:]
            narrow = sorted([spans[j] for j in range(len(tokens)) if j != k] + [self.span(t[j:j + 1]) for j in range(len(t))],
                            key=lambda s: self.post_start[s[1]] - self.post_start[s[0]])
            pool = set(self.using(*narrow[0]))
            for s in narrow[1:3]:
                pool.intersection_update(self.using(*s))
            found = []
            for d in sorted(pool):
                ws = line(d).split()
                if t in bytes(w[0] for w in ws) and all(any(w.startswith(r) for w in ws) for r in rest):
                    found.append(d)
            if take(6, found):
                return

        # Part: only when nothing starts with the query, since then it may well be longer
        # than the title it means.
        if len(tokens) > 1 and not any(key[0] <= 2 for key, _d in best.values()):
            take(7, self.part(tokens, spans, slips))

    def slips(self, word, typing=False):
        """Runs of vocab words, as (lo, hi) pairs, one slip from word; or, typing, the
        words that start with a string one slip from it and with the same letter."""
        if len(word) < 3:
            return []
        own = self.span(word.encode())
        runs = []
        for guess in edits(word):
            if typing and (len(guess) < 4 or guess[0] != word[0]):
                continue
            guess = guess.encode()
            k = bisect_left(self.vocab, guess)
            if k == len(self.vocab):
                continue
            if typing and self.vocab[k].startswith(guess):
                runs.append((k, bisect_left(self.vocab, guess + TOP, k)))
            elif not typing and self.vocab[k] == guess and not own[0] <= k < own[1]:
                runs.append((k, k + 1))
        return runs

    def part(self, tokens, spans, slips):
        """Titles the query covers wholly or mostly, with words to spare: (sub, line)
        pairs, best first, where sub ranks by how much each covers of the other. Words
        count by how rare they are, so the and no count for little."""
        n = self.n
        weight = lambda df: math.log((n + 1) / (df + 1))
        df = lambda lo, hi: self.post_start[hi] - self.post_start[lo]
        ids = [self.word_id(t) for t in tokens]
        # A slip in a short word matches too much to say what a title is about.
        near = [{k for lo, hi in slips[j] for k in range(lo, hi)} if ids[j] is None and len(tokens[j]) > 4 else set()
                for j in range(len(tokens))]
        asked = [weight(df(ids[j], ids[j] + 1) if ids[j] is not None else 0) for j in range(len(tokens))]
        pool = set()
        for j in range(len(tokens)):
            runs = ([(ids[j], ids[j] + 1)] if ids[j] is not None else []) + [(k, k + 1) for k in near[j]]
            if sum(df(lo, hi) for lo, hi in runs) <= BROAD:
                for lo, hi in runs:
                    pool.update(self.using(lo, hi))
        scored = []
        for d in sorted(pool)[:BROAD]:
            ws = self.line(d).split()
            wids = [self.word_id(w) for w in ws]
            hit = [{j for j in range(len(tokens)) if wid == ids[j] or wid in near[j]} for wid in wids]
            have = [weight(df(wid, wid + 1)) for wid in wids]
            title = sum(h for h, m in zip(have, hit) if m) / (sum(have) or 1)
            query = sum(asked[j] for j in set().union(*hit)) / (sum(asked) or 1)
            if title >= .5 and query >= .25:
                scored.append((-round(2 * title * query / (title + query), 3), d))
        scored.sort()
        return scored
