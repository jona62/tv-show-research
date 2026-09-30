"""A person's page: who someone in a show's cast is, and the shows they are in.

TVmaze gives the person, their name, photo and dates, with the shows they are a regular in
and those they helped make, and, asked separately, every episode they were a guest in. Each
show the catalogue holds carries its card, so it opens its own title page; the rest keep
their name and years.

TVmaze keeps no biographies. Wikidata links some people to their TVmaze id (P11449), but
only about seventeen thousand of them, so a person without that link is looked for by their
name and taken only when Wikidata's date of birth is TVmaze's to the day; two such people,
or none, and there is no biography rather than a guess. Their English Wikipedia article
gives the biography, its summary's opening paragraph, and Wikidata their place of birth,
their IMDb id and a short description. Wikidata and Wikipedia are asked for the person's
TVmaze id, name and date of birth, and nothing about whoever is looking.

Wikidata's query service takes from a fraction of a second to several, so a page asks for
the biography apart from the person, and the server starts the lookup as soon as TVmaze has
answered for them: asked for meanwhile, the biography waits on that lookup rather than
starting another. Answers are cached, and a source that cannot be reached rests a minute.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as Unfinished
import re
import threading
from urllib.parse import quote, unquote, urlencode

from live import LiveError, picture, whole

PERSON = '/people/{id}?embed%5B%5D=castcredits&embed%5B%5D=crewcredits'
GUESTS = '/people/{id}/guestcastcredits?embed=episode'
WIKIDATA = 'https://query.wikidata.org'
WIKIPEDIA = 'https://en.wikipedia.org'
SUMMARY = '/api/rest_v1/page/summary/{title}'
SHOW = re.compile(r'https?://api\.tvmaze\.com/shows/(\d{1,9})')
PAGE = re.compile(r'https://www\.tvmaze\.com/people/\d+(?:/[a-z0-9-]*)?')
DAY = re.compile(r'\d{4}-\d{2}-\d{2}')
ITEM = re.compile(r'https?://www\.wikidata\.org/entity/(Q\d+)')
ARTICLE = re.compile(r'https://en\.wikipedia\.org/wiki/([^\s?#]+)')
IMDB = re.compile(r'nm\d{7,9}')
# How much a regular part counts, on top of the show's popularity (0 to 100), and how much
# a guest part counts for each episode, up to ten: a little less than a regular one at most.
REGULAR, GUEST = 35, 3
# Popularity from here up is everybody's: some 1,200 shows, the top 1.4% of the catalogue.
KNOWN = 98
# Making a show is a bigger part in it than producing one.
MAKERS = ('Creator', 'Co-Creator', 'Developer', 'Showrunner')
# The most of each list a page carries.
MOST_ROLES, MOST_APPEARANCES, MOST_CREW = 200, 100, 60
# A biography runs to the end of the sentence before this many characters.
MOST_TEXT = 1500
# Seconds a source that could not be reached is left alone.
REST = 60


def day(value):
    return value if isinstance(value, str) and DAY.fullmatch(value) else None


def text(value, most=200):
    return ' '.join(value.split())[:most] if isinstance(value, str) else ''


def linked(credit, key):
    """What a credit links to under `key` (a show, an episode's show, a character) as its
    name, with a TVmaze id for a show; None without a name."""
    links = credit.get('_links') if isinstance(credit, dict) and isinstance(credit.get('_links'), dict) else {}
    link = links.get(key) if isinstance(links.get(key), dict) else {}
    name = text(link.get('name'))
    if not name:
        return None
    if key != 'show':
        return {'name': name}
    found = SHOW.fullmatch(link['href']) if isinstance(link.get('href'), str) else None
    return {'id': int(found[1]), 'name': name} if found else None


def trim_person(raw):
    """A person as TVmaze keeps them, with the shows they are a regular in (as whom, and
    whether as themselves or by voice alone) and the shows they helped make, and how."""
    if not isinstance(raw, dict) or not whole(raw.get('id')) or not text(raw.get('name')):
        raise ValueError('not a person')
    embedded = raw.get('_embedded') if isinstance(raw.get('_embedded'), dict) else {}
    cast, crew = [], []
    for credit in embedded.get('castcredits') or []:
        show = linked(credit, 'show')
        if show:
            character = linked(credit, 'character')
            cast.append({**show, 'as': character['name'] if character else '', 'self': credit.get('self') is True,
                         'voice': credit.get('voice') is True})
    for credit in embedded.get('crewcredits') or []:
        show = linked(credit, 'show')
        job = text(credit.get('type'), 60) if isinstance(credit, dict) else ''
        if show and job:
            crew.append({**show, 'job': job})
    country = raw.get('country') if isinstance(raw.get('country'), dict) else {}
    url = raw.get('url')
    return {
        'id': raw['id'], 'name': text(raw['name']), 'photo': picture(raw.get('image')),
        'birthday': day(raw.get('birthday')), 'deathday': day(raw.get('deathday')),
        'gender': text(raw.get('gender'), 30) or None, 'country': text(country.get('name')) or None,
        'url': url if isinstance(url, str) and PAGE.fullmatch(url) else f'https://www.tvmaze.com/people/{raw["id"]}',
        'cast': cast[:500], 'crew': crew[:500],
    }


def trim_guests(raw):
    """The shows someone was a guest in, from TVmaze's episode credits: for each, how many
    episodes, the years they aired, whom they played most, and whether every one of them
    was as themselves or by voice alone."""
    if not isinstance(raw, list):
        raise ValueError('not a list of guest credits')
    shows = {}
    for credit in raw[:5000]:
        embedded = credit.get('_embedded') if isinstance(credit, dict) and isinstance(credit.get('_embedded'), dict) else {}
        episode = embedded.get('episode')
        show = linked(episode, 'show') if isinstance(episode, dict) else None
        if not show:
            continue
        s = shows.setdefault(show['id'], {**show, 'episodes': 0, 'years': [], 'as': Counter(), 'self': 0, 'voice': 0})
        s['episodes'] += 1
        aired = day(episode.get('airdate'))
        if aired:
            s['years'].append(int(aired[:4]))
        if credit.get('self') is True:
            s['self'] += 1
        else:
            character = linked(credit, 'character')
            if character:
                s['as'][character['name']] += 1
        s['voice'] += credit.get('voice') is True
    return [{'id': s['id'], 'name': s['name'], 'episodes': s['episodes'],
             'years': [min(s['years']), max(s['years'])] if s['years'] else [],
             'as': ', '.join(name for name, _n in s['as'].most_common(2)),
             'self': s['self'] == s['episodes'], 'voice': s['voice'] == s['episodes']} for s in shows.values()]


def public(person):
    """What a page shows of a person, without the credits it has sorted apart."""
    return {key: person[key] for key in ('id', 'name', 'photo', 'birthday', 'deathday', 'gender', 'country', 'url')}


def credits(library, person, guests):
    """What someone is in, in three lists, each best known first: their roles (every show
    they are a regular in, as themselves too, since a host's own show is what they are known
    for, and every one they were a guest in as someone else), their appearances as
    themselves, and the shows they helped make.

    How well known a part is: the show's popularity in the catalogue (TVmaze's, 0 to 100),
    REGULAR more for a regular part and GUEST more for each episode of a guest one, up to
    ten, so a lead in a show few know follows a recurring part in one everybody does.
    Popularity runs out at the top, where a point is noise (The Gentlemen is 100, Breaking
    Bad 99), so from KNOWN up every show counts the same and ties go to the better rated
    (Breaking Bad before Westworld), then to the latest. A show the catalogue holds
    carries its card and years; the rest keep their name, and a guest part the years its
    episodes aired."""
    e = library.e

    def shown(show_id, name, when=None):
        """A show as a credit, with its popularity and rating: none for one the catalogue lacks."""
        i = e.by_id.get(show_id)
        if i is None:
            return {'id': show_id, 'name': name, 'show': None, 'years': when or []}, 0, 0
        s = e.shows[i]
        run = [s['year'], library.ended[i] or None] if s['year'] else []
        return ({'id': show_id, 'name': s['name'], 'show': library.card(i), 'years': when or run},
                min(e.popularity[i], KNOWN), s['rating'] or 0)

    def ordered(found, most):
        latest = lambda credit: max((y for y in credit['years'] if y), default=0)
        found.sort(key=lambda f: (-f[1], -f[2], -latest(f[0]), f[0]['name']))
        return [credit for credit, _score, _rating in found[:most]]

    roles, appearances, crew, regular = [], [], [], set()
    for c in person['cast']:
        if c['id'] in regular:
            continue
        regular.add(c['id'])
        credit, known, rating = shown(c['id'], c['name'])
        roles.append(({**credit, 'as': '' if c['self'] else c['as'], 'regular': True, 'episodes': None,
                       'self': c['self'], 'voice': c['voice']}, known + REGULAR, rating))
    for g in guests:
        if g['id'] in regular:
            continue
        credit, known, rating = shown(g['id'], g['name'], g['years'])
        found = {**credit, 'as': g['as'], 'regular': False, 'episodes': g['episodes'], 'self': g['self'],
                 'voice': g['voice']}
        (appearances if g['self'] else roles).append((found, known + GUEST * min(g['episodes'], 10), rating))
    jobs = {}
    for c in person['crew']:
        held = jobs.setdefault(c['id'], {'name': c['name'], 'jobs': []})
        if c['job'] not in held['jobs']:
            held['jobs'].append(c['job'])
    for show_id, held in jobs.items():
        credit, known, rating = shown(show_id, held['name'])
        made = sorted(held['jobs'], key=lambda job: MAKERS.index(job) if job in MAKERS else len(MAKERS))
        crew.append(({**credit, 'jobs': made}, known + (REGULAR if made[0] in MAKERS else 0), rating))
    return {'roles': ordered(roles, MOST_ROLES), 'appearances': ordered(appearances, MOST_APPEARANCES),
            'crew': ordered(crew, MOST_CREW)}


# ------------------------------------------------------------------ Wikidata and Wikipedia

def wikidata_path(person):
    """The query that finds a person on Wikidata, as a path on its query service: by the
    TVmaze id Wikidata keeps for them, and by their name, as a label or an alias in English
    or in every language, with a date of birth that is TVmaze's to the day. With them come
    their English Wikipedia article, IMDb id and description, and their place of birth with
    the region and country it lies in."""
    name = re.sub(r'["\\\x00-\x1f\x7f]', '', person['name']).strip()
    by_name = ''
    if person['birthday'] and name:
        by_name = f'''UNION {{
    VALUES ?name {{ "{name}"@en "{name}"@mul }}
    ?item rdfs:label|skos:altLabel ?name ; p:P569/psv:P569 ?born .
    ?born wikibase:timeValue "{person['birthday']}T00:00:00Z"^^xsd:dateTime ; wikibase:timePrecision 11 .
    BIND("name" AS ?by)
  }}'''
    query = f'''SELECT DISTINCT ?item ?by ?article ?imdb ?about ?placeLabel ?regionLabel ?countryLabel WHERE {{
  {{ ?item wdt:P11449 "{person['id']}" . BIND("id" AS ?by) }}
  {by_name}
  OPTIONAL {{ ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }}
  OPTIONAL {{ ?item wdt:P345 ?imdb . }}
  OPTIONAL {{ ?item schema:description ?about . FILTER(LANG(?about) = "en") }}
  OPTIONAL {{
    ?item wdt:P19 ?place .
    OPTIONAL {{ ?place wdt:P17 ?country . }}
    OPTIONAL {{ ?place wdt:P131/wdt:P131?/wdt:P131?/wdt:P131? ?region . ?region wdt:P31/wdt:P279? wd:Q10864048 . }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en,mul". }}
}} LIMIT 200'''
    return '/sparql?' + urlencode({'query': query, 'format': 'json'})


def label(value):
    """A label, unless Wikidata had none and gave the item's id in its place."""
    value = text(value)
    return '' if re.fullmatch(r'Q\d+', value) else value


def initials(name):
    return ''.join(word[0] for word in name.split() if word[:1].isupper())


def within(small, large):
    """Whether one name is in another as whole words: York in New York, not in Yorkshire."""
    return re.search(rf'(?<!\w){re.escape(small)}(?!\w)', large) is not None


def birthplace(place, region, country):
    """"Hollywood, California, United States": a place of birth, then the region and the
    country it lies in, less whatever an earlier part already says (Santiago, Chile, not
    Santiago, Santiago Metropolitan Region, Chile; Washington, D.C. is in the District of
    Columbia already)."""
    parts = []
    for part in (label(place), label(region), label(country)):
        folded = part.casefold()
        said = [p.casefold() for p in parts]
        if not part or any(within(folded, p) or within(p.split(',')[0], folded) for p in said):
            continue
        if len(initials(part)) > 1 and any(initials(part) in p.replace('.', '').upper().split() for p in parts):
            continue
        parts.append(part)
    return ', '.join(parts)


FIELDS = ('item', 'by', 'article', 'imdb', 'about', 'placeLabel', 'regionLabel', 'countryLabel')


def bound(row, key):
    """A SPARQL answer's value for `key` in one row, as text."""
    cell = row.get(key) if isinstance(row, dict) else None
    value = cell.get('value') if isinstance(cell, dict) else None
    return value if isinstance(value, str) else ''


def trim_wikidata(raw):
    """The one Wikidata item a query found, or None: the item linked to the TVmaze id, or
    else the only one with the name and the date of birth. Two linked to the same id, unless
    only one of them also has the name and date, or two people of the same name born the
    same day, are no answer at all."""
    results = raw.get('results') if isinstance(raw, dict) else None
    rows = results.get('bindings') if isinstance(results, dict) else None
    if not isinstance(rows, list):
        raise ValueError('not a SPARQL answer')
    items = {}
    for row in rows:
        values = {key: bound(row, key) for key in FIELDS}
        item = ITEM.fullmatch(values['item'])
        if item:
            items.setdefault(item[1], []).append(values)
    linked_to = [q for q, found in items.items() if any(r['by'] == 'id' for r in found)]
    named = [q for q, found in items.items() if any(r['by'] == 'name' for r in found)]
    if len(linked_to) > 1:
        linked_to = [q for q in linked_to if q in named]
    chosen = linked_to or named
    if len(chosen) != 1:
        return None
    found = items[chosen[0]]

    def first(key, test=bool):
        return next((r[key] for r in found if r[key] and test(r[key])), '')

    article = ARTICLE.fullmatch(first('article', ARTICLE.fullmatch))
    return {'item': chosen[0], 'article': unquote(article[1]) if article else None,
            'imdb': first('imdb', IMDB.fullmatch) or None, 'about': text(first('about'), 250),
            'birthplace': birthplace(first('placeLabel', label), first('regionLabel', label), first('countryLabel', label))}


def cut(value, most=MOST_TEXT):
    """Plain text at most `most` characters long, cut after a sentence where one ends past
    half way, otherwise between words."""
    value = ' '.join(value.split())
    if len(value) <= most:
        return value
    head = value[:most]
    stop = max(head.rfind('. '), head.rfind('! '), head.rfind('? '))
    return head[:stop + 1] if stop > most // 2 else head.rsplit(' ', 1)[0] + '…'


def trim_summary(raw):
    """A Wikipedia article's summary: the opening paragraph as plain text, the short
    description, the article's address and the Wikidata item it is about. A page that is
    not an article (a disambiguation page, a list) has none."""
    if not isinstance(raw, dict):
        raise ValueError('not a page summary')
    if raw.get('type') != 'standard' or not text(raw.get('extract')):
        return None
    urls = raw.get('content_urls') if isinstance(raw.get('content_urls'), dict) else {}
    desktop = urls.get('desktop') if isinstance(urls.get('desktop'), dict) else {}
    page = desktop.get('page') if isinstance(desktop.get('page'), str) else ''
    return {'text': cut(raw['extract']), 'description': text(raw.get('description'), 250),
            'url': page if ARTICLE.fullmatch(page) else None,
            'item': raw.get('wikibase_item') if isinstance(raw.get('wikibase_item'), str) else None}


class Biographies:
    """Biographies of TVmaze people, from Wikidata and Wikipedia, each looked up once at a
    time: asked for while a lookup for the same person is under way, one waits for it."""

    def __init__(self, wikidata, wikipedia, workers=4):
        self.wikidata, self.wikipedia = wikidata, wikipedia
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='biography')
        self.pending = {}
        self.lock = threading.Lock()

    def start(self, person):
        """The lookup for a person, begun unless it is under way already."""
        with self.lock:
            future = self.pending.get(person['id'])
            fresh = future is None
            if fresh:
                future = self.pending[person['id']] = self.pool.submit(self.lookup, person)
        if fresh:
            future.add_done_callback(lambda done: self._forget(person['id'], done))
        return future

    def _forget(self, key, done):
        with self.lock:
            if self.pending.get(key) is done:
                del self.pending[key]

    def get(self, person, wait=15.0):
        """A person's biography, or None when they have none. A lookup that fails raises
        LiveError, and so does one still going after `wait` seconds, whose answer the next
        ask then finds cached."""
        try:
            return self.start(person).result(timeout=wait)
        except Unfinished:
            raise LiveError('That service is busy. Details will be back in a moment.', 503) from None

    def ask(self, source, path, trim, missing=None):
        """An answer from Wikidata or Wikipedia. One that cannot be reached is left alone for
        REST seconds, so a page does not wait on it again and again meanwhile."""
        try:
            return source.get(path, trim, missing)
        except LiveError as exc:
            if exc.status == 502:
                with source.lock:
                    source.pause = max(source.pause, source.clock() + REST)
            raise

    def lookup(self, person):
        """What Wikidata and Wikipedia say about a person, or None when Wikidata has no one
        who is surely them: the biography from their English Wikipedia article, which must be
        about the same Wikidata item, its short description or else Wikidata's, their place of
        birth and their IMDb id. Wikipedia out of reach leaves the rest."""
        found = self.ask(self.wikidata, wikidata_path(person), trim_wikidata)
        if not found:
            return None
        summary = None
        if found['article']:
            try:
                summary = self.ask(self.wikipedia, SUMMARY.format(title=quote(found['article'], safe='')),
                                   trim_summary, missing=False)
            except LiveError:
                summary = None
        own = summary if summary and summary['item'] == found['item'] else None
        return {'text': own['text'] if own else '', 'description': (own and own['description']) or found['about'],
                'wikipedia': own['url'] if own else None, 'imdb': found['imdb'], 'birthplace': found['birthplace'],
                'wikidata': found['item']}
