# Задача 03 — Сервис диаризации: pyannote.audio + слияние с транскрипцией

## Цель

Для транскрибированного задания (`status = transcribed`) выполнить диаризацию спикеров
с помощью `pyannote.audio`, затем наложить результат на сегменты Whisper и сохранить
объединённый JSON с размеченными репликами.

---

## Входные данные

- Аудиофайл из `jobs.file_path`
- Транскрипция: `/var/data/transcripts/<job_id>_whisper.json`

---

## Требования к реализации

### Шаг A — Диаризация (pyannote.audio)

```python
from pyannote.audio import Pipeline

pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-3.1",
    use_auth_token=HUGGINGFACE_TOKEN,
)
pipeline.to(torch.device("cuda"))

diarization = pipeline(audio_path)
```

Выход: список интервалов `[{start, end, speaker}]` где `speaker` — `"SPEAKER_00"`, `"SPEAKER_01"` и т.д.

Нормализовать имена спикеров: `"SPEAKER_00"` → `"Спикер 1"`, `"SPEAKER_01"` → `"Спикер 2"` и т.д.

### Шаг Б — Слияние транскрипции и диаризации

Алгоритм: для каждого сегмента Whisper определить спикера по максимальному перекрытию
временного интервала с сегментами диаризации.

```python
def assign_speaker(segment_start, segment_end, diarization_segments):
    """Возвращает спикера с наибольшим перекрытием с данным сегментом."""
    best_speaker = "Неизвестно"
    best_overlap = 0.0
    for d in diarization_segments:
        overlap = min(segment_end, d["end"]) - max(segment_start, d["start"])
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = d["speaker"]
    return best_speaker
```

### Шаг В — Объединение соседних реплик одного спикера

Соседние сегменты одного спикера с паузой менее 1.5 секунды объединять в одну реплику.

### Формат выходного JSON

Путь: `/var/data/transcripts/<job_id>_diarized.json`

```json
{
  "job_id": 42,
  "duration_seconds": 3720.5,
  "speakers_count": 2,
  "turns": [
    {
      "start": 0.0,
      "end": 9.1,
      "speaker": "Спикер 1",
      "text": "Добрый день, как дела с проектом?"
    },
    {
      "start": 9.5,
      "end": 18.3,
      "speaker": "Спикер 2",
      "text": "Всё хорошо, вчера закончили правки по баннерам."
    }
  ]
}
```

### Обработка ошибок и статусы

- Начало обработки: `status = diarizing`
- Успех: `status = diarized`
- Ошибка: `status = error`, записать `error_message`

---

## Структура файлов

```
src/
└── workers/
    └── diarizer.py   ← воркер диаризации и функции слияния
```

---

## Переменные окружения

| Переменная | Описание |
|------------|----------|
| `HUGGINGFACE_TOKEN` | Токен HuggingFace для загрузки модели pyannote |
| `DATA_DIR` | Корневая папка для данных |

> **Примечание:** модель `pyannote/speaker-diarization-3.1` требует принятия условий
> использования на huggingface.co и HF-токена с доступом к модели.

---

## Критерий приёмки

1. Создать задание со статусом `transcribed`, убедиться что `<job_id>_whisper.json` существует
2. Запустить воркер диаризации
3. После завершения: файл `<job_id>_diarized.json` существует, статус `diarized`
4. Проверить на тестовой записи с двумя спикерами: в JSON корректно чередуются `"Спикер 1"` и `"Спикер 2"`
5. Проверить объединение реплик: короткие паузы (<1.5 с) одного спикера склеены

---

## Зависимости

```toml
pyannote-audio = "^3.x"
torch = "^2.x"   # с CUDA
```
