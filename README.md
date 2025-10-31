# Docker Builder Service

Лёгкий сервис на FastAPI для автоматизации сборки Docker-образов и их деплоя.

Это приложение предоставляет HTTP API и минимальный веб-интерфейс для создания задач сборки и деплоя, хранения их состояния и просмотра логов выполнения. Оно пригодно для локальной разработки и как компонент более сложного CI/CD пайплайна.

Коротко — что в репозитории

- `app/` — исходный код FastAPI-приложения и воркера.
- `frontend/` — простая веб-обёртка (Vite + React) для управления задачами.
- `deploy/` — пример ansible playbook и вспомогательные сценарии.
- `tests/` — базовые тесты.
- `requirements.txt` — Python-зависимости.

Почему это удобно

- Файлы логов и состояния задач хранятся в Redis (если он настроен) — можно быстро посмотреть историю и логи.
- Поддерживается очередь RQ: задачи можно ставить в очередь и выполнять отдельными воркерами.
- При отсутствии Redis/RQ приложение использует in-memory fallback и выполняет задачу в фоне (полезно для простых сценариев и локальной отладки).

Содержание файла

- Быстрый старт (локально без Docker)
- Запуск в Docker
- API — краткий обзор
- Jobs / Workers / Queues — как это устроено и где смотреть логи
- Полезные команды для отладки

---

## Быстрый старт — запустить локально (без Docker)

Рекомендуется использовать виртуальное окружение Python:

```bash
cd /home/psychopanda/techops/infra/docker-builder-backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Запустить сервер разработчика (uvicorn):

```bash
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Если вы хотите, чтобы задачи реально выполнялись асинхронно через очередь RQ, запустите Redis и воркер в отдельном терминале:

```bash
# запустить redis (на Linux)
sudo service redis-server start
# в проекте (venv активирован)
export REDIS_URL=redis://localhost:6379/0
venv/bin/rq worker > rq.log 2>&1 &
tail -f rq.log
```

Фронтенд (локальная разработка):

```bash
cd frontend
npm install
npm run dev
# интерфейс по умолчанию будет на http://localhost:3000
```

Примечание: frontend делает proxy-запросы к `http://127.0.0.1:8000/api`, так что backend должен быть запущен.

---

## Запуск в Docker

Можно упаковать сервис в контейнер. Есть два распространённых подхода:

1) Использовать демон Docker хоста (монтировать `/var/run/docker.sock`). Быстро и удобно для локальной сборки.
2) Разворачивать вспомогательный сервис Docker-in-Docker (dind) — безопаснее, но сложнее.

Пример (вариант с примонтированным сокетом):

```bash
# собрать образ
docker build -t docker-builder-service .
# запустить (пробрасываем текущую директорию и сокет)
docker run --rm -p 8000:8000 -v /var/run/docker.sock:/var/run/docker.sock -v "$PWD":/app docker-builder-service
```

Или использовать docker-compose (если в `docker-compose.yml` настроен dind).

---

## Кратко про API

- POST /api/build — создать задачу сборки (см. `CreateBuildPayload` в `app/main.py`).
- POST /api/deploy-services — создать задачу деплоя с `mappings` (service -> image:tag).
- GET /api/build/{job_id} — получить статус и логи job.
- GET /api/builds — список job'ов.
- GET /api/_debug — отладочные флаги сервиса (наличие Redis, RQ и т.д.).

Для быстрой проверке используйте curl или Swagger UI: http://127.0.0.1:8000/docs

---

## Jobs, воркеры и очереди — как всё устроено (понимание и отладка)

Здесь коротко и по делу — где что хранится и как следить за задачами.

- Job: запись о задаче с полями `id`, `state` (queued / running / done / error) и `logs` (JSON-массив строк). Это «источник правды» для UI.
- Очередь: используется RQ (Redis Queue). Это список заданий, ожидающих своего исполнения воркером.
- Worker: отдельный процесс (запускается командой `rq worker`), который забирает задачу из очереди и выполняет её, обновляя `job:<id>` через `JobStore`.

Реализация `JobStore`:
- `InMemoryJobStore` — для локального режима (всё хранится в памяти процесса).
- `RedisJobStore` — работает через `redis.asyncio` и сохраняет job'ы в Redis.

Структура ключей Redis (если используется Redis):
- `jobs:ids` — множество всех job id.
- `job:<JOB_ID>` — hash с `id`, `state`, `logs`.
- `deploy:<JOB_ID>` — дополнительные метаданные для deploy (mappings, user).

Жизненный цикл задачи:
1. Клиент создаёт job (POST `/api/build` или `/api/deploy-services`).
2. Сервис сохраняет job (`state=queued`) и пытается поставить задачу в RQ.
3. Если enqueue прошёл — задача ждёт воркера; иначе запускается в фоне (fallback).
4. Воркeр/фоновая задача ставит `state=running`, пишет логи через `append_log` и по завершении ставит `done` или `error`.

Полезно: чтобы не терять историю и логи — запускайте Redis + отдельный RQ worker при разработке.

---

## Где смотреть логи и статус (полезные команды)

```bash
# список job id
redis-cli SMEMBERS jobs:ids
# показать job (включая логи)
redis-cli HGETALL job:<JOB_ID>
# показать deploy meta
redis-cli HGETALL deploy:<JOB_ID>
# содержимое RQ-очереди
redis-cli LRANGE rq:queue:default 0 -1
# tail логов воркера
tail -f rq.log
# tail логов uvicorn
tail -f uvicorn.log
```

Если в поле `logs` вы видите нечитаемые символы — иногда это значит, что там попали бинарные данные или сжатый поток (gzip/zlib). В репозитории есть рекомендации по диагностике и нормализации таких значений (читайте раздел «Troubleshooting» в этом README).

---

## Troubleshooting — частые проблемы

- Frontend не грузится / нет стилей: проверьте, что backend доступен по `http://127.0.0.1:8000` (vite проксирует запросы к API). Если backend не запущен, фронтенд покажет «голый» HTML.
- Задачи не попадают в очередь: проверьте `REDIS_URL`, запущен ли Redis и доступен ли он. В `/api/_debug` видна информация о подключении.
- Воркeр ничего не делает: убедитесь, что воркер запущен в том же окружении (тот же `REDIS_URL`), и смотрите `rq.log`.
- В `logs` в Redis — непонятные байты: возможно, туда попали бинарные данные. Сделайте бэкап значения, попробуйте распаковать gzip/zlib и сохранить в виде JSON-массива строк. В проекте есть скрипт диагностики, который помогает распознать и нормализовать такие логи.

---

## Как отлаживать ansible playbook и пример payload для `/api/deploy-services`

Ниже — компактная инструкция, которая поможет быстро локально отладить playbook и понять, какие переменные получает Ansible из бекенда.

1) Где искать playbook

- По умолчанию сервис ищет плейбук по пути `./deploy/playbook.yml` или `./playbook.yml` (см. `app/main.py`).
- Убедитесь, что этот файл существует и что ansible-playbook установлен в вашем окружении.

2) Что именно бекенд передаёт в playbook

- endpoint `/api/deploy-services` формирует JSON с ключом `mappings`, например:

```json
{
  "mappings": {
    "rag-service": "us-central1-docker.pkg.dev/PROJECT/REPO/rag-service:20251025-111006",
    "neuroboss-service": "us-central1-docker.pkg.dev/PROJECT/REPO/neuroboss-service:20251025-183318",
    "agent-service": "us-central1-docker.pkg.dev/PROJECT/REPO/agent-service:20251025-184200"
  }
}
```

- В playbook это доступно как переменная `mappings`. Пример: `{{ mappings }}` — это словарь serviceId -> image:tag.
- Бекенд также устанавливает env var `DEPLOY_USER_SUB` (если пользователь доступен) — можно использовать её внутри playbook.

3) Пример простого тестового `deploy/playbook.yml` (печатает mappings, извлекает TAG и симулирует прогресс 1..100)

```yaml
- name: Debug deploy mappings
  hosts: localhost
  connection: local
  gather_facts: no
  tasks:
    - name: Print received mappings (raw)
      debug:
        var: mappings

    - name: Print each service mapping with extracted tag
      vars:
        item_list: "{{ mappings | dict2items }}"
      loop: "{{ item_list }}"
      loop_control:
        loop_var: svc
      debug:
        msg: "{{ svc.key }} -> image={{ svc.value }} ; tag={{ (svc.value.split(':')[-1]) if ':' in svc.value else 'latest' }}"

    - name: Simulate work and emit progress 1..100
      loop: "{{ range(1, 101) | list }}"
      loop_control:
        label: "progress-{{ item }}"
      debug:
        msg: "PROGRESS {{ item }}"

    - name: Final message
      debug:
        msg: "Simulation complete"
```

- Этот плейбук полезен для отладки: он явно печатает полученные mappings и показывает извлечённый TAG для каждого сервиса.
- Для реальной логики замените блок `Simulate work...` на ваши задачи (deploy/ansible roles и т.д.).

4) Запуск playbook вручную (полезно для локальной отладки)

```bash
# пример: запустить playbook вручную и передать mappings
ansible-playbook deploy/playbook.yml -i "localhost," --connection local --extra-vars '{"mappings": {"rag-service": "us-central1-docker.pkg.dev/PROJECT/REPO/rag-service:20251025-111006", "neuroboss-service": "us-central1-docker.pkg.dev/PROJECT/REPO/neuroboss-service:20251025-183318", "agent-service": "us-central1-docker.pkg.dev/PROJECT/REPO/agent-service:20251025-184200"}}'

# для подробной отладки добавьте -vvv
ansible-playbook -vvv deploy/playbook.yml -i "localhost," --connection local --extra-vars '...'
```

- Важно: общий JSON передаётся как единый аргумент `--extra-vars`. В оболочке используйте правильные кавычки (обычно внешние одинарные, внутренние двойные).

5) Как отлаживать через API (пример запроса к бекенду)

```bash
curl -sS -X POST http://127.0.0.1:8000/api/deploy-services \
  -H 'Content-Type: application/json' \
  -d '{"mappings": {"rag-service": "us-central1-docker.pkg.dev/PROJECT/REPO/rag-service:20251025-111006", "neuroboss-service": "us-central1-docker.pkg.dev/PROJECT/REPO/neuroboss-service:20251025-183318", "agent-service": "us-central1-docker.pkg.dev/PROJECT/REPO/agent-service:20251025-184200"}}' | jq .
```

- Пример успешного ответа: `{"id": "<job-id>", "enqueued": true}` — где `id` можно использовать для просмотра логов и статуса.
- Дальше проверьте в Redis:

```bash
# deploy metadata (raw mappings)
redis-cli HGETALL deploy:<JOB_ID>
# сам job: лог и состояние
redis-cli HGETALL job:<JOB_ID>
```

6) Просмотр прогресса и логов

- UI: страница Queue (если доступна) показывает список job'ов и логи.
- Если UI недоступен, см. Redis и логи сервера/воркера:

```bash
tail -f uvicorn.log
tail -f rq.log
redis-cli HGETALL job:<JOB_ID>
```

7) Советы по отладке

- Используйте `-vvv` в `ansible-playbook` для максимально подробного вывода.
- Печатайте (debug) промежуточные переменные в плейбуке (особенно `mappings` и `ansible_env.DEPLOY_USER_SUB`).
- Если плейбук падает из-за отсутствия переменной, убедитесь, что вы называете её `mappings` и что JSON корректен. Ошибки вроде `dict2items requires a dictionary` означают, что переменная либо не передана, либо имеет неправильный тип.
- В плейбуке избегайте переменных с дефисами в имени (они неудобны для Jinja). Используйте `dict2items`/`items()` для итерации.

---

## Разработка и тесты

Установка и запуск тестов в venv:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest -q
```
---
