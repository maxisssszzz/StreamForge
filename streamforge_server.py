from __future__ import annotations

import json
import ipaddress
import math
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit


APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HTML_FILE = "streamforge_minimalist_media_downloader.html"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads"
SETTINGS_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "StreamForge"
SETTINGS_FILE = SETTINGS_DIR / "settings.json"
DOWNLOAD_DIR = DEFAULT_DOWNLOAD_DIR
SAVE_LOCATION_CONFIGURED = False
SOURCE_DIR = APP_DIR / "yt-dlp-2026.10.21" / "yt-dlp-2026.10.21"
HOST = "127.0.0.1"
PORT = 8765
MAX_REQUEST_BYTES = 64 * 1024
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
SETTINGS_LOCK = threading.Lock()


def configure_ffmpeg_path() -> None:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return
    packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    for package_dir in packages_dir.glob("Gyan.FFmpeg.*_Microsoft.Winget.Source_*"):
        for binary_dir in package_dir.glob("*/bin"):
            if (binary_dir / "ffmpeg.exe").is_file() and (binary_dir / "ffprobe.exe").is_file():
                os.environ["PATH"] = str(binary_dir) + os.pathsep + os.environ.get("PATH", "")
                return


configure_ffmpeg_path()


def normalize_save_location(value: object) -> Path:
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise ValueError("Enter a valid folder path.")
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    path = Path(expanded)
    if not path.is_absolute():
        raise ValueError("The save location must be an absolute path.")
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        raise ValueError("Choose a folder below the drive or filesystem root.")
    return resolved


def load_save_location() -> None:
    global DOWNLOAD_DIR, SAVE_LOCATION_CONFIGURED
    if not SETTINGS_FILE.is_file():
        return
    try:
        settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        DOWNLOAD_DIR = normalize_save_location(settings.get("save_location"))
        SAVE_LOCATION_CONFIGURED = True
    except (OSError, json.JSONDecodeError, AttributeError, ValueError) as error:
        raise RuntimeError(f"Cannot load StreamForge settings from {SETTINGS_FILE}: {error}") from error


def save_location(path: Path) -> None:
    global DOWNLOAD_DIR, SAVE_LOCATION_CONFIGURED
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".streamforge-write-test-{uuid.uuid4().hex}"
    try:
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as error:
        raise ValueError(f"Cannot write to the selected folder: {error}") from error

    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    temporary_settings = SETTINGS_FILE.with_suffix(".tmp")
    try:
        temporary_settings.write_text(
            json.dumps({"save_location": str(path)}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_settings.replace(SETTINGS_FILE)
    except OSError:
        temporary_settings.unlink(missing_ok=True)
        raise

    with SETTINGS_LOCK:
        DOWNLOAD_DIR = path
        SAVE_LOCATION_CONFIGURED = True


load_save_location()


def yt_dlp_command() -> tuple[list[str], dict[str, str]]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--streamforge-yt-dlp"], os.environ.copy()

    installed = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if installed:
        return [installed], os.environ.copy()

    for binary_name in ("yt-dlp.exe", "yt-dlp"):
        local_binary = APP_DIR / binary_name
        if local_binary.is_file():
            return [str(local_binary)], os.environ.copy()

    if SOURCE_DIR.is_dir():
        env = os.environ.copy()
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(SOURCE_DIR) + (os.pathsep + existing if existing else "")
        return [sys.executable, "-m", "yt_dlp"], env

    raise RuntimeError(
        "yt-dlp was not found. Install it with `python -m pip install -U \"yt-dlp[default]\"` "
        "or place the yt-dlp source folder next to this server."
    )


def validate_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Enter a valid media URL.")
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise ValueError("Use a public http or https media URL without embedded credentials.")

    try:
        hostname = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as error:
        raise ValueError("The media URL contains an invalid port.") from error
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, port)}
    except OSError as error:
        raise ValueError("The media URL host could not be resolved.") from error
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Local and private network URLs are not supported.")
    return value.strip()


def run_metadata(url: str) -> dict:
    command, env = yt_dlp_command()
    result = subprocess.run(
        command + [
            "--dump-single-json", "--skip-download", "--no-warnings", "--no-playlist",
            "--socket-timeout", "20", "--retries", "1", url,
        ],
        cwd=SOURCE_DIR if SOURCE_DIR.is_dir() else APP_DIR,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[-1500:] or "yt-dlp could not inspect this URL.")
    try:
        info = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("yt-dlp returned invalid metadata.") from error

    formats = info.get("formats") or []
    heights = [item.get("height") for item in formats if isinstance(item.get("height"), int)]
    widths = [item.get("width") for item in formats if isinstance(item.get("width"), int)]
    duration = info.get("duration")
    return {
        "title": info.get("title") or "Untitled media",
        "channel": info.get("uploader") or info.get("channel") or info.get("extractor_key") or "Unknown source",
        "views": info.get("view_count"),
        "uploadDate": info.get("upload_date"),
        "durationSeconds": duration if isinstance(duration, (int, float)) else None,
        "thumbnail": info.get("thumbnail") or "",
        "webpageUrl": info.get("webpage_url") or url,
        "extractor": info.get("extractor_key") or info.get("extractor") or "",
        "maxHeight": max(heights, default=None),
        "maxWidth": max(widths, default=None),
        "hasAudio": any(item.get("acodec") not in (None, "none") for item in formats),
    }


def validate_options(payload: dict) -> dict:
    mode = payload.get("mode", "video")
    if mode not in {"video", "audio", "gif"}:
        raise ValueError("Unsupported output type.")
    quality = payload.get("videoQuality", "1080p")
    if quality not in {"480p", "720p", "1080p", "2160p"}:
        raise ValueError("Unsupported video resolution.")
    container = str(payload.get("videoContainer", "MP4")).lower()
    if container not in {"mp4", "webm", "mkv"}:
        raise ValueError("Unsupported video container.")
    codec = str(payload.get("audioCodec", "MP3")).lower()
    if codec not in {"mp3", "m4a", "opus", "wav", "flac"}:
        raise ValueError("Unsupported audio format.")
    bitrate = str(payload.get("audioBitrate", "320"))
    if bitrate not in {"128", "256", "320"}:
        raise ValueError("Unsupported audio bitrate.")
    fps = payload.get("gifFps", 24)
    width = payload.get("gifWidth", "480")
    if fps not in {15, 24, 30} or str(width) not in {"320", "480", "720"}:
        raise ValueError("Unsupported GIF settings.")
    subtitle_format = str(payload.get("subFormat", "srt")).lower()
    if subtitle_format not in {"srt", "vtt", "ass"}:
        raise ValueError("Unsupported subtitle format.")
    language = str(payload.get("subLang", "en"))
    if not re.fullmatch(r"[A-Za-z0-9,-]{1,32}", language):
        raise ValueError("Invalid subtitle language.")

    start = payload.get("trimStart", 0)
    end = payload.get("trimEnd", 0)
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        raise ValueError("Invalid trim range.")
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < 0 or end > 21600:
        raise ValueError("Trim times must be between 0 and 6 hours.")
    if end and end <= start:
        raise ValueError("The end time must be later than the start time.")
    duration = payload.get("durationSeconds")
    if start == 0 and isinstance(duration, (int, float)) and duration > 0 and end >= duration:
        end = 0
    return {
        **payload,
        "mode": mode,
        "quality": int(quality.removesuffix("p")),
        "container": container,
        "codec": codec,
        "bitrate": bitrate,
        "fps": fps,
        "width": int(width),
        "subtitleFormat": subtitle_format,
        "language": language,
        "trimStart": float(start),
        "trimEnd": float(end),
    }


def fmt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int(seconds % 3600 // 60)
    whole_seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:05.2f}"


def update_job(job_id: str, **values) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(values)


def promote_download(filepath: Path, staging_dir: Path, download_dir: Path, options: dict) -> Path:
    if options["mode"] == "video":
        quality_label = f"{options['quality']}p" + ("" if options["includeAudio"] else "-video-only")
    elif options["mode"] == "audio":
        quality_label = f"{options['codec'].upper()}-{options['bitrate']}kbps"
    else:
        quality_label = f"GIF-{options['fps']}fps-{options['width']}px"

    final_stem = f"{filepath.stem} [{quality_label}]"
    staged_files = sorted(
        (
            path for path in staging_dir.iterdir()
            if path.is_file() and (path == filepath or path.name.startswith(filepath.stem))
        ),
        key=lambda path: path != filepath,
    )
    promoted_path = None
    for staged_file in staged_files:
        suffix = staged_file.name[len(filepath.stem):]
        final_path = download_dir / f"{final_stem}{suffix}"
        os.replace(staged_file, final_path)
        if staged_file == filepath:
            promoted_path = final_path

    if promoted_path is None:
        raise RuntimeError("The completed media file could not be moved into the save location.")
    return promoted_path


def run_download(job_id: str, url: str, options: dict) -> None:
    with JOBS_LOCK:
        cancelled = JOBS[job_id].get("cancel_requested")
    if cancelled:
        update_job(job_id, status="cancelled", message="Download cancelled.")
        return
    staging_dir = None
    try:
        with SETTINGS_LOCK:
            download_dir = DOWNLOAD_DIR
        download_dir.mkdir(parents=True, exist_ok=True)
        command, env = yt_dlp_command()
        staging_dir = download_dir / f".streamforge-{job_id}"
        staging_dir.mkdir()
    except Exception as error:
        update_job(job_id, status="error", message=str(error))
        return
    output_template = str(staging_dir / "%(title).180B [%(id)s].%(ext)s")
    args = command + [
        "--newline", "--no-colors", "--no-warnings", "--no-playlist",
        "--socket-timeout", "20", "--retries", "2", "--output", output_template,
        "--print", "after_move:filepath",
    ]

    if options["mode"] == "audio":
        args += ["--extract-audio", "--audio-format", options["codec"], "--audio-quality", options["bitrate"] + "K"]
    elif options["mode"] == "gif":
        args += [
            "--format",
            f"bestvideo[height<={options['quality']}][ext=mp4]+bestaudio[ext=m4a]/best[height<={options['quality']}][ext=mp4]",
            "--merge-output-format", "mp4",
        ]
    elif options["includeAudio"] and options["container"] == "webm":
        args += [
            "--format",
            f"bestvideo[height<={options['quality']}][ext=webm]+bestaudio[ext=webm]/best[height<={options['quality']}][ext=webm]",
            "--merge-output-format", "webm",
        ]
    elif options["includeAudio"] and options["container"] == "mp4":
        args += [
            "--format",
            f"bestvideo[height<={options['quality']}][ext=mp4]+bestaudio[ext=m4a]/best[height<={options['quality']}][ext=mp4]",
            "--merge-output-format", "mp4",
        ]
    elif options["includeAudio"]:
        args += [
            "--format",
            f"bestvideo[height<={options['quality']}]+bestaudio/best[height<={options['quality']}]",
            "--merge-output-format", options["container"],
        ]
    else:
        args += ["--format", f"bestvideo[height<={options['quality']}]"]

    if options["mode"] == "video" and options["embedMetadata"]:
        args.append("--embed-metadata")
    if options["mode"] == "audio" and options["embedMetadata"]:
        args += ["--embed-metadata", "--embed-thumbnail"]
    if options["downloadSubs"]:
        args += [
            "--write-subs", "--write-auto-subs", "--sub-langs", options["language"],
            "--sub-format", options["subtitleFormat"] + "/best", "--convert-subs", options["subtitleFormat"],
        ]
    if options["trimEnd"]:
        args += ["--download-sections", f"*{fmt_time(options['trimStart'])}-{fmt_time(options['trimEnd'])}", "--force-keyframes-at-cuts"]
    args += ["--progress", url]

    try:
        with JOBS_LOCK:
            if JOBS[job_id].get("cancel_requested"):
                cancelled = True
                process = None
            else:
                cancelled = False
                JOBS[job_id].update(status="running", message="Starting yt-dlp…")
                process = subprocess.Popen(
                    args,
                    cwd=SOURCE_DIR if SOURCE_DIR.is_dir() else APP_DIR,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                JOBS[job_id]["process"] = process
        if cancelled:
            update_job(job_id, status="cancelled", message="Download cancelled.")
            return
        filepath = None
        errors = []
        assert process.stdout is not None
        for line in process.stdout:
            clean = line.strip()
            if not clean:
                continue
            if clean.startswith(str(staging_dir)):
                filepath = Path(clean)
            match = re.search(r"\[download\]\s+([\d.]+)%", clean)
            if match:
                percentage = min(100.0, max(0.0, float(match.group(1))))
                speed_match = re.search(r"\bat\s+(.+?)(?:\s+ETA|\s*$)", clean)
                eta_match = re.search(r"\bETA\s+(.+)$", clean)
                update_job(
                    job_id,
                    progress=int(percentage * (0.85 if options["mode"] == "gif" else 1)),
                    message="Downloading media…",
                    speed=speed_match.group(1).strip() if speed_match else "—",
                    eta=eta_match.group(1).strip() if eta_match else "—",
                )
            elif any(word in clean.lower() for word in ("merging formats", "post-processing", "extracting audio")):
                with JOBS_LOCK:
                    current_progress = JOBS[job_id]["progress"]
                update_job(job_id, progress=max(current_progress, 90), message="Processing media…")
            elif clean.startswith("ERROR:"):
                errors.append(clean)
                errors = errors[-5:]

        return_code = process.wait(timeout=14400)
        with JOBS_LOCK:
            cancelled = JOBS[job_id].get("cancel_requested")
        if cancelled:
            update_job(job_id, status="cancelled", message="Download cancelled.")
            return
        if return_code:
            raise RuntimeError("\n".join(errors) or "yt-dlp could not complete this download.")
        if not filepath or not filepath.is_file() or not filepath.resolve().is_relative_to(download_dir.resolve()):
            raise RuntimeError("yt-dlp finished but the output file could not be found.")

        if options["mode"] == "gif":
            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                raise RuntimeError("GIF output requires ffmpeg. Install ffmpeg, then try again.")
            gif_path = filepath.with_suffix(".gif")
            update_job(job_id, progress=90, message="Creating animated GIF…")
            conversion = subprocess.run(
                [
                    ffmpeg, "-y", "-i", str(filepath),
                    "-filter_complex",
                    f"[0:v]fps={options['fps']},scale={options['width']}:-1:flags=lanczos,split[a][b];"
                    f"[a]palettegen[p];[b][p]paletteuse",
                    str(gif_path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=3600,
                check=False,
            )
            if conversion.returncode:
                raise RuntimeError(conversion.stderr.strip()[-1200:] or "ffmpeg could not create the GIF.")
            filepath.unlink(missing_ok=True)
            filepath = gif_path

        filepath = promote_download(filepath, staging_dir, download_dir, options)
        update_job(
            job_id,
            status="complete",
            progress=100,
            message="Download complete.",
            file_path=filepath,
            file_name=filepath.name,
            file_size=filepath.stat().st_size,
        )
    except Exception as error:
        update_job(job_id, status="error", message=str(error))
    finally:
        if staging_dir and staging_dir.exists():
            try:
                shutil.rmtree(staging_dir)
            except OSError as error:
                print(f"[StreamForge] Could not remove temporary download folder {staging_dir}: {error}")


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_DIR), **kwargs)

    def log_message(self, format, *args):
        print(f"[StreamForge] {self.address_string()} {format % args}")

    def translate_path(self, path: str) -> str:
        if path.split("?", 1)[0] in {"/", "/" + HTML_FILE}:
            return str(APP_DIR / HTML_FILE)
        return str(APP_DIR / "__not_found__")

    def send_json(self, status: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def check_local_request(self) -> bool:
        if self.headers.get("Host", "").split(":", 1)[0] not in {"127.0.0.1", "localhost"}:
            self.send_json(403, {"error": "Only local StreamForge requests are allowed."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in {"http://127.0.0.1:8765", "http://localhost:8765"}:
            self.send_json(403, {"error": "Cross-origin requests are not allowed."})
            return False
        return True

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError("Invalid request size.")
        data = json.loads(self.rfile.read(length))
        if not isinstance(data, dict):
            raise ValueError("Invalid request body.")
        return data

    def do_GET(self):
        if not self.check_local_request():
            return
        if self.path == "/api/health":
            try:
                command, env = yt_dlp_command()
                result = subprocess.run(
                    command + ["--version"],
                    cwd=SOURCE_DIR if SOURCE_DIR.is_dir() else APP_DIR,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=15,
                    check=False,
                )
                if result.returncode:
                    raise RuntimeError(result.stderr.strip() or "yt-dlp could not start.")
                self.send_json(200, {"ok": True, "version": result.stdout.strip(), "ffmpeg": bool(shutil.which("ffmpeg"))})
            except Exception as error:
                self.send_json(503, {"ok": False, "error": str(error)})
            return

        if self.path == "/api/settings":
            with SETTINGS_LOCK:
                data = {
                    "saveLocation": str(DOWNLOAD_DIR),
                    "configured": SAVE_LOCATION_CONFIGURED,
                    "defaultSaveLocation": str(DEFAULT_DOWNLOAD_DIR),
                }
            self.send_json(200, data)
            return

        match = re.fullmatch(r"/api/jobs/([a-f0-9]+)/file", self.path)
        if match:
            with JOBS_LOCK:
                job = JOBS.get(match.group(1))
            filepath = job.get("file_path") if job else None
            if not filepath or not Path(filepath).is_file():
                self.send_json(404, {"error": "The completed file is no longer available."})
                return
            file_path = Path(filepath)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(file_path.stat().st_size))
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(file_path.name))
            self.end_headers()
            try:
                with file_path.open("rb") as stream:
                    shutil.copyfileobj(stream, self.wfile)
            except (BrokenPipeError, ConnectionResetError):
                return
            with JOBS_LOCK:
                JOBS.pop(match.group(1), None)
            return

        match = re.fullmatch(r"/api/jobs/([a-f0-9]+)", self.path)
        if match:
            with JOBS_LOCK:
                job = JOBS.get(match.group(1))
                if job:
                    data = {key: job.get(key) for key in ("status", "progress", "message", "file_name", "file_size", "speed", "eta")}
            if not job:
                self.send_json(404, {"error": "Download job not found."})
            else:
                self.send_json(200, data)
            return

        super().do_GET()

    def do_POST(self):
        if not self.check_local_request():
            return
        try:
            payload = self.read_json()
            if self.path == "/api/settings":
                location = normalize_save_location(payload.get("saveLocation"))
                save_location(location)
                self.send_json(200, {
                    "saveLocation": str(location),
                    "configured": True,
                    "defaultSaveLocation": str(DEFAULT_DOWNLOAD_DIR),
                })
                return
            if self.path == "/api/info":
                url = validate_url(payload.get("url"))
                self.send_json(200, run_metadata(url))
                return
            if self.path == "/api/download":
                url = validate_url(payload.get("url"))
                options = validate_options(payload)
                with JOBS_LOCK:
                    if sum(job["status"] in {"queued", "running"} for job in JOBS.values()) >= 2:
                        raise ValueError("Two downloads are already running. Wait for one to finish.")
                    job_id = uuid.uuid4().hex
                    JOBS[job_id] = {
                        "status": "queued", "progress": 0, "message": "Queued…",
                        "cancel_requested": False, "process": None,
                    }
                threading.Thread(target=run_download, args=(job_id, url, options), daemon=True).start()
                self.send_json(202, {"id": job_id})
                return
            self.send_json(404, {"error": "Unknown API endpoint."})
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
        except subprocess.TimeoutExpired:
            self.send_json(504, {"error": "yt-dlp timed out while inspecting this URL."})
        except Exception as error:
            self.send_json(500, {"error": str(error)})

    def do_DELETE(self):
        if not self.check_local_request():
            return
        match = re.fullmatch(r"/api/jobs/([a-f0-9]+)", self.path)
        if not match:
            self.send_json(404, {"error": "Unknown API endpoint."})
            return
        with JOBS_LOCK:
            job = JOBS.get(match.group(1))
            if not job or job["status"] not in {"queued", "running"}:
                self.send_json(404, {"error": "Active download job not found."})
                return
            job["cancel_requested"] = True
            process = job.get("process")
        if process and process.poll() is None:
            process.terminate()
        self.send_json(200, {"ok": True})


def run_server() -> None:
    if not (APP_DIR / HTML_FILE).is_file():
        raise SystemExit(f"StreamForge interface file not found: {APP_DIR / HTML_FILE}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    address = f"http://{HOST}:{server.server_port}"
    print(f"StreamForge is ready at {address}")
    print("Press Ctrl+C to stop the local server.")
    threading.Timer(1, webbrowser.open, args=(address,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping StreamForge…")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
