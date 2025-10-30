import os
import asyncio
import json
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


def process_deploy(job_id: str, mappings: Dict):
    """RQ worker entrypoint for deploy tasks.

    Receives job_id and mappings dict. Runs ansible-playbook locally and streams
    output into the job store (logs)."""
    redis_url = os.environ.get("REDIS_URL")
    store = get_job_store(redis_url=redis_url)

    async def _run():
        await store.set_state(job_id, "running")
        try:
            extra_vars = json.dumps(mappings)
            # ensure playbook receives a top-level 'mappings' variable
            try:
                # if mappings looks like a dict, wrap it
                if isinstance(mappings, (str, bytes)):
                    # try to parse JSON string
                    parsed = json.loads(mappings) if isinstance(mappings, str) else json.loads(mappings.decode('utf-8'))
                    wrapper = {'mappings': parsed}
                else:
                    wrapper = {'mappings': mappings}
                extra_vars = json.dumps(wrapper)
            except Exception:
                # fallback: send mappings as-is
                extra_vars = json.dumps({'mappings': mappings})

            # Find playbook path
            candidates = [
                os.path.join(os.getcwd(), 'deploy', 'playbook.yml'),
                os.path.join(os.getcwd(), 'playbook.yml'),
                os.path.join(os.path.dirname(__file__), '..', 'deploy', 'playbook.yml')
            ]
            playbook = None
            for c in candidates:
                try:
                    if os.path.exists(c):
                        playbook = c
                        break
                except Exception:
                    pass

            if not playbook:
                msg = 'No ansible playbook found (searched deploy/playbook.yml, playbook.yml)'
                await store.append_log(job_id, msg)
                await store.set_state(job_id, 'error')
                return

            cmd = [
                'ansible-playbook',
                playbook,
                '-i', 'localhost,',
                '--connection', 'local',
                '--extra-vars', extra_vars
            ]

            env = os.environ.copy()
            # try to read deploy meta (user) from Redis if available
            try:
                if redis_url:
                    import redis as redis_sync
                    rconn = redis_sync.from_url(redis_url)
                    try:
                        meta = rconn.hgetall(f"deploy:{job_id}") or {}
                        user = meta.get('user')
                        if user:
                            env['DEPLOY_USER_SUB'] = user
                    except Exception:
                        pass
            except Exception:
                pass

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env
            )

            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors='replace').rstrip()
                await store.append_log(job_id, text)

            rc = await proc.wait()
            if rc == 0:
                await store.set_state(job_id, 'done')
            else:
                await store.set_state(job_id, 'error')
                await store.append_log(job_id, f'ansible-playbook exited with code {rc}')

        except Exception as e:
            await store.set_state(job_id, 'error')
            await store.append_log(job_id, str(e))

    try:
        asyncio.run(_run())
    except Exception as e:
        try:
            asyncio.run(store.append_log(job_id, f"worker-exception: {e}"))
            asyncio.run(store.set_state(job_id, "error"))
        except Exception:
            pass
        raise
