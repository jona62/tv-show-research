"""Check the row of shows like a search (related.py): which row a search gets, what is in
it and what is not.

Run from the repository root:  .venv/bin/python couchside/test_related.py
It reads the repository's model/ directly, its Wikidata facets included, and reaches
nothing else: TVmaze's search is left out, so each answer is the catalogue's own.
"""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'couchside'))

from engine import Engine, DEFAULT_SETTINGS                     # noqa: E402
from fallback import answer                                     # noqa: E402
from library import Library                                     # noqa: E402
from related import Related, fold, numbers, slipped, COUNT      # noqa: E402

engine = Engine(ROOT / 'model')
lib = Library(engine, ROOT / 'couchside' / 'art.bin.gz')
pool = lib.pool_stats(DEFAULT_SETTINGS)['pool']
rel = Related(engine, pool)
failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + str(detail) if detail and not ok else ""}')
    if not ok:
        failures.append(name)


def search(q, into=None):
    """The title matches and the row for q, as the server works them out."""
    cards = answer(engine, q, None, lib.card)['shows']
    return cards, (into or rel).of(q, cards)


def named(indices):
    return [engine.shows[j]['name'] for j in indices]


def index(name, year=None):
    return next(i for i, s in enumerate(engine.shows) if s['name'] == name and (year is None or s['year'] == year))


f = engine.facets
genre = {label: c for c in range(*f.family_ranges[f.families.index('genre')]) for label in [f.labels[c]]}


def carries(j, label):
    return any(c == genre[label] for c, _v in f.row(j))


# 1. Reading a search: the same plain words as the summaries, both numbers of a word, and
# typos word for word.
check('searches and summaries fold alike: accents go, apostrophes join, anything else parts words',
      fold(["Grey's Anatomy", 'a Mad Max-style gang', 'Café  Society', '進撃']) ==
      [b'greys anatomy', b'a mad max style gang', b'cafe society', b''])
check('a word comes in both numbers', {b'zombie', b'zombies'} <= set(numbers(b'zombies'))
      and {b'mystery', b'mysteries'} <= set(numbers(b'mysteries')) and b'witches' in numbers(b'witch')
      and b'heists' in numbers(b'heist') and numbers(b'boss')[0] == b'boss')
check('a slip or two, each in a word of four letters or more, is a typo of a title',
      slipped([b'brekaing', b'bad'], [b'breaking', b'bad']) and slipped([b'stranger', b'thigns'], [b'stranger', b'things'])
      and slipped([b'ofice'], [b'the', b'office']))
check('but a word changed outright, a slip in a short word or three slips is not',
      not slipped([b'jurassic', b'park'], [b'jurassic', b'war']) and not slipped([b'bat', b'man'], [b'bad', b'man'])
      and not slipped([b'brekaing', b'bda', b'sohw'], [b'breaking', b'bad', b'show'])
      and not slipped([b'breaking', b'bad'], [b'breaking', b'bad']))

# 2. A search that names a show gets More like it: the title page's More like this, less
# the shows it matched. Game of Thrones matches House of the Dragon by its other title.
cards, row = search('game of thrones')
matched = {engine.by_id[c['id']] for c in cards}
got = index('Game of Thrones')
check('game of thrones matches House of the Dragon, and gets More like Game of Thrones',
      'House of the Dragon' in [c['name'] for c in cards] and row and row['kind'] == 'show'
      and row['title'] == 'More like Game of Thrones' and len(row['shows']) == COUNT, row)
check('its row leads with the rest of the franchise and shows like it',
      'A Knight of the Seven Kingdoms' in named(row['shows'][:3])
      and {'The Lord of the Rings: The Rings of Power', 'The Wheel of Time'} <= set(named(row['shows'])), named(row['shows']))
check('no show in the row is one the search matched, or the show itself', not matched & set(row['shows']) and got not in row['shows'])
near = engine.blend(got, DEFAULT_SETTINGS)
whole = [j for j in pool if j != got and j not in matched]
scores = engine.rank(whole, [{'id': 82, 'weight': 1}], [], {82: near}, DEFAULT_SETTINGS)
page = sorted((j for j in whole if scores[j] > 0), key=lambda j: (-scores[j], engine.shows[j]['id']))
check('it is the title page\'s ranking, weighed over the whole catalogue', row['shows'][:12] == page[:12],
      (named(row['shows'][:12]), named(page[:12])))
for q, title, among in (('breaking bad', 'More like Breaking Bad', 'Better Call Saul'),
                        ('the office', 'More like The Office', 'Parks and Recreation'),
                        ('stranger things', 'More like Stranger Things', 'Dark'),
                        ('brekaing bad', 'More like Breaking Bad', 'The Sopranos'),
                        ('attack on titan', 'More like Attack on Titan', 'Demon Slayer'),
                        ('shingeki no kyojin', 'More like Shingeki no Kyojin', 'Jujutsu Kaisen'),
                        ('money heist', 'More like Money Heist', 'Vis a Vis'),
                        ('la casa de papel', 'More like La Casa de Papel', 'Élite'),
                        ('오징어 게임', 'More like 오징어 게임', 'Alice in Borderland'),
                        ('supernatural', 'More like Supernatural', None),
                        ('atlanta', 'More like Atlanta', None)):
    _cards, row = search(q)
    check(f'{q} gets {title}', row and row['title'] == title and row['kind'] == 'show'
          and (among is None or among in named(row['shows'])), row and (row['title'], named(row['shows'][:8])))
check('a show typed with a slip is named by its own title, one found by another title by that title',
      search('brekaing bad')[1]['title'] == 'More like Breaking Bad' and search('money heist')[1]['title'] == 'More like Money Heist')
check('a household name keeps its own name though a Wikidata genre has it too (Supernatural), and so does a well-known show '
      'named after a place (Atlanta)', search('supernatural')[1]['kind'] == search('atlanta')[1]['kind'] == 'show')

# 3. A topic, a Wikidata genre or subject, gets Shows like it, even when a less known show
# has it for a title (Zombies, a Disney musical).
cards, row = search('zombies')
check('zombies gets Shows like zombies, not More like the musical Zombies', cards[0]['name'] == 'Zombies'
      and row['kind'] == 'topic' and row['title'] == 'Shows like zombies', row and row['title'])
zombie = {c for c in range(f.cols) if f.labels[c] == 'zombie'}
about = [j for j in row['shows'] if any(c in zombie for c, _v in f.row(j))
         or 'zombie' in (engine.shows[j]['summary'] or '').lower() or any('zombie' in k for k in engine.shows[j]['keywords'])]
check('its shows are about zombies, The Walking Dead among them', len(about) >= 14 and 'The Walking Dead' in named(row['shows']),
      named(row['shows']))
for q, among in (('space opera', {'The Expanse', 'Firefly', 'The Mandalorian'}), ('vampires', {'What We Do in the Shadows'}),
                 ('true crime', {'The Staircase'}), ('westerns', {'Deadwood', '1883'}), ('time travel', {'Travelers'})):
    _cards, row = search(q)
    check(f'{q} is a topic with {", ".join(sorted(among))}', row and row['kind'] == 'topic' and among <= set(named(row['shows'])),
          row and named(row['shows']))
check('either number of a topic names it', search('zombie')[1]['kind'] == 'topic' and search('vampire')[1]['kind'] == 'topic')

# 4. Anything else by meaning: mad max is in Daybreak's summary, Daybreak is
# post-apocalyptic, and so the row is post-apocalyptic shows.
cards, row = search('mad max')
check('mad max, a film, finds only a documentary by name and gets Shows like mad max',
      named(engine.by_id[c['id']] for c in cards) == ['Mad Max, univers brûlant'] and row['kind'] == 'meaning'
      and row['title'] == 'Shows like mad max', row and row['title'])
apocalyptic = [j for j in row['shows'] if carries(j, 'post apocalyptic')]
check('its shows are post-apocalyptic, led by Daybreak and Fallout', len(apocalyptic) >= 15
      and named(row['shows'][:2]) == ['Daybreak', 'Fallout'], named(row['shows']))
cards, row = search('the matrix')
check('the matrix is not taken for Matrix, a 1993 series about a hitman, and finds cyberpunk',
      cards[0]['name'] == 'Matrix' and row['kind'] == 'meaning'
      and {'Altered Carbon', 'Cyberpunk: Edgerunners', 'The Ghost in the Shell'} & set(named(row['shows'][:10])), named(row['shows']))
_cards, row = search('boxing')
check('boxing finds boxing, not the romances one boxer is in', row and {'Lights Out', 'The Contender'} <= set(named(row['shows'])),
      row and named(row['shows']))
check('a search with nothing behind it gets no row, not Jurassic War for jurassic park',
      search('jurassic park')[1] is None and search('xyzzyq')[1] is None)

# 5. While a search is typed: the start of a household name's title names it; half a word
# gets nothing; a show begun by another of its titles goes by its own name.
check('game o names Game of Thrones', search('game o')[1]['title'] == 'More like Game of Thrones')
check('a search still being typed, or of half a word, waits', search('mad ma')[1] is None and search('gam')[1] is None
      and search('ga')[1] is None)
check('zomb begins Z Nation by its Lithuanian title, and the row goes by Z Nation', search('zomb')[1]['title'] == 'More like Z Nation')

# 6. Answers are kept, and are the same each time.
first = search('mad max')[1]
started = time.perf_counter()
again = search('mad max')[1]
check('an answer is kept and comes back at once', again is first and time.perf_counter() - started < 0.05)
rel.answers.clear()
check('worked out again it is the same', search('mad max')[1] == first)
cold = Related(engine, pool)
check('built on first use it is the same as warmed', search('zombies', cold)[1] == search('zombies')[1])

# 7. Without Wikidata's facets there are no topics, and a search still gets its row.
facets = engine.facets
engine.facets = None
try:
    bare = Related(engine, pool)
    check('without facets, a search that names a show still gets More like it',
          search('game of thrones', bare)[1]['title'] == 'More like Game of Thrones')
    _cards, row = search('boxing', bare)
    check('and one by meaning still finds the shows its words are in', row and row['kind'] == 'meaning'
          and 'Lights Out' in named(row['shows']), row)
    check('but mad max, with only two such shows and no genres to go on, gets none', search('mad max', bare)[1] is None)
finally:
    engine.facets = facets

print()
if failures:
    print(f'{len(failures)} check(s) failed')
    sys.exit(1)
print('all related checks passed')
