"""Run a pipeline job within its package: python pipeline/run.py build_model."""
from pathlib import Path
import argparse
import runpy
import sys


def main():
    names = sorted(path.stem for path in (Path(__file__).parent / 'jobs').glob('*.py') if path.stem != '__init__')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', choices=names)
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    sys.argv = [args.job, *args.args]
    runpy.run_module('jobs.' + args.job, run_name='__main__')


if __name__ == '__main__':
    main()
