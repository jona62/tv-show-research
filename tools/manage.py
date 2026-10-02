"""Build, run and check the apps, or launch a research pipeline job."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
APPS = ('app', 'couchside', 'site')
SERVICES = (*APPS, 'pipeline')


def launch(command, directory=ROOT):
    return subprocess.call([str(part) for part in command], cwd=directory)


def build(app):
    if app == 'site':
        return launch([sys.executable, ROOT / 'pipeline/run.py', 'build_site'])
    return launch([sys.executable, 'build.py'], ROOT / app)


def check(service):
    """Isolate each suite so independent deployed backend packages never collide."""
    folder = ROOT / service / 'tests'
    paths = sorted([*folder.glob('test_*.py'), *folder.glob('test_*.mjs')])
    failures = 0
    env = os.environ.copy()
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS'):
        env.setdefault(name, '1')
    if not paths:
        print(f'{service}: no standalone test suites', flush=True)
    for path in paths:
        runtime = sys.executable if path.suffix == '.py' else 'node'
        with tempfile.TemporaryFile(mode='w+') as log:
            try:
                result = subprocess.run([runtime, str(path)], cwd=ROOT, env=env, stdout=log,
                                        stderr=subprocess.STDOUT)
            except FileNotFoundError:
                print(f'{path.relative_to(ROOT)}: missing {runtime}', flush=True)
                failures += 1
                continue
            print(f'{path.relative_to(ROOT)}: {"passed" if result.returncode == 0 else "FAILED"}', flush=True)
            if result.returncode:
                log.seek(0)
                print(''.join(log.readlines()[-60:]), flush=True)
                failures += 1
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command, choices in (('build', (*APPS, 'all')), ('run', SERVICES),
                             ('test', (*SERVICES, 'all'))):
        commands.add_parser(command).add_argument('target', choices=choices)
    for command, folder in (('job', 'pipeline/jobs'), ('bench', 'pipeline/bench')):
        child = commands.add_parser(command)
        names = sorted(path.stem for path in (ROOT / folder).glob('*.py')
                       if path.stem not in ('__init__', 'runtime', 'large_lists', 'stub_tiers'))
        child.add_argument('name', choices=names)
        child.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'build':
        for app in APPS if args.target == 'all' else (args.target,):
            result = build(app)
            if result:
                return result
        return 0
    if args.command == 'run':
        module = 'backend.refresher' if args.target == 'pipeline' else 'backend.server'
        return launch([sys.executable, '-m', module], ROOT / args.target)
    if args.command == 'test':
        targets = SERVICES if args.target == 'all' else (args.target,)
        return int(sum(check(service) for service in targets) > 0)
    if args.command == 'job':
        return launch([sys.executable, ROOT / 'pipeline/run.py', args.name, *args.args])
    return launch([sys.executable, ROOT / 'pipeline/bench' / (args.name + '.py'), *args.args])


if __name__ == '__main__':
    raise SystemExit(main())
