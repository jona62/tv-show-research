"""Shows TVmaze added since the catalogue was built, which search finds on every query.

The catalogue is rebuilt each night and TVmaze adds some 30 shows a day. Search asks
TVmaze's own search only when the catalogue's match is weak (fallback.py), so a new show
named like an older one was never offered: a reboot or a revival, such as HBO Max's
The Howard Stern Show of 2026 beside the 1992 one. So the server keeps the shows TVmaze
lists past the newest the catalogue holds (Added). About every hour it reads TVmaze's
updates list, a day of it (a week on starting, and a week or a month after a longer
gap), and asks for each new show once through the client title pages use, its cache and
its rate window, so the title page a search then opens costs TVmaze nothing more. That
is some 24 calls a day for the list and one for each of the 30 or so new shows; a
restart reads the list again and asks again for the shows the catalogue still lacks.

Search matches them on every query at no cost to TVmaze (join), as the catalogue's first
three tiers do (titles.py) and on its reading of titles: the whole title, its start, or
every word starting one of its words, with a year ending a search picking the show of
that year. They join the answer's missing shows, ahead of those TVmaze's search named,
and come ahead of the catalogue's matches when one matches better than the catalogue's
best match does, or the search names both whole and the new one is premiering or airing
now: howard stern show leads with the 2026 show and has the 1992 one beside it.

At most MOST shows are kept, the newest, about a month of TVmaze's additions, and only
those a title page opens (server.newer). The next nightly build holds them all, so the
list starts again from nothing as the catalogue takes them in.
"""
from datetime import date, datetime, timedelta, timezone
import sys
import threading
import time

from live import LiveError
from titles import YEAR, forms, normalize

UPDATES = '/updates/shows?since={window}'
MOST = 1000             # shows kept: about a month of TVmaze's additions
NAMED = 3               # just-added shows a search names, as many as fallback.py names
SHORTEST = 3            # characters a search needs before a title's start or words count
MOST_WORDS = 16         # words of a search that count, as titles.py reads them
EVERY = 3600            # seconds between reads of the updates list, which TVmaze caches an hour
RETRY = 300             # seconds before trying again when TVmaze could not be asked
GAP = 2.0               # seconds between shows asked for: 5 at most of title pages' 12 calls in 10 seconds
# How long since the last list read a day of it still reaches back far enough, with room for
# TVmaze's hour of caching and a late round, and a week of it.
DAY, WEEK = 20 * 3600, 6 * 86400
# A show premiering or airing now: running, or premiering from 60 days before today to 30 after.
BEFORE, AFTER = timedelta(days=60), timedelta(days=30)


def read(text):
    """A title's or a search's words as titles.py reads them, as bytes."""
    return [w.encode() for w in normalize([(text or '').replace('\n', ' ')])[0].split()[:MOST_WORDS]]


def tier(title, shapes, words, wanted):
    """How a title matches a search, as titles.py's first three tiers count: 0 the whole
    title, with or without a leading article and with numbers as words or digits, 1 its
    start, 2 every word of the search starting one of its words; None otherwise. shapes
    and wanted are titles.forms of the title's words and the search's. A search shorter
    than SHORTEST matches a whole title only."""
    if not words or not title:
        return None
    if any(f in shapes for f in wanted):
        return 0
    if len(b''.join(words)) < SHORTEST:
        return None
    typed = [f for f, kind in wanted.items() if kind in (0, 2)]
    if any(s.startswith(f) for s in shapes for f in typed):
        return 1
    if all(any(w.startswith(t) for w in title) for t in words):
        return 2
    return None


class Search:
    """A search read once for every title it is matched against: its words, and, when a
    year ends it, its words without the year and the year, which may be part of a title
    (Space: 1999) or pick one of several shows of a name (Doctor Who 2005)."""

    def __init__(self, q):
        self.words = read(q)
        self.wanted = forms(self.words) if self.words else {}
        self.year = int(self.words[-1]) if len(self.words) > 1 and YEAR.fullmatch(self.words[-1].decode()) else None
        self.rest = self.words[:-1] if self.year else []
        self.rest_wanted = forms(self.rest) if self.rest else {}

    def key(self, title, shapes, year):
        """How well a show of these title words and premiere year matches, best first, as
        (tier, whether it misses the year the search ends with), or None."""
        found = tier(title, shapes, self.words, self.wanted)
        best = None if found is None else (found, False)
        if self.year:
            rest = tier(title, shapes, self.rest, self.rest_wanted)
            if rest is not None and (best is None or (rest, year != self.year) < best):
                best = (rest, year != self.year)
        return best


def current(show, today):
    """Whether a show is premiering or airing about now."""
    if show['status'] == 'Running':
        return True
    if not show['premiered']:
        return False
    return today - BEFORE <= date.fromisoformat(show['premiered']) <= today + AFTER


def trim_updates(raw):
    """TVmaze's updates list as {show id: when it last changed, in seconds}."""
    if not isinstance(raw, dict):
        raise ValueError('not an updates list')
    return {int(k): v for k, v in raw.items() if isinstance(k, str) and k.isdigit() and type(v) is int}


class Added:
    """The shows TVmaze lists past the catalogue's newest, kept for search (see above)."""

    def __init__(self, live, newest, reach, most=MOST, gap=GAP, clock=time.time, sleep=time.sleep):
        """live is the TVmaze client title pages use (live.Live), newest the newest show id
        the catalogue holds, and reach how far past it a title page opens."""
        self.live, self.newest, self.reach, self.most = live, newest, reach, most
        self.gap, self.clock, self.sleep = gap, clock, sleep
        self.lock = threading.Lock()
        self.shows = {}         # id: (show, its title's words, their compact forms)
        self.waiting = set()    # ids an updates list named that are still to be asked for
        self.gone = set()       # ids TVmaze has no show for
        self.seen = None        # the latest change an updates list held, in seconds

    def window(self):
        """The updates list that reaches back to the last one read, by when its latest
        change was: a day of it, a week or a month. The first is a week of it: the catalogue
        is a night old, and a show the index its build read lacked may be a day or two older,
        while a catalogue a failing refresher left weeks behind would have hundreds of shows
        asked for again on every restart. Those older ones TVmaze's search still finds."""
        if self.seen is None:
            return 'week'
        gap = self.clock() - self.seen
        return 'day' if gap < DAY else 'week' if gap < WEEK else 'month'

    def refresh(self):
        """One round: the updates list, then, newest first and GAP apart, each show it names
        past the catalogue's newest and within reach that is not yet known, until MOST
        are kept, the newest. Returns how many shows it kept, or None when the list could
        not be had. TVmaze busy or out of reach ends the round, and the shows still to ask
        about wait for the next."""
        try:
            changed = self.live.get(UPDATES.format(window=self.window()), trim_updates, ttl=0)
        except LiveError:
            return None
        if changed:
            self.seen = max(self.seen or 0, max(changed.values()))
        last = self.newest + self.reach
        with self.lock:
            self.waiting.update(i for i in changed if self.newest < i <= last and i not in self.shows
                                and i not in self.gone)
        kept, asked = 0, False
        while True:
            with self.lock:
                if not self.waiting:
                    break
                show_id = max(self.waiting)
                if len(self.shows) >= self.most and show_id < min(self.shows):
                    self.waiting.clear()
                    break
            if asked:
                self.sleep(self.gap)
            asked = True
            try:
                about = self.live.show(show_id)['about']
            except LiveError as exc:
                if exc.status != 404:
                    break
                about = None
            with self.lock:
                self.waiting.discard(show_id)
                if not about:
                    self.gone.add(show_id)
                    continue
                words = read(about['name'])
                self.shows[show_id] = ({key: about[key] for key in ('id', 'name', 'year', 'url', 'poster', 'premiered',
                                                                     'status', 'known')}, words, forms(words))
                while len(self.shows) > self.most:
                    del self.shows[min(self.shows)]
            kept += 1
        return kept

    def run(self, every=EVERY, retry=RETRY):
        """Keeps the list for as long as the server runs: a round at once, then one every
        hour, or after RETRY seconds when TVmaze could not be asked."""
        while True:
            try:
                done = self.refresh()
            except Exception as exc:  # noqa: BLE001 - a round that fails must not end the thread
                print(f'Just-added shows: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
                done = None
            self.sleep(every if done is not None else retry)

    def join(self, found, q, today=None):
        """A search's answer (fallback.answer's) with the just-added shows q matches: ahead
        of the missing shows TVmaze's search named, NAMED in all, and ahead of the
        catalogue's matches (missing_first) when the best of them matches q better than
        the catalogue's best match does, or is named by q whole as that match is and is
        premiering or airing now. A tie of the start or the words of two titles, as for
        the, leaves the catalogue's matches first."""
        search = Search(q)
        with self.lock:
            kept = list(self.shows.values())
        if not search.words or not kept:
            return found
        today = today or datetime.now(timezone.utc).date()
        hits = []
        for show, words, shapes in kept:
            key = search.key(words, shapes, show['year'])
            if key is not None:
                hits.append((key, not current(show, today), -show['known'], -show['id'], show))
        if not hits:
            return found
        hits.sort(key=lambda hit: hit[:4])
        named = [{key: show[key] for key in ('id', 'name', 'year', 'url', 'poster')} for *_rank, show in hits]
        ids = {show['id'] for show in named}
        found['missing'] = (named + [m for m in found['missing'] if m['id'] not in ids])[:NAMED]
        theirs = None
        if found['shows']:
            top = found['shows'][0]
            for name in (top['name'], top.get('aka')):
                words = read(name) if name else []
                key = search.key(words, forms(words), top.get('year')) if words else None
                if key is not None and (theirs is None or key < theirs):
                    theirs = key
        best, later = hits[0][:2]
        if theirs is None or best < theirs or (best == theirs == (0, False) and not later):
            found['missing_first'] = True
        return found
