"""Sample an owned Linux server and its workers without collecting request data."""
from argparse import ArgumentParser
from pathlib import Path
import json
import os
import time


def process(pid):
    try:
        root = Path('/proc') / str(pid)
        fields = (root / 'stat').read_text().rsplit(')', 1)[1].split()
        return {'pid': pid, 'parent': int(fields[1]),
                'cpu_seconds': (int(fields[11]) + int(fields[12])) / os.sysconf('SC_CLK_TCK'),
                'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE'),
                'threads': int(fields[17]), 'fds': len(list((root / 'fd').iterdir()))}
    except (OSError, ValueError, IndexError):
        return None


def snapshot(parent):
    processes = [value for path in Path('/proc').iterdir()
                 if path.name.isdecimal() and (value := process(int(path.name)))]
    selected = {parent}
    while children := {p['pid'] for p in processes if p['parent'] in selected} - selected:
        selected.update(children)
    workers = [p for p in processes if p['pid'] in selected]
    cpu = [int(value) for value in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    memory = {parts[0].rstrip(':'): int(parts[1]) * 1024
              for line in Path('/proc/meminfo').read_text().splitlines() if len(parts := line.split()) >= 2}
    return {'processes': workers, 'rss_sum_bytes': sum(p['rss_bytes'] for p in workers),
            'threads': sum(p['threads'] for p in workers), 'fds': sum(p['fds'] for p in workers),
            'cpu_seconds': sum(p['cpu_seconds'] for p in workers), 'host_cpu_ticks': cpu,
            'memory_available_bytes': memory.get('MemAvailable'),
            'memory_total_bytes': memory.get('MemTotal')}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--pid-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=240)
    args = parser.parse_args()
    parent = int(args.pid_file.read_text().strip())
    began, previous = time.monotonic(), None
    with args.output.open('w') as output:
        while (elapsed := time.monotonic() - began) < args.seconds:
            current = {'seconds': elapsed, 'timestamp': time.time(), **snapshot(parent)}
            if previous:
                current['process_cpu_percent'] = max(0, 100 * (current['cpu_seconds'] - previous['cpu_seconds']) /
                                                    (elapsed - previous['seconds']))
                delta = [a - b for a, b in zip(current['host_cpu_ticks'], previous['host_cpu_ticks'])]
                total = sum(delta)
                current['host_steal_percent'] = 100 * delta[7] / total if total else 0
            output.write(json.dumps(current, separators=(',', ':')) + '\n')
            output.flush()
            previous = current
            if not current['processes']:
                break
            time.sleep(1)


if __name__ == '__main__':
    main()
