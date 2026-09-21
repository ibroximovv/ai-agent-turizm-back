# Content Pipeline & Open WebUI Integration Rules

This document specifies the rules for document ingestion, Uzbek transliteration, grounding markers, and Open WebUI synchronization.

---

## 1. Grounding Marker: [MANBA: ...] (Source Grounding)

To enable accurate grounding in RAG responses (e.g., `file.pdf, page 14`), a standardized source marker MUST be injected into the markdown body:

```markdown
[MANBA: Constitution.pdf | page 14 | Topic 1.1 | literature]
```

*(Note: `[MANBA: ...]` tag name is preserved as expected by the AI agent's system prompt and RAG citation extractor).*

### Marker Rules:
1. **Interval (`MARKER_INTERVAL`)**: Injected every **~600 characters**.
   - *Rationale*: Open WebUI uses a chunk size of 1500 characters. Injecting at ~600 characters guarantees that every chunk has at least one source marker even if the page spans multiple chunks.
2. **Chunk Boundary Labels**:
   - PDF: `page {i}` / `{i}-sahifa`
   - PPTX: `slide {i}` / `{i}-slayd`
   - DOCX / MD / TXT: `section` / `bo'lim`
3. **YAML Frontmatter**: Every converted `.md` document MUST start with standard metadata:
```markdown
---
module_id: "module-01"
module_name: "Module 1 Name"
topic_id: "topic-01"
topic_name: "Topic 1 Name"
type: "literature"
source: "original_file.pdf"
script: "latin"
chunks: "14"
---
```

---

## 2. Script Detection & Transliteration (Cyrillic -> Latin)
- **Script Detection (`detect_script`)**:
  - Sample first 4000 characters.
  - Uzbek Cyrillic distinct characters: `ў, қ, ғ, ҳ, Ў, Қ, Ғ, Ҳ`.
  - Russian distinct characters: `ы, щ, Ы, Щ`.
- **Transliteration Rules**:
  1. **Uzbek Cyrillic (`uz-cyrl`)**: MUST be transliterated to Latin (`to_latin`). Without this, users querying in Latin script cannot match Cyrillic documents in vector or BM25 retrieval.
  2. **Russian (`ru`)**: Preserved as-is (not transliterated).
  3. **Broken Font Repair**:
     - Word-ending `ии` caused by broken PDF glyph maps is repaired to `ий` (e.g. `маъмурии` -> `маъмурий`).
     - All-caps digraphs repaired (e.g. `TO‘RTINChI` -> `TO‘RTINCHI`, `TUZILIShI` -> `TUZILISHI`).
  4. **Text Unwrapping**: Hyphenated line breaks (`infor-` + `mation` -> `information`) and layout line breaks merged into continuous sentences.

---

## 3. Supported Formats & Constraints
- Supported: `.pdf`, `.pptx`, `.docx`, `.md`, `.txt`.
- Legacy formats rejected: `.ppt`, `.doc` (must be converted to modern formats first).
- Scanned images in PDFs (less than 40 chars per page) produce a warning/error requiring OCR.

---

## 4. Open WebUI (OWUI) Integration Protocol
- **Communication Protocol**: Strictly HTTP REST API (`OWUI_URL` + `OWUI_API_KEY`).
- **Knowledge Base Creation**:
  - Automatically verified or created per module via `POST /api/v1/knowledge/create`.
- **File Upload & Indexing**:
  - Markdown payload uploaded via `POST /api/v1/files/` (`process=true`).
  - Linked to KB via `POST /api/v1/knowledge/{kb_id}/file/add`.
- **Purging & Cleanup**:
  - When a material is deleted or re-uploaded, the prior file MUST be unlinked (`/api/v1/knowledge/{kb_id}/file/remove`) and deleted (`DELETE /api/v1/files/{file_id}`).
