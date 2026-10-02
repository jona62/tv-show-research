"""Behavioral and independent numerical checks for personalized recommendations."""
import copy
import json
import math
from pathlib import Path
import sys
import time
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'site'))
from backend.recommender import Engine, DEFAULT_PROFILE, DEFAULT_SETTINGS

class RecommenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine=Engine()
        cls.base=cls.engine.calculate({'profile':DEFAULT_PROFILE,'settings':DEFAULT_SETTINGS})

    def run_profile(self,profile,**settings):
        return self.engine.calculate({'profile':profile,'settings':dict(DEFAULT_SETTINGS,**settings)})

    def test_expanded_ranking_against_independent_numpy_reference(self):
        from scipy.sparse import csr_matrix
        e=self.engine
        t=csr_matrix((np.asarray(e.values),np.asarray(e.terms),np.asarray(e.row_ptr)),shape=(e.n,e.text_features))
        h=np.array([[bool(s['theme_bits']&(1<<j)) for j in range(len(e.themes))] for s in e.shows],float)
        g=np.array([[name in s['genres'] for name in e.genres] for s in e.shows],float)
        for m in (h,g):m/=np.maximum(1,np.linalg.norm(m,axis=1))[:,None]
        seeds=[e.by_id[p['id']] for p in DEFAULT_PROFILE];weights=np.array([p['weight'] for p in DEFAULT_PROFILE])
        affinity=.4*(t@t[seeds].T).toarray()+.35*h@h[seeds].T+.25*g@g[seeds].T
        scores=.7*np.average(affinity,axis=1,weights=weights)+.3*(affinity*(weights/weights.max())).max(axis=1)
        pool=[i for i,s in enumerate(e.shows) if i not in seeds and e.eligible(s,DEFAULT_SETTINGS)]
        order=sorted(pool,key=lambda i:(-scores[i],e.shows[i]['id']))[:20]
        self.assertEqual([e.shows[i]['id'] for i in order],[p['id'] for p in self.base['recommendations']])
        for i,actual in zip(order,self.base['recommendations']):self.assertAlmostEqual(scores[i]*100,actual['score'],places=2)

    def test_neutral_watched_title_is_excluded_without_changing_other_scores(self):
        watched=self.base['recommendations'][0]
        actual=self.run_profile(DEFAULT_PROFILE+[{'id':watched['id'],'weight':0}])
        self.assertNotIn(watched['id'],[r['id'] for r in actual['recommendations']])
        self.assertEqual(actual['candidate_count'],self.base['candidate_count']-1)
        self.assertEqual([r['id'] for r in actual['recommendations'][:19]],[r['id'] for r in self.base['recommendations'][1:]])
        self.assertEqual([r['score'] for r in actual['recommendations'][:19]],[r['score'] for r in self.base['recommendations'][1:]])

    def test_dislikes_reduce_scores_and_do_not_change_catalog_correlations(self):
        show=self.base['recommendations'][2]['id']
        neutral=self.run_profile(DEFAULT_PROFILE+[{'id':show,'weight':0}])
        negative=self.run_profile(DEFAULT_PROFILE+[{'id':show,'weight':-1}])
        old={p['id']:p['score'] for p in neutral['points']}
        common=[p for p in negative['points'] if p['id'] in old]
        self.assertTrue(any(p['score']<old[p['id']] for p in common))
        self.assertTrue(all(p['score']<=old[p['id']] for p in common))
        self.assertEqual(neutral['correlations'],negative['correlations'])

    def test_comedy_profile_changes_recommendations_and_counts(self):
        offices=[s for s in self.engine.shows if s['name']=='The Office' and s['year']==2005]
        self.assertEqual(len(offices),1)
        actual=self.run_profile([{'id':offices[0]['id'],'weight':1}],text=0,themes=0,genres=100,runtime_min=0)
        self.assertTrue(all('Comedy' in r['genres'] for r in actual['recommendations'][:10]))
        self.assertTrue(any(f['feature']=='Genre: Comedy' and f['liked_count']==1 for f in actual['features']))
        self.assertLess(len({p['id'] for p in actual['recommendations']} & {p['id'] for p in self.base['recommendations']}),5)

    def test_radar_comparison_uses_a_different_closest_like(self):
        ids=[p['id'] for p in DEFAULT_PROFILE]
        for point in self.base['points']:
            self.assertIn(point['nearest_other_id'],ids)
            self.assertNotEqual(point['id'],point['nearest_other_id'])
            if point['id'] in ids:
                i=ids.index(point['id'])
                expected=max((j for j in range(len(ids)) if j!=i),key=lambda j:self.base['pairs'][i][j])
                self.assertEqual(point['nearest_other_id'],ids[expected])
        single=self.run_profile([{'id':169,'weight':1}])
        self.assertIsNone(next(p for p in single['points'] if p['id']==169)['nearest_other_id'])

    def test_map_axis_changes_coordinates_but_not_ranking(self):
        actual=self.run_profile(DEFAULT_PROFILE,axis_x=182,axis_y=169)
        self.assertEqual(actual['axes'],{'x':'Black Sails','y':'Breaking Bad'})
        self.assertEqual(actual['recommendations'][0]['score'],self.base['recommendations'][0]['score'])
        self.assertNotEqual(actual['recommendations'][0]['x'],self.base['recommendations'][0]['x'])

    def test_numeric_reference_for_pairwise_cosine_and_phi(self):
        e=self.engine;i=e.by_id[169];j=e.by_id[182]
        vectors=[]
        for idx in (i,j):
            row=e.shows[idx];text=np.zeros(e.text_features)
            for term,value in e.text_items(idx):text[term]=value
            themes=np.array([bool(row['theme_bits']&(1<<k)) for k in range(len(e.themes))],float)
            genres=np.array([g in row['genres'] for g in e.genres],float)
            vectors.append((text,themes,genres))
        similarity=sum(weight*np.dot(a,b)/(np.linalg.norm(a)*np.linalg.norm(b)) for weight,a,b in zip((.4,.35,.25),*vectors))
        pair=self.run_profile([{'id':169,'weight':1},{'id':182,'weight':1}])
        self.assertAlmostEqual(pair['pairs'][0][1],similarity*100,places=1)
        top=self.base['correlations'][0]
        watched={p['id'] for p in DEFAULT_PROFILE}
        pool=[s for s in e.shows if s['id'] not in watched and e.eligible(s,DEFAULT_SETTINGS)]
        values=[[bool(s['theme_bits']&(1<<e.themes.index(key))) for s in pool] for key in (top['a'],top['b'])]
        self.assertAlmostEqual(top['r'],np.corrcoef(values)[0,1],places=3)

    def test_filters_empty_state_and_ratings(self):
        future=self.run_profile(DEFAULT_PROFILE,year_min=2100)
        self.assertEqual(future['candidate_count'],0);self.assertEqual(future['recommendations'],[])
        self.assertTrue(future['message']);json.dumps(future,allow_nan=False)
        rating=self.run_profile(DEFAULT_PROFILE,rating_min=8,runtime_min=50,year_min=2015)
        self.assertTrue(all(r['rating']>=8 and r['runtime']>=50 and r['year']>=2015 for r in rating['recommendations']))
        for profile in ([],[{'id':169,'weight':0}],[{'id':169,'weight':-1}]):
            empty=self.run_profile(profile);self.assertEqual(empty['positive_count'],0);self.assertEqual(empty['points'],[])

    def test_validation(self):
        for payload in ({'profile':[{'id':169,'weight':2}]},{'profile':[{'id':-1}]},{'profile':[{'id':169}]*2},
                        {'settings':{'text':0,'themes':0,'genres':0}},{'settings':{'text':float('nan')}},
                        {'settings':{'year_min':True}},{'profile':[{'id':169}]*51}):
            with self.assertRaises(ValueError):self.engine.calculate(payload)

    def test_catalog_expansion_filters_and_feature_coverage(self):
        e=self.engine
        self.assertEqual(e.n,89594);self.assertEqual(len(e.themes),32);self.assertEqual(e.text_features,40000)
        self.assertGreater(len(e.metadata['language']),80)
        for language,kind in [('Japanese','Animation'),('English','Documentary'),('English','Reality'),('German','Scripted')]:
            anchor=next(s for s in e.shows if s['language']==language and s['type']==kind and s['recommendable'] and s['summary_words']>=15)
            result=self.run_profile([{'id':anchor['id'],'weight':1}],language=language,type=kind,year_min=1900,runtime_min=0)
            self.assertTrue(result['recommendations'])
            self.assertTrue(all(s['language']==language and s['type']==kind for s in result['recommendations']))
            self.assertTrue(any(f['group']=='language' and f['liked_count']==1 for f in result['features']))
            self.assertTrue(all('keywords' in s and 'detected_themes' in s for s in result['recommendations']))
        unknown=next(s for s in e.shows if s['year'] is None)
        e.search(unknown['name'])  # Missing years must not break sort order.
        result=self.run_profile([{'id':unknown['id'],'weight':1}],language='all',type='all',year_min=1900,runtime_min=0)
        self.assertTrue(all(s['year'] is not None for s in result['recommendations']))
        sparse=next(s for s in e.shows if not s['genre_bits'] and not s['theme_bits'] and not s['summary_words'])
        result=self.run_profile([{'id':sparse['id'],'weight':1}],language='all',type='all')
        self.assertEqual(result['recommendations'],[]);self.assertTrue(result['warnings']);self.assertTrue(result['message'])
        for settings in ({'language':'Klingon'},{'type':['Scripted']},{'status':'Never existed'}):
            with self.assertRaises(ValueError):e.calculate({'settings':settings})

    def test_fifty_show_profile_is_bounded(self):
        profile=[{'id':s['id'],'weight':1} for s in self.engine.shows[:50]]
        start=time.monotonic();actual=self.run_profile(profile)
        self.assertEqual(actual['positive_count'],50);self.assertEqual(len(actual['pairs']),12)
        self.assertLessEqual(len(actual['points']),110)
        self.assertTrue(all(0<=p['score']<=100 for p in actual['points']))
        self.assertLess(len(json.dumps(actual)),350000)
        print(f'50-show calculation: {time.monotonic()-start:.3f}s')

if __name__=='__main__':unittest.main()
