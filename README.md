# AI Agent Turizm — Backend + Admin

**AI Agent Turizm** ta'lim tizimining backend API'si, boshqaruv paneli va hujjat
ingestion pipeline'i. Kontent ierarxiyasini (**Modullar → Mavzular → Materiallar**)
boshqaradi va xom hujjatlarni (PDF, PPTX, DOCX, TXT, MD) **Open WebUI** RAG
agentlari uchun grounding markerli Markdown bilim bazasiga aylantiradi.

**Stack:** Python 3.12 · Django 5 · Django REST Framework · PostgreSQL ·
Django Admin + [django-unfold](https://unfoldadmin.com/) · SimpleJWT ·
drf-spectacular · pytest · Ruff

> Backend ham, adminka ham bitta Python loyihasida — alohida frontend kerak emas.

---

## Pipeline nima uchun kerak

Open WebUI hujjatlarni vektor bazasi uchun bo'laklarga ajratadi va shu jarayonda
ikkita narsa buziladi. Bu servis matn indeksga yetib borgunga qadar ikkalasini
ham tuzatadi.

### 1. Manba grounding (`[MANBA: ...]`)

Vektor chunking atrofdagi kontekstni yo'qotadi, natijada javob qayerdan
kelganini ko'rsata olmaydi. Pipeline taxminan har **600 belgida** grounding
markerini takrorlaydi — shunda har bir vektor chunk o'z manbasini olib yuradi:

```markdown
[MANBA: Constitution.pdf | page 14 | topic-01 | literature]
```

Har bir hujjat YAML frontmatter bilan boshlanadi (`module_id`, `topic_id`,
`source`, `script`, `chunks`, …).

### 2. O'zbek transliteratsiyasi (`uz-cyrl` → `uz-latn`)

Lotin yozuvidagi so'rovlar kirill hujjatlariga mos kelmaydi. Pipeline yozuvni
aniqlaydi va o'zbek kirilini lotinga o'giradi; rus tilidagi matn o'zgarishsiz
qoladi. Yo'l-yo'lakay ikkita keng tarqalgan font nuqsoni tuzatiladi:

| Nuqson | Misol | Tuzatilgan |
| --- | --- | --- |
| So'z oxiridagi buzilgan digraf | `-ии` | `-ий` |
| Bosh harfli sarlavhada kichik digraf dumi | `TO‘RTINChI` | `TO‘RTINCHI` |

---

## Tezkor start

### 1. Bog'liqliklar

[uv](https://github.com/astral-sh/uv) bilan (tavsiya etiladi):

```bash
uv sync
```

yoki oddiy pip bilan:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Muhit o'zgaruvchilari

```bash
cp .env.example .env
```

### 3. PostgreSQL

```bash
docker compose up -d postgres
```

### 4. Baza sxemasi

**Toza baza uchun:**

```bash
python manage.py migrate
```

**Eski (TypeORM/NestJS) bazasi ustiga o'tish uchun** — avval sxemani moslang,
keyin mavjud jadvallarni "qabul qiling":

```bash
python manage.py adopt_legacy_schema              # rejani ko'rsatadi
python manage.py adopt_legacy_schema --apply --drop-empty-users
python manage.py migrate --fake-initial
```

`adopt_legacy_schema` nima qiladi: native PostgreSQL enum ustunlarini
`varchar` ga o'giradi (ma'lumot saqlanadi) va eski `users` jadvalini —
u bo'sh bo'lsa — o'chiradi, chunki unda Django auth ustunlari yo'q.
Agar `users` jadvalida qator bo'lsa, buyruq to'xtaydi va sizdan qaror kutadi.

### 5. Administrator yarating

```bash
python manage.py createsuperuser
```

### 6. Ishga tushiring

```bash
python manage.py runserver 3005
```

| Manzil | Nima |
| --- | --- |
| <http://localhost:3005/admin/> | **Boshqaruv paneli** (adminka) |
| <http://localhost:3005/api/> | Health check |
| <http://localhost:3005/api/docs> | Swagger / OpenAPI |

---

## Boshqaruv paneli

`/admin/` — loyihaning "front"i. django-unfold temasi: chap yon panel, qorong'i
rejim, Tailwind komponentlari.

| Sahifa | Nima bor |
| --- | --- |
| **Dashboard** | Modul/mavzu/material hisoblagichlari, oxirgi 2 haftalik yuklash grafigi, pipeline holati kesimi, modullar bo'yicha indekslash foizi, oxirgi xatoliklar |
| **Kontent daraxti** | Modul → mavzu → material ierarxiyasi bitta ekranda, qidiruv va holat nuqtalari bilan |
| **Hujjat yuklash** | Drag & drop, bir vaqtda bir nechta fayl, har biri uchun progress bar, yuklangandan keyin holat avtomatik yangilanadi |
| **Modullar** | Mavzular inline; qator tugmalari: *KB sinxronlash*, *barchasini qayta ishlash* |
| **Mavzular** | Materiallar inline ko'rinadi |
| **Materiallar** | Rangli holat chiplari; qator tugmalari: *Qayta ishlash*, *Markdown*. Ro'yxat konvertatsiya davom etayotganda o'zini yangilaydi. O'chirish diskdagi fayllarni va Open WebUI nusxasini ham tozalaydi |
| **Audit yozuvlari** | Faqat o'qish uchun pipeline tarixi |
| **Foydalanuvchilar** | Rollar va huquqlar |

Yon paneldagi havolalar `UNFOLD["SIDEBAR"]["navigation"]` da
([config/settings.py](config/settings.py)) sozlanadi — yangi sahifa qo'shsangiz,
uni shu ro'yxatga ham qo'shing.

---

## Auth va rollar

Adminka session auth'dan, API esa JWT'dan foydalanadi.

```bash
curl -X POST http://localhost:3005/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@turizm.uz","password":"..."}'
# -> {"access": "...", "refresh": "...", "user": {...}}

curl http://localhost:3005/api/modules -H "Authorization: Bearer <access>"
```

| Rol | Huquqlar |
| --- | --- |
| `admin` | Hammasi, jumladan o'chirish va foydalanuvchilarni boshqarish |
| `editor` | O'qish + yaratish/tahrirlash, o'chirishsiz |
| `viewer` | Faqat o'qish |

`/api/` (health) va `/api/docs` ochiq. Butun API'ni tokensiz ochish uchun
`API_REQUIRE_AUTH=false` (faqat lokal ishlash uchun).

---

## API endpointlari

| Metod | Yo'l | Tavsif |
| --- | --- | --- |
| `GET` | `/api/` | Health check |
| `POST` | `/api/auth/login` | Kirish (access + refresh + profil) |
| `POST` | `/api/auth/refresh` | Access tokenni yangilash |
| `POST` | `/api/auth/logout` | Refresh tokenni bekor qilish |
| `GET` `POST` | `/api/auth/me` | Profil / parolni almashtirish |
| `GET` … | `/api/auth/users` | Foydalanuvchilar CRUD (admin) |
| `GET` `POST` | `/api/modules` | Modullar ro'yxati / yaratish |
| `GET` `PATCH` `DELETE` | `/api/modules/{id}` | Modul tafsiloti / tahrir / o'chirish |
| `POST` | `/api/modules/{id}/kb` | Open WebUI KB yaratish / sinxronlash |
| `POST` | `/api/modules/{id}/process-all` | Modulning barcha materiallarini qayta ishlash |
| `GET` `POST` | `/api/topics` | Mavzular ro'yxati / yaratish |
| `GET` `PATCH` `DELETE` | `/api/topics/{id}` | Mavzu tafsiloti / tahrir / o'chirish |
| `GET` | `/api/materials` | Materiallar ro'yxati (filtrlar bilan) |
| `POST` | `/api/materials/upload` | Hujjat yuklash (multipart) |
| `GET` `DELETE` | `/api/materials/{id}` | Material tafsiloti / o'chirish |
| `GET` | `/api/materials/{id}/content` | Konvertatsiya qilingan Markdown |
| `POST` | `/api/materials/{id}/retry` | Pipeline'ni qayta ishga tushirish |
| `GET` | `/api/audit-logs` | Pipeline loglari |
| `GET` | `/api/owui/status` | Open WebUI ulanish diagnostikasi |
| `GET` | `/api/owui/knowledge-bases` | Open WebUI KB ro'yxati |

Ro'yxat qaytaruvchi endpointlar `{items, total, page, limit, totalPages}`
shaklida javob beradi; `?page=`, `?limit=`, `?search=` qo'llab-quvvatlanadi.
Har bir yo'l oxirgi `/` bilan ham, usiz ham ishlaydi.

---

## Muhit o'zgaruvchilari

| O'zgaruvchi | Standart | Vazifasi |
| --- | --- | --- |
| `APP_ENV` | `development` | Muhit nomi (health javobida ko'rinadi) |
| `DJANGO_DEBUG` | `APP_ENV==development` | Debug rejimi |
| `DJANGO_SECRET_KEY` | — | `DEBUG=False` da **majburiy** |
| `DJANGO_ALLOWED_HOSTS` | `*` (DEBUG'da) | Vergul bilan ajratilgan hostlar |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | — | HTTPS orqasida adminka uchun kerak |
| `PORT` | `8000` | HTTP port |
| `POSTGRES_*` | `localhost/postgres/turizm_db` | Baza ulanishi |
| `API_REQUIRE_AUTH` | `true` | API'ni token ostiga oladi |
| `JWT_ACCESS_MINUTES` / `JWT_REFRESH_DAYS` | `60` / `14` | Token muddati |
| `UPLOADS_DIR` | `<project>/uploads` | `raw/` va `ready/` shu yerda |
| `MAX_UPLOAD_MB` | `200` | Bundan kattasi HTTP 413 |
| `PIPELINE_CONCURRENCY` | `2` | Bir vaqtda konvertatsiya qilinadigan hujjatlar |
| `PIPELINE_RUN_SYNC` | `false` | Pipeline'ni fon o'rniga inline ishlatish |
| `OWUI_URL` / `OWUI_API_KEY` | — | Open WebUI integratsiyasi |
| `OWUI_TIMEOUT_MS` | `30000` | Open WebUI so'rovlari uchun taymaut |
| `CORS_ALLOW_ALL_ORIGINS` / `CORS_ALLOWED_ORIGINS` | `true` / — | Brauzerdan murojaat siyosati |
| `LANGUAGE_CODE` / `TIME_ZONE` | `uz` / `Asia/Tashkent` | Lokal sozlamalar |

> Knowledge Base identifikatori muhit o'zgaruvchisi emas: har bir modul o'zining
> KB'siga ega va u `modules.owui_kb_id` ustunida saqlanadi.

---

## Loyiha tuzilishi

```text
config/                     # Django loyihasi (settings, urls, admin site)
apps/
├── common/                 # Pagination, exception handler, permissions, filename utils
├── accounts/               # User modeli, JWT auth, foydalanuvchilar admini
├── catalog/                # Module / Topic / Material / AuditLog + API + adminka
│   ├── api/                # serializers.py, views.py
│   ├── services.py         # Yuklash, retry, o'chirish, KB sinxronlash
│   ├── admin.py            # Unfold ModelAdmin klasslari
│   ├── admin_views.py      # Kontent daraxti (uchala modelni qamraydi)
│   └── management/commands/adopt_legacy_schema.py
├── owui/                   # Open WebUI REST klienti va diagnostika endpointlari
└── pipeline/
    ├── services/           # parser.py, cleaner.py, translit.py, chunker.py
    ├── service.py          # Uchdan-uchgacha koordinator
    └── runner.py           # Fon rejimidagi ishlov (thread pool + in-flight registry)
templates/admin/            # Dashboard, kontent daraxti, yuklash formasi, Markdown
tests/                      # pytest: pipeline, API, auth, adminka oqimlari
```

---

## Ishlab chiqish

```bash
python manage.py check          # Tizim tekshiruvi
python manage.py makemigrations --check --dry-run
pytest                          # Barcha testlar
ruff check .                    # Lint
ruff format .                   # Formatlash
python manage.py spectacular --file schema.yml
```

---

## Ishlab chiqarishga chiqarish

```bash
export DJANGO_SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
docker compose up -d --build
```

Konteyner ichida migratsiyalar avtomatik bajariladi va statik fayllar image
qurilishida yig'iladi. Gunicorn bitta worker + bir nechta thread bilan ishlaydi:
ingestion navbati jarayon ichida saqlanadi, ikkinchi worker uni ikki marta
ishga tushirib yuborgan bo'lardi. Gorizontal masshtablash kerak bo'lsa,
pipeline'ni Celery/RQ ga ko'chiring.
