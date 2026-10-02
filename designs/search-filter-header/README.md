# Search and filters in the Couchside title row

Run the existing app preview on port 8766, then `python3 designs/search-filter-header/serve.py`.
Open http://localhost:8783/options for four choices, with resting and focused mobile headers.
Links beneath each choice show it over Home, Browse, New & Popular, My List and Search.
These are local mockups; the deployed app and its saved list remain untouched.

1. **Inline expansion (recommended):** visible field, funnel divided within it;
   focus uses the profile button's space while the wordmark remains.
2. **Full-width focus:** typing temporarily replaces the header's wordmark and
   profile with a wide field and back arrow.
3. **Compact control:** one small outlined control with search and funnel icons;
   search expands into the same inline field.
4. **Inset filter:** the funnel sits in a small inset button; focus uses the
   existing amber outline and expands inline.

The native dropdown/bottom sheet stays in use. Search remains universal, the funnel
filters the current page, and My List retains its own local search. Filter actions
and search never require each other. A filled field stays expanded; Escape exits
focus, and reduced-motion preferences disable transitions. On small tablets,
section links occupy the second row while search shares the wordmark's first row.
