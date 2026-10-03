"""Preview episode ratings inside Couchside without editing its generated bundle."""
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json
import sys

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1] / 'couchside'
sys.path.insert(0, str(APP))
from backend import server
from backend.live import Live, LiveError, picture, plain, score, whole
from local_account import PATH as LOCAL_ACCOUNT_PATH, bootstrap as bootstrap_local_account

# Include the existing catalogue description wherever the preview uses a show card.
# This avoids a separate title request for each hover.
native_card = server.LIBRARY.card


def preview_card(index, taste=None):
    return {**native_card(index, taste), 'summary': server.ENGINE.shows[index]['summary'] or ''}


server.LIBRARY.card = preview_card

RATINGS = Live(calls=12, size=1000)
FIXTURES = {s['id']: s for s in json.loads((HERE / 'data.js').read_text().removeprefix('window.SHOWS = ').rstrip().removesuffix(';'))}
server.PAGE = server.PAGE.replace('</head>', '<link rel="stylesheet" href="/ratings-mock.css"><link rel="stylesheet" href="/watch-card-designs.css"></head>')


def tracking_preview():
    """Frozen public catalog snapshot with invented personal progress."""
    return json.loads((HERE / 'watch-tracking-fixtures.json').read_text())


def episodes(raw):
    if not isinstance(raw, list):
        raise ValueError('not an episode list')
    return [{'id': e['id'], 'season': e['season'], 'number': e['number'], 'name': e['name'],
             'rating': score(e.get('rating')), 'airdate': e.get('airdate', ''),
             'runtime': whole(e.get('runtime')), 'image': picture(e.get('image')),
             'summary': plain(e.get('summary'), 360)}
            for e in raw if isinstance(e, dict) and whole(e.get('id')) and
            whole(e.get('season')) and whole(e.get('number')) and isinstance(e.get('name'), str)]


class Preview(server.Handler):
    def do_POST(self):
        if urlsplit(self.path).path == LOCAL_ACCOUNT_PATH:
            bootstrap_local_account(self, server.ACCOUNT_ROUTES)
            return
        super().do_POST()

    def do_GET(self):
        parts = urlsplit(self.path)
        path = parts.path
        self.cache_control = 'no-store'
        if path == '/api/tracking-preview':
            self.send_json(tracking_preview())
            return
        if path == '/api/ratings-preview':
            try:
                show_id = int(parse_qs(parts.query).get('id', ['0'])[0])
                if not 0 < show_id < 10_000_000:
                    raise ValueError('Choose a valid show.')
                found = FIXTURES.get(show_id) or {'id': show_id, 'episodes': RATINGS.get(f'/shows/{show_id}/episodes', episodes)}
                self.send_json(found)
            except (ValueError, TypeError):
                self.send_json({'error': 'Choose a valid show.'}, 400)
            except LiveError as exc:
                self.send_json({'error': str(exc)}, exc.status)
            return
        assets = {'/ratings-mock.js': 'ratings-mock.js', '/ratings-mock.css': 'ratings-mock.css',
                  '/ratings-core.js': 'ratings-core.js', '/ratings-home.js': 'ratings-home.js',
                  '/title-sections.js': 'title-sections.js',
                  '/watch-tracking.js': 'watch-tracking.js', '/watch-tracking.css': 'watch-tracking.css',
                  '/watch-card-designs.js': 'watch-card-designs.js', '/watch-card-designs.css': 'watch-card-designs.css',
                  '/ratings-data.js': 'data.js'}
        if path in assets:
            self.send_body((HERE / assets[path]).read_bytes(), 'text/css' if path.endswith('.css') else 'text/javascript')
            return
        if path == '/assets/scripts/main.js':
            source = (APP / 'public/assets/scripts/main.js').read_text()
            if "from './watch-tracking.js" in source:
                source = source.replace('startAppUpdates();', '/* Local preview: no service worker. */', 1)
                account_mount = 'accounts = mountAccounts('
                assert account_mount in source, 'Account mount point changed; update the preview adapter.'
                source = source.replace(account_mount, '''await fetch('/api/account/local-development', {
  method: 'POST', credentials: 'same-origin', cache: 'no-store',
  signal: AbortSignal.timeout(12000),
  headers: { 'Content-Type': 'application/json', 'X-Account-Request': '1' },
  body: JSON.stringify({ state }),
}).catch(() => {});
''' + account_mount, 1)
                source += "\nconst { mountCardDesigns } = await import('/watch-card-designs.js');\nmountCardDesigns();\n"
                self.send_body(source.encode(), 'text/javascript')
                return
            if "from './episode-ratings.js" in source:
                source = source.replace("if ('serviceWorker' in navigator && window.isSecureContext)", 'if (false)')
                source = source.replace('startAppUpdates();', '/* Local design preview: no service worker. */', 1)
                source = "import { mountTrackingTitle, mountEpisodeProgress, renderTrackingList, trackingListButton } from '/watch-tracking.js';\n" + source
                hooks = {
                    '  paintOut(t, c);\n  mountTitleSections': '  paintOut(t, c);\n  mountTrackingTitle(t);\n  mountTitleSections',
                    'function renderList() {\n': 'function renderList() {\n  renderTrackingList();\n',
                    '  li.append(still, text);\n  return li;': '  li.append(still, text);\n  mountEpisodeProgress(li, ep, season);\n  return li;',
                    'function listButton(c, kind) {\n': 'function listButton(c, kind) {\n  return trackingListButton(c, kind, icon, () => ({ ...c, ...info(c.id) }));\n',
                    "search:page==='list'": 'search:false',
                }
                for before, after in hooks.items():
                    assert before in source, 'Tracking mount point changed; update the preview adapter.'
                    source = source.replace(before, after, 1)
                self.send_body(source.encode(), 'text/javascript')
                return
            needle = '  T.episodes.hidden = false;\n  loadSeason(first.number).then(painted);'
            assert needle in source, 'Episode mount point changed; update the mockup adapter.'
            source = "import { mountEpisodeRatings } from '/ratings-mock.js';\nimport { mountTitleSections } from '/title-sections.js';\nimport { enhanceShowCard } from '/ratings-home.js';\n" + source.replace(
                needle, '  T.episodes.hidden = false;\n  const ratingsTitle = T;\n  loadSeason(first.number).then(() => { if (T === ratingsTitle) mountEpisodeRatings(T, { openEpisode, episodeEl, revealButton, paintReveal, unfold, busy, snippet, revealLabel }); painted(); });')
            hooks = {
                '  paintOut(t, c);\n  return t;':
                    '  paintOut(t, c);\n  mountTitleSections(t, { revealButton, paintReveal, unfold, busy, edges });\n  return t;',
                '  T.about.replaceChildren(...about);':
                    '  T.about.replaceChildren(...about);\n  T.sectionsUpdate?.();',
                '  T.fans.hidden = !fans.length;':
                    '  T.fans.hidden = !fans.length;\n  T.sectionsUpdate?.();',
                '  for (const p of cast.slice(0, 12)) {':
                    '  for (const p of cast) {',
                "function cardEl(c, { rank = 0, soon = false, note = '', row = '', ahead = false } = {}) {":
                    "function cardEl(c, { rank = 0, soon = false, note = '', row = '', ahead = false, related = false } = {}) {",
                "  if (soon && c.premiered) card.append(el('span', `Premieres ${premiere(c.premiered)}`, 'soon-date'));\n  return card;":
                    "  if (soon && c.premiered) card.append(el('span', `Premieres ${premiere(c.premiered)}`, 'soon-date'));\n  enhanceShowCard(card, { ...full, similar: c.similar, why: c.why }, related);\n  return card;",
            }
            for before, after in hooks.items():
                assert before in source, 'Title section changed; update the mockup adapter.'
                source = source.replace(before, after)
            start = source.index('function moreCard(c) {')
            end = source.index('\nfunction paintEpisodes(', start)
            source = source[:start] + '''function moreCard(c) {
  const li = el('li', '', 'ratings-related-card');
  li.append(cardEl(c, { related: true, note: [c.similar ? `${c.similar}% similar` : '', c.why].filter(Boolean).join(' · ') }));
  return li;
}
''' + source[end:]
            update = "  paintReveal(T.epsMore, revealLabel('episodes', items.length, open), open);"
            assert update in source, 'Episode reveal point changed; update the mockup adapter.'
            source = source.replace(update, update + '\n  T.ratingsUpdate?.();')
            source = source.replace("if ('serviceWorker' in navigator && window.isSecureContext)", 'if (false)')
            self.send_body(source.encode(), 'text/javascript')
            return
        if path == '/assets/scripts/start.js':
            source = (APP / 'public/assets/scripts/start.js').read_text()
            source = source.replace('return fresh();', 'return { ...fresh(), onboarded: true };', 1)
            self.send_body(source.encode(), 'text/javascript')
            return
        super().do_GET()


if __name__ == '__main__':
    popular = sorted(range(server.ENGINE.n), key=lambda i: (server.ENGINE.popularity[i], server.ENGINE.shows[i].get('rating') or 0), reverse=True)
    server.RATINGS.start(server.ENGINE.shows[i]['id'] for i in popular[:200])
    print('Couchside mockup: http://localhost:8766/?show=169', flush=True)
    ThreadingHTTPServer(('127.0.0.1', 8766), partial(Preview, directory=str(APP / 'public'))).serve_forever()
