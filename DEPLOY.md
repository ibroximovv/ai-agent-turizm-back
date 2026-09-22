# Serverga o'rnatish — `admin-ai.ocomarket.uz`

Bu hujjat NestJS'dan Django'ga o'tishni **bir marta** bajarish tartibi va
keyingi har bir yangilanish uchun qisqa amaliyotni tavsiflaydi.

Barcha yo'llar `/var/www/ai-agent-turizm-back` deb olingan. Boshqa joyda bo'lsa,
`deploy/ecosystem.config.js` va nginx konfigidagi yo'llarni almashtiring.

> **Muhim:** bu loyiha bitta gunicorn worker'ida ishlashi shart. Konvertatsiya
> navbati jarayon ichida saqlanadi — ikkinchi worker bir materialni ikki marta
> ishlab, bir-birining natijasini buzadi. Parallellik threadlar orqali beriladi.

---

## 0. Oldindan zaxira

```bash
# Baza
pg_dump -U postgres turizm_db | gzip > ~/turizm_db_$(date +%F_%H%M).sql.gz

# Yuklangan hujjatlar (agar serverda bo'lsa)
tar czf ~/turizm_uploads_$(date +%F).tgz -C /var/www/ai-agent-turizm-back uploads

# Mavjud nginx konfigi
sudo cp /etc/nginx/sites-available/<eski-konfig> ~/nginx-eski.conf.bak
```

Migratsiya bazadagi enum ustunlarini o'zgartiradi va eski `users` jadvalini
o'chiradi — zaxirasiz boshlamang.

---

## 1. Tizim bog'liqliklari

```bash
# uv (Python muhitini ham o'zi o'rnatadi — tizim Python'i 3.12 bo'lishi shart emas)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc

# PM2 (agar hali yo'q bo'lsa)
npm install -g pm2

# psycopg uchun kerak bo'ladigan kutubxonalar
sudo apt update && sudo apt install -y libpq5
```

---

## 2. Eski NestJS jarayonini to'xtatish

```bash
pm2 list                      # eski app nomini aniqlang
pm2 stop <eski-nom>
pm2 delete <eski-nom>
pm2 save
```

Yangi jarayon ham **3005**-portni egallaydi, shuning uchun eskisi o'chirilmasa
gunicorn ko'tarilmaydi.

---

## 3. Kodni yangilash

```bash
cd /var/www/ai-agent-turizm-back
git fetch origin
git checkout main
git reset --hard origin/main
```

Eski `node_modules/` va `dist/` endi keraksiz:

```bash
rm -rf node_modules dist
```

---

## 4. `.env`

```bash
cp .env.example .env
nano .env
```

Production uchun majburiy o'zgarishlar:

```ini
APP_ENV=production
DJANGO_DEBUG=false
# Yangi kalit yarating — dasturchi mashinasidagisini ishlatmang:
#   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_SECRET_KEY=<yangi-uzun-kalit>
DJANGO_ALLOWED_HOSTS=admin-ai.ocomarket.uz
DJANGO_CSRF_TRUSTED_ORIGINS=https://admin-ai.ocomarket.uz

POSTGRES_HOST=localhost
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<serverdagi-parol>
POSTGRES_DB=turizm_db

UPLOADS_DIR=/var/www/ai-agent-turizm-back/uploads
MAX_UPLOAD_MB=200

API_REQUIRE_AUTH=true
CORS_ALLOW_ALL_ORIGINS=false
CORS_ALLOWED_ORIGINS=https://admin-ai.ocomarket.uz

OWUI_URL=https://ai.ocomarket.uz
OWUI_API_KEY=<kalit>
```

Faylni faqat o'zingiz o'qiy oladigan qiling:

```bash
chmod 600 .env
```

---

## 5. Bog'liqliklar va baza

```bash
uv sync --no-dev
```

### Baza — eski TypeORM sxemasi ustiga

Serverdagi baza NestJS tomonidan yaratilgan bo'lsa, avval uni Django uchun
moslash kerak:

```bash
# 1. Nima o'zgarishini ko'ring (hech narsa bajarilmaydi)
.venv/bin/python manage.py adopt_legacy_schema

# 2. Bajaring
.venv/bin/python manage.py adopt_legacy_schema --apply --drop-empty-users

# 3. Mavjud jadvallarni "qabul qiling"
.venv/bin/python manage.py migrate --fake-initial
```

Buyruq native PostgreSQL enum ustunlarini `varchar` ga o'giradi (ma'lumot
saqlanadi) va eski `users` jadvalini o'chiradi — unda Django auth ustunlari
yo'q. **Agar `users` jadvalida qatorlar bo'lsa, buyruq to'xtaydi** va sizdan
qaror kutadi; u holda avval o'sha foydalanuvchilarni qayerga ko'chirishni
hal qiling.

### Baza toza bo'lsa

```bash
.venv/bin/python manage.py migrate
```

### Administrator

```bash
.venv/bin/python manage.py createsuperuser
```

---

## 6. Statik fayllar

```bash
.venv/bin/python manage.py collectstatic --noinput
mkdir -p logs uploads
```

nginx `staticfiles/` ni to'g'ridan-to'g'ri o'qiydi, shuning uchun papka
`www-data` uchun o'qilishi kerak:

```bash
sudo chown -R $USER:www-data /var/www/ai-agent-turizm-back
sudo chmod -R u=rwX,g=rX,o= /var/www/ai-agent-turizm-back
sudo chmod -R u=rwX,g=,o= /var/www/ai-agent-turizm-back/uploads   # hujjatlar yopiq
```

---

## 7. PM2

```bash
pm2 start deploy/ecosystem.config.js
pm2 save
pm2 startup          # chiqqan buyruqni nusxalab, sudo bilan bajaring
```

Tekshirish:

```bash
pm2 status
curl -s http://127.0.0.1:3005/api/      # {"status":"ok", ...} qaytishi kerak
pm2 logs turizm-back --lines 50
```

---

## 8. nginx

```bash
sudo cp deploy/nginx/admin-ai.ocomarket.uz.conf \
        /etc/nginx/sites-available/admin-ai.ocomarket.uz
sudo ln -s /etc/nginx/sites-available/admin-ai.ocomarket.uz /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t` xato bersa, `sites-enabled/` da shu domen uchun **eski** konfig
qolmaganini tekshiring (`ls -l /etc/nginx/sites-enabled/`).

Konfigdagi eng muhim ikki satr:

- `client_max_body_size 210m;` — busiz nginx 200 MB'lik PDF'ni Django'ga
  yetkazmasdan **413** qaytaradi;
- `proxy_set_header X-Forwarded-Proto $scheme;` — busiz adminkadagi har qanday
  forma yuborish **CSRF xatosi** bilan rad etiladi.

---

## 9. HTTPS

DNS'da `admin-ai.ocomarket.uz` shu serverga qarab turganiga ishonch hosil
qiling, so'ng:

```bash
sudo certbot --nginx -d admin-ai.ocomarket.uz
```

Certbot 443-blokini va http → https yo'naltirishni o'zi qo'shadi.
Sertifikat yangilanishini tekshirish:

```bash
sudo certbot renew --dry-run
```

HTTPS bir necha hafta barqaror ishlagach, `.env` da `SECURE_HSTS_SECONDS=2592000`
qilib qo'yishingiz mumkin (ilgari emas — HSTS'ni orqaga qaytarish qiyin).

---

## 10. Yakuniy tekshirish

```bash
curl -I https://admin-ai.ocomarket.uz/api/
curl -s https://admin-ai.ocomarket.uz/api/ | head
```

Brauzerda:

| Manzil | Kutilayotgan natija |
| --- | --- |
| `https://admin-ai.ocomarket.uz/admin/` | Unfold login sahifasi, keyin dashboard |
| `https://admin-ai.ocomarket.uz/api/docs` | Swagger |
| `https://admin-ai.ocomarket.uz/admin/catalog/material/upload/` | Drag & drop forma |

Open WebUI ulanishini adminkadan tekshiring yoki:

```bash
curl -s https://admin-ai.ocomarket.uz/api/owui/status \
     -H "Authorization: Bearer <token>"
```

Kichik `.txt` fayl yuklab ko'ring — holat `indexed` ga yetsa, butun zanjir
(konvertatsiya → transliteratsiya → grounding → Open WebUI) ishlayapti.

---

## Keyingi yangilanishlar

```bash
cd /var/www/ai-agent-turizm-back
./deploy/deploy.sh
```

Skript: `git reset --hard origin/main` → `uv sync` → `check --deploy` →
migratsiya drift tekshiruvi → `migrate` → `collectstatic` → `pm2 restart` →
health check. Biror qadam yiqilsa to'xtaydi va orqaga qaytarish buyrug'ini
chiqaradi.

Boshqa branch'dan deploy qilish:

```bash
BRANCH=dev ./deploy/deploy.sh
```

---

## Bilib qo'yish kerak bo'lgan narsalar

**Qayta ishga tushirish yarim yo'ldagi konvertatsiyani to'xtatadi.**
`pm2 restart` jarayonni o'ldiradi, u bilan birga fon threadlari ham ketadi.
Bunday materiallar bazada `converting` holatida qolib ketadi. `deploy.sh`
ularning sonini xabar qiladi — adminkadan tanlab **"Pipeline'ni qayta ishga
tushirish"** amalini bajaring.

**Nega bitta worker?** Navbat va "hozir ishlanmoqda" ro'yxati jarayon
xotirasida (`apps/pipeline/runner.py`). Ikkinchi worker o'z nusxasiga ega
bo'lar va bir material ikki marta konvertatsiya qilinib, natijalar bir-birini
qoplar edi. Gorizontal masshtablash kerak bo'lganda pipeline'ni avval
Celery/RQ ga ko'chirish lozim.

**Loglar:**

```bash
pm2 logs turizm-back              # ilova
sudo tail -f /var/log/nginx/turizm-error.log
```

**Orqaga qaytarish:**

```bash
cd /var/www/ai-agent-turizm-back
git reset --hard <oldingi-commit>
uv sync --no-dev
.venv/bin/python manage.py collectstatic --noinput
pm2 restart turizm-back
```

Migratsiyalar avtomatik orqaga qaytmaydi — sxema o'zgargan bo'lsa,
`migrate <app> <oldingi_migratsiya>` yoki baza zaxirasidan tiklang.
