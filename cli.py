#!/usr/bin/env python3
"""StudyBuddy CLI — add lectures from the command line.

Examples:
  python cli.py add --exam "Exam 1" --lecture "Cranial Nerves" \\
      --video lecture1.mp4 --notes notes.pdf

  python cli.py add --exam "Exam 1" --lecture "Pharyngeal Arches" \\
      --video "https://youtube.com/watch?v=..." --notes-text "$(cat notes.txt)"

  python cli.py list

  python cli.py serve     # start the web UI
"""
import argparse
import sys
from pathlib import Path

import library
import ingest
import notes_parser
import generator


def cmd_add(args):
    exam = library.get_or_create_exam(args.exam)
    print(f"📂 Exam: {exam['name']}")

    if args.video:
        transcript = ingest.get_transcript(args.video)
    elif args.transcript_text:
        transcript = args.transcript_text
    elif args.transcript_file:
        transcript = Path(args.transcript_file).read_text(encoding="utf-8")
    else:
        print("ERROR: need --video, --transcript-file, or --transcript-text", file=sys.stderr)
        sys.exit(1)

    notes = ""
    if args.notes:
        notes = notes_parser.load_notes(args.notes)
    elif args.notes_text:
        notes = args.notes_text

    sections = generator.build_sections(transcript, notes)
    if not sections:
        print("❌ No sections generated", file=sys.stderr)
        sys.exit(1)

    lecture = library.add_lecture(exam["id"], args.lecture, sections)
    print(f"✅ Lecture '{lecture['name']}' added with {len(sections)} sections.")
    print(f"   Run `python cli.py serve` to view in browser.")


def cmd_list(args):
    lib = library.load_library()
    if not lib["exams"]:
        print("(no exams yet)")
        return
    for exam in lib["exams"]:
        print(f"\n📂 {exam['name']}")
        if not exam["lectures"]:
            print("   (no lectures)")
            continue
        for lec in exam["lectures"]:
            done, total = library.lecture_progress(lec)
            print(f"   • {lec['name']}  [{done}/{total} sections complete]")


def cmd_serve(args):
    from app import app
    print(f"\n🌱 StudyBuddy running at http://127.0.0.1:{args.port}\n")
    app.run(debug=False, port=args.port)


def main():
    p = argparse.ArgumentParser(description="StudyBuddy CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("add", help="Add a new lecture")
    pa.add_argument("--exam", required=True, help="Exam name (created if missing)")
    pa.add_argument("--lecture", required=True, help="Lecture name")
    pa.add_argument("--video", help="YouTube URL or path to video/audio/transcript file")
    pa.add_argument("--transcript-file", help="Path to a transcript .txt file")
    pa.add_argument("--transcript-text", help="Pasted transcript text")
    pa.add_argument("--notes", help="Path to notes file (PDF/DOCX/TXT)")
    pa.add_argument("--notes-text", help="Pasted notes text")
    pa.set_defaults(func=cmd_add)

    pl = sub.add_parser("list", help="List exams and lectures")
    pl.set_defaults(func=cmd_list)

    ps = sub.add_parser("serve", help="Start the web UI")
    ps.add_argument("--port", type=int, default=5000)
    ps.set_defaults(func=cmd_serve)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
