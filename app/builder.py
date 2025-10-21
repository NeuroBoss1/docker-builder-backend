import asyncio
import os
import shutil
import tempfile
from typing import AsyncIterator, Dict, Optional, List, Tuple
from pydantic import BaseModel
import json


class BuildRequest(BaseModel):
    id: str
    repo_url: str
    branch: str = "main"
    tag: str
    registry: str
    dockerfile_path: Optional[str] = ""
    registry_username: Optional[str] = None
    registry_password: Optional[str] = None
    repo_username: Optional[str] = None  # Git repository credentials
    repo_password: Optional[str] = None  # Git repository credentials
    build_args: Dict[str, str] = {}
    push: bool = True
    dry_run: bool = False
    no_cache: bool = False
    # Optional: full resource name for a Secret Manager secret (e.g. "projects/PROJECT/secrets/NAME/versions/latest")
    gcp_secret_name: Optional[str] = None


class BuildStatus(BaseModel):
    id: str
    state: str
    logs: List[str] = []


class DockerBuilder:
    """Simple async Docker builder. It clones repositories, builds images and optionally pushes them.

    - Supports dry_run mode which simulates real operations (useful for tests).
    - Concurrency limit via asyncio.Semaphore.
    - Supports Google Artifact Registry login via gcloud or GCP Secret Manager if available.
    """

    def __init__(self, concurrency: int = 4):
        self._sem = asyncio.Semaphore(concurrency)
        # Find docker executable path
        self._docker_cmd = self._find_docker()

    def _find_docker(self) -> str:
        """Find docker executable, checking common locations and resolving symlinks"""
        docker_paths = [
            '/usr/local/bin/docker',
            '/usr/bin/docker',
        ]
        for path in docker_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                # Resolve symlinks to get the real path
                real_path = os.path.realpath(path)
                return real_path
        # If not found in standard locations, try shutil.which as fallback
        try:
            which_result = shutil.which('docker')
            if which_result:
                # Resolve symlinks
                return os.path.realpath(which_result)
        except Exception:
            pass
        # Last resort fallback - return real path
        return '/usr/bin/docker'

    async def build(self, req: BuildRequest) -> AsyncIterator[str]:
        await self._acquire()
        try:
            # Use a temporary directory for clone/build
            tmp = tempfile.mkdtemp(prefix="docker_build_")
            try:
                async for line in self._run_build(tmp, req):
                    yield line
            finally:
                # try to cleanup, don't raise on failure
                try:
                    shutil.rmtree(tmp)
                except Exception:
                    pass
        finally:
            self._release()

    async def _acquire(self):
        await self._sem.acquire()

    def _release(self):
        try:
            self._sem.release()
        except Exception:
            pass

    async def _run_build(self, tmpdir: str, req: BuildRequest) -> AsyncIterator[str]:
        # Dry-run simulation
        if req.dry_run:
            yield f"[dry_run] create workspace: {tmpdir}"
            await asyncio.sleep(0.05)
            yield f"[dry_run] cloning {req.repo_url} (branch: {req.branch})"
            await asyncio.sleep(0.05)
            yield "[dry_run] checking dockerfile"
            await asyncio.sleep(0.05)
            image_ref = f"{req.registry}:{req.tag}"
            no_cache_flag = " --no-cache" if req.no_cache else ""
            yield f"[dry_run] building image {image_ref}{no_cache_flag}"
            await asyncio.sleep(0.05)
            if req.push:
                yield f"[dry_run] logging into {req.registry} (if credentials provided)"
                await asyncio.sleep(0.05)
                yield f"[dry_run] pushing image {image_ref}"
                await asyncio.sleep(0.05)
            yield "[dry_run] build complete"
            return

        # Real execution path
        # 1. git clone with authentication if credentials provided
        clone_url = req.repo_url

        # If repo credentials are provided, inject them into the URL
        if req.repo_username and req.repo_password:
            import re
            from urllib.parse import quote

            # Parse URL and inject credentials
            match = re.match(r'^(https?://)(.+)$', req.repo_url)
            if match:
                protocol = match.group(1)
                rest = match.group(2)
                # URL-encode username and password to handle special characters
                encoded_user = quote(req.repo_username, safe='')
                encoded_pass = quote(req.repo_password, safe='')
                clone_url = f"{protocol}{encoded_user}:{encoded_pass}@{rest}"
                yield f"cloning private repository (authenticated)"
            else:
                yield f"cloning repository {req.repo_url}"
        else:
            yield f"cloning repository {req.repo_url}"

        git_cmd = ["git", "clone", "--depth", "1", "--branch", req.branch, clone_url, tmpdir]
        async for l in self._run_cmd(git_cmd, cwd=None):
            yield l

        # determine dockerfile path
        dockerfile = req.dockerfile_path or "Dockerfile"
        if not os.path.isabs(dockerfile):
            dockerfile = os.path.join(tmpdir, dockerfile)

        if not os.path.exists(dockerfile):
            yield f"error: Dockerfile not found at {dockerfile}"
            return

        image_ref = f"{req.registry}:{req.tag}"

        # extract registry host for docker login (docker expects host, not full image path)
        registry_host = req.registry.split('/') [0] if req.registry and '/' in req.registry else req.registry

        # login handling: prefer secure methods (password-stdin) and support gcloud or Secret Manager for GCP registries
        logged_in = False
        # if explicit username/password provided -> use secure stdin login
        if req.registry_username and req.registry_password:
            yield f"logging into {registry_host} with provided credentials"
            pwd = req.registry_password.encode('utf-8')
            success, login_lines = await self._docker_login_with_password_stdin(registry_host, req.registry_username, pwd)
            for line in login_lines:
                yield line
            logged_in = success
            if not success:
                yield f"warning: docker login to {registry_host} failed"
                # Fallback for GCP registries: try gcloud/SA token
                lower = (req.registry or "").lower()
                if ".gcr.io" in lower or ".pkg.dev" in lower or "artifactregistry" in lower:
                    yield f"attempting fallback login with gcloud/SA token for {registry_host}"
                    token = await self._get_gcloud_access_token()
                    if token:
                        success2, login_lines2 = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token.encode('utf-8'))
                        for line in login_lines2:
                            yield line
                        logged_in = success2
                        if not success2:
                            yield f"warning: gcloud-based docker login to {registry_host} failed"
                    if not logged_in:
                        # try secret/SA file if available
                        if req.gcp_secret_name:
                            yield f"attempting to retrieve token/service-account from Secret Manager or file: {req.gcp_secret_name}"
                            token_or_sa = await self._get_token_from_secret(req.gcp_secret_name)
                            if token_or_sa:
                                try:
                                    parsed = json.loads(token_or_sa)
                                    token_sa = await self._get_access_token_from_service_account_dict(parsed)
                                    if token_sa:
                                        success3, login_lines3 = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token_sa.encode('utf-8'))
                                        for line in login_lines3:
                                            yield line
                                        logged_in = success3
                                        if not success3:
                                            yield f"warning: docker login with service account token to {registry_host} failed"
                                    else:
                                        yield f"warning: failed to obtain access token from provided service account JSON"
                                except Exception:
                                    token_raw = token_or_sa.strip()
                                    if token_raw:
                                        success4, login_lines4 = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token_raw.encode('utf-8'))
                                        for line in login_lines4:
                                            yield line
                                        logged_in = success4
                                        if not success4:
                                            yield f"warning: docker login with raw token to {registry_host} failed"
                                    else:
                                        yield f"warning: secret returned empty token"
                        else:
                            yield f"hint: set GCP_SA_KEY_PATH environment variable or provide gcp_secret_name to enable service account login"
        else:
            # try to detect GCP registries (gcr.io, pkg.dev) and attempt token flow
            lower = (req.registry or "").lower()
            if ".gcr.io" in lower or ".pkg.dev" in lower or "artifactregistry" in lower:
                # 1) try gcloud if available
                yield f"attempting gcloud-based login for {registry_host}"
                token = await self._get_gcloud_access_token()
                if token:
                    success, login_lines = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token.encode('utf-8'))
                    for line in login_lines:
                        yield line
                    logged_in = success
                    if not success:
                        yield f"warning: gcloud-based docker login to {registry_host} failed"
                else:
                    # 2) fallback: try to get a token or SA creds from Secret Manager (if provided)
                    if req.gcp_secret_name:
                        yield f"attempting to retrieve token/service-account from Secret Manager or file: {req.gcp_secret_name}"
                        token_or_sa = await self._get_token_from_secret(req.gcp_secret_name)
                        if token_or_sa:
                            # if returned value looks like a service account JSON -> use it to obtain a token
                            try:
                                parsed = json.loads(token_or_sa)
                                # treat as service account JSON
                                token = await self._get_access_token_from_service_account_dict(parsed)
                                if token:
                                    success, login_lines = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token.encode('utf-8'))
                                    for line in login_lines:
                                        yield line
                                    logged_in = success
                                    if not success:
                                        yield f"warning: docker login with service account token to {registry_host} failed"
                                else:
                                    yield f"warning: failed to obtain access token from provided service account JSON"
                            except Exception:
                                # treat returned secret as a raw token
                                token = token_or_sa.strip()
                                if token:
                                    success, login_lines = await self._docker_login_with_password_stdin(registry_host, "oauth2accesstoken", token.encode('utf-8'))
                                    for line in login_lines:
                                        yield line
                                    logged_in = success
                                    if not success:
                                        yield f"warning: docker login with raw token to {registry_host} failed"
                                else:
                                    yield f"warning: secret returned empty token"
                        else:
                            yield f"warning: failed to retrieve secret from Secret Manager or file"
                    else:
                        yield f"warning: gcloud not available and no Secret Manager secret provided; registry may require auth"

        # docker build
        build_cmd = [self._docker_cmd, "build", "-t", image_ref, "-f", dockerfile, tmpdir]
        # add --no-cache flag if requested
        if req.no_cache:
            build_cmd.insert(2, "--no-cache")
        # append build-args
        for k, v in (req.build_args or {}).items():
            build_cmd.extend(["--build-arg", f"{k}={v}"])

        async for l in self._run_cmd(build_cmd, cwd=None):
            yield l

        if req.push:
            if not logged_in:
                yield f"warning: pushing to {req.registry} without successful login (may fail)"
            push_cmd = [self._docker_cmd, "push", image_ref]
            async for l in self._run_cmd(push_cmd, cwd=None):
                yield l

    async def _get_gcloud_access_token(self) -> Optional[str]:
        """Try to get an access token using gcloud. Returns token string or None."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "gcloud",
                "auth",
                "print-access-token",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert proc.stdout is not None
            out = await proc.stdout.read()
            await proc.wait()
            if proc.returncode != 0:
                return None
            token = out.decode('utf-8').strip()
            if not token:
                return None
            return token
        except FileNotFoundError:
            return None
        except Exception:
            return None

    async def _get_token_from_secret(self, secret_resource: str) -> Optional[str]:
        """Retrieve secret payload from GCP Secret Manager.

        secret_resource: full resource name like "projects/PROJECT/secrets/NAME/versions/latest".
        Returns secret payload as string (raw) or None on failure.
        """
        # allow a special form 'file:///path/to/key.json' to read a local file
        if isinstance(secret_resource, str) and secret_resource.startswith('file://'):
            path = secret_resource[len('file://'):]
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                return None

        try:
            # import here to avoid hard dependency unless this method is used
            from google.cloud import secretmanager
        except Exception:
            return None

        try:
            client = secretmanager.SecretManagerServiceClient()
            response = client.access_secret_version(request={"name": secret_resource})
            payload = response.payload.data.decode("utf-8")
            return payload
        except Exception:
            return None

    async def _get_access_token_from_service_account_dict(self, sa_dict: Dict) -> Optional[str]:
        """Create Credentials from service account dict and refresh to obtain an access token."""
        try:
            # import lazily
            from google.oauth2 import service_account
            from google.auth.transport.requests import Request
        except Exception:
            return None

        try:
            creds = service_account.Credentials.from_service_account_info(sa_dict, scopes=["https://www.googleapis.com/auth/cloud-platform"])
            # refresh to populate token
            creds.refresh(Request())
            return creds.token
        except Exception:
            return None

    async def _docker_login_with_password_stdin(self, registry_host: str, username: str, password_bytes: bytes) -> Tuple[bool, List[str]]:
        """Perform `docker login` feeding password via stdin. Returns (success, output_lines)."""
        lines: List[str] = []
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_cmd,
                "login",
                registry_host,
                "--username",
                username,
                "--password-stdin",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(password_bytes)
                await proc.stdin.drain()
                proc.stdin.close()
            except Exception:
                pass
            # collect output
            while True:
                chunk = await proc.stdout.readline()
                if not chunk:
                    break
                try:
                    decoded = chunk.decode("utf-8", errors="replace").rstrip()
                except Exception:
                    decoded = str(chunk)
                lines.append(decoded)
            await proc.wait()
            success = (proc.returncode == 0) and any("Login Succeeded" in l for l in lines)
            if not success and proc.returncode != 0:
                lines.append(f"command exited with code {proc.returncode}")
            return success, lines
        except Exception as e:
            lines.append(f"error: docker login failed: {e}")
            return False, lines

    async def _run_cmd(self, cmd: list, cwd: Optional[str] = None) -> AsyncIterator[str]:
        """Run a subprocess and yield stdout/stderr lines as they appear."""
        # Start process
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        assert proc.stdout is not None
        # read lines
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                decoded = str(line)
            yield decoded
        await proc.wait()
        if proc.returncode != 0:
            # Do not echo full command to avoid leaking secrets
            yield f"command exited with code {proc.returncode}"

    async def _run_cmd_with_input(self, cmd: list, input_bytes: bytes, cwd: Optional[str] = None) -> AsyncIterator[str]:
        """Run a subprocess, send input_bytes to stdin, and yield stdout/stderr lines."""
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        assert proc.stdout is not None and proc.stdin is not None
        try:
            proc.stdin.write(input_bytes)
            await proc.stdin.drain()
            proc.stdin.close()
        except Exception:
            pass

        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                decoded = str(line)
            yield decoded
        await proc.wait()
        if proc.returncode != 0:
            yield f"command exited with code {proc.returncode}"
