"""Follow a model that is replaced while the server runs.

The refresher builds each new model into a directory of its own, writes build.json
there last, then moves the MODEL_DIR link to it. A server loads its model once, at
startup, so rather than reload in place it leaves, and the host starts it again on
the new model. Nothing here reads the model; it only watches where the link leads.
Couchside's build.py copies this file, like engine.py.
"""
import math
import os
import sys
import threading
import time


def moved(model_dir, loaded):
    """Where MODEL_DIR now leads, when that is a complete model other than the one
    loaded, else None. A directory without build.json is still being written and one
    that is gone is no model at all, so neither is ever a reason to leave."""
    target = os.path.realpath(model_dir)
    if target != os.fspath(loaded) and os.path.isfile(os.path.join(target, 'build.json')):
        return target
    return None


def watch(model_dir, loaded, poll=60.0, delay=0.0, sleep=time.sleep, leave=os._exit, say=None):
    """Check every poll seconds. Once the model has moved, wait delay seconds, check that
    it still has, say so in one line and leave with status 0, so the host restarts this
    process on the new model. Tests pass their own sleep, leave and say."""
    while True:
        sleep(poll)
        if not moved(model_dir, loaded):
            continue
        sleep(delay)
        target = moved(model_dir, loaded)
        if target:
            (say or tell)(f'The model moved from {os.fspath(loaded)} to {target}. '
                          'Exiting so the service restarts on it.')
            leave(0)
            return target


def start(model_dir, loaded, environ=os.environ):
    """Follow MODEL_DIR on a daemon thread, checking every MODEL_POLL_SECONDS (60) and
    waiting RELOAD_DELAY_SECONDS (0) before leaving. A poll of 0 turns following off."""
    poll = seconds(environ.get('MODEL_POLL_SECONDS'), 60.0)
    delay = seconds(environ.get('RELOAD_DELAY_SECONDS'), 0.0)
    if not poll:
        return None
    thread = threading.Thread(target=watch, args=(model_dir, loaded, poll, delay), name='follow-model', daemon=True)
    thread.start()
    return thread


def seconds(value, default):
    """A duration from the environment: a number of seconds, 0 or more, else the default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) and number >= 0 else default


def tell(line):
    # Written and flushed at once: os._exit skips the buffers.
    sys.stderr.write(line + '\n')
    sys.stderr.flush()
