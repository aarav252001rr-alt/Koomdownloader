"""
🎵 YouTube Music API v1.0
FastAPI + yt-dlp | Render.com Ready
"""

import os
import re
import time
import uuid
import asyncio
import secrets
import logging
from typing import Optional, List, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Header, Depends, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl, Field
import httpx
import yt_dlp


# ============================================
# Config
# ============================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("ytmusic-api")

API_KEY = os.getenv("API_KEY", "")  # optional
STREAM_TTL = int(os.getenv("STREAM_TTL", "300"))  # 5 min
COOKIES_FILE = os.getenv("COOKIES_FILE", "/app/cookies.txt")
MAX_STREAM_SIZE = int(os.getenv("MAX_STREAM_SIZE", str(200 * 1024 * 1024)))  # 200MB

# In-memory temp stream store (single instance)
STREAM_CACHE: Dict[str, Dict[str, Any]] = {}


# ============================================
# Cleanup task (background)
# ============================================
async def cleanup_expired():
    while True:
        now = time.time()
        expired = [k for k, v in STREAM_CACHE.items() if v["expires"] < now]
        for k in expired:
            STREAM_CACHE.pop(k, None)
        if expired:
            logger.info(f"Cleaned {len(expired)} expired stream tokens")
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup_expired())
    logger.info("YTMusic API started")
    yield
    task.cancel()
    logger.info("YTMusic API stopped")


# ============================================
# App
# ============================================
app = FastAPI(
    title="🎵 YouTube Music API",
    description="Fetch info, formats, quality & temporary stream URLs from YouTube Music",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================
# Auth (optional API key)
# ============================================
async def verify_key(x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True


# ============================================
# Models
# ============================================
class FormatInfo(BaseModel):
    format_id: str
    ext: str
    acodec: Optional[str] = None
    abr: Optional[float] = None
    asr: Optional[int] = None
    filesize: Optional[int] = None
    quality_label: Optional[str] = None
    url: Optional[str] = None  # removed from public response


class InfoResponse(BaseModel):
    id: str
    title: str
    uploader: Optional[str] = None
    duration: Optional[int] = None
    duration_string: Optional[str] = None
    view_count: Optional[int] = None
    upload_date: Optional[str] = None
    thumbnail: Optional[str] = None
    webpage_url: str
    is_playlist: bool = False
    formats: List[FormatInfo] = []


class StreamRequest(BaseModel):
    url: HttpUrl = Field(..., description="YouTube Music URL")
    format_id: str = Field(..., description="Format ID from /info (e.g. 251, 140)")
    # Optional: ask for conversion (uses ffmpeg)
    convert_to: Optional[str] = Field(None, description="mp3, m4a, opus, flac, wav, ogg, aac")


class StreamResponse(BaseModel):
    stream_url: str
    expires_in: int
    format_id: str
    ext: str
    convert_to: Optional[str] = None
    token: str


# ============================================
# yt-dlp helpers
# ============================================
def _get_ydl_opts(extra: Optional[dict] = None) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
        "socket_timeout": 30,
        # Yeh add karo - multiple clients try karega
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb", "tv", "android", "ios"],
                "player_skip": ["webpage", "configs"],
            }
        },
    }
    if os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    if extra:
        opts.update(extra)
    return opts


def _detect_quality_label(abr: Optional[float], acodec: Optional[str]) -> str:
    if abr is None:
        return "unknown"
    if abr >= 256:
        return f"{int(abr)}kbps (Very High)"
    if abr >= 192:
        return f"{int(abr)}kbps (High)"
    if abr >= 128:
        return f"{int(abr)}kbps (Medium)"
    if abr >= 96:
        return f"{int(abr)}kbps (Low)"
    return f"{int(abr)}kbps (Very Low)"


def fetch_video_info(url: str) -> dict:
    """Blocking yt-dlp call - runs in thread pool"""
    with yt_dlp.YoutubeDL(_get_ydl_opts()) as ydl:
        return ydl.extract_info(url, download=False)


def extract_audio_formats(info: dict) -> List[Dict]:
    """Return audio-only formats, sorted by bitrate desc"""
    fmts = []
    for f in info.get("formats", []) or []:
        if f.get("vcodec") not in (None, "none"):
            continue
        if not f.get("acodec") or f.get("acodec") == "none":
            continue

        fmts.append({
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "acodec": f.get("acodec"),
            "abr": f.get("abr"),
            "asr": f.get("asr"),
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "quality_label": _detect_quality_label(f.get("abr"), f.get("acodec")),
        })

    # dedupe by (ext, abr)
    seen = set()
    out = []
    for f in sorted(fmts, key=lambda x: (x["abr"] or 0), reverse=True):
        key = (f["ext"], round(f["abr"] or 0))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)

    return out


# ============================================
# Routes
# ============================================
@app.get("/")
async def root():
    return {
        "name": "🎵 YouTube Music API",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Health check",
            "GET /info?url=...": "Fetch metadata + audio formats",
            "POST /stream": "Create temporary stream URL",
            "GET /stream/{token}": "Proxy stream (temporary)",
            "GET /formats?url=...": "Quick list of formats only",
            "POST /download": "Get download info (no direct link)",
        },
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "ok", "time": int(time.time())}


# ---------- INFO ----------
@app.get("/info", response_model=InfoResponse, dependencies=[Depends(verify_key)])
async def info(
    url: str = Query(..., description="YouTube Music URL"),
):
    """Fetch track metadata + available audio formats (no direct URLs exposed)"""
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(400, "Only YouTube URLs allowed")

    try:
        data = await asyncio.to_thread(fetch_video_info, url)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(422, f"Extraction failed: {str(e)[:200]}")
    except Exception as e:
        logger.exception("info error")
        raise HTTPException(500, f"Server error: {str(e)[:200]}")

    formats = extract_audio_formats(data)

    return InfoResponse(
        id=data.get("id", ""),
        title=data.get("title", ""),
        uploader=data.get("uploader") or data.get("channel"),
        duration=data.get("duration"),
        duration_string=data.get("duration_string"),
        view_count=data.get("view_count"),
        upload_date=data.get("upload_date"),
        thumbnail=data.get("thumbnail"),
        webpage_url=data.get("webpage_url", url),
        is_playlist=data.get("_type") == "playlist",
        formats=[FormatInfo(**f) for f in formats],
    )


# ---------- FORMATS (shortcut) ----------
@app.get("/formats", dependencies=[Depends(verify_key)])
async def formats(url: str = Query(...)):
    """Just formats, lighter payload"""
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(400, "Only YouTube URLs allowed")

    try:
        data = await asyncio.to_thread(fetch_video_info, url)
    except Exception as e:
        raise HTTPException(422, f"Extraction failed: {str(e)[:200]}")

    return {
        "title": data.get("title"),
        "id": data.get("id"),
        "formats": extract_audio_formats(data),
    }


# ---------- STREAM CREATION ----------
@app.post("/stream", response_model=StreamResponse, dependencies=[Depends(verify_key)])
async def create_stream(req: StreamRequest):
    """
    Create a TEMPORARY stream URL.
    - Video URL is NOT exposed to user.
    - Token expires in STREAM_TTL seconds.
    - Only audio formats allowed.
    """
    url = str(req.url)
    if "youtube.com" not in url and "youtu.be" not in url:
        raise HTTPException(400, "Only YouTube URLs allowed")

    # Validate format ID & get info
    try:
        data = await asyncio.to_thread(fetch_video_info, url)
    except Exception as e:
        raise HTTPException(422, f"Extraction failed: {str(e)[:200]}")

    audio_formats = extract_audio_formats(data)
    matched = None
    for f in audio_formats:
        if f["format_id"] == req.format_id:
            matched = f
            break

    if not matched:
        raise HTTPException(400, f"Format ID '{req.format_id}' not available or not audio-only")

    # Validate convert_to
    allowed_conv = {None, "mp3", "m4a", "opus", "flac", "wav", "ogg", "aac"}
    if req.convert_to not in allowed_conv:
        raise HTTPException(400, f"convert_to must be one of {allowed_conv}")

    # Build token
    token = secrets.token_urlsafe(24)
    STREAM_CACHE[token] = {
        "url": url,
        "format_id": req.format_id,
        "ext": matched["ext"],
        "convert_to": req.convert_to,
        "expires": time.time() + STREAM_TTL,
        "title": data.get("title"),
    }

    logger.info(f"Stream token created: {token[:8]}... fmt={req.format_id} conv={req.convert_to}")

    base = os.getenv("PUBLIC_BASE_URL", "")
    stream_url = f"{base}/stream/{token}" if base else f"/stream/{token}"

    return StreamResponse(
        stream_url=stream_url,
        expires_in=STREAM_TTL,
        format_id=req.format_id,
        ext=matched["ext"],
        convert_to=req.convert_to,
        token=token,
    )


# ---------- STREAM PROXY ----------
@app.get("/stream/{token}")
async def proxy_stream(token: str, request: Request):
    """
    Proxy the actual stream. YouTube URL is hidden from user.
    Supports Range requests for seeking.
    """
    item = STREAM_CACHE.get(token)
    if not item:
        raise HTTPException(404, "Stream not found or expired")
    if item["expires"] < time.time():
        STREAM_CACHE.pop(token, None)
        raise HTTPException(410, "Stream expired")

    url = item["url"]
    fmt_id = item["format_id"]
    convert_to = item["convert_to"]

    # Build yt-dlp opts to extract direct URL
    opts = _get_ydl_opts({
        "format": fmt_id,
        "noplaylist": True,
    })

    try:
        data = await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(opts).extract_info(url, download=False))
    except Exception as e:
        raise HTTPException(502, f"Failed to resolve: {str(e)[:200]}")

    # Find the URL for the chosen format
    direct_url = None
    ext = item["ext"]
    for f in data.get("formats", []) or []:
        if f.get("format_id") == fmt_id:
            direct_url = f.get("url")
            ext = f.get("ext", ext)
            break

    if not direct_url:
        # fallback: top-level url
        direct_url = data.get("url")
        ext = data.get("ext", ext)

    if not direct_url:
        raise HTTPException(502, "Could not resolve direct URL")

    # --- If no conversion, just proxy bytes ---
    if not convert_to:
        return await _proxy_bytes(direct_url, ext, request)

    # --- If conversion requested ---
    return await _proxy_ffmpeg(direct_url, convert_to, request)


# ---------- Helpers: byte proxy ----------
async def _proxy_bytes(direct_url: str, ext: str, request: Request):
    """Simple byte-range proxy"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
    }
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    mime = {
        "m4a": "audio/mp4",
        "mp3": "audio/mpeg",
        "opus": "audio/ogg",
        "webm": "audio/webm",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "aac": "audio/aac",
    }.get(ext, "application/octet-stream")

    client = httpx.AsyncClient(timeout=60.0, follow_redirects=True)
    req = client.build_request("GET", direct_url, headers=headers)
    resp = await client.send(req, stream=True)

    if resp.status_code not in (200, 206):
        await resp.aclose()
        await client.aclose()
        raise HTTPException(502, f"Upstream error {resp.status_code}")

    async def streamer():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    resp_headers = {
        "Content-Type": mime,
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    if "content-length" in resp.headers:
        resp_headers["Content-Length"] = resp.headers["content-length"]
    if "content-range" in resp.headers:
        resp_headers["Content-Range"] = resp.headers["content-range"]

    return StreamingResponse(
        streamer(),
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=mime,
    )


# ---------- Helpers: ffmpeg convert + proxy ----------
async def _proxy_ffmpeg(direct_url: str, target_fmt: str, request: Request):
    """Pipe through ffmpeg -> response. No range support (live transcode)."""
    mime_map = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "opus": "audio/ogg",
        "ogg": "audio/ogg",
        "flac": "audio/flac",
        "wav": "audio/wav",
        "aac": "audio/aac",
    }
    mime = mime_map.get(target_fmt, "application/octet-stream")

    # ffmpeg command
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-vn",
        "-f", target_fmt,
    ]

    # format-specific quality
    if target_fmt == "mp3":
        cmd += ["-codec:a", "libmp3lame", "-b:a", "192k"]
    elif target_fmt == "m4a":
        cmd += ["-codec:a", "aac", "-b:a", "192k"]
    elif target_fmt == "opus":
        cmd += ["-codec:a", "libopus", "-b:a", "160k"]
    elif target_fmt == "ogg":
        cmd += ["-codec:a", "libvorbis", "-q:a", "5"]
    elif target_fmt == "flac":
        cmd += ["-codec:a", "flac"]
    elif target_fmt == "wav":
        cmd += ["-codec:a", "pcm_s16le"]
    elif target_fmt == "aac":
        cmd += ["-codec:a", "aac", "-b:a", "192k"]

    cmd += ["pipe:1"]

    # Download upstream (whole thing in memory - simple; fine for songs)
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        async with client.stream("GET", direct_url, headers={
            "User-Agent": "Mozilla/5.0",
        }) as resp:
            if resp.status_code not in (200, 206):
                raise HTTPException(502, f"Upstream {resp.status_code}")

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            async def feed_stdin():
                try:
                    async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                        proc.stdin.write(chunk)
                        await proc.stdin.drain()
                except Exception:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass

            asyncio.create_task(feed_stdin())

            async def reader():
                try:
                    while True:
                        chunk = await proc.stdout.read(64 * 1024)
                        if not chunk:
                            break
                        yield chunk
                finally:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            return StreamingResponse(
                reader(),
                media_type=mime,
                headers={
                    "Content-Disposition": f'attachment; filename="audio.{target_fmt}"',
                    "Cache-Control": "no-store",
                },
            )


# ---------- DOWNLOAD (info only, no direct link) ----------
@app.post("/download", dependencies=[Depends(verify_key)])
async def download_info(req: StreamRequest):
    """
    Same as /stream but returns a token instead of a URL.
    Use /stream/{token} to fetch bytes.
    """
    return await create_stream(req)


# ============================================
# Error handlers
# ============================================
@app.exception_handler(HTTPException)
async def http_exc_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": exc.status_code},
    )
