# PharmaRef - Повна документацiя

## Огляд проєкту

**PharmaRef** - веб-додаток для пошуку iнформацiї про лiкарськi засоби України та США. Поєднує данi Державного реєстру лiкарських засобiв України (DRLZ) з базою FDA (США) та використовує штучний iнтелект для аналiзу запитiв.

### Ключовi особливостi

- Три режими пошуку (за назвою, захворюванням, iнгредiєнтом)
- AI-аналiз з автоматичним fallback мiж провайдерами
- Визначення правового статусу речовин
- Транслiтерацiя та fuzzy search
- Кешування запитiв до зовнiшнiх API

---

## Архiтектура

```
┌─────────────────────────────────────────────────────────────┐
│                        Frontend                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  index.html │  │ results.html│  │     search.js       │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼────────────────┼───────────────────┼──────────────┘
          │                │                   │
          ▼                ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                     Flask Routes                             │
│  ┌─────────────────┐          ┌─────────────────────────┐   │
│  │   search.py     │          │        api.py           │   │
│  │  (веб-сторiнки) │          │    (REST API JSON)      │   │
│  └────────┬────────┘          └────────────┬────────────┘   │
└───────────┼────────────────────────────────┼────────────────┘
            │                                │
            ▼                                ▼
┌─────────────────────────────────────────────────────────────┐
│                       Services                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │search_service│  │  ai_service  │  │  status_resolver │   │
│  │   (пошук)    │  │(Groq/OR/Gem) │  │ (правовий статус)│   │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘   │
│         │                 │                   │              │
│  ┌──────┴───────┐  ┌──────┴───────┐  ┌───────┴────────┐     │
│  │  fda_client  │  │text_processor│  │ analog_finder  │     │
│  │  (FDA API)   │  │(транслiтер.) │  │   (аналоги)    │     │
│  └──────────────┘  └──────────────┘  └────────────────┘     │
└─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │   SQLite + FTS5  │    │     Статичнi JSON файли      │   │
│  │   pharmaref.db   │    │  controlled_ua/dea, atc_codes│   │
│  └──────────────────┘    └──────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## Режими пошуку

### F-01: Пошук за назвою препарату

**Endpoint:** `GET /api/search?q=<запит>&mode=name`

Шукає за торговою назвою та МНН (мiжнародна непатентована назва).

**Алгоритм:**
1. Генерацiя варiантiв транслiтерацiї (кирилиця <-> латиниця)
2. FTS5 пошук в локальнiй БД
3. Fuzzy search якщо FTS дав мало результатiв
4. Пошук в FDA API
5. AI-аналiз запиту (виправлення помилок)
6. AI-аналiз результатiв (попередження)

**Приклад:**
```bash
curl "http://localhost:5001/api/search?q=парацетамол&mode=name"
```

**Вiдповiдь:**
```json
{
  "query": "парацетамол",
  "mode": "name",
  "count": 15,
  "results": [...],
  "suggestion": null,
  "warnings": [],
  "variants_used": ["парацетамол", "paracetamol"],
  "ai_analysis": {
    "summary": "Знайдено 15 препаратiв парацетамолу...",
    "warnings": ["Не перевищуйте добову дозу 4г"],
    "interactions": [],
    "recommendations": ["Консультуйтесь з лiкарем"]
  }
}
```

---

### F-02: Пошук за захворюванням

**Endpoint:** `GET /api/search?q=<запит>&mode=disease`

Шукає препарати для лiкування захворювання/симптому.

**Алгоритм:**
1. AI перекладає захворювання на англiйську
2. AI визначає вiдповiднi ATC коди
3. Пошук в БД за ATC кодами
4. Пошук в FDA за показаннями (indications)
5. Fallback на статичний словник якщо AI недоступний

**Приклад:**
```bash
curl "http://localhost:5001/api/search?q=головний%20бiль&mode=disease"
```

**AI переклад:**
```json
{
  "english_term": "headache",
  "search_terms": ["headache", "cephalalgia", "head pain"],
  "atc_codes": ["N02", "M01"],
  "explanation": "Головний бiль - поширений симптом..."
}
```

---

### F-03: Пошук за дiючою речовиною

**Endpoint:** `GET /api/search?q=<запит>&mode=ingredient`

Шукає всi препарати з вказаною дiючою речовиною (INN).

**Алгоритм:**
1. Генерацiя варiантiв транслiтерацiї
2. Пошук в БД за полем INN
3. Fuzzy search для схожих назв
4. Пошук в FDA за substance

**Приклад:**
```bash
curl "http://localhost:5001/api/search?q=ibuprofen&mode=ingredient"
```

---

## AI сервiс

### Архiтектура мульти-провайдера

```
┌─────────────────────────────────────────────────────┐
│                    AIService                         │
│  ┌─────────────────────────────────────────────┐    │
│  │            _generate_with_fallback()         │    │
│  │                                              │    │
│  │   ┌─────────┐   ┌───────────┐   ┌────────┐  │    │
│  │   │  Groq   │──▶│OpenRouter │──▶│ Gemini │  │    │
│  │   │ (1st)   │   │  (2nd)    │   │ (3rd)  │  │    │
│  │   └─────────┘   └───────────┘   └────────┘  │    │
│  │        │              │              │       │    │
│  │        ▼              ▼              ▼       │    │
│  │   ┌─────────────────────────────────────┐   │    │
│  │   │     Automatic Fallback on Error      │   │    │
│  │   │  - 429 Rate Limit                    │   │    │
│  │   │  - 403 Cloudflare Block              │   │    │
│  │   │  - Network Errors                    │   │    │
│  │   └─────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### Провайдери та моделi

| Провайдер | Моделi | Лiмiти (free tier) | Швидкiсть |
|-----------|--------|-------------------|-----------|
| **Groq** | llama-3.1-8b-instant | 14,400 req/day | Дуже швидко |
| | llama-3.3-70b-versatile | 1,000 req/day | Швидко |
| | qwen-qwq-32b | 14,400 req/day | Швидко |
| | llama-4-scout | 1,000 req/day | Швидко |
| **OpenRouter** | openrouter/free (авто) | 50 req/day | Середньо |
| | llama-3.3-70b:free | 50 req/day | Середньо |
| | nemotron-3-super:free | 50 req/day | Середньо |
| **Gemini** | gemini-2.5-flash-lite | 1,000 req/day | Середньо |
| | gemini-2.5-flash | 500 req/day | Середньо |
| | gemini-2.5-pro | 50 req/day | Повiльно |

### AI функцiї

#### 1. analyze_query(query, mode)

Аналiзує пошуковий запит користувача.

**Що робить:**
- Виправляє орфографiчнi помилки (аспирiн -> аспiрин)
- Визначає тип запиту (лiк/захворювання/iнгредiєнт)
- Попереджає про схожi назви препаратiв
- Оцiнює впевненiсть (0-100%)

**Приклад вiдповiдi:**
```json
{
  "original_query": "аспирiн",
  "corrected_query": "аспiрин",
  "is_drug_name": true,
  "is_disease": false,
  "is_ingredient": false,
  "confidence": 0.95,
  "suggestion": null,
  "warnings": ["Не плутайте з Аспаркам"]
}
```

#### 2. analyze_results(query, drugs)

Аналiзує знайденi препарати.

**Що робить:**
- Формує короткий опис результатiв
- Попереджає про контрольованi речовини
- Виявляє можливi взаємодiї
- Дає рекомендацiї користувачу

**Приклад вiдповiдi:**
```json
{
  "summary": "Знайдено 5 варiантiв iбупрофену, всi безрецептурнi",
  "warnings": ["Не приймайте на голодний шлунок"],
  "interactions": ["Не поєднуйте з аспiрином"],
  "recommendations": ["Консультуйтесь з лiкарем при тривалому прийомi"]
}
```

#### 3. translate_disease(disease)

Перекладає захворювання та визначає ATC коди.

**Приклад:**
```
Вхiд: "гiпертонiя"
Вихiд: {
  "english_term": "hypertension",
  "search_terms": ["hypertension", "high blood pressure"],
  "atc_codes": ["C02", "C03", "C07", "C08", "C09"],
  "explanation": "Гiпертонiя - пiдвищений артерiальний тиск..."
}
```

#### 4. explain_drug(drug)

Пояснює препарат простою мовою.

**Приклад:**
```
Вхiд: {"trade_name": "Лоратадин", "inn": "loratadine"}
Вихiд: "Лоратадин - це антигiстамiнний препарат для лiкування
алергiї. Допомагає при нежитi, свербежi, кропив'янцi.
Продається без рецепта. Не викликає сонливостi."
```

---

## Правовий статус

### Категорiї статусiв

| Статус | Опис | Колiр бейджа |
|--------|------|--------------|
| `forbidden_ua` | Заборонено в Українi (Таблиця I) | Червоний |
| `restricted_ua` | Обмежений обiг (Таблиця II) | Помаранчевий |
| `precursor` | Прекурсор (Таблиця III) | Жовтий |
| `dea_i` - `dea_v` | DEA Schedule I-V (США) | Червоний-Зелений |
| `conflict` | Конфлiкт UA/DEA статусу | Фiолетовий |
| `prescription` | Рецептурний | Синiй |
| `otc` | Безрецептурний | Зелений |

### Джерела даних

**Українське законодавство:**
- КМУ №770/2000 - Перелiк наркотичних засобiв
  - Таблиця I: Забороненi (героїн, LSD, MDMA)
  - Таблиця II: Обмежений обiг (морфiн, кодеїн)
  - Таблиця III: Прекурсори (ефедрин, псевдоефедрин)

**США (DEA):**
- Schedule I: Високий потенцiал зловживання, немає медичного використання
- Schedule II: Високий потенцiал, є медичне використання (оксикодон)
- Schedule III-V: Зменшуваний потенцiал зловживання

### Приклад API

```bash
curl "http://localhost:5001/api/status?substance=morphine"
```

```json
{
  "substance": "morphine",
  "ua_status": {
    "status": "restricted",
    "table": "II",
    "law": "КМУ №770/2000"
  },
  "dea_status": {
    "schedule": "II",
    "description": "High potential for abuse"
  },
  "combined_status": "restricted_ua",
  "badge": {
    "color": "orange",
    "icon": "exclamation-triangle",
    "label": "Обмежений обiг"
  }
}
```

---

## База даних

### Схема SQLite

```sql
-- Головна таблиця препаратiв
CREATE TABLE drugs (
    id INTEGER PRIMARY KEY,
    trade_name TEXT NOT NULL,      -- Торгова назва
    inn TEXT,                       -- МНН (International Nonproprietary Name)
    atc_code TEXT,                  -- ATC класифiкацiя
    indications TEXT,               -- Показання (тiльки FDA)
    dispensing TEXT,                -- Умови вiдпуску
    reg_number TEXT,                -- Реєстрацiйний номер (UA)
    fda_set_id TEXT,                -- FDA set_id
    source TEXT NOT NULL,           -- 'ua' або 'fda'
    status TEXT,                    -- Статус реєстрацiї
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

-- FTS5 iндекс для повнотекстового пошуку
CREATE VIRTUAL TABLE drugs_fts USING fts5(
    trade_name,
    inn,
    indications,
    content='drugs',
    content_rowid='id'
);

-- Контрольованi речовини України
CREATE TABLE controlled_ua (
    id INTEGER PRIMARY KEY,
    substance TEXT NOT NULL,
    table_number INTEGER,           -- 1, 2, або 3
    synonyms TEXT                   -- JSON масив синонiмiв
);

-- DEA Schedules
CREATE TABLE controlled_dea (
    id INTEGER PRIMARY KEY,
    substance TEXT NOT NULL,
    schedule TEXT,                  -- I, II, III, IV, V
    description TEXT
);
```

### FTS5 пошук

```sql
-- Пошук з ранжуванням
SELECT d.*, bm25(drugs_fts) as rank
FROM drugs d
JOIN drugs_fts ON d.id = drugs_fts.rowid
WHERE drugs_fts MATCH '"парацетамол"* OR "paracetamol"*'
ORDER BY rank
LIMIT 50;
```

---

## API Reference

### Пошук

#### GET /api/search

| Параметр | Тип | Обов'язковий | Опис |
|----------|-----|--------------|------|
| q | string | Так | Пошуковий запит (мiн. 3 символи) |
| mode | string | Нi | `name` (default), `disease`, `ingredient` |
| limit | int | Нi | Макс. результатiв (default: 50, max: 100) |

#### GET /api/suggest

Автодоповнення для пошукового поля.

| Параметр | Тип | Обов'язковий | Опис |
|----------|-----|--------------|------|
| q | string | Так | Частковий запит (мiн. 3 символи) |
| limit | int | Нi | Кiлькiсть пiдказок (default: 10) |

### Аналоги

#### GET /api/analogs

| Параметр | Тип | Обов'язковий | Опис |
|----------|-----|--------------|------|
| inn | string | Так* | МНН для пошуку |
| atc | string | Так* | ATC код |
| exclude | string | Нi | Торгова назва для виключення |
| limit | int | Нi | Лiмiт (default: 20) |

*Потрiбен або `inn`, або `atc`

### AI

#### GET /api/ai/status

Перевiрка статусу AI сервiсу.

```json
{
  "available": true,
  "provider": "groq",
  "providers_order": ["groq", "openrouter", "gemini"]
}
```

#### GET /api/explain

AI пояснення препарату.

| Параметр | Тип | Обов'язковий | Опис |
|----------|-----|--------------|------|
| name | string | Так | Назва препарату |
| inn | string | Нi | МНН |

### Iнше

#### GET /api/status

Правовий статус речовини.

#### GET /api/db/info

Iнформацiя про базу даних (кiлькiсть записiв, дата оновлення).

---

## Транслiтерацiя

### Пiдтримуванi напрямки

```
Кирилиця -> Латиниця: парацетамол -> paracetamol
Латиниця -> Кирилиця: ibuprofen -> iбупрофен
```

### Таблиця транслiтерацiї

| Кирилиця | Латиниця | Кирилиця | Латиниця |
|----------|----------|----------|----------|
| а | a | п | p |
| б | b | р | r |
| в | v | с | s |
| г | h/g | т | t |
| д | d | у | u |
| е | e | ф | f/ph |
| є | ye | х | kh |
| ж | zh | ц | ts |
| з | z | ч | ch |
| и | y | ш | sh |
| і | i | щ | shch |
| ї | yi | ю | yu |
| й | y | я | ya |
| к | k | ' | (skip) |
| л | l | | |
| м | m | | |
| н | n | | |
| о | o | | |

### Fuzzy Search

Використовує вiдстань Левенштейна для пошуку схожих назв:

```
Запит: "парацитамол" (помилка)
Знайдено: "парацетамол" (схожiсть 91%)
```

Порiг схожостi: 60%

---

## Конфiгурацiя

### Змiннi середовища (.env)

```env
# AI провайдери (хоча б один)
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=AIza...

# Flask
SECRET_KEY=your-secret-key
FLASK_DEBUG=false
FLASK_ENV=production
```

### config.py параметри

| Параметр | Значення | Опис |
|----------|----------|------|
| DATABASE_PATH | pharmaref.db | Шлях до SQLite |
| FDA_CACHE_TTL | 86400 | Кеш FDA (24 год) |
| FDA_RATE_LIMIT | 240 | Запитiв/хв до FDA |
| MIN_SEARCH_LENGTH | 3 | Мiн. довжина запиту |
| AI_ENABLED | True | Увiмкнути AI |

---

## Troubleshooting

### AI не працює

1. Перевiрте `/api/ai/status`
2. Перевiрте наявнiсть ключiв в `.env`
3. Перевiрте логи (stderr) на помилки 429/403

### Groq заблокований

Cloudflare може блокувати запити. Рiшення:
- Використовується правильний User-Agent
- Fallback на OpenRouter/Gemini автоматичний

### Пошук не дає результатiв

1. Перевiрте чи є данi в БД: `GET /api/db/info`
2. Спробуйте iншу транслiтерацiю
3. Використайте mode=ingredient для пошуку за INN

### Помилка 503 на /api/explain

AI сервiс недоступний. Перевiрте:
- Наявнiсть API ключiв
- Лiмiти провайдерiв
- Мережеве з'єднання

---

## Розробка

### Запуск в режимi розробки

```bash
export FLASK_DEBUG=true
python app.py
```

### Структура тестiв

```bash
# Тест AI сервiсу
python -c "
from services.ai_service import get_ai_service
ai = get_ai_service()
print(f'Available: {ai.is_available()}')
print(f'Provider: {ai.get_active_provider()}')
"

# Тест пошуку
curl "http://localhost:5001/api/search?q=test&mode=name"
```

### Оновлення даних DRLZ

```python
from services.drlz_loader import load_drlz_data
load_drlz_data()  # Завантажує CSV з drlz.com.ua
```

---

## Лiцензiя

MIT License

## Автори

- SKPdeveloper
- Claude Opus 4.5 (AI assistant)
