"""Production HTTP transport. Workers are spawned, never forked with live DBs."""
import os
import sys


def launch():
    # Multiprocessing re-executes __main__ as __mp_main__. Use this light entry
    # module so spawned workers do not load server/model once during bootstrap
    # and a second time through the ASGI factory.
    os.execv(sys.executable, [sys.executable, '-m', 'backend.runtime'])


def main():
    os.environ.setdefault('OPENBLAS_NUM_THREADS', '1')
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    import uvicorn
    workers = max(1, int(os.environ.get('COUCHSIDE_WORKERS', '1')))
    os.environ['COUCHSIDE_WORKERS'] = str(workers)
    uvicorn.run('backend.asgi:create_app', factory=True,
                host=os.environ.get('HOST', '0.0.0.0'), port=int(os.environ.get('PORT', '8082')),
                workers=workers, proxy_headers=False, access_log=False,
                server_header=False, timeout_keep_alive=5, timeout_graceful_shutdown=20,
                # Loading the immutable catalogue can hold the GIL beyond the
                # default five-second watchdog on a contended compute host.
                timeout_worker_healthcheck=60,
                backlog=2048, limit_concurrency=12000, ws='none')


if __name__ == '__main__':
    main()
