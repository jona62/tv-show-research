#!/bin/sh
# Export platform sizes from the four original ImageGen masters.
# Requires ImageMagick. Run from any directory.
set -eu
cd "$(dirname "$0")"
for concept in 01-soft-seat 02-screen-seat 03-afterglow 04-couchside-c; do
  for spec in '512 icon-512' '192 icon-192' '180 apple-touch-icon' '48 favicon-48' '32 favicon-32' '16 favicon-16'; do
    set -- $spec
    magick "$concept/master.png" -resize "${1}x${1}" -strip "$concept/$2.png"
  done
  # Each mark is entirely within the central 80%-diameter safe circle.
  # The full-bleed, opaque background lets the platform apply its own mask.
  cp "$concept/icon-512.png" "$concept/icon-maskable-512.png"
  magick "$concept/favicon-16.png" "$concept/favicon-32.png" "$concept/favicon-48.png" "$concept/favicon.ico"
done
