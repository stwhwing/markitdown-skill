#!/usr/bin/env python3
"""media_detect.py — Recognise audio/video URLs and report missing backends.

Split out of ``url_to_markdown.py``: a video/audio link is not a document — its
page text (title, view count, nav) is not the content the user actually wants.
Transcription needs external backends, and a media URL used to fall through the
normal path and return page chrome as if it were success. This surfaces that
clearly instead.
"""
import importlib
import re
import shutil
import sys

_MEDIA_URL_RE = re.compile(
    r"(bilibili\.com/video/|bilibili\.com/bangumi|youtube\.com/watch|youtu\.be/|"
    r"vimeo\.com/|douyu\.com/|kuaishou\.com/|"
    r"\.(mp3|mp4|wav|m4a|aac|flac|ogg|opus|webm|mkv|avi|mov)(\?|$))",
    re.I,
)

_MEDIA_BACKENDS = (
    ("yt_dlp", "yt-dlp", "pip install yt-dlp"),
    ("whisper", "openai-whisper", "pip install openai-whisper"),
    ("speech_recognition", "SpeechRecognition", "pip install SpeechRecognition"),
    ("youtube_transcript_api", "youtube-transcript-api", "pip install youtube-transcript-api"),
)


def missing_media_backends():
    """Return human-readable list of missing media/transcription dependencies."""
    missing = []
    if not (shutil.which("ffmpeg") or shutil.which("avconv")):
        missing.append("ffmpeg — 音视频解码/转换，必需（用系统包管理器安装）")
    for mod, label, cmd in _MEDIA_BACKENDS:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            missing.append(f"{label} — {cmd}")
    return missing


def warn_media_backends(url):
    """If `url` is a media link, report missing transcription backends once."""
    if not _MEDIA_URL_RE.search(url or ""):
        return
    missing = missing_media_backends()
    if not missing:
        return
    print("[media] 检测到音视频链接。本工具只能返回网页侧文本（标题/简介等），"
          "无法产出音视频正文转写；当前环境缺少以下转写后端：", file=sys.stderr)
    for m in missing:
        print(f"  - {m}", file=sys.stderr)
    print("  补齐后可获得转写内容；否则请改用平台字幕或人工整理。", file=sys.stderr)
