"""Render Couchside's icons and share image from the selected raster master.

    .venv/bin/python couchside/assets/brand/make.py

Needs ImageMagick (brew install imagemagick) and Google Chrome for the share
image, which lays real posters out as HTML. The outputs are
committed, and couchside/build.py copies them into public/, so neither the
server nor a deploy needs any of these tools.

- icon-master.png is the selected Sculpted C artwork; icon-prompt.txt
  preserves its ImageGen prompt. Every platform uses the same full-bleed,
  opaque composition, with the operating system applying its own mask.
- The SVGs are self-contained wrappers of the same artwork, retained for
  compatibility. favicon.svg embeds a compact 128-pixel PNG; the other wrappers
  embed the 512-pixel icon used by the app and share image.
"""
import base64
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'


def run(*args):
    subprocess.run(args, check=True, capture_output=True)


def raster_icon(size, out):
    run('magick', str(HERE / 'icon-master.png'), '-resize', f'{size}x{size}', '-strip', str(out))


def svg_wrapper(png):
    encoded = base64.b64encode(png.read_bytes()).decode('ascii')
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">\n'
            f'  <image width="512" height="512" href="data:image/png;base64,{encoded}"/>\n'
            '</svg>\n')


def icons():
    for size, name in ((16, 'favicon-16.png'), (32, 'favicon-32.png'), (48, 'favicon-48.png'),
                       (180, 'apple-touch-icon.png'), (192, 'icon-192.png'), (512, 'icon-512.png')):
        raster_icon(size, HERE / name)
    run('magick', *(str(HERE / f'favicon-{size}.png') for size in (16, 32, 48)),
        str(HERE / 'favicon.ico'))
    shutil.copyfile(HERE / 'icon-512.png', HERE / 'icon-maskable-512.png')
    full = svg_wrapper(HERE / 'icon-512.png')
    for name in ('icon.svg', 'icon-full.svg', 'icon-maskable.svg'):
        (HERE / name).write_text(full)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / 'favicon-128.png'
        raster_icon(128, png)
        (HERE / 'favicon.svg').write_text(svg_wrapper(png))


def share_image():
    """The picture a shared link shows: the wordmark over a wall of popular posters."""
    sys.path.insert(0, str(ROOT / 'couchside'))
    from backend.recommendation.engine import Engine
    from backend.recommendation.library import Library
    engine = Engine(ROOT / 'data/model')
    library = Library(engine, ROOT / 'couchside/assets/model/art.bin.gz')
    posters = [library.poster(i) for i in library.shelf[:40]]
    icon = (HERE / 'icon.svg').read_text()
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
    <div class="copy">{icon}<h1>Couchside</h1><p>Your next show, picked for your taste.</p>
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
