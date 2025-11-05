MinIO deployment (standalone on node3)
=====================================

This playbook installs MinIO as a systemd service on the host(s) in the `minio_node` group.
By default the inventory in `inventory.ini` assigns node3 to `minio_node`, so MinIO will be
installed only on the third VM.

Quick start
-----------
1) Edit credentials securely (recommended via ansible-vault): create `group_vars/minio_node.yml` with:

```yaml
minio_root_user: "minioadmin"
minio_root_password: "VerySecretPassword"
minio_data_dir: "/srv/minio/data"
minio_port: 9000
minio_console_port: 9001
```

2) Run the playbook:

```bash
cd deploy/ansible
ansible-playbook -i inventory.ini deploy-minio.yml --ask-become-pass -u psychopanda
```

Or pass secrets on the command line (not recommended for production):

```bash
ansible-playbook -i inventory.ini deploy-minio.yml -e "minio_root_password=VerySecretPassword" -u psychopanda --ask-become-pass
```

Checks
------
- Check systemd status on node3:

```bash
ssh psychopanda@<node3-ip> sudo systemctl status minio
```

- Health endpoint (on node3):

```bash
curl -I http://127.0.0.1:9000/minio/health/ready
```

- MinIO console: http://<node3-ip>:9001 (login with minio_root_user/minio_root_password)

- Test with `mc` (minio client):

```bash
mc alias set myminio http://<node3-ip>:9000 minioadmin VerySecretPassword
mc admin info myminio
mc mb myminio/test-bucket
echo hello | mc pipe myminio/test-bucket/hello.txt
mc cat myminio/test-bucket/hello.txt
```

Notes
-----
- For production use ansible-vault for secrets and open firewall rules only as needed.
- If you plan for high availability, consider distributed MinIO across several nodes instead of a single-node setup.
