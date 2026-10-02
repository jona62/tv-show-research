from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
import gzip
import json

from episode_store import Store, Episodes
from live import Live, LiveError, SHOW
from warm_cache import warm


class WarmTests(TestCase):
    def test_nightly_writes_are_readable_after_restart_without_upstream_calls(self):
        with TemporaryDirectory() as folder:
            model=Path(folder)/'model';model.mkdir()
            (model/'catalog.json.gz').write_bytes(gzip.compress(json.dumps({'shows':[{'id':169,'name':'A','status':'Running'}]}).encode()))
            (model/'popularity.bin.gz').write_bytes(gzip.compress(bytes([99])))
            calls=[]
            def fetch(path):
                calls.append(path)
                if path.endswith('/episodes'):
                    return [{'id':1,'season':1,'number':1,'name':'Pilot','rating':{'average':8.1},'summary':'Description'}]
                return {'id':169,'name':'A','_embedded':{'cast':[],'seasons':[]}}
            cache=Path(folder)/'episodes.sqlite3'
            with patch('warm_cache.Live',side_effect=lambda **options: Live(fetch=fetch,**options)):
                result=warm(model,cache,limit=1,log=lambda message:None)
            self.assertEqual(result['refreshed'],1)
            self.assertEqual(len(calls),2)
            store=Store(cache)
            try:
                def unavailable(path):
                    raise AssertionError('Visitor should not need an upstream lookup')
                live=Live(fetch=unavailable,store=store)
                self.assertEqual(live.show(169)['about']['name'],'A')
                matrices=Episodes(store,live).matrices([169])
                self.assertFalse(matrices['pending'])
                self.assertEqual(matrices['shows'][0]['episodes'][0]['rating'],8.1)
            finally:
                store.db.close()

    def test_existing_fresh_data_is_kept_and_failed_warming_is_deferred(self):
        with TemporaryDirectory() as folder:
            model=Path(folder)/'model';model.mkdir()
            (model/'catalog.json.gz').write_bytes(gzip.compress(json.dumps({'shows':[{'id':1,'status':'Running'},{'id':2,'status':'Running'}]}).encode()))
            (model/'popularity.bin.gz').write_bytes(gzip.compress(bytes([99,98])))
            cache=Path(folder)/'episodes.sqlite3'
            store=Store(cache)
            store.put(1,{'id':1,'tvmaze':[],'episodes':[],'tmdb':{},'tmdb_at':0})
            store.put_live(SHOW.format(id=1), {'about': {'name': 'A'}})
            store.db.close()
            def failed(path):raise LiveError('busy',503)
            with patch('warm_cache.Live',side_effect=lambda **options: Live(fetch=failed,**options)):
                result=warm(model,cache,limit=2,log=lambda message:None)
            self.assertEqual(result,{'kept':1,'refreshed':0,'deferred':1})

    def test_fresh_episode_data_does_not_prevent_details_from_being_warmed(self):
        with TemporaryDirectory() as folder:
            model=Path(folder)/'model';model.mkdir()
            (model/'catalog.json.gz').write_bytes(gzip.compress(json.dumps({'shows':[{'id':1,'status':'Ended'}]}).encode()))
            (model/'popularity.bin.gz').write_bytes(gzip.compress(bytes([99])))
            cache=Path(folder)/'episodes.sqlite3'
            store=Store(cache)
            store.put(1,{'id':1,'tvmaze':[],'episodes':[],'tmdb':{},'tmdb_at':0});store.db.close()
            calls=[]
            def fetch(path):
                calls.append(path)
                return {'id':1,'name':'A','_embedded':{'cast':[],'seasons':[]}}
            with patch('warm_cache.Live',side_effect=lambda **options: Live(fetch=fetch,**options)):
                result=warm(model,cache,limit=1,log=lambda message:None)
            self.assertEqual(result['refreshed'],1)
            self.assertEqual(calls,[SHOW.format(id=1)])

if __name__=='__main__':main()
