# Задача 05 — Инфраструктура: Docker, GPU VPS, деплой

## Цель

Упаковать весь пайплайн в Docker Compose, обеспечить деплой на GPU VPS (Timeweb Cloud),
настроить автозапуск и мониторинг.

---

## Архитектура сервисов

```
docker-compose.yml
├── bot          ← Telegram-бот (приём файлов + отправка результата)
├── transcriber  ← воркер faster-whisper (GPU)
├── diarizer     ← воркер pyannote.audio (GPU)
└── sender       ← воркер генерации MD и отправки в Telegram
```

Все сервисы используют общую SQLite-базу и тома `/var/data` через Docker volume.

---

## Требования к реализации

### Dockerfile (общий для всех сервисов)

```dockerfile
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3.11 python3-pip ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir -e .

COPY src/ src/
```

### docker-compose.yml

```yaml
version: "3.9"

x-gpu: &gpu
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]

services:
  bot:
    build: .
    command: python -m src.bot.main
    env_file: .env
    volumes:
      - data:/var/data
    restart: unless-stopped

  transcriber:
    build: .
    command: python -m src.workers.transcriber
    env_file: .env
    volumes:
      - data:/var/data
    <<: *gpu
    restart: unless-stopped

  diarizer:
    build: .
    command: python -m src.workers.diarizer
    env_file: .env
    volumes:
      - data:/var/data
    <<: *gpu
    restart: unless-stopped

  sender:
    build: .
    command: python -m src.workers.sender
    env_file: .env
    volumes:
      - data:/var/data
    restart: unless-stopped

volumes:
  data:
    driver: local
    driver_opts:
      type: none
      o: bind
      device: /var/data
```

### .env.example

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=

HUGGINGFACE_TOKEN=

WHISPER_MODEL=large-v3-turbo
WHISPER_DEVICE=cuda

DATA_DIR=/var/data
```

### Структура проекта

```
transcription-pipeline/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── pyproject.toml
├── tasks/                ← постановки задач
└── src/
    ├── bot/
    │   ├── main.py
    │   ├── handlers/audio.py
    │   └── db.py
    ├── workers/
    │   ├── transcriber.py
    │   ├── diarizer.py
    │   └── sender.py
    └── config.py
```

---

## Требования к VPS

| Параметр | Минимум | Рекомендуется |
|----------|---------|---------------|
| CPU | 4 vCPU | 8 vCPU |
| RAM | 16 ГБ | 32 ГБ |
| GPU | NVIDIA T4 (16 ГБ VRAM) | NVIDIA A10 |
| Диск | 60 ГБ SSD | 100 ГБ SSD |
| ОС | Ubuntu 22.04 | Ubuntu 22.04 |

---

## Одноразовая настройка VPS (bootstrap)

```bash
# NVIDIA Driver + Container Toolkit
apt-get install -y nvidia-driver-535
apt-get install -y nvidia-container-toolkit
systemctl restart docker

# Проверка GPU в контейнере
docker run --rm --gpus all nvidia/cuda:12.3.2-base-ubuntu22.04 nvidia-smi

# Клонирование репозитория
git clone <repo> /opt/transcription-pipeline
cd /opt/transcription-pipeline

# Настройка
cp .env.example .env && nano .env

# Папка для данных
mkdir -p /var/data/audio/inbox /var/data/transcripts /var/data/results

# Первый запуск (скачает модели ~8 ГБ)
docker compose up --build -d

# Логи
docker compose logs -f transcriber
```

### Предзагрузка моделей

При первом запуске `transcriber` скачивает `large-v3-turbo` (~3 ГБ),
`diarizer` скачивает `pyannote/speaker-diarization-3.1` (~1 ГБ).

Чтобы не скачивать при каждом пересборке — примонтировать кэш:

```yaml
# в docker-compose.yml для transcriber и diarizer:
volumes:
  - data:/var/data
  - model_cache:/root/.cache
```

---

## Локальная разработка и тестирование (без GPU)

Пайплайн разрабатывается и тестируется локально на CPU, затем деплоится на GPU VPS
без изменения кода — переключение осуществляется только через переменные окружения
и Docker Compose override-файл.

### Файлы конфигурации

```
transcription-pipeline/
├── docker-compose.yml           ← базовый (без GPU, для локальной разработки)
├── docker-compose.gpu.yml       ← override (добавляет GPU-секцию для VPS)
├── .env.example                 ← шаблон
├── .env.local.example           ← шаблон для локальной разработки
└── .env.vps.example             ← шаблон для VPS
```

### .env.local.example (CPU-режим)

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=

HUGGINGFACE_TOKEN=

WHISPER_MODEL=base        # tiny / base / small — для теста пайплайна
WHISPER_DEVICE=cpu

DATA_DIR=./data           # локальная папка вместо /var/data
```

### .env.vps.example (GPU-режим)

```env
TELEGRAM_BOT_TOKEN=
ALLOWED_CHAT_ID=

HUGGINGFACE_TOKEN=

WHISPER_MODEL=large-v3-turbo
WHISPER_DEVICE=cuda

DATA_DIR=/var/data
```

### docker-compose.gpu.yml (override для VPS)

```yaml
version: "3.9"

x-gpu: &gpu
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            count: 1
            capabilities: [gpu]

services:
  transcriber:
    <<: *gpu

  diarizer:
    <<: *gpu
```

Базовый `docker-compose.yml` не содержит GPU-секции — работает на любой машине.

### Команды запуска

```bash
# Локально (CPU)
cp .env.local.example .env
docker compose up --build

# На VPS (GPU)
cp .env.vps.example .env
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build -d
```

### Рекомендуемые модели для локального теста

| Модель | VRAM/RAM | Скорость на CPU | Назначение |
|--------|----------|-----------------|------------|
| `tiny` | ~1 ГБ | ~реальное время | быстрая проверка пайплайна |
| `base` | ~1 ГБ | ~1–2× реального | тест качества диаризации |
| `small` | ~2 ГБ | ~3–5× реального | тест качества транскрипции |

Для проверки пайплайна (не качества распознавания) достаточно `tiny` или `base`
на аудиофайле длиной **1–2 минуты**.

### Ожидаемое время обработки 1 минуты аудио

| Среда | Модель | Транскрипция | Диаризация | Итого |
|-------|--------|-------------|-----------|-------|
| CPU (локально) | `base` | ~1–2 мин | ~3–5 мин | ~5–7 мин |
| GPU VPS (L40S-12Q) | `large-v3-turbo` | ~10–20 сек | ~30–60 сек | ~1–2 мин |

### Порядок локального тестирования

1. Запустить пайплайн на CPU с моделью `tiny`
2. Отправить тестовый аудиофайл 1–2 мин с двумя чётко различимыми голосами
3. Убедиться что MD-файл сформирован корректно и пришёл в Telegram
4. Задеплоить на VPS: переключить `.env` и добавить GPU override
5. Повторить тест — результат тот же, скорость значительно выше

---

## Критерий приёмки

1. `docker compose up --build` проходит без ошибок на GPU VPS
2. `docker compose ps` — все 4 сервиса в статусе `running`
3. `nvidia-smi` внутри контейнера `transcriber` показывает GPU
4. Отправить аудиофайл боту → пройти весь пайплайн end-to-end → получить `.md`-файл
5. `docker compose restart transcriber` → воркер подхватывает незавершённые задания
6. После перезагрузки VPS (`reboot`) — все сервисы поднялись автоматически (`restart: unless-stopped`)
