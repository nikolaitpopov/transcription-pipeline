# Transcription Pipeline

A Telegram bot for audio transcription with job queue management.

## Features

- Accept audio files from Telegram (voice messages, audio files, documents)
- Support for multiple audio formats: mp3, mp4, m4a, wav, ogg, webm, flac
- File size limit: 200 MB
- SQLite-based job queue for processing
- Chat access control

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd transcription-pipeline
```

2. Create a virtual environment and activate it:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp .env.example .env
# Edit .env and add your TELEGRAM_BOT_TOKEN
```

## Configuration

Create a `.env` file in the project root with the following variables:

- `TELEGRAM_BOT_TOKEN` (required): Your Telegram bot token from @BotFather
- `ALLOWED_CHAT_ID` (optional): Restrict bot access to a specific chat ID
- `DATA_DIR` (optional): Data directory path (default: `./data` for local, `/var/data` for VPS)

## Usage

### Running the Bot

```bash
python -m src.bot.main
```

### Supported Commands

- `/start` - Get welcome message and instructions
- `/help` - Show help information

### Sending Audio Files

The bot accepts:
- Voice messages (recorded directly in Telegram)
- Audio files (uploaded from device)
- Documents with audio extensions

Supported formats: mp3, mp4, m4a, wav, ogg, webm, flac
Maximum file size: 200 MB

### Response Format

After successfully receiving an audio file:
```
✅ Файл получен и поставлен в очередь.
ID задания: #123
Формат: mp3 · Размер: 5.42 МБ
Ожидайте результат — это займёт несколько минут.
```

## Project Structure

```
transcription-pipeline/
├── src/
│   ├── __init__.py
│   ├── config.py              # Configuration and environment variables
│   └── bot/
│       ├── __init__.py
│       ├── main.py            # Bot entry point
│       ├── db.py              # Database operations
│       └── handlers/
│           ├── __init__.py
│           └── audio.py       # Audio message handlers
├── data/                      # Data directory (created automatically)
│   ├── audio/
│   │   └── inbox/            # Incoming audio files
│   └── jobs.db               # SQLite database
├── .env                       # Environment variables (not in git)
├── .env.example              # Example environment file
├── .gitignore
├── requirements.txt          # Python dependencies
└── README.md
```

## Database Schema

### jobs table

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key (auto-increment) |
| file_path | TEXT | Absolute path to audio file |
| original_filename | TEXT | Original filename from Telegram |
| telegram_chat_id | INTEGER | Chat ID for sending results |
| status | TEXT | Job status (pending/transcribing/transcribed/sending/done/error) |
| created_at | TEXT | ISO 8601 UTC timestamp |
| updated_at | TEXT | ISO 8601 UTC timestamp |
| error_message | TEXT | Error message if status is 'error' |

## Development

### Running Tests

```bash
# TODO: Add tests
```

### Code Style

The project follows PEP 8 style guidelines.

## License

[Add your license here]
