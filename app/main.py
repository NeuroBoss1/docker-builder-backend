import asyncio
import uuid
import os
import json
from typing import Dict, Optional, Any

# Load environment file from repo root (named `env`) so os.environ populated when app starts.
# Uses python-dotenv if available; otherwise falls back to default env vars.
_env_path = None
try:
    from dotenv import load_dotenv
    from pathlib import Path
    # project root is parent of `app` dir
    _proj_root = Path(__file__).resolve().parent.parent
    _env_path = _proj_root / 'env'
    if _env_path.exists():
        load_dotenv(_env_path)
    else:
        # fallback: try to load default .env if present
        load_dotenv()
except Exception:
    # python-dotenv not installed or failed to load; proceed, relying on existing env
    _env_path = None
    pass

# Emit a small log/print so it's easy to verify env loading when running uvicorn
try:
    import logging
    _logger = logging.getLogger("app.env")
    if _env_path and _env_path.exists():
        _logger.info(f"Loaded env file: {_env_path}")
    else:
        _logger.info("No env file loaded via python-dotenv (relying on process env vars)")
    # also log a key variable
    _logger.info(f"REDIS_URL={os.environ.get('REDIS_URL')}")
except Exception:
    # best-effort logging only
    try:
        print(f"REDIS_URL={os.environ.get('REDIS_URL')}")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .builder import DockerBuilder, BuildRequest
from .store import get_job_store, JobStore

# optionally use redis + rq for background worker enqueueing
try:
    import redis as redis_sync
    from rq import Queue
except Exception:
    redis_sync = None
    Queue = None

# try to import async redis for non-blocking storage of user data
try:
    import redis.asyncio as aioredis
except Exception:
    aioredis = None

# Google id_token verification (optional)
try:
    from google.oauth2 import id_token as google_id_token
    from google.auth.transport import requests as google_requests
except Exception:
    google_id_token = None
    google_requests = None

# HTTP client
import httpx

# JWT for internal tokens (optional)
try:
    import jwt
except Exception:
    jwt = None

app = FastAPI(title="Docker Builder Service")

# Allow CORS for simple local use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# configuration
JWT_SECRET = os.environ.get("JWT_SECRET", "dev_jwt_secret_change_me")
JWT_ALG = "HS256"
REDIS_URL = os.environ.get('REDIS_URL')
PORT_APP = os.environ.get('PORT_APP', 8998)
# RQ queue (None if not available)
_queue = None
if redis_sync is not None and Queue is not None and REDIS_URL:
    try:
        _rq_conn = redis_sync.from_url(REDIS_URL)
        _queue = Queue(connection=_rq_conn)
    except Exception:
        _queue = None

# redis async client for user data (optional)
_aredis_client = None

# We'll initialize the async redis client on application startup so we can
# perform an async ping and log detailed errors if initialization fails.


@app.on_event("startup")
async def init_async_redis():
    global _aredis_client
    import logging
    logger = logging.getLogger("app.init")
    if not REDIS_URL:
        logger.info("REDIS_URL not configured; async redis client will not be initialized")
        _aredis_client = None
        return
    if aioredis is None:
        logger.info("redis.asyncio not available; async redis client will not be initialized")
        _aredis_client = None
        return

    try:
        # Create client and try a quick ping to validate connectivity
        client = aioredis.from_url(REDIS_URL, decode_responses=True)
        try:
            # ping to ensure connection works (may raise)
            pong = await client.ping()
            logger.info(f"Connected to Redis at {REDIS_URL}; ping returned: {pong}")
            _aredis_client = client
        except Exception as e:
            logger.exception(f"Failed to ping Redis at {REDIS_URL}: {e}")
            try:
                await client.close()
            except Exception:
                pass
            _aredis_client = None
    except Exception as e:
        logger.exception(f"Failed to initialize async Redis client from {REDIS_URL}: {e}")
        _aredis_client = None

# store and builder instances
store: JobStore = get_job_store(REDIS_URL)
builder = DockerBuilder()


def _generate_default_tag() -> str:
    from datetime import datetime, timezone
    # UTC timestamp yyyymmdd-hhmmss
    return datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')


def _normalize_registry_url(url: str) -> str:
    """Normalize registry URL.
    - If given in GCP IAM resource form: projects/{project}/locations/{loc}/repositories/{repo}[/rest],
      convert to {loc}-docker.pkg.dev/{project}/{repo}[/rest].
    - Strip any leading https://.
    - Remove trailing slash.
    """
    try:
        if not url:
            return url
        u = url.strip()
        # strip protocol
        if u.startswith('https://'):
            u = u[len('https://'):]
        if u.startswith('http://'):
            u = u[len('http://'):]
        # match IAM-style path
        # e.g. projects/my-proj/locations/us-central1/repositories/my-repo/rag-service
        import re
        m = re.match(r"^projects/([^/]+)/locations/([^/]+)/repositories/([^/]+)(?:/(.*))?$", u)
        if m:
            project = m.group(1)
            loc = m.group(2)
            repo = m.group(3)
            rest = m.group(4) or ''
            rebuilt = f"{loc}-docker.pkg.dev/{project}/{repo}"
            if rest:
                rebuilt += f"/{rest}"
            u = rebuilt
        # remove trailing slash
        if u.endswith('/'):
            u = u[:-1]
        return u
    except Exception:
        return url


def _sanitize_image_string(img: str) -> str:
    """Sanitize a single image string by removing duplicated trailing path segments.
    Rules:
    - Preserve tag which is the last ':' after the final '/'. This avoids confusing registry ports (e.g. localhost:5000/repo:tag).
    - Split the path (without tag) by '/'. If the last L segments repeat immediately before them (pattern ... X Y X Y), remove the earlier duplicate block.
    - Return cleaned_path[:]/tag if present.
    """
    try:
        if not img or not isinstance(img, str):
            return img

        # Find tag: a ':' that occurs after the last '/' marks the tag separator.
        last_slash = img.rfind('/')
        last_colon = img.rfind(':')
        if last_colon > last_slash:
            path = img[:last_colon]
            tag = img[last_colon+1:]
        else:
            path = img
            tag = ''

        parts = [p for p in path.split('/') if p != '']
        if not parts:
            return f"{path}:{tag}" if tag else path

        # Heuristic: look for a repeating tail: parts[-L:] == parts[-2L:-L]
        for L in range(len(parts)//2, 0, -1):
            if len(parts) >= 2*L and parts[-L:] == parts[-2*L:-L]:
                parts = parts[:-L]
                break

        cleaned = '/'.join(parts)
        return f"{cleaned}:{tag}" if tag else cleaned
    except Exception:
        return img


def _sanitize_mappings_map(mappings: dict) -> dict:
    """Return a new dict of mappings with image strings sanitized.
    Non-string values are preserved unchanged.
    If mappings is falsy or not a dict, returns an empty dict.
    """
    if not mappings or not isinstance(mappings, dict):
        return {}
    out = {}
    for k, v in mappings.items():
        if isinstance(v, str):
            out[k] = _sanitize_image_string(v)
        else:
            out[k] = v
    return out


class CreateBuildPayload(BaseModel):
    repo_url: str
    branch: Optional[str] = "main"
    tag: Optional[str] = None
    registry: str
    dockerfile_path: Optional[str] = None
    registry_username: Optional[str] = None
    registry_password: Optional[str] = None
    build_args: Optional[Dict[str, str]] = None
    push: Optional[bool] = True
    dry_run: Optional[bool] = False
    no_cache: Optional[bool] = False
    gcp_secret_name: Optional[str] = None


class GoogleTokenPayload(BaseModel):
    id_token: str


class GoogleCodePayload(BaseModel):
    code: str
    redirect_uri: Optional[str] = None


class CredPayload(BaseModel):
    name: str
    username: str
    password: str


class RegistryPayload(BaseModel):
    name: str  # User-friendly name
    url: str  # Registry URL (e.g., gcr.io/project, docker.io/username)
    username: Optional[str] = None
    password: Optional[str] = None
    is_default: Optional[bool] = False
    use_service_account: Optional[bool] = False  # Use service account from secrets/docker-puller-key.json
    project_id: Optional[str] = None  # For GCR/Artifact Registry


def json_string(obj: Dict) -> str:
    return json.dumps(obj)


def create_internal_token(user: Dict) -> Optional[str]:
    """Create a signed internal JWT for the user (if PyJWT available)."""
    if jwt is None:
        return None
    try:
        payload = {
            'sub': user.get('sub'),
            'email': user.get('email'),
            'name': user.get('name')
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)
        # PyJWT >=2 returns str, older versions may return bytes
        if isinstance(token, bytes):
            token = token.decode('utf-8')
        return token
    except Exception:
        return None


def verify_internal_token(token: str) -> Optional[Dict[str, Any]]:
    if jwt is None:
        return None
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return data
    except Exception:
        return None


async def _get_user_from_token(id_tok: str) -> Optional[Dict]:
    # try internal JWT first
    try:
        data = verify_internal_token(id_tok)
        if data:
            return {"sub": data.get("sub"), "email": data.get("email"), "name": data.get("name")}
    except Exception:
        pass

    # fallback: Google id_token
    if google_id_token is None or google_requests is None:
        return None
    try:
        req = google_requests.Request()
        info = google_id_token.verify_oauth2_token(id_tok, req)
        return {"sub": info.get("sub"), "email": info.get("email"), "name": info.get("name")}
    except Exception:
        return None


async def _refresh_google_access_token_for_user(sub: str) -> Optional[str]:
    """If a refresh_token is stored for user `sub`, exchange it for a new access_token and persist it.
    Returns new access_token or None."""
    if _aredis_client is None:
        return None
    try:
        token_info = await _aredis_client.hgetall(f'user:{sub}:tokens')
        refresh = token_info.get('refresh_token') if token_info else None
        if not refresh:
            return token_info.get('access_token') if token_info else None
        client_id = os.environ.get('GOOGLE_CLIENT_ID')
        client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
        if not client_id or not client_secret:
            return token_info.get('access_token') if token_info else None
        data = {
            'client_id': client_id,
            'client_secret': client_secret,
            'refresh_token': refresh,
            'grant_type': 'refresh_token'
        }
        async with httpx.AsyncClient() as c:
            r = await c.post('https://oauth2.googleapis.com/token', data=data, timeout=10.0)
            if r.status_code != 200:
                return token_info.get('access_token') if token_info else None
            tj = r.json()
            new_access = tj.get('access_token')
            if new_access:
                # persist updated access_token (and expiry if provided)
                await _aredis_client.hset(f'user:{sub}:tokens', mapping={'access_token': new_access})
                return new_access
        return token_info.get('access_token') if token_info else None
    except Exception:
        return None


async def _get_user_from_request(request: Request) -> Optional[Dict]:
    """Simplified auth: if secrets/docker-puller-key.json exists, user is authenticated.
    All other auth methods are temporarily disabled.
    """
    # Check if secrets/docker-puller-key.json exists
    sa_path = 'secrets/docker-puller-key.json'
    if os.path.exists(sa_path):
        try:
            with open(sa_path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
                email = doc.get('client_email') or doc.get('clientId') or doc.get('client_id') or 'service-account@example.com'
                return {'sub': email, 'email': email, 'name': email, 'service_account': True}
        except Exception:
            pass

    # If file doesn't exist, user is not authenticated
    return None


# --- Endpoints ---
# Google OAuth endpoints temporarily disabled - using service account file auth only
# @app.post("/api/auth/google")
# async def auth_google(payload: GoogleTokenPayload):
#     ...

# @app.post('/api/auth/google_exchange')
# async def auth_google_exchange(payload: GoogleCodePayload):
#     ...


# Creds endpoints use _get_user_from_request so SA-file grants access
@app.post("/api/creds")
async def add_cred(request: Request, payload: CredPayload):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    key = f"user:{sub}:creds"
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")
    # store credential as hash under key:name
    await _aredis_client.hset(key, payload.name, json_string(payload.dict()))
    return {"ok": True}


@app.get("/api/creds")
async def list_creds(request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")
    data = await _aredis_client.hgetall(f"user:{sub}:creds")
    # return parsed JSONs
    res = {}
    for k, v in (data or {}).items():
        try:
            res[k] = json.loads(v)
        except Exception:
            res[k] = v
    return {"creds": res}


@app.delete("/api/creds/{cred_name}")
async def delete_cred(cred_name: str, request: Request):
    """Delete a credential"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")
    await _aredis_client.hdel(f"user:{sub}:creds", cred_name)
    return {"ok": True}


@app.get("/api/history")
async def get_history(request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")
    lst = await _aredis_client.lrange(f"user:{sub}:history", 0, -1)
    try:
        return {"history": [json.loads(x) for x in lst]}
    except Exception:
        return {"history": lst}


@app.get('/api/profile')
async def get_profile(request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail='Redis not configured')
    data = await _aredis_client.hgetall(f'user:{sub}:profile')
    # return as JSON
    return {'profile': data or {}}


@app.post('/api/profile')
async def set_profile(request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail='Redis not configured')
    payload = await request.json()
    # allow setting simple keys like default_project
    await _aredis_client.hset(f'user:{sub}:profile', mapping=payload)
    return {'ok': True}


@app.get("/api/service-account-info")
async def get_service_account_info(request: Request):
    """Get service account information from secrets/docker-puller-key.json"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')

    sa_path = 'secrets/docker-puller-key.json'
    if not os.path.exists(sa_path):
        raise HTTPException(status_code=404, detail='Service account file not found')

    try:
        with open(sa_path, 'r', encoding='utf-8') as f:
            sa_data = json.load(f)
            return {
                'project_id': sa_data.get('project_id'),
                'client_email': sa_data.get('client_email'),
                'available': True
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to read service account: {str(e)}')


@app.post("/api/registry")
async def add_registry(request: Request, payload: RegistryPayload):
    """Add a new registry for the authenticated user"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']

    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    # Generate unique ID for registry
    registry_id = str(uuid.uuid4())

    normalized_url = _normalize_registry_url(payload.url)

    registry_data = {
        'id': registry_id,
        'name': payload.name,
        'url': normalized_url,
        'username': payload.username or '',
        'password': payload.password or '',
        'is_default': payload.is_default or False,
        'use_service_account': payload.use_service_account or False,
        'project_id': payload.project_id or '',
        'is_authenticated': False,  # Will be checked separately
        'created_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z'
    }

    # Store registry
    await _aredis_client.hset(f"user:{sub}:registries", registry_id, json.dumps(registry_data))

    # If this is default, unset other defaults
    if payload.is_default:
        registries = await _aredis_client.hgetall(f"user:{sub}:registries")
        for rid, rdata in registries.items():
            if rid != registry_id:
                try:
                    reg = json.loads(rdata)
                    if reg.get('is_default'):
                        reg['is_default'] = False
                        await _aredis_client.hset(f"user:{sub}:registries", rid, json.dumps(reg))
                except Exception:
                    pass

    return {"ok": True, "registry": registry_data}


@app.get("/api/registry")
async def list_registries(request: Request):
    """Get list of registries for authenticated user"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']

    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    registries_data = await _aredis_client.hgetall(f"user:{sub}:registries")
    registries = []

    for rid, rdata in (registries_data or {}).items():
        try:
            reg = json.loads(rdata)
            # Don't expose password in list
            reg_safe = {**reg, 'password': '***' if reg.get('password') else ''}
            registries.append(reg_safe)
        except Exception:
            pass

    return {"registries": registries}


@app.delete("/api/registry/{registry_id}")
async def delete_registry(registry_id: str, request: Request):
    """Delete a registry"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']

    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    await _aredis_client.hdel(f"user:{sub}:registries", registry_id)
    return {"ok": True}


@app.post("/api/registry/{registry_id}/test")
async def test_registry_auth(registry_id: str, request: Request):
    """Test authentication for a registry"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']

    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    registries_data = await _aredis_client.hgetall(f"user:{sub}:registries")
    registry_json = registries_data.get(registry_id)

    if not registry_json:
        raise HTTPException(status_code=404, detail="Registry not found")

    try:
        registry = json.loads(registry_json)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid registry data")

    # Try to authenticate with Docker registry
    authenticated = False
    error_message = None

    try:
        registry_url = _normalize_registry_url(registry.get('url', ''))
        username = registry.get('username', '')
        password = registry.get('password', '')
        use_service_account = registry.get('use_service_account', False)

        # Extract registry host
        import re
        host_match = re.match(r'^(?:https?://)?([^/]+)', registry_url)
        registry_host = host_match.group(1) if host_match else registry_url.split('/')[0]

        # If using service account, get access token
        if use_service_account:
            sa_path = 'secrets/docker-puller-key.json'
            if os.path.exists(sa_path):
                try:
                    # Import Google auth libraries
                    from google.oauth2 import service_account
                    from google.auth.transport.requests import Request

                    # Load service account credentials
                    credentials = service_account.Credentials.from_service_account_file(
                        sa_path,
                        scopes=['https://www.googleapis.com/auth/cloud-platform']
                    )
                    # Refresh to get access token
                    credentials.refresh(Request())

                    username = 'oauth2accesstoken'
                    password = credentials.token
                except Exception as e:
                    error_message = f"Failed to get service account token: {str(e)}"
                    username = ''
                    password = ''
            else:
                error_message = "Service account file not found"

        if username and password:
            # Try Docker Registry API v2
            auth_url = f"https://{registry_host}/v2/"

            import base64
            credentials_str = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers = {'Authorization': f'Basic {credentials_str}'}

            async with httpx.AsyncClient() as client:
                response = await client.get(auth_url, headers=headers, timeout=10.0)

                if response.status_code == 200:
                    authenticated = True
                elif response.status_code == 401:
                    authenticated = False
                    error_message = "Authentication failed: Invalid credentials"
                else:
                    authenticated = False
                    error_message = f"Registry returned status {response.status_code}"
        else:
            if not error_message:
                error_message = "No credentials provided"

    except Exception as e:
        error_message = str(e)

    # Update registry authentication status
    registry['is_authenticated'] = authenticated
    await _aredis_client.hset(f"user:{sub}:registries", registry_id, json.dumps(registry))

    return {
        "authenticated": authenticated,
        "error": error_message
    }


@app.get("/api/registry/{registry_id}/images")
async def list_registry_images(registry_id: str, request: Request):
    """List images in a registry (if supported by registry API)"""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Missing or invalid authentication')
    sub = info['sub']

    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    registries_data = await _aredis_client.hgetall(f"user:{sub}:registries")
    registry_json = registries_data.get(registry_id)

    if not registry_json:
        raise HTTPException(status_code=404, detail="Registry not found")

    try:
        registry = json.loads(registry_json)
    except Exception:
        raise HTTPException(status_code=500, detail="Invalid registry data")

    images = []

    try:
        registry_url = _normalize_registry_url(registry.get('url', ''))
        username = registry.get('username', '')
        password = registry.get('password', '')
        use_service_account = registry.get('use_service_account', False)

        # If using service account, get access token
        if use_service_account:
            sa_path = 'secrets/docker-puller-key.json'
            if os.path.exists(sa_path):
                try:
                    from google.oauth2 import service_account
                    from google.auth.transport.requests import Request

                    credentials = service_account.Credentials.from_service_account_file(
                        sa_path,
                        scopes=['https://www.googleapis.com/auth/cloud-platform']
                    )
                    credentials.refresh(Request())

                    username = 'oauth2accesstoken'
                    password = credentials.token
                except Exception:
                    pass

        # Extract registry host and path
        import re
        # For gcr.io/project or docker.io/username
        match = re.match(r'^(?:https?://)?([^/]+)(?:/(.+))?', registry_url)
        if match:
            registry_host = match.group(1)
            base_path = match.group(2) or ''

            # Try Docker Registry API v2 - list repositories
            catalog_url = f"https://{registry_host}/v2/_catalog"

            headers = {}
            if username and password:
                import base64
                credentials_str = base64.b64encode(f"{username}:{password}".encode()).decode()
                headers['Authorization'] = f'Basic {credentials_str}'

            async with httpx.AsyncClient() as client:
                response = await client.get(catalog_url, headers=headers, timeout=10.0)

                if response.status_code == 200:
                    data = response.json()
                    repositories = data.get('repositories', [])

                    # Filter by base_path if specified
                    if base_path:
                        repositories = [r for r in repositories if r.startswith(base_path)]

                    # Get tags for each repository (limit to first 10 repos)
                    for repo in repositories[:10]:
                        try:
                            tags_url = f"https://{registry_host}/v2/{repo}/tags/list"
                            tags_response = await client.get(tags_url, headers=headers, timeout=5.0)

                            if tags_response.status_code == 200:
                                tags_data = tags_response.json()
                                tags = tags_data.get('tags', [])

                                images.append({
                                    'name': repo,
                                    'tags': tags[:5]  # Limit to 5 tags
                                })
                        except Exception:
                            pass

    except Exception as e:
        return {"images": [], "error": str(e)}

    return {"images": images}


@app.get("/api/parse-dockerfile")
async def parse_dockerfile(repo_url: str, branch: str, dockerfile_path: Optional[str] = None, request: Request = None):
    """Parse Dockerfile from remote repository and extract ARG directives"""
    if not repo_url or not branch:
        raise HTTPException(status_code=400, detail="repo_url and branch are required")

    # Get user credentials for accessing private repos
    user_info = await _get_user_from_request(request)
    username = None
    password = None

    if user_info and user_info.get('sub') and _aredis_client is not None:
        try:
            sub = user_info.get('sub')
            creds_data = await _aredis_client.hgetall(f"user:{sub}:creds")

            if creds_data:
                import re
                match = re.match(r'^(?:https?://|git@)([^/:]+)', repo_url)
                if match:
                    host = match.group(1)

                    def normalize_key(key):
                        normalized = key.lower()
                        normalized = re.sub(r'^https?://', '', normalized)
                        normalized = normalized.rstrip('/')
                        return normalized

                    normalized_host = normalize_key(host)
                    chosen = None

                    # Try to find matching git credentials
                    if host in creds_data:
                        chosen = creds_data[host]
                    else:
                        for cred_key, cred_value in creds_data.items():
                            normalized_cred_key = normalize_key(cred_key)
                            if normalized_cred_key == normalized_host:
                                chosen = cred_value
                                break
                            if normalized_host.startswith('git.'):
                                host_without_git = normalized_host[4:]
                                if normalized_cred_key == host_without_git:
                                    chosen = cred_value
                                    break
                            if normalized_cred_key.startswith('git.'):
                                cred_without_git = normalized_cred_key[4:]
                                if cred_without_git == normalized_host:
                                    chosen = cred_value
                                    break

                    if not chosen and 'default' in creds_data:
                        chosen = creds_data['default']

                    if not chosen and len(creds_data) > 0:
                        first_key = next(iter(creds_data.keys()))
                        chosen = creds_data[first_key]

                    if chosen:
                        try:
                            parsed = json.loads(chosen)
                            username = parsed.get('username')
                            password = parsed.get('password')
                        except Exception:
                            password = chosen
        except Exception:
            pass

    # Clone repo to temporary directory and parse Dockerfile
    build_args = []

    try:
        import tempfile
        import shutil

        tmpdir = tempfile.mkdtemp(prefix="dockerfile_parse_")

        try:
            # Build authenticated URL if credentials available
            authenticated_url = repo_url
            if username and password:
                import re
                from urllib.parse import quote
                match = re.match(r'^(https?://)(.+)$', repo_url)
                if match:
                    protocol = match.group(1)
                    rest = match.group(2)
                    encoded_user = quote(username, safe='')
                    encoded_pass = quote(password, safe='')
                    authenticated_url = f"{protocol}{encoded_user}:{encoded_pass}@{rest}"

            # Clone repository (shallow, single branch)
            proc = await asyncio.create_subprocess_exec(
                'git', 'clone', '--depth', '1', '--branch', branch, authenticated_url, tmpdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            await asyncio.wait_for(proc.communicate(), timeout=30.0)

            if proc.returncode != 0:
                raise HTTPException(status_code=400, detail="Failed to clone repository")

            # Determine Dockerfile path
            dockerfile = dockerfile_path or "Dockerfile"
            if not os.path.isabs(dockerfile):
                dockerfile = os.path.join(tmpdir, dockerfile)

            if not os.path.exists(dockerfile):
                raise HTTPException(status_code=404, detail=f"Dockerfile not found at {dockerfile_path or 'Dockerfile'}")

            # Parse Dockerfile and extract ARG directives
            import re
            with open(dockerfile, 'r', encoding='utf-8') as f:
                content = f.read()

                # Match ARG directives: ARG NAME or ARG NAME=default_value
                arg_pattern = re.compile(r'^ARG\s+([A-Za-z_][A-Za-z0-9_]*?)(?:=(.+?))?(?:\s+|$)', re.MULTILINE)

                for match in arg_pattern.finditer(content):
                    arg_name = match.group(1)
                    default_value = match.group(2) if match.group(2) else ''

                    build_args.append({
                        'name': arg_name,
                        'default_value': default_value,
                        'value': default_value  # Initial value same as default
                    })

        finally:
            # Cleanup temp directory
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

    except asyncio.TimeoutError:
        raise HTTPException(status_code=408, detail="Repository clone timeout")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse Dockerfile: {str(e)}")

    return {"build_args": build_args}


@app.get("/api/branches")
async def get_branches(repo_url: str, request: Request):
    """Get list of branches for a repository using git ls-remote. Uses saved credentials if available."""
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")

    # Get user info to access their credentials
    user_info = await _get_user_from_request(request)

    # Try to extract git host and find matching credentials
    username = None
    password = None

    if user_info and user_info.get('sub') and _aredis_client is not None:
        try:
            sub = user_info.get('sub')
            creds_data = await _aredis_client.hgetall(f"user:{sub}:creds")

            if creds_data:
                # Extract host from repo_url (e.g., git.ascender.space, github.com)
                import re
                # Match http(s)://host or git@host
                match = re.match(r'^(?:https?://|git@)([^/:]+)', repo_url)
                if match:
                    host = match.group(1)

                    # Helper function to normalize credential keys (remove protocol, trailing slashes)
                    def normalize_key(key):
                        """Remove http://, https://, trailing slashes from credential key"""
                        normalized = key.lower()
                        normalized = re.sub(r'^https?://', '', normalized)
                        normalized = normalized.rstrip('/')
                        return normalized

                    # Normalize the host from repo_url
                    normalized_host = normalize_key(host)

                    # Try to find matching credentials with normalization
                    chosen = None

                    # 1. Try exact match first (without normalization for backwards compatibility)
                    if host in creds_data:
                        chosen = creds_data[host]
                    else:
                        # 2. Try normalized matching - iterate through all saved credentials
                        for cred_key, cred_value in creds_data.items():
                            normalized_cred_key = normalize_key(cred_key)

                            # Check if normalized keys match
                            if normalized_cred_key == normalized_host:
                                chosen = cred_value
                                break

                            # Also check if the host without 'git.' prefix matches
                            if normalized_host.startswith('git.'):
                                host_without_git = normalized_host[4:]
                                if normalized_cred_key == host_without_git:
                                    chosen = cred_value
                                    break

                            # Check reverse: if cred has 'git.' prefix
                            if normalized_cred_key.startswith('git.'):
                                cred_without_git = normalized_cred_key[4:]
                                if cred_without_git == normalized_host:
                                    chosen = cred_value
                                    break

                    # 3. Try default
                    if not chosen and 'default' in creds_data:
                        chosen = creds_data['default']

                    # 4. Use first available credential
                    if not chosen and len(creds_data) > 0:
                        first_key = next(iter(creds_data.keys()))
                        chosen = creds_data[first_key]

                    if chosen:
                        try:
                            parsed = json.loads(chosen)
                            username = parsed.get('username')
                            password = parsed.get('password')
                        except Exception:
                            # chosen may be a plain string password
                            password = chosen
        except Exception:
            pass

    # Now try to fetch branches using git ls-remote
    branches = []

    try:
        # Build authenticated URL if credentials are available
        authenticated_url = repo_url
        if username and password:
            import re
            from urllib.parse import quote

            # Parse the URL to inject credentials
            # http://git.ascender.space/user/repo.git -> http://username:password@git.ascender.space/user/repo.git
            match = re.match(r'^(https?://)(.+)$', repo_url)
            if match:
                protocol = match.group(1)
                rest = match.group(2)
                # URL-encode username and password
                encoded_user = quote(username, safe='')
                encoded_pass = quote(password, safe='')
                authenticated_url = f"{protocol}{encoded_user}:{encoded_pass}@{rest}"

        # Execute git ls-remote to get all branches
        import subprocess

        # Run git ls-remote --heads to get only branch refs
        proc = await asyncio.create_subprocess_exec(
            'git', 'ls-remote', '--heads', authenticated_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)

        if proc.returncode == 0:
            # Parse output: each line is like "commit_hash\trefs/heads/branch_name"
            output = stdout.decode('utf-8', errors='replace')
            import re
            for line in output.strip().split('\n'):
                if line:
                    # Extract branch name from "refs/heads/branch_name"
                    match = re.search(r'refs/heads/(.+)$', line)
                    if match:
                        branch_name = match.group(1).strip()
                        branches.append(branch_name)
        else:
            # git ls-remote failed - likely auth issue or repo doesn't exist
            # Return empty list to indicate no access
            pass

    except asyncio.TimeoutError:
        # Timeout - return empty list
        pass
    except Exception as e:
        # On any error, return empty list
        pass

    return {"branches": branches}


@app.post("/api/build")
async def create_build(payload: CreateBuildPayload, request: Request):
    job_id = str(uuid.uuid4())

    # Check if user is authenticated (via service account file)
    user_info = await _get_user_from_request(request)

    # Extract git repository credentials from saved user creds
    repo_username = None
    repo_password = None

    # Try to extract credentials for repo from saved creds
    if user_info and user_info.get('sub') and _aredis_client is not None:
        try:
            sub = user_info.get('sub')
            creds_data = await _aredis_client.hgetall(f"user:{sub}:creds")

            if creds_data:
                import re
                # Extract host from repo_url
                match = re.match(r'^(?:https?://|git@)([^/:]+)', payload.repo_url)
                if match:
                    host = match.group(1)

                    def normalize_key(key):
                        normalized = key.lower()
                        normalized = re.sub(r'^https?://', '', normalized)
                        normalized = normalized.rstrip('/')
                        return normalized

                    normalized_host = normalize_key(host)
                    chosen = None

                    # Try to find matching git credentials
                    if host in creds_data:
                        chosen = creds_data[host]
                    else:
                        for cred_key, cred_value in creds_data.items():
                            normalized_cred_key = normalize_key(cred_key)
                            if normalized_cred_key == normalized_host:
                                chosen = cred_value
                                break
                            if normalized_host.startswith('git.'):
                                host_without_git = normalized_host[4:]
                                if normalized_cred_key == host_without_git:
                                    chosen = cred_value
                                    break
                            if normalized_cred_key.startswith('git.'):
                                cred_without_git = normalized_cred_key[4:]
                                if cred_without_git == normalized_host:
                                    chosen = cred_value
                                    break

                    if not chosen and 'default' in creds_data:
                        chosen = creds_data['default']

                    if chosen:
                        try:
                            parsed = json.loads(chosen)
                            repo_username = parsed.get('username')
                            repo_password = parsed.get('password')
                        except Exception:
                            repo_password = chosen
        except Exception:
            pass

    # Sanitize/validate registry and tag
    reg_in = (payload.registry or '').strip()
    raw_tag = (payload.tag or '').strip()

    # If tag not provided -> generate
    if not raw_tag:
        tag_in = _generate_default_tag()
    else:
        tag_in = raw_tag
        # Basic docker tag validation: up to 128 chars, allowed [A-Za-z0-9_.-]
        import re as _re
        if len(tag_in) > 128 or not _re.match(r'^[A-Za-z0-9_][A-Za-z0-9_.-]*$', tag_in):
            raise HTTPException(status_code=400, detail="Invalid tag format. Allowed: letters, digits, underscore, dot, dash; max length 128; no spaces.")

    # build initial request object
    req = BuildRequest(
        id=job_id,
        repo_url=payload.repo_url,
        branch=payload.branch or "main",
        tag=tag_in,
        registry=_normalize_registry_url(reg_in),
        dockerfile_path=payload.dockerfile_path or "",
        registry_username=payload.registry_username,
        registry_password=payload.registry_password,
        repo_username=repo_username,
        repo_password=repo_password,
        build_args=payload.build_args or {},
        push=payload.push,
        dry_run=payload.dry_run,
        no_cache=payload.no_cache,
        gcp_secret_name=payload.gcp_secret_name,
    )

    # If client didn't provide gcp_secret_name but the container has a mounted SA key path, use it
    if not req.gcp_secret_name:
        env_sa = os.environ.get('GCP_SA_KEY_PATH')
        if env_sa:
            # use file:// prefix so builder._get_token_from_secret can read from disk
            req.gcp_secret_name = f"file://{env_sa}"

    # if registry username/password not provided, try to load from user's saved creds
    if (not req.registry_username or not req.registry_password) and user_info and _aredis_client is not None:
        try:
            sub = user_info.get("sub")
            data = await _aredis_client.hgetall(f"user:{sub}:creds")
            if data:
                # try matching by registry host (e.g., gcr.io) or exact registry string
                registry_host = (req.registry.split('/')[0] if req.registry and '/' in req.registry else req.registry)
                chosen = None
                # prefer exact host match
                if registry_host and registry_host in data:
                    chosen = data[registry_host]
                # else try registry full string
                elif req.registry in data:
                    chosen = data[req.registry]
                # else try default
                elif 'default' in data:
                    chosen = data['default']
                # else pick first credential
                elif len(data) > 0:
                    # take the first entry
                    first_key = next(iter(data.keys()))
                    chosen = data[first_key]
                if chosen:
                    try:
                        parsed = json.loads(chosen)
                        if not req.registry_username and parsed.get('username'):
                            req.registry_username = parsed.get('username')
                        if not req.registry_password and parsed.get('password'):
                            req.registry_password = parsed.get('password')
                    except Exception:
                        # chosen may be a plain string password
                        if not req.registry_password:
                            req.registry_password = chosen
        except Exception:
            pass

    # create job in store
    await store.create_job(job_id, "queued", [])

    # also ensure job is present in Redis (so worker and other processes can see it)
    if _aredis_client is not None:
        try:
            # store basic job hash and add to jobs set
            await _aredis_client.hset(f"job:{job_id}", mapping={"id": job_id, "state": "queued", "logs": "[]"})
            await _aredis_client.sadd("jobs:ids", job_id)
        except Exception:
            pass

    # if user is authenticated, append to history in background
    if user_info and user_info.get("sub") and _aredis_client is not None:
        sub = user_info["sub"]
        try:
            entry = {
                "id": job_id,
                "repo_url": payload.repo_url,
                "branch": payload.branch,
                "tag": req.tag,  # store actual tag used
                "registry": req.registry,  # normalized registry
                "timestamp": __import__('datetime').datetime.utcnow().isoformat() + 'Z'
            }
            # push to list and trim to last 100
            await _aredis_client.lpush(f"user:{sub}:history", json.dumps(entry))
            await _aredis_client.ltrim(f"user:{sub}:history", 0, 99)
        except Exception:
            pass

    # enqueue or fallback
    if _queue is not None:
        try:
            _queue.enqueue('app.worker.process_build', req.dict(), job_timeout=3600)
            # we won't block on history write
            return {"id": job_id}
        except Exception:
            pass

    asyncio.create_task(_run_build(req))
    return {"id": job_id}


async def _run_build(req: BuildRequest):
    await store.set_state(req.id, "running")
    try:
        async for line in builder.build(req):
            await store.append_log(req.id, line)
        await store.set_state(req.id, "done")
    except Exception as e:
        await store.set_state(req.id, "error")
        await store.append_log(req.id, str(e))


# Provide an async in-process deploy runner used when RQ is not available.
async def _run_deploy(job_id: str, mappings: dict, user_sub: str):
    """Run ansible-playbook with mappings passed as --extra-vars (JSON). Writes logs to store."""
    await store.set_state(job_id, "running")
    try:
        # wrap mappings under key 'mappings' so playbook can reference {{ mappings }}
        extra_vars = json.dumps({'mappings': mappings})

        # Find playbook path - prefer ./deploy/playbook.yml or ./playbook.yml
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

        # Run ansible-playbook locally
        cmd = [
            'ansible-playbook',
            playbook,
            '-i', 'localhost,',
            '--connection', 'local',
            '--extra-vars', extra_vars
        ]

        env = os.environ.copy()
        # Pass user_sub as env var for playbook to use if needed
        env['DEPLOY_USER_SUB'] = user_sub

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


@app.get("/api/build/{job_id}")
async def get_build(job_id: str):
    job = await store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/builds")
async def list_builds():
    return await store.list_jobs()


@app.get("/", response_class=HTMLResponse)
async def index():
    tmpl = os.path.join(os.path.dirname(__file__), "templates", "index.html")
    if not os.path.exists(tmpl):
        return HTMLResponse('<html><body><h1>Docker Builder</h1><p>No template found.</p></body></html>')
    with open(tmpl, "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())

class MappingsPayload(BaseModel):
    mappings: dict

@app.get("/api/service-image-mapping")
async def get_service_mappings(request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")

    data = await _aredis_client.get(f"user:{sub}:service_mappings")
    if not data:
        return {"mappings": {}}
    try:
        return {"mappings": json.loads(data)}
    except Exception:
        return {"mappings": {}}



@app.post("/api/service-image-mapping")
async def save_service_mappings(payload: MappingsPayload, request: Request):
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sub = info['sub']
    if _aredis_client is None:
        raise HTTPException(status_code=500, detail="Redis not configured")
    try:
        # sanitize mappings before saving to avoid duplicated path segments
        cleaned = _sanitize_mappings_map(payload.mappings)
        await _aredis_client.set(f"user:{sub}:service_mappings", json.dumps(cleaned))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# New endpoint: deploy services using selected tags (runs ansible-playbook in background)
@app.post("/api/deploy-services")
async def deploy_services(payload: dict = Body(...), request: Request = None):
    """Start deployment: accept mappings { serviceId: "registry/repo:tag" } and run ansible-playbook with these values as extra-vars."""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail="Unauthorized")
    sub = info['sub']

    # validate payload and extract mappings
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Request body must be a JSON object containing 'mappings')")
    mappings = payload.get('mappings')
    if mappings is None or not isinstance(mappings, dict):
        raise HTTPException(status_code=422, detail="Missing or invalid 'mappings' object in request body")

    # sanitize mappings
    try:
        mappings = _sanitize_mappings_map(mappings)
    except Exception:
        pass

    job_id = str(uuid.uuid4())
    # create job in store
    await store.create_job(job_id, "queued", [])

    # store in redis for visibility if available
    if _aredis_client is not None:
        try:
            await _aredis_client.hset(f"deploy:{job_id}", mapping={"mappings": json.dumps(mappings), "user": sub})
        except Exception:
            pass

    # Try to enqueue via RQ if available
    if _queue is not None:
        try:
            _queue.enqueue('app.worker.process_deploy', job_id, mappings, job_timeout=3600)
            try:
                await store.append_log(job_id, "Enqueued to RQ (app.worker.process_deploy)")
            except Exception:
                pass
            return {"id": job_id, "enqueued": True}
        except Exception as e:
            try:
                await store.append_log(job_id, f"Failed to enqueue to RQ: {e}; falling back to in-process run")
            except Exception:
                pass

    # fallback: run in-process
    try:
        await store.append_log(job_id, "Running deploy in-process (no RQ available)")
    except Exception:
        pass
    # run the async in-process deploy coroutine (_run_deploy) in background
    asyncio.create_task(_run_deploy(job_id, mappings, sub))
    return {"id": job_id, "enqueued": False}


# DEBUG endpoint to inspect runtime flags helpful for diagnosing RQ/Redis issues
@app.get("/api/_debug")
async def _debug_info():
    """Return basic runtime debug info: REDIS_URL, whether RQ queue object exists, and availability of redis clients."""
    try:
        queue_conn = None
        queue_info = None
        try:
            if _queue is not None:
                queue_info = {
                    'queue_class': type(_queue).__name__,
                }
                try:
                    # rq.Queue has 'connection' attr
                    conn = getattr(_queue, 'connection', None)
                    if conn is not None:
                        queue_info['connection_repr'] = repr(conn)
                except Exception:
                    pass
        except Exception:
            queue_info = str(_queue)

        store_type = type(store).__name__ if 'store' in globals() else 'unknown'

        return {
            "REDIS_URL": REDIS_URL,
            "queue_configured": _queue is not None,
            "redis_sync_available": redis_sync is not None,
            "redis_async_available": aioredis is not None,
            "rq_available": Queue is not None,
            "store_type": store_type,
            "queue_info": queue_info,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- helper functions for re-enqueueing ---

def _decode_redis_value(val):
    """Decode a Redis value which may be bytes or string. Return None for falsy values."""
    if val is None:
        return None
    try:
        if isinstance(val, bytes):
            return val.decode('utf-8')
        return val
    except Exception:
        return val


def _get_sync_redis_client():
    """Return a sync redis client (redis-py) if available and REDIS_URL set, otherwise None."""
    try:
        if redis_sync is None or not REDIS_URL:
            return None
        # create a new client instance to avoid mutating global connection state
        return redis_sync.from_url(REDIS_URL)
    except Exception:
        return None


@app.post('/api/queue/reenqueue')
async def reenque_all_jobs(request: Request, force: bool = False):
    """Re-enqueue all jobs found in Redis set `jobs:ids` that have deploy metadata.
    Returns lists of requeued ids, skipped ids (with reason) and errors.
    """
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Unauthorized')

    # require Redis sync client available
    r = _get_sync_redis_client()
    if r is None:
        raise HTTPException(status_code=500, detail='Redis sync client not configured')

    try:
        raw_jobs = r.smembers('jobs:ids') or set()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Failed to read jobs: {e}')

    jobs = []
    for j in raw_jobs:
        try:
            if isinstance(j, bytes):
                jobs.append(j.decode())
            else:
                jobs.append(str(j))
        except Exception:
            jobs.append(str(j))

    requeued = []
    skipped = []
    errors = []

    # prepare queue object
    q = None
    try:
        if _queue is not None:
            q = _queue
        else:
            # create local Queue using redis client
            from rq import Queue as _RQQueue
            q = _RQQueue(connection=r)
    except Exception:
        q = None

    for jid in sorted(jobs):
        deploy_key = f'deploy:{jid}'
        try:
            if not r.exists(deploy_key):
                skipped.append({'id': jid, 'reason': 'no deploy metadata'})
                continue
            mappings_raw = r.hget(deploy_key, 'mappings')
            mappings_raw = _decode_redis_value(mappings_raw)
            if not mappings_raw:
                skipped.append({'id': jid, 'reason': 'no mappings field'})
                continue
            try:
                mappings = json.loads(mappings_raw)
            except Exception as e:
                errors.append({'id': jid, 'error': f'invalid mappings JSON: {e}'})
                continue

            # If not forcing, skip jobs that are already done to avoid overwriting final state
            try:
                if not force:
                    try:
                        existing = await store.get_job(jid)
                        if existing and existing.get('state') == 'done':
                            skipped.append({'id': jid, 'reason': 'already done'})
                            continue
                    except Exception:
                        pass

            except Exception:
                pass

            # enqueue
            try:
                if q is None:
                    errors.append({'id': jid, 'error': 'RQ not available'})
                    continue

                # IMPORTANT: set job state to 'queued' in the job store BEFORE enqueueing.
                # If the worker executes very quickly and sets state to 'done', a subsequent
                # set_state('queued') after enqueue would incorrectly overwrite the final state.
                try:
                    await store.set_state(jid, 'queued')
                except Exception:
                    pass

                q.enqueue('app.worker.process_deploy', jid, mappings, job_timeout=3600)

                # record enqueue action in job logs so UI/worker can show what happened
                try:
                    await store.append_log(jid, 'Re-enqueued via UI')
                except Exception:
                    pass

                requeued.append(jid)
            except Exception as e:
                errors.append({'id': jid, 'error': str(e)})
        except Exception as e:
            errors.append({'id': jid, 'error': str(e)})

    return {
        'requeued': requeued,
        'skipped': skipped,
        'errors': errors,
        'count': {'found': len(jobs), 'requeued': len(requeued), 'skipped': len(skipped), 'errors': len(errors)}
    }


@app.post('/api/queue/reenqueue/{job_id}')
async def reenque_job(job_id: str, request: Request, force: bool = False):
    """Re-enqueue a specific job id if deploy metadata available."""
    info = await _get_user_from_request(request)
    if not info or not info.get('sub'):
        raise HTTPException(status_code=401, detail='Unauthorized')

    r = _get_sync_redis_client()
    if r is None:
        raise HTTPException(status_code=500, detail='Redis sync client not configured')

    deploy_key = f'deploy:{job_id}'
    try:
        if not r.exists(deploy_key):
            return {'ok': False, 'reason': 'no deploy metadata'}
        mappings_raw = r.hget(deploy_key, 'mappings')
        mappings_raw = _decode_redis_value(mappings_raw)
        if not mappings_raw:
            return {'ok': False, 'reason': 'no mappings field'}
        try:
            mappings = json.loads(mappings_raw)
        except Exception as e:
            return {'ok': False, 'reason': f'invalid mappings JSON: {e}'}

        # prepare queue
        q = None
        try:
            if _queue is not None:
                q = _queue
            else:
                from rq import Queue as _RQQueue
                q = _RQQueue(connection=r)
        except Exception:
            q = None

        # If not forcing, skip re-enqueue when job already done to avoid overwriting final state.
        if not force:
            try:
                existing = await store.get_job(job_id)
                if existing and existing.get('state') == 'done':
                    return {'ok': False, 'reason': 'already done'}
            except Exception:
                pass

        # IMPORTANT: set job state to 'queued' BEFORE enqueueing to avoid overwriting a
        # 'done' state if the worker runs very quickly.
        try:
            await store.set_state(job_id, 'queued')
        except Exception:
            pass

        q.enqueue('app.worker.process_deploy', job_id, mappings, job_timeout=3600)
         try:
             await store.append_log(job_id, 'Re-enqueued via UI')
         except Exception:
             pass

         return {'ok': True, 'id': job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# serve static files if present
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


# End of file
