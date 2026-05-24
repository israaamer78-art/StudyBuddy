"""Spaced repetition using a simplified SM-2 algorithm.

Each item (a flashcard, missed question, or cloze) carries:
- ease_factor: float, starts at 2.5, decreases with bad recalls
- interval: int (days until next review)
- repetitions: int (consecutive correct recalls)
- due: ISO date string for next review
- last_reviewed: ISO date string

Quality of recall (rating):
  0 = "Again" (wrong / total blank)
  1 = "Hard" (got it but struggled)
  2 = "Good" (got it)
  3 = "Easy" (instant)
"""
from datetime import datetime, timedelta


def _today_iso() -> str:
    return datetime.utcnow().date().isoformat()


def _add_days(days: int) -> str:
    return (datetime.utcnow().date() + timedelta(days=days)).isoformat()


def initial_state() -> dict:
    return {
        "ease_factor": 2.5,
        "interval": 0,
        "repetitions": 0,
        "due": _today_iso(),
        "last_reviewed": None,
    }


def update_state(state: dict, rating: int) -> dict:
    """Apply SM-2 update based on rating (0-3)."""
    ef = state.get("ease_factor", 2.5)
    interval = state.get("interval", 0)
    reps = state.get("repetitions", 0)

    if rating == 0:  # Again
        reps = 0
        interval = 0  # review again today
        ef = max(1.3, ef - 0.20)
    else:
        if reps == 0:
            interval = 1
        elif reps == 1:
            interval = 3 if rating >= 2 else 1
        else:
            interval = max(1, round(interval * ef))
        reps += 1

        # Adjust ease based on quality
        if rating == 1:  # Hard
            ef = max(1.3, ef - 0.15)
            interval = max(1, round(interval * 0.7))
        elif rating == 2:  # Good
            pass
        elif rating == 3:  # Easy
            ef += 0.15
            interval = round(interval * 1.3)

    return {
        "ease_factor": round(ef, 2),
        "interval": interval,
        "repetitions": reps,
        "due": _add_days(interval),
        "last_reviewed": datetime.utcnow().isoformat() + "Z",
    }


def is_due(state: dict) -> bool:
    """Is this item due for review?"""
    due = state.get("due")
    if not due:
        return True
    return due <= _today_iso()
