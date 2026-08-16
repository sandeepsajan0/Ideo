# 🎬 Ideo: Idea-to-Video Generator

An AI-powered platform that transforms any topic into a complete video with script, voiceover, visuals, and assembly — all from a single prompt.

## ✨ Features

- **AI Script Generation** — Gemini generates structured scripts with narration and visual prompts
- **AI Voiceover** — ElevenLabs v3 produces natural, expressive narration
- **AI Video Generation** — Fal.ai Hunyuan Video creates cinematic clips
- **AI Thumbnails** — FLUX generates eye-catching thumbnails
- **Smart Assembly** — FFmpeg merges audio/video and concatenates scenes
- **Real-Time Progress** — SSE streaming shows live pipeline updates
- **Multiple Formats** — Supports 9:16 (Shorts), 16:9 (YouTube), 1:1 (Instagram)
- **Mock Mode** — Test without API credits using placeholder assets

## 🛠️ Tech Stack

| Layer | Technology |
|:------|:-----------|
| Backend | FastAPI (Python) |
| Script AI | Google Gemini 2.5 Flash |
| Voice AI | ElevenLabs v3 |
| Video AI | Fal.ai Hunyuan Video |
| Image AI | Fal.ai FLUX |
| Assembly | FFmpeg |
| Frontend | HTML / CSS / JavaScript |

## 🚀 Quick Start

### 1. Prerequisites

- Python 3.11+
- FFmpeg (`brew install ffmpeg` on macOS)
- API keys for Gemini, ElevenLabs, and Fal.ai

### 2. Install

```bash
cd video_generator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run

```bash
# With real AI APIs
uvicorn app.main:app --reload --port 8000

# With mock mode (no API keys needed)
MOCK_MODE=true uvicorn app.main:app --reload --port 8000
```

Open **http://localhost:8000** in your browser.

## 📡 API Endpoints

| Method | Endpoint | Description |
|:-------|:---------|:------------|
| `POST` | `/api/projects` | Create a new video project |
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{id}` | Get project details |
| `GET` | `/api/projects/{id}/stream` | SSE progress stream |
| `GET` | `/api/projects/{id}/download` | Download final video |
| `GET` | `/api/projects/{id}/thumbnail` | Get thumbnail |
| `DELETE` | `/api/projects/{id}` | Delete project |
| `PUT` | `/api/projects/{id}/scenes/{idx}` | Edit a scene |

## 📁 Project Structure

```
video_generator/
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── schemas.py            # Pydantic models
│   ├── core/config.py        # Settings
│   ├── api/router.py         # API routes
│   └── services/
│       ├── script_service.py # Gemini
│       ├── audio_service.py  # ElevenLabs
│       ├── video_service.py  # Fal.ai video
│       ├── image_service.py  # Fal.ai images
│       ├── assembly_service.py # FFmpeg
│       └── pipeline.py       # Orchestrator
├── frontend/                 # Web UI
├── output/                   # Generated videos
├── .env.example
└── requirements.txt
```

## 🧪 Mock Mode

Set `MOCK_MODE=true` in your `.env` to use placeholder assets:
- Silent audio files (FFmpeg-generated)
- Solid color videos with text overlay
- Placeholder thumbnails
- No API credits consumed

## 📄 License

MIT
