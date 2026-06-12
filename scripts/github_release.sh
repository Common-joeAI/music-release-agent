#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  Music Release Prep Agent — GitHub Auto-Release Script
#  Creates repo, pushes code, triggers GitHub Release + Actions
# ═══════════════════════════════════════════════════════════════

set -euo pipefail

# ── Config ──────────────────────────────────────────────────────
REPO_NAME="${REPO_NAME:-music-release-agent}"
GITHUB_USER="${GITHUB_USER:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
VERSION="${VERSION:-1.0.0}"
PRIVATE="${PRIVATE:-false}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
log()  { echo -e "${CYAN}[MRA]${NC} $1"; }
ok()   { echo -e "${GREEN}[OK]${NC}  $1"; }
warn() { echo -e "${YELLOW}[!!]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

# ── Validate ─────────────────────────────────────────────────────
[[ -z "$GITHUB_USER"  ]] && err "GITHUB_USER not set"
[[ -z "$GITHUB_TOKEN" ]] && err "GITHUB_TOKEN not set"

# ── Check git ────────────────────────────────────────────────────
command -v git  >/dev/null || err "git not installed"
command -v curl >/dev/null || err "curl not installed"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

log "Project: $PROJECT_DIR"
log "Target:  github.com/$GITHUB_USER/$REPO_NAME"
log "Version: v$VERSION"

# ── Create GitHub repo ───────────────────────────────────────────
log "Creating GitHub repository..."
CREATE_RESP=$(curl -sf -X POST \
  -H "Authorization: token $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/user/repos \
  -d "{
    \"name\": \"$REPO_NAME\",
    \"description\": \"🎵 AI-powered music release prep agent — metadata, artwork & packaging\",
    \"private\": $PRIVATE,
    \"auto_init\": false,
    \"has_issues\": true,
    \"has_wiki\": false
  }" 2>/dev/null || true)

if echo "$CREATE_RESP" | grep -q '"already exists"' || echo "$CREATE_RESP" | grep -q '"name": "'"$REPO_NAME"'"'; then
  warn "Repository already exists — will push to existing"
else
  ok "Repository created"
fi

REMOTE_URL="https://${GITHUB_TOKEN}@github.com/${GITHUB_USER}/${REPO_NAME}.git"

# ── Init git ─────────────────────────────────────────────────────
cd "$PROJECT_DIR"

if [[ ! -d .git ]]; then
  log "Initializing git repository..."
  git init
  git branch -M main
fi

# ── GitHub Actions workflow ───────────────────────────────────────
mkdir -p .github/workflows
cat > .github/workflows/docker-release.yml << 'WORKFLOW'
name: Docker Build & Release

on:
  push:
    tags: ["v*.*.*"]
  workflow_dispatch:

jobs:
  build-and-release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Extract metadata
        id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=semver,pattern={{version}}
            type=semver,pattern={{major}}.{{minor}}
            type=raw,value=latest

      - name: Build and push Docker image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Create GitHub Release
        uses: softprops/action-gh-release@v1
        if: startsWith(github.ref, 'refs/tags/')
        with:
          name: "Music Release Prep Agent ${{ github.ref_name }}"
          body: |
            ## 🎵 Music Release Prep Agent ${{ github.ref_name }}

            AI-powered music release preparation tool.

            ### Docker (recommended)
            ```bash
            docker pull ghcr.io/${{ github.repository }}:latest
            docker run -p 7700:7700 -e GROQ_API_KEY=your_key ghcr.io/${{ github.repository }}:latest
            ```

            ### Docker Compose
            ```bash
            git clone https://github.com/${{ github.repository }}
            cd music-release-agent
            cp .env.example .env  # add your keys
            docker compose up -d
            ```

            Open http://localhost:7700
          draft: false
          prerelease: false
WORKFLOW

ok "GitHub Actions workflow created"

# ── Commit & push ────────────────────────────────────────────────
log "Staging files..."
git config user.email "release-bot@osone.ai" 2>/dev/null || true
git config user.name  "OSONE Release Bot"      2>/dev/null || true

git add -A

if git diff --cached --quiet; then
  warn "Nothing new to commit"
else
  git commit -m "🎵 Music Release Prep Agent v${VERSION}

- AI-powered metadata generation (Groq LLM)
- Automated album artwork creation
- Clean release packaging with tracklist
- Docker containerized — single command deploy
- WebSocket real-time progress
- Drag & drop single/album support"
  ok "Committed"
fi

# ── Set remote & push ─────────────────────────────────────────────
if git remote get-url origin &>/dev/null; then
  git remote set-url origin "$REMOTE_URL"
else
  git remote add origin "$REMOTE_URL"
fi

log "Pushing to GitHub..."
git push -u origin main --force
ok "Code pushed!"

# ── Tag & push release ────────────────────────────────────────────
TAG="v${VERSION}"
if git rev-parse "$TAG" &>/dev/null; then
  warn "Tag $TAG already exists — skipping"
else
  git tag -a "$TAG" -m "Release $TAG"
  git push origin "$TAG"
  ok "Release tag $TAG pushed — GitHub Actions will build the Docker image"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ Music Release Prep Agent pushed to GitHub!    ${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo ""
echo -e "  📦 Repo:     https://github.com/${GITHUB_USER}/${REPO_NAME}"
echo -e "  🚀 Actions:  https://github.com/${GITHUB_USER}/${REPO_NAME}/actions"
echo -e "  📌 Release:  https://github.com/${GITHUB_USER}/${REPO_NAME}/releases"
echo ""
