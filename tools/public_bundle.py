"""Shared placement rules for generated browser bundles; no runtime dependency."""
from pathlib import Path
import shutil

ENTRYPOINTS = frozenset(('index.html', 'sw.js', 'manifest.webmanifest', 'robots.txt'))
DIRECTORIES = ('assets/scripts', 'assets/styles', 'assets/icons', 'assets/images', 'pages', 'data')


def output_path(name):
    """Map a logical bundle filename to the same purpose-based layout in every app."""
    if Path(name).name != name:
        raise ValueError(f'Expected a bundle filename, received {name!r}')
    if name in ENTRYPOINTS:
        return Path(name)
    suffix = Path(name).suffix
    if suffix == '.js':
        folder = 'assets/scripts'
    elif suffix == '.css':
        folder = 'assets/styles'
    elif suffix == '.ico' or name.startswith(('favicon', 'apple-touch-icon', 'icon-')):
        folder = 'assets/icons'
    elif suffix in ('.svg', '.png', '.jpg', '.jpeg', '.webp'):
        folder = 'assets/images'
    elif suffix == '.html':
        folder = 'pages'
    elif suffix in ('.csv', '.json'):
        folder = 'data'
    else:
        raise ValueError(f'No public asset group for {name!r}')
    return Path(folder) / name


def reset_public(folder):
    """Regenerate only a public build directory, removing obsolete output files."""
    folder = Path(folder)
    if folder.name != 'public' or folder.is_symlink():
        raise ValueError('The generated output must be a public directory, not a symlink.')
    if folder.exists():
        shutil.rmtree(folder)
    for relative in ('', *DIRECTORIES):
        (folder / relative).mkdir(parents=True, exist_ok=True)
