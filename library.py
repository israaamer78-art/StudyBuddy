"""Library storage: exams -> lectures -> sections + comprehensive quiz."""
import json
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
LIBRARY_FILE = DATA_DIR / "library.json"
_lock = Lock()


def _empty_library() -> dict:
    return {"exams": [], "version": 2}


def validate_library(lib: dict) -> dict:
    """Validate an imported library shape before replacing local data."""
    if not isinstance(lib, dict):
        raise ValueError("Project file must contain a JSON object")
    if not isinstance(lib.get("exams"), list):
        raise ValueError("Project file is missing an exams list")
    version = lib.get("version", 2)
    if not isinstance(version, int):
        raise ValueError("Project version must be a number")
    return {"version": version, "exams": lib["exams"], **{k: v for k, v in lib.items() if k not in ("version", "exams")}}


def load_library() -> dict:
    if not LIBRARY_FILE.exists():
        return _empty_library()
    with open(LIBRARY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_library(lib: dict) -> None:
    lib = validate_library(lib)
    with _lock:
        tmp = LIBRARY_FILE.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(lib, f, indent=2)
        tmp.replace(LIBRARY_FILE)


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


# --- Exams ---

def create_exam(name: str) -> dict:
    lib = load_library()
    exam = {"id": str(uuid.uuid4()), "name": name, "created_at": _now(), "lectures": []}
    lib["exams"].append(exam)
    save_library(lib)
    return exam


def find_exam(lib: dict, exam_id: str) -> dict | None:
    return next((e for e in lib["exams"] if e["id"] == exam_id), None)


def find_exam_by_name(name: str) -> dict | None:
    lib = load_library()
    for e in lib["exams"]:
        if e["name"].lower() == name.lower():
            return e
    return None


def get_or_create_exam(name: str) -> dict:
    return find_exam_by_name(name) or create_exam(name)


def delete_exam(exam_id: str) -> bool:
    lib = load_library()
    before = len(lib["exams"])
    lib["exams"] = [e for e in lib["exams"] if e["id"] != exam_id]
    save_library(lib)
    return len(lib["exams"]) < before


def rename_exam(exam_id: str, new_name: str) -> bool:
    lib = load_library()
    exam = find_exam(lib, exam_id)
    if not exam:
        return False
    exam["name"] = new_name
    save_library(lib)
    return True


# --- Lectures ---

def add_lecture(exam_id: str, name: str, sections: list[dict], source_metadata: dict | None = None) -> dict | None:
    lib = load_library()
    exam = find_exam(lib, exam_id)
    if not exam:
        return None
    lecture = {
        "id": str(uuid.uuid4()),
        "name": name,
        "created_at": _now(),
        "source_metadata": source_metadata or {},
        "sections": sections,
        "comprehensive_quiz": None,  # generated on demand
    }
    exam["lectures"].append(lecture)
    save_library(lib)
    return lecture


def find_lecture(lib: dict, lecture_id: str) -> tuple[dict, dict] | None:
    for exam in lib["exams"]:
        for lec in exam["lectures"]:
            if lec["id"] == lecture_id:
                return exam, lec
    return None


def delete_lecture(lecture_id: str) -> bool:
    lib = load_library()
    for exam in lib["exams"]:
        before = len(exam["lectures"])
        exam["lectures"] = [l for l in exam["lectures"] if l["id"] != lecture_id]
        if len(exam["lectures"]) < before:
            save_library(lib)
            return True
    return False


def rename_lecture(lecture_id: str, new_name: str) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    lec["name"] = new_name
    save_library(lib)
    return True


# --- Section operations ---

def find_section(lecture: dict, section_index: int) -> dict | None:
    return next((s for s in lecture["sections"] if s["section_index"] == section_index), None)


def update_section(lecture_id: str, section_index: int, updates: dict) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    section.update(updates)
    save_library(lib)
    return True


def mark_section_complete(lecture_id: str, section_index: int, completed: bool = True) -> bool:
    return update_section(lecture_id, section_index, {"completed": completed})


def set_section_questions(lecture_id: str, section_index: int, difficulty: str,
                          questions: list[dict], replace: bool = False) -> bool:
    """Add or replace questions for a section.

    difficulty: 'L1' or 'NBME'
    replace: if True, replace existing; if False, append to existing.
    """
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    key = "questions_l1" if difficulty == "L1" else "questions_nbme"
    if replace:
        section[key] = questions
    else:
        section[key] = (section.get(key) or []) + questions
    save_library(lib)
    return True


def set_section_recall(lecture_id: str, section_index: int, prompts: list[dict],
                       replace: bool = True) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    section = find_section(lec, section_index)
    if not section:
        return False
    if replace:
        section["recall_prompts"] = prompts
    else:
        section["recall_prompts"] = (section.get("recall_prompts") or []) + prompts
    save_library(lib)
    return True


# --- Comprehensive quiz ---

def set_comprehensive_quiz(lecture_id: str, questions: list[dict]) -> bool:
    lib = load_library()
    found = find_lecture(lib, lecture_id)
    if not found:
        return False
    _, lec = found
    lec["comprehensive_quiz"] = questions
    save_library(lib)
    return True


# --- Progress summary ---

def lecture_progress(lecture: dict) -> tuple[int, int]:
    total = len(lecture["sections"])
    done = sum(1 for s in lecture["sections"] if s.get("completed"))
    return done, total
