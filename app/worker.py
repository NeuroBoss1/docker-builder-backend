import os
import asyncio
from typing import Dict

from rq import get_current_job

from .builder import DockerBuilder, BuildRequest
from .store import get_job_store


def process_build(req_dict: Dict):
    """RQ worker entrypoint (synchronous). Receives serialized BuildRequest dict.

    This function runs inside an RQ worker process. It builds a Docker image using
    the existing `DockerBuilder` (which is async) by running the async builder
    inside `asyncio.run`.
    """
    redis_url = os.environ.get("REDIS_URL")
    store = get_job_store(redis_url=redis_url)

    req = BuildRequest(**req_dict)

    # synchronous wrapper: run the async builder in an event loop
    async def _run():
        builder = DockerBuilder(concurrency=4)
        await store.set_state(req.id, "running")
        try:
            async for line in builder.build(req):
                await store.append_log(req.id, line)
            await store.set_state(req.id, "done")
        except Exception as e:
            await store.set_state(req.id, "error")
            await store.append_log(req.id, str(e))

    try:
        asyncio.run(_run())
    except Exception as e:
        # best-effort logging to Redis (store may or may not be available)
        try:
            asyncio.run(store.append_log(req.id, f"worker-exception: {e}"))
            asyncio.run(store.set_state(req.id, "error"))
        except Exception:
            pass
        raise

