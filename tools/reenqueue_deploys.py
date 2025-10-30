#!/usr/bin/env python3
"""Helper: re-enqueue deploy jobs that were created but not enqueued in RQ.

Usage (from repo root, with venv activated):

export REDIS_URL="redis://localhost:6379/0"
export PYTHONPATH=.
python tools/reenqueue_deploys.py

This script will:
 - read Redis set `jobs:ids`
 - for each id, check `deploy:<id>` hash and read field `mappings`
 - if mappings found, enqueue `app.worker.process_deploy(job_id, mappings)` into RQ default queue

Be careful: this will re-run deploy playbooks for listed job ids.
"""
import os
import json
import sys

try:
    import redis
    from rq import Queue
except Exception as e:
    print('Missing dependency:', e)
    print('Run: pip install redis rq')
    sys.exit(1)

REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
print('Using REDIS_URL=', REDIS_URL)

r = redis.from_url(REDIS_URL)
q = Queue(connection=r)

jobs = r.smembers('jobs:ids') or set()
if not jobs:
    print('No jobs found in jobs:ids')
    sys.exit(0)

print(f'Found {len(jobs)} jobs in jobs:ids')
requeued = 0
skipped = 0

for jid in sorted(jobs):
    # redis-py returns bytes in py3 unless decode_responses=True; handle both
    if isinstance(jid, bytes):
        jid = jid.decode()
    deploy_key = f'deploy:{jid}'
    if r.exists(deploy_key):
        try:
            mappings_json = r.hget(deploy_key, 'mappings')
            if mappings_json is None:
                print(f'{jid}: deploy:{jid} present but no mappings field, skipping')
                skipped += 1
                continue
            if isinstance(mappings_json, bytes):
                mappings_json = mappings_json.decode('utf-8')
            mappings = json.loads(mappings_json)
            # import worker callable
            # We import lazily so script can fail fast if not runnable
            import importlib
            worker_mod = importlib.import_module('app.worker')
            # Enqueue callable
            q.enqueue(worker_mod.process_deploy, jid, mappings, job_timeout=3600)
            print(f'{jid}: enqueued process_deploy')
            requeued += 1
        except Exception as e:
            print(f'{jid}: failed to enqueue: {e}')
            skipped += 1
    else:
        print(f'{jid}: no deploy metadata found (deploy:{jid}), skipping')
        skipped += 1

print(f'Done. Requeued: {requeued}. Skipped: {skipped}.')

