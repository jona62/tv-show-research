# Couchside depth studies

Four refinements of the preferred first-round concepts, created with the built-in
ImageGen tool on October 1, 2026. The colors follow the current brand's amber
`#ffc53d` through orange to coral `#ff6a3d`, on charcoal `#141414`.

| Option | Change | Exact generation prompt |
| --- | --- | --- |
| 05 Soft Seat Studio | Sculpted two-seat cushions, recessed joints and satin volume | [prompt](05-soft-seat-studio/prompt.txt) |
| 06 Afterglow Ember | Warmer coral upholstery, richer side planes and cushion contours | [prompt](06-afterglow-ember/prompt.txt) |
| 07 Sculpted C | A thick beveled C with visible extrusion and a couch-shaped base | [prompt](07-sculpted-c/prompt.txt) |
| 08 Cushion C | A softer tactile C with an inviting seat and rounded arms | [prompt](08-cushion-c/prompt.txt) |

Open `index.html` to compare each refinement with its original and inspect actual
Home Screen and favicon sizes. `current-icon.png` records the color reference.
The first-round originals remain in the parent directory.

Each concept folder holds its original 1254-square `master.png`, the exact prompt,
512/192-square app PNGs, 180-square Apple touch icon, opaque 512-square maskable
icon, 16/32/48-square favicon PNGs and a three-size `favicon.ico`. The wide Soft
Seat Studio has a small extra safety margin in its maskable export; the other
marks already fit inside the required central circle.

Run `sh designs/app-icons/round-2/export.sh` to recreate the exports with ImageMagick.
All icon sizes share each concept's artwork. Sculpted C, option 07, was selected for
production on October 1, 2026; its production copies and icon generator live in
`couchside/assets/brand`. All four second-round concepts remain available for comparison,
alongside the first-round originals.
