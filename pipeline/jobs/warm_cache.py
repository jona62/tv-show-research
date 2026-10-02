"""Refresh the same durable details and episode matrices Couchside serves to visitors."""
from pathlib import Path
import argparse
import gzip
import json
import time

from backend.episode_store import Store, Episodes
from backend.live import Live, LiveError, SHOW


def warm(model, cache, limit=200, seconds=900, log=print):
    with gzip.open(Path(model) / 'catalog.json.gz', 'rt') as source:
        shows = json.load(source)['shows']
    with gzip.open(Path(model) / 'popularity.bin.gz', 'rb') as source:
        weights = source.read()
    popular = [shows[i]['id'] for i in sorted(range(len(shows)), key=lambda i: weights[i], reverse=True)[:limit]]
    store = Store(cache)
    live = Live(store=store)
    ratings = Episodes(store, live, ended=(s['id'] for s in shows if s.get('status') == 'Ended'))
    known = {s['id'] for s in shows}
    due = list(dict.fromkeys([*(sid for sid in store.recent(limit) if sid in known), *popular]))[:limit * 2]
    deadline = time.monotonic() + seconds
    counts = {'refreshed': 0, 'kept': 0, 'deferred': 0}
    try:
        for show_id in due:
            if time.monotonic() >= deadline:
                break
            held = store.get(show_id)
            episodes_fresh = held and not ratings.stale(show_id, held[0])
            details = store.get_live(SHOW.format(id=show_id))
            details_fresh = details and store.clock() - details[0] < live.ttl
            if episodes_fresh and details_fresh:
                counts['kept'] += 1
                continue
            try:
                # TVmaze lands even if optional season ratings cannot be enriched.
                if not episodes_fresh:
                    ratings.refresh(show_id, enrich=False)
                if not details_fresh:
                    live.show(show_id)
                counts['refreshed'] += 1
            except (LiveError, OSError, ValueError):
                counts['deferred'] += 1
        log('RESULT ' + json.dumps(counts))
        return counts
    finally:
        store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()
    warm(args.model, args.cache, args.limit)
