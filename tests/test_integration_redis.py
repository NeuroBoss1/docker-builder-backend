import os
import threading
import pytest

# Integration test: requires a running Redis (provide REDIS_URL env var), otherwise skipped.
REDIS_URL = os.environ.get("REDIS_URL")

pytestmark = pytest.mark.skipif(not REDIS_URL, reason="Skipping integration tests: REDIS_URL not set")


def test_enqueue_and_process_with_rq():
    import redis as redis_sync
    from rq import Queue, SimpleWorker
    from httpx import AsyncClient

    # ensure app is imported after REDIS_URL is set
    from app import main as app_main
    app = app_main.app

    # flush Redis DB used by test
    conn = redis_sync.from_url(REDIS_URL)
    conn.flushdb()

    queue = Queue(connection=conn)

    # worker runner
    def run_worker():
        w = SimpleWorker([queue], connection=conn)
        # burst mode: process all queued jobs then exit
        w.work(burst=True)

    payload = {
        "repo_url": "https://example.com/fake/repo.git",
        "branch": "main",
        "tag": "test-tag",
        "registry": "example.registry/repo/image",
        "dockerfile_path": "",
        "push": True,
        "dry_run": True,
    }

    # Send request to enqueue job
    import asyncio

    async def client_flow():
        async with AsyncClient(app=app, base_url="http://test") as ac:
            r = await ac.post('/api/build', json=payload)
            assert r.status_code == 200
            data = r.json()
            job_id = data['id']

            # start worker thread to process enqueued jobs
            t = threading.Thread(target=run_worker)
            t.start()
            t.join(timeout=30)

            # poll for job completion
            js = None
            for _ in range(60):
                r2 = await ac.get(f'/api/build/{job_id}')
                assert r2.status_code == 200
                js = r2.json()
                if js['state'] in ('done', 'error'):
                    break
                await asyncio.sleep(0.1)

            assert js is not None
            assert js['state'] == 'done'
            assert any('[dry_run] build complete' in l for l in js['logs'])

    asyncio.get_event_loop().run_until_complete(client_flow())
