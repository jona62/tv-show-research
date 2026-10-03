// Navigation keeps the public metadata in step with the server-rendered page.
const description = 'Find your next TV show, keep a watchlist, and explore episode ratings and comparisons with Couchside.';
const plain = value => String(value || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
const snippet = value => {
  const text = plain(value);
  return text.length <= 200 ? text : text.slice(0, 200).replace(/\s+\S*$/, '') + '…';
};

export function metadataFor(config, { page = 'home', show = null, params = new URLSearchParams() } = {}) {
  if (!config?.origin || !config.pages) return null;
  const route = config.pages[page] || config.pages.home;
  const value = { ...route, title: route.title, ogTitle: route.title, url: config.origin + route.path,
    image: config.origin + '/assets/images/og.jpg', imageAlt: 'The Couchside wordmark beside a wall of TV show posters',
    card: 'summary_large_image', noindex: Boolean(route.private || params.has('episode') || params.has('person') || params.has('compare')) };
  if (show?.name && Number.isInteger(show.id) && show.id > 0) {
    Object.assign(value, { title: `${show.name} · Couchside`, heading: show.name,
      ogTitle: `${show.name}${show.year ? ` (${show.year})` : ''} on Couchside`,
      description: snippet(show.summary) || description, url: `${config.origin}/?show=${show.id}`,
      image: show.art || show.poster || value.image, imageAlt: `Poster for ${show.name}`, card: 'summary',
      noindex: params.has('episode') || params.has('person') });
    value.schema = { '@context': 'https://schema.org', '@type': 'TVSeries', url: value.url, name: show.name,
      description: value.description, image: value.image, genre: show.genres || [] };
    if (/^\d{4}-\d{2}-\d{2}$/.test(show.premiered || '')) value.schema.datePublished = show.premiered;
    if (show.url) value.schema.sameAs = show.url;
  } else if (params.has('show')) value.noindex = true;
  else if (route.path === '/') value.schema = { '@context': 'https://schema.org', '@graph': [
    { '@type': 'WebSite', '@id': config.origin + '/#website', url: config.origin + '/', name: 'Couchside', description },
    { '@type': 'WebApplication', name: 'Couchside', url: config.origin + '/', description,
      applicationCategory: 'EntertainmentApplication', operatingSystem: 'Any', browserRequirements: 'Requires JavaScript' }] };
  else value.schema = { '@context': 'https://schema.org', '@type': 'CollectionPage', url: value.url,
    name: value.heading, description: value.description, isPartOf: { '@id': config.origin + '/#website' } };
  return value;
}

function meta(kind, key, value) {
  let node = document.head.querySelector(`meta[${kind}="${key}"]`);
  if (!node) {
    node = document.createElement('meta');
    node.setAttribute(kind, key);
    document.head.append(node);
  }
  node.content = value;
}

export function updateMetadata(state, boot = null) {
  if (!boot) {
    try { boot = JSON.parse(document.getElementById('boot')?.textContent || '{}'); }
    catch { return; }
  }
  const params = new URLSearchParams(location.search);
  // A direct shared link already has the correct metadata while its show loads.
  if (params.has('show') && !state?.show?.name) return;
  const value = metadataFor(boot.seo, { ...state, params });
  if (!value) return;
  if (!state?.preserveTitle) document.title = value.title;
  meta('name', 'description', value.description);
  meta('name', 'robots', value.noindex ? 'noindex, follow' : 'index, follow, max-image-preview:large');
  const tags = { title: value.ogTitle, description: value.description, image: value.image, 'image:alt': value.imageAlt };
  for (const [key, text] of Object.entries(tags)) {
    meta('property', `og:${key}`, text);
    meta('name', `twitter:${key}`, text);
  }
  meta('property', 'og:url', value.url);
  meta('property', 'og:site_name', 'Couchside');
  meta('property', 'og:type', state?.show?.name ? 'video.tv_show' : 'website');
  for (const [key, size] of [['width', '1200'], ['height', '630']]) {
    if (state?.show?.name) document.head.querySelector(`meta[property="og:image:${key}"]`)?.remove();
    else meta('property', `og:image:${key}`, size);
  }
  meta('name', 'twitter:card', value.card);
  let canonical = document.head.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.rel = 'canonical';
    document.head.append(canonical);
  }
  canonical.href = value.url;
  let schema = document.getElementById('page-schema');
  if (!schema) {
    schema = document.createElement('script');
    schema.type = 'application/ld+json';
    schema.id = 'page-schema';
    document.head.append(schema);
  }
  schema.textContent = JSON.stringify(value.schema || {});
}
