"""Extract transcripts from YouTube URLs, local files, or plain text."""
import os
import re
from pathlib import Path

import cache_store
from model_config import current_model

CACHE_DIR = cache_store.CACHE_DIR
TRANSCRIPT_CACHE_VERSION = 2


def is_youtube_url(s: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)", s))


def get_youtube_transcript(url: str) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError(f"Couldn't extract video ID from URL: {url}")
    video_id = m.group(1)
    transcript = YouTubeTranscriptApi.get_transcript(video_id)
    return " ".join(seg["text"] for seg in transcript)


def transcribe_file_with_whisper(path: str) -> str:
    from openai import OpenAI
    client = OpenAI()
    size_mb = os.path.getsize(path) / (1024 * 1024)
    if size_mb > 24:
        print(f"⚠️  File is {size_mb:.1f}MB (Whisper limit ~25MB). Attempting anyway...")
        print("    If it fails, compress with: ffmpeg -i in.mp4 -vn -ac 1 -ar 16000 -b:a 64k out.mp3")
    with open(path, "rb") as f:
        result = client.audio.transcriptions.create(
            model="whisper-1", file=f, response_format="text"
        )
    return result if isinstance(result, str) else result.text


def load_text_file(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    text = re.sub(r"\d{2}:\d{2}:\d{2}[.,]\d{3} --> \d{2}:\d{2}:\d{2}[.,]\d{3}", "", text)
    text = re.sub(r"^\d+\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"WEBVTT.*?\n", "", text)
    return re.sub(r"\n+", " ", text).strip()


def get_transcript(source: str, progress=None) -> str:
    if is_youtube_url(source):
        print("📺 Fetching YouTube transcript...")
        key = cache_store.make_key("transcript_youtube", {
            "version": TRANSCRIPT_CACHE_VERSION,
            "url_hash": cache_store.hash_text(source),
        })
        cached = cache_store.get(CACHE_DIR, "transcript_youtube", key)
        if cached is not None:
            return cached
        transcript = get_youtube_transcript(source)
        cache_store.set(CACHE_DIR, "transcript_youtube", key, transcript)
        return transcript
    p = Path(source)
    if not p.exists():
        raise FileNotFoundError(f"Source not found: {source}")
    ext = p.suffix.lower()
    key = cache_store.make_key("transcript_file", {
        "version": TRANSCRIPT_CACHE_VERSION,
        "file_hash": cache_store.hash_file(p),
        "suffix": ext,
        "model": current_model() if ext in {".pdf", ".pptx"} else None,
        "vision": ext in {".pdf", ".pptx"},
    })
    cached = cache_store.get(CACHE_DIR, "transcript_file", key)
    if cached is not None:
        return cached
    if ext in {".mp3", ".mp4", ".m4a", ".wav", ".webm", ".mpeg", ".mpga"}:
        print(f"🎙️  Transcribing {p.name} via Whisper API...")
        transcript = transcribe_file_with_whisper(str(p))
    elif ext in {".txt", ".vtt", ".srt", ".md"}:
        print(f"📄 Loading transcript from {p.name}...")
        transcript = load_text_file(str(p))
    elif ext == ".pdf":
        print(f"📄 Extracting lecture source PDF from {p.name} via vision...")
        import notes_parser
        transcript = notes_parser.parse_pdf(str(p), use_vision=True, progress=progress)
    elif ext == ".pptx":
        print(f"📊 Extracting lecture source text from {p.name}...")
        import notes_parser
        transcript = notes_parser.parse_pptx(str(p), progress=progress)
    else:
        raise ValueError(f"Unsupported file type: {ext}")
    cache_store.set(CACHE_DIR, "transcript_file", key, transcript)
    return transcript
