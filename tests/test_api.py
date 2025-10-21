import asyncio
import os
import sys
import pytest
from httpx import AsyncClient

# ensure local package is importable when tests are run from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app


@pytest.mark.asyncio
async def test_create_build_dry_run_and_poll():
    payload = {
        "repo_url": "https://example.com/fake/repo.git",
        "branch": "main",
        "tag": "test-tag",
        "registry": "example.registry/repo/image",
        "dockerfile_path": "",
        "push": True,
        "dry_run": True,
    }

    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post('/api/build', json=payload)
        assert r.status_code == 200
        data = r.json()
        assert 'id' in data
        job_id = data['id']

        # poll until done (with timeout)
        js = None
        for _ in range(30):
            r2 = await ac.get(f'/api/build/{job_id}')
            assert r2.status_code == 200
            js = r2.json()
            if js['state'] in ('done', 'error'):
                break
            await asyncio.sleep(0.05)

        assert js is not None
        assert js['state'] == 'done'
        assert any('[dry_run] build complete' in l for l in js['logs'])


@pytest.mark.asyncio
async def test_list_builds():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.get('/api/builds')
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

