"""Load a benchmark's runtime from a current or historical app checkout."""
import importlib
from pathlib import Path
import sys


def module(app_root, name):
    """Support the structured app tree and explicit legacy --app/--code folders."""
    app_root = Path(app_root).resolve()
    structured = app_root / 'backend' / 'recommendation' / f'{name}.py'
    legacy = app_root / f'{name}.py'
    if structured.is_file():
        package = 'backend.recommendation.'
    elif legacy.is_file():
        package = ''
    else:
        raise FileNotFoundError(f'No recommendation module {name}.py in {app_root}')
    sys.path.insert(0, str(app_root))
    return importlib.import_module(package + name)


def source_path(app_root, name):
    """The source used for a report's provenance hash."""
    app_root = Path(app_root).resolve()
    structured = app_root / 'backend' / 'recommendation' / f'{name}.py'
    return structured if structured.is_file() else app_root / f'{name}.py'
