"""
Сервiс iнтеграцiї з Google Gemini API.
Аналiз запитiв користувача та перевiрка результатiв пошуку.
"""

import os
import json
from typing import Optional, List
from dataclasses import dataclass

try:
    from google import genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


@dataclass
class QueryAnalysis:
    """Результат аналiзу запиту користувача."""
    original_query: str
    corrected_query: Optional[str]  # Виправлений запит (якщо були помилки)
    is_drug_name: bool  # Чи це назва лiку
    is_disease: bool  # Чи це захворювання
    is_ingredient: bool  # Чи це дiюча речовина
    confidence: float  # Впевненiсть (0-1)
    suggestion: Optional[str]  # Пропозицiя для користувача
    warnings: List[str]  # Попередження


@dataclass
class ResultsAnalysis:
    """Результат аналiзу знайдених препаратiв."""
    summary: str  # Короткий опис результатiв
    warnings: List[str]  # Попередження про небезпеку
    interactions: List[str]  # Можливi взаємодiї
    recommendations: List[str]  # Рекомендацiї


class GeminiService:
    """Сервiс для роботи з Gemini API."""

    # Актуальнi моделi Gemini (квiтень 2026)
    # Лiмiти free tier:
    # - flash-lite: 15 RPM, 1000 req/day (найбiльшi лiмiти)
    # - flash: середнi лiмiти
    # - pro: 5 RPM (мiнiмальнi лiмiти)
    MODELS = [
        "gemini-2.5-flash-lite",  # Найбiльшi лiмiти free tier
        "gemini-2.5-flash",       # Середнi лiмiти
        "gemini-2.5-pro",         # Мiнiмальнi лiмiти, останнiй варiант
    ]

    # Для сумiсностi зi старим кодом
    MODEL_FLASH = "gemini-2.5-flash"
    MODEL_LITE = "gemini-2.5-flash-lite"
    MODEL_PRO = "gemini-2.5-pro"

    def __init__(self, api_key: str = None):
        """
        Iнiцiалiзацiя сервiсу.

        Args:
            api_key: API ключ Gemini. Якщо не вказано, береться з GEMINI_API_KEY
        """
        self.enabled = False
        self.client = None

        if not GEMINI_AVAILABLE:
            return

        # API ключ з параметра або змiнної середовища
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

        if not self.api_key:
            return

        try:
            self.client = genai.Client(api_key=self.api_key)
            self.enabled = True
        except Exception as e:
            print(f"Помилка iнiцiалiзацiї Gemini: {e}")

    def is_available(self) -> bool:
        """Перевiрка чи сервiс доступний."""
        return self.enabled and self.client is not None

    def _generate_with_fallback(self, prompt: str) -> Optional[str]:
        """
        Генерує контент з автоматичним переключенням мiж моделями при помилцi 429.

        Args:
            prompt: Промпт для генерацiї

        Returns:
            Текст вiдповiдi або None
        """
        import sys

        if not self.is_available():
            return None

        last_error = None
        for model in self.MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                # Успiшна вiдповiдь
                print(f"[Gemini] Успiх з моделлю {model}", file=sys.stderr, flush=True)
                return response.text.strip()

            except Exception as e:
                error_str = str(e)
                last_error = e

                # Якщо 429 (квота вичерпана) - пробуємо наступну модель
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    print(f"[Gemini] Модель {model} - квота вичерпана, пробуємо наступну...", file=sys.stderr, flush=True)
                    continue
                else:
                    # Iнша помилка - виходимо
                    print(f"[Gemini] Помилка ({model}): {e}", file=sys.stderr, flush=True)
                    return None

        # Всi моделi вичерпанi
        print(f"[Gemini] Всi моделi вичерпанi: {last_error}", file=sys.stderr, flush=True)
        return None

    def analyze_query(self, query: str, mode: str = "name") -> Optional[QueryAnalysis]:
        """
        Аналiз пошукового запиту користувача.

        Перевiряє:
        - Чи правильно написана назва
        - Чи це взагалi лiк/захворювання/речовина
        - Що користувач мiг мати на увазi

        Args:
            query: Пошуковий запит
            mode: Режим пошуку (name/disease/ingredient)

        Returns:
            QueryAnalysis або None якщо сервiс недоступний
        """
        if not self.is_available():
            return None

        mode_context = {
            "name": "назву лiкарського препарату",
            "disease": "назву захворювання або симптому",
            "ingredient": "назву дiючої речовини (МНН)"
        }

        prompt = f"""Ти - фармацевтичний експерт. Користувач шукає {mode_context.get(mode, 'iнформацiю про лiки')}.

Запит користувача: "{query}"

Проаналiзуй запит та дай вiдповiдь у форматi JSON:
{{
    "corrected_query": "виправлений запит якщо є помилки, або null",
    "is_drug_name": true/false,
    "is_disease": true/false,
    "is_ingredient": true/false,
    "confidence": 0.0-1.0,
    "suggestion": "пропозицiя для користувача якщо потрiбно уточнення, або null",
    "warnings": ["попередження якщо є схожi назви з iншими препаратами"]
}}

Важливо:
- Якщо є орфографiчна помилка - виправ (модафенiл -> модафiнiл)
- Якщо назва схожа на iнший препарат - попередь
- Якщо це не схоже на медичний термiн - вкажи це
- Вiдповiдай ТIЛЬКИ JSON, без додаткового тексту"""

        try:
            text = self._generate_with_fallback(prompt)
            if not text:
                return None

            # Видаляємо можливi markdown обгортки
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]

            data = json.loads(text)

            return QueryAnalysis(
                original_query=query,
                corrected_query=data.get("corrected_query"),
                is_drug_name=data.get("is_drug_name", False),
                is_disease=data.get("is_disease", False),
                is_ingredient=data.get("is_ingredient", False),
                confidence=data.get("confidence", 0.5),
                suggestion=data.get("suggestion"),
                warnings=data.get("warnings", [])
            )

        except Exception as e:
            print(f"Помилка аналiзу запиту Gemini: {e}")
            return None

    def analyze_results(self, query: str, drugs: List[dict],
                        user_context: str = None) -> Optional[ResultsAnalysis]:
        """
        Аналiз результатiв пошуку.

        Перевiряє:
        - Попередження про небезпечнi препарати
        - Можливi взаємодiї
        - Рекомендацiї для користувача

        Args:
            query: Оригiнальний запит
            drugs: Список знайдених препаратiв
            user_context: Додатковий контекст (вiк, стан здоров'я тощо)

        Returns:
            ResultsAnalysis або None
        """
        if not self.is_available() or not drugs:
            return None

        # Формуємо список препаратiв для аналiзу
        drugs_info = []
        for d in drugs[:10]:  # Обмежуємо 10 препаратами
            info = {
                "name": d.get("trade_name", ""),
                "inn": d.get("inn", ""),
                "status": d.get("legal_status", ""),
                "dispensing": d.get("dispensing", "")
            }
            drugs_info.append(info)

        drugs_json = json.dumps(drugs_info, ensure_ascii=False)

        context_part = ""
        if user_context:
            context_part = f"\nКонтекст користувача: {user_context}"

        prompt = f"""Ти - фармацевтичний експерт. Користувач шукав: "{query}"{context_part}

Знайденi препарати:
{drugs_json}

Проаналiзуй результати та дай вiдповiдь у форматi JSON:
{{
    "summary": "короткий опис що знайдено (1-2 речення)",
    "warnings": ["критичнi попередження про небезпеку, контрольованi речовини, тощо"],
    "interactions": ["попередження про можливi взаємодiї мiж препаратами"],
    "recommendations": ["рекомендацiї для користувача"]
}}

Важливо:
- Попереджай про контрольованi/заборонені речовини
- Попереджай якщо препарати мають схожi назви (ризик плутанини)
- Рекомендуй консультацiю з лiкарем для рецептурних препаратiв
- Вiдповiдай ТIЛЬКИ JSON, без додаткового тексту
- Не вигадуй iнформацiю якої немає в даних"""

        try:
            text = self._generate_with_fallback(prompt)
            if not text:
                return None

            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]

            data = json.loads(text)

            return ResultsAnalysis(
                summary=data.get("summary", ""),
                warnings=data.get("warnings", []),
                interactions=data.get("interactions", []),
                recommendations=data.get("recommendations", [])
            )

        except Exception as e:
            print(f"Помилка аналiзу результатiв Gemini: {e}")
            return None

    def translate_disease(self, disease: str) -> Optional[dict]:
        """
        Перекласти захворювання на англiйську та визначити ATC коди.

        Args:
            disease: Назва захворювання (будь-якою мовою)

        Returns:
            Словник з перекладом та ATC кодами
        """
        if not self.is_available():
            return None

        prompt = f"""Ти - фармацевтичний експерт. Користувач шукає лiки вiд: "{disease}"

Визнач:
1. Англiйську назву захворювання/симптому для пошуку в медичних базах
2. Вiдповiднi ATC коди (анатомо-терапевтично-хiмiчна класифiкацiя)

Вiдповiдь у форматi JSON:
{{
    "english_term": "назва англiйською для пошуку",
    "search_terms": ["термiн1", "термiн2"],
    "atc_codes": ["C02", "C09"],
    "explanation": "коротке пояснення що це за захворювання"
}}

ATC коди:
- A: травна система, A02-антацидні, A10-діабет
- B: кров, B01-антитромботичні, B03-анемія
- C: серцево-судинна, C01-серце, C02-гіпертензія, C03-діуретики, C07-бета-блокатори, C09-РААС, C10-ліпіди
- D: шкіра, D01-протигрибкові
- G: сечостатева
- H: гормони, H03-щитовидна
- J: протимікробні, J01-антибіотики, J02-протигрибкові, J05-противірусні
- L: онкологія/імунологія
- M: кістково-м'язова, M01-НПЗЗ, M05-остеопороз
- N: нервова, N02-анальгетики, N03-протиепілептичні, N05-психолептики, N06-антидепресанти
- P: паразити
- R: дихальна, R01-ніс, R03-астма, R05-кашель, R06-антигістамінні
- S: органи чуття

Вiдповiдай ТIЛЬКИ JSON."""

        try:
            text = self._generate_with_fallback(prompt)
            if not text:
                return None

            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]

            return json.loads(text)

        except Exception as e:
            print(f"Помилка перекладу Gemini: {e}")
            return None

    def explain_drug(self, drug: dict) -> Optional[str]:
        """
        Пояснення iнформацiї про препарат простою мовою.

        Args:
            drug: Данi препарату

        Returns:
            Текстове пояснення або None
        """
        if not self.is_available():
            return None

        drug_info = json.dumps({
            "name": drug.get("trade_name", ""),
            "inn": drug.get("inn", ""),
            "indications": drug.get("indications", "")[:500] if drug.get("indications") else None,
            "dispensing": drug.get("dispensing", ""),
            "legal_status": drug.get("legal_status", "")
        }, ensure_ascii=False)

        prompt = f"""Поясни простою мовою для звичайної людини (не медика) що це за препарат:

{drug_info}

Дай коротке пояснення (3-4 речення):
- Для чого застосовується
- Чи потрiбен рецепт
- Важливi застереження

Вiдповiдай українською, простими словами без медичного жаргону."""

        try:
            text = self._generate_with_fallback(prompt)
            return text

        except Exception as e:
            print(f"Помилка пояснення Gemini: {e}")
            return None


# Глобальний екземпляр
_gemini_service = None


def get_gemini_service() -> GeminiService:
    """Отримати екземпляр GeminiService (singleton)."""
    global _gemini_service
    if _gemini_service is None:
        # Беремо API ключ з конфiгурацiї
        from config import Config
        api_key = getattr(Config, 'GEMINI_API_KEY', None)
        _gemini_service = GeminiService(api_key=api_key)
    return _gemini_service


def init_gemini_service(api_key: str = None) -> GeminiService:
    """Iнiцiалiзувати сервiс з API ключем."""
    global _gemini_service
    _gemini_service = GeminiService(api_key=api_key)
    return _gemini_service
