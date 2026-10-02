#!/bin/sh
# Export the second-round masters into matching platform icon sizes.
# Requires ImageMagick. Run from any directory.
set -eu
cd "$(dirname "$0")"
for concept in 05-soft-seat-studio 06-afterglow-ember 07-sculpted-c 08-cushion-c; do
  for spec in '512 icon-512' '192 icon-192' '180 apple-touch-icon' '48 favicon-48' '32 favicon-32' '16 favicon-16'; do
    set -- $spec
    magick "$concept/master.png" -resize "${1}x${1}" -strip "$concept/$2.png"
  done
  if [ "$concept" = 05-soft-seat-studio ]; then
    # This wider sofa needs a small safety margin for circular Android masks.
    magick "$concept/master.png" -resize 480x480 -background '#141414' -gravity center -extent 512x512 -strip "$concept/icon-maskable-512.png"
  else
    cp "$concept/icon-512.png" "$concept/icon-maskable-512.png"
  fi
  magick "$concept/favicon-16.png" "$concept/favicon-32.png" "$concept/favicon-48.png" "$concept/favicon.ico"
done
