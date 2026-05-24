"""Generate study content from transcript + notes using the selected AI provider.

Pipeline:
1. Section generation: each lecture chunk becomes a section with reading, key terms,
   matching pairs, and an optional diagram (Mermaid for flows, SVG for spatial).
2. Question generation (on demand): Level 1 (recall) or NBME (clinical vignette) MCQs
   for a section, ordered chronologically by the section's content.
3. Active recall (on demand): free-response prompts for a section.
4. Comprehensive quiz (on demand): MCQs spanning the whole lecture in order.
"""
import json
import re

import ai_provider
import cache_store
from model_config import DEFAULT_MODEL, current_model

MODEL = DEFAULT_MODEL
CACHE_DIR = cache_store.CACHE_DIR
GENERATOR_CACHE_VERSION = 1


# ============================================================================
# Chunking
# ============================================================================

def chunk_transcript(transcript: str, target_words: int = 600) -> list[str]:
    """Split transcript into roughly equal chunks at sentence boundaries."""
    sentences = re.split(r"(?<=[.!?])\s+", transcript.strip())
    chunks, current, count = [], [], 0
    for sent in sentences:
        words = len(sent.split())
        if count + words > target_words and current:
            chunks.append(" ".join(current))
            current, count = [sent], words
        else:
            current.append(sent)
            count += words
    if current:
        chunks.append(" ".join(current))
    return chunks


# ============================================================================
# Slide-based chunking — when slides are present, they are the authoritative
# skeleton. Slides get grouped into logical sections, and matching transcript
# excerpts are attached to each section.
# ============================================================================

def parse_slides(notes_text: str) -> list[dict]:
    """Parse a notes string that contains '--- Slide N ---' markers
    (produced by vision PDF reading or pptx parsing) into a list of slides."""
    if "--- Slide" not in notes_text:
        return []
    parts = re.split(r"---\s*Slide\s+(\d+)\s*---", notes_text)
    # parts is like: ['', '1', 'content...', '2', 'content...', ...]
    slides = []
    for i in range(1, len(parts), 2):
        try:
            num = int(parts[i])
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            if content:
                slides.append({"slide_num": num, "content": content})
        except (ValueError, IndexError):
            continue
    return slides


GROUPING_PROMPT = """You are organizing medical school lecture slides into logical sections.

Below are slides, each marked with its number and content. Group consecutive slides into LOGICAL SECTIONS — slides on the same topic should go together.

Guidelines:
- Each section should cover ONE coherent topic (e.g. "Patella anatomy", "Femoral nerve branches", "Vasculature of the thigh")
- Group 1-4 consecutive slides per section based on topic
- A title slide (just a topic name) starts a new section with the slides that follow it
- Sections must respect slide order — slide 5 can't be grouped with slide 12
- **A slide with a lot of dense content (tables, many bullets, structured reference info) should usually be its OWN section** — do not bury it inside a multi-slide grouping where it will get glossed over
- **Slides that are pure tables/reference content** (e.g. "Sacral plexus: Origin/Branches/Supply") should always stand alone as their own section
- Aim for 4-15 sections per lecture depending on length

SLIDES:
\"\"\"
{slides_text}
\"\"\"

Output a JSON array of section groupings:
[
  {{
    "title": "Short 3-7 word section title",
    "slide_numbers": [1, 2, 3]
  }},
  {{
    "title": "Next section title",
    "slide_numbers": [4, 5]
  }}
]

Output ONLY the JSON array. No preamble, no markdown fences."""


def group_slides_into_sections(slides: list[dict]) -> list[dict]:
    """Ask Claude to group consecutive slides into logical sections.
    Returns: [{'title': str, 'slide_numbers': [int], 'content': str}]"""
    if not slides:
        return []

    cache_key = cache_store.make_key("slide_grouping", {
        "version": GENERATOR_CACHE_VERSION,
        "model": current_model(),
        "slides": slides,
    })
    cached = cache_store.get(CACHE_DIR, "slide_grouping", cache_key)
    if cached is not None:
        return cached

    # Build slide text for the prompt
    slides_text = "\n\n".join(
        f"--- Slide {s['slide_num']} ---\n{s['content']}" for s in slides
    )
    # Cap to avoid blowing context
    if len(slides_text) > 30000:
        slides_text = slides_text[:30000] + "\n\n[content truncated]"

    prompt = GROUPING_PROMPT.format(slides_text=slides_text)
    try:
        groupings = _call_claude_json(prompt, max_tokens=2048)
        if not isinstance(groupings, list):
            raise ValueError("Expected list")
    except Exception as e:
        print(f"⚠️  Slide grouping failed ({e}), falling back to one section per slide")
        groupings = [{"title": f"Slide {s['slide_num']}", "slide_numbers": [s["slide_num"]]} for s in slides]

    # Build out section content by joining slide content
    slide_lookup = {s["slide_num"]: s["content"] for s in slides}
    sections = []
    for g in groupings:
        nums = g.get("slide_numbers", [])
        if not nums:
            continue
        content_parts = []
        for n in nums:
            if n in slide_lookup:
                content_parts.append(f"--- Slide {n} ---\n{slide_lookup[n]}")
        if not content_parts:
            continue
        sections.append({
            "title": g.get("title", f"Section"),
            "slide_numbers": nums,
            "slides_content": "\n\n".join(content_parts),
        })
    cache_store.set(CACHE_DIR, "slide_grouping", cache_key, sections)
    return sections


def align_transcript_to_sections(transcript: str, sections: list[dict]) -> list[dict]:
    """Distribute the transcript across slide-based sections proportionally.

    The transcript flows linearly during a lecture, and slides advance during
    the talk, so we slice the transcript into equal-ish chunks matching the
    section count. Then keyword-match each transcript chunk to the section it
    best fits with (since slide advancement isn't perfectly even).
    """
    if not transcript.strip() or not sections:
        for s in sections:
            s["transcript_excerpt"] = ""
        return sections

    # Slice transcript into N roughly-equal pieces (by sentences)
    sentences = re.split(r"(?<=[.!?])\s+", transcript.strip())
    n = len(sections)
    per_section = max(1, len(sentences) // n)
    chunks = []
    for i in range(n):
        start = i * per_section
        end = start + per_section if i < n - 1 else len(sentences)
        chunks.append(" ".join(sentences[start:end]))

    # Improve alignment by keyword matching — for each section,
    # pick the transcript chunk with the most term overlap, preferring
    # chunks near the section's expected position.
    used = set()
    for idx, section in enumerate(sections):
        slide_terms = set(
            w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z-]{4,}\b", section["slides_content"])
        )
        best_chunk_idx = idx  # default: positional
        best_score = -1
        # Check chunks within +/- 2 of expected position
        for ci in range(max(0, idx - 2), min(len(chunks), idx + 3)):
            if ci in used:
                continue
            chunk_lower = chunks[ci].lower()
            score = sum(1 for t in slide_terms if t in chunk_lower)
            # Positional bonus to break ties
            distance_penalty = abs(ci - idx) * 0.5
            adjusted = score - distance_penalty
            if adjusted > best_score:
                best_score = adjusted
                best_chunk_idx = ci
        used.add(best_chunk_idx)
        section["transcript_excerpt"] = chunks[best_chunk_idx]
        section["transcript_index"] = best_chunk_idx
    return sections


def _snippet(text: str, max_chars: int = 360) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text[:max_chars].rstrip()


def _source_matches(needle: str, slides: list[dict], transcript: str) -> dict:
    terms = [
        t.lower()
        for t in re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", needle or "")
        if len(t) >= 4
    ][:8]
    slide_numbers = []
    for slide in slides:
        content = slide.get("excerpt") or ""
        content_lower = content.lower()
        if any(term in content_lower for term in terms):
            slide_numbers.append(slide.get("slide_number"))
    transcript_lower = (transcript or "").lower()
    transcript_hit = any(term in transcript_lower for term in terms)
    return {
        "slide_numbers": [n for n in slide_numbers if n is not None],
        "transcript_excerpt": _snippet(transcript) if transcript_hit else "",
    }


def build_source_citations(group: dict) -> dict:
    slides = []
    for slide in parse_slides(group.get("slides_content", "")):
        slides.append({
            "slide_number": slide["slide_num"],
            "excerpt": _snippet(slide["content"]),
        })
    transcript_excerpt = _snippet(group.get("transcript_excerpt", ""))
    return {
        "slides": slides,
        "transcript": {
            "chunk_index": group.get("transcript_index"),
            "excerpt": transcript_excerpt,
        },
    }


def attach_fact_citations(section: dict, citations: dict) -> dict:
    slides = citations.get("slides") or []
    transcript = (citations.get("transcript") or {}).get("excerpt") or ""
    fact_citations = []
    for term in section.get("key_terms") or []:
        label = term.get("term") or ""
        source_text = f"{term.get('term', '')} {term.get('definition', '')}"
        fact_citations.append({
            "kind": "key_term",
            "label": label,
            **_source_matches(source_text, slides, transcript),
        })
    for pair in section.get("matching") or []:
        label = pair.get("left") or ""
        source_text = f"{pair.get('left', '')} {pair.get('right', '')}"
        fact_citations.append({
            "kind": "matching",
            "label": label,
            **_source_matches(source_text, slides, transcript),
        })
    section["source_citations"] = citations
    section["fact_citations"] = fact_citations
    return section


def find_relevant_notes(chunk: str, notes: str, max_chars: int = 3000) -> str:
    """Pull paragraphs from notes that share terms with the chunk."""
    if not notes.strip():
        return ""
    if len(notes) <= max_chars:
        return notes
    terms = {w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z-]{3,}\b", chunk)}
    paragraphs = re.split(r"\n\s*\n", notes)
    scored = [(sum(1 for t in terms if t in p.lower()), p) for p in paragraphs]
    scored.sort(key=lambda x: -x[0])
    selected, total = [], 0
    for score, para in scored:
        if score == 0 or total + len(para) > max_chars:
            break
        selected.append(para)
        total += len(para)
    return "\n\n".join(selected) if selected else notes[:max_chars]


# ============================================================================
# Claude call helper
# ============================================================================

def _call_claude_json(prompt: str, max_tokens: int = 4096) -> dict | list:
    """Send a prompt and parse a JSON response, tolerating markdown fences."""
    return ai_provider.call_json(prompt, max_tokens=max_tokens)


def _rebalance_answer_positions(questions: list[dict]) -> list[dict]:
    """Shuffle answer positions so correct_index is roughly evenly distributed.

    This is a safety net — even with prompt instructions, LLMs cluster correct
    answers in the middle. We deterministically rebalance afterward.
    """
    import random
    if not questions:
        return questions

    # Target distribution: cycle through 0,1,2,3 evenly
    target_positions = []
    for i in range(len(questions)):
        target_positions.append(i % 4)
    random.shuffle(target_positions)

    rebalanced = []
    for q, new_pos in zip(questions, target_positions):
        choices = list(q.get("choices", []))
        correct_idx = q.get("correct_index", 0)
        if not choices or correct_idx >= len(choices) or new_pos >= len(choices):
            rebalanced.append(q)
            continue
        # Move the correct choice to new_pos
        correct_choice = choices.pop(correct_idx)
        choices.insert(new_pos, correct_choice)
        rebalanced.append({**q, "choices": choices, "correct_index": new_pos})
    return rebalanced


# ============================================================================
# Strict-source preamble used in every prompt
# ============================================================================

STRICT_RULES = """CRITICAL SOURCE RULES (apply to everything you generate):
1. Use ONLY information explicitly present in the supplied LECTURE CHUNK and NOTES.
2. Do NOT add facts from your general medical knowledge, even if they would be helpful or "standard."
3. Do NOT skip anything substantive from the lecture chunk — every concept, term, mechanism, structure, or clinical detail mentioned in the chunk must be reflected in your output.
4. If the lecture mentions something briefly without explanation, you may include it as a term but do not invent the explanation.
5. If unsure whether a fact comes from the materials or your own knowledge, leave it out.
"""


# ============================================================================
# 1. Section generation (reading + matching + terms + optional diagram)
# ============================================================================

SECTION_PROMPT = STRICT_RULES + """

You are creating a study section from a medical school lecture.

You are given TWO authoritative sources covering the same topic:
- SLIDES: the text and labels from the actual lecture slides
- TRANSCRIPT: what the professor said while presenting these slides

Both are equally authoritative. Your job is to MERGE them into a complete study section that misses NOTHING from either source.

SLIDES (every bullet, label, term, and fact here MUST appear in your output):
\"\"\"
{slides_content}
\"\"\"

TRANSCRIPT (every concept, mechanism, and explanation here MUST appear in your output):
\"\"\"
{transcript_excerpt}
\"\"\"

CRITICAL MERGING RULES:
1. Every bullet point, anatomical label, structure name, and fact on the slides must be reflected in your output, even if the professor didn't mention it out loud.
2. Every explanation, mechanism, clinical correlation, and detail from the transcript must be reflected in your output, even if it's not on the slides.
3. When the slide says "X" and the transcript expands on what X does/means, combine them — the slide gives the term, the transcript gives the context.
4. Do NOT skip slide content because the professor didn't talk about it. Do NOT skip professor content because it's not on the slides.
5. **Tables in the slides must be preserved as markdown tables** in your output (using `| header | header |` syntax with `|---|---|` separator rows). Every row and cell must be kept. Do NOT flatten tables into prose.
6. **When slides contain structured reference content** (origin/branches/supply tables, lists of attachments, lists of innervations) — preserve the exact structure. These are the highest-yield testable content for exams.
7. Do NOT add facts from your general medical knowledge. Only use what's in slides or transcript.
8. If unsure whether a fact comes from the sources or your own knowledge, leave it out.

Produce a JSON object with this exact structure:
{{
  "title": "3-7 word topic title (use the topic, not slide numbers)",
  "reading": "A well-organized notes-style summary formatted in Markdown that MERGES both sources. USE: ## subheadings to break up the content into logical groupings; **bold** for key anatomical terms, structures, and important facts the first time they appear; bullet lists (- item) when describing components, branches, or lists of things; prose paragraphs when explaining mechanisms. The reading must include EVERY substantive item from both slides AND transcript. About 400-700 words depending on content density.",
  "key_terms": [
    {{"term": "term", "definition": "definition from the materials"}}
  ],
  "matching": [
    {{"left": "term/concept", "right": "matching fact/definition"}}
  ],
  "diagram": null OR one of:
    {{"type": "mermaid", "code": "flowchart TD\\n    A[Step 1] --> B[Step 2]", "caption": "Brief caption"}}
    OR
    {{"type": "svg", "code": "<svg viewBox=\\"0 0 400 300\\" xmlns=\\"http://www.w3.org/2000/svg\\">...</svg>", "caption": "Brief caption"}}
}}

DIAGRAM RULES:
- If the content describes a pathway, sequence, cascade, branching structure, or flow, INCLUDE a diagram.
- Use Mermaid (flowchart TD or flowchart LR) for: pathways, cascades, decision trees, sequences, branching.
- Use SVG for: anatomical layouts, spatial relationships, labeled structures.
- For SVG: use viewBox="0 0 600 400", muted earthy colors (#6b8060 sage, #b56b4a terracotta, #c69149 gold, #2d2a24 ink, #f5efe4 cream), labeled with <text> elements at 13-14px.
- Keep diagrams clean — 5-12 nodes/elements maximum.
- Do NOT include facts in the diagram that aren't in the source materials.
- If no pathway/structure is described, set diagram to null.

QUANTITY GUIDELINES:
- 5-12 key_terms (more if slide content is dense)
- 5-10 matching pairs

Output ONLY the JSON object. No preamble, no markdown fences."""


READING_ONLY_PROMPT = STRICT_RULES + """

Regenerate just the reading section. Same strict source rules apply.

You are given TWO authoritative sources covering the same topic. Merge them completely:

SLIDES (every bullet, label, term, and fact must appear in your output):
\"\"\"
{slides_content}
\"\"\"

TRANSCRIPT (every concept, mechanism, and detail must appear in your output):
\"\"\"
{transcript_excerpt}
\"\"\"

MERGING RULES:
1. Every fact on the slides must be reflected, even if not mentioned in transcript.
2. Every explanation in the transcript must be reflected, even if not on slides.
3. Do not skip anything substantive from either source.
4. **Tables in the slides must be preserved as markdown tables** in your output (using `| header | header |` and `|---|---|` syntax). Every row and cell must be kept.
5. **Structured reference content** (origin/branches/supply, attachments, innervations) must keep its structure — these are the highest-yield testable items.
6. Use ONLY information from the supplied sources.

Produce a JSON object with exactly this structure:
{{
  "reading": "A well-organized notes-style summary formatted in Markdown that MERGES both sources. USE: ## subheadings to break up the content into logical groupings; **bold** for key anatomical terms, structures, and important facts the first time they appear; bullet lists (- item) when describing components, branches, or lists of things; prose paragraphs when explaining mechanisms. The reading must include EVERY substantive item from both slides AND transcript. About 400-700 words depending on content density."
}}

Output ONLY the JSON object."""


def regenerate_reading(chunk: str = "", notes: str = "",
                       slides_content: str = "", transcript_excerpt: str = "") -> str:
    """Regenerate just the reading portion of a section.

    Supports two calling modes:
    - New: pass slides_content + transcript_excerpt
    - Old (back-compat): pass chunk + notes — they get mapped to the new prompt slots
    """
    if not slides_content and not transcript_excerpt:
        # Back-compat: old-style call. Treat 'chunk' as transcript_excerpt
        # and 'notes' as slides_content.
        slides_content = notes or ""
        transcript_excerpt = chunk or ""

    prompt = READING_ONLY_PROMPT.format(
        slides_content=slides_content or "(no slides provided)",
        transcript_excerpt=transcript_excerpt or "(no transcript provided)",
    )
    data = _call_claude_json(prompt, max_tokens=4096)
    return data.get("reading", "")


def generate_section(slides_content: str, transcript_excerpt: str,
                     section_index: int, suggested_title: str = "") -> dict:
    """Generate one section by merging slides + transcript.

    slides_content: text of all slides in this section
    transcript_excerpt: relevant portion of the lecture transcript
    """
    cache_key = cache_store.make_key("section_generation", {
        "version": GENERATOR_CACHE_VERSION,
        "model": current_model(),
        "slides_hash": cache_store.hash_text(slides_content or ""),
        "transcript_hash": cache_store.hash_text(transcript_excerpt or ""),
        "suggested_title": suggested_title or "",
    })
    cached = cache_store.get(CACHE_DIR, "section_generation", cache_key)
    if cached is not None:
        data = cached
    else:
        prompt = SECTION_PROMPT.format(
            slides_content=slides_content or "(no slides provided)",
            transcript_excerpt=transcript_excerpt or "(no transcript provided)",
        )
        data = _call_claude_json(prompt, max_tokens=6144)
        cache_store.set(CACHE_DIR, "section_generation", cache_key, data)
    data = dict(data)
    data["section_index"] = section_index
    # Store both sources so question generators can use the full content
    data["chunk"] = f"=== SLIDES ===\n{slides_content}\n\n=== TRANSCRIPT ===\n{transcript_excerpt}".strip()
    data["slides_content"] = slides_content
    data["transcript_excerpt"] = transcript_excerpt
    data["completed"] = False
    data["questions_l1"] = []      # generated on demand
    data["questions_nbme"] = []    # generated on demand
    data["recall_prompts"] = []    # generated on demand
    # Use the suggested grouping title if Claude didn't pick a better one
    if suggested_title and not data.get("title"):
        data["title"] = suggested_title
    return data


def build_sections(transcript: str, notes: str, progress=None) -> list[dict]:
    """Build all sections for a lecture.

    Smart pipeline:
    - If notes contain '--- Slide N ---' markers (from PDF vision or pptx parsing),
      use slide-based grouping: slides become sections, transcript gets attached.
    - Otherwise, fall back to transcript-only chunking.
    """
    slides = parse_slides(notes)

    if slides:
        if progress:
            progress({"stage": "Detecting slides", "slide_count": len(slides)})
        print(f"📑 Detected {len(slides)} slides — using slide-based sectioning")
        print(f"   Grouping slides into logical sections...")
        if progress:
            progress({"stage": "Grouping slides", "item_label": "slide", "current": 0, "total": len(slides)})
        groups = group_slides_into_sections(slides)
        print(f"   Created {len(groups)} sections from {len(slides)} slides")
        print(f"   Aligning transcript to sections...")
        if progress:
            progress({"stage": "Aligning transcript", "total": len(groups), "current": 0})
        groups = align_transcript_to_sections(transcript, groups)

        sections = []
        if progress:
            progress({"stage": "Generating study sections", "total": len(groups), "current": 0})
        for i, g in enumerate(groups, 1):
            print(f"   [{i}/{len(groups)}] Generating: {g['title']}...")
            if progress:
                progress({
                    "stage": "Generating study sections",
                    "total": len(groups),
                    "current": i,
                    "section_title": g.get("title") or f"Section {i}",
                })
            try:
                section = generate_section(
                    slides_content=g["slides_content"],
                    transcript_excerpt=g.get("transcript_excerpt", ""),
                    section_index=i,
                    suggested_title=g.get("title", ""),
                )
                # Store slide numbers so the UI can show them
                section["slide_numbers"] = g.get("slide_numbers", [])
                attach_fact_citations(section, build_source_citations(g))
                sections.append(section)
                if progress:
                    progress({
                        "stage": "Generating study sections",
                        "total": len(groups),
                        "current": i,
                        "completed": len(sections),
                        "section_title": section.get("title") or g.get("title") or f"Section {i}",
                    })
            except Exception as e:
                print(f"   ⚠️  Skipping section {i}: {e}")
        return sections

    # No slides detected — fall back to transcript chunking
    print(f"📜 No slides detected — using transcript-only chunking")
    if progress:
        progress({"stage": "Chunking transcript"})
    chunks = chunk_transcript(transcript)
    print(f"   Split transcript into {len(chunks)} chunks")
    sections = []
    if progress:
        progress({"stage": "Generating study sections", "total": len(chunks), "current": 0})
    for i, chunk in enumerate(chunks, 1):
        print(f"   [{i}/{len(chunks)}] Section...")
        if progress:
            progress({
                "stage": "Generating study sections",
                "total": len(chunks),
                "current": i,
                "section_title": f"Section {i}",
            })
        try:
            # In transcript-only mode, the chunk acts as the transcript and notes acts as slides_content
            section = generate_section(
                slides_content=notes or "",
                transcript_excerpt=chunk,
                section_index=i,
            )
            attach_fact_citations(section, build_source_citations({
                "slides_content": notes or "",
                "transcript_excerpt": chunk,
                "transcript_index": i - 1,
            }))
            sections.append(section)
            if progress:
                progress({
                    "stage": "Generating study sections",
                    "total": len(chunks),
                    "current": i,
                    "completed": len(sections),
                    "section_title": section.get("title") or f"Section {i}",
                })
        except Exception as e:
            print(f"   ⚠️  Skipping section {i}: {e}")
    return sections


# ============================================================================
# 2. Question generation (Level 1 and NBME)
# ============================================================================

L1_QUESTIONS_PROMPT = STRICT_RULES + """

Generate Level 1 multiple-choice questions for this section.

SECTION CHUNK (the authoritative content):
\"\"\"
{chunk}
\"\"\"

RELEVANT NOTES:
\"\"\"
{notes_context}
\"\"\"

REQUIREMENTS:
- Generate 6-10 questions.
- All questions must be MULTIPLE CHOICE with exactly 4 choices.
- "Level 1" means FIRST-ORDER RECALL: direct facts, definitions, identifications, "what is X?", "which nerve does Y?", "what's the function of Z?".
- NO clinical vignettes at this level.
- CHRONOLOGICAL ORDER: order questions to follow the section's content top-to-bottom, so a student progresses through the section like a story.
- Avoid duplicating these existing questions: {avoid_list}

ANSWER POSITION DISTRIBUTION (critical):
- The correct_index MUST be distributed roughly evenly across positions 0, 1, 2, and 3.
- For a set of 8 questions: roughly 2 should have correct_index=0, 2 should have correct_index=1, 2 should have correct_index=2, and 2 should have correct_index=3.
- DO NOT cluster correct answers at index 1 or 2. Vary the position deliberately.
- Before finalizing, count your correct_indices and rebalance if needed.

DISTRACTOR QUALITY (critical):
- The three wrong choices must be PLAUSIBLE — a student who didn't study carefully should be tempted by them.
- Distractors must be SIMILAR IN LENGTH to the correct answer. Do NOT make the correct one noticeably longer or shorter.
- Distractors must be SIMILAR IN STRUCTURE: same grammatical form, same level of specificity.
- Distractors should be drawn from RELATED content in the materials (other nerves, other structures, other muscles in the same region, etc.) — not random unrelated things.
- No "obviously wrong" choices like "the moon" or unrelated topics.
- No "all of the above" or "none of the above" choices.
- The correct answer should not be the only choice that's a complete sentence, or the only one with specific numbers, etc.

Output JSON array only:
[
  {{
    "question": "...",
    "choices": ["choice A", "choice B", "choice C", "choice D"],
    "correct_index": 0,
    "explanation": "Why correct, citing what the materials say.",
    "difficulty": "L1"
  }}
]

Output ONLY the JSON array. No preamble, no markdown fences."""


NBME_QUESTIONS_PROMPT = STRICT_RULES + """

Generate NBME-style multiple-choice questions for this section.

SECTION CHUNK (the authoritative content):
\"\"\"
{chunk}
\"\"\"

RELEVANT NOTES:
\"\"\"
{notes_context}
\"\"\"

REQUIREMENTS:
- Generate 5-8 questions.
- All questions must be MULTIPLE CHOICE with exactly 4 choices.
- NBME-STYLE: clinical vignette stems (a patient presents with...), second-order reasoning, applying the section's facts to a scenario. USMLE Step 1 difficulty.
- The CLINICAL FACTS used in the stem and the CORRECT ANSWER must be derivable from the supplied materials. If the materials don't contain a clinical detail, do not invent one — pick a different angle.
- CHRONOLOGICAL ORDER: order questions to follow the section's content top-to-bottom.
- Avoid duplicating these existing questions: {avoid_list}

ANSWER POSITION DISTRIBUTION (critical):
- The correct_index MUST be distributed roughly evenly across positions 0, 1, 2, and 3.
- For a set of 8 questions: roughly 2 should have correct_index=0, 2 should have correct_index=1, 2 should have correct_index=2, and 2 should have correct_index=3.
- DO NOT cluster correct answers at index 1 or 2. Vary the position deliberately.
- Before finalizing, count your correct_indices and rebalance if needed.

DISTRACTOR QUALITY (critical):
- The three wrong choices must be PLAUSIBLE — a student who didn't study carefully should be tempted by them.
- Distractors must be SIMILAR IN LENGTH to the correct answer. Do NOT make the correct one noticeably longer or shorter.
- Distractors must be SIMILAR IN STRUCTURE: same grammatical form, same level of specificity.
- Distractors should be drawn from RELATED content in the materials (other nerves, other diagnoses, other mechanisms in the same region) — not random unrelated things.
- No "obviously wrong" choices.
- No "all of the above" or "none of the above" choices.
- The correct answer should not be obvious from length, formatting, or specificity differences.

Output JSON array only:
[
  {{
    "question": "Clinical vignette ending in a question.",
    "choices": ["choice A", "choice B", "choice C", "choice D"],
    "correct_index": 0,
    "explanation": "Clinical reasoning citing the source material.",
    "difficulty": "NBME"
  }}
]

Output ONLY the JSON array. No preamble, no markdown fences."""


def generate_questions(chunk: str, notes: str, difficulty: str, existing: list[dict] | None = None) -> list[dict]:
    """Generate questions at given difficulty level for a section.

    difficulty: 'L1' or 'NBME'
    existing: list of previously generated questions to avoid duplicating.
    """
    notes_context = find_relevant_notes(chunk, notes)
    avoid = [q["question"][:80] for q in (existing or [])][:20]
    avoid_list = json.dumps(avoid)

    if difficulty == "L1":
        prompt = L1_QUESTIONS_PROMPT.format(
            chunk=chunk, notes_context=notes_context, avoid_list=avoid_list
        )
    elif difficulty == "NBME":
        prompt = NBME_QUESTIONS_PROMPT.format(
            chunk=chunk, notes_context=notes_context, avoid_list=avoid_list
        )
    else:
        raise ValueError(f"Unknown difficulty: {difficulty}")

    data = _call_claude_json(prompt, max_tokens=4096)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of questions")
    return _rebalance_answer_positions(data)


# ============================================================================
# 3. Active recall prompts (free response)
# ============================================================================

RECALL_PROMPT = STRICT_RULES + """

Generate active-recall free-response prompts for this section.

SECTION CHUNK:
\"\"\"
{chunk}
\"\"\"

RELEVANT NOTES:
\"\"\"
{notes_context}
\"\"\"

REQUIREMENTS:
- Generate 4-6 prompts.
- These are FREE-RESPONSE (not multiple choice). The student will type an answer, then reveal a model answer.
- Prompts should require recall and explanation, not just one-word answers. Examples: "Describe the pathway of...", "Explain the difference between X and Y...", "Walk through the steps of..."
- Order prompts CHRONOLOGICALLY to follow the section's content.
- Model answers must be derivable from the supplied materials.

Output JSON array only:
[
  {{
    "prompt": "...",
    "model_answer": "What a complete answer should contain, based only on the materials."
  }}
]

Output ONLY the JSON array. No preamble, no markdown fences."""


def generate_recall_prompts(chunk: str, notes: str) -> list[dict]:
    notes_context = find_relevant_notes(chunk, notes)
    prompt = RECALL_PROMPT.format(chunk=chunk, notes_context=notes_context)
    data = _call_claude_json(prompt, max_tokens=2048)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of recall prompts")
    return data


# ============================================================================
# 4. Comprehensive end-of-lecture quiz
# ============================================================================

COMPREHENSIVE_PROMPT = STRICT_RULES + """

Generate a COMPREHENSIVE end-of-lecture multiple-choice quiz covering the entire lecture.

ALL LECTURE CONTENT (in order):
\"\"\"
{full_content}
\"\"\"

REQUIREMENTS:
- Generate 15-25 questions covering the WHOLE lecture.
- All multiple choice with 4 choices.
- Mix difficulty: roughly 60% Level 1 (recall) and 40% NBME-style clinical vignettes.
- ORDER QUESTIONS CHRONOLOGICALLY across the lecture: questions about early-lecture content come first, late-lecture content last. The quiz should walk through the lecture like a story.
- Cover all the major sections and important concepts.

ANSWER POSITION DISTRIBUTION (critical):
- correct_index must be distributed roughly evenly across positions 0, 1, 2, 3.
- For a 20-question quiz, approximately 5 should be at each position.
- Do NOT cluster correct answers at index 1 or 2.

DISTRACTOR QUALITY (critical):
- All three wrong choices must be plausible and tempting to a student who didn't study carefully.
- Distractors must be similar in length and grammatical structure to the correct answer.
- Distractors should be drawn from other parts of the lecture (related structures, similar mechanisms) — not random unrelated content.
- No "all of the above" or "none of the above" choices.

Output JSON array only:
[
  {{
    "question": "...",
    "choices": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "Why correct, citing the source.",
    "difficulty": "L1" or "NBME"
  }}
]

Output ONLY the JSON array. No preamble, no markdown fences."""


# ============================================================================
# 5. Flashcards
# ============================================================================

FLASHCARDS_PROMPT = STRICT_RULES + """

Generate flashcards for this section.

SECTION CHUNK:
\"\"\"
{chunk}
\"\"\"

RELEVANT NOTES:
\"\"\"
{notes_context}
\"\"\"

REQUIREMENTS:
- Generate 8-15 flashcards.
- Each card has a "front" (a prompt or question) and "back" (the answer).
- Cards should test atomic facts (one fact per card), not paragraphs.
- Mix card types: term-definition, function-of-X, structure-passing-through-X, source-of-X, etc.
- Order chronologically by where the fact appears in the section.

Output JSON array only:
[
  {{"front": "...", "back": "..."}}
]

Output ONLY the JSON array."""


def generate_flashcards(chunk: str, notes: str) -> list[dict]:
    notes_context = find_relevant_notes(chunk, notes)
    prompt = FLASHCARDS_PROMPT.format(chunk=chunk, notes_context=notes_context)
    data = _call_claude_json(prompt, max_tokens=3072)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of flashcards")
    return data


# ============================================================================
# 6. Cloze deletions
# ============================================================================

CLOZE_PROMPT = STRICT_RULES + """

Generate cloze deletion cards (fill-in-the-blank) for this section.

SECTION CHUNK:
\"\"\"
{chunk}
\"\"\"

RELEVANT NOTES:
\"\"\"
{notes_context}
\"\"\"

REQUIREMENTS:
- Generate 6-12 cloze cards.
- Each card has "text" with one blank marked by {{{{...}}}} and "answer" with the blanked text.
- Example: {{"text": "The {{{{glossopharyngeal nerve}}}} provides general sensation to the posterior third of the tongue.", "answer": "glossopharyngeal nerve"}}
- Blank out the single most important fact in each sentence (a structure, function, source, value, etc.).
- Order chronologically by where the fact appears.
- Use only facts present in the materials.

Output JSON array only:
[
  {{"text": "Sentence with {{{{blanked term}}}}.", "answer": "blanked term"}}
]

Output ONLY the JSON array."""


def generate_clozes(chunk: str, notes: str) -> list[dict]:
    notes_context = find_relevant_notes(chunk, notes)
    prompt = CLOZE_PROMPT.format(chunk=chunk, notes_context=notes_context)
    data = _call_claude_json(prompt, max_tokens=3072)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of clozes")
    return data


# ============================================================================
# 7. Exam-level cumulative quiz (across multiple lectures)
# ============================================================================

EXAM_QUIZ_PROMPT = STRICT_RULES + """

Generate an EXAM-LEVEL cumulative multiple-choice quiz drawing from MULTIPLE lectures.

ALL LECTURES IN THIS EXAM (in order):
\"\"\"
{full_content}
\"\"\"

REQUIREMENTS:
- Generate 25-40 questions.
- All multiple choice, 4 choices each.
- Mix difficulty: 50% Level 1 recall, 50% NBME-style clinical vignettes.
- Distribute questions across all lectures — don't favor one.
- Within each lecture's questions, follow chronological order.

ANSWER POSITION DISTRIBUTION (critical):
- correct_index must be distributed roughly evenly across positions 0, 1, 2, 3.
- For 30 questions, approximately 7-8 should be at each position.
- Do NOT cluster correct answers at index 1 or 2.

DISTRACTOR QUALITY (critical):
- Wrong choices must be plausible and tempting.
- Distractors must be similar in length and structure to the correct answer.
- Distractors should pull from related content across lectures in this exam — not random unrelated topics.
- No "all of the above" or "none of the above" choices.

Output JSON array only:
[
  {{
    "question": "...",
    "choices": ["A", "B", "C", "D"],
    "correct_index": 0,
    "explanation": "...",
    "difficulty": "L1" or "NBME",
    "source_lecture": "Lecture name where this comes from"
  }}
]

Output ONLY the JSON array."""


def generate_exam_quiz(lectures: list[dict]) -> list[dict]:
    """Generate a cumulative quiz across all lectures in an exam."""
    parts = []
    for lec in lectures:
        parts.append(f"\n========= LECTURE: {lec['name']} =========\n")
        for s in lec["sections"]:
            parts.append(f"--- Section {s['section_index']}: {s['title']} ---\n{s.get('chunk', '')}")
    full_content = "\n\n".join(parts)
    if len(full_content) > 80000:
        full_content = full_content[:80000]
    prompt = EXAM_QUIZ_PROMPT.format(full_content=full_content)
    data = _call_claude_json(prompt, max_tokens=8192)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of questions")
    return _rebalance_answer_positions(data)


# ============================================================================
# 4. Comprehensive end-of-lecture quiz (continued from above)
# ============================================================================

def generate_comprehensive_quiz(sections: list[dict]) -> list[dict]:
    """Generate a comprehensive quiz from all sections of a lecture."""
    parts = []
    for s in sections:
        parts.append(f"--- SECTION {s['section_index']}: {s['title']} ---\n{s['chunk']}")
    full_content = "\n\n".join(parts)
    # Cap to avoid blowing context — full lectures are usually fine
    if len(full_content) > 60000:
        full_content = full_content[:60000]
    prompt = COMPREHENSIVE_PROMPT.format(full_content=full_content)
    data = _call_claude_json(prompt, max_tokens=8192)
    if not isinstance(data, list):
        raise ValueError("Expected JSON array of questions")
    return _rebalance_answer_positions(data)
