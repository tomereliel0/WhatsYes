# WhatsYes 📺

A simple, accessible web app that shows Yes TV broadcast schedules in a grandma-friendly interface.

## Setup

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000

## API Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/channels` | List available channels |
| `GET /api/schedule/{channel_id}?date=YYYY-M-D` | Get schedule for a channel |
| `GET /api/now` | What's currently airing across channels |
