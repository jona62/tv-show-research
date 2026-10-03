"""Public page metadata and discovery, using only the loaded catalogue."""
from functools import lru_cache
from html import escape, unescape
from urllib.parse import urlsplit
import json
import os
import re

DEFAULT_ORIGIN = 'https://couchside-jlvf21do.rigbox.dev'
DESCRIPTION = 'Find your next TV show, keep a watchlist, and explore episode ratings and comparisons with Couchside.'
PAGES = {
    'home': {'path': '/', 'title': 'Couchside', 'heading': 'Find your next TV show', 'description': DESCRIPTION},
    'browse': {'path': '/browse', 'title': 'Browse TV shows · Couchside', 'heading': 'Browse TV shows',
               'description': 'Explore TV shows by genre, language, year and rating, and find something that fits your taste.'},
    'new': {'path': '/new', 'title': 'New & Popular TV shows · Couchside', 'heading': 'New & Popular',
            'description': 'Discover new and popular TV shows, explore their episode ratings, and add your next watch to My List.'},
    'compare': {'path': '/compare', 'title': 'Compare shows · Couchside', 'heading': 'Compare shows',
                'description': 'Compare TV shows side by side with episode matrices and rating timelines, then save your comparison as an image.'},
    'list': {'path': '/list', 'title': 'My List · Couchside', 'heading': 'My List',
             'description': 'Your saved TV shows and ratings on Couchside.', 'private': True},
    'search': {'path': '/search', 'title': 'Search TV shows · Couchside', 'heading': 'Search shows',
               'description': 'Search Couchside for TV shows and explore their episode ratings.', 'private': True},
    'welcome': {'path': '/welcome', 'title': 'Welcome · Couchside', 'heading': 'Welcome to Couchside',
                'description': 'Pick shows you like to discover what to watch next.', 'private': True},
}
INDEXED = tuple(page['path'] for page in PAGES.values() if not page.get('private'))
SITEMAP_SIZE = 10000
SHARE = re.compile(r'<!--share.*?<!--/share-->', re.S)
NO_SCRIPT = re.compile(r'<!--seo-content-->.*?<!--/seo-content-->', re.S)
TITLE = re.compile(r'<title>.*?</title>', re.S)
TAG = re.compile(r'<[^>]*>')


def public_origin(value=None):
    """A deployment setting, never a request Host or forwarded header."""
    value = value if value is not None else os.environ.get('COUCHSIDE_ORIGIN') or os.environ.get('ACCOUNT_ORIGIN') or DEFAULT_ORIGIN
    parsed = urlsplit(value)
    local = parsed.hostname in ('localhost', '127.0.0.1', '::1')
    if (parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.password
            or re.search(r'[\s<>"\'\\]', parsed.netloc)
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')
            or (parsed.scheme != 'https' and not local)):
        raise ValueError('COUCHSIDE_ORIGIN must be a public HTTPS origin or a local HTTP origin.')
    return f'{parsed.scheme}://{parsed.netloc}'.rstrip('/')


def bootstrap():
    return {'origin': public_origin(), 'pages': PAGES}


def plain(value):
    return ' '.join(unescape(TAG.sub(' ', value or '')).split())


def snippet(value, limit=200):
    value = plain(value)
    return value if len(value) <= limit else value[:limit].rsplit(' ', 1)[0] + '…'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')


def page_name(path, query):
    if path in ('/', '/index.html'):
        return query.get('page', ['home'])[0] if query.get('page', ['home'])[0] in PAGES else 'home'
    return next((name for name, page in PAGES.items() if page['path'] == path), 'home')


class SEO:
    def __init__(self, engine, library, site=None):
        self.engine, self.library, self.site = engine, library, public_origin(site)
        self.ids = tuple(sorted(show['id'] for show in engine.shows if show.get('name') and plain(show.get('summary'))))

    def show(self, query):
        raw = query.get('show', [''])[0]
        index = self.engine.by_id.get(int(raw)) if re.fullmatch(r'[1-9][0-9]{0,8}', raw) else None
        if index is None:
            return None
        return {**self.engine.shows[index], 'art': self.library.poster(index, 'original_untouched')}

    def metadata(self, path, query):
        page = PAGES[page_name(path, query)]
        show = self.show(query)
        noindex = bool(page.get('private') or query.get('episode') or query.get('person') or query.get('compare'))
        result = {**page, 'url': self.site + page['path'], 'image': self.site + '/assets/images/og.jpg',
                  'imageAlt': 'The Couchside wordmark beside a wall of TV show posters', 'noindex': noindex,
                  'ogTitle': page['title'], 'card': 'summary_large_image', 'show': show}
        if show:
            year = f" ({show['year']})" if show.get('year') else ''
            result.update(title=f"{show['name']} · Couchside", heading=show['name'],
                          description=snippet(show.get('summary')) or DESCRIPTION,
                          ogTitle=f"{show['name']}{year} on Couchside", url=f"{self.site}/?show={show['id']}",
                          image=show.get('art') or result['image'], imageAlt=f"Poster for {show['name']}", card='summary',
                          noindex=bool(query.get('episode') or query.get('person')))
        elif query.get('show'):
            result['noindex'] = True
        return result

    def structured(self, metadata):
        show = metadata['show']
        common = {'@context': 'https://schema.org', 'url': metadata['url'], 'name': metadata['heading'],
                  'description': metadata['description']}
        if show:
            value = {**common, '@type': 'TVSeries', 'image': metadata['image'], 'genre': show.get('genres', [])}
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', show.get('premiered') or ''):
                value['datePublished'] = show['premiered']
            if show.get('url'):
                value['sameAs'] = show['url']
            return value
        if metadata['path'] == '/':
            return {'@context': 'https://schema.org', '@graph': [
                {'@type': 'WebSite', '@id': self.site + '/#website', 'url': self.site + '/', 'name': 'Couchside',
                 'description': DESCRIPTION},
                {'@type': 'WebApplication', 'name': 'Couchside', 'url': self.site + '/', 'description': DESCRIPTION,
                 'applicationCategory': 'EntertainmentApplication', 'operatingSystem': 'Any',
                 'browserRequirements': 'Requires JavaScript'}]}
        return {**common, '@type': 'CollectionPage', 'isPartOf': {'@id': self.site + '/#website'}}

    def head(self, metadata):
        tags = [('name', 'description', metadata['description']), ('name', 'robots',
                 'noindex, follow' if metadata['noindex'] else 'index, follow, max-image-preview:large'),
                ('property', 'og:site_name', 'Couchside'), ('property', 'og:type', 'video.tv_show' if metadata['show'] else 'website'),
                ('property', 'og:title', metadata['ogTitle']), ('property', 'og:description', metadata['description']),
                ('property', 'og:url', metadata['url']), ('property', 'og:image', metadata['image']),
                ('property', 'og:image:alt', metadata['imageAlt']), ('name', 'twitter:card', metadata['card']),
                ('name', 'twitter:title', metadata['ogTitle']), ('name', 'twitter:description', metadata['description']),
                ('name', 'twitter:image', metadata['image']), ('name', 'twitter:image:alt', metadata['imageAlt'])]
        lines = [f'<meta {kind}="{key}" content="{escape(value, quote=True)}">' for kind, key, value in tags]
        if not metadata['show']:
            lines.extend(['<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">'])
        lines.append(f'<link rel="canonical" href="{escape(metadata["url"], quote=True)}">')
        lines.append(f'<script type="application/ld+json" id="page-schema">{encoded(self.structured(metadata))}</script>')
        return '<!--share-->\n' + '\n'.join(lines) + '\n<!--/share-->'

    def content(self, metadata):
        show = metadata['show']
        heading, description = escape(metadata['heading']), escape(plain(show.get('summary')) if show else metadata['description'])
        parts = [f'<h1>{heading}</h1>', f'<p>{description}</p>']
        if show:
            facts = [str(show['year']) if show.get('year') else '', ', '.join(show.get('genres', [])), show.get('status') or '']
            parts.append(f'<p>{escape(" · ".join(fact for fact in facts if fact))}</p>')
            parts.append(f'<p>Explore {heading} episode ratings, season matrices and timelines, or add it to a comparison.</p>')
            if show.get('url'):
                parts.append(f'<p><a href="{escape(show["url"], quote=True)}">{heading} on TVmaze</a></p>')
        elif not metadata['noindex']:
            cards = self.library.starters[:12]
            links = ''.join(f'<li><a href="/?show={card["id"]}">{escape(card["name"])}</a></li>' for card in cards)
            parts.append(f'<h2>Explore TV shows</h2><ul>{links}</ul>')
        parts.append('<p><a href="/browse">Browse TV shows</a> · <a href="/new">New &amp; Popular</a> · <a href="/compare">Compare shows</a></p>')
        parts.append('<p>Turn on JavaScript to use interactive recommendations, lists and episode graphs.</p>')
        return '<!--seo-content--><noscript><article class="noscript">' + ''.join(parts) + '</article></noscript><!--/seo-content-->'

    def render(self, template, path, query):
        metadata = self.metadata(path, query)
        page = SHARE.sub(lambda _match: self.head(metadata), template, count=1)
        page = TITLE.sub(lambda _match: f'<title>{escape(metadata["title"])}</title>', page, count=1)
        return NO_SCRIPT.sub(lambda _match: self.content(metadata), page, count=1).encode()

    def robots(self):
        return f'User-agent: *\nDisallow: /api/\n\nSitemap: {self.site}/sitemap.xml\n'.encode()

    @lru_cache(maxsize=8)
    def sitemap(self, path):
        if path == '/sitemap.xml':
            count = (len(self.ids) + SITEMAP_SIZE - 1) // SITEMAP_SIZE
            names = ['/sitemaps/pages.xml', *(f'/sitemaps/shows-{part + 1}.xml' for part in range(count))]
            entries = ''.join(f'<sitemap><loc>{escape(self.site + name)}</loc></sitemap>' for name in names)
            return self.xml('sitemapindex', entries)
        if path == '/sitemaps/pages.xml':
            return self.xml('urlset', ''.join(f'<url><loc>{escape(self.site + page)}</loc></url>' for page in INDEXED))
        found = re.fullmatch(r'/sitemaps/shows-([1-9][0-9]{0,4})\.xml', path)
        if not found:
            return None
        start = (int(found[1]) - 1) * SITEMAP_SIZE
        ids = self.ids[start:start + SITEMAP_SIZE]
        if not ids:
            return None
        entries = ''.join(f'<url><loc>{escape(f"{self.site}/?show={show_id}")}</loc></url>' for show_id in ids)
        return self.xml('urlset', entries)

    @staticmethod
    def xml(tag, content):
        return f'<?xml version="1.0" encoding="UTF-8"?>\n<{tag} xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{content}</{tag}>\n'.encode()
