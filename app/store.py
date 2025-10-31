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
        raw = None
        try:
            # hget might return bytes or str depending on client config
            raw = await self._redis.hget(key, "logs")
        except Exception:
            raw = None

        logs = []
        # Try to robustly detect and parse existing logs value
        try:
            if raw is None:
                logs = []
            else:
                # If bytes, keep bytes for detection
                if isinstance(raw, (bytes, bytearray)):
                    b = bytes(raw)
                elif isinstance(raw, str):
                    # If string contains binary-looking characters, try to treat as bytes
                    try:
                        # attempt direct json parse first
                        logs = json.loads(raw)
                    except Exception:
                        # fallback: decode as latin-1 to preserve bytes, then try gzip/zlib
                        b = raw.encode('latin-1')
                else:
                    # unknown type - coerce to string
                    try:
                        logs = json.loads(str(raw))
                    except Exception:
                        b = str(raw).encode('utf-8', errors='replace')

                # If logs not filled yet and we have bytes, analyze bytes
                if logs == [] and 'b' in locals():
                    # detect gzip
                    try:
                        import gzip, zlib
                        if len(b) >= 2 and b[0] == 0x1f and b[1] == 0x8b:
                            # gzip
                            try:
                                decompressed = gzip.decompress(b)
                                logs = json.loads(decompressed.decode('utf-8', errors='replace'))
                            except Exception:
                                # fallback to decode as text
                                logs = [decompressed.decode('utf-8', errors='replace')] if 'decompressed' in locals() else []
                        else:
                            # try zlib decompress (common for some clients)
                            try:
                                decompressed = zlib.decompress(b)
                                logs = json.loads(decompressed.decode('utf-8', errors='replace'))
                            except Exception:
                                # not compressed JSON, try to parse raw bytes as utf-8 JSON
                                try:
                                    logs = json.loads(b.decode('utf-8', errors='replace'))
                                except Exception:
                                    # fallback: treat as single log line string
                                    logs = [b.decode('utf-8', errors='replace')]
                    except Exception:
                        # any failure -> fallback
                        try:
                            logs = json.loads(raw.decode() if hasattr(raw, 'decode') else str(raw))
                        except Exception:
                            logs = [str(raw)]
        except Exception:
            logs = []

        # Ensure logs is a list
        if not isinstance(logs, list):
            logs = [str(logs)]

        # Append new line and persist
        logs.append(line)
        try:
            await self._redis.hset(key, "logs", json.dumps(logs))
        except Exception:
            # last resort: set as plain string
            try:
                await self._redis.hset(key, "logs", json.dumps([str(l) for l in logs]))
            except Exception:
                pass

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
