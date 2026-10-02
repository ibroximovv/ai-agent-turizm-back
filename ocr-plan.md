# OCR rejasi — skanerlangan PDF'larni Markdown'ga o'tkazish

> Holat: **1-bosqich amalga oshirildi** (2026-10-02), 0-qadam — haqiqiy
> kitoblarda o'lchash — hali qilinmagan. 2- va 3-bosqichlar — reja.
> Maqsad: skaner qilingan (rasm ko'rinishidagi) PDF yuklanganda pipeline uni
> avtomatik OCR qilib, oddiy PDF kabi grounded Markdown'ga aylantirsin va
> Open WebUI KB'ga indekslasin.

### Qabul qilingan qarorlar

| Qaror | Ta'siri |
|---|---|
| **Hozir** OCR backend bilan bir serverda ishlaydi | Tesseract mavjud serverga o'rnatiladi, alohida infratuzilma yo'q |
| **Keyinroq** OCR alohida serverga ko'chiriladi | Kod boshidanoq `OcrBackend` interfeysi orqali yoziladi: ko'chirish = yangi backend + sozlama, pipeline kodi o'zgarmaydi (3.2, 4-bo'lim) |
| Asosiy hujjatlar — **200–500 sahifalik kitoblar**, soni ko'p | OCR bitta kitobga ~10–40 daqiqa oladi → alohida OCR navbati (3.9), sahifa keshi (3.8), progress, katta fayl yuklash limiti (4.1) majburiy |

---

## 0. Hozirgi holat — muammo qayerda

Pipeline: `parse_file` → `clean_text` → `detect_script`/`to_latin` →
`build_grounded_markdown` → Open WebUI (`apps/pipeline/service.py`).

PDF'ni `apps/pipeline/services/parser.py:_parse_pdf` o'qiydi va faqat
`pypdf` ning **matn qatlami**dan (`page.extract_text()`) foydalanadi:

- Sahifada matn bo'lmasa — sahifa shunchaki tashlab ketiladi.
- 40 belgidan kam bo'lsa — "skanerlangan rasm bo'lishi mumkin" ogohlantirishi.
- Hech bir sahifada matn bo'lmasa — `"PDF ichidan matn topilmadi — hujjat
  skanerlangan va OCR talab qiladi."` va `service.py` material'ni `failed`
  qiladi (`Hujjatdan matn ajratib bo'lmadi`).

Ya'ni aniqlash allaqachon bor, faqat **OCR bosqichi yo'q**. Yana bir yashirin
muammo: *aralash* PDF (bir qismi matnli, bir qismi skan) hozir "muvaffaqiyatli"
o'tadi, lekin skan sahifalar indeksga tushmay qoladi — buni hech kim sezmaydi.

---

## 1. OCR nima va qanday ishlaydi (nazariya)

**OCR (Optical Character Recognition)** — rasmdagi harflarni mashina o'qiy
oladigan matnga aylantirish. Skanerlangan PDF aslida har sahifasi bitta rasm
(JPEG / JBIG2 / CCITT) bo'lgan konteyner: unda "harf" degan narsa yo'q, faqat
piksellar bor. Shuning uchun `pypdf` hech narsa topmaydi.

### 1.1. Klassik OCR konveyeri

```
 PDF sahifa
    │
    ▼
 1. Rasterizatsiya   — sahifani rasmga chizish (300 DPI)
    │
    ▼
 2. Oldindan ishlash — kulrang, binarizatsiya (Otsu/Sauvola), shovqinni
    │                  tozalash, qiyshiqlikni (deskew) va burilishni tuzatish
    ▼
 3. Layout tahlili   — ustunlar, bloklar, qatorlar, so'zlarni topish
    │                  (qaysi tartibda o'qish kerakligi)
    ▼
 4. Tanib olish      — har bir qator rasmini neyron tarmoq (LSTM / CNN /
    │                  transformer) belgilar ketma-ketligiga aylantiradi
    ▼
 5. Til modeli       — lug'at va til ehtimolliklari bilan xatolarni kamaytirish
    │
    ▼
 Matn + har so'z uchun ishonch (confidence 0–100) + koordinatalar
```

Muhim tushunchalar:

| Tushuncha | Nima uchun muhim |
|---|---|
| **DPI** | 300 DPI — oddiy matn uchun standart. 200 dan pasti aniqlikni keskin tushiradi, 400+ faqat mayda shrift uchun kerak, vaqt va xotira oshadi. |
| **Til paketi** | Model qaysi alifbo va tilga o'qitilgan bo'lsa, shuni yaxshi taniydi. O'zbek kirill uchun `uzb_cyrl` alohida kerak — `rus` modelida `ў қ ғ ҳ` harflari yo'q. |
| **Confidence** | Har so'z/sahifa uchun ishonch bali. Past ball — yomon skan, noto'g'ri til yoki rasm/jadval. Biz uni sifat nazorati uchun ishlatamiz. |
| **PSM (page segmentation mode)** | Tesseract'ga sahifa tuzilishini qanday taxmin qilishni aytadi. `3` (avto) — kitob sahifalari uchun; `6` — bitta matn bloki. |
| **Text layer** | OCR natijasini PDF ichiga ko'rinmas qatlam qilib yozish mumkin (searchable PDF). Bizga bu shart emas — bizga faqat matn kerak. |

### 1.2. OCR dvigatellari turlari

1. **Klassik / CPU** — *Tesseract 5* (Google, LSTM). Bepul, offline, CPU'da
   ishlaydi, 100+ til, jumladan `uzb`, `uzb_cyrl`, `rus`. Toza kitob
   skanlarida yaxshi; yomon skan, jadval, qo'lyozmada zaif.
2. **Deep-learning / GPU tavsiya etiladi** — PaddleOCR, docTR, Surya,
   EasyOCR. Murakkab layout'da kuchliroq, lekin o'zbek (ayniqsa kirill)
   qo'llab-quvvatlashi zaif yoki yo'q; GPU'siz sekin.
3. **Bulutli OCR API** — Google Cloud Vision / Document AI, Azure Document
   Intelligence. Yuqori sifat, server kerak emas, sahifa uchun pul to'lanadi,
   hujjat tashqi xizmatga yuboriladi. (AWS Textract o'zbek/rus tillarini
   qo'llamaydi — bizga mos emas.)
4. **Vision LLM** — Gemini, Claude, GPT kabi rasm tushunadigan modellar yoki
   ochiq modellar (Qwen2.5-VL, olmOCR). Sahifani to'g'ridan-to'g'ri
   **Markdown**ga (sarlavha, ro'yxat, jadval bilan) aylantiradi, yomon skanni
   ham "tushunib" o'qiydi. Kamchiligi: **gallyutsinatsiya** — so'zni "tuzatib"
   yuborishi yoki o'qiy olmagan joyni o'ylab topishi mumkin; har sahifa uchun
   to'lov; sekinroq; rate-limit.

---

## 2. Variantlarni solishtirish (bizning loyiha uchun)

| Mezon | Tesseract (lokal) | Bulutli OCR API | Vision LLM (API) | GPU'dagi ochiq model |
|---|---|---|---|---|
| O'zbek kirill | ✅ `uzb_cyrl` | ⚠️ tekshirish kerak | ✅ yaxshi | ⚠️ modelga bog'liq |
| O'zbek lotin / rus | ✅ | ✅ | ✅ | ✅ |
| Narx | Bepul | ~$1.5 / 1000 sahifa | Model va tokenga bog'liq | Server ijarasi |
| Server talabi | Mavjud server, CPU | Yo'q | Yo'q | GPU server (≥16 GB VRAM) |
| Maxfiylik | Hujjat serverdan chiqmaydi | Tashqariga ketadi | Tashqariga ketadi | Ichkarida |
| Jadval / layout | Zaif | O'rtacha–yaxshi | Juda yaxshi | Yaxshi |
| Gallyutsinatsiya xavfi | Yo'q (xato bo'ladi, lekin uydirma emas) | Yo'q | **Bor** | Bor |
| Joriy etish murakkabligi | Past | Past | Past–o'rta | Yuqori |

**Tavsiya — gibrid, bosqichma-bosqich:**

1. **1-bosqich (hozir):** Tesseract 5, backend bilan bir serverda. Bepul,
   maxfiy, deterministik, `uzb_cyrl`/`uzb`/`rus` ni qo'llaydi — turizm
   darsliklari va me'yoriy hujjatlar (asosan toza bosma matn) uchun yetarli.
2. **2-bosqich (keyinroq):** xuddi shu Tesseract **alohida CPU serverga**
   ko'chiriladi — kitoblar ko'p bo'lgani uchun asosiy serverni bo'shatish.
3. **3-bosqich (ixtiyoriy):** past confidence chiqqan sahifalar uchun **Vision
   LLM fallback** (masalan, Gemini Flash — embedding uchun Gemini allaqachon
   ishlatilmoqda). Faqat yomon sahifalar yuboriladi → arzon.
4. GPU server — faqat juda katta hajm bo'lsa. Hozircha kerak emas.

Nega OCRmyPDF emas? OCRmyPDF (Tesseract ustidagi CLI) ajoyib vosita, lekin u
butun faylni qayta yozib, yangi PDF chiqaradi. Bizga sahifa darajasida nazorat
kerak: har sahifa confidence'i, progress, sahifa keshi, aralash PDF'da faqat
skan sahifalarni OCR qilish. Shuning uchun Tesseract'ni to'g'ridan-to'g'ri
chaqiramiz. (Tez prototip uchun OCRmyPDF `--skip-text` + mavjud `_parse_pdf`
ham ishlaydi — 1 kunlik yechim sifatida.)

---

## 3. Arxitektura — loyihaga qanday qo'shiladi

### 3.1. Oqim

```
_parse_pdf(path)
  1. har sahifa: text = page.extract_text()
                 needs_ocr(page, text)?  → ocr_pages ro'yxatiga
  2. ocr_pages dan keshda borlarini olib tashlash
  3. qolganlari → get_ocr_backend().ocr_pages(path, pages, langs, on_page)
                    on_page: keshga yozish + progress "OCR: 145/480"
  4. matnli sahifalar + OCR sahifalar → sahifa tartibida birlashtirish
     chunks.append(ParsedChunk(label=f"page {i}", text=text))
  → ParsedDocument(chunks, warnings, ocr_stats)
        │
        ▼
clean_text → ocr_cleanup (faqat OCR sahifalarga) → detect_script → to_latin
        │
        ▼
build_grounded_markdown  (o'zgarishsiz: label "page N", [MANBA: ...] bir xil)
```

Muhim: **grounding marker formati va frontmatter o'zgarmaydi.**
`tests/pipeline/test_chunker.py` frontmatter'da aynan 8 qator borligini
tekshiradi — bu kontrakt. OCR metama'lumotlari DB'da saqlanadi.

### 3.2. Yangi paket: `apps/pipeline/ocr/` — keyinroq ko'chirishga tayyor

Interfeys **sahifa-rasm** darajasida emas, **"shu PDF'ning shu sahifalarini
OCR qil"** darajasida bo'ladi. Sababi — keyingi alohida server: 500 sahifani
300 DPI rasm qilib tarmoqdan yuborish ~0.5 GB trafik; PDF'ni bir marta
yuborib, rasterizatsiyani OCR serverning o'zida qilish ancha arzon.

```
apps/pipeline/ocr/
├── base.py        # OcrBackend Protocol, PageResult, OcrError
├── local.py       # LocalBackend: pypdfium2 render + tesseract (hozir)
├── remote.py      # RemoteBackend: HTTP orqali OCR server (keyinroq)
├── tesseract.py   # tesseract CLI chaqiruvi, TSV → matn + confidence
├── detect.py      # needs_ocr, pdf_needs_ocr (tez tekshiruv), til tanlash
├── cache.py       # ocr-cache/<file_hash>/... o'qish-yozish
└── cleanup.py     # OCR'dan keyingi tozalash
```

```python
@dataclass(frozen=True)
class PageResult:
    page: int              # 1 dan boshlanadi
    text: str
    confidence: float      # 0..100, so'zlar bo'yicha o'rtacha
    engine: str            # "tesseract" | "remote:tesseract" | "vision-llm"

class OcrBackend(Protocol):
    def ocr_pages(
        self,
        pdf_path: Path,
        pages: list[int],
        languages: str,
        on_page: Callable[[PageResult], None],   # progress + kesh shu yerda
        cancel: threading.Event | None = None,
    ) -> None: ...

def get_ocr_backend() -> OcrBackend | None   # OCR_BACKEND=none|local|remote
```

- `on_page` callback har tayyor sahifada chaqiriladi → pipeline uni darhol
  keshga yozadi va progress'ni yangilaydi. Ikkala backend uchun bir xil.
- **Kesh backend'dan tashqarida** (asosiy serverda) turadi: OCR server
  o'zgarsa yoki o'chsa ham tayyor sahifalar yo'qolmaydi.
- Testlarda soxta backend qo'yiladi (xuddi `tests/owui/fake_owui.py` kabi) —
  Tesseract o'rnatilmagan CI ham ishlaydi.

### 3.3. Qaysi sahifa OCR'ga ketadi (`needs_ocr`)

1. Matn qatlami bo'sh yoki `< SPARSE_PAGE_THRESHOLD` (40) belgi **va** sahifada
   rasm bor (`page.images` yoki `/XObject /Image`).
2. Matn qatlami **buzuq**: harflar ulushi past, `�` ko'p, yoki so'zlar
   mantiqsiz (eski noto'g'ri OCR qatlami yoki buzilgan shrift kodirovkasi).
   Oddiy evristika: harf bo'lmagan belgilar > 30% → OCR.
3. Admin'dan **"OCR bilan majburan qayta ishlash"** bosilgan bo'lsa — barcha
   sahifalar.

### 3.4. Sahifani rasmga aylantirish

- **`pypdfium2`** — PDFium (Chrome'ning PDF dvigateli) bindingi; tayyor wheel,
  tizim paketi kerak emas, tez, shifrlangan PDF'larni ham ochadi.
  (`pdf2image` poppler-utils talab qiladi — kerak emas.)
- 300 DPI, **kulrang** (RGB'dan 3 baravar kam xotira): A4 ≈ 2480×3508 ≈ 8.7 MB.
- **Sahifama-sahifa** — hech qachon butun hujjatni xotiraga yuklamaslik.
  PM2'da `max_memory_restart: "1G"` turibdi; 300 sahifani birdan render qilish
  jarayonni o'ldiradi.

### 3.5. Tesseract chaqiruvi

```bash
tesseract page.png stdout -l uzb_cyrl+rus --oem 1 --psm 3 tsv
```

- `--oem 1` — faqat LSTM dvigateli.
- `tsv` chiqishi — har so'z bilan `conf` beradi → sahifa confidence'i.
- Rasm `stdin` orqali uzatiladi, vaqtinchalik fayl shart emas.
- `OMP_THREAD_LIMIT=1` — Tesseract'ning ichki OpenMP threadlarini o'chiramiz,
  parallellikni sahifalar darajasida o'zimiz boshqaramiz (aks holda
  `PIPELINE_CONCURRENCY × sahifa_worker × OpenMP` yadrolardan oshib, hammasi
  sekinlashadi).
- Har chaqiruvga `timeout` (masalan 120 s) — osilib qolgan sahifa butun
  pipeline'ni to'xtatmasin.
- `pytesseract` kutubxonasi shart emas — u ham `subprocess` wrapper. O'zimiz
  10–20 qatorda yozamiz va xatolarni o'zbekcha xabar bilan qaytaramiz.

### 3.6. Til tanlash strategiyasi

Ko'p tilni birga berish (`uzb_cyrl+uzb+rus+eng`) sekinlashtiradi va harflarni
aralashtiradi. Shuning uchun:

1. Birinchi 2–3 OCR sahifani `uzb_cyrl+rus` bilan o'qish.
2. Natijaga mavjud `detect_script()` ni qo'llash:
   - `uz-cyrl` → qolganlari `uzb_cyrl` (+ `rus` ehtiyot uchun);
   - `ru` → `rus`;
   - lotin → `uzb+eng`.
3. Tanlangan til material bo'yicha eslab qolinadi.

Shundan keyin oqim avvalgidek: o'zbek kirill → `to_latin`, rus → o'zgarishsiz.

### 3.7. OCR'dan keyingi tozalash (`ocr_cleanup`)

`clean_text` allaqachon tire bilan bo'lingan so'zlarni ulaydi
(`_HYPHEN_LINEBREAK`) va qatorlarni birlashtiradi. OCR uchun qo'shimcha:

- **Gomoglif aralashmasi**: kirill so'z ichida lotin `o a e c p x` (va
  aksincha) — OCR'ning eng tipik xatosi; translit va RAG qidiruvini buzadi.
  So'zning asosiy alifbosiga moslab almashtirish.
- **Kolontitul va sahifa raqamlari**: har sahifada takrorlanuvchi yuqori/pastki
  qatorlar (kitob nomi, bob, "— 14 —") — bir necha sahifada takrorlansa olib
  tashlash.
- Yakka "axlat" qatorlar (`|`, `~`, `»»` kabi, rasm qoldiqlari).
- Bu funksiyalar `regex` moduli bilan yoziladi (CLAUDE.md 5.5).

### 3.8. Sahifa keshi — qayta boshlashda yo'qotmaslik

OCR sekin (300 sahifa — bir necha daqiqadan yarim soatgacha). Server qayta
ishga tushsa, `recovery.py` materialni qayta navbatga qo'yadi va hammasi
noldan boshlanadi. Yechim:

```
UPLOADS_DIR/ocr-cache/<file_hash>/<lang>/page-0001.json   {text, confidence, engine}
```

- `materials.file_hash` allaqachon mavjud → kalit tayyor.
- Retry, "qayta ishlash", recovery — tayyor sahifalarni qayta OCR qilmaydi.
- Material o'chirilganda kesh ham o'chiriladi (`catalog/signals.py` yoki
  `services.delete_material`), boshqa material shu hash'ni ishlatmasa.

### 3.9. Navbat, parallellik va resurslar — katta kitoblar uchun

**Muammo:** hozir `runner` da bitta pool bor, `PIPELINE_CONCURRENCY=2`. Ikkita
400 sahifalik kitob yuklansa, ikkala worker ~30 daqiqa band bo'ladi va shu
vaqt ichida 5 sahifalik DOCX ham navbatda kutadi. Modulga 20 ta kitob
yuklansa — bir necha soat hamma narsa to'xtaydi.

**Yechim: ikki yo'lak (lane).**

```
runner.submit(material_id)
   │
   ├─ pdf_needs_ocr(raw_file)?  — birinchi ~5 sahifani tez tekshirish (ms)
   │
   ├─ yo'q → "default" pool  (PIPELINE_CONCURRENCY=2)  DOCX, PPTX, matnli PDF
   └─ ha   → "ocr" pool      (OCR_CONCURRENCY=1)       skan kitoblar
```

- Oddiy hujjatlar hech qachon kitoblar ortida kutmaydi.
- In-flight registry (`_pending` / `_running`) ikkala yo'lak uchun **umumiy**
  qoladi — bir material ikki marta ishlanmasligi kafolati saqlanadi.
- `recovery.py` va `queue_module_materials` o'zgarishsiz `runner.submit()` ni
  chaqiradi — yo'lakni `submit` o'zi tanlaydi.
- Material ichida sahifalar `OCR_PAGE_WORKERS` ta parallel. Tesseract —
  alohida jarayon (GIL muammo emas), `pypdfium2` render C kodida ishlaydi.
- CPU qoidasi (hozir, bir serverda):
  `OCR_CONCURRENCY × OCR_PAGE_WORKERS ≤ CPU yadrolari − 2`
  (2 yadro gunicorn, PostgreSQL va oddiy pipeline uchun qoladi).
  Masalan 8 vCPU: `1 × 6`; 4 vCPU: `1 × 2`.
- Kitoblar navbati **FIFO**, admin'da "OCR navbatida: 3 ta kitob, ~1 soat"
  ko'rinadi.
- Uzoq OCR davomida DB ulanishi ochiq turmaydi: progress qisqa `UPDATE`
  bilan yoziladi, `runner` dagi `close_old_connections()` qoidasi saqlanadi.
- **Bekor qilish:** admin'dan material o'chirilsa yoki "to'xtatish" bosilsa —
  `cancel` event o'rnatiladi, keyingi sahifadan oldin to'xtaydi (500 sahifani
  oxirigacha behuda o'qimaslik uchun).
- `OCR_MAX_PAGES=1000` — tasodifan yuklangan 3000 sahifalik arxivdan himoya.

**Keyinroq, alohida serverga o'tganda:** `ocr` yo'lagi faqat HTTP so'rov
yuborib kutadi, CPU asosiy serverda sarflanmaydi → `OCR_CONCURRENCY` ni
oshirish mumkin (OCR server quvvatiga qarab).

### 3.10. Model va admin o'zgarishlari

`Material` ga yangi ustunlar (migratsiya kerak, varchar/int/float — native enum
emas):

| Ustun | Turi | Ma'nosi |
|---|---|---|
| `extraction_method` | varchar: `text` / `ocr` / `mixed` | Matn qanday olingan |
| `ocr_page_count` | int, null | Nechta sahifa OCR qilingan |
| `ocr_confidence` | float, null | O'rtacha ishonch (0–100) |
| `progress_message` | varchar, null | "OCR: 45/300 sahifa" — admin'da jonli |

Status: yangi status qo'shmaymiz — `converting` qoladi, tafsilot
`progress_message` da. (Yangi status recovery, `IN_PROGRESS_STATUSES`, API va
filtrlarning hammasiga ta'sir qiladi — foydasi kam.)

Admin (barcha matnlar o'zbekcha):

- Ro'yxatda `@display(label=...)` chip: **"OCR"** / **"Aralash"**, confidence
  past bo'lsa sariq.
- Material sahifasida: OCR sahifalar soni, confidence, past ishonchli
  sahifalar ro'yxati (audit log'dan).
- Action: **"OCR bilan qayta ishlash"** (force OCR, kesh e'tiborsiz).
- Dashboard: "OCR kutayotgan / OCR qilingan" hisoblagichlari (ixtiyoriy).

Audit log (`stage="ocr"`): boshlanish, har 10–25 sahifada progress, past
confidence sahifalar (`WARN`), tugash statistikasi.

### 3.11. Sozlamalar (`config/settings.py` → `OcrConfig` dataclass)

CLAUDE.md 5.1: env faqat `settings.py` da o'qiladi, kod `ocr_config()` dan
foydalanadi. `.env.example` va `README.md` ga ham qo'shiladi.

```dotenv
# --- OCR ------------------------------------------------------------------
# none | local | remote
#   none   — skan sahifalar avvalgidek ogohlantirish bilan o'tadi.
#   local  — tesseract shu serverda ishlaydi (hozirgi rejim).
#   remote — alohida OCR serverga yuboriladi (keyingi rejim).
OCR_BACKEND=local
# Birinchi sahifalar shu tillar bilan o'qiladi, keyin yozuvga qarab toraytiriladi.
OCR_LANGUAGES=uzb_cyrl+rus
OCR_DPI=300
# Bir vaqtda nechta kitob OCR qilinadi (alohida navbat, oddiy hujjatlarni to'smaydi).
OCR_CONCURRENCY=1
# Bitta kitob ichida parallel OCR qilinadigan sahifalar (faqat local rejimda).
# Qoida: OCR_CONCURRENCY × OCR_PAGE_WORKERS ≤ CPU yadrolari − 2.
OCR_PAGE_WORKERS=2
# Bir sahifaga ajratilgan eng ko'p vaqt (soniya).
OCR_PAGE_TIMEOUT_SECONDS=120
# Bundan past ishonchli sahifa audit log'ga WARN bo'lib tushadi (0–100).
OCR_MIN_CONFIDENCE=60
# Juda katta skanlardan himoya: bundan ko'p sahifa bo'lsa rad etiladi.
OCR_MAX_PAGES=1000
# Ixtiyoriy: tessdata_best modellari joyi (local rejim).
TESSDATA_PREFIX=
# remote rejim: OCR server manzili va tokeni.
OCR_REMOTE_URL=
OCR_REMOTE_TOKEN=
# 3-bosqich: past ishonchli sahifalar uchun vision LLM (bo'sh — o'chiq).
OCR_FALLBACK_ENGINE=
OCR_FALLBACK_API_KEY=
```

`python manage.py check` da **system check** (`apps/pipeline/checks.py`):
`local` bo'lib `tesseract` yoki kerakli til paketi topilmasa, `remote` bo'lib
`OCR_REMOTE_URL`/`OCR_REMOTE_TOKEN` bo'sh bo'lsa — warning. Runtime'da tushunarli
xato: "Tesseract o'rnatilmagan" / "OCR serveriga ulanib bo'lmadi".

---

## 4. Serverlar — hozir bir serverda, keyin alohida

### 4.0. Hajm hisobi (200–500 sahifalik kitoblar)

Tesseract, 300 DPI, toza kitob sahifasi, 1 yadro: **~2–6 s/sahifa**
(`uzb_cyrl+rus` sekinroq, bitta til tezroq). O'rtacha 4 s deb olamiz:

| Sahifa | 1 yadro | 2 parallel | 6 parallel | 16 parallel |
|---|---|---|---|---|
| 200 | ~13 daq | ~7 daq | ~2–3 daq | ~1 daq |
| 350 | ~23 daq | ~12 daq | ~4 daq | ~1.5 daq |
| 500 | ~33 daq | ~17 daq | ~6 daq | ~2 daq |
| 20 kitob × 350 = 7000 | ~8 soat | ~4 soat | ~1.3 soat | ~30 daq |

Bu taxmin — 6-bo'lim, 0-qadamda haqiqiy kitoblarimizda o'lchanadi.

Fayl hajmi: 300 DPI skan kitob odatda **50–400 MB**. Hozirgi limitlar
(`MAX_UPLOAD_MB=200`, nginx `client_max_body_size 210m`) katta kitoblarni rad
etadi → ikkalasini **500 MB / 510m** ga ko'tarish kerak; nginx
`proxy_read_timeout` va gunicorn `--timeout 300` sekin internetda 500 MB
yuklash uchun yetarliligini tekshirish kerak.

Disk: 100 ta kitob × ~200 MB ≈ 20 GB xom fayl (`uploads/raw`). OCR kesh va
Markdown — ahamiyatsiz (kitobga bir necha MB).

### 4.1. 1-bosqich (hozir): backend bilan bir serverda — `OCR_BACKEND=local`

Alohida server **kerak emas**. Tesseract — oddiy tizim dasturi.

```bash
sudo apt install -y tesseract-ocr \
    tesseract-ocr-uzb tesseract-ocr-uzb-cyrl \
    tesseract-ocr-rus tesseract-ocr-eng
tesseract --version
tesseract --list-langs     # uzb, uzb_cyrl, rus, eng ko'rinishi kerak
```

Python paketlari (`uv add`): `pypdfium2`, `Pillow`. (Deskew uchun keyinchalik
`opencv-python-headless` — faqat sifat yetmasa.)

Server talabi (katta kitoblar bilan):

| | Minimal | Tavsiya |
|---|---|---|
| CPU | 4 vCPU (`OCR_PAGE_WORKERS=2`) | 8 vCPU (`OCR_PAGE_WORKERS=6`) |
| RAM | 8 GB | 16 GB |
| Disk | +20 GB bo'sh | +50 GB |

Bitta OCR sahifa jarayoni ~100–300 MB xotira (render + tesseract).

Deploy o'zgarishlari:
- `Dockerfile` runtime bosqichida `apt-get install` ga yuqoridagi paketlar
  (~60–100 MB).
- `DEPLOY.md` 1-bo'limiga `apt install` qatori.
- `.env`: `MAX_UPLOAD_MB=500`, nginx `client_max_body_size 510m`.
- PM2 `max_memory_restart: "1G"` faqat gunicorn jarayonini o'lchaydi;
  tesseract alohida jarayon. Render qilingan rasmlar esa gunicorn xotirasida —
  shuning uchun sahifama-sahifa ishlash shart.

Bu bosqichning cheklovi: OCR asosiy server CPU'sini yeydi. Ko'p kitob
yuklanganda admin panel va Open WebUI (agar shu serverda bo'lsa) sekinlashadi.
`OCR_PAGE_WORKERS` ni kamaytirish — sekinroq, lekin xavfsiz.

### 4.2. 2-bosqich (keyinroq): alohida OCR server — `OCR_BACKEND=remote`

**Qachon o'tish kerak** (birortasi bajarilsa):
- OCR navbati doim 1 soatdan uzun;
- OCR paytida admin panel / Open WebUI sezilarli sekinlashadi;
- yuzlab kitob bir vaqtda kelishi kutilmoqda.

**Arxitektura:**

```
 Asosiy server (Django)                     OCR server
 ┌──────────────────────────┐   HTTPS    ┌──────────────────────────────┐
 │ runner "ocr" yo'lagi     │ ─────────► │ ocr-service (FastAPI)        │
 │  RemoteBackend           │  PDF + job │  ichki navbat                │
 │  ↳ on_page → kesh, DB    │ ◄───────── │  pypdfium2 + tesseract       │
 │                          │  sahifalar │  N ta parallel sahifa        │
 └──────────────────────────┘            └──────────────────────────────┘
```

OCR servis API (kichik, holatsiz bo'lishi mumkin):

| So'rov | Vazifa |
|---|---|
| `POST /jobs` (multipart: pdf, `pages`, `languages`, `dpi`) | Ish yaratadi → `{job_id}` |
| `GET /jobs/{id}?after=<page>` | Holat + `after` dan keyingi tayyor sahifalar (`text`, `confidence`) |
| `DELETE /jobs/{id}` | Bekor qilish (material o'chirilganda) |
| `GET /health` | Tesseract versiyasi, tillar, navbat uzunligi |

- Auth: `Authorization: Bearer OCR_REMOTE_TOKEN`; server faqat asosiy server
  IP'sidan yoki VPN/ichki tarmoq orqali ochiq.
- `RemoteBackend` har bir necha soniyada `GET /jobs/{id}?after=N` qiladi va
  har yangi sahifa uchun `on_page` ni chaqiradi — kesh va progress xuddi local
  rejimdagidek ishlaydi.
- Tarmoq uzilsa yoki OCR server qayta ishga tushsa: keshdagi sahifalar
  saqlangan, yangi job faqat qolgan sahifalar bilan yaratiladi.
- Bir xil `file_hash` uchun PDF qayta yuborilmasligi uchun `POST /jobs`
  `file_hash` ni qabul qilib, server o'zida PDF bo'lsa yuklashni o'tkazib
  yuborishi mumkin (ixtiyoriy optimallashtirish).
- OCR servis kodi shu repoda `ocr_service/` papkasida (alohida
  `Dockerfile`), `apps/pipeline/ocr/tesseract.py` va render kodini qayta
  ishlatadi — mantiq ikki joyda takrorlanmaydi.

**OCR server talabi** (faqat CPU, GPU kerak emas):

| | Boshlang'ich | Katta hajm |
|---|---|---|
| CPU | 8 vCPU (CPU-optimized) | 16–32 vCPU |
| RAM | 16 GB | 32 GB |
| Disk | 50 GB (vaqtinchalik PDF'lar) | 100 GB |
| 500 sahifalik kitob | ~5 daqiqa | ~1–2 daqiqa |

Gorizontal kengayish: bir nechta OCR server + oddiy load balancer — API
holatsiz bo'lsa (job PDF'i bilan bitta serverda yashaydi), sticky routing
`job_id` bo'yicha.

**Ko'chirish tartibi (downtime'siz):**
1. OCR serverni ko'tarish, `GET /health` tekshirish.
2. Staging'da `OCR_BACKEND=remote` bilan 2–3 kitobni sinash; natijani local
   rejim natijasi bilan solishtirish (bir xil Tesseract versiyasi va tillar →
   matn deyarli bir xil bo'lishi kerak).
3. Prod `.env` da `OCR_BACKEND=remote`, gunicorn restart. Yarim qolgan
   kitoblar `recovery.py` orqali qayta navbatga tushadi va keshdan davom etadi.
4. Asosiy serverda `OCR_CONCURRENCY` ni oshirish (CPU endi band emas).
5. Bir necha hafta barqaror ishlagach — asosiy serverdan tesseract paketlarini
   olib tashlash ixtiyoriy (`local` rejimga qaytish imkoni uchun qoldirgan ma'qul).

### 4.3. Boshqa variantlar (hozir kerak emas)

- **GPU server** — ochiq vision modellar (Qwen2.5-VL, olmOCR, Surya), ≥16 GB
  VRAM (L4 / A10 / RTX 4090), vLLM orqali. Faqat juda katta hajm va yuqori
  sifat talabi bo'lsa. `OcrBackend` interfeysi bunga ham mos keladi.
- **Bulut API / Vision LLM** — server kerak emas. 3-bosqichdagi past
  confidence sahifalar uchun fallback sifatida. Hujjat tashqi provayderga
  ketadi — buyurtmachi bilan kelishish kerak.

## 5. Testlar

CLAUDE.md 5.8 ga mos:

- **Unit (Tesseract'siz, CI'da ham ishlaydi)** — `tests/pipeline/test_ocr.py`:
  - `needs_ocr`: bo'sh sahifa, siyrak sahifa, buzuq qatlam, oddiy matnli sahifa.
  - Soxta `OcrBackend` bilan `_parse_pdf`: aralash PDF'da faqat skan sahifalar
    OCR'ga boradi, label'lar `page N` tartibini saqlaydi.
  - Kesh: ikkinchi chaqiruvda engine chaqirilmaydi.
  - Til tanlash: kirill natija → keyingi sahifalar `uzb_cyrl`.
  - `ocr_cleanup`: gomogliflar, kolontitul, axlat qatorlar.
  - `OCR_BACKEND=none` — avvalgi xatti-harakat (ogohlantirish, `failed`).
  - `runner`: OCR kerak PDF `ocr` yo'lagiga, DOCX va matnli PDF `default` ga tushadi; bir material ikki yo'lakda ham ikki marta ishlanmaydi.
  - Bekor qilish: `cancel` o'rnatilgach keyingi sahifa OCR qilinmaydi.
  - `RemoteBackend` (2-bosqich): `httpx.MockTransport` bilan soxta OCR server — sahifalar bo'laklab kelishi, uzilishdan keyin keshdan davom etish.
- **Integratsion (Tesseract bo'lsa)** — `@pytest.mark.skipif(shutil.which("tesseract") is None)`:
  test ichida Pillow bilan o'zbek kirill matnli rasm chizib, PDF qilib saqlash
  (matn qatlamisiz) → pipeline → Markdown'da lotincha matn va `[MANBA: ... | page 1 | ...]`.
- **Pipeline/service** — `PIPELINE_RUN_SYNC=true`: skan PDF yuklanganda status
  `md_ready`/`indexed`, `extraction_method="ocr"`, audit log'da `ocr` yozuvlari.
- **Admin** — `tests/admin/` yangi ustun va action bilan barcha sahifalar
  render bo'lishi.
- Mavjud `tests/pipeline/*` kontrakt testlari o'zgarmasdan o'tishi kerak.

---

## 6. Ish rejasi (qadamlar)

### 1-bosqich — bir serverda (hozir)

| # | Qadam | Natija | Taxminiy vaqt |
|---|---|---|---|
| 0 | **Tajriba.** 5–10 ta haqiqiy skan kitob (200–500 sahifa; kirill, lotin, rus, yomon sifatli). Lokalda `tesseract` bilan 20–30 sahifani qo'lda o'qish: til kombinatsiyalari, DPI 200/300, `tessdata` vs `tessdata_best`. **Sahifa/soniya va sifatni yozib qo'yish** — 4.0 dagi jadval shu raqamlar bilan yangilanadi. | Tezlik, til strategiyasi, server talabi tasdiqlanadi | 1 kun |
| 1 | `OcrConfig` + settings + `.env.example` + README + system check | Sozlama tayyor | 0.5 kun |
| 2 | `apps/pipeline/ocr/`: `OcrBackend` Protocol, `LocalBackend` (pypdfium2 + tesseract TSV + confidence + timeout + cancel), `needs_ocr` / `pdf_needs_ocr`, til tanlash | OCR paketi + unit testlar | 1.5 kun |
| 3 | `_parse_pdf` integratsiyasi: aralash PDF, sahifa parallelligi, `ParsedDocument` ga OCR statistikasi | Skan PDF → Markdown | 1 kun |
| 4 | Sahifa keshi (`ocr-cache/<file_hash>`), o'chirishda tozalash, bekor qilish | Restart/retry'da qayta OCR yo'q | 0.5 kun |
| 5 | `runner` da ikki yo'lak (`default` / `ocr`), umumiy in-flight registry | Kitoblar oddiy hujjatlarni to'smaydi | 1 kun |
| 6 | `ocr_cleanup` (gomoglif, kolontitul, axlat) | Toza matn, ishlaydigan translit | 1 kun |
| 7 | Model ustunlari + migratsiya, progress, audit log, admin: chip, "OCR bilan qayta ishlash", "to'xtatish", OCR navbati | Operator OCR'ni ko'radi va boshqaradi | 1 kun |
| 8 | Dockerfile, `DEPLOY.md`, upload limiti 500 MB (Django + nginx), serverga paket o'rnatish, staging'da 2–3 to'liq kitob bilan sinov | Prod'ga tayyor | 0.5–1 kun |

1-bosqich: taxminan **8–9 ish kuni**.

**Bajarilgani (2026-10-02):** 1–8-qadamlar. Rejadan farqlar:

- Paket `apps/pipeline/ocr/` (`base`, `local`, `tesseract`, `detect`, `cache`,
  `cleanup`, `document`); `remote.py` 2-bosqichda qo'shiladi.
- `OCR_BACKEND` hozircha `none | local`; `OCR_REMOTE_*` 2-bosqichda.
- Standart `OCR_LANGUAGES=uzb+uzb_cyrl+rus` (lotin kitoblar ham to'g'ri
  aniqlanishi uchun `uzb` qo'shildi), `OCR_AUTO_LANGUAGE=true`.
- "OCR bilan qayta ishlash" — `materials.force_ocr` bayrog'i (saqlanib qoladi)
  va keshni tozalash; "To'xtatish" — `runner.cancel()`.
- Sahifa rasmi Tesseract'ga PNG emas, siqilmagan kulrang PNM sifatida stdin
  orqali beriladi (siqish vaqti yo'q).
- Kesh, til tanlash va tozalashdan tashqari OCR natijasidagi tutuq belgilari
  (`' ` ʻ ʼ ’`) `to_latin` shakliga keltiriladi: `o‘`, `g‘`, `ʼ`.
- PDF fayl handle orqali o'qiladi (yo'l bilan ochilsa pypdf butun faylni
  xotiraga oladi), PM2/Docker'da `MALLOC_ARENA_MAX=2`.

**Lokal o'lchov (2026-10-02, sun'iy skan, haqiqiy kitob emas).** Tesseract
4.1.1, laptop i5-1235U (2 P + 8 E yadro). Sahifalar Noto Serif 12 pt, 300 DPI,
qiyshiqlik, xiralik, dog'lar va JPEG bilan "skanerlangan":

| | O'zbek kirill | O'zbek lotin | Rus |
|---|---|---|---|
| Asl matnga o'xshashlik | 99.9–100% | 99.5% | 99.3–99.6% |
| Tesseract ishonchi | 95.5% | 95.3% | 94.7% |
| Aniqlangan til | `uzb_cyrl` | `uzb` | `rus` |

| `OCR_PAGE_WORKERS` | s/sahifa | 500 sahifa | Python xotirasi (eng ko'p) |
|---|---|---|---|
| 1 | 1.86 | ~15 daq | — |
| 2 | 1.44 | ~12 daq | 287 MB |
| 4 | 1.03 | ~9 daq | — |
| 8 | 0.75 | ~6 daq | 644 MB → 357 MB (`MALLOC_ARENA_MAX=2`) |

Har bir tesseract jarayoni ~85 MB va bitta yadro oladi. Laptopda kengayish
sust — shell'dan to'g'ridan-to'g'ri ishga tushirilgan tesseract ham shunday
(protsessor chastotasi tushadi); kod ulushi ~5–15%. Server CPU'larida yaxshiroq
bo'lishi kutiladi.

- **0-qadam qolgan:** prod serverda haqiqiy kitoblar (yomon skan, jadval,
  ikki ustun) bilan o'lchash va `OCR_PAGE_WORKERS` ni yadrolarga moslash.

### 2-bosqich — alohida OCR server (keyinroq)

| # | Qadam | Taxminiy vaqt |
|---|---|---|
| 9 | `ocr_service/` (FastAPI): `/jobs`, `/health`, ichki navbat, `apps/pipeline/ocr` kodini qayta ishlatish, alohida Dockerfile | 1.5–2 kun |
| 10 | `RemoteBackend`: job yaratish, `after=N` bilan so'rash, uzilishdan keyin davom etish, bekor qilish; soxta server bilan testlar | 1 kun |
| 11 | OCR server deploy (8 vCPU / 16 GB), token, firewall, monitoring; 4.2 dagi ko'chirish tartibi | 1 kun |

### 3-bosqich — ixtiyoriy

| # | Qadam | Taxminiy vaqt |
|---|---|---|
| 12 | Past confidence sahifalar uchun Vision LLM fallback | 1–2 kun |

Har qadam oxirida CLAUDE.md 7-bo'limdagi tekshiruvlar: `manage.py check`,
`makemigrations --check`, `ruff check .`, `pytest`, `spectacular` warningsiz.

---

## 7. Xavflar va ularga yechim

| Xavf | Yechim |
|---|---|
| Kitoblar navbati soatlab cho'ziladi | Alohida `ocr` yo'lagi (oddiy hujjatlar kutmaydi), progress va navbat admin'da ko'rinadi; doimiy bo'lsa → 2-bosqich (alohida server) |
| OCR asosiy server CPU'sini yeydi, admin sekinlashadi | `OCR_CONCURRENCY=1`, `OCR_PAGE_WORKERS ≤ yadrolar − 2`; 2-bosqichda to'liq hal bo'ladi |
| 500 MB fayl yuklanmaydi | `MAX_UPLOAD_MB=500`, nginx `client_max_body_size 510m`, timeout'larni tekshirish |
| Xotira oshib, PM2 jarayonni o'ldiradi | Sahifama-sahifa render, kulrang, rasmni darhol yopish |
| Server restart 500 sahifalik OCR'ni yarmida uzadi | Sahifa keshi + mavjud `recovery.py` → tayyor sahifalardan davom etadi |
| OCR server ishlamay qoladi (2-bosqich) | Kesh asosiy serverda; `OCR_BACKEND=local` ga vaqtincha qaytish mumkin; `/health` monitoring |
| Yomon skan → axlat matn KB'ga tushadi | Confidence chegarasi, WARN audit, admin'da ko'rinadi; juda past sahifani chiqarib tashlash yoki LLM fallback |
| Kirill/lotin harflar aralashadi | Til strategiyasi (3.6) + gomoglif tozalash (3.7) |
| Jadvallar buziladi | 1-bosqichda qabul qilinadi; kerak bo'lsa LLM fallback (Markdown jadval) |
| LLM matnni "o'ylab topadi" | LLM faqat fallback, natija `engine="vision-llm"` bilan belgilanadi, prompt: "faqat ko'ringan matnni ko'chir, tuzatma" |
| Katta kitob KB'ga embedding paytida rate-limit'ga uchraydi | Mavjud retry mexanizmi (`add_file_to_knowledge_base`); 500 sahifa ≈ 1–1.5 mln belgi — `OWUI_INDEX_TIMEOUT_MS` yetishini staging'da tekshirish |
| Tesseract serverda yo'q | System check warning + tushunarli xato, `OCR_BACKEND=none` bilan eski xatti-harakat |

---

## 8. Ochiq savollar

1. Hozirgi prod serverda nechta vCPU / RAM bor, va Open WebUI ham shu serverdami? — `OCR_PAGE_WORKERS` shunga qarab tanlanadi.
2. Taxminan nechta kitob kutilmoqda (birinchi import va keyin oyiga)? — 2-bosqich qachon kerakligini aniqlaydi.
3. Hujjatlarni tashqi API'ga (Gemini va h.k.) yuborish mumkinmi? — 3-bosqich shunga bog'liq.
4. Kitoblar asosan qaysi tilda: o'zbek kirill, lotin yoki rus?
5. Eng katta skan fayl necha MB? — upload limiti shunga moslanadi.
6. Jadval va rasmlardagi matn muhimmi yoki faqat asosiy matn yetarlimi?
