# PharmaRef

Довiдник лiкарських засобiв України з AI-аналiзом (Groq, OpenRouter, Gemini).

## Можливостi

- Пошук за назвою препарату (торгова назва + МНН)
- Пошук за захворюванням/показанням
- Пошук за дiючою речовиною
- AI-аналiз запитiв та результатiв
- Визначення правового статусу (контрольованi речовини)
- Пiдтримка транслiтерацiї та fuzzy search

## Встановлення

### 1. Клонування репозиторiю

```bash
git clone https://github.com/SKPdeveloper/PharmaRef.git
cd PharmaRef
```

### 2. Встановлення залежностей

```bash
pip install flask python-dotenv requests google-genai
```

### 3. Отримання API ключiв

Для роботи AI-аналiзу потрiбен хоча б один ключ. Рекомендую Groq - безкоштовний i швидкий.

---

#### Groq (рекомендовано)

**Лiмiти безкоштовного тiру:** 14,400 запитiв/день для llama-3.1-8b

1. Перейдiть на [console.groq.com](https://console.groq.com)
2. Натиснiть **Sign Up** (або увiйдiть через Google/GitHub)
3. Пiдтвердiть email
4. Перейдiть в [API Keys](https://console.groq.com/keys)
5. Натиснiть **Create API Key**
6. Скопiюйте ключ (починається з `gsk_...`)

---

#### OpenRouter

**Лiмiти безкоштовного тiру:** 50 запитiв/день, 29 безкоштовних моделей

1. Перейдiть на [openrouter.ai](https://openrouter.ai)
2. Натиснiть **Sign In** (Google/GitHub/Email)
3. Перейдiть в [Settings > Keys](https://openrouter.ai/settings/keys)
4. Натиснiть **Create Key**
5. Скопiюйте ключ (починається з `sk-or-...`)

---

#### Google Gemini

**Лiмiти безкоштовного тiру:** 1000 запитiв/день для flash-lite

1. Перейдiть на [aistudio.google.com](https://aistudio.google.com)
2. Увiйдiть через Google акаунт
3. Натиснiть **Get API Key** (лiворуч)
4. Натиснiть **Create API Key**
5. Виберiть проєкт або створiть новий
6. Скопiюйте ключ (починається з `AIza...`)

---

### 4. Налаштування ключiв

Створiть файл `.env` в кореневiй папцi проєкту:

```bash
cp .env.example .env
```

Вiдкрийте `.env` та вставте вашi ключi:

```env
# Groq - швидкий, 14,400 req/day (рекомендовано)
GROQ_API_KEY=gsk_your_key_here

# OpenRouter - 50 req/day, багато моделей
OPENROUTER_API_KEY=sk-or-your_key_here

# Gemini - 1000 req/day, fallback
GEMINI_API_KEY=AIza_your_key_here
```

Достатньо одного ключа. Система автоматично переключається мiж провайдерами:
```
Groq -> OpenRouter -> Gemini
```

### 5. Запуск

```bash
python app.py
```

Вiдкрийте http://localhost:5001

## API

| Метод | URL | Опис |
|-------|-----|------|
| GET | `/api/search?q=&mode=name\|disease\|ingredient` | Пошук |
| GET | `/api/ai/status` | Статус AI сервiсу |
| GET | `/api/analogs?inn=` | Пошук аналогiв |
| GET | `/api/status?substance=` | Правовий статус |
| GET | `/api/explain?name=` | AI пояснення препарату |
| GET | `/api/db/info` | Iнформацiя про БД |

### Приклад вiдповiдi `/api/ai/status`

```json
{
  "available": true,
  "provider": "groq",
  "providers_order": ["groq", "openrouter", "gemini"]
}
```

## Структура проєкту

```
pharmaref/
├── app.py                 # Flask entry point
├── config.py              # Конфiгурацiя
├── .env                   # API ключi (не в git)
├── services/
│   ├── ai_service.py      # Унiфiкований AI сервiс
│   ├── search_service.py  # Пошуковий сервiс
│   ├── db.py              # SQLite + FTS5
│   └── ...
├── routes/
│   ├── api.py             # REST API
│   └── search.py          # Веб-маршрути
├── templates/             # Jinja2 шаблони
└── static/                # CSS + JS
```

## AI провайдери

| Провайдер | Моделi | Лiмiти (free) |
|-----------|--------|---------------|
| **Groq** | llama-3.1-8b-instant, llama-3.3-70b, qwen-qwq-32b | 14,400 req/day |
| **OpenRouter** | openrouter/free, llama-3.3-70b:free | 50 req/day |
| **Gemini** | flash-lite, flash, pro | 1000 req/day |

## Лiцензiя

MIT
