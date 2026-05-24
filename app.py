"""Flask app: library navigation + lecture upload + study UI with on-demand generation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
import tempfile
from pathlib import Path
from threading import Lock
import time
import uuid

from flask import Flask, render_template, jsonify, request, abort, Response, g

import cache_store
import library
import library_ext as libx
import ingest
import notes_parser
import generator
import model_config
from app_ext import ext_bp

import anthropic
from anthropic import Anthropic
import openai
from openai import OpenAI

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500 MB
app.register_blueprint(ext_bp)

UPLOAD_DIR = Path(tempfile.gettempdir()) / "studybuddy_uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, dict] = {}
JOBS_LOCK = Lock()


def _set_job(job_id: str, **updates) -> None:
    with JOBS_LOCK:
        job = JOBS.setdefault(job_id, {})
        job.update(updates)
        job["updated_at"] = datetime.utcnow().isoformat() + "Z"


def _get_job(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


@app.before_request
def apply_request_model():
    g.model_tokens = model_config.set_current_provider_model(
        request.headers.get("X-StudyBuddy-Provider"),
        request.headers.get("X-StudyBuddy-Model"),
    )
    provider = model_config.current_provider()
    key_header = "X-OpenAI-Api-Key" if provider == model_config.PROVIDER_OPENAI else "X-Anthropic-Api-Key"
    g.api_key_token = model_config.set_current_api_key(request.headers.get(key_header))


@app.after_request
def reset_request_model(response):
    tokens = getattr(g, "model_tokens", None)
    if tokens is not None:
        model_config.reset_current_provider_model(tokens)
    api_key_token = getattr(g, "api_key_token", None)
    if api_key_token is not None:
        model_config.reset_current_api_key(api_key_token)
    return response


# --- Pages ---

@app.route("/")
def index():
    return render_template("index.html")


# --- Library ---

@app.get("/api/library")
def api_library():
    lib = library.load_library()
    # Enrich with progress (don't ship full section bodies in the library tree)
    out_exams = []
    for exam in lib["exams"]:
        out_lecs = []
        for lec in exam["lectures"]:
            done, total = library.lecture_progress(lec)
            out_lecs.append({
                "id": lec["id"],
                "name": lec["name"],
                "created_at": lec.get("created_at"),
                "progress": {"done": done, "total": total},
            })
        out_exams.append({
            "id": exam["id"],
            "name": exam["name"],
            "created_at": exam.get("created_at"),
            "lectures": out_lecs,
        })
    return jsonify({"exams": out_exams})


@app.get("/api/project")
def api_export_project():
    """Export the complete local study library for browser backup/download."""
    lib = library.load_library()
    exported_at = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    body = {
        "app": "studybuddy",
        "format_version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "library": lib,
    }
    import json
    return Response(
        json.dumps(body, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="studybuddy-{exported_at}.studybuddy.json"'},
    )


@app.post("/api/project/import")
def api_import_project():
    """Restore a project file exported by /api/project."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Upload a valid StudyBuddy JSON project file"}), 400
    if data.get("app") == "studybuddy" and "library" in data:
        candidate = data["library"]
    else:
        # Accept a raw library.json as a convenience.
        candidate = data
    try:
        library.save_library(candidate)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "library": library.load_library()})


@app.get("/api/models")
def api_models():
    return jsonify({
        "default_provider": model_config.DEFAULT_PROVIDER,
        "default": model_config.DEFAULT_MODEL,
        "providers": [
            {
                "id": model_config.PROVIDER_ANTHROPIC,
                "label": "Anthropic",
                "default_model": model_config.DEFAULT_MODELS[model_config.PROVIDER_ANTHROPIC],
                "models": [
                    {"id": "claude-opus-4-7", "label": "Claude Opus 4.7", "hint": "best"},
                    {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "hint": "default, balanced"},
                    {"id": "claude-haiku-4-5", "label": "Claude Haiku 4.5", "hint": "fastest, cheapest"},
                ],
            },
            {
                "id": model_config.PROVIDER_OPENAI,
                "label": "OpenAI",
                "default_model": model_config.DEFAULT_MODELS[model_config.PROVIDER_OPENAI],
                "models": [
                    {"id": "gpt-5.5", "label": "GPT-5.5", "hint": "best"},
                    {"id": "gpt-5.4-mini", "label": "GPT-5.4 Mini", "hint": "default, balanced"},
                    {"id": "gpt-5.4-nano", "label": "GPT-5.4 Nano", "hint": "fastest, cheapest"},
                ],
            },
        ],
    })


@app.get("/api/settings")
def api_settings():
    return jsonify({
        "has_server_anthropic_key": bool(model_config.normalize_api_key(os.environ.get("ANTHROPIC_API_KEY"), model_config.PROVIDER_ANTHROPIC)),
        "has_server_openai_key": bool(model_config.normalize_api_key(os.environ.get("OPENAI_API_KEY"), model_config.PROVIDER_OPENAI)),
    })


def _anthropic_error_message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(exc)


def _openai_error_message(exc: Exception) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
    return str(exc)


def _is_output_limit_probe_error(message: str) -> bool:
    message = (message or "").lower()
    return "max_tokens" in message and "output limit" in message


def validate_anthropic_key(api_key: str, model: str | None = None) -> dict:
    """Validate key, selected model access, and billing with a tiny real request."""
    model = model_config.normalize_model(model)
    try:
        client = Anthropic(api_key=api_key)
        client.messages.create(
            model=model,
            max_tokens=1,
            messages=[{"role": "user", "content": "Reply with OK."}],
        )
        return {"ok": True, "status": "valid", "message": "Anthropic key validated."}
    except anthropic.AuthenticationError:
        return {"ok": False, "status": "invalid_key", "message": "Anthropic rejected this API key. Check that it was copied correctly."}
    except anthropic.PermissionDeniedError as exc:
        return {"ok": False, "status": "permission_denied", "message": _anthropic_error_message(exc) or "This key does not have permission to use the selected model."}
    except anthropic.BadRequestError as exc:
        msg = _anthropic_error_message(exc)
        low_credit_terms = ("credit", "balance", "fund", "billing", "insufficient")
        if any(term in msg.lower() for term in low_credit_terms):
            return {"ok": False, "status": "billing_error", "message": msg}
        return {"ok": False, "status": "request_error", "message": msg}
    except anthropic.RateLimitError as exc:
        return {"ok": False, "status": "rate_limited", "message": _anthropic_error_message(exc) or "This key is currently rate limited."}
    except anthropic.APIConnectionError as exc:
        return {"ok": False, "status": "network_error", "message": _anthropic_error_message(exc) or "Could not reach Anthropic. Check your internet connection."}
    except anthropic.APIStatusError as exc:
        return {"ok": False, "status": "provider_error", "message": _anthropic_error_message(exc) or f"Anthropic returned HTTP {exc.status_code}."}
    except Exception as exc:
        return {"ok": False, "status": "unknown_error", "message": str(exc)}


def validate_openai_key(api_key: str, model: str | None = None) -> dict:
    """Validate key, selected model access, and billing with a tiny real request."""
    _, model = model_config.normalize_provider_model(model_config.PROVIDER_OPENAI, model)
    try:
        client = OpenAI(api_key=api_key)
        client.chat.completions.create(
            model=model,
            max_completion_tokens=16,
            messages=[{"role": "user", "content": "Reply with only: OK"}],
        )
        return {"ok": True, "status": "valid", "message": "OpenAI key validated."}
    except openai.AuthenticationError:
        return {"ok": False, "status": "invalid_key", "message": "OpenAI rejected this API key. Check that it was copied correctly."}
    except openai.PermissionDeniedError as exc:
        return {"ok": False, "status": "permission_denied", "message": _openai_error_message(exc) or "This key does not have permission to use the selected model."}
    except openai.BadRequestError as exc:
        msg = _openai_error_message(exc)
        if _is_output_limit_probe_error(msg):
            return {"ok": True, "status": "valid", "message": "OpenAI key validated."}
        low_credit_terms = ("credit", "balance", "fund", "billing", "insufficient", "quota")
        if any(term in msg.lower() for term in low_credit_terms):
            return {"ok": False, "status": "billing_error", "message": msg}
        return {"ok": False, "status": "request_error", "message": msg}
    except openai.RateLimitError as exc:
        msg = _openai_error_message(exc)
        low_credit_terms = ("quota", "billing", "balance", "credit", "fund", "insufficient")
        status = "billing_error" if any(term in msg.lower() for term in low_credit_terms) else "rate_limited"
        return {"ok": False, "status": status, "message": msg or "This key is currently rate limited."}
    except openai.APIConnectionError as exc:
        return {"ok": False, "status": "network_error", "message": _openai_error_message(exc) or "Could not reach OpenAI. Check your internet connection."}
    except openai.APIStatusError as exc:
        return {"ok": False, "status": "provider_error", "message": _openai_error_message(exc) or f"OpenAI returned HTTP {exc.status_code}."}
    except Exception as exc:
        return {"ok": False, "status": "unknown_error", "message": str(exc)}


@app.post("/api/settings/validate-key")
def api_validate_key():
    data = request.get_json(silent=True) or {}
    provider, model = model_config.normalize_provider_model(
        data.get("provider") or request.headers.get("X-StudyBuddy-Provider"),
        data.get("model") or request.headers.get("X-StudyBuddy-Model"),
    )
    if provider == model_config.PROVIDER_OPENAI:
        api_key = model_config.normalize_api_key(
            data.get("openai_api_key")
            or request.headers.get("X-OpenAI-Api-Key")
            or os.environ.get("OPENAI_API_KEY"),
            provider,
        )
        provider_name = "OpenAI"
    else:
        api_key = model_config.normalize_api_key(
            data.get("anthropic_api_key")
            or request.headers.get("X-Anthropic-Api-Key")
            or os.environ.get("ANTHROPIC_API_KEY"),
            provider,
        )
        provider_name = "Anthropic"
    if not api_key:
        return jsonify({
            "ok": False,
            "status": "missing_key",
            "message": f"No {provider_name} API key is configured. Add one in AI Provider Settings.",
        }), 400
    if provider == model_config.PROVIDER_OPENAI:
        result = validate_openai_key(api_key, model)
    else:
        result = validate_anthropic_key(api_key, model)
    return jsonify(result), 200 if result.get("ok") else 400


@app.get("/api/jobs/<job_id>")
def api_get_job(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.post("/api/exams")
def api_create_exam():
    name = (request.get_json().get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    return jsonify(library.create_exam(name))


@app.patch("/api/exams/<exam_id>")
def api_rename_exam(exam_id):
    name = (request.get_json().get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    if not library.rename_exam(exam_id, name):
        return jsonify({"error": "Exam not found"}), 404
    return jsonify({"ok": True})


@app.delete("/api/exams/<exam_id>")
def api_delete_exam(exam_id):
    if not library.delete_exam(exam_id):
        return jsonify({"error": "Exam not found"}), 404
    return jsonify({"ok": True})


# --- Lectures ---

def _lecture_summary(lec: dict) -> dict:
    """Return a lecture with sections trimmed (no `chunk` in the response)."""
    sections_out = []
    for s in lec["sections"]:
        s_out = {k: v for k, v in s.items() if k != "chunk"}
        sections_out.append(s_out)
    return {
        "id": lec["id"],
        "name": lec["name"],
        "created_at": lec.get("created_at"),
        "source_metadata": lec.get("source_metadata") or {},
        "sections": sections_out,
        "has_comprehensive_quiz": bool(lec.get("comprehensive_quiz")),
    }


@app.get("/api/lectures/<lecture_id>")
def api_get_lecture(lecture_id):
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        abort(404)
    exam, lec = found
    return jsonify({
        "exam": {"id": exam["id"], "name": exam["name"]},
        "lecture": _lecture_summary(lec),
    })


@app.patch("/api/lectures/<lecture_id>")
def api_rename_lecture(lecture_id):
    name = (request.get_json().get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name required"}), 400
    if not library.rename_lecture(lecture_id, name):
        return jsonify({"error": "Lecture not found"}), 404
    return jsonify({"ok": True})


@app.delete("/api/lectures/<lecture_id>")
def api_delete_lecture(lecture_id):
    if not library.delete_lecture(lecture_id):
        return jsonify({"error": "Lecture not found"}), 404
    return jsonify({"ok": True})


@app.post("/api/lectures/<lecture_id>/sections/<int:section_index>/progress")
def api_section_progress(lecture_id, section_index):
    completed = bool(request.get_json().get("completed", True))
    if not library.mark_section_complete(lecture_id, section_index, completed):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


# --- On-demand question generation ---

def _get_section_for_gen(lecture_id: str, section_index: int):
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        return None, None
    _, lec = found
    section = library.find_section(lec, section_index)
    if not section:
        return None, None
    return lec, section


@app.post("/api/lectures/<lecture_id>/sections/<int:section_index>/questions")
def api_generate_questions(lecture_id, section_index):
    """Generate (or regenerate) questions for a section.

    Body: { "difficulty": "L1" | "NBME", "regenerate": bool }
    """
    data = request.get_json() or {}
    difficulty = data.get("difficulty", "L1")
    regenerate = bool(data.get("regenerate", False))

    lec, section = _get_section_for_gen(lecture_id, section_index)
    if not section:
        return jsonify({"error": "Section not found"}), 404

    try:
        existing = []
        if not regenerate:
            existing = (section.get("questions_l1") or []) + (section.get("questions_nbme") or [])

        new_questions = generator.generate_questions(
            section["chunk"], "", difficulty, existing=existing
        )
        library.set_section_questions(
            lecture_id, section_index, difficulty, new_questions, replace=regenerate
        )
        # Return the now-current set
        lib = library.load_library()
        _, lec = library.find_lecture(lib, lecture_id)
        section = library.find_section(lec, section_index)
        return jsonify({
            "questions_l1": section.get("questions_l1") or [],
            "questions_nbme": section.get("questions_nbme") or [],
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.post("/api/lectures/<lecture_id>/sections/<int:section_index>/recall")
def api_generate_recall(lecture_id, section_index):
    """Generate active recall prompts for a section."""
    lec, section = _get_section_for_gen(lecture_id, section_index)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    try:
        prompts = generator.generate_recall_prompts(section["chunk"], "")
        library.set_section_recall(lecture_id, section_index, prompts, replace=True)
        return jsonify({"recall_prompts": prompts})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.post("/api/lectures/<lecture_id>/comprehensive")
def api_generate_comprehensive(lecture_id):
    """Generate (or regenerate) the comprehensive end-of-lecture quiz."""
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        return jsonify({"error": "Lecture not found"}), 404
    _, lec = found
    try:
        questions = generator.generate_comprehensive_quiz(lec["sections"])
        library.set_comprehensive_quiz(lecture_id, questions)
        return jsonify({"questions": questions})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/lectures/<lecture_id>/comprehensive")
def api_get_comprehensive(lecture_id):
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        return jsonify({"error": "Lecture not found"}), 404
    _, lec = found
    return jsonify({"questions": lec.get("comprehensive_quiz") or []})


# --- Upload / generate full lecture ---

def _generate_lecture_job(
    job_id: str,
    *,
    exam_id: str,
    lecture_name: str,
    video_source: str,
    notes_text: str,
    video_path: str | None,
    notes_path: str | None,
    provider: str,
    model: str,
    api_key: str | None = None,
    source_metadata: dict | None = None,
) -> None:
    model_tokens = model_config.set_current_provider_model(provider, model)
    api_key_token = model_config.set_current_api_key(api_key)
    paths = [Path(p) for p in (video_path, notes_path) if p]
    started_at = time.monotonic()

    def record_progress(update: dict) -> None:
        elapsed = max(0, round(time.monotonic() - started_at))
        _set_job(job_id, elapsed_seconds=elapsed, **update)

    try:
        record_progress({"status": "running", "stage": "Extracting transcript"})
        video_ext = Path(video_path).suffix.lower() if video_path else ""
        if video_path:
            transcript = ingest.get_transcript(video_path, progress=record_progress)
        elif video_source:
            transcript = ingest.get_transcript(video_source) if ingest.is_youtube_url(video_source) else video_source
        else:
            raise ValueError("Provide a video file, YouTube URL, or pasted transcript")

        if notes_path:
            record_progress({"stage": "Loading notes", "section_title": Path(notes_path).name})
            notes = notes_parser.load_notes(notes_path, progress=record_progress)
        else:
            record_progress({"stage": "Loading pasted notes" if notes_text else "No notes provided"})
            notes = notes_text or ""

        if video_ext in {".pdf", ".pptx"} and not notes.strip():
            record_progress({"stage": f"Using {video_ext[1:].upper()} slides as notes"})
            notes = transcript
            transcript = ""

        record_progress({"stage": "Generating study sections", "current": 0, "total": None})
        sections = generator.build_sections(transcript, notes, progress=record_progress)
        if not sections:
            raise ValueError("No sections were generated")

        record_progress({"stage": "Saving lecture"})
        lecture = library.add_lecture(exam_id, lecture_name, sections, source_metadata=source_metadata)
        if not lecture:
            raise ValueError("Exam not found")

        _set_job(
            job_id,
            status="completed",
            stage="Complete",
            elapsed_seconds=max(0, round(time.monotonic() - started_at)),
            current=len(sections),
            total=len(sections),
            result={"exam_id": exam_id, "lecture": _lecture_summary(lecture)},
        )
    except Exception as e:
        import traceback; traceback.print_exc()
        _set_job(
            job_id,
            status="failed",
            stage="Failed",
            elapsed_seconds=max(0, round(time.monotonic() - started_at)),
            error=str(e),
        )
    finally:
        model_config.reset_current_provider_model(model_tokens)
        model_config.reset_current_api_key(api_key_token)
        for p in paths:
            if p.exists():
                try: p.unlink()
                except OSError: pass


@app.post("/api/lectures")
def api_add_lecture():
    """Create a new lecture from uploaded materials.

    Multipart form fields:
      exam_id OR exam_name
      lecture_name
      video_source (YouTube URL or pasted transcript)
      video_file (upload)
      notes_file (upload)
      notes_text (pasted)
    """
    exam_id = request.form.get("exam_id")
    exam_name = (request.form.get("exam_name") or "").strip()
    lecture_name = (request.form.get("lecture_name") or "").strip()
    video_source = (request.form.get("video_source") or "").strip()
    notes_text = (request.form.get("notes_text") or "").strip()
    selected_provider, selected_model = model_config.normalize_provider_model(
        request.form.get("provider") or request.headers.get("X-StudyBuddy-Provider"),
        request.form.get("model") or request.headers.get("X-StudyBuddy-Model"),
    )
    key_field = "openai_api_key" if selected_provider == model_config.PROVIDER_OPENAI else "anthropic_api_key"
    key_header = "X-OpenAI-Api-Key" if selected_provider == model_config.PROVIDER_OPENAI else "X-Anthropic-Api-Key"
    selected_api_key = model_config.normalize_api_key(request.form.get(key_field) or request.headers.get(key_header), selected_provider)

    if not lecture_name:
        return jsonify({"error": "lecture_name required"}), 400

    if exam_id:
        lib = library.load_library()
        exam = library.find_exam(lib, exam_id)
        if not exam:
            return jsonify({"error": "Exam not found"}), 404
    elif exam_name:
        exam = library.get_or_create_exam(exam_name)
    else:
        return jsonify({"error": "exam_id or exam_name required"}), 400

    video_file = request.files.get("video_file")
    notes_file = request.files.get("notes_file")
    video_path = None
    notes_path = None
    source_metadata = {
        "model": selected_model,
        "provider": selected_provider,
        "video_source_hash": cache_store.hash_text(video_source) if video_source else None,
        "notes_text_hash": cache_store.hash_text(notes_text) if notes_text else None,
    }

    try:
        if video_file and video_file.filename:
            video_path = UPLOAD_DIR / f"{uuid.uuid4()}-{Path(video_file.filename).name}"
            video_file.save(video_path)
            source_metadata["video_file_name"] = Path(video_file.filename).name
            source_metadata["video_file_hash"] = cache_store.hash_file(video_path)
        if notes_file and notes_file.filename:
            notes_path = UPLOAD_DIR / f"{uuid.uuid4()}-{Path(notes_file.filename).name}"
            notes_file.save(notes_path)
            source_metadata["notes_file_name"] = Path(notes_file.filename).name
            source_metadata["notes_file_hash"] = cache_store.hash_file(notes_path)

        job_id = str(uuid.uuid4())
        _set_job(
            job_id,
            id=job_id,
            status="queued",
            stage="Queued",
            created_at=datetime.utcnow().isoformat() + "Z",
            provider=selected_provider,
            model=selected_model,
        )
        JOB_EXECUTOR.submit(
            _generate_lecture_job,
            job_id,
            exam_id=exam["id"],
            lecture_name=lecture_name,
            video_source=video_source,
            notes_text=notes_text,
            video_path=str(video_path) if video_path else None,
            notes_path=str(notes_path) if notes_path else None,
            provider=selected_provider,
            model=selected_model,
            api_key=selected_api_key,
            source_metadata={k: v for k, v in source_metadata.items() if v},
        )
        return jsonify({"job_id": job_id, "status": "queued"}), 202

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("\n🌱 StudyBuddy running at http://127.0.0.1:5000\n")
    app.run(debug=False, port=5000)
