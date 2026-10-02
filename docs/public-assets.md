# Public asset conventions

READMEs describe what each app does and how to run it. Keep repository layout
inventories out of them; this document explains the public asset conventions.

Each app's `public/` directory is its generated deployment bundle. Browser source
belongs in that app's `client/` directory, brand source belongs in
`assets/brand/`, and research results belong in `research/output/`. Edit those
sources and rebuild; changes made directly in `public/` are overwritten.

The three builds use `tools/public_bundle.py` for the shared folder convention.
They clear the previous bundle before writing the next one, which removes assets
that are no longer used. Generated bundles remain tracked in Git because the
deployment starts the server with the built files already present.

```sh
.venv/bin/python tools/manage.py build all
```

## Generated folders and URLs

The folders describe a file's job, rather than the app feature that happens to use
it. Not every app needs every folder.

| Public path | Purpose | Source and generation |
| --- | --- | --- |
| `index.html` | The home-page entrypoint. App servers also use it for their client-side routes. | The app's `client/index.template.html`, processed by its build. Next Watch and Couchside keep model placeholders that their server fills when it loads the model. |
| `assets/scripts/*.js` | Browser behavior, requests, state, rendering, and charts. | JavaScript modules in `client/`, copied during the build. Couchside versions module imports and page references with content hashes. |
| `assets/styles/*.css` | Layout, colors, typography, responsive behavior, and visual states. | CSS in `client/`, copied during the build. |
| `assets/icons/` | Favicons and operating-system app icons. | Brand files in `assets/brand/`, copied during the build. |
| `assets/images/` | Share previews and provider artwork. | Couchside's `assets/brand/og.jpg` and `tmdb.svg`, copied during its build. Show posters and backdrops are loaded from providers rather than duplicated into this folder. |
| `pages/*.html` | Secondary documents that have their own HTML page. | The research report is rendered by `pipeline/jobs/build_site.py`; Couchside's build writes its offline and error pages. |
| `data/*.csv`, `data/*.json` | Published research tables, rules, and audit evidence for download. | Selected files from `research/output/`, copied by `pipeline/jobs/build_site.py`. Model data, account records, and backend files are never published here. |

A module's relative import such as `./transfer.js` stays within
`assets/scripts/`. Page references use canonical nested URLs such as
`/assets/styles/style.css`, `/assets/icons/favicon.svg`, and
`/pages/research.html`; research download links use `/data/`. The research server
redirects the older `/research.html` address to the canonical report page.

Root-level files are reserved for entrypoints or platform conventions. Couchside
keeps these alongside `index.html`:

| Root file | Why it is there |
| --- | --- |
| `sw.js` | The service worker controls the entire app from scope `/`. Keeping its existing registration URL also lets installed clients upgrade to the new nested bundle. Its cached asset list points into the new folders. |
| `manifest.webmanifest` | The installed-app descriptor, linked by the page. It specifies the name, start URL, scope, colors, shortcuts, and icon URLs. |
| `robots.txt` | Crawlers discover this conventional root address. It tells them to avoid API routes. |

Favicons are linked explicitly at their canonical `assets/icons/` addresses;
older flat asset URLs are not served. App routes such as Couchside's `/search`
and `/list` are server routes backed by `index.html`, rather than extra generated
HTML files. An offline or error document belongs under `pages/`.

## Why the artwork has different formats

| Format and files | Purpose |
| --- | --- |
| SVG: `favicon.svg`, `tmdb.svg` | SVG supports a scalable canvas and works well for simple vector marks and provider logos. Next Watch and the research site use vector favicons. Couchside's favicon is a self-contained SVG wrapper around its raster artwork, so its underlying picture has a fixed resolution. |
| PNG: `apple-touch-icon.png` | A raster icon for an iOS home-screen shortcut, at the dimensions that platform expects. |
| PNG: `icon-192.png`, `icon-512.png` | Installed-app icons at explicit pixel sizes, referenced by the web manifest. |
| PNG: `icon-maskable-512.png` | An installed-app icon declared as maskable, allowing the operating system to apply its own icon shape. |
| ICO: `favicon.ico` | Small raster sizes bundled together for legacy browser tabs, linked explicitly from the page. |
| JPG: `og.jpg` | The wide social share preview. JPEG is suitable for its poster collage and keeps its download small. |

These are different delivery formats for different consumers, rather than
interchangeable duplicates. Couchside keeps its chosen raster master and the
generation script in `couchside/assets/brand/`. `make.py` produces the platform
icons and share image; its prerequisites are needed only when changing that
artwork. The ordinary app build copies the committed outputs and does not render
new artwork. TMDB's logo is retained separately as provider attribution.

## Examples of browser module boundaries

Modules stay small enough to follow by purpose; the generated scripts folder
does not add another source-code layer. These Couchside examples illustrate the
boundaries without serving as a complete file inventory:

| Source modules in `couchside/client/` | Responsibility |
| --- | --- |
| `main.js`, `start.js` | Page interaction, personal ratings and My List, initial browser state, and the first home-page request. |
| `accounts.js`, `account-state.js` | Account forms, session state, account-specific local caches, and synchronization. |
| `network.js` | Shared browser request handling. |
| `ratings.js`, `episode-ratings.js` | Provider rating labels, score formatting, and episode-rating displays. |
| `filter-state.js`, `filters.js` | Filter values and their controls. |
| `show-cards.js`, `title-sections.js` | Show cards and sections within title pages. |
| `format.js`, `gestures.js` | Display helpers and touch interaction. |
| `sw.js` | Offline caching and service-worker upgrades; the build adds the asset hashes and writes the result at the public root. |

`transfer.js`, `qr.js`, `fresh.js`, and `starters.js` have their canonical source
in `app/client/`. Couchside's build copies them into its own public scripts
folder. They share the list transfer format and QR encoder, freshness state, and
initial recommendation helpers with Next Watch. Each app deploys a complete
bundle without requiring the other app's directory at runtime.

## Where to add a file

Add browser code to `client/`; add brand masters or their committed derivatives
to `assets/brand/`. Add backend modules to `backend/`, with ranking and model
readers in `backend/recommendation/`. Research jobs belong in `pipeline/jobs/`,
and their reports, charts, and exports go to `research/output/`.

The shared public-bundle helper decides where each delivery type goes. A build
should explicitly select what it publishes and update the HTML, module imports,
manifest, and service-worker cache list together. Keep new output at the public
root only when a platform routing or discovery convention requires it.
