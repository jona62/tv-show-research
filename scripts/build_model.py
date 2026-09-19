"""Build the expanded catalog and compact sparse vectors; preserve the original study."""
import gzip
import html
import json
import re
import struct
from collections import Counter
from pathlib import Path
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'
TARGET=ROOT/'model'
TARGET.mkdir(exist_ok=True)
rules=json.loads((OUT/'theme_rules.json').read_text())
rules.update({
 'Science / technology':r'\b(scien\w*|technolog\w*|robot\w*|artificial intelligence|inventor\w*|laborator\w*|cyber\w*)\b',
 'Space / other worlds':r'\b(spacecraft|spaceship\w*|astronaut\w*|galax\w*|interstellar|alien\w*|outer space|space station|planet\w*)\b',
 'Medicine / health':r'\b(doctor\w*|nurs\w*|hospital\w*|surgeon\w*|surgery|medical|patient\w*|healthcare)\b',
 'War / military':r'\b(war|wars|wartime|soldier\w*|military|army|armies|navy|veteran\w*|combat|troops)\b',
 'History / period setting':r'\b(histor\w*|medieval|victorian|ancient|renaissance|century|centuries|1920s|1930s|1940s)\b',
 'Work / business':r'\b(workplace|office|employee\w*|colleague\w*|boss|business\w*|entrepreneur\w*|corporat\w*|career\w*)\b',
 'School / education':r'\b(school\w*|student\w*|teacher\w*|college|university|campus|classroom\w*)\b',
 'Identity / self-discovery':r'\b(identity|identities|self.discovery|self.acceptance|belonging|reinvent\w*|coming.out|find herself|find himself|find themselves)\b',
 'Revenge / redemption':r'\b(revenge|vengeance|avenge\w*|redempt\w*|redeem\w*|aton\w*|second chance\w*)\b',
 'Psychology / mental health':r'\b(psycholog\w*|psychiatr\w*|therapist\w*|mental health|mental illness|trauma\w*|depression|addiction\w*)\b',
 'Competition / achievement':r'\b(competi\w*|contest\w*|tournament\w*|champion\w*|win|winning|winner\w*)\b',
 'Sport / athletics':r'\b(sport\w*|athlet\w*|football|soccer|basketball|baseball|hockey|tennis|boxing|cricket|olympic\w*)\b',
 'Music / performance':r'\b(music\w*|singer\w*|singing|concert\w*|orchestra\w*|dance\w*|dancing|theatre|theater)\b',
 'Food / cooking':r'\b(food|cook\w*|chef\w*|cuisine\w*|restaurant\w*|baking|baker\w*|culinary|recipe\w*)\b',
 'Nature / wildlife':r'\b(nature|natural world|natural history|wildlife|animal\w*|ecolog\w*|ecosystem\w*|conservation|wilderness|ocean\w*|forest\w*)\b',
 'Travel / cultures':r'\b(travel\w*|touris\w*|journey\w*|around the world|cultur\w*|destination\w*)\b',
 'Relationships / dating':r'\b(dating|marriage\w*|married|divorc\w*|couple\w*|relationship\w*|wedding\w*|matchmak\w*)\b',
 'Home / design':r'\b(renovat\w*|interior design|home improv\w*|architecture|architect\w*|real estate|property|properties)\b',
 'Belief / spirituality':r'\b(religio\w*|spiritual\w*|faith|priest\w*|church\w*|monk\w*|pilgrim\w*)\b',
 'Mystery / puzzles':r'\b(myster\w*|puzzle\w*|enigma\w*|clue\w*|unsolved|disappear\w*|missing person\w*)\b',
})
patterns=[re.compile(p,re.I) for p in rules.values()]
manifest=json.loads((ROOT/'data/manifest.json').read_text())
date=manifest['retrieved_utc'][:10]
raw=[s for p in sorted((ROOT/'data/raw').glob('page-*.json')) for s in json.loads(p.read_text())]
assert len({s['id'] for s in raw})==len(raw)
raw.sort(key=lambda s:s['id'])
genres=sorted({g for s in raw for g in s['genres']})
seed_names=json.loads((OUT/'audit.json').read_text())['seed_ids']
texts=[];shows=[]
for s in raw:
    summary=re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',s.get('summary') or ''))).strip()
    text=re.sub(r'(?<!\w)'+re.escape(s['name'])+r'(?!\w)',' ',summary,flags=re.I)
    for title in seed_names:text=re.sub(r'(?<!\w)'+re.escape(title)+r'(?!\w)',' ',text,flags=re.I)
    texts.append(text)
    channel=s.get('webChannel') or s.get('network') or {}
    premiere=s.get('premiered')
    shows.append({'id':s['id'],'name':s['name'],'year':int(premiere[:4]) if premiere else None,
        'premiered':premiere,'runtime':s.get('averageRuntime') or s.get('runtime'),
        'rating':s.get('rating',{}).get('average'),'genres':s['genres'],'status':s.get('status'),
        'language':s.get('language'),'type':s.get('type'),
        'country':(channel.get('country') or {}).get('code'),'channel':channel.get('name'),
        'url':s['url'],'summary':summary[:480]+('…' if len(summary)>480 else ''),
        'summary_words':len(summary.split()),
        'genre_bits':sum(1<<genres.index(g) for g in s['genres']),
        'theme_bits':sum(1<<j for j,p in enumerate(patterns) if p.search(text)),
        'recommendable':bool(premiere and premiere<=date and (len(summary.split())>=15 or s['genres']))})
del raw
stops=sorted(set(ENGLISH_STOP_WORDS)|{'series','show','season','episode','episodes','based','starring','drama'})
vectorizer=TfidfVectorizer(stop_words=stops,ngram_range=(1,2),min_df=3,max_df=.7,max_features=40000,sublinear_tf=True,dtype=np.float32)
csr=vectorizer.fit_transform(texts).tocsr();csr.sort_indices();csc=csr.tocsc()
# Both orientations avoid Python objects per nonzero on a 1GB server.
with gzip.GzipFile(filename=str(TARGET/'vectors.bin.gz'),mode='wb',mtime=0) as f:
    f.write(struct.pack('<III',*csr.shape,csr.nnz))
    for m in (csr,csc):
        for a,dtype in ((m.indptr,'<u4'),(m.indices,'<u4'),(m.data,'<f4')):f.write(a.astype(dtype).tobytes())
terms=vectorizer.get_feature_names_out()
for i,show in enumerate(shows):
    row=csr[i];ordered=sorted(zip(row.indices,row.data),key=lambda pair:-pair[1]);keywords=[]
    for idx,value in ordered:
        term=str(terms[idx])
        if not any(term in old or old in term for old in keywords):keywords.append(term)
        if len(keywords)==6:break
    show['keywords']=keywords
metadata={k:sorted({s[k] for s in shows if s[k]}) for k in ('language','type','country','status')}
for s in shows:
    if s['summary_words']<15:s['coverage']='Limited plot text' if s['genres'] else 'Very limited metadata'
    elif not s['genres']:s['coverage']='No genre tags'
    else:s['coverage']='Plot and genres available'
data={'version':'tvmaze-v2-'+date,'date':date,'shows':shows,'genres':genres,'themes':list(rules),
      'text_features':csr.shape[1],'metadata':metadata}
with gzip.GzipFile(filename=str(TARGET/'catalog.json.gz'),mode='wb',mtime=0) as f:
    f.write(json.dumps(data,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode())
audit={'version':data['version'],'retrieved':date,'searchable_shows':len(shows),
    'recommendable_shows':sum(s['recommendable'] for s in shows),'genres':len(genres),'themes':len(rules),
    'text_features':csr.shape[1],'languages':len(metadata['language']),
    'types':dict(Counter(s['type'] for s in shows)),
    'coverage':dict(Counter(s['coverage'] for s in shows)),
    'recommendation_rule':'Known premiere on or before snapshot date, and at least 15 summary words or one genre.',
    'country_meaning':'Country of listed network/web channel; not necessarily production origin or streaming availability.',
    'themes_method':'Analyst-authored English regex proxies over summaries, with own title and example titles removed. No translations or human annotations.',
    'source':'https://www.tvmaze.com/api','license':'https://creativecommons.org/licenses/by-sa/4.0/'}
(OUT/'catalog-audit.json').write_text(json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
(OUT/'expanded_theme_rules.json').write_text(json.dumps(rules,indent=2)+'\n')
print(json.dumps(audit,indent=2))
print('Model bytes',sum(p.stat().st_size for p in TARGET.glob('*.gz')))
