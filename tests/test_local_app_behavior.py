import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import library
import app as app_module
from app import app


def sample_section():
    return {
        "section_index": 1,
        "title": "Pelvis",
        "reading": "Reading",
        "key_terms": [],
        "matching": [],
        "diagram": None,
        "chunk": "=== SLIDES ===\nPelvis\n\n=== TRANSCRIPT ===\nTranscript",
        "slides_content": "Pelvis",
        "transcript_excerpt": "Transcript",
        "completed": False,
        "questions_l1": [],
        "questions_nbme": [],
        "recall_prompts": [],
    }


class LocalAppBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_library_file = library.LIBRARY_FILE
        library.LIBRARY_FILE = Path(self.tmp.name) / "library.json"
        app.config.update(TESTING=True)
        app_module.JOBS.clear()
        self.client = app.test_client()

    def tearDown(self):
        library.LIBRARY_FILE = self.old_library_file
        self.tmp.cleanup()

    def create_lecture(self):
        exam = library.create_exam("Exam 1")
        lecture = library.add_lecture(
            exam["id"],
            "Lecture 1",
            [sample_section()],
            source_metadata={"model": "claude-sonnet-4-6", "notes_file_hash": "abc"},
        )
        return exam, lecture

    def test_library_file_is_updated_by_local_operations(self):
        exam, lecture = self.create_lecture()

        self.assertTrue(library.LIBRARY_FILE.exists())
        saved = json.loads(library.LIBRARY_FILE.read_text(encoding="utf-8"))
        self.assertEqual(saved["exams"][0]["id"], exam["id"])
        self.assertEqual(saved["exams"][0]["lectures"][0]["id"], lecture["id"])
        self.assertEqual(saved["exams"][0]["lectures"][0]["source_metadata"]["notes_file_hash"], "abc")

    def test_library_and_lecture_routes_trim_private_chunk_but_keep_metadata(self):
        exam, lecture = self.create_lecture()

        library_response = self.client.get("/api/library")
        self.assertEqual(library_response.status_code, 200)
        self.assertEqual(library_response.get_json()["exams"][0]["lectures"][0]["progress"], {"done": 0, "total": 1})

        lecture_response = self.client.get(f"/api/lectures/{lecture['id']}")
        self.assertEqual(lecture_response.status_code, 200)
        body = lecture_response.get_json()
        self.assertEqual(body["exam"]["id"], exam["id"])
        self.assertEqual(body["lecture"]["source_metadata"]["notes_file_hash"], "abc")
        self.assertNotIn("chunk", body["lecture"]["sections"][0])

    def test_project_export_import_round_trip_and_invalid_import(self):
        self.create_lecture()

        exported = self.client.get("/api/project")
        self.assertEqual(exported.status_code, 200)
        project = exported.get_json()
        self.assertEqual(project["app"], "studybuddy")
        self.assertEqual(len(project["library"]["exams"]), 1)

        library.save_library({"version": 2, "exams": []})
        imported = self.client.post("/api/project/import", json=project)
        self.assertEqual(imported.status_code, 200)
        self.assertEqual(len(library.load_library()["exams"]), 1)

        invalid = self.client.post("/api/project/import", json={"version": 2})
        self.assertEqual(invalid.status_code, 400)

    def test_section_progress_confidence_highlights_notes_and_wrong_answers_persist(self):
        _, lecture = self.create_lecture()
        lecture_id = lecture["id"]

        self.assertEqual(
            self.client.post(f"/api/lectures/{lecture_id}/sections/1/progress", json={"completed": True}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(f"/api/lectures/{lecture_id}/sections/1/confidence", json={"rating": "low"}).status_code,
            200,
        )
        highlight = self.client.post(
            f"/api/lectures/{lecture_id}/sections/1/highlights",
            json={"text": "Pelvis", "color": "yellow"},
        )
        self.assertEqual(highlight.status_code, 200)
        self.assertEqual(
            self.client.put(f"/api/lectures/{lecture_id}/sections/1/notes", json={"notes": "Margin note"}).status_code,
            200,
        )
        question = {"question": "Q?", "choices": ["A", "B", "C", "D"], "correct_index": 0}
        self.assertEqual(
            self.client.post(f"/api/lectures/{lecture_id}/wrong-answers", json={"section_index": 1, "question": question}).status_code,
            200,
        )

        section = library.load_library()["exams"][0]["lectures"][0]["sections"][0]
        self.assertTrue(section["completed"])
        self.assertEqual(section["confidence"], "low")
        self.assertEqual(section["highlights"][0]["text"], "Pelvis")
        self.assertEqual(section["margin_notes"], "Margin note")
        self.assertEqual(library.load_library()["exams"][0]["lectures"][0]["wrong_answers"][0]["question"]["question"], "Q?")

    def test_generation_routes_save_mocked_outputs_without_calling_claude(self):
        _, lecture = self.create_lecture()
        lecture_id = lecture["id"]

        with patch("generator.generate_questions", return_value=[{
            "question": "Q?",
            "choices": ["A", "B", "C", "D"],
            "correct_index": 1,
            "explanation": "Because",
            "difficulty": "L1",
        }]):
            response = self.client.post(f"/api/lectures/{lecture_id}/sections/1/questions", json={"difficulty": "L1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["questions_l1"][0]["question"], "Q?")

        with patch("generator.generate_recall_prompts", return_value=[{"prompt": "Explain", "model_answer": "Answer"}]):
            response = self.client.post(f"/api/lectures/{lecture_id}/sections/1/recall")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["recall_prompts"][0]["prompt"], "Explain")

        with patch("generator.generate_comprehensive_quiz", return_value=[{"question": "Comprehensive?"}]):
            response = self.client.post(f"/api/lectures/{lecture_id}/comprehensive")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f"/api/lectures/{lecture_id}/comprehensive").get_json()["questions"][0]["question"], "Comprehensive?")

    def test_slide_deck_lecture_source_is_used_as_slide_notes(self):
        exam = library.create_exam("Exam 1")
        deck_path = Path(self.tmp.name) / "lecture.pdf"
        deck_text = "--- Slide 1 ---\nPelvis overview"
        deck_path.write_bytes(b"pdf")

        with (
            patch("ingest.get_transcript", return_value=deck_text) as get_transcript,
            patch("generator.build_sections", return_value=[sample_section()]) as build_sections,
        ):
            app_module._generate_lecture_job(
                "job-pdf",
                exam_id=exam["id"],
                lecture_name="PDF Lecture",
                video_source="",
                notes_text="",
                video_path=str(deck_path),
                notes_path=None,
                provider="anthropic",
                model="claude-sonnet-4-6",
                api_key="sk-ant-test",
                source_metadata={"video_file_name": "lecture.pdf"},
            )

        self.assertEqual(get_transcript.call_args.args[0], str(deck_path))
        self.assertIn("progress", get_transcript.call_args.kwargs)
        build_sections.assert_called_once()
        transcript_arg, notes_arg = build_sections.call_args.args[:2]
        self.assertEqual(transcript_arg, "")
        self.assertEqual(notes_arg, deck_text)
        self.assertEqual(app_module.JOBS["job-pdf"]["status"], "completed")

    def test_flashcards_clozes_history_and_anki_export_use_local_data(self):
        _, lecture = self.create_lecture()
        lecture_id = lecture["id"]

        with patch("generator.generate_flashcards", return_value=[{"front": "Front", "back": "Back"}]):
            response = self.client.post(f"/api/lectures/{lecture_id}/sections/1/flashcards")
        self.assertEqual(response.status_code, 200)
        card = response.get_json()["flashcards"][0]
        self.assertEqual(card["front"], "Front")

        with patch("generator.generate_clozes", return_value=[{"text": "The {{pelvis}}", "answer": "pelvis"}]):
            response = self.client.post(f"/api/lectures/{lecture_id}/sections/1/clozes")
        self.assertEqual(response.status_code, 200)
        cloze = response.get_json()["clozes"][0]
        self.assertEqual(cloze["answer"], "pelvis")

        self.assertEqual(
            self.client.post(f"/api/lectures/{lecture_id}/sections/1/flashcards/{card['id']}/rate", json={"rating": 2}).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(f"/api/lectures/{lecture_id}/sections/1/clozes/{cloze['id']}/rate", json={"rating": 2}).status_code,
            200,
        )

        history = self.client.get("/api/history?limit=10").get_json()
        self.assertGreaterEqual(len(history["history"]), 2)
        anki = self.client.get(f"/api/lectures/{lecture_id}/export/anki")
        self.assertEqual(anki.status_code, 200)
        self.assertIn("Front\tBack", anki.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
