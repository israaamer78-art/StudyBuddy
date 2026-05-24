"""Extended library functions for flashcards, clozes, confidence, wrong-answer tracking,
study history, and exam-level cumulative quizzes.

These all read/write the same data/library.json that library.py manages."""
import uuid
from datetime import datetime
from library import (
    load_library, save_library, find_lecture, find_section, find_exam, _now
)
import spaced_repetition as sr


# ============================================================================
# Confidence rating per section
# ============================================================================

def set_section_confidence(lecture_id: str, section_index: int, rating: str) -> bool:
    """rating: 'low' | 'medium' | 'high'"""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    section["confidence"] = rating
    section["confidence_updated_at"] = _now()
    save_library(lib)
    return True


# ============================================================================
# Flashcards (per section, with spaced repetition state)
# ============================================================================

def set_section_flashcards(lecture_id: str, section_index: int, cards: list[dict]) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    enriched = []
    for c in cards:
        enriched.append({
            "id": str(uuid.uuid4()),
            "front": c["front"],
            "back": c["back"],
            "sr_state": sr.initial_state(),
        })
    section["flashcards"] = enriched
    save_library(lib)
    return True


def rate_flashcard(lecture_id: str, section_index: int, card_id: str, rating: int) -> bool:
    """Apply a SR rating (0-3) to a flashcard."""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    for card in section.get("flashcards", []):
        if card["id"] == card_id:
            card["sr_state"] = sr.update_state(card.get("sr_state", sr.initial_state()), rating)
            save_library(lib)
            return True
    return False


# ============================================================================
# Cloze deletions (per section, with spaced repetition state)
# ============================================================================

def set_section_clozes(lecture_id: str, section_index: int, clozes: list[dict]) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    enriched = []
    for c in clozes:
        enriched.append({
            "id": str(uuid.uuid4()),
            "text": c["text"],
            "answer": c["answer"],
            "sr_state": sr.initial_state(),
        })
    section["clozes"] = enriched
    save_library(lib)
    return True


def rate_cloze(lecture_id: str, section_index: int, cloze_id: str, rating: int) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    for cloze in section.get("clozes", []):
        if cloze["id"] == cloze_id:
            cloze["sr_state"] = sr.update_state(cloze.get("sr_state", sr.initial_state()), rating)
            save_library(lib)
            return True
    return False


# ============================================================================
# Highlights and margin notes (per section)
# ============================================================================

def set_section_reading(lecture_id: str, section_index: int, reading: str) -> bool:
    """Update just the reading text for a section (after regeneration)."""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    section["reading"] = reading
    save_library(lib)
    return True


def add_highlight(lecture_id: str, section_index: int, highlight: dict) -> dict | None:
    """Add a highlight. Returns the enriched highlight (with id)."""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return None
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return None
    entry = {
        "id": str(uuid.uuid4()),
        "text": highlight.get("text", ""),
        "color": highlight.get("color", "yellow"),
        "start": highlight.get("start", 0),
        "end": highlight.get("end", 0),
        "note": highlight.get("note", ""),
        "created_at": _now(),
    }
    section.setdefault("highlights", []).append(entry)
    save_library(lib)
    return entry


def update_highlight(lecture_id: str, section_index: int, highlight_id: str, updates: dict) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    for h in section.get("highlights", []):
        if h["id"] == highlight_id:
            # Only update specific fields
            for k in ("color", "note"):
                if k in updates:
                    h[k] = updates[k]
            save_library(lib)
            return True
    return False


def delete_highlight(lecture_id: str, section_index: int, highlight_id: str) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    before = len(section.get("highlights", []))
    section["highlights"] = [h for h in section.get("highlights", []) if h["id"] != highlight_id]
    if len(section["highlights"]) < before:
        save_library(lib)
        return True
    return False


def set_section_notes(lecture_id: str, section_index: int, notes_text: str) -> bool:
    """Set the free-form margin notes for a section."""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    section["margin_notes"] = notes_text
    section["margin_notes_updated_at"] = _now()
    save_library(lib)
    return True


# ============================================================================
# Wrong-answer tracking
#
# When a user gets an MCQ wrong, we add it to a review pool on the lecture.
# Each entry stores the question + SR state for review scheduling.
# ============================================================================

def record_wrong_answer(lecture_id: str, section_index: int | None, question: dict,
                        source: str = "section") -> bool:
    """source: 'section' | 'comprehensive' | 'exam'"""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    pool = lec.setdefault("wrong_answers", [])
    # Avoid exact duplicates by question text
    q_text = question.get("question", "")
    for entry in pool:
        if entry.get("question", {}).get("question") == q_text:
            # Reset SR state on a repeat miss
            entry["sr_state"] = sr.update_state(entry.get("sr_state", sr.initial_state()), 0)
            entry["miss_count"] = entry.get("miss_count", 1) + 1
            save_library(lib)
            return True
    pool.append({
        "id": str(uuid.uuid4()),
        "section_index": section_index,
        "source": source,
        "question": question,
        "miss_count": 1,
        "sr_state": sr.initial_state(),
        "first_missed_at": _now(),
    })
    save_library(lib)
    return True


def rate_wrong_answer(lecture_id: str, entry_id: str, rating: int) -> bool:
    """Apply SR rating when reviewing a previously-missed question."""
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    for entry in lec.get("wrong_answers", []):
        if entry["id"] == entry_id:
            entry["sr_state"] = sr.update_state(entry.get("sr_state", sr.initial_state()), rating)
            entry["last_reviewed_at"] = _now()
            save_library(lib)
            return True
    return False


# ============================================================================
# Exam-level cumulative quiz storage
# ============================================================================

def set_exam_cumulative_quiz(exam_id: str, questions: list[dict]) -> bool:
    lib = load_library()
    exam = find_exam(lib, exam_id)
    if not exam:
        return False
    exam["cumulative_quiz"] = questions
    save_library(lib)
    return True


def get_exam_cumulative_quiz(exam_id: str) -> list[dict] | None:
    lib = load_library()
    exam = find_exam(lib, exam_id)
    if not exam:
        return None
    return exam.get("cumulative_quiz")


# ============================================================================
# Study history (lightweight log of session activity)
# ============================================================================

def log_activity(lecture_id: str, kind: str, detail: dict | None = None) -> None:
    """kind: 'study_section' | 'quiz_section' | 'comprehensive' | 'review' | 'flashcards' | 'clozes' | ..."""
    lib = load_library()
    history = lib.setdefault("history", [])
    history.append({
        "ts": _now(),
        "lecture_id": lecture_id,
        "kind": kind,
        "detail": detail or {},
    })
    # Keep history capped at 1000 events
    if len(history) > 1000:
        lib["history"] = history[-1000:]
    save_library(lib)


def get_history(limit: int = 200) -> list[dict]:
    lib = load_library()
    return list(reversed(lib.get("history", [])))[:limit]


def get_enriched_history(limit: int = 200) -> list[dict]:
    """Return history with lecture/exam/section labels resolved for display."""
    lib = load_library()
    lecture_lookup = {}
    for exam in lib.get("exams", []):
        for lecture in exam.get("lectures", []):
            sections = {
                section.get("section_index"): {
                    "section_index": section.get("section_index"),
                    "section_title": section.get("title"),
                }
                for section in lecture.get("sections", [])
            }
            lecture_lookup[lecture.get("id")] = {
                "exam_id": exam.get("id"),
                "exam_name": exam.get("name"),
                "lecture_id": lecture.get("id"),
                "lecture_name": lecture.get("name"),
                "sections": sections,
            }

    enriched = []
    for event in get_history(limit):
        item = dict(event)
        detail = item.get("detail") or {}
        lecture = lecture_lookup.get(item.get("lecture_id"))
        if lecture:
            item["exam_name"] = lecture["exam_name"]
            item["lecture_name"] = lecture["lecture_name"]
            section_index = detail.get("section") or detail.get("section_index")
            if section_index in lecture["sections"]:
                item.update(lecture["sections"][section_index])
        enriched.append(item)
    return enriched


def study_streak() -> int:
    """Consecutive days with at least one activity."""
    history = load_library().get("history", [])
    if not history:
        return 0
    days = set()
    for h in history:
        ts = h.get("ts", "")
        if ts:
            days.add(ts[:10])
    sorted_days = sorted(days, reverse=True)
    today = datetime.utcnow().date().isoformat()
    if sorted_days[0] != today:
        # If today isn't in history, streak only counts if yesterday is
        from datetime import timedelta
        yesterday = (datetime.utcnow().date() - timedelta(days=1)).isoformat()
        if sorted_days[0] != yesterday:
            return 0
    streak = 1
    for i in range(1, len(sorted_days)):
        from datetime import timedelta
        prev = datetime.fromisoformat(sorted_days[i-1])
        cur = datetime.fromisoformat(sorted_days[i])
        if (prev - cur).days == 1:
            streak += 1
        else:
            break
    return streak


# ============================================================================
# Weak-spot analytics
# ============================================================================

def weak_spots(exam_id: str | None = None) -> dict:
    """Return aggregated weak-spot data.

    Returns: {
      "by_section": [{ lecture_id, lecture_name, section_index, section_title,
                       miss_count, confidence }],
      "by_lecture": [{ lecture_id, lecture_name, total_misses }],
    }
    """
    lib = load_library()
    by_section = []
    by_lecture = []

    for exam in lib["exams"]:
        if exam_id and exam["id"] != exam_id:
            continue
        for lec in exam["lectures"]:
            lec_total_misses = 0
            section_misses = {}
            for entry in lec.get("wrong_answers", []):
                si = entry.get("section_index")
                if si is not None:
                    section_misses[si] = section_misses.get(si, 0) + entry.get("miss_count", 1)
                lec_total_misses += entry.get("miss_count", 1)

            for section in lec["sections"]:
                si = section["section_index"]
                conf = section.get("confidence")
                misses = section_misses.get(si, 0)
                if misses > 0 or conf == "low":
                    by_section.append({
                        "lecture_id": lec["id"],
                        "lecture_name": lec["name"],
                        "section_index": si,
                        "section_title": section.get("title"),
                        "miss_count": misses,
                        "confidence": conf,
                    })
            if lec_total_misses > 0:
                by_lecture.append({
                    "lecture_id": lec["id"],
                    "lecture_name": lec["name"],
                    "total_misses": lec_total_misses,
                })

    by_section.sort(key=lambda x: -x["miss_count"])
    by_lecture.sort(key=lambda x: -x["total_misses"])
    return {"by_section": by_section, "by_lecture": by_lecture}


# ============================================================================
# Cram mode: pull everything that needs attention right now
# ============================================================================

def cram_items(exam_id: str | None = None) -> dict:
    """Return items prioritized for cramming: due wrong-answers, due flashcards,
    due clozes, plus low-confidence sections."""
    lib = load_library()
    due_wrong = []
    due_cards = []
    due_clozes = []
    low_confidence_sections = []

    for exam in lib["exams"]:
        if exam_id and exam["id"] != exam_id:
            continue
        for lec in exam["lectures"]:
            for entry in lec.get("wrong_answers", []):
                if sr.is_due(entry.get("sr_state", {})):
                    due_wrong.append({
                        "lecture_id": lec["id"],
                        "lecture_name": lec["name"],
                        "entry": entry,
                    })
            for section in lec["sections"]:
                if section.get("confidence") == "low":
                    low_confidence_sections.append({
                        "lecture_id": lec["id"],
                        "lecture_name": lec["name"],
                        "section_index": section["section_index"],
                        "section_title": section.get("title"),
                    })
                for card in section.get("flashcards", []) or []:
                    if sr.is_due(card.get("sr_state", {})):
                        due_cards.append({
                            "lecture_id": lec["id"],
                            "lecture_name": lec["name"],
                            "section_index": section["section_index"],
                            "card": card,
                        })
                for cloze in section.get("clozes", []) or []:
                    if sr.is_due(cloze.get("sr_state", {})):
                        due_clozes.append({
                            "lecture_id": lec["id"],
                            "lecture_name": lec["name"],
                            "section_index": section["section_index"],
                            "cloze": cloze,
                        })

    return {
        "due_wrong_answers": due_wrong,
        "due_flashcards": due_cards,
        "due_clozes": due_clozes,
        "low_confidence_sections": low_confidence_sections,
    }
