# TV Taste

Three apps over the TVmaze catalogue of TV series. Next Watch and Couchside read
a model rebuilt every night; the research site keeps the 89,594-show snapshot it
was published with.

**[app/](app/) is Next Watch**, the web app: rate what you have watched, get
ranked picks with the reason each one surfaced, and see your taste drawn against
them. Four screens, light by default, about 145 KB on first load, works on a
phone. Lists stay in your browser and can be moved by link or file.
[Read more](app/README.md).

**[couchside/](couchside/) is Couchside**, the same recommender dressed as a
streaming service: a hero and rows built from what you rate, title pages with
cast, episodes and more like this, and My List. Optional email/password accounts
sync ratings and My List across devices. It is for finding your next show.
[Read more](couchside/README.md).

**[site/](site/) is the original research write-up** and its interactive
recommender, kept as published. [Live](https://tv-taste-jlvf21do.rigbox.dev/) ·
[Report](research/output/research-report.md) · [Notebook](research/tv_taste_research.ipynb) · [Notes](site/README.md).

## Common commands

Local development needs Python 3.10+. Each app's README covers dependencies and
setup. Run these from the repository root with the project's Python environment:

```sh
.venv/bin/python tools/manage.py build all
.venv/bin/python tools/manage.py run couchside
.venv/bin/python tools/manage.py test all
```

| Command | Supported targets |
| --- | --- |
| `build <target>` | `app`, `couchside`, `site`, `all` |
| `run <target>` | `app`, `couchside`, `site`, `pipeline` |
| `test <target>` | `app`, `couchside`, `site`, `pipeline`, `tools`, `all` |

The helper selects the right working directory and entrypoint. It also runs
pipeline jobs and [recommendation benchmarks](pipeline/bench/README.md).

Shared browser checks run with `test tools` and are included in `test all`.
Install their WebKit browser once with
`.venv/bin/python -m playwright install webkit`.

## Fresh recommendations

Next Watch and Couchside share a recommender. It compares plots, themes, genres,
franchises, and makers, then considers what a person's whole list leans toward:
languages, formats, networks, eras, and other patterns. Ratings and dislikes shape
those picks. A list with several tastes can receive recommendations for each,
and long lists use precomputed neighbors to keep requests responsive.

The shared catalog and model refresh nightly. A new model is checked before
publication, and a failed build leaves the previous one available. The research
site keeps the snapshot used for its published study. With provider credentials
configured, Couchside also shows trailers, streaming availability, cast, and
provider ratings. Provider details do not change recommendation rankings.

[Recommendation practice](docs/recommender-practice.md) describes the approach
and its evaluation. [Public asset conventions](docs/public-assets.md) explains
where browser files come from, how builds group them, and why the icon formats
differ. Each app's README covers its local setup and checks.

## Deployment

Rigbox uses the root `rig.yaml`. A push to `main` deploys the changed apps. Build
and commit the generated public bundles with their sources before deploying;
the servers serve those existing bundles.

The shared model, provider caches, and Couchside accounts use the persistent
`data` volume. Guest lists remain in each browser, and signed-in Couchside lists
sync between devices. See [Couchside's deployment notes](couchside/README.md) for
account configuration and operational details.

Data from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), and
[Wikidata](https://www.wikidata.org/),
[CC0](https://creativecommons.org/publicdomain/zero/1.0/). Similarity is not a
guarantee of enjoyment.
