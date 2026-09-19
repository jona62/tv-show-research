# TV Taste

Two things over one frozen TVmaze snapshot of 89,594 shows.

**[app/](app/) is Next Watch**, the web app: rate what you have watched, get
ranked picks with the reason each one surfaced, and see your taste drawn against
them. Three screens, light by default, under 50 KB on first load, works on a
phone. [Read more](app/README.md).

```sh
python3 app/build.py && python3 app/server.py
```

**[site/](site/) is the original research write-up** and its interactive
recommender, kept as published. [Live](https://tv-taste-jlvf21do.rigbox.dev/) ·
[Report](output/research-report.md) · [Notes](site/README.md).

```sh
python3 site/server.py
```

`scripts/` holds the pipeline that downloads the catalog, derives theme and genre
features, and builds the shared model both apps read. Python 3.10+; neither app
needs packages at runtime.

Data from [TVmaze](https://www.tvmaze.com/),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Similarity is
not a guarantee of enjoyment.
