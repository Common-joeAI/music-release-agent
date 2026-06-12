# 🎵 Music Release Prep Agent

> AI-powered music release preparation — metadata, artwork, and packaging in seconds.

![dark UI](https://img.shields.io/badge/UI-Dark%20Mode-7c5cff?style=flat-square)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker)
![AI](https://img.shields.io/badge/AI-Groq%20LLM-F55036?style=flat-square)

## ✨ Features

- **Drag & drop** — drop one audio file (Single) or multiple (Album)
- **AI analysis** — LLM generates release title, genre, subgenre, mood, description, hashtags
- **Album artwork** — auto-generates a beautiful square cover image
- **Clean package** — organized output folder with renamed audio, artwork, and metadata
- **Copy-paste ready** — formatted text file with all release details
- **Real-time progress** — WebSocket-powered live status updates

## 🚀 Quick Start

```bash
# Clone
git clone https://github.com/YOUR_USER/music-release-agent
cd music-release-agent

# Configure
cp .env.example .env
# Add your GROQ_API_KEY to .env (free at console.groq.com)

# Run
docker compose up -d

# Open
open http://localhost:7700
```

## 🔑 Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Free LLM API for metadata (groq.com) |
| `TOGETHER_API_KEY` | No | FLUX image generation (together.ai) |
| `FAL_API_KEY` | No | Alternative image generation |

## 📦 Output Structure

```
RELEASE_My_Amazing_Track/
├── audio/
│   └── 01_My_Amazing_Track.wav
├── artwork/
│   └── cover.png
├── METADATA.txt          ← copy-paste ready
└── metadata.json         ← machine-readable
```

## 🐳 Docker

```bash
docker run -d \
  -p 7700:7700 \
  -e GROQ_API_KEY=your_key \
  --name music-release-agent \
  ghcr.io/YOUR_USER/music-release-agent:latest
```

## 📤 Deploy to GitHub

```bash
export GITHUB_USER=yourusername
export GITHUB_TOKEN=your_pat_token
export REPO_NAME=music-release-agent
bash scripts/github_release.sh
```

---

Built with Flask · Socket.IO · Groq · ffmpeg · Docker
