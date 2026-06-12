#!/usr/bin/env python3
"""
Music Release Prep Agent - Backend
Analyzes audio, generates metadata, creates album art, packages release
"""

import os, json, time, uuid, shutil, subprocess, re, hashlib, base64
from pathlib import Path
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import threading

app = Flask(__name__, static_folder="../frontend/dist", static_url_path="")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

UPLOAD_DIR = Path("/tmp/mra_uploads")
OUTPUT_DIR = Path("/tmp/mra_output")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── helpers ──────────────────────────────────────────────────────────────────

def emit_progress(session_id, step, message, percent):
    socketio.emit("progress", {
        "session": session_id, "step": step,
        "message": message, "percent": percent
    })

def call_groq(system_prompt, user_prompt, model="meta-llama/llama-4-scout-17b-16e-instruct"):
    import urllib.request
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return None
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt}
        ],
        "temperature": 0.85,
        "max_tokens": 1500
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["choices"][0]["message"]["content"]

def analyze_audio_file(path: Path):
    """Extract basic audio metadata using ffprobe"""
    try:
        result = subprocess.run([
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path)
        ], capture_output=True, text=True, timeout=30)
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        tags = fmt.get("tags", {})
        duration = float(fmt.get("duration", 0))
        return {
            "filename": path.name,
            "duration_sec": round(duration, 1),
            "duration_str": f"{int(duration//60)}:{int(duration%60):02d}",
            "bitrate": fmt.get("bit_rate", "unknown"),
            "format": fmt.get("format_long_name", path.suffix),
            "title": tags.get("title", path.stem),
            "artist": tags.get("artist", ""),
            "album": tags.get("album", ""),
            "genre": tags.get("genre", ""),
        }
    except Exception as e:
        return {"filename": path.name, "duration_str": "?:??", "error": str(e)}

def generate_metadata(tracks_info, session_id):
    """Use Groq LLM to generate release metadata"""
    emit_progress(session_id, "analyze", "Analyzing tracks with AI...", 35)
    
    is_album = len(tracks_info) > 1
    release_type = "Album" if is_album else "Single"
    
    track_lines = "\n".join([
        f"Track {i+1}: {t['filename']} ({t.get('duration_str','?')})"
        for i, t in enumerate(tracks_info)
    ])
    
    system = """You are a professional music A&R consultant and release metadata specialist.
You analyze audio file names and metadata to generate compelling, commercially viable release information.
Always respond with valid JSON only — no markdown, no explanation."""

    user = f"""Analyze this {release_type} release and generate metadata:

FILES:
{track_lines}

Generate a JSON object with these exact fields:
{{
  "release_title": "catchy, memorable title for the {'album' if is_album else 'single'}",
  "genre": "primary genre (e.g. Electronic, Hip-Hop, Ambient, Pop, R&B)",
  "subgenre": "more specific subgenre",
  "mood": "2-3 mood descriptors comma separated (e.g. Euphoric, Melancholic, Energetic)",
  "bpm_feel": "Slow / Mid-tempo / Upbeat / High-energy",
  "description": "2-3 sentence compelling release description for music platforms",
  "hashtags": "10-15 relevant hashtags with # symbols",
  "track_titles": [array of {"original": "filename", "suggested": "clean track title"} for each track],
  "visual_style": "describe the album art style in detail for image generation — colors, mood, aesthetic, imagery",
  "image_prompt": "detailed DALL-E / Stable Diffusion prompt for a square album cover image"
}}"""

    try:
        raw = call_groq(system, user)
        # strip markdown code fences if present
        raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
        return json.loads(raw)
    except Exception as e:
        # fallback metadata
        stem = tracks_info[0]["filename"].rsplit(".", 1)[0] if tracks_info else "Untitled"
        return {
            "release_title": stem.replace("_", " ").replace("-", " ").title(),
            "genre": "Electronic",
            "subgenre": "Ambient",
            "mood": "Atmospheric, Cinematic",
            "bpm_feel": "Mid-tempo",
            "description": f"A compelling {release_type.lower()} release featuring original production.",
            "hashtags": "#music #newrelease #electronic #producer #original",
            "track_titles": [{"original": t["filename"], "suggested": t["filename"].rsplit(".", 1)[0].replace("_", " ").title()} for t in tracks_info],
            "visual_style": "Dark, atmospheric with neon accents",
            "image_prompt": "Abstract dark music album cover, neon colors, professional, square format"
        }

def generate_album_art(meta, output_path: Path, session_id):
    """Generate album art using image generation API"""
    emit_progress(session_id, "art", "Generating album artwork...", 60)
    
    # Try multiple image gen endpoints
    groq_key = os.environ.get("GROQ_API_KEY", "")
    
    prompt = meta.get("image_prompt", f"Abstract album cover art for {meta.get('release_title','Music')} — {meta.get('visual_style', 'dark moody atmosphere')}, professional, square format, no text")
    
    # Try together.ai / fal.ai if keys exist, otherwise create a beautiful SVG placeholder
    together_key = os.environ.get("TOGETHER_API_KEY", "")
    fal_key = os.environ.get("FAL_API_KEY", "")
    
    if together_key:
        try:
            import urllib.request
            body = json.dumps({
                "model": "black-forest-labs/FLUX.1-schnell-Free",
                "prompt": prompt,
                "width": 1024, "height": 1024,
                "steps": 4, "n": 1,
                "response_format": "b64_json"
            }).encode()
            req = urllib.request.Request(
                "https://api.together.xyz/v1/images/generations",
                data=body,
                headers={"Authorization": f"Bearer {together_key}", "Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
                img_b64 = data["data"][0]["b64_json"]
                with open(output_path, "wb") as f:
                    f.write(base64.b64decode(img_b64))
                return True
        except Exception as e:
            print(f"Together.ai failed: {e}")
    
    # Generate a beautiful SVG album cover as fallback
    _generate_svg_cover(meta, output_path)
    return True

def _generate_svg_cover(meta, output_path: Path):
    """Generate a beautiful SVG album cover"""
    title = meta.get("release_title", "Untitled")
    genre = meta.get("genre", "Music")
    mood = meta.get("mood", "")
    
    # Color schemes based on mood/genre
    color_map = {
        "Electronic": ("#0a0a1a", "#00ffcc", "#ff00aa", "#0066ff"),
        "Hip-Hop": ("#0d0d0d", "#ff6600", "#ffcc00", "#cc0000"),
        "Ambient": ("#050510", "#4466ff", "#aa88ff", "#224488"),
        "Pop": ("#1a0a2e", "#ff44aa", "#ffaa00", "#aa00ff"),
        "R&B": ("#0a0510", "#cc6600", "#ff9933", "#884400"),
        "Jazz": ("#0a0505", "#cc9933", "#ffcc66", "#996622"),
        "Rock": ("#050505", "#cc0000", "#ff3300", "#660000"),
    }
    
    genre_key = next((k for k in color_map if k.lower() in genre.lower()), "Electronic")
    bg, c1, c2, c3 = color_map[genre_key]
    
    # Truncate title for display
    display_title = title if len(title) <= 20 else title[:18] + "…"
    
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" 
     width="1024" height="1024" viewBox="0 0 1024 1024">
  <defs>
    <radialGradient id="bg" cx="50%" cy="40%" r="70%">
      <stop offset="0%" stop-color="{c3}" stop-opacity="1"/>
      <stop offset="100%" stop-color="{bg}" stop-opacity="1"/>
    </radialGradient>
    <radialGradient id="glow1" cx="30%" cy="30%" r="50%">
      <stop offset="0%" stop-color="{c1}" stop-opacity="0.4"/>
      <stop offset="100%" stop-color="{c1}" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="glow2" cx="70%" cy="65%" r="45%">
      <stop offset="0%" stop-color="{c2}" stop-opacity="0.35"/>
      <stop offset="100%" stop-color="{c2}" stop-opacity="0"/>
    </radialGradient>
    <filter id="blur1">
      <feGaussianBlur stdDeviation="40"/>
    </filter>
    <filter id="blur2">
      <feGaussianBlur stdDeviation="25"/>
    </filter>
    <filter id="glow-text">
      <feGaussianBlur stdDeviation="8" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  
  <!-- Background -->
  <rect width="1024" height="1024" fill="url(#bg)"/>
  
  <!-- Glow orbs -->
  <ellipse cx="300" cy="320" rx="400" ry="350" fill="url(#glow1)" filter="url(#blur1)"/>
  <ellipse cx="720" cy="680" rx="350" ry="300" fill="url(#glow2)" filter="url(#blur1)"/>
  
  <!-- Geometric art - concentric rings -->
  <g transform="translate(512,430)" opacity="0.15">
    <circle r="380" fill="none" stroke="{c1}" stroke-width="1"/>
    <circle r="320" fill="none" stroke="{c2}" stroke-width="0.8"/>
    <circle r="260" fill="none" stroke="{c1}" stroke-width="0.6"/>
    <circle r="200" fill="none" stroke="{c2}" stroke-width="0.5"/>
  </g>
  
  <!-- Abstract waveform bars -->
  <g transform="translate(150, 500)" opacity="0.6">
    {"".join([f'<rect x="{i*22}" y="{-abs(((i-18)**2 - 120) % 180 - 90) + 90}" width="14" height="{abs(((i-18)**2 - 120) % 180 - 90) + 10}" rx="4" fill="{c1 if i%3==0 else c2 if i%3==1 else c3}" opacity="{0.5 + (i%5)*0.1}"/>' for i in range(33)])}
  </g>
  
  <!-- Center diamond shape -->
  <g transform="translate(512, 420)" opacity="0.25">
    <polygon points="0,-180 155,0 0,180 -155,0" fill="none" stroke="{c1}" stroke-width="2"/>
    <polygon points="0,-120 100,0 0,120 -100,0" fill="none" stroke="{c2}" stroke-width="1.5"/>
    <polygon points="0,-60 50,0 0,60 -50,0" fill="{c1}" opacity="0.3"/>
  </g>
  
  <!-- Title text -->
  <text x="512" y="810" 
        font-family="'Arial Black', Arial, sans-serif" 
        font-size="72" font-weight="900" 
        text-anchor="middle" 
        fill="{c1}" 
        filter="url(#glow-text)"
        letter-spacing="2">{display_title.upper()}</text>
  
  <!-- Genre label -->
  <text x="512" y="870" 
        font-family="Arial, sans-serif" 
        font-size="28" font-weight="300"
        text-anchor="middle" 
        fill="white" opacity="0.6"
        letter-spacing="8">{genre.upper()}</text>
  
  <!-- Thin accent line -->
  <line x1="200" y1="890" x2="824" y2="890" stroke="{c2}" stroke-width="1" opacity="0.4"/>
  
  <!-- Corner accent dots -->
  <circle cx="80" cy="80" r="4" fill="{c1}" opacity="0.8"/>
  <circle cx="944" cy="80" r="4" fill="{c2}" opacity="0.8"/>
  <circle cx="80" cy="944" r="4" fill="{c2}" opacity="0.8"/>
  <circle cx="944" cy="944" r="4" fill="{c1}" opacity="0.8"/>
  
  <!-- Corner lines -->
  <polyline points="60,30 30,30 30,60" fill="none" stroke="{c1}" stroke-width="2" opacity="0.6"/>
  <polyline points="964,30 994,30 994,60" fill="none" stroke="{c1}" stroke-width="2" opacity="0.6"/>
  <polyline points="60,994 30,994 30,964" fill="none" stroke="{c1}" stroke-width="2" opacity="0.6"/>
  <polyline points="964,994 994,994 994,964" fill="none" stroke="{c1}" stroke-width="2" opacity="0.6"/>
</svg>"""
    
    # Save as SVG
    svg_path = output_path.with_suffix(".svg")
    svg_path.write_text(svg)
    
    # Try to convert to PNG using ImageMagick or cairosvg
    try:
        subprocess.run(["convert", "-size", "1024x1024", str(svg_path), str(output_path)],
                      capture_output=True, timeout=15)
        if not output_path.exists() or output_path.stat().st_size < 1000:
            raise Exception("convert failed")
    except:
        try:
            import cairosvg
            cairosvg.svg2png(url=str(svg_path), write_to=str(output_path), output_width=1024, output_height=1024)
        except:
            # Just keep the SVG, rename it
            shutil.copy(svg_path, output_path.with_suffix(".png"))
            shutil.move(str(svg_path), str(output_path))

def create_output_package(session_id, tracks_info, meta, art_path, session_dir):
    """Build the final organized output folder"""
    emit_progress(session_id, "package", "Building release package...", 80)
    
    release_title = meta.get("release_title", "Untitled Release")
    safe_title = re.sub(r'[^\w\s-]', '', release_title).strip().replace(' ', '_')
    
    pkg_dir = session_dir / f"RELEASE_{safe_title}"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    
    # Copy audio files with clean names
    audio_dir = pkg_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    
    track_titles_map = {t["original"]: t["suggested"] for t in meta.get("track_titles", [])}
    
    for i, track in enumerate(tracks_info):
        src = session_dir / "uploads" / track["filename"]
        if src.exists():
            ext = Path(track["filename"]).suffix
            suggested = track_titles_map.get(track["filename"], track["filename"].rsplit(".", 1)[0])
            safe_name = re.sub(r'[^\w\s-]', '', suggested).strip().replace(' ', '_')
            dst = audio_dir / f"{i+1:02d}_{safe_name}{ext}"
            shutil.copy2(src, dst)
    
    # Copy album art
    art_dir = pkg_dir / "artwork"
    art_dir.mkdir(exist_ok=True)
    if art_path.exists():
        ext = art_path.suffix or ".png"
        shutil.copy2(art_path, art_dir / f"cover{ext}")
    
    # Write metadata text file
    is_album = len(tracks_info) > 1
    release_type = "Album" if is_album else "Single"
    
    track_lines = "\n".join([
        f"  {i+1:02d}. {track_titles_map.get(t['filename'], t['filename'].rsplit('.', 1)[0])} ({t.get('duration_str', '?:??')})"
        for i, t in enumerate(tracks_info)
    ])
    
    metadata_txt = f"""╔══════════════════════════════════════════════════════════════╗
║              MUSIC RELEASE PREP — METADATA SHEET             ║
╚══════════════════════════════════════════════════════════════╝

RELEASE TYPE:    {release_type}
TITLE:           {meta.get('release_title', 'Untitled')}
GENRE:           {meta.get('genre', '')}
SUBGENRE:        {meta.get('subgenre', '')}
MOOD:            {meta.get('mood', '')}
BPM FEEL:        {meta.get('bpm_feel', '')}

──────────────────────────────────────────────────────────────
DESCRIPTION:
{meta.get('description', '')}

──────────────────────────────────────────────────────────────
TRACKLIST:
{track_lines}

──────────────────────────────────────────────────────────────
HASHTAGS:
{meta.get('hashtags', '')}

──────────────────────────────────────────────────────────────
VISUAL DIRECTION:
{meta.get('visual_style', '')}

──────────────────────────────────────────────────────────────
Generated by Music Release Prep Agent
Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}
"""
    (pkg_dir / "METADATA.txt").write_text(metadata_txt)
    
    # Write JSON metadata
    (pkg_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    
    # Create zip
    zip_path = session_dir / f"RELEASE_{safe_title}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(session_dir), f"RELEASE_{safe_title}")
    
    return pkg_dir, zip_path, metadata_txt

# ── API Routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "1.0.0"})

@app.route("/api/process", methods=["POST"])
def process_release():
    session_id = str(uuid.uuid4())[:8]
    session_dir = OUTPUT_DIR / session_id
    upload_dir = session_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "No files uploaded"}), 400
    
    # Save uploaded files
    saved = []
    for f in files:
        if f.filename:
            safe_name = re.sub(r'[^\w\s.\-]', '_', f.filename)
            path = upload_dir / safe_name
            f.save(str(path))
            saved.append(path)
    
    def run_pipeline():
        try:
            emit_progress(session_id, "upload", f"Processing {len(saved)} file(s)...", 10)
            
            # Analyze audio
            emit_progress(session_id, "analyze", "Analyzing audio files...", 20)
            tracks_info = [analyze_audio_file(p) for p in saved]
            
            # Generate metadata via LLM
            meta = generate_metadata(tracks_info, session_id)
            emit_progress(session_id, "metadata", "Metadata generated!", 50)
            
            # Generate album art
            art_path = session_dir / "cover.png"
            generate_album_art(meta, art_path, session_id)
            emit_progress(session_id, "art", "Artwork ready!", 70)
            
            # Package everything
            pkg_dir, zip_path, metadata_txt = create_output_package(
                session_id, tracks_info, meta, art_path, session_dir
            )
            emit_progress(session_id, "done", "Release package ready! 🎉", 100)
            
            # Find actual art file
            art_files = list((pkg_dir / "artwork").glob("cover*"))
            art_ext = art_files[0].suffix if art_files else ".svg"
            
            socketio.emit("complete", {
                "session": session_id,
                "metadata": meta,
                "metadata_txt": metadata_txt,
                "tracks": tracks_info,
                "zip_url": f"/api/download/{session_id}/zip",
                "art_url": f"/api/artwork/{session_id}",
                "art_ext": art_ext
            })
        except Exception as e:
            import traceback
            socketio.emit("error", {"session": session_id, "error": str(e), "trace": traceback.format_exc()})
    
    thread = threading.Thread(target=run_pipeline)
    thread.daemon = True
    thread.start()
    
    return jsonify({"session_id": session_id})

@app.route("/api/download/<session_id>/zip")
def download_zip(session_id):
    session_dir = OUTPUT_DIR / session_id
    zips = list(session_dir.glob("*.zip"))
    if not zips:
        return jsonify({"error": "Not found"}), 404
    return send_file(str(zips[0]), as_attachment=True, download_name=zips[0].name)

@app.route("/api/artwork/<session_id>")
def get_artwork(session_id):
    session_dir = OUTPUT_DIR / session_id
    # Check package folder
    for pkg in session_dir.glob("RELEASE_*"):
        art_dir = pkg / "artwork"
        if art_dir.exists():
            for ext in [".png", ".jpg", ".jpeg", ".svg"]:
                f = art_dir / f"cover{ext}"
                if f.exists():
                    mime = "image/svg+xml" if ext == ".svg" else "image/png"
                    return send_file(str(f), mimetype=mime)
    # Fallback to root cover
    for ext in [".png", ".jpg", ".svg"]:
        f = session_dir / f"cover{ext}"
        if f.exists():
            return send_file(str(f))
    return jsonify({"error": "Not found"}), 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7700))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
