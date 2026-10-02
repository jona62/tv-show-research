"""Shared placement rules for generated browser bundles; no runtime dependency."""
from pathlib import Path
import hashlib
import re
import shutil

ENTRYPOINTS = frozenset(('index.html', 'sw.js', 'manifest.webmanifest', 'robots.txt'))
DIRECTORIES = ('assets/scripts', 'assets/styles', 'assets/icons', 'assets/images', 'pages', 'data')
TOUCH_FORMS_SCRIPT = 'touch-forms.js'
VIEWPORT_META = re.compile(r'''<meta\b[^>]*\bname\s*=\s*["']viewport["'][^>]*>''', re.I)


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


def copy_touch_forms(public):
    """Copy the shared early classic script and return its content version."""
    source = Path(__file__).resolve().parents[1] / 'shared/client' / TOUCH_FORMS_SCRIPT
    destination = Path(public) / output_path(TOUCH_FORMS_SCRIPT)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return hashlib.sha256(destination.read_bytes()).hexdigest()[:16]


def inject_touch_forms(page, version):
    """Set the font floor before the parser reaches any form controls.

    A classic external script respects the apps' self-only script policies. It
    deliberately has no async, defer or module attribute, so it runs immediately.
    """
    if len(VIEWPORT_META.findall(page)) != 1:
        raise ValueError('A public page needs exactly one viewport meta for the early form guard.')
    path = f'/{output_path(TOUCH_FORMS_SCRIPT)}'
    if path in page:
        raise ValueError('The early form guard is already included in this page.')
    script = f'<script src="{path}?v={version}"></script>'
    return VIEWPORT_META.sub(lambda match: match[0] + '\n' + script, page, count=1)


def bundle_styles(source, destination, *, extras=()):
    """Include the shared form-font guard in every app's generated stylesheet.

    The first declared layer wins for important rules, including against later
    component-important overrides. A layer declaration also permits a source
    stylesheet to begin with @import; the guard rules themselves go last. The
    guard also has an unlayered fallback for browsers without layer support.
    """
    guard = Path(__file__).with_name('touch-forms.css').read_text(encoding='utf-8')
    styles = '\n\n'.join(Path(path).read_text(encoding='utf-8').rstrip() for path in (source, *extras))
    Path(destination).write_text('@layer touch-forms;\n' + styles.rstrip() + '\n\n' + guard, encoding='utf-8')
