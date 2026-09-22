# AGENTS.md — AI Agent Turizm Backend

Bu loyiha **AI Agent Turizm** ta'lim tizimining backend API'si, boshqaruv
paneli va hujjat ingestion pipeline'i. Backend ham, adminka ham bitta Python
loyihasida.

**Stack:** Python 3.12 · Django 5 · Django REST Framework · PostgreSQL ·
Django Admin (django-unfold) · SimpleJWT · drf-spectacular · pytest · Ruff · uv

---

## Asosiy hujjatlar

| Fayl | Nima uchun |
| --- | --- |
| [`CLAUDE.md`](CLAUDE.md) | **Yagona haqiqat manbai** — arxitektura, buyruqlar, kodlash standartlari, sifat ro'yxati |
| [`README.md`](README.md) | O'rnatish, API endpointlari, muhit o'zgaruvchilari, deploy |
| [`.agents/rules/architecture-rules.md`](.agents/rules/architecture-rules.md) | Django/DRF qatlamlari, papka tuzilishi, fon rejimi qoidalari |
| [`.agents/rules/database-rules.md`](.agents/rules/database-rules.md) | Jadval/ustun nomlari, DDL, indekslar, o'chirish siyosati |
| [`.agents/rules/pipeline-rules.md`](.agents/rules/pipeline-rules.md) | `[MANBA: ...]` grounding, transliteratsiya, OWUI protokoli |

> Har qanday o'zgarishdan oldin `CLAUDE.md` dagi **Quality Checklist** bo'limini
> o'qing — barcha tekshiruvlar shu yerda.

---

## Tizim nima qiladi

```
┌────────────────────────────────────────────────────────┐        HTTP REST        ┌─────────────────────────────────┐
│          Django Backend + Admin (bu loyiha)            │ ──────────────────────> │           Open WebUI            │
│  Modullar  ─►  Mavzular  ─►  Materiallar (PDF, PPTX)   │                         │        (ai-agent-turizm)        │
│  • O'zbek kirill -> lotin transliteratsiyasi           │                         │  • Knowledge Bases (KB)         │
│  • [MANBA: ...] grounding markerlari (~600 belgi)      │                         │  • Vector Search (RAG)          │
│  • PostgreSQL + fon rejimidagi pipeline                │                         │  • AI Agent / Chat              │
│  • /admin — Unfold paneli, /api/docs — Swagger         │                         │                                 │
└────────────────────────────────────────────────────────┘                         └─────────────────────────────────┘
```

### Nega oldindan ishlov berish kerak

Xom PDF/PPTX'ni to'g'ridan-to'g'ri Open WebUI'ga yuklash **manba
ko'rsatilishini (grounding) yo'qotadi**. AI agent manbani aniq keltira olishi
uchun (masalan `Law_Constitution.pdf, 14-sahifa`) pipeline har **~600 belgida**
takrorlanuvchi manba tegini qo'shadi:

```markdown
[MANBA: Constitution.pdf | page 14 | topic-01 | literature]
```

Bundan tashqari pipeline:

1. **O'zbek kirill → lotin**: lotin yozuvidagi so'rovlar kirill hujjatlariga mos
   tushishi uchun avtomatik o'giradi. Rus tilidagi matn tegilmaydi.
2. **Buzilgan font/glifni tuzatish**: `final -ии` → `-ий`,
   `TO‘RTINChI` → `TO‘RTINCHI`.

---

## Tezkor buyruqlar

```bash
uv sync                                   # bog'liqliklar
python manage.py migrate                  # baza
python manage.py createsuperuser          # admin
python manage.py runserver 3005           # ishga tushirish

pytest                                    # testlar
ruff check .                              # lint
python manage.py check                    # tizim tekshiruvi
python manage.py makemigrations --check --dry-run
```

Eski (TypeORM/NestJS) bazasidan o'tish:

```bash
python manage.py adopt_legacy_schema --apply --drop-empty-users
python manage.py migrate --fake-initial
```
