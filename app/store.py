import asyncio
import json
from typing import Dict, List, Optional

try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None


class JobStore:
    async def create_job(self, job_id: str, state: str, logs: List[str]) -> None:
        raise NotImplementedError

    async def set_state(self, job_id: str, state: str) -> None:
        raise NotImplementedError

    async def append_log(self, job_id: str, line: str) -> None:
        raise NotImplementedError

    async def get_job(self, job_id: str) -> Optional[Dict]:
        raise NotImplementedError

    async def list_jobs(self) -> List[Dict]:
        raise NotImplementedError


class InMemoryJobStore(JobStore):
    def __init__(self):
        self._jobs: Dict[str, Dict] = {}
        self._lock = asyncio.Lock()

    async def create_job(self, job_id: str, state: str, logs: List[str]) -> None:
        async with self._lock:
            self._jobs[job_id] = {"id": job_id, "state": state, "logs": list(logs)}

    async def set_state(self, job_id: str, state: str) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["state"] = state

    async def append_log(self, job_id: str, line: str) -> None:
        async with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["logs"].append(line)

    async def get_job(self, job_id: str) -> Optional[Dict]:
        async with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return None
            return {"id": j["id"], "state": j["state"], "logs": list(j["logs"]) }

    async def list_jobs(self) -> List[Dict]:
        async with self._lock:
            return [ {"id": j["id"], "state": j["state"], "logs": list(j["logs"]) } for j in self._jobs.values() ]


class RedisJobStore(JobStore):
    def __init__(self, redis_url: str):
        if aioredis is None:
            raise RuntimeError("redis.asyncio is not available")
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._jobs_set_key = "jobs:ids"

    async def create_job(self, job_id: str, state: str, logs: List[str]) -> None:
        await self._redis.hset(f"job:{job_id}", mapping={"id": job_id, "state": state, "logs": json.dumps(list(logs))})
        await self._redis.sadd(self._jobs_set_key, job_id)

    async def set_state(self, job_id: str, state: str) -> None:
        await self._redis.hset(f"job:{job_id}", "state", state)

    async def append_log(self, job_id: str, line: str) -> None:
        key = f"job:{job_id}"
        raw = await self._redis.hget(key, "logs")
        try:
            logs = json.loads(raw) if raw else []
        except Exception:
            logs = []
        logs.append(line)
        await self._redis.hset(key, "logs", json.dumps(logs))

    async def get_job(self, job_id: str) -> Optional[Dict]:
        key = f"job:{job_id}"
        data = await self._redis.hgetall(key)
        if not data:
            return None
        raw = data.get("logs") or "[]"
        try:
            logs = json.loads(raw)
        except Exception:
            logs = []
        return {"id": data.get("id", job_id), "state": data.get("state", "queued"), "logs": logs}

    async def list_jobs(self) -> List[Dict]:
        ids = await self._redis.smembers(self._jobs_set_key) or []
        res = []
        for jid in ids:
            job = await self.get_job(jid)
            if job:
                res.append(job)
        return res


def get_job_store(redis_url: Optional[str] = None) -> JobStore:
    if redis_url and aioredis is not None:
        try:
            return RedisJobStore(redis_url)
        except Exception:
            return InMemoryJobStore()
    return InMemoryJobStore()

