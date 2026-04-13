# PharmaRef — Довідник лікарських препаратів
## Технічна специфікація v2.0 (lean)

---

## 1. Концепція

Три поля на препарат. Три режими пошуку. Один чіткий результат.

| Поле | Джерело | Примітка |
|---|---|---|
| **Назва** | ДРЛЗ + FDA | Торгова назва + МНН |
| **Активні речовини** | ДРЛЗ (`inn`) + FDA (`active_ingredient`) | Для пошуку аналогів |
| **Показання** | FDA (`indications_and_usage` / `purpose`) | ДРЛЗ показань у CSV не має |

Плюс правовий статус — без нього довідник перетворюється на рекламний буклет.

---

## 2. Джерела даних і що беремо

### 2.1 ДРЛЗ CSV (`drlz.com.ua/ibp/zvity.nsf/all/zvit/$file/reestr.csv`)

З усіх полів CSV використовуємо тільки:

```
trade_name          -- торгова назва (укр.)
inn                 -- МНН / активна речовина
atc_code            -- для групування і пошуку по хворобі
dispensing_condition -- рецептурний / ОТС
registration_number
status              -- active / expired / suspended
```

Все інше (виробник, форма, дозування, адреса, примітки) — **не зберігаємо**.

### 2.2 OpenFDA Drug Label API

Запити в реальному часі. З JSON-відповіді беремо **тільки**:

```json
openfda.brand_name          -- торгова назва
openfda.generic_name        -- МНН
openfda.substance_name      -- активні речовини (масив)
indications_and_usage       -- показання (Rx-препарати)
purpose                     -- показання (OTC-препарати)
```

Всі інші поля (`warnings`, `dosage_and_administration`, `adverse_reactions`,
`drug_interactions` тощо) — **ігноруємо повністю**.

### 2.3 Нормативні переліки (статичні JSON)

Без змін відносно v1.0 — тільки для правового статусу речовин:
- `controlled_ua.json` — КМУ №770/2000 (Таблиці I–III)
- `controlled_dea.json` — DEA Schedule I–V
- `atc_codes.json` — АТХ-класифікатор (для пошуку по хворобі через АТХ)

---

## 3. Модель даних (SQLite)

### 3.1 Таблиці

```sql
-- Єдина таблиця препаратів (об'єднує UA і FDA записи)
CREATE TABLE drugs (
    id               INTEGER PRIMARY KEY,
    source           TEXT NOT NULL,      -- 'ua' | 'fda'
    trade_name       TEXT NOT NULL,
    inn              TEXT,               -- МНН, нормалізований
    atc_code         TEXT,
    indications      TEXT,               -- показання (тільки для FDA)
    dispensing       TEXT,               -- 'otc' | 'rx' | 'special'
    reg_number       TEXT,               -- для UA: реєстраційний номер
    status           TEXT DEFAULT 'active', -- 'active'|'expired'|'suspended'
    fda_set_id       TEXT                -- для FDA: set_id для повторного запиту
);

-- FTS5 для повнотекстового пошуку
CREATE VIRTUAL TABLE drugs_fts USING fts5(
    trade_name,
    inn,
    indications,
    content='drugs',
    content_rowid='id'
);

-- Контрольні речовини
CREATE TABLE controlled_ua (
    substance  TEXT PRIMARY KEY COLLATE NOCASE,
    table_num  INTEGER,   -- 1=заборонено, 2=обмежено, 3=прекурсор
    list_num   INTEGER,
    level      TEXT       -- 'forbidden'|'restricted'|'precursor'
);

CREATE TABLE controlled_dea (
    substance  TEXT PRIMARY KEY COLLATE NOCASE,
    schedule   TEXT        -- 'I'|'II'|'III'|'IV'|'V'
);

-- АТХ (тільки назви, для декодування кодів)
CREATE TABLE atc (
    code        TEXT PRIMARY KEY,
    name_uk     TEXT,
    name_en     TEXT
);
```

### 3.2 Індекси

```sql
CREATE INDEX idx_drugs_inn     ON drugs(inn COLLATE NOCASE);
CREATE INDEX idx_drugs_atc     ON drugs(atc_code);
CREATE INDEX idx_drugs_source  ON drugs(source);
```

---

## 4. Архітектура

```
pharmaref/
├── app.py
├── config.py
│
├── data/
│   ├── controlled_ua.json
│   ├── controlled_dea.json
│   └── atc_codes.json
│
├── services/
│   ├── db.py               -- SQLite, get_db(), init_db()
│   ├── drlz_loader.py      -- завантаження CSV, парсинг, запис у drugs
│   ├── fda_client.py       -- OpenFDA HTTP-клієнт, витяг 5 полів
│   ├── search_service.py   -- три режими пошуку
│   ├── status_resolver.py  -- правовий статус речовини
│   └── analog_finder.py    -- аналоги за МНН і АТХ
│
├── routes/
│   ├── search.py           -- GET /search
│   └── api.py              -- GET /api/search, /api/analogs, /api/status
│
├── templates/
│   ├── base.html
│   ├── index.html
│   └── results.html        -- картка препарату вбудована в результати
│
└── static/
    ├── style.css
    └── search.js
```

Окремої сторінки картки препарату **немає** — вся інформація відображається
безпосередньо в рядку результату (accordion-розкриття).

---

## 5. Три режими пошуку

### F-01: За назвою препарату

```
Вхід:    "аспірин" / "aspirin" / "ацетилсаліцилова"
Пошук:   drugs_fts MATCH → поля trade_name + inn
Джерела: ДРЛЗ (локально) + OpenFDA (live, кеш 24 год)
Вивід:   назва | МНН | показання | статус UA | статус DEA
```

### F-02: За хворобою / показанням

```
Вхід:    "гіпертонія" / "hypertension" / "тиск"
Крок 1:  пошук у drugs_fts по полю indications (FDA-дані)
Крок 2:  пошук по atc_codes → знайти АТХ-коди для даної нозології
         (статичний словник 80 нозологій МКХ-10 → АТХ)
Крок 3:  вибірка з drugs по atc_code → препарати ДРЛЗ без показань
Об'єднання результатів, дедублікація за inn
```

Словник нозологій будується один раз статично (80 найпоширеніших):
`"гіпертонія" → ["C02", "C03", "C07", "C08", "C09"]` тощо.

### F-03: За активною речовиною (пошук аналогів)

```
Вхід:    "метформін" / "metformin"
Пошук:   drugs WHERE inn LIKE '%метформін%' (COLLATE NOCASE)
         + OpenFDA search openfda.substance_name:"metformin"
Вивід:   всі препарати з даною речовиною, згруповані:
         [UA-зареєстровані] → [тільки FDA] → [заборонені/обмежені]
```

---

## 6. Правовий статус (status_resolver.py)

Логіка незмінна — для кожної речовини зі списку `inn` препарату:

```python
def resolve(inn: str) -> LegalStatus:
    ua = db.query("SELECT level FROM controlled_ua WHERE substance=?", inn)
    dea = db.query("SELECT schedule FROM controlled_dea WHERE substance=?", inn)

    if ua and ua.level == 'forbidden':
        return LegalStatus(badge='🔴', text='Заборонено в Україні',
                           ref='КМУ №770, Табл.I сп.1')
    if ua and ua.level == 'restricted':
        return LegalStatus(badge='🟡', text='Обмежений обіг в Україні',
                           ref='КМУ №770, Табл.II')
    if ua and ua.level == 'precursor':
        return LegalStatus(badge='⚠️', text='Прекурсор — фізособам недоступний',
                           ref='КМУ №770, Табл.III')
    if dea and not ua:
        return LegalStatus(badge='🇺🇸', text=f'DEA Schedule {dea.schedule}',
                           ref='21 CFR §1308')
    if dea and ua:
        return LegalStatus(badge='⚡', text='Різний статус UA/USA',
                           ref=f'UA: КМУ №770 / USA: DEA Sch.{dea.schedule}')
    # перевірка умов відпуску з ДРЛЗ
    if dispensing == 'rx':
        return LegalStatus(badge='🔵', text='За рецептом')
    return LegalStatus(badge='🟢', text='Вільний продаж')
```

---

## 7. Завантаження даних

### 7.1 ДРЛЗ — при старті (`drlz_loader.py`)

```python
def load_drlz():
    url = "http://www.drlz.com.ua/ibp/zvity.nsf/all/zvit/$file/reestr.csv"
    response = requests.get(url, timeout=30)
    content = response.content.decode('windows-1251')
    reader = csv.DictReader(io.StringIO(content), delimiter=';')

    for row in reader:
        db.execute("""
            INSERT OR REPLACE INTO drugs
            (source, trade_name, inn, atc_code, dispensing, reg_number, status)
            VALUES ('ua', ?, ?, ?, ?, ?, ?)
        """, [
            normalize(row['Торгова назва']),
            normalize_inn(row['МНН']),    # прибрати концентрації, дужки
            row['Код АТС'].strip().upper(),
            map_dispensing(row['Умови відпуску']),
            row['Номер реєстраційного посвідчення'],
            detect_status(row)
        ])
    rebuild_fts()
```

Поле `indications` для UA-записів залишається `NULL` — показань у ДРЛЗ CSV немає.

### 7.2 OpenFDA — live з кешем (`fda_client.py`)

```python
FIELDS = "openfda.brand_name,openfda.generic_name,openfda.substance_name,indications_and_usage,purpose"

def search_fda(query: str, mode: str) -> list[dict]:
    cache_key = md5(f"{mode}:{query}").hexdigest()
    cached = db.get_cache(cache_key, ttl_hours=24)
    if cached:
        return cached

    if mode == 'name':
        q = f'openfda.brand_name:"{query}"+openfda.generic_name:"{query}"'
    elif mode == 'disease':
        q = f'indications_and_usage:"{query}"+purpose:"{query}"'
    elif mode == 'ingredient':
        q = f'openfda.substance_name:"{query}"'

    url = f"https://api.fda.gov/drug/label.json?search={q}&limit=20&_fields={FIELDS}"
    data = requests.get(url, timeout=10).json()
    results = parse_fda_response(data)
    db.set_cache(cache_key, results)
    return results
```

---

## 8. API Endpoints

| Метод | URL | Параметри | Відповідь |
|---|---|---|---|
| GET | `/api/search` | `q`, `mode=name\|disease\|ingredient` | JSON: список препаратів |
| GET | `/api/analogs` | `inn` | JSON: аналоги за МНН і АТХ |
| GET | `/api/status` | `substance` | JSON: UA і DEA статус |
| GET | `/api/db/info` | — | JSON: дата оновлення ДРЛЗ, кількість записів |

Формат одного результату:

```json
{
  "trade_name": "Глюкофаж",
  "inn": "metformin",
  "indications": "Type 2 diabetes mellitus...",
  "source": "fda",
  "atc_code": "A10BA02",
  "atc_name": "Метформін",
  "legal_ua": { "badge": "🔵", "text": "За рецептом" },
  "legal_dea": null,
  "ua_registered": true
}
```

---

## 9. Інтерфейс

### Головна сторінка
- Пошукове поле + перемикач режиму: **Назва / Хвороба / Компонент**
- Live-suggestions після 3 символів
- Дисклеймер у шапці (незнімний)

### Результати (одна сторінка без переходів)
Кожен рядок результату:

```
[🔵] ГЛЮКОФАЖ   metformin   A10BA02 · Метформін
     Показання: Цукровий діабет 2 типу у дорослих...   [FDA]
     ▼ Аналоги (14 препаратів)
```

При розкритті аналогів — таблиця: назва | джерело | правовий статус.

Фільтри панелі:
- Джерело: UA / FDA / обидва
- Статус в UA: зареєстровані / всі
- Правовий: тільки вільний обіг / всі

### Дисклеймер (фіксований у header)
> ⚠️ Виключно інформаційний ресурс. Не є медичною рекомендацією.
> Самолікування — пряма загроза здоров'ю. Правовий статус речовин
> актуальний на дату оновлення бази — перевіряйте чинне законодавство.

---

## 10. Обмеження

- Показання є **тільки для FDA-препаратів**. ДРЛЗ CSV їх не містить —
  для UA-записів показання визначаються виключно через АТХ-код.
- OpenFDA rate limit: 240 req/хв без ключа. Кеш 24 год вирішує проблему
  для типового використання.
- Нормативні переліки (КМУ №770) оновлюються вручну — автопарсингу
  zakon.rada.gov.ua немає.

---

*Специфікація v2.0 (lean) — 12.04.2026*
