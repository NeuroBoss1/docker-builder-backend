import os
import asyncio
import json
from typing import Dict
import shutil

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
    output into the job store (logs). This implementation creates a temporary
    vars file next to the playbook and executes the playbook in that directory
    using the provided command pattern (inventory, vault file, user, limit).
    """
    redis_url = os.environ.get("REDIS_URL")
    store = get_job_store(redis_url=redis_url)

    async def _run():
        await store.set_state(job_id, "running")
        try:
            # Wrap mappings under key 'mappings'
            try:
                if isinstance(mappings, (str, bytes)):
                    parsed = json.loads(mappings) if isinstance(mappings, str) else json.loads(mappings.decode('utf-8'))
                    wrapper = {'mappings': parsed}
                else:
                    wrapper = {'mappings': mappings}
            except Exception:
                wrapper = {'mappings': mappings}

            # Locate ansible playbook directory
            candidates = [
                os.path.join(os.getcwd(), 'deploy', 'deploy', 'ansible'),
                os.path.join(os.getcwd(), 'deploy', 'ansible'),
                os.path.join(os.path.dirname(__file__), '..', 'deploy', 'deploy', 'ansible')
            ]
            playbook_dir = None
            for c in candidates:
                try:
                    if os.path.isdir(c):
                        playbook_dir = c
                        break
                except Exception:
                    pass

            if not playbook_dir:
                await store.append_log(job_id, 'No ansible playbook directory found (searched deploy/.../ansible)')
                await store.set_state(job_id, 'error')
                return

            # Prefer main playbook `playbook.yml` if present, otherwise fallback to cleanup_disk_when_low.yml
            chosen_playbook = None
            for name in ('playbook.yml', 'cleanup_disk_when_low.yml'):
                p = os.path.join(playbook_dir, name)
                if os.path.exists(p):
                    chosen_playbook = name
                    break

            if not chosen_playbook:
                await store.append_log(job_id, f'No ansible playbook found in {playbook_dir} (checked cleanup_disk_when_low.yml, playbook.yml)')
                await store.set_state(job_id, 'error')
                return

            # Build small vars (NEUROBOSS_TAG/AGENT_TAG/RAG_TAG) and write temp vars file
            def _extract_tag(img: str) -> str:
                if not img or not isinstance(img, str):
                    return ''
                last_slash = img.rfind('/')
                last_colon = img.rfind(':')
                if last_colon > last_slash:
                    return img[last_colon+1:]
                return ''

            svc_to_var = {
                'neuroboss': 'NEUROBOSS_TAG',
                'agent': 'AGENT_TAG',
                'rag': 'RAG_TAG'
            }
            vars_map = {}
            for svc, var in svc_to_var.items():
                img = mappings.get(svc) if isinstance(mappings, dict) else None
                tag = _extract_tag(img) if img else ''
                if tag:
                    vars_map[var] = tag

            # Добавляем реальные имена образов (image:tag), если они пришли из фронтенда
            # Если фронтенд прислал только тег (без '/'), то составляем полный путь по known registry bases
            image_vars = {
                'neuroboss': 'NEUROBOSS_IMAGE',
                'agent': 'AGENT_IMAGE',
                'rag': 'RAG_IMAGE'
            }

            # Базовые пути Artifact Registry для каждого сервиса (константы)
            IMAGE_BASES = {
                'agent': 'us-central1-docker.pkg.dev/augmented-audio-474107-v3/neuroboss-docker-repo/agent-service',
                'neuroboss': 'us-central1-docker.pkg.dev/augmented-audio-474107-v3/neuroboss-docker-repo/neuroboss-service',
                'rag': 'us-central1-docker.pkg.dev/augmented-audio-474107-v3/neuroboss-docker-repo/rag-service'
            }

            for svc, var in image_vars.items():
                img = mappings.get(svc) if isinstance(mappings, dict) else None
                if img and isinstance(img, str) and img.strip():
                    candidate = img.strip()
                    # if value looks like a tag (no slash), join with base path
                    if '/' not in candidate and svc in IMAGE_BASES:
                        full_image = f"{IMAGE_BASES[svc]}:{candidate}"
                    else:
                        full_image = candidate
                    vars_map[var] = full_image

            tmp_file_path = None
            try:
                import tempfile
                tf = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yml', dir=playbook_dir, encoding='utf-8')
                tmp_file_path = tf.name
                try:
                    for k, v in vars_map.items():
                        safe_v = str(v).replace('"', '\"')
                        tf.write(f'{k}: "{safe_v}"\n')
                    tf.write('mappings:\n')
                    if isinstance(mappings, dict):
                        for mk, mv in mappings.items():
                            safe_mv = str(mv).replace('"', '\"')
                            tf.write(f'  {mk}: "{safe_mv}"\n')
                    else:
                        safe_json = json.dumps(mappings).replace('"', '\"')
                        tf.write(f'  raw: "{safe_json}"\n')
                finally:
                    tf.close()
                await store.append_log(job_id, f'Created temporary vars file: {tmp_file_path}')
            except Exception as e:
                await store.append_log(job_id, f'Failed to create temporary vars file: {e}')
                tmp_file_path = None

            # Build ansible-playbook command (use the user-provided pattern)
            vault_pw = os.path.expanduser('~/.ansible_vault_pass.txt')
            inventory = 'inventory.ini'
            # find ansible-playbook binary in PATH
            ansible_bin = shutil.which('ansible-playbook')
            if not ansible_bin:
                await store.append_log(job_id, "ansible-playbook not found in PATH. Install Ansible or ensure it is available to the RQ worker process.")
                await store.set_state(job_id, 'error')
                # cleanup temp file if created
                if tmp_file_path:
                    try:
                        os.remove(tmp_file_path)
                        await store.append_log(job_id, f'Removed temporary vars file: {tmp_file_path}')
                    except Exception as e:
                        await store.append_log(job_id, f'Failed to remove temporary vars file {tmp_file_path}: {e}')
                return

            # Tell ssh to use only the provided identity file and skip host key checks to avoid verification failures
            ssh_common = '-o IdentitiesOnly=yes -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'
            # limit hosts as a single comma-separated string; allow override via DEPLOY_LIMIT env var
            limit_str = os.environ.get('DEPLOY_LIMIT', 'node1,node2,node3')
            cmd = [
                ansible_bin,
                '-i', inventory,
                chosen_playbook,
                '-u', 'psychopanda',
                '--vault-password-file', vault_pw,
                '--limit', limit_str,
                '--ssh-common-args', ssh_common,
            ]
            if tmp_file_path:
                cmd.extend(['--extra-vars', f'@{tmp_file_path}'])

            # Attempt to discover an SSH private key in common mounted locations
            # Prefer the GCE-style key name to avoid ambiguity; ignore public keys (*.pub).
            # This reduces confusion when multiple keys are present in ./secrets.
            ssh_key_candidates = [
                '/run/secrets/google_compute_engine',
                os.path.join(playbook_dir, 'files', 'google_compute_engine'),
                os.path.expanduser('~/.ssh/google_compute_engine'),
                # fallback (last-resort) keep ansible_id_rsa only if google_compute_engine not present
                '/run/secrets/ansible_id_rsa'
            ]
            chosen_ssh_key = None
            pub_only_found = []
            for kpath in ssh_key_candidates:
                try:
                    # prefer private key files; skip obvious public keys
                    if kpath.endswith('.pub'):
                        continue
                    if os.path.exists(kpath) and os.path.isfile(kpath):
                        # skip if the only matching file is a public key (named with .pub)
                        if kpath.endswith('.pub'):
                            pub_only_found.append(kpath)
                            continue
                        chosen_ssh_key = kpath
                        break
                except Exception:
                    continue

            # If we found only public keys (rare), log a hint to the user
            if not chosen_ssh_key and pub_only_found:
                await store.append_log(job_id, f'Only public SSH key files found: {pub_only_found}. Please mount the corresponding private key (no .pub) as /run/secrets/google_compute_engine')

            if chosen_ssh_key:
                try:
                    # try to make permissions strict (best-effort)
                    try:
                        os.chmod(chosen_ssh_key, 0o600)
                    except Exception:
                        pass
                    cmd.extend(['--private-key', chosen_ssh_key])
                    await store.append_log(job_id, f'Using SSH private key: {chosen_ssh_key}')

                    # Ensure compatibility with GCE-style default key path expected by some inventories
                    try:
                        ssh_dir = '/root/.ssh'
                        gce_key_path = os.path.join(ssh_dir, 'google_compute_engine')
                        if not os.path.exists(ssh_dir):
                            os.makedirs(ssh_dir, mode=0o700, exist_ok=True)
                        # create symlink if the GCE-named key is missing
                        if not os.path.exists(gce_key_path):
                            try:
                                os.symlink(chosen_ssh_key, gce_key_path)
                                # set strict perms on the target (best-effort)
                                try:
                                    os.chmod(chosen_ssh_key, 0o600)
                                except Exception:
                                    pass
                                await store.append_log(job_id, f'Created symlink {gce_key_path} -> {chosen_ssh_key}')
                            except Exception as e:
                                await store.append_log(job_id, f'Failed to create symlink {gce_key_path}: {e}')
                    except Exception:
                        pass

                except Exception as e:
                    await store.append_log(job_id, f'Failed to use SSH key {chosen_ssh_key}: {e}')

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

            # PRE-STEP: run cleanup playbook unconditionally before main deploy
            cleanup_playbook = 'cleanup_disk_when_low.yml'
            cleanup_path = os.path.join(playbook_dir, cleanup_playbook)
            if os.path.exists(cleanup_path):
                cleanup_cmd = [
                    ansible_bin,
                    '-i', inventory,
                    cleanup_playbook,
                    '-u', 'psychopanda',
                    '--vault-password-file', vault_pw,
                    '--limit', limit_str,
                    '--ssh-common-args', ssh_common,
                ]
                if chosen_ssh_key:
                    cleanup_cmd.extend(['--private-key', chosen_ssh_key])
                await store.append_log(job_id, f'Running pre-cleanup playbook: {cleanup_playbook}')
                try:
                    cproc = await asyncio.create_subprocess_exec(
                        *cleanup_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        cwd=playbook_dir,
                        env=env
                    )
                    assert cproc.stdout is not None
                    while True:
                        cline = await cproc.stdout.readline()
                        if not cline:
                            break
                        await store.append_log(job_id, cline.decode(errors='replace').rstrip())
                    crc = await cproc.wait()
                    if crc != 0:
                        await store.append_log(job_id, f'WARNING: cleanup playbook exited with code {crc}, continuing deploy')
                except Exception as e:
                    await store.append_log(job_id, f'WARNING: failed to run cleanup playbook: {e}')
            else:
                await store.append_log(job_id, 'cleanup_disk_when_low.yml not found, skipping pre-cleanup')

            # MAIN DEPLOY
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=playbook_dir,
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

            # cleanup temp file
            if tmp_file_path:
                try:
                    os.remove(tmp_file_path)
                    await store.append_log(job_id, f'Removed temporary vars file: {tmp_file_path}')
                except Exception as e:
                    await store.append_log(job_id, f'Failed to remove temporary vars file {tmp_file_path}: {e}')

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
