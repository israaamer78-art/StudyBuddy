"""Additional Flask routes for flashcards, clozes, confidence, wrong answers,
weak-spot dashboard, cram mode, history, exam-level quiz, and Anki export."""
from flask import Blueprint, jsonify, request, Response

import library
import library_ext as libx
import generator

ext_bp = Blueprint("ext", __name__)


# ============================================================================
# Confidence rating
# ============================================================================

@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/confidence")
def api_set_confidence(lecture_id, section_index):
    rating = (request.get_json() or {}).get("rating")
    if rating not in ("low", "medium", "high"):
        return jsonify({"error": "rating must be low/medium/high"}), 400
    if not libx.set_section_confidence(lecture_id, section_index, rating):
        return jsonify({"error": "Not found"}), 404
    libx.log_activity(lecture_id, "confidence", {"section": section_index, "rating": rating})
    return jsonify({"ok": True})


# ============================================================================
# Flashcards
# ============================================================================

def _section_for_gen(lecture_id, section_index):
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        return None
    _, lec = found
    return library.find_section(lec, section_index)


@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/flashcards")
def api_generate_flashcards(lecture_id, section_index):
    section = _section_for_gen(lecture_id, section_index)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    try:
        cards = generator.generate_flashcards(section["chunk"], "")
        libx.set_section_flashcards(lecture_id, section_index, cards)
        libx.log_activity(lecture_id, "generate_flashcards", {"section": section_index})
        # Return enriched cards
        lib = library.load_library()
        _, lec = library.find_lecture(lib, lecture_id)
        s = library.find_section(lec, section_index)
        return jsonify({"flashcards": s.get("flashcards", [])})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/flashcards/<card_id>/rate")
def api_rate_flashcard(lecture_id, section_index, card_id):
    rating = int((request.get_json() or {}).get("rating", 2))
    if not libx.rate_flashcard(lecture_id, section_index, card_id, rating):
        return jsonify({"error": "Not found"}), 404
    libx.log_activity(lecture_id, "rate_flashcard", {"card_id": card_id, "rating": rating})
    return jsonify({"ok": True})


# ============================================================================
# Cloze deletions
# ============================================================================

@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/clozes")
def api_generate_clozes(lecture_id, section_index):
    section = _section_for_gen(lecture_id, section_index)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    try:
        clozes = generator.generate_clozes(section["chunk"], "")
        libx.set_section_clozes(lecture_id, section_index, clozes)
        libx.log_activity(lecture_id, "generate_clozes", {"section": section_index})
        lib = library.load_library()
        _, lec = library.find_lecture(lib, lecture_id)
        s = library.find_section(lec, section_index)
        return jsonify({"clozes": s.get("clozes", [])})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/clozes/<cloze_id>/rate")
def api_rate_cloze(lecture_id, section_index, cloze_id):
    rating = int((request.get_json() or {}).get("rating", 2))
    if not libx.rate_cloze(lecture_id, section_index, cloze_id, rating):
        return jsonify({"error": "Not found"}), 404
    libx.log_activity(lecture_id, "rate_cloze", {"cloze_id": cloze_id, "rating": rating})
    return jsonify({"ok": True})


# ============================================================================
# Wrong answer tracking
# ============================================================================

@ext_bp.post("/api/lectures/<lecture_id>/wrong-answers")
def api_record_wrong(lecture_id):
    data = request.get_json() or {}
    section_index = data.get("section_index")
    question = data.get("question")
    source = data.get("source", "section")
    if not question:
        return jsonify({"error": "question required"}), 400
    if not libx.record_wrong_answer(lecture_id, section_index, question, source):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@ext_bp.post("/api/lectures/<lecture_id>/wrong-answers/<entry_id>/rate")
def api_rate_wrong(lecture_id, entry_id):
    rating = int((request.get_json() or {}).get("rating", 2))
    if not libx.rate_wrong_answer(lecture_id, entry_id, rating):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


# ============================================================================
# Weak-spot dashboard
# ============================================================================

@ext_bp.get("/api/weak-spots")
def api_weak_spots():
    exam_id = request.args.get("exam_id")
    return jsonify(libx.weak_spots(exam_id))


# ============================================================================
# Cram mode
# ============================================================================

@ext_bp.get("/api/cram")
def api_cram():
    exam_id = request.args.get("exam_id")
    return jsonify(libx.cram_items(exam_id))


# ============================================================================
# History & streak
# ============================================================================

@ext_bp.get("/api/history")
def api_history():
    limit = int(request.args.get("limit", 50))
    return jsonify({
        "history": libx.get_enriched_history(limit),
        "streak": libx.study_streak(),
    })


# ============================================================================
# Exam-level cumulative quiz
# ============================================================================

@ext_bp.post("/api/exams/<exam_id>/cumulative-quiz")
def api_generate_exam_quiz(exam_id):
    lib = library.load_library()
    exam = library.find_exam(lib, exam_id)
    if not exam:
        return jsonify({"error": "Exam not found"}), 404
    if not exam["lectures"]:
        return jsonify({"error": "Exam has no lectures yet"}), 400
    try:
        questions = generator.generate_exam_quiz(exam["lectures"])
        libx.set_exam_cumulative_quiz(exam_id, questions)
        return jsonify({"questions": questions})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@ext_bp.get("/api/exams/<exam_id>/cumulative-quiz")
def api_get_exam_quiz(exam_id):
    q = libx.get_exam_cumulative_quiz(exam_id)
    return jsonify({"questions": q or []})


# ============================================================================
# Anki export (.apkg via genanki, but fall back to .txt if not installed)
# ============================================================================

@ext_bp.get("/api/lectures/<lecture_id>/export/anki")
def api_export_anki(lecture_id):
    """Export flashcards + clozes as a tab-separated text file Anki can import.

    Format: front<TAB>back<TAB>tags (for basic cards)
            text<TAB>extra<TAB>tags (for cloze cards, where text contains {{c1::...}})
    """
    lib = library.load_library()
    found = library.find_lecture(lib, lecture_id)
    if not found:
        return jsonify({"error": "Lecture not found"}), 404
    exam, lec = found
    lines = ["#separator:tab", "#html:true", "#tags column:3"]
    for section in lec["sections"]:
        section_tag = f"{exam['name'].replace(' ', '_')}::{lec['name'].replace(' ', '_')}::Section_{section['section_index']}"
        for card in section.get("flashcards", []) or []:
            front = card["front"].replace("\t", " ").replace("\n", "<br>")
            back = card["back"].replace("\t", " ").replace("\n", "<br>")
            lines.append(f"{front}\t{back}\t{section_tag}::basic")
        for cloze in section.get("clozes", []) or []:
            # Convert {{answer}} markers to Anki's {{c1::answer}} syntax
            text = cloze["text"].replace("{{" + cloze["answer"] + "}}", f"{{{{c1::{cloze['answer']}}}}}")
            text = text.replace("\t", " ").replace("\n", "<br>")
            lines.append(f"{text}\t\t{section_tag}::cloze")
    body = "\n".join(lines)
    fname = f"{lec['name'].replace(' ', '_')}_anki.txt"
    return Response(
        body,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ============================================================================
# Section activity log helper for the main app
# ============================================================================

@ext_bp.post("/api/log")
def api_log():
    data = request.get_json() or {}
    libx.log_activity(
        data.get("lecture_id"),
        data.get("kind", "view"),
        data.get("detail"),
    )
    return jsonify({"ok": True})


# ============================================================================
# Regenerate reading (markdown-style)
# ============================================================================

@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/reading")
def api_regenerate_reading(lecture_id, section_index):
    section = _section_for_gen(lecture_id, section_index)
    if not section:
        return jsonify({"error": "Section not found"}), 404
    try:
        # Use new slides/transcript fields if present, fall back to chunk
        slides_content = section.get("slides_content", "")
        transcript_excerpt = section.get("transcript_excerpt", "")
        if slides_content or transcript_excerpt:
            new_reading = generator.regenerate_reading(
                slides_content=slides_content,
                transcript_excerpt=transcript_excerpt,
            )
        else:
            new_reading = generator.regenerate_reading(chunk=section.get("chunk", ""))
        libx.set_section_reading(lecture_id, section_index, new_reading)
        libx.log_activity(lecture_id, "regenerate_reading", {"section": section_index})
        return jsonify({"reading": new_reading})
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Highlights
# ============================================================================

@ext_bp.post("/api/lectures/<lecture_id>/sections/<int:section_index>/highlights")
def api_add_highlight(lecture_id, section_index):
    data = request.get_json() or {}
    entry = libx.add_highlight(lecture_id, section_index, data)
    if not entry:
        return jsonify({"error": "Section not found"}), 404
    return jsonify(entry)


@ext_bp.patch("/api/lectures/<lecture_id>/sections/<int:section_index>/highlights/<highlight_id>")
def api_update_highlight(lecture_id, section_index, highlight_id):
    data = request.get_json() or {}
    if not libx.update_highlight(lecture_id, section_index, highlight_id, data):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@ext_bp.delete("/api/lectures/<lecture_id>/sections/<int:section_index>/highlights/<highlight_id>")
def api_delete_highlight(lecture_id, section_index, highlight_id):
    if not libx.delete_highlight(lecture_id, section_index, highlight_id):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


# ============================================================================
# Margin notes
# ============================================================================

@ext_bp.put("/api/lectures/<lecture_id>/sections/<int:section_index>/notes")
def api_set_notes(lecture_id, section_index):
    text = (request.get_json() or {}).get("notes", "")
    if not libx.set_section_notes(lecture_id, section_index, text):
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})
