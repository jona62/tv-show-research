"""Check how titles are read and matched (titles.py) and the TVmaze fallback
(fallback.py), over a small made-up catalogue and a fake TVmaze.

Run from the repository root:  .venv/bin/python app/tests/test_search.py
Nothing here reaches TVmaze: the fallback is driven by fakes, one of them a local HTTP
server standing in for api.tvmaze.com. The real catalogue's search is checked by
test_engine.py and, over HTTP with aliases, by test_server.py.
"""
from array import array
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
import atexit
import contextlib
import gzip
import io
import json
import shutil
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'app'))

from backend.recommendation import titles                                                     # noqa: E402
from backend.recommendation.titles import Titles, normalize, numbered, edits, load_aliases  # noqa: E402
from backend.fallback import Remote, answer, trim                         # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def words(text):
    return normalize([text])[0]


# 1. Titles and queries are read the same way.
check('case and accents go', words('Pokémon ÉLITE') == 'pokemon elite')
check('an apostrophe joins its word', words("Grey's Anatomy") == 'greys anatomy' and words('Grey’s') == 'greys')
check('an elided article splits off', words("L'Amica geniale") == 'l amica geniale' and words("qu'il") == 'qu il')
check('& reads as and', words('Law & Order: SVU') == 'law and order svu' and words('Rizzoli ＆ Isles') == 'rizzoli and isles')
check('punctuation separates words', words('Spider-Man') == 'spider man' and words('9-1-1') == '9 1 1'
      and words('Marvel’s Agents of S.H.I.E.L.D.') == 'marvels agents of s h i e l d')
check('full-width and styled letters fold to plain ones', words('ＮＣＩＳ') == 'ncis' and words('𝕏-Files') == 'x files')
check('spaces collapse and the ends are trimmed', words('  The   Office  ') == 'the office')
check('underscores and odd spacing separate words', words('the_office\tus') == 'the office us')
check('scripts keep their letters', words('進撃の巨人') == '進撃の巨人' and words('Атака титанов') == 'атака титанов')
check('vowel signs stay inside their word', words('हिन्दी फ़िल्म').split()[0] == words('हिन्दी'))
check('one call reads many texts', normalize(['A-Team', 'B & B']) == ['a team', 'b and b'])
check('number words become digits', numbered(b'brooklyn nine nine'.split()) == [b'brooklyn', b'9', b'9']
      and numbered(b'twenty one pilots'.split()) == [b'21', b'pilots']
      and numbered(b'ninety day fiance'.split()) == [b'90', b'day', b'fiance']
      and numbered(b'twenty twelve'.split()) == [b'20', b'12'])
slips = edits('thigns')
check('one slip covers a swap, a drop, a change and an extra letter',
      {'things', 'thins', 'thigs', 'thignss', 'xhigns'} <= slips and 'thigns' not in slips)
check('two letters that should be doubled count as one slip', 'succession' in edits('sucesion')
      and 'sucesion' in edits('succession'))


# 2. A made-up catalogue, where each tier can be seen on its own.
def show(id, name, year=2000, rating=None):
    return {'id': id, 'name': name, 'year': year, 'rating': rating}


SHOWS = [
    show(1, 'The Office', 2005, 8.5), show(2, 'The Office', 2001, 7.8), show(3, 'Office Hours'),
    show(4, 'Box Office Heroes'), show(5, 'SpongeBob SquarePants', 1999), show(6, 'Breaking Bad', 2008, 9.2),
    show(7, 'Breaking Bear', 2026), show(8, 'Stranger Things', 2016), show(9, 'Succession', 2018),
    show(10, 'The Wire', 2002), show(11, 'Law & Order: Special Victims Unit', 1999), show(12, 'Law & Order', 1990),
    show(13, 'Brooklyn Nine-Nine', 2013), show(14, '9-1-1', 2018), show(15, "Grey's Anatomy", 2005),
    show(16, 'Mr. Robot', 2015), show(17, 'Demon Slayer', 2019), show(18, 'La Casa de Papel', 2017),
    show(19, 'Attack on Titan', 2013), show(20, 'Doctor Who', 1963), show(21, 'Doctor Who', 2005),
    show(22, 'Space: 1999', 1975), show(23, 'Space', 2001), show(24, 'V', 2009), show(25, 'V', 1983),
    show(26, 'Ted', 2024), show(27, 'Ted Lasso', 2020), show(28, 'The Last of Us', 2023),
    show(29, 'The Last Kingdom', 2015), show(30, '13 Reasons Why', 2017), show(31, 'How I Met Your Mother', 2005),
    show(32, 'Bob Hearts Abishola', 2019), show(33, 'Popular Show', 2010, 9.9), show(34, 'Popular Show', 2012, 5.0),
    show(35, 'Popular Show', 2014, 5.0), show(36, '!!!', 2000), show(37, 'Shogun', 1980), show(38, 'Shōgun', 2024),
    show(39, 'Hi! My Mr. Right', 2023),
    show(81, 'Criminal Minds', 2005, 8.7), show(3032, 'Criminal Minds: Beyond Borders', 2016),
    show(1020, 'Criminal Minds: Suspect Behavior', 2011), show(50417, 'The Real Criminal Minds', 2019),
]
KNOWN = {1: 99, 2: 97, 3: 40, 4: 60, 5: 98, 6: 99, 7: 70, 8: 100, 9: 99, 10: 99, 11: 100, 12: 95, 13: 99, 14: 100,
         15: 100, 16: 99, 17: 98, 18: 99, 19: 98, 20: 99, 21: 100, 22: 80, 23: 50, 24: 99, 25: 98, 26: 99, 27: 100,
         28: 100, 29: 97, 30: 98, 31: 99, 32: 90, 33: 60, 34: 60, 35: 60, 36: 10, 37: 85, 38: 100, 39: 70,
         81: 99, 3032: 100, 1020: 95, 50417: 70}
ALIASES = {18: ['Money Heist', 'La casa de papel', 'LA CASA DE PAPEL', 'Haus des Geldes'],
           19: ['Shingeki no Kyojin', '進撃の巨人'], 11: ['Law & Order: SVU'], 6: ['Breaking Bad', 'Во все тяжкие'],
           3: ['The Office'], 23: ['The', 'La'], 999: ['Nowhere']}
popularity = array('B', [KNOWN[s['id']] for s in SHOWS])
index = Titles(SHOWS, popularity, ALIASES)
at = {s['id']: i for i, s in enumerate(SHOWS)}


def ids(q, n=None):
    return [SHOWS[i]['id'] for i, _aka in index.find(q).hits[:n]]


def aka(q):
    return [(SHOWS[i]['id'], also) for i, also in index.find(q).hits]


check('an exact title comes first, best known first', ids('the office', 2) == [1, 2])
check('a leading article is optional for an exact title', ids('office', 2) == [1, 2])
check('exact beats prefix beats words beats inside', ids('office') == [1, 2, 3, 4])
check('the prefix of a title as it is typed', ids('breaking b', 2) == [6, 7] and ids('the last of', 1) == [28])
check('prefixes ignore spacing', ids('sponge bob', 1) == [5] and ids('spongebob', 1) == [5] and ids('spongebob sq') == [5])
check('words match in any order', ids('us last') == [28])
check('a word inside another word matches after one that starts a word', ids('bob', 2) == [32, 5])
check('punctuation and spacing are forgiven', ids("greys anatomy") == [15] and ids('mr robot') == [16]
      and ids('grey s anatomy') == [15])
check('& and and are one', ids('law and order', 1) == [12] and ids('law & order special', 1) == [11])
check('numbers match as digits or words', ids('brooklyn 99') == [13] and ids('brooklyn nine nine') == [13]
      and ids('911', 1) == [14] and ids('nine one one', 1) == [14] and ids('thirteen reasons why') == [30])
check('typos are forgiven', ids('breaking bda', 1) == [6] and ids('stranger thigns') == [8]
      and ids('sucession') == [9] and ids('sucesion') == [9] and ids('the wirre', 1) == [10])
criminal_family = {81, 3032, 1020, 50417}
check('an exact title leads its more popular franchise matches', ids('Criminal Minds')[0] == 81
      and criminal_family <= set(ids('Criminal Minds')))
check('reversed title words and an extra conjunction retain the franchise',
      criminal_family <= set(ids('Minds Criminal')) and ids('Minds and Criminal')[0] == 81)
check('commas are separators and apostrophes are optional',
      ids('Criminal,Minds') == ids('Criminal Minds') == ids('Criminal, Minds')
      and ids('Grey’s Anatomy') == ids('Greys Anatomy') == ids("Grey's Anatomy"))
check('substrings and typo variants retain related titles', all(criminal_family <= set(ids(query))
      for query in ('riminal Mind', 'Crimnal Minds', 'Criminal Mnds', 'Criminal Midns')))
check('only a complete one-slip title is protected from remote partial matches',
      all(index.find(query).preferred == [(at[81], None)]
          for query in ('Crimnal Minds', 'Criminal Mnds', 'Criminal Midns'))
      and not index.find('riminal Mind').preferred and not index.find('Minds and Criminal').preferred
      and not index.find('Crimnal Minds 2005').preferred)
check('a slip in the word being typed', ids('stranger thign') == [8])
check('initials stand for words', ids('law and order svu', 1) == [11] and ids('himym') == [39, 31])
check('a title the letters happen to start does not hide the one they stand for', ids('himym')[1:] == [31])
check('a longer query still finds the title it holds', ids('demon slayer kimetsu no yaiba') == [17]
      and ids('stranger things season 4') == [8])
check('a trailing year picks the show of that year', ids('doctor who 1963', 1) == [20]
      and ids('doctor who 2005', 1) == [21] and ids('shogun 1980', 1) == [37] and ids('shogun 2024', 1) == [38])
check('a year that belongs to the title still counts', ids('space 1999', 2) == [22, 23])
check('a year nobody premiered in changes nothing', ids('doctor who 1999', 2) == [21, 20])
check('ties go to popularity, then rating, then year', ids('popular show') == [33, 35, 34])
check('a single character finds only that exact title', ids('v') == [24, 25] and ids('t') == [])
check('short titles are found exactly first', ids('ted', 2) == [26, 27])
check('nothing to search for finds nothing', ids('') == [] and ids('   ') == [] and ids('?!') == [])
check('a title of punctuation alone is still a show, found by nothing', 36 not in ids('!!!'))
check('each show comes back once', all(len(ids(q)) == len(set(ids(q))) for q in ('office', 'the', 'la casa', 'popular')))
check('a page holds twelve at most', len(Titles([show(i, f'Same {i}') for i in range(40)], array('B', [50] * 40)).find('same').hits) == 12)

check('another title finds its show, saying which title matched', aka('money heist') == [(18, 'Money Heist')]
      and aka('shingeki no kyojin') == [(19, 'Shingeki no Kyojin')] and aka('進撃の巨人') == [(19, '進撃の巨人')])
check('another title matches by prefix and in any script', aka('haus des') == [(18, 'Haus des Geldes')]
      and aka('進撃') == [(19, '進撃の巨人')] and aka('во все') == [(6, 'Во все тяжкие')])
check('a show found by its own name carries no aka', aka('la casa de papel')[0] == (18, None)
      and aka('breaking bad')[0] == (6, None))
check('an alias shared with another show\'s name ranks by popularity', ids('the office', 3) == [1, 2, 3]
      and aka('the office')[2] == (3, 'The Office'))
check('titles that read the same as the name are kept once', index.n == len(SHOWS) + 7)
check('typos reach other titles too', aka('mony heist')[:1] == [(18, 'Money Heist')])
check('an alias for a show not in the catalogue is ignored', ids('nowhere') == [])
check('an other title that is only an article is no title', 23 not in ids('the') and 23 not in ids('la'))
strong = lambda q: index.find(q).strong
check('exact, prefix and word matches answer a search by themselves',
      strong('office') and strong('breaking b') and strong('us last') and strong('v'))
check('guesses do not', not strong('sucession') and not strong('demon slayer kimetsu no yaiba')
      and not strong('bob hearts abishola netflix') and not strong('zzzqqq'))
typing = lambda q: index.find(q).typing
check('a last word too short, or the start of a longer one, is still being typed',
      typing('breaking b') and typing('the la') and typing('the las') and typing('demon slayer kimetsu no ya'))
check('a whole word, or one no title starts with, is finished',
      not typing('the last') and not typing('sucession') and not typing('the office') and not typing('zzzqqq'))

# 3. Other titles, as the model carries them.
TMP = Path(tempfile.mkdtemp(prefix='titles-test-'))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)


def aliases_from(content, raw=False):
    path = TMP / 'search.json.gz'
    if raw:
        path.write_bytes(content)
    else:
        with gzip.open(path, 'wt', encoding='utf-8') as f:
            json.dump(content, f, ensure_ascii=False)
    said = io.StringIO()
    with contextlib.redirect_stderr(said):
        found = load_aliases(path)
    return found, said.getvalue()


found, said = aliases_from({'version': 1, 'aliases': {
    '18': ['Money Heist', 'Money\nHeist', 7, None, '', 'x' * 151], '19': 'not a list', 'abc': ['x'], '-3': ['y'],
    '20': [f'Title {k}' for k in range(150)]}})
check('aliases load, keyed by show id', found[18] == ['Money Heist', 'Money Heist'] and 19 not in found and said == '')
check('odd entries are dropped, not trusted', set(found) == {18, 20})
check('a show keeps at most a hundred other titles', len(found[20]) == titles.MOST_ALIASES)
check('no file means no aliases, quietly', load_aliases(TMP / 'nothing.json.gz') == {})
for label, content, raw in [('not gzip', b'plain', True), ('broken JSON', gzip.compress(b'{"version": 1'), True),
                            ('another version', {'version': 2, 'aliases': {}}, False),
                            ('no map of aliases', {'version': 1, 'aliases': []}, False)]:
    found, said = aliases_from(content, raw)
    check(f'a file that is {label} means no aliases, and says so', found == {} and said.startswith('Ignoring'), said)


# 4. The TVmaze fallback, with a fake TVmaze.
def result(id, name, premiered=None, url=None, image=None):
    return {'score': 0.9, 'show': {'id': id, 'name': name, 'premiered': premiered,
                                   'url': url or f'https://www.tvmaze.com/shows/{id}/x', 'image': image}}


POSTER = 'https://static.tvmaze.com/uploads/images/medium_portrait/190/475439.jpg'
check('TVmaze answers are trimmed to what the page shows', trim([
    result(9, 'Succession', '2018-06-03', image={'medium': POSTER, 'original': POSTER.replace('medium_portrait', 'original_untouched')}),
    result(77, ' New  Show ', None, 'javascript:alert(1)', {'medium': 'https://evil.example/x.jpg'}),
    {'show': {'id': '5', 'name': 'x'}}, {'show': {'id': 6}}, 'junk', result(8, '', '2020-01-01')]) == [
    {'id': 9, 'name': 'Succession', 'year': 2018, 'url': 'https://www.tvmaze.com/shows/9/x', 'poster': POSTER},
    {'id': 77, 'name': 'New Show', 'year': None, 'url': 'https://www.tvmaze.com/shows/77', 'poster': None}])
try:
    trim({'not': 'a list'})
    check('an answer that is not a list is refused', False)
except ValueError:
    check('an answer that is not a list is refused', True)

now = [0.0]
asked = []


def fake(path):
    asked.append(path)
    return [result(9, 'Succession', '2018-06-03'), result(424242, 'Brand New Show', '2026-09-26')]


remote = Remote(fetch=fake, calls=2, period=10, ttl=60, clock=lambda: now[0])
first = remote.search('Sucession')
check('a search is asked of TVmaze, folded and escaped', asked == ['/search/shows?q=sucession'] and first[0]['id'] == 9)
remote.search('  SUCESSION ')
check('the same search again is answered from the cache', len(asked) == 1)
remote.search('b')
check('a second search goes out', len(asked) == 2)
check('calls stay inside their window', remote.search('c') is None and len(asked) == 2)
now[0] = 11.0
check('the window moves on', remote.search('c') is not None and len(asked) == 3)
now[0] = 100.0


def failing(error):
    def fetch(path):
        asked.append(path)
        raise error
    return fetch


for label, error in [('a server error', HTTPError('u', 500, 'boom', {}, None)), ('no connection', URLError('down')),
                     ('a timeout', TimeoutError()), ('a broken answer', ValueError('bad json'))]:
    broken = Remote(fetch=failing(error), clock=lambda: now[0])
    check(f'{label} is no answer, not an error', broken.search('anything') is None)
remote.fetch = failing(HTTPError('u', 500, 'boom', {}, None))
check('a stale answer beats none when TVmaze fails', remote.search('sucession')[0]['id'] == 9)
busy = Remote(fetch=failing(HTTPError('u', 429, 'slow down', {}, None)), clock=lambda: now[0])
before = len(asked)
check('a 429 is no answer', busy.search('x') is None)
check('and pauses the calls that follow', busy.search('y') is None and len(asked) == before + 1 and busy.pause > now[0])


class Engine:
    """Just enough of engine.Engine for answer()."""
    def __init__(self):
        self.titles, self.shows = index, SHOWS
        self.by_id = at

    def card(self, i):
        return {'id': SHOWS[i]['id'], 'name': SHOWS[i]['name']}


engine = Engine()
said = []


class Stub:
    def __init__(self, found):
        self.found = found

    def search(self, q):
        said.append(q)
        return self.found


new = {'id': 424242, 'name': 'Brand New Show', 'year': 2026, 'url': 'https://www.tvmaze.com/shows/424242/brand-new-show'}
tvmaze = Stub([{'id': 19, 'name': 'Attack on Titan', 'year': 2013, 'url': 'https://www.tvmaze.com/shows/19/x'}, new,
               {'id': 9, 'name': 'Succession', 'year': 2018, 'url': 'https://www.tvmaze.com/shows/9/x'}])
out = answer(engine, 'money heist', tvmaze)
check('a strong local answer does not ask TVmaze', said == [] and out == {
    'shows': [{'id': 18, 'name': 'La Casa de Papel', 'aka': 'Money Heist'}], 'missing': [], 'missing_first': False})
out = answer(engine, 'sucession', tvmaze)
check('a weak one still asks TVmaze, but a whole-title typo correction leads unrelated results',
      said == ['sucession'] and [c['id'] for c in out['shows']] == [9, 19])
check('shows TVmaze has and the catalogue does not are missing, with their page', out['missing'] == [new])
check('they follow the results when TVmaze ranks a catalogue show first', out['missing_first'] is False)
out = answer(engine, 'unrecognized title', Stub([new, tvmaze.found[0]]))
check('and lead them when an uncertain query has a missing show first', out['missing_first'] is True
      and out['missing'] == [new] and out['shows'][0]['id'] == 19)
out = answer(engine, 'sucession', Stub([new, tvmaze.found[0]]))
check('an unrelated remote missing show cannot precede a whole-title typo correction',
      out['missing_first'] is False and out['missing'] == [new] and out['shows'][0]['id'] == 9)
remote_family = [{'id': show_id, 'name': SHOWS[at[show_id]]['name']} for show_id in (3032, 1020, 81, 50417)]
for query in ('Crimnal Minds', 'Criminal Mnds', 'Criminal Midns'):
    out = answer(engine, query, Stub(remote_family))
    check(f'{query} keeps the corrected primary ahead of remote spinoffs',
          out['shows'][0]['id'] == 81 and criminal_family <= {show['id'] for show in out['shows']})
out = answer(engine, 'sucession', Stub([{'id': 19, 'name': 'Sucession'}, new]))
check('a remote exact title remains ahead of a local typo correction', [show['id'] for show in out['shows']] == [19, 9])
exact_missing = {**new, 'name': 'Sucession'}
out = answer(engine, 'sucession', Stub([new, exact_missing, tvmaze.found[0]]))
check('a remote exact missing title leads and is offered once',
      out['missing_first'] is True and out['missing'][0] == exact_missing and len(out['missing']) == 1
      and out['shows'][0]['id'] == 9)
said.clear()
out = answer(engine, 'shingeki no kyojim', tvmaze)
check('a show both found keeps the title it was found by', out['shows'][0] == {
    'id': 19, 'name': 'Attack on Titan', 'aka': 'Shingeki no Kyojin'})
check('TVmaze down leaves the local answer as it was', answer(engine, 'sucession', Stub(None)) == {
    'shows': [{'id': 9, 'name': 'Succession'}], 'missing': [], 'missing_first': False})
said.clear()
check('a search too short is never sent', answer(engine, 'zq', tvmaze)['shows'] == [] and said == [])
out = answer(engine, 'demon slayer kimetsu no ya', tvmaze)
check('nor is one whose last word is still being typed', said == [] and out['shows'][0]['id'] == 17)
answer(engine, 'demon slayer kimetsu no yaiba', tvmaze)
check('until the word is finished', said == ['demon slayer kimetsu no yaiba'])
check('nothing found anywhere is an empty answer',
      answer(engine, 'zzzqqq', Stub([])) == {'shows': [], 'missing': [], 'missing_first': False})
many = Stub([{**new, 'id': 500 + k} for k in range(8)])
check('at most three missing shows are named', len(answer(engine, 'zzzqqq', many)['missing']) == 3)


# 5. The real client over HTTP, against a local stand-in for TVmaze.
class FakeTVmaze(BaseHTTPRequestHandler):
    def do_GET(self):
        q = self.path.split('q=', 1)[-1]
        if q == 'slow':
            time.sleep(1.5)
        if q == 'boom':
            self.send_error(500)
            return
        if q == 'busy':
            self.send_error(429)
            return
        body = b'not json' if q == 'garbled' else json.dumps([result(9, 'Succession', '2018-06-03')]).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


httpd = ThreadingHTTPServer(('127.0.0.1', 0), FakeTVmaze)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
local = partial(Remote, base=f'http://127.0.0.1:{httpd.server_address[1]}', timeout=.5)
check('the client reads a real HTTP answer', local().search('sucession') == [
    {'id': 9, 'name': 'Succession', 'year': 2018, 'url': 'https://www.tvmaze.com/shows/9/x', 'poster': None}])
started = time.perf_counter()
check('a slow TVmaze is given up on after the timeout', local().search('slow') is None
      and time.perf_counter() - started < 1.2, time.perf_counter() - started)
check('a failing TVmaze is no answer', local().search('boom') is None and local().search('garbled') is None)
client = local()
check('a 429 over HTTP pauses the client', client.search('busy') is None and client.pause > 0)
check('the default timeout is three seconds', Remote().timeout == 3.0)
httpd.shutdown()

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
