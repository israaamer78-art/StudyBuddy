# StudyBuddy 🌱

A personalized medical school study tool. Upload your lecture (video, audio, or transcript) and your notes, and it builds a complete study guide tailored to *that specific lecture*: reading passages with markdown formatting, key terms, matching, MCQs (Level 1 + NBME-style), active recall, flashcards, cloze deletions, diagrams, highlights, margin notes, and a comprehensive end-of-lecture quiz.

Everything is organized into **Exams → Lectures → Sections**, with progress tracking, confidence ratings, spaced repetition for missed questions, and a weak-spot dashboard.

**Core principle:** content is generated **strictly from your supplied materials** — no outside medical knowledge is injected. The AI is instructed to refuse to invent facts.

---

## 👋 New here? Start with the setup guide

**If you're setting this up for the first time, read [SETUP.md](SETUP.md).** It walks you through everything step-by-step for Mac or Windows, no coding knowledge required.

The rest of this README is the reference manual — what features exist, how they work, troubleshooting.

---

## What it does

### Per-section study experience

Each lecture is broken into chronological sections. For each section you get six tabs:

- **Reading** — markdown-formatted notes (headers, bold key terms, bullets, prose). You can:
  - Highlight in 4 colors (yellow, green, pink, blue)
  - Take margin notes on a side panel (autosaves)
  - Regenerate the reading if you don't like the format
- **Matching** — pair terms with their definitions
- **Quiz** — multiple choice. Toggle between Level 1 (recall) and NBME (clinical vignettes). All shown at once with reveal-on-click. Wrong answers go into a spaced-repetition review pool.
- **Active Recall** — free-response prompts. Write your answer, then reveal the model answer.
- **Flashcards** — atomic facts with SR scheduling
- **Clozes** — fill-in-the-blank cards

Each section has a confidence rating (low/medium/high) and a "mark complete" toggle.

### Lecture and exam features

- **Comprehensive quiz** — covers an entire lecture, chronological, mixed difficulty, restartable
- **Cumulative exam quiz** — covers all lectures in an exam
- **Diagrams** — Mermaid for pathways/flows, SVG for anatomy when appropriate
- **Weak-spot dashboard** — sections with missed questions or low confidence
- **Cram mode** — what's due right now via spaced repetition
- **Study history & streak** — your activity log
- **Anki export** — flashcards and clozes as a tab-separated file Anki can import

### Strict-source generation

Every prompt sent to Claude includes:

> 1. Use ONLY information explicitly present in the lecture chunk and notes.
> 2. Do NOT add facts from your general medical knowledge.
> 3. Do NOT skip anything substantive from the lecture.
> 4. If unsure whether a fact comes from the materials, leave it out.

Not bulletproof — LLMs can drift — but strongly biases generation toward your source material. If you spot something off, regenerate that piece.

---

## How content stays "strictly from your materials"

Every prompt the app sends to Claude includes the strict source rules. This isn't bulletproof — LLMs can drift — but it strongly biases generation toward your source material. If you spot something that wasn't in your lecture, regenerate that section's content.

---

## Cost estimate

Roughly **$3-5 per lecture** if you use every feature. See SETUP.md for the full breakdown. Set spending caps in the Anthropic console before you start.

---

## Adding lectures

### From the web UI

1. Create an exam in the sidebar
2. Click **+ New Lecture**
3. Provide a YouTube URL, paste a transcript, or upload a video file
4. Add your notes (PDF/DOCX/TXT upload or paste)
5. Click **Generate study guide**

### From the command line

```bash
python cli.py add \
    --exam "Exam 1 — Head & Neck" \
    --lecture "Cranial Nerves" \
    --video lecture1.mp4 \
    --notes notes.pdf
```

Or with a YouTube URL:

```bash
python cli.py add \
    --exam "Exam 1" \
    --lecture "Pharyngeal Arches" \
    --video "https://youtube.com/watch?v=..." \
    --notes notes.pdf
```

---

## File structure

```
studybuddy/
├── SETUP.md                # Friendly setup guide for newcomers
├── README.md               # This file
├── LICENSE
├── .gitignore
├── requirements.txt
├── cli.py                  # Command-line entry point
├── app.py                  # Flask app
├── app_ext.py              # Extended Flask routes
├── ingest.py               # Transcript extraction (YouTube/Whisper/text)
├── notes_parser.py         # PDF/DOCX/TXT parsing
├── generator.py            # Claude prompts and content generation
├── library.py              # Core data storage
├── library_ext.py          # Flashcards, SR, highlights, notes
├── spaced_repetition.py    # SM-2 algorithm
├── templates/
│   └── index.html
├── static/
│   ├── style.css
│   └── app.js
└── data/
    └── library.json        # YOUR personal library (auto-created, not tracked in git)
```

All your study data is in `data/library.json`. **Back this file up** — it has all your highlights, notes, progress, and study history. It's gitignored so it won't be uploaded if you push to GitHub.

---

## Tests

Run the local test suite without making Claude API calls:

```bash
venv/bin/python -m unittest discover -s tests
```

These tests use temporary library files and mocked AI outputs, so they should not spend API credits.

---

## Troubleshooting

See SETUP.md for setup-specific issues. For runtime issues:

**Section generation fails partway through** — usually a JSON parse issue from the AI. The other sections continue. Check console output.

**Diagram doesn't render** — Mermaid syntax errors fail silently. Regenerating the section usually fixes it.

**Lost work / accidental delete** — `data/library.json` is the source of truth. Keep backups before risky operations.

**Whisper API "file too large"** — files must be under 25MB. Compress with:
```bash
ffmpeg -i input.mp4 -vn -ac 1 -ar 16000 -b:a 64k output.mp3
```

---

## Contributing

This is meant to be customizable for personal use. Fork it, modify it for your specific needs. If you make improvements that others would benefit from, PRs welcome.

---

## License & responsibility

MIT licensed. See LICENSE.

This is a personal study tool. It is not a substitute for engaging with your lectures, attending class, or using proven resources like Anki/UWorld. The AI can make mistakes — always cross-check important facts against your primary sources.

**Don't share generated content publicly.** The underlying lecture material isn't yours to redistribute.

**Check your school's AI policy** before relying on this for credit-bearing coursework.
