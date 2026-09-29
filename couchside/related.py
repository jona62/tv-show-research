"""Shows like a search: beside the titles it matches, a row of what it is like.

GET /api/search answers with the shows whose titles match (fallback.answer, Next
Watch's own), and this adds one row of shows related to the search, as Netflix's
search does. Which row depends on what was typed:

- A search that names a show gets *More like* that show: the title page's own More
  like this (engine.py: closeness in plot, themes and genres, a franchise or makers
  shared, and what the show's Wikipedia readers look up next), less the shows the
  search already matched. It names a show when it is one of the show's titles typed
  in full, or with a slip or two, or holding the whole title and more, or when
  TVmaze's search put the show first; or when it starts the title of a show nearly
  everyone knows, as "game of" does while it is typed. The show must be well known
  too, so that "the matrix" is not taken for Matrix, a 1993 series about a hitman.
- A search that names a topic, a genre or subject from Wikidata's labels such as
  "zombies", "space opera" or "true crime", gets *Shows like* it, by meaning. A show
  nearly everyone knows keeps its own name (Supernatural), and so does any
  well-known show named after a place (Atlanta, Dallas).
- Anything else gets *Shows like* it by meaning when the catalogue holds evidence of
  what it means, as for a film ("mad max"); a search still being typed waits.

Meaning comes from evidence about each show: a Wikidata genre or subject the search
names; the search among a show's keywords, the terms its summary is most about; the
search as a phrase in its summary; and the search in its title. The shows with
evidence are anchors. Their Wikidata genres and subjects, weighed by how rare each
is and kept only when the anchors lean toward it, make a profile: "mad max" is in
Daybreak's summary, Daybreak is post-apocalyptic, and so the row is post-apocalyptic
shows. A show's place in the row is its evidence plus its closeness to the profile,
times how well known it is and how well its format (scripted, animation, reality...)
fits the anchors'.

The summaries and keywords of the 47,000 shows at least REACH well known are searched
as byte strings of plain lowercase words, about 19 MB built once, in the background
at startup or on first use; each answer is kept, since a search's row changes only
with the model. Standard library only.
"""
from array import array
from bisect import bisect_right
from collections import OrderedDict
import heapq
import math
import re
import threading
import unicodedata

from engine import DEFAULT_SETTINGS
from titles import YEAR, forms, normalize

COUNT = 18          # shows in a related row
FEWEST = 4          # a row found by meaning needs at least this many
MEANT = 4           # and a search of at least this many letters: gam or mad is half a word
NAMED = 75          # how well known a show must be for its title typed in full to name it
TYPED = 95          # and for the start of its title to name it
HOUSEHOLD = 97      # a show this well known keeps its name even when a topic has it too
# More like weighs the 3,000 closest shows by taste, not all 25,000: its first twelve are
# then the title page's for 96% of the 300 best-known shows, in half the time.
CLOSEST = 3000
# Summaries and keywords searched belong to shows at least this well known: the 47,000
# down to The Animatrix (48), whose summary tells what "the matrix" means, where the
# 25,000 a row may offer would leave that search to fantasy romances.
REACH = 40
ANCHORS = 40        # anchors whose genres and subjects make a search's profile
LEAN = 0.15         # share of the anchors a genre or subject needs to join the profile
LIFT = 3.0          # and how many times more often than among shows in general
RARE = 2            # a genre or subject counts toward the profile by its rarity (idf) to this power
FURTHER = 0.25      # past the part of the profile a show carries best, each other part counts this much
COMMON = 0.015      # a phrase in more than this share of summaries says too little alone
FAME = 4            # a show's place is scaled by its popularity, out of 100, to this power
FIT = 0.35          # a format none of the anchors has keeps this share of its place
PROFILE = 1.0       # closeness to the profile, at best, against the evidence below
MOST = 1.6          # evidence past this adds nothing more
CACHED = 1024       # answers kept
# What each kind of evidence is worth, and a keyword counts less when the search is
# only one word of it (zombie in zombie apocalypse).
LABEL, KEYWORD, KEYWORD_PART, PHRASE, TITLE = 1.0, 0.6, 0.3, 0.4, 0.3
STOP = frozenset(b'a an and at by for from in is it of on or the to with'.split())
ARTICLES = frozenset(b'the a an'.split())
# Every byte a plain word may hold stays, capitals as small letters, newlines as they
# are; anything else is a space. Apostrophes are dropped, so Grey's reads greys. KEPT
# also keeps the bar that stands between a show's keywords.
FOLD = bytes(c + 32 if 65 <= c <= 90 else c if 97 <= c <= 122 or 48 <= c <= 57 or c == 10 else 32
             for c in range(256))
KEPT = FOLD[:124] + b'|' + FOLD[125:]
SPACES = re.compile(rb' {2,}')
NEWLINE = re.compile(rb'\n')


def folded(texts, table=FOLD):
    """The texts as plain lowercase ASCII words, one space apart, a line each: accents
    go, and anything not a letter or digit separates words. Summaries and searches alike."""
    raw = b'\n'.join((t if t.isascii() else unicodedata.normalize('NFKD', t)).encode('ascii', 'ignore').replace(b'\n', b' ')
                     for t in texts)
    return SPACES.sub(b' ', raw.translate(table, b"'`"))


def fold(texts):
    """Each text folded, as its own bytes."""
    return [line.strip() for line in folded(texts).split(b'\n')]


def lines(texts, table=FOLD, chunk=4096):
    """(text, where each line starts, and where the text ends): the texts folded, a line
    each, every line opening and closing with a space so that each of its words, the
    first and the last too, sits between spaces. One string, not a string a line, which
    keeps tens of thousands of lines to their bytes; folded a few thousand at a time, so
    building it takes little more than it keeps."""
    parts = [SPACES.sub(b' ', b' ' + folded(texts[k:k + chunk], table).replace(b'\n', b' \n ') + b' \n')
             for k in range(0, len(texts), chunk)]
    text = b''.join(parts)
    del parts
    starts = array('I', [0])
    starts.extend(m.end() for m in NEWLINE.finditer(text))
    return text, starts


def numbers(word):
    """A word and its other number: zombies and zombie, mysteries and mystery, witch
    and witches. Forms that are no word are harmless: nothing is found under them."""
    out = [word]
    if word.endswith(b'ies') and len(word) > 4:
        out += [word[:-1], word[:-3] + b'y']
    elif word.endswith(b'es') and len(word) > 4:
        out += [word[:-1], word[:-2]]
    elif word.endswith(b's') and not word.endswith(b'ss') and len(word) > 3:
        out.append(word[:-1])
    elif len(word) > 2:
        out.append(word + (b'es' if word.endswith((b's', b'x', b'z', b'ch', b'sh')) else b's'))
        if word.endswith(b'y') and word[-2:-1] not in b'aeiou':
            out.append(word[:-1] + b'ies')
    return out


def slipped(typed, title):
    """Whether typed words are a title's words with a slip or two, as titles.py reads
    typos: word for word, each within one slip, a slip only in a word of four letters or
    more, and two at most, with or without a leading article. brekaing bad is Breaking
    Bad; jurassic park is not Jurassic War."""
    if len(typed) == len(title) - 1 and title[0] in ARTICLES:
        title = title[1:]
    if len(typed) != len(title) or typed == title:
        return False
    count = 0
    for a, b in zip(typed, title):
        if a != b:
            if min(len(a), len(b)) < 4 or not slips(a, b, 1):
                return False
            count += 1
    return count <= 2


def slips(a, b, most):
    """Whether a and b are within most slips of each other: a character added, dropped,
    changed or two swapped (optimal string alignment distance)."""
    if abs(len(a) - len(b)) > most:
        return False
    before, row = None, list(range(len(b) + 1))
    for x in range(1, len(a) + 1):
        now = [x] + [0] * len(b)
        for y in range(1, len(b) + 1):
            cost = a[x - 1] != b[y - 1]
            now[y] = min(row[y] + 1, now[y - 1] + 1, row[y - 1] + cost)
            if before and x > 1 and y > 1 and a[x - 1] == b[y - 2] and a[x - 2] == b[y - 1]:
                now[y] = min(now[y], before[y - 2] + 1)
        if min(now) > most:
            return False
        before, row = row, now
    return row[-1] <= most


class Related:
    """The related row for any search, over one engine. pool is the shows a row may
    offer: those a title page's More like this offers before any settings."""

    def __init__(self, engine, pool, settings=None):
        e = self.e = engine
        self.settings = dict(settings or DEFAULT_SETTINGS)
        self.pool = list(pool)
        self.offered = bytearray(e.n)
        for i in self.pool:
            self.offered[i] = 1
        # Wikidata's genres and subjects by label, and for each: its rarity over the whole
        # catalogue, as build_facets.py weighed it into every value; its share of the shows
        # that have any of its family; and its family.
        self.labels, self.proper, self.rarity, self.base, self.family = {}, set(), {}, {}, {}
        f = e.facets
        if f:
            for name in ('genre', 'subject'):
                if name not in f.families:
                    continue
                start, end = f.family_ranges[f.families.index(name)]
                known = max(f.coverage.get(name, 0), max((f.df[c] for c in range(start, end)), default=1), 1)
                for c in range(start, end):
                    label = f.labels[c]
                    self.labels.setdefault(normalize([label])[0], []).append(c)
                    self.rarity[c] = math.log(e.n / max(f.df[c], 1)) or 1.0
                    self.base[c] = f.df[c] / known
                    self.family[c] = name
                    # A place, a year or an event (Atlanta, 1899, World War II) is where or
                    # when a show is set, not what it is like, so it names a topic but
                    # stays out of a profile.
                    if name == 'subject' and not label[:1].islower():
                        self.proper.add(c)
        self.index = None
        self.building = threading.Lock()
        self.answers = OrderedDict()
        self.lock = threading.Lock()

    # ---------------------------------------------------------------- built once

    def warm(self):
        """Builds what searching by meaning reads now rather than on first use."""
        self.ready()

    def ready(self):
        """(lines' shows, summaries, keywords, scales), built on first use. Summaries and
        keywords are those of shows at least REACH well known, one line a show, each as
        (text, where each line starts); scales are presence() for each family."""
        if self.index is None:
            with self.building:
                if self.index is None:
                    e = self.e
                    shows = [i for i, s in enumerate(e.shows) if s['recommendable'] and e.popularity[i] >= REACH]
                    summaries = lines([e.shows[i]['summary'] or '' for i in shows])
                    keywords = lines([' | '.join(e.shows[i]['keywords']) for i in shows], KEPT)
                    self.index = (array('I', shows), summaries, keywords, self.presence())
        return self.index

    def texts(self):
        return self.ready()[:3]

    def presence(self):
        """{family: for each show, what turns a value into how directly it carries a
        genre or subject}. A value is rarity x Wikidata's weight (1 for a show's own
        genre, a half for that genre's parent), scaled to unit length over the family, so
        a show with several rare genres holds each at less than one with only one;
        divided by its rarity and by the show's largest such quotient, a value becomes
        the weight again, the same for every show that has the genre as its own. Each
        show keeps one over its largest."""
        f = self.e.facets
        scales = {}
        for name in set(self.family.values()):
            start, end = f.family_ranges[f.families.index(name)]
            best = array('f', bytes(4 * self.e.n))
            for c in range(start, end):
                a, b, inverse = f.col_ptr[c], f.col_ptr[c + 1], 1.0 / self.rarity[c]
                for j, v in zip(f.post_rows[a:b], f.post_values[a:b]):
                    if v * inverse > best[j]:
                        best[j] = v * inverse
            scales[name] = array('f', (1.0 / x if x else 0.0 for x in best))
        return scales

    def carries(self, j, c, value, scales):
        """How directly show j carries genre or subject c, whose value in its row is value."""
        return value / self.rarity[c] * scales[self.family[c]][j]

    def phrase_hits(self, spellings, keywords=False, most=None):
        """The shows whose summary holds any of spellings (one phrase in its numbers) as
        whole words, or, with keywords, those with one among their keywords, as (show,
        whether it is a whole keyword). Past most shows, None: too common to say anything.

        The text is read once for the spellings' shared start, and each place it turns up
        is checked for one of their endings; a start of under four letters would turn up
        too often (mad in made), so such spellings are each looked for whole."""
        shows, summaries, words = self.texts()
        blob, starts = words if keywords else summaries
        stem = spellings[0][:min(map(len, spellings))]
        while not all(s.startswith(stem) for s in spellings):
            stem = stem[:-1]
        groups = ([(stem, [s[len(stem):] + b' ' for s in spellings])] if len(stem) >= 4
                  else [(s, [b' ']) for s in spellings])
        found, seen = [], set()
        for start, endings in groups:
            pattern = b' ' + start
            at = blob.find(pattern)
            while at >= 0:
                end = at + len(pattern)
                ending = next((x for x in endings if blob.startswith(x, end)), None)
                if ending is None:
                    at = blob.find(pattern, at + 1)
                    continue
                line = bisect_right(starts, at) - 1
                if keywords:
                    after = end + len(ending)
                    whole = (at == starts[line] or blob[at - 1:at] == b'|') and blob[after:after + 1] in (b'|', b'\n')
                    found.append((shows[line], whole))
                    at = blob.find(pattern, at + 1)
                    continue
                if line not in seen:
                    seen.add(line)
                    found.append(shows[line])
                    if most is not None and len(found) > most:
                        return None
                at = blob.find(pattern, starts[line + 1])
        return found

    # ---------------------------------------------------------------- a search

    def of(self, q, cards):
        """The related row for search q, whose title matches are cards (the answer's, best
        first): {'title', 'kind', 'shows': [index]} or None. kind is 'show' for More like
        one show, 'topic' for a Wikidata genre or subject, 'meaning' for anything else."""
        words = normalize([q])[0].split()
        if len(''.join(words)) < 3:
            return None
        key = (' '.join(q.split()), tuple(c['id'] for c in cards))
        with self.lock:
            if key in self.answers:
                self.answers.move_to_end(key)
                return self.answers[key]
        answer = self.work(q, words, cards)
        with self.lock:
            self.answers[key] = answer
            while len(self.answers) > CACHED:
                self.answers.popitem(last=False)
        return answer

    def work(self, q, words, cards):
        e = self.e
        mine = e.titles.find(q)
        matched = {e.by_id[c['id']] for c in cards if c['id'] in e.by_id}
        named = self.named(words, cards, mine)
        topics = self.topics(words)
        common = [c for c in topics if c not in self.proper]
        household = named and named[2] == 'exact' and e.popularity[named[0]] >= HOUSEHOLD
        if topics and not (named and (household or not common)):
            kind = 'topic'
        elif named:
            i, title, _how = named
            return {'title': f'More like {title}', 'kind': 'show', 'shows': self.more_like(i, matched)}
        elif mine.typing or len(''.join(words)) < MEANT:
            return None
        else:
            kind = 'meaning'
        shows = self.meaning(q, words, cards, topics, matched)
        if len(shows) < FEWEST:
            return None
        return {'title': f"Shows like {' '.join(q.split())}", 'kind': kind, 'shows': shows}

    def named(self, words, cards, mine):
        """(show, title, how) for the show a search names, or None; title is the one it
        was named by, the show's own or another of its titles."""
        e = self.e
        if not cards or cards[0]['id'] not in e.by_id:
            return None
        card = cards[0]
        i = e.by_id[card['id']]
        known = e.popularity[i]
        if len(words) > 1 and YEAR.fullmatch(words[-1]):
            words = words[:-1]
        asked = [w.encode() for w in words]
        query = set(forms(asked))
        best = None
        for title in dict.fromkeys(t for t in (card.get('aka'), card['name']) if t):
            spelled = [w.encode() for w in normalize([title])[0].split()]
            if not spelled:
                continue
            found = set()
            for form in forms(spelled):
                for typed in query:
                    if typed == form:
                        found.add('exact')
                    elif len(typed) >= 4 and form.startswith(typed):
                        found.add('start')
            if slipped(asked, spelled):
                found.add('slip')
            # The whole title and more besides, as in Demon Slayer: Kimetsu no Yaiba.
            if len(b''.join(spelled)) >= 6 and set(spelled) <= set(asked) and len(spelled) < len(asked):
                found.add('part')
            for how in found:
                rank = ('exact', 'slip', 'part', 'start').index(how)
                if best is None or rank < best[0]:
                    # The row is named by the title typed (Money Heist, not La Casa de
                    # Papel), but a title only begun is the show's own: zomb is the start
                    # of Z Nation, not of its Lithuanian title.
                    best = (rank, card['name'] if how == 'start' else title, how)
        if best is None and (not mine.hits or mine.hits[0][0] != i):
            # TVmaze's search put it first: it knows a title the catalogue does not.
            best = (4, card['name'], 'remote')
        if best is None or known < (TYPED if best[2] == 'start' else NAMED):
            return None
        return i, best[1], best[2]

    def topics(self, words):
        """The Wikidata genres and subjects a search names, in either number."""
        if not self.labels:
            return []
        asked = [w.encode() for w in words]
        found = []
        for said in (asked, asked[1:] if len(asked) > 1 and asked[0] in ARTICLES else None):
            for text in dict.fromkeys(b' '.join(said[:-1] + [last]) for last in numbers(said[-1])) if said else ():
                for c in self.labels.get(text.decode(), ()):
                    if c not in found and self.e.facets.df[c] >= 3:
                        found.append(c)
        return found

    # ---------------------------------------------------------------- More like

    def more_like(self, i, matched):
        """The title page's More like this for show i, before any list or settings are
        known, less the matched shows."""
        e, settings = self.e, self.settings
        show_id = e.shows[i]['id']
        near = e.blend(i, settings)
        pool = [j for j in self.pool if j != i and j not in matched]
        closest = sorted(pool, key=near.__getitem__, reverse=True)[:CLOSEST]
        scores = e.rank(closest, [{'id': show_id, 'weight': 1}], [], {show_id: near}, settings)
        ranked = sorted((j for j in closest if scores[j] > 0), key=lambda j: (-scores[j], e.shows[j]['id']))
        return ranked[:COUNT]

    # ---------------------------------------------------------------- meaning

    def phrases(self, q):
        """The search as phrases to look for in summaries and keywords, each in its
        numbers: as typed, and without a leading article. None when it is only little words."""
        folded = fold([q])[0].split()
        if not folded or all(w in STOP for w in folded):
            return []
        out = []
        for words in (folded, folded[1:] if len(folded) > 1 and folded[0] in ARTICLES else None):
            if words:
                out.append(list(dict.fromkeys(b' '.join(words[:-1] + [last]) for last in numbers(words[-1]))))
        return out

    def evidence(self, q, words, cards, topics):
        """{show: evidence}, anchors for the profile and candidates for the row."""
        e = self.e
        found = {}
        f = e.facets
        labelled = set()
        for c in topics:
            labelled.update(f.post_rows[p] for p in range(f.col_ptr[c], f.col_ptr[c + 1]))
        for j in labelled:
            found[j] = LABEL
        said, keyed = set(), {}
        common = COMMON * len(self.texts()[0])
        for phrase in self.phrases(q):
            for j, whole in self.phrase_hits(phrase, keywords=True):
                keyed[j] = max(keyed.get(j, 0.0), KEYWORD if whole else KEYWORD_PART)
            said.update(self.phrase_hits(phrase, most=common) or ())
        for j, value in keyed.items():
            found[j] = found.get(j, 0.0) + value
        for j in said:
            found[j] = found.get(j, 0.0) + PHRASE
        asked = {w for w in words if w.encode() not in STOP}
        for card in cards:
            j = e.by_id.get(card['id'])
            titles = [normalize([t])[0].split() for t in (card['name'], card.get('aka')) if t]
            if j is not None and asked and any(asked <= set(t) for t in titles):
                found[j] = found.get(j, 0.0) + TITLE
        return found

    def profile(self, anchors):
        """The genres and subjects the anchors lean toward, each weighed by how directly
        and how many of the anchors carry it and by how rare it is, as a unit vector:
        {column: weight}."""
        f = self.e.facets
        if not f or not anchors:
            return {}
        scales = self.ready()[3]
        # Every anchor counts toward the shares, labelled or not: where most anchors carry
        # no Wikidata genre (boxing's are mostly fight nights), the one romance among them
        # says nothing about boxing.
        weight, share, total = {}, {}, sum(w for _j, w in anchors)
        for j, w in anchors:
            for c, v in f.row(j):
                if c not in self.family or c in self.proper:
                    continue
                weight[c] = weight.get(c, 0.0) + w * self.carries(j, c, v, scales) * self.rarity[c] ** RARE
                share[c] = share.get(c, 0.0) + w
        kept = {c: x for c, x in weight.items()
                if share[c] >= LEAN * total and share[c] / total >= LIFT * self.base[c]}
        norm = math.sqrt(sum(x * x for x in kept.values())) or 1.0
        return {c: x / norm for c, x in kept.items()}

    def meaning(self, q, words, cards, topics, matched):
        """The row for a search by what it means: its shows, best first."""
        e = self.e
        found = self.evidence(q, words, cards, topics)
        if not found:
            return []
        known = e.popularity
        anchors = heapq.nlargest(ANCHORS, found.items(), key=lambda kv: (kv[1], known[kv[0]], -kv[0]))
        profile = self.profile(anchors)
        # Closeness to the profile: the part of it a show carries best, and a quarter of
        # the rest it carries, so what the profile is most about leads. Summed alone, a
        # show with Daybreak's three commoner genres would pass one that is only
        # post-apocalyptic.
        best, rest = {}, {}
        f, offered = e.facets, self.offered
        scales = self.ready()[3] if profile else None
        for c, x in profile.items():
            a, b, scale = f.col_ptr[c], f.col_ptr[c + 1], scales[self.family[c]]
            x /= self.rarity[c]
            for j, v in zip(f.post_rows[a:b], f.post_values[a:b]):
                if offered[j]:
                    part = x * v * scale[j]
                    if part > best.get(j, 0.0):
                        part, best[j] = best.get(j, 0.0), part
                    rest[j] = rest.get(j, 0.0) + part
        near = {j: x + FURTHER * rest[j] for j, x in best.items()}
        top = max(near.values(), default=0.0) or 1.0
        # How well each format fits: its share of the anchors, measured against the most
        # common one's.
        formats = {}
        for j, w in anchors:
            kind = e.shows[j]['type']
            formats[kind] = formats.get(kind, 0.0) + w
        most = max(formats.values())
        scores = {}
        for j in set(near) | {j for j in found if self.offered[j]}:
            if j in matched:
                continue
            fit = FIT + (1 - FIT) * formats.get(e.shows[j]['type'], 0.0) / most
            value = min(found.get(j, 0.0), MOST) + PROFILE * near.get(j, 0.0) / top
            scores[j] = (known[j] / 100) ** FAME * fit * value
        return heapq.nsmallest(COUNT, scores, key=lambda j: (-scores[j], e.shows[j]['id']))
