---
name: content-pipeline
description: >-
  Guide and procedures for parsing documents (PDF, PPTX, DOCX, TXT, MD),
  Uzbek Cyrillic to Latin transliteration, injecting grounding [MANBA: ...] markers,
  and syncing with Open WebUI Knowledge Bases.
---

# Content Pipeline & Ingestion Skill

This skill guides the agent through parsing, cleaning, transliterating, and indexing documents into Open WebUI knowledge bases.

---

## Pipeline Workflow

### 1. Ingestion & Deduplication
- When a file is uploaded, calculate its SHA-256 hash (`file_hash`).
- Reject the upload with `409 Conflict` if a byte-identical file is already attached to the same topic.
- Set `materials.status` to `'queued'` and enqueue an asynchronous worker job.

### 2. Document Parsing & Text Cleaning
1. **PDF**: Extract text and tables page by page. Ensure minimum 40 characters per page; flag for OCR if below threshold.
2. **PPTX**: Extract titles, slide body text, tables, and presenter notes (`notes_slide`).
3. **DOCX**: Extract paragraphs, map heading styles (`Heading 1`, `Heading 2`) to Markdown headings (`#`, `##`), and convert tables to Markdown tables.
4. **Typography & Cleaning**:
   - Normalize non-breaking spaces `\u00a0` to standard spaces.
   - Apply Unicode NFC normalization.
   - Unwrap broken layout lines (`unwrap`).

### 3. Script Detection & Transliteration
1. Analyze script (`detect_script`) from initial sample.
2. If `uz-cyrl`:
   - Fix corrupted glyphs (`final -ии` -> `-ий`).
   - Fix capital digraphs (`TO‘RTINChI` -> `TO‘RTINCHI`).
   - Transliterate to Latin (`to_latin`).
3. If `ru`: preserve as-is without transliteration.

### 4. Grounding Marker Injection
- Split page/slide text into segments of ~600 characters (`MARKER_INTERVAL`).
- Inject grounding header:
  `[MANBA: {original_filename} | {page_or_slide} | {topic_code} | {material_type}]`
- Prepend YAML frontmatter with module, topic, and source metadata.
- Save to `uploads/ready/{module_code}/...md` and update `materials.md_file_path`.
- Set status to `'md_ready'`.

### 5. Open WebUI Synchronization
1. Verify or create module Knowledge Base (`POST /api/v1/knowledge/create`).
2. Upload markdown via `POST /api/v1/files/` (`process=true`). Store returned ID in `materials.owui_file_id`.
3. Associate file with KB: `POST /api/v1/knowledge/{kb_id}/file/add`.
4. Update `materials.status` to `'indexed'` and set `materials.indexed_at = now()`.
5. Log each milestone and error into the `audit_logs` table.
