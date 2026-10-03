import assert from 'node:assert/strict';
import { metadataFor } from '../client/metadata.js';

const config = { origin: 'https://couchside.example', pages: {
  home: { path: '/', title: 'Couchside', heading: 'Find your next TV show', description: 'Discover TV shows.' },
  compare: { path: '/compare', title: 'Compare shows · Couchside', heading: 'Compare shows', description: 'Compare episode ratings.' },
  list: { path: '/list', title: 'My List · Couchside', heading: 'My List', description: 'Your saved shows.', private: true },
} };
const show = { id: 169, name: 'Breaking Bad', year: 2008, summary: 'A chemistry teacher turns to making meth.',
  art: 'https://static.tvmaze.com/original_untouched/1/1.jpg', genres: ['Drama', 'Crime'], premiered: '2008-01-20',
  url: 'https://www.tvmaze.com/shows/169/breaking-bad' };

const detail = metadataFor(config, { page: 'list', show, params: new URLSearchParams('show=169&view=timeline&utm_source=other') });
assert.equal(detail.url, 'https://couchside.example/?show=169');
assert.equal(detail.title, 'Breaking Bad · Couchside');
assert.equal(detail.ogTitle, 'Breaking Bad (2008) on Couchside');
assert.equal(detail.image, show.art);
assert.equal(detail.noindex, false);
assert.equal(detail.schema['@type'], 'TVSeries');
assert.equal(detail.schema.datePublished, show.premiered);
assert.deepEqual(detail.schema.genre, show.genres);
assert.equal(detail.schema.sameAs, show.url);
assert.equal(detail.schema.aggregateRating, undefined);

assert.equal(metadataFor(config, { page: 'list' }).noindex, true);
assert.equal(metadataFor(config, { page: 'compare' }).noindex, false);
assert.equal(metadataFor(config, { page: 'compare', params: new URLSearchParams('compare=169,82') }).noindex, true);
assert.equal(metadataFor(config, { show, params: new URLSearchParams('show=169&episode=100') }).noindex, true);
assert.equal(metadataFor(config, { params: new URLSearchParams('show=999999999') }).noindex, true);
assert.equal(metadataFor(config, { page: 'unknown' }).url, 'https://couchside.example/');
assert.equal(metadataFor({}, { show }), null);
assert.equal(metadataFor(config, { show: { ...show, summary: '<b>Text</b>\nwith  spaces.' } }).description, 'Text with spaces.');
assert.ok(metadataFor(config, { show: { ...show, summary: 'word '.repeat(60) } }).description.endsWith('…'));
console.log('Metadata checks passed.');
