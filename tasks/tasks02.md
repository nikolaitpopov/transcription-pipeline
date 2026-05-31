# Задача 02 — Сервис транскрипции: faster-whisper

## Цель

Реализовать фоновый сервис, который берёт аудиофайл из очереди (`status = pending`),
транскрибирует его с помощью `faster-whisper` и сохраняет результат в JSON.

---

## Входные данные

- Аудиофайл по пути из поля `file_path` в таблице `jobs`
- Модель: `large-v3-turbo`
- Язык: `ru` (русский, зафиксировать, не автоопределение)

---

## Требования к реализации

### Воркер очереди

- Бесконечный цикл с паузой 5 секунд между проверками
- Выбирает одно задание со статусом `pending` (FIFO по `created_at`)
- Обновляет статус на `transcribing` перед началом
- Запускает транскрипцию в отдельном процессе (`ProcessPoolExecutor`, 1 воркер)
  чтобы не блокировать event loop бота

### Параметры faster-whisper

```python
model = WhisperModel(
    "large-v3-turbo",
    device="cuda",          # GPU обязателен
    compute_type="float16",
)

segments, info = model.transcribe(
    audio_path,
    language="ru",
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 500},
    word_timestamps=False,
)
```

### Формат выходного JSON

Путь: `/var/data/transcripts/<job_id>_whisper.json`

```json
{
  "job_id": 42,
  "duration_seconds": 3720.5,
  "language": "ru",
  "segments": [
    {
      "start": 0.0,
      "end": 4.2,
      "text": "Добрый день, как дела с проектом?"
    },
    {
      "start": 4.5,
      "end": 9.1,
      "text": "Всё хорошо, вчера закончили правки по баннерам."
    }
  ]
}
```

### Обработка ошибок

- При исключении: обновить `status = error`, записать `error_message`
- Логировать в stdout с уровнем `ERROR`
- Не падать — продолжить цикл со следующим заданием

### Обновление статуса

После успешной транскрипции: `status = transcribed`, `updated_at = now()`

---

## Структура файлов

```
src/
├── workers/
│   ├── __init__.py
│   └── transcriber.py   ← воркер + функция транскрипции
└── config.py
```

---

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `WHISPER_MODEL` | default: `large-v3-turbo` |
| `WHISPER_DEVICE` | default: `cuda` |
| `DATA_DIR` | Корневая папка для данных |

---

## Критерий приёмки

1. Положить тестовый аудиофайл в `inbox/`, создать запись в `jobs` со статусом `pending`
2. Запустить воркер
3. Через N минут: статус задания стал `transcribed`, файл `<job_id>_whisper.json` существует
4. JSON содержит непустой массив `segments` с корректными таймкодами и русским текстом
5. Проверить на файле с тишиной в начале: VAD-фильтр отсекает тишину

---

## Зависимости

```toml
faster-whisper = "^1.x"
```

Системные требования:
- CUDA 12.x
- cuDNN 8.x
- GPU с ≥ 8 ГБ VRAM (NVIDIA T4 и выше)
