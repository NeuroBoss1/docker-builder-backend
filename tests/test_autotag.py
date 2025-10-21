import asyncio
import re
import os
import sys
import pytest
from httpx import AsyncClient

# ensure local package is importable when tests are run from the app directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app


@pytest.mark.asyncio
async def test_build_autogenerates_tag_when_missing():
    # No tag provided; dry_run enabled so no real docker calls
    payload = {
        "repo_url": "https://example.com/fake/repo.git",
        "branch": "main",
        # "tag": omitted on purpose
        "registry": "example.registry/repo/image",
        "dockerfile_path": "",
        "push": True,
        "dry_run": True,
    }

    async with AsyncClient(app=app, base_url="http://test") as ac:
        r = await ac.post('/api/build', json=payload)
        assert r.status_code == 200
        job_id = r.json()["id"]

        # poll until done
        js = None
        for _ in range(60):
            r2 = await ac.get(f"/api/build/{job_id}")
            assert r2.status_code == 200
            js = r2.json()
            if js['state'] in ('done', 'error'):
                break
            await asyncio.sleep(0.05)

        assert js is not None
        assert js['state'] == 'done'
        logs = "\n".join(js['logs'])
        # Look for the building image line and validate tag format yyyymmdd-hhmmss at the end
        # example: [dry_run] building image example.registry/repo/image:20250102-123456
        m = re.search(r"building image\s+[^:]+:(\d{8}-\d{6})", logs)
        assert m, f"Auto tag with expected pattern not found in logs: {logs}"
