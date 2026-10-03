"""Public metadata remains crawlable, canonical and independent of viewer state."""
from pathlib import Path
from types import SimpleNamespace
from html import escape
import json
import re
import sys
import unittest
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.seo import SEO, PAGES, SITEMAP_SIZE, public_origin


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.show = {'id': 169, 'name': 'Breaking Bad', 'year': 2008, 'genres': ['Drama', 'Crime'],
                     'premiered': '2008-01-20', 'status': 'Ended', 'summary': 'A chemistry teacher turns to making meth.',
                     'url': 'https://www.tvmaze.com/shows/169/breaking-bad'}
        engine = SimpleNamespace(shows=[self.show], by_id={169: 0})
        library = SimpleNamespace(poster=lambda _i, _size: 'https://static.tvmaze.com/poster.jpg',
                                  starters=[{'id': 169, 'name': 'Breaking Bad'}])
        self.seo = SEO(engine, library, 'https://couchside.example')
        self.template = (ROOT / 'client/index.template.html').read_text()

    def rendered(self, path='/', query=None):
        return self.seo.render(self.template, path, query or {}).decode()

    def test_public_routes_have_distinct_titles_and_matching_canonicals(self):
        for name in ('home', 'browse', 'new', 'compare'):
            with self.subTest(page=name):
                page = PAGES[name]
                body = self.rendered(page['path'])
                self.assertIn(f'<title>{escape(page["title"])}</title>', body)
                self.assertIn(f'rel="canonical" href="https://couchside.example{page["path"]}"', body)
                self.assertEqual(body.count('name="description"'), 1)
                self.assertEqual(body.count('rel="canonical"'), 1)
                self.assertIn('content="index, follow, max-image-preview:large"', body)

    def test_show_is_crawlable_without_client_or_remote_lookup(self):
        body = self.rendered('/browse', {'show': ['169'], 'view': ['timeline'], 'utm_source': ['ignored']})
        self.assertIn('<title>Breaking Bad · Couchside</title>', body)
        self.assertIn('rel="canonical" href="https://couchside.example/?show=169"', body)
        self.assertIn('<h1>Breaking Bad</h1>', body)
        self.assertIn('<p>A chemistry teacher turns to making meth.</p>', body)
        self.assertIn('Breaking Bad (2008) on Couchside', body)
        schema = json.loads(re.search(r'id="page-schema">(.*?)</script>', body, re.S)[1])
        self.assertEqual(schema['@type'], 'TVSeries')
        self.assertEqual(schema['datePublished'], '2008-01-20')
        self.assertEqual(schema['genre'], ['Drama', 'Crime'])
        self.assertNotIn('aggregateRating', schema)
        self.assertNotIn('utm_source', body)

    def test_html_and_json_data_cannot_close_script_or_inject_markup(self):
        self.show['name'] = 'A & B "special" <script>bad()</script>'
        self.show['summary'] = '<b>Safe plot</b> </script><script>alert(1)</script>'
        body = self.rendered('/', {'show': ['169']})
        self.assertIn('A &amp; B &quot;special&quot; &lt;script&gt;', body)
        self.assertNotIn('<script>bad()', body)
        self.assertNotIn('<script>alert(1)', body)
        schema = json.loads(re.search(r'id="page-schema">(.*?)</script>', body, re.S)[1])
        self.assertEqual(schema['name'], self.show['name'])

    def test_private_pages_and_unbounded_queries_are_noindex(self):
        cases = [('/list', {}), ('/welcome', {}), ('/search', {'q': ['Criminal Minds']}),
                 ('/compare', {'compare': ['169,82']}), ('/', {'show': ['999999999']}),
                 ('/', {'show': ['169'], 'episode': ['7']}), ('/', {'person': ['123']})]
        for path, query in cases:
            with self.subTest(path=path, query=query):
                self.assertIn('name="robots" content="noindex, follow"', self.rendered(path, query))

    def test_show_over_private_route_has_public_canonical(self):
        body = self.rendered('/list', {'show': ['169']})
        self.assertIn('content="index, follow, max-image-preview:large"', body)
        self.assertIn('href="https://couchside.example/?show=169"', body)

    def test_sitemap_lists_public_pages_and_catalogue_show_canonicals_only(self):
        ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        index = ET.fromstring(self.seo.sitemap('/sitemap.xml'))
        self.assertEqual([node.text for node in index.findall('.//s:loc', ns)],
                         ['https://couchside.example/sitemaps/pages.xml', 'https://couchside.example/sitemaps/shows-1.xml'])
        pages = ET.fromstring(self.seo.sitemap('/sitemaps/pages.xml'))
        self.assertEqual([node.text for node in pages.findall('.//s:loc', ns)],
                         ['https://couchside.example/', 'https://couchside.example/browse',
                          'https://couchside.example/new', 'https://couchside.example/compare'])
        shows = ET.fromstring(self.seo.sitemap('/sitemaps/shows-1.xml'))
        self.assertEqual([node.text for node in shows.findall('.//s:loc', ns)], ['https://couchside.example/?show=169'])
        self.assertIsNone(self.seo.sitemap('/sitemaps/shows-2.xml'))
        self.assertIsNone(self.seo.sitemap('/sitemaps/not-real.xml'))
        self.assertIn('Sitemap: https://couchside.example/sitemap.xml', self.seo.robots().decode())
        self.assertNotIn('Disallow: /list', self.seo.robots().decode())

    def test_sitemap_chunks_stay_under_provider_url_limit(self):
        self.seo.ids = tuple(range(1, SITEMAP_SIZE + 2))
        self.seo.sitemap.cache_clear()
        first = ET.fromstring(self.seo.sitemap('/sitemaps/shows-1.xml'))
        last = ET.fromstring(self.seo.sitemap('/sitemaps/shows-2.xml'))
        self.assertEqual(len(first), SITEMAP_SIZE)
        self.assertEqual(len(last), 1)
        self.assertIsNone(self.seo.sitemap('/sitemaps/shows-3.xml'))

    def test_public_origin_accepts_only_configured_origins(self):
        self.assertEqual(public_origin('https://couchside.example/'), 'https://couchside.example')
        self.assertEqual(public_origin('http://127.0.0.1:18091'), 'http://127.0.0.1:18091')
        for value in ('http://public.example', 'https://name:secret@example.com', 'https://example.com/private',
                      'https://example.com?next=evil', '//example.com', 'https://example.com#part', 'https://example.com"unsafe'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                public_origin(value)


if __name__ == '__main__':
    unittest.main()
