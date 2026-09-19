"""Content recommendation engine over frozen TF-IDF, genre, and theme vectors."""
from array import array
import struct
import sys
from functools import lru_cache
import gzip
import json
import math
import os
from pathlib import Path
import unicodedata

DEFAULT_PROFILE=[{'id':i,'weight':w} for i,w in [(13417,1),(169,1),(618,1),(42062,1),(182,1),(82,.35)]]
DEFAULT_SETTINGS={'text':40,'themes':35,'genres':25,'closest':.3,'dislike':.35,
                  'language':'English','type':'Scripted','status':'all','year_min':1990,'runtime_min':25,'rating_min':0,'axis_x':'all','axis_y':42062}

def model_dir():
    """One model copy serves both apps. It is too large for the release uploader,
    so deployments keep it outside the synced tree and name it in MODEL_DIR; a
    checkout or a git-source deploy finds it in place."""
    here=Path(__file__).resolve().parent
    for candidate in (os.environ.get('MODEL_DIR'), here/'model', here.parent/'model'):
        if candidate and (Path(candidate)/'catalog.json.gz').exists():return Path(candidate)
    raise SystemExit('No model found. Set MODEL_DIR, or build the model into model/.')

def folded(s):
    return ''.join(c for c in unicodedata.normalize('NFKD',s.casefold()) if not unicodedata.combining(c))

class Engine:
    def __init__(self,path=None):
        model=Path(path) if path else model_dir()
        with gzip.open(model/'catalog.json.gz','rt') as f:data=json.load(f)
        self.shows=data['shows'];self.by_id={s['id']:i for i,s in enumerate(self.shows)}
        self.genres=data['genres'];self.themes=data['themes'];self.version=data['version'];self.date=data['date']
        self.n=len(self.shows)
        self.names=[folded(s['name']) for s in self.shows]
        self.metadata=data['metadata']
        with gzip.open(model/'vectors.bin.gz','rb') as f:
            rows,cols,nnz=struct.unpack('<III',f.read(12))
            if rows!=self.n or cols!=data['text_features']:raise ValueError('Model vector dimensions do not match catalog.')
            def read_array(code,count):
                values=array(code);values.frombytes(f.read(count*4))
                if sys.byteorder!='little':values.byteswap()
                if len(values)!=count:raise ValueError('Incomplete model vectors.')
                return values
            self.row_ptr=read_array('I',rows+1);self.terms=read_array('I',nnz);self.values=read_array('f',nnz)
            self.col_ptr=read_array('I',cols+1);self.post_rows=read_array('I',nnz);self.post_values=read_array('f',nnz)
        self.text_features=cols
        self.feature_specs=[('themes',name,'theme_bits',j) for j,name in enumerate(self.themes)]
        self.feature_specs += [('genres','Genre: '+name,'genre_bits',j) for j,name in enumerate(self.genres)]
        for key,prefix in [('type','Format'),('language','Language'),('country','Network country'),('status','Status')]:
            self.feature_specs += [(key,prefix+': '+value,key,value) for value in self.metadata[key]]
        self.feature_masks=[]
        for group,label,field,value in self.feature_specs:
            mask=bytearray((self.n+7)//8)
            for i,show in enumerate(self.shows):
                present=bool(show[field]&(1<<value)) if field.endswith('_bits') else show[field]==value
                if present:mask[i//8]|=1<<(i%8)
            self.feature_masks.append(int.from_bytes(mask,'little'))
        self.theme_counts=[s['theme_bits'].bit_count() for s in self.shows]
        self.genre_counts=[s['genre_bits'].bit_count() for s in self.shows]

    def public(self,i):
        s=self.shows[i]
        return {k:s[k] for k in ('id','name','year','runtime','rating','genres','url','channel','language','type','country','status','coverage','summary','keywords')}

    def search(self,q):
        query=folded(q.strip())
        if len(query)<2:return []
        tokens=query.split()
        matches=[i for i,name in enumerate(self.names) if all(t in name for t in tokens)]
        matches.sort(key=lambda i:(self.names[i].removeprefix('the ')!=query,self.names[i]!=query,not self.names[i].startswith(query),-(self.shows[i]['year'] or 0),len(self.names[i]),self.shows[i]['id']))
        return [self.public(i) for i in matches[:10]]

    def validate(self,body):
        if not isinstance(body,dict):raise ValueError('Send a watched list and settings.')
        profile=body.get('profile',[])
        if not isinstance(profile,list) or len(profile)>50:raise ValueError('Your list can contain up to 50 shows.')
        seen=set();parsed=[]
        for p in profile:
            if not isinstance(p,dict) or type(p.get('id')) is not int or p['id'] not in self.by_id:raise ValueError('A watched show is not in this dataset. Remove it and try again.')
            if p['id'] in seen:raise ValueError('Each watched show should appear only once.')
            weight=p.get('weight',1)
            if isinstance(weight,bool) or not isinstance(weight,(int,float)) or not math.isfinite(weight) or weight not in (-1,0,.35,.7,1):raise ValueError('Choose a valid rating for each show.')
            seen.add(p['id']);parsed.append({'id':p['id'],'weight':weight})
        settings=body.get('settings',{})
        if not isinstance(settings,dict):raise ValueError('Settings must be an object.')
        result=dict(DEFAULT_SETTINGS)
        ranges={'text':(0,100),'themes':(0,100),'genres':(0,100),'closest':(0,1),'dislike':(0,1),'year_min':(1900,2100),'runtime_min':(0,240),'rating_min':(0,10)}
        for k,(lo,hi) in ranges.items():
            value=settings.get(k,result[k])
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError(f'Invalid value for {k.replace("_"," ")}.')
            result[k]=value
        if result['text']+result['themes']+result['genres']==0:raise ValueError('Give plot text, themes, or genres a weight above zero.')
        for key in ('language','type','status'):
            value=settings.get(key,result[key])
            if not isinstance(value,str) or value not in ['all','unknown']+self.metadata[key]:raise ValueError(f'Choose a valid {key} filter.')
            result[key]=value
        positive={p['id'] for p in parsed if p['weight']>0}
        for k in ('axis_x','axis_y'):
            value=settings.get(k,result[k])
            if value=='all':result[k]='all'
            elif type(value) is int and value in positive:result[k]=value
            else:result[k]='all'
        return parsed,result

    def text_items(self,index):
        return ((self.terms[k],self.values[k]) for k in range(self.row_ptr[index],self.row_ptr[index+1]))

    def eligible(self,show,settings):
        if not show['recommendable'] or show['year']<settings['year_min']:return False
        for key in ('language','type','status'):
            value=settings[key]
            if value!='all' and (show[key] or 'unknown')!=value:return False
        return all(settings[key]==0 or (show[field] is not None and show[field]>=settings[key])
                   for key,field in [('runtime_min','runtime'),('rating_min','rating')])

    @lru_cache(maxsize=64)
    def components(self,index):
        """Compact cached catalog similarities; no user profiles are cached."""
        source=self.shows[index];text=array('f',[0])*self.n
        for term,value in self.text_items(index):
            for k in range(self.col_ptr[term],self.col_ptr[term+1]):text[self.post_rows[k]]+=value*self.post_values[k]
        def bits(field,counts):
            source_bits=source[field];n=source_bits.bit_count()
            return array('f',((source_bits&s[field]).bit_count()/math.sqrt(n*counts[i]) if n and counts[i] else 0.0 for i,s in enumerate(self.shows)))
        return text,bits('theme_bits',self.theme_counts),bits('genre_bits',self.genre_counts)

    def calculate(self,body):
        profile,settings=self.validate(body)
        watched=[dict(self.public(self.by_id[p['id']]),weight=p['weight']) for p in profile]
        positives=[p for p in profile if p['weight']>0];negatives=[p for p in profile if p['weight']<0]
        watched_ids={p['id'] for p in profile}
        candidates=[i for i,s in enumerate(self.shows) if s['id'] not in watched_ids and self.eligible(s,settings)]
        base={'version':self.version,'date':self.date,'catalog_count':self.n,'candidate_count':len(candidates),
              'profile':watched,'settings':settings,'positive_count':len(positives),'negative_count':len(negatives),
              'recommendations':[],'points':[],'features':[],'pairs':[],'pair_labels':[],
              'axes':{'x':'All liked shows','y':'All liked shows'},'correlations':[],'warnings':[]}
        if not positives:
            base['message']='Search for a show and mark at least one as liked to get recommendations.'
            return base
        if any(self.shows[self.by_id[p['id']]]['summary_words']<15 for p in positives):
            base['warnings'].append('Some liked shows have little plot text. Their matches rely on whichever genres and theme evidence are available; missing features contribute zero similarity.')
        total=settings['text']+settings['themes']+settings['genres']
        mix=[settings[k]/total for k in ('text','themes','genres')]
        affinities={}
        for p in positives+negatives:
            components=self.components(self.by_id[p['id']])
            t,h,g=components;a,b,c=mix
            affinities[p['id']]=array('f',(min(1.0,a*x+b*y+c*z) for x,y,z in zip(t,h,g)))
        norm=sum(p['weight'] for p in positives);max_weight=max(p['weight'] for p in positives)
        average=[sum(p['weight']*affinities[p['id']][i] for p in positives)/norm for i in range(self.n)]
        best=[max(p['weight']/max_weight*affinities[p['id']][i] for p in positives) for i in range(self.n)]
        penalty=[settings['dislike']*sum(affinities[p['id']][i] for p in negatives)/len(negatives) if negatives else 0.0 for i in range(self.n)]
        scores=[max(0.0,(1-settings['closest'])*average[i]+settings['closest']*best[i]-penalty[i]) for i in range(self.n)]
        ordered=sorted((i for i in candidates if scores[i]>0),key=lambda i:(-scores[i],self.shows[i]['id']))
        ranks={i:n+1 for n,i in enumerate(ordered)}
        axes=[]
        for key in ('axis_x','axis_y'):
            value=settings[key]
            axes.append(average if value=='all' else affinities[value])
            base['axes']['x' if key=='axis_x' else 'y']='All liked shows' if value=='all' else self.shows[self.by_id[value]]['name']

        def record(i):
            s=self.shows[i]
            source=max(positives,key=lambda p:affinities[p['id']][i])
            source_show=self.shows[self.by_id[source['id']]]
            other=max((p for p in positives if p['id']!=s['id']),key=lambda p:affinities[p['id']][i],default=None)
            overlap=s['theme_bits']&source_show['theme_bits']
            return dict(self.public(i),seed=s['id'] in watched_ids,score=round(scores[i]*100,2),rank=ranks.get(i),
                x=round(axes[0][i]*100,2),y=round(axes[1][i]*100,2),nearest=source_show['name'],nearest_id=source_show['id'],nearest_other_id=other['id'] if other else None,
                detected_themes=[name for j,name in enumerate(self.themes) if s['theme_bits']&(1<<j)],
                shared=[name for j,name in enumerate(self.themes) if overlap&(1<<j)],
                dislike_penalty=round(penalty[i]*100,2))
        base['recommendations']=[record(i) for i in ordered[:20]]
        plotted=list(dict.fromkeys([self.by_id[p['id']] for p in positives]+ordered[:60]))
        base['points']=[record(i) for i in plotted]
        liked_indices=[self.by_id[p['id']] for p in positives]
        def mask_for(indices):
            data=bytearray((self.n+7)//8)
            for i in indices:data[i//8]|=1<<(i%8)
            return int.from_bytes(data,'little')
        pool_mask=mask_for(candidates);liked_mask=mask_for(liked_indices)
        for (group,name,field,value),mask in zip(self.feature_specs,self.feature_masks):
            count=(mask&liked_mask).bit_count()
            prevalence=(mask&pool_mask).bit_count()/len(candidates) if candidates else 0.0
            base['features'].append({'feature':name,'group':group,'liked_count':count,'liked_total':len(positives),
                'liked_pct':round(count/len(positives)*100,2),'baseline_pct':round(prevalence*100,2),
                'lift':round(count/len(positives)/prevalence,2) if prevalence else None})
        base['features'].sort(key=lambda f:(-f['liked_count'],-(f['lift'] or 0),f['feature']))
        pair_indices=liked_indices[:12]
        base['pair_labels']=[self.shows[i]['name'] for i in pair_indices]
        base['pairs']=[[round(affinities[self.shows[j]['id']][i]*100,1) for j in pair_indices] for i in pair_indices]
        # Binary Pearson/phi over the eligible, unwatched catalog, not a preference correlation.
        n=len(candidates)
        theme_masks=[m&pool_mask for m in self.feature_masks[:len(self.themes)]]
        counts=[m.bit_count() for m in theme_masks]
        for a,name_a in enumerate(self.themes):
            for b in range(a):
                denom=math.sqrt(counts[a]*(n-counts[a])*counts[b]*(n-counts[b]))
                both=(theme_masks[a]&theme_masks[b]).bit_count()
                r=(n*both-counts[a]*counts[b])/denom if denom else None
                if r is not None:base['correlations'].append({'a':name_a,'b':self.themes[b],'r':round(r,3),'n':n})
        base['correlations'].sort(key=lambda p:-abs(p['r']))
        base['correlations']=base['correlations'][:5]
        base['message']='' if ordered else ('No unwatched shows match these filters. Broaden the language, format, status, year, runtime, or rating filters.' if not candidates else 'No positive similarity matches under these settings. Add another like, enable other features, or reduce the dislike penalty.')
        return base
