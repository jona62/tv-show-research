"""Check the taste model: what a list leans toward, and how a show's fit is scored.

Run from the repository root:  .venv/bin/python app/test_taste.py
"""
from pathlib import Path
import math
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from engine import Engine                                        # noqa: E402
import taste                                                     # noqa: E402
from taste import Attributes, Taste, FAMILIES, CATEGORICAL        # noqa: E402

failures = []


def check(name, ok, detail=''):
    print(f'{"pass" if ok else "FAIL"}  {name}{"  " + detail if detail and not ok else ""}')
    if not ok:
        failures.append(name)


model = ROOT / 'app' / 'model'
e = Engine(model if (model / 'catalog.json.gz').exists() else ROOT / 'model')
a = Attributes(e)


def index(name, year=None):
    found = [i for i, s in enumerate(e.shows) if s['name'].casefold() == name.casefold() and (year is None or s['year'] == year)]
    assert found, name
    return max(found, key=lambda i: e.popularity[i])


# 1. Attributes: every show has at most one value per plain family, base rates are shares.
for family in CATEGORICAL:
    base = a.base[family]
    check(f'{family}: base rates are shares of known shows', abs(sum(base[1:]) - 1) < .02 and min(base[1:]) > 0,
          f'sum {sum(base[1:]):.3f}')
    check(f'{family}: every value names a label', max(a.values[family]) < len(a.labels[family]))
check('genre and theme rates sit strictly between 0 and 1',
      all(0 < b < 1 for f in ('genre', 'theme') for b in a.base[f]))

# 2. An empty list says nothing: every show scores zero and the factor is one.
empty = Taste(a, [], [])
sample = range(0, e.n, 997)
check('an empty list scores every show zero', all(empty.score(i) == 0 for i in sample))
check('an empty list adds only the pull toward well-rated shows',
      all(abs(empty.factor(i) - math.exp(taste.QUALITY * empty.quality(i))) < 1e-12 for i in sample))
check('an empty list has no leanings', empty.summary() == {'leans': [], 'avoids': []})

# 3. A list of Korean dramas prefers Korean dramas to American sitcoms.
korean = [index(n) for n in ('Crash Landing on You', 'Descendants of the Sun', 'Business Proposal',
                             'Itaewon Class', 'Hometown Cha-Cha-Cha')]
k = Taste(a, [(i, 1) for i in korean], [])
check('Korean dramas score above American sitcoms for a K-drama list',
      k.score(index('Vincenzo')) > k.score(index('Friends')) + 1,
      f"{k.score(index('Vincenzo')):.2f} vs {k.score(index('Friends')):.2f}")
check('the leaning names the language', any(f['label'] == 'Korean' for f in k.summary()['leans']))

# 4. One or two ratings barely move anything; many move a lot.
crime = [index(n) for n in ('Breaking Bad', 'The Sopranos', 'The Wire', 'Better Call Saul', 'Ozark',
                            'Narcos', 'Fargo', 'Mindhunter', 'Boardwalk Empire', 'True Detective')]
target = index('Peaky Blinders')
one, many = Taste(a, [(crime[0], 1)], []), Taste(a, [(i, 1) for i in crime], [])
check('one liked show moves less than ten', abs(one.score(target)) < abs(many.score(target)),
      f'{one.score(target):.2f} vs {many.score(target):.2f}')
check('a crime list favours a crime drama over a baking show',
      many.score(target) > many.score(index('The Great British Bake Off')))

# 5. Dislikes count against what they carry.
reality = [index(n) for n in ('Love Island', 'Big Brother', 'The Bachelor')]
without = Taste(a, [(i, 1) for i in crime], [])
against = Taste(a, [(i, 1) for i in crime], reality)
probe = index('Survivor')
check('disliked reality shows lower another reality show', against.score(probe) < without.score(probe),
      f'{against.score(probe):.2f} vs {without.score(probe):.2f}')
check('two or more dislikes of a kind read as avoiding it',
      any(f['label'] == 'Reality' and f['why'] == 'disliked' for f in against.summary()['avoids']))

# 6. Scores stay bounded by the family weights and clips.
bound = sum(w * c for f, (w, c) in FAMILIES.items() if f in a.values or f in a.masks)
check('taste scores stay within their bound', all(abs(many.score(i)) <= bound + 1e-6 for i in range(0, e.n, 311)))
check('the factor is exp(strength x fit + quality x rating pull)',
      abs(many.factor(target) - math.exp(taste.STRENGTH * many.score(target) + taste.QUALITY * many.quality(target))) < 1e-9)
check('an unrated show is not pulled either way', many.quality(next(i for i, s in enumerate(e.shows) if not s['rating'])) == 0)

# 7. A show with no data in a family is not guessed at: that family adds nothing.
no_genre = next(i for i, s in enumerate(e.shows) if not s['genre_bits'] and s['recommendable'])
entry = next(entry for entry in many.sets if entry[0] == 'genre')
check('unknown genres add nothing', many.family_score(entry, no_genre) == 0)

# 8. Reasons explain with what is distinctive, never with what most shows share.
reasons = [r['label'] for r in many.reasons(target)]
check('reasons name something distinctive', reasons and 'English' not in reasons and 'Scripted' not in reasons,
      str(reasons))
leans = many.summary()['leans']
check('leanings need two liked shows', all(f['shows'] >= 2 for f in leans))
check('crime is among the leanings', any(f['label'].split(' / ')[0].casefold() == 'crime' for f in leans), str([f['label'] for f in leans]))

print()
if failures:
    sys.exit(f'{len(failures)} check(s) failed: {", ".join(failures)}')
print('all checks passed')
