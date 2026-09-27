"""Render Couchside's icons and share image from the SVGs beside this file.

    .venv/bin/python couchside/brand/make.py

Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick) and Google
Chrome for the share image, which lays real posters out as HTML. The outputs are
committed, and couchside/build.py copies them into public/, so neither the
server nor a deploy needs any of these tools.

- small.svg is the mark drawn for 16 to 48 pixels: an outline sofa that stays
  legible in a browser tab. It becomes favicon.svg and favicon.ico.
- icon.svg is the app icon with its own rounded corners, for Android and the
  manifest. icon-full.svg fills the square for Apple, which rounds the corners
  itself. icon-maskable.svg keeps the sofa inside the circle Android may crop to.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def svg_to_png(source, size, out):
    run('rsvg-convert', '-w', str(size), '-h', str(size), str(HERE / source), '-o', str(out))


def icons():
    with tempfile.TemporaryDirectory() as tmp:
        sizes = []
        for size in (16, 32, 48):
            png = Path(tmp) / f'{size}.png'
            svg_to_png('small.svg', size, png)
            sizes.append(str(png))
        run('magick', *sizes, str(HERE / 'favicon.ico'))
    shutil.copyfile(HERE / 'small.svg', HERE / 'favicon.svg')
    svg_to_png('icon-full.svg', 180, HERE / 'apple-touch-icon.png')
    svg_to_png('icon.svg', 192, HERE / 'icon-192.png')
    svg_to_png('icon.svg', 512, HERE / 'icon-512.png')
    svg_to_png('icon-maskable.svg', 512, HERE / 'icon-maskable-512.png')


def share_image():
    """The picture a shared link shows: the wordmark over a wall of popular posters."""
    sys.path.insert(0, str(ROOT / 'couchside'))
    from engine import Engine
    from library import Library
    engine = Engine(ROOT / 'model')
    library = Library(engine, ROOT / 'couchside' / 'art.bin.gz')
    posters = [library.poster(i) for i in library.shelf[:40]]
    sofa = (HERE / 'icon.svg').read_text()
    tiles = ''.join(f'<img src="{url}" alt="">' for url in posters)
    page = f"""<!doctype html><meta charset="utf-8"><style>
    html,body{{margin:0;width:1200px;height:630px;overflow:hidden;background:#141414}}
    body{{font-family:-apple-system,BlinkMacSystemFont,"Helvetica Neue",Arial,sans-serif;color:#fff}}
    .wall{{position:absolute;left:470px;top:-150px;width:980px;display:grid;grid-template-columns:repeat(6,146px);gap:14px;
      transform:rotate(-9deg);transform-origin:top left}}
    .wall img{{width:146px;height:219px;object-fit:cover;border-radius:8px;display:block}}
    .shade{{position:absolute;inset:0;background:linear-gradient(90deg,#141414 0,#141414 36%,#141414d0 50%,#14141440 72%,#14141410 100%),
      linear-gradient(0deg,#141414 0,#14141400 30%)}}
    .copy{{position:absolute;left:72px;top:0;bottom:0;width:560px;display:flex;flex-direction:column;justify-content:center}}
    .copy svg{{width:112px;height:112px;margin-bottom:26px}}
    h1{{margin:0;font-size:88px;line-height:1;font-weight:900;letter-spacing:.06em;text-transform:uppercase;
      background:linear-gradient(90deg,#ffb020,#ff6a3d);-webkit-background-clip:text;background-clip:text;color:transparent}}
    p{{margin:22px 0 0;font-size:34px;line-height:1.25;font-weight:700;text-wrap:balance}}
    small{{display:block;margin-top:18px;font-size:23px;color:#b8b8b8;font-weight:500}}
    </style><div class="wall">{tiles}</div><div class="shade"></div>
    <div class="copy">{sofa}<h1>Couchside</h1><p>Your next show, picked for your taste.</p>
    <small>{engine.n:,} series · trailers · where to watch · My List</small></div>"""
    with tempfile.TemporaryDirectory() as tmp:
        html, png = Path(tmp) / 'share.html', Path(tmp) / 'share.png'
        html.write_text(page)
        run(CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--window-size=1200,630',
            '--virtual-time-budget=15000', f'--screenshot={png}', html.as_uri())
        run('magick', str(png), '-strip', '-quality', '84', str(HERE / 'og.jpg'))


if __name__ == '__main__':
    icons()
    share_image()
    for name in ('favicon.ico', 'favicon.svg', 'apple-touch-icon.png', 'icon-192.png', 'icon-512.png',
                 'icon-maskable-512.png', 'og.jpg'):
        print(f'  {name:<22} {(HERE / name).stat().st_size / 1000:6.1f} KB')
