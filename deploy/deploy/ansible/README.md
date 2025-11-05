NeuroBoss Ansible deployment

Overview
--------
Этот playbook автоматизирует развёртывание стека NeuroBoss на трёх VM. Он устанавливает Docker, docker-compose, копирует `docker-compose.yml`, `nginx` конфигурации и генерирует `.env` из шаблона. Затем запускает стек через systemd unit и docker-compose.

Файловая структура
------------------
- `inventory.ini` — список хостов (замените IP/пользователей на ваши)
- `group_vars/all.yml` — глобальные переменные (образы, .env значения). Храните секреты через `ansible-vault`!
- `playbook.yml` — основной playbook
- `env.j2` — шаблон для `.env`
- `docker-compose.service.j2` — systemd unit template
- `../../deploy/vm/docker-compose.yml` — docker-compose для сервисов (копируется на хосты)
- `../../deploy/vm/nginx/nginx.conf` — nginx конфиг (копируется)

Подготовка
----------
1. Установите Ansible на контрольной машине (control node):

```bash
python3 -m pip install --user ansible
# или через систему пакетов
sudo apt update && sudo apt install -y ansible
```

2. Подготовьте SSH доступ с control node к каждой VM (ключи). Убедитесь, что `ansible_user` в `inventory.ini` существует и может sudo.

3. Отредактируйте `deploy/ansible/inventory.ini`, замените `REPLACE_WITH_IP_NODE*` и `ansible_user`.

4. Отредактируйте `deploy/ansible/group_vars/all.yml`:
   - Укажите `NEUROBOSS_IMAGE`, `AGENT_IMAGE`, `RAG_IMAGE` — теги ваших образов в GCR.
   - Укажите `DATABASE_URL`, `REDIS_URL` и MinIO креды.
   - Проверьте `deploy_user` (по умолчанию `ubuntu`) — учётная запись, под которой будет создаваться `/opt/neuroboss`.

Важно: не храните секреты в плейбуке в открытом виде. Используйте `ansible-vault`:

```bash
ansible-vault encrypt_string 'mypassword' --name 'MINIO_ROOT_PASSWORD' >> group_vars/all.yml
```

Запуск playbook
---------------
1. Тестовый запуск (dry run):

```bash
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/playbook.yml --check --diff
```

2. Полный запуск:

```bash
ansible-playbook -i deploy/ansible/inventory.ini deploy/ansible/playbook.yml
```

3. Если вы зашифровали секреты с помощью ansible-vault, добавьте `--ask-vault-pass` или `--vault-password-file <file>`.

Проверка после деплоя
---------------------
На каждой VM выполните:

```bash
# контейнеры
docker ps
# логи
docker-compose -f /opt/neuroboss/docker-compose.yml logs -f rag-service
# systemd
systemctl status docker-compose-neuroboss.service
```

Проверьте доступность HTTP endpoints:

```bash
curl -v http://127.0.0.1:15015/api/rag/
curl -v http://127.0.0.1:15011/
curl -v http://127.0.0.1:1216/
```

Особенности для `neuroboss-service-prod` VM
-------------------------------------------
Вы указали, что одна VM имеет kernel `6.1.0-39-cloud-amd64` на Debian — playbook учитывает Debian/Ubuntu и добавляет apt-репозиторий Docker в зависимости от дистрибутива. Если у вас нестандартная система (например, minimal образ без `lsb_release`) — убедитесь, что пакет `lsb-release` установлен (playbook это делает).

Мониторинг и Node Exporter
--------------------------
В `group_vars/all.yml` переменная `install_monitoring` отключена по умолчанию. Если хотите запустить Prometheus+Grafana и node_exporter, включите переменные и убедитесь, что `docker-compose.monitoring.yml` присутствует в `deploy/vm`.

Откат
-----
Чтобы откатить изменения, можно использовать предыдущие теги образов и выполнить `docker-compose -f /opt/neuroboss/docker-compose.yml pull` и `up -d` или `systemctl restart docker-compose-neuroboss.service`.

Поддержка и безопасность
-----------------------
- Рассмотрите использование GCP Secret Manager или HashiCorp Vault вместо хранения секретов в `group_vars`.
- Рекомендуется настроить HTTPS через GCP Load Balancer или Certbot на nginx.

Если хотите, я могу:
- Добавить роль для установки и настройки `node_exporter` на всех VM;
- Подготовить `gcloud`-скрипт для создания load balancer и health checks;
- Записать Ansible Vault за вас (сгенерировать секреты) и подставить их в `group_vars`.

