import os
import re
import tempfile
import subprocess
from pathlib import Path
from typing import Optional

import yt_dlp

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware


# ============================================================
# CONFIG
# ============================================================

APP_NAME = "YouTube Music API"

API_KEY = os.getenv("API_KEY", "Mys1104")

COOKIES_FILE = os.getenv(
    "COOKIES_FILE",
    "/app/cookies.txt"
)

DOWNLOAD_DIR = Path(
    os.getenv(
        "DOWNLOAD_DIR",
        "/tmp/downloads"
    )
)

DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title=APP_NAME,
    version="1.2.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# API KEY
# ============================================================

def check_api_key(
    x_api_key: Optional[str]
):
    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key"
        )


# ============================================================
# SANITIZE LOG / ERROR
# ============================================================

def sanitize_text(text):

    text = str(text)

    patterns = [
        r"(?i)cookie[^,\n]*",
        r"(?i)authorization[^,\n]*",
        r"(?i)proxy[^,\n]*",
        r"(?i)po[_ -]?token[^,\n]*",
    ]

    for pattern in patterns:
        text = re.sub(
            pattern,
            "[REDACTED]",
            text
        )

    if len(text) > 2000:
        text = text[:2000] + "..."

    return text


def sanitize_error(error):
    return sanitize_text(error)


# ============================================================
# YT-DLP OPTIONS
# ============================================================

def get_ydl_opts(
    client: Optional[str] = None
):

    opts = {

        "quiet": True,

        "no_warnings": True,

        "skip_download": True,

        "noplaylist": True,

        # JavaScript runtime
        "js_runtimes": {
            "deno": {}
        },

        # Network
        "socket_timeout": 30,

        "retries": 2,

        # SSL
        "nocheckcertificate": False,

        # Browser headers
        "http_headers": {

            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "(KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36",

            "Accept-Language":
                "en-US,en;q=0.9",

            "Accept":
                "text/html,application/xhtml+xml,"
                "application/xml;q=0.9,*/*;q=0.8"
        }
    }

    # --------------------------------------------------------
    # YouTube client
    # --------------------------------------------------------

    if client:

        opts["extractor_args"] = {

            "youtube": {

                "player_client": [
                    client
                ]
            }
        }

    # --------------------------------------------------------
    # Cookies
    # --------------------------------------------------------

    if os.path.exists(
        COOKIES_FILE
    ):

        opts["cookiefile"] = (
            COOKIES_FILE
        )

    return opts


# ============================================================
# VERBOSE LOGGER
# ============================================================

class YTDLPLogger:

    def __init__(self):
        self.logs = []

    def _add(self, level, message):

        text = sanitize_text(
            message
        )

        if not text:
            return

        self.logs.append({
            "level": level,
            "message": text
        })

    def debug(self, message):

        self._add(
            "debug",
            message
        )

    def warning(self, message):

        self._add(
            "warning",
            message
        )

    def error(self, message):

        self._add(
            "error",
            message
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {

        "name":
            APP_NAME,

        "status":
            "online",

        "version":
            "1.2.0",

        "yt_dlp":
            yt_dlp.version.__version__,

        "endpoints": [

            "/",

            "/health",

            "/debug",

            "/debug/youtube",

            "/debug/verbose",

            "/info",

            "/download"

        ]
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    return {

        "status":
            "ok",

        "yt_dlp":
            yt_dlp.version.__version__
    }


# ============================================================
# DEBUG
# ============================================================

@app.get("/debug")
async def debug(

    x_api_key: Optional[str] = Header(
        default=None
    )

):

    check_api_key(
        x_api_key
    )

    deno_version = None

    try:

        result = subprocess.run(

            [
                "deno",
                "--version"
            ],

            capture_output=True,

            text=True,

            timeout=10
        )

        deno_version = (
            result.stdout
            .strip()
            .splitlines()
        )

    except Exception:

        deno_version = [
            "Deno unavailable"
        ]

    cookie_exists = (
        os.path.exists(
            COOKIES_FILE
        )
    )

    cookie_size = 0

    if cookie_exists:

        try:

            cookie_size = os.path.getsize(
                COOKIES_FILE
            )

        except Exception:

            cookie_size = 0

    return {

        "yt_dlp_version":
            yt_dlp.version.__version__,

        "cookies_file": {

            "path":
                COOKIES_FILE,

            "exists":
                cookie_exists,

            "size":
                cookie_size
        },

        "js_runtime": {

            "deno":
                bool(deno_version),

            "deno_version":
                deno_version
        }
    }


# ============================================================
# INFO
# ============================================================

@app.get("/info")
async def info(

    url: str = Query(...),

    x_api_key: Optional[str] = Header(
        default=None
    )

):

    check_api_key(
        x_api_key
    )

    try:

        opts = get_ydl_opts()

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info_data = ydl.extract_info(
                url,
                download=False
            )

        formats = []

        for fmt in info_data.get(
            "formats",
            []
        ):

            formats.append({

                "format_id":
                    fmt.get("format_id"),

                "ext":
                    fmt.get("ext"),

                "resolution":
                    fmt.get("resolution"),

                "height":
                    fmt.get("height"),

                "width":
                    fmt.get("width"),

                "fps":
                    fmt.get("fps"),

                "vcodec":
                    fmt.get("vcodec"),

                "acodec":
                    fmt.get("acodec"),

                "abr":
                    fmt.get("abr"),

                "tbr":
                    fmt.get("tbr"),

                "filesize":
                    fmt.get("filesize"),

                "url":
                    fmt.get("url")
            })

        return {

            "status":
                "success",

            "id":
                info_data.get("id"),

            "title":
                info_data.get("title"),

            "channel":
                info_data.get("channel"),

            "uploader":
                info_data.get("uploader"),

            "duration":
                info_data.get("duration"),

            "thumbnail":
                info_data.get("thumbnail"),

            "description":
                info_data.get("description"),

            "webpage_url":
                info_data.get("webpage_url"),

            "view_count":
                info_data.get("view_count"),

            "upload_date":
                info_data.get("upload_date"),

            "formats":
                formats
        }

    except Exception as e:

        return JSONResponse(

            status_code=422,

            content={

                "error":
                    "Extraction failed: "
                    + sanitize_error(e),

                "status":
                    422
            }
        )


# ============================================================
# YOUTUBE CLIENT DIAGNOSTIC
# ============================================================

@app.get("/debug/youtube")
async def debug_youtube(

    url: str = Query(...),

    x_api_key: Optional[str] = Header(
        default=None
    )

):

    check_api_key(
        x_api_key
    )

    clients = [

        "tv",

        "web_embedded",

        "android_vr",

        "web",

        "mweb",

        "web_music"
    ]

    results = []

    for client in clients:

        try:

            opts = get_ydl_opts(
                client=client
            )

            with yt_dlp.YoutubeDL(
                opts
            ) as ydl:

                info_data = ydl.extract_info(
                    url,
                    download=False
                )

            formats = info_data.get(
                "formats",
                []
            )

            results.append({

                "client":
                    client,

                "status":
                    "PASS",

                "id":
                    info_data.get("id"),

                "title":
                    info_data.get("title"),

                "duration":
                    info_data.get("duration"),

                "formats":
                    len(formats)
            })

        except Exception as e:

            results.append({

                "client":
                    client,

                "status":
                    "FAIL",

                "error":
                    sanitize_error(e)
            })

    return {

        "status":
            "completed",

        "yt_dlp":
            yt_dlp.version.__version__,

        "url":
            url,

        "results":
            results
    }


# ============================================================
# VERBOSE DIAGNOSTIC
# ============================================================

@app.get("/debug/verbose")
async def debug_verbose(

    url: str = Query(...),

    x_api_key: Optional[str] = Header(
        default=None
    )

):

    check_api_key(
        x_api_key
    )

    logger = YTDLPLogger()

    opts = get_ydl_opts()

    opts.update({

        "quiet":
            False,

        "no_warnings":
            False,

        "verbose":
            True,

        "logger":
            logger
    })

    try:

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            info_data = ydl.extract_info(
                url,
                download=False
            )

        return {

            "status":
                "PASS",

            "yt_dlp":
                yt_dlp.version.__version__,

            "id":
                info_data.get("id"),

            "title":
                info_data.get("title"),

            "duration":
                info_data.get("duration"),

            "logs":
                logger.logs[-200:]
        }

    except Exception as e:

        return {

            "status":
                "FAIL",

            "yt_dlp":
                yt_dlp.version.__version__,

            "error":
                sanitize_error(e),

            "log_count":
                len(logger.logs),

            "logs":
                logger.logs[-250:]
        }


# ============================================================
# DOWNLOAD
# ============================================================

@app.get("/download")
async def download(

    url: str = Query(...),

    format_id: str = Query(
        "bestaudio"
    ),

    x_api_key: Optional[str] = Header(
        default=None
    )

):

    check_api_key(
        x_api_key
    )

    try:

        temp_dir = tempfile.mkdtemp(
            dir=str(
                DOWNLOAD_DIR
            )
        )

        output_template = os.path.join(
            temp_dir,
            "%(title)s.%(ext)s"
        )

        opts = get_ydl_opts()

        opts.update({

            "skip_download":
                False,

            "format":
                format_id,

            "outtmpl":
                output_template,

            "noplaylist":
                True,

            "postprocessors": [

                {

                    "key":
                        "FFmpegExtractAudio",

                    "preferredcodec":
                        "mp3",

                    "preferredquality":
                        "192"
                }
            ]
        })

        with yt_dlp.YoutubeDL(
            opts
        ) as ydl:

            ydl.extract_info(
                url,
                download=True
            )

        files = list(
            Path(temp_dir).glob("*")
        )

        if not files:

            raise Exception(
                "Downloaded file not found"
            )

        mp3_files = [

            f for f in files

            if f.suffix.lower() == ".mp3"
        ]

        if mp3_files:

            file_path = mp3_files[0]

        else:

            file_path = files[0]

        if not file_path.exists():

            raise Exception(
                "Downloaded file does not exist"
            )

        return FileResponse(

            path=str(
                file_path
            ),

            filename=file_path.name,

            media_type="audio/mpeg"
        )

    except Exception as e:

        return JSONResponse(

            status_code=422,

            content={

                "error":
                    "Download failed: "
                    + sanitize_error(e),

                "status":
                    422
            }
        )


# ============================================================
# STARTUP
# ============================================================

@app.on_event(
    "startup"
)
async def startup_event():

    print("=" * 60)

    print(
        APP_NAME
    )

    print("=" * 60)

    print(
        "yt-dlp:",
        yt_dlp.version.__version__
    )

    print(
        "Cookies:",
        os.path.exists(
            COOKIES_FILE
        )
    )

    print(
        "Cookie path:",
        COOKIES_FILE
    )

    try:

        result = subprocess.run(

            [
                "deno",
                "--version"
            ],

            capture_output=True,

            text=True,

            timeout=10
        )

        print(
            result.stdout
        )

    except Exception:

        print(
            "Deno unavailable"
        )

    print(
        "Download directory:",
        DOWNLOAD_DIR
    )

    print("=" * 60)


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000"
        )
    )

    uvicorn.run(

        "app:app",

        host="0.0.0.0",

        port=port
    )
