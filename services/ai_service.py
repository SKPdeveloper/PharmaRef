"""
Унiфiкований AI сервiс з пiдтримкою кiлькох провайдерiв.
Пiдтримує: Gemini, Groq, OpenRouter з автоматичним fallback.
"""

import os
import json
import time
import sys
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod
import urllib.request
import urllib.error


@dataclass
class QueryAnalysis:
    """Результат аналiзу запиту користувача."""
    original_query: str
    corrected_query: Optional[str]
    is_drug_name: bool
    is_disease: bool
    is_ingredient: bool
    confidence: float
    suggestion: Optional[str]
    warnings: List[str]


@dataclass
class ResultsAnalysis:
    """Результат аналiзу знайдених препаратiв."""
    summary: str
    warnings: List[str]
    interactions: List[str]
    recommendations: List[str]


class AIProvider(ABC):
    """Базовий клас для AI провайдерiв."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.name = "base"

    @abstractmethod
    def generate(self, prompt: str) -> Optional[str]:
        """Генерацiя вiдповiдi на промпт."""
        pass

    def is_available(self) -> bool:
        """Перевiрка доступностi провайдера."""
        return bool(self.api_key)


class GeminiProvider(AIProvider):
    """Провайдер Google Gemini."""

    MODELS = [
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-pro",
    ]

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.name = "gemini"
        self.client = None

        if not api_key:
            return

        try:
            from google import genai
            self.client = genai.Client(api_key=api_key)
        except ImportError:
            print("[AI] google-genai не встановлено, Gemini недоступний", file=sys.stderr)
        except Exception as e:
            print(f"[AI] Помилка iнiцiалiзацiї Gemini: {e}", file=sys.stderr)

    def is_available(self) -> bool:
        return self.client is not None

    def generate(self, prompt: str) -> Optional[str]:
        if not self.is_available():
            return None

        for model in self.MODELS:
            try:
                response = self.client.models.generate_content(
                    model=model,
                    contents=prompt
                )
                print(f"[Gemini] Успiх: {model}", file=sys.stderr, flush=True)
                return response.text.strip()

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    print(f"[Gemini] {model} - квота вичерпана", file=sys.stderr, flush=True)
                    continue
                else:
                    print(f"[Gemini] Помилка ({model}): {e}", file=sys.stderr, flush=True)
                    return None

        return None


class GroqProvider(AIProvider):
    """Провайдер Groq (безкоштовний тир, квiтень 2026)."""

    API_URL = "https://api.groq.com/openai/v1/chat/completions"

    # Актуальнi моделi безкоштовного тiру Groq (2026)
    # Лiмiти: llama-3.1-8b-instant найбiльш permissive (14,400 req/day, 500k tokens)
    # 70B моделi: 30 RPM, 1000 req/day
    MODELS = [
        "llama-3.1-8b-instant",     # Найбiльшi лiмiти: 14,400 req/day
        "llama-3.3-70b-versatile",  # 30 RPM, 1000 req/day
        "qwen-qwq-32b",             # Qwen3 32B: 60 RPM
        "llama-4-scout-17b-16e-instruct",  # Llama 4 Scout
    ]

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.name = "groq"

    def generate(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            return None

        for model in self.MODELS:
            try:
                result = self._call_api(model, prompt)
                if result:
                    print(f"[Groq] Успiх: {model}", file=sys.stderr, flush=True)
                    return result
            except Exception as e:
                error_str = str(e)
                # 429 = rate limit, 403 = blocked (Cloudflare), 1010 = Cloudflare
                if "429" in error_str or "rate_limit" in error_str.lower():
                    print(f"[Groq] {model} - rate limit", file=sys.stderr, flush=True)
                    time.sleep(1)
                    continue
                elif "403" in error_str or "1010" in error_str:
                    # Cloudflare блокує - переходимо до наступного провайдера
                    print(f"[Groq] Заблоковано (Cloudflare), пропускаємо провайдер", file=sys.stderr, flush=True)
                    return None
                else:
                    print(f"[Groq] Помилка ({model}): {e}", file=sys.stderr, flush=True)
                    continue

        return None

    def _call_api(self, model: str, prompt: str) -> Optional[str]:
        """Виклик Groq API (OpenAI-сумiсний)."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PharmaRef/1.0"  # Cloudflare блокує дефолтний Python urllib
        }

        data = json.dumps({
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 2048
        }).encode("utf-8")

        request = urllib.request.Request(
            self.API_URL,
            data=data,
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise Exception(f"HTTP {e.code}: {error_body}")


class OpenRouterProvider(AIProvider):
    """Провайдер OpenRouter (доступ до багатьох моделей, квiтень 2026)."""

    API_URL = "https://openrouter.ai/api/v1/chat/completions"

    # Актуальнi безкоштовнi моделi OpenRouter (2026)
    # Лiмiти free plan: 50 req/day, 20 RPM
    # Можна використати openrouter/free для автовибору
    MODELS = [
        "openrouter/free",                        # Автоматичний вибiр найкращої free моделi
        "meta-llama/llama-3.3-70b-instruct:free", # Llama 3.3 70B
        "nvidia/nemotron-3-super-49b-v1:free",    # Nemotron 3 Super (262K context)
        "mistralai/devstral-small:free",          # Devstral 2
    ]

    def __init__(self, api_key: str):
        super().__init__(api_key)
        self.name = "openrouter"

    def generate(self, prompt: str) -> Optional[str]:
        if not self.api_key:
            return None

        for model in self.MODELS:
            try:
                result = self._call_api(model, prompt)
                if result:
                    print(f"[OpenRouter] Успiх: {model}", file=sys.stderr, flush=True)
                    return result
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate" in error_str.lower():
                    print(f"[OpenRouter] {model} - rate limit", file=sys.stderr, flush=True)
                    time.sleep(1)
                    continue
                else:
                    print(f"[OpenRouter] Помилка ({model}): {e}", file=sys.stderr, flush=True)
                    continue

        return None

    def _call_api(self, model: str, prompt: str) -> Optional[str]:
        """Виклик OpenRouter API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://pharmaref.ua",
            "X-Title": "PharmaRef"
        }

        data = json.dumps({
            "model": model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.3,
            "max_tokens": 2048
        }).encode("utf-8")

        request = urllib.request.Request(
            self.API_URL,
            data=data,
            headers=headers,
            method="POST"
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
                return result["choices"][0]["message"]["content"].strip()
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise Exception(f"HTTP {e.code}: {error_body}")


class AIService:
    """
    Унiфiкований AI сервiс з автоматичним fallback мiж провайдерами.

    Порядок спроб:
    1. Groq (безкоштовний, швидкий)
    2. OpenRouter (безкоштовнi моделi)
    3. Gemini (якщо є ключ)
    """

    def __init__(
        self,
        gemini_key: str = None,
        groq_key: str = None,
        openrouter_key: str = None
    ):
        self.providers: List[AIProvider] = []

        # Groq першим (безкоштовний, швидкий)
        if groq_key:
            self.providers.append(GroqProvider(groq_key))

        # OpenRouter другим (багато безкоштовних моделей)
        if openrouter_key:
            self.providers.append(OpenRouterProvider(openrouter_key))

        # Gemini останнiм (якщо є SDK)
        if gemini_key:
            self.providers.append(GeminiProvider(gemini_key))

        self._log_providers()

    def _log_providers(self):
        """Логування доступних провайдерiв."""
        available = [p.name for p in self.providers if p.is_available()]
        if available:
            print(f"[AI] Доступнi провайдери: {', '.join(available)}", file=sys.stderr, flush=True)
        else:
            print("[AI] Жоден AI провайдер не налаштований", file=sys.stderr, flush=True)

    def is_available(self) -> bool:
        """Перевiрка чи є хоча б один доступний провайдер."""
        return any(p.is_available() for p in self.providers)

    def get_active_provider(self) -> Optional[str]:
        """Повертає iм'я першого доступного провайдера."""
        for p in self.providers:
            if p.is_available():
                return p.name
        return None

    def _generate_with_fallback(self, prompt: str, max_retries: int = 2) -> Optional[str]:
        """
        Генерацiя з автоматичним fallback мiж провайдерами.

        Args:
            prompt: Промпт для генерацiї
            max_retries: Кiлькiсть повторних спроб при тимчасових помилках

        Returns:
            Текст вiдповiдi або None
        """
        for provider in self.providers:
            if not provider.is_available():
                continue

            for attempt in range(max_retries):
                try:
                    result = provider.generate(prompt)
                    if result:
                        return result
                    # Якщо None - провайдер вичерпав всi свої моделi
                    break

                except Exception as e:
                    print(f"[AI] {provider.name} спроба {attempt + 1}: {e}", file=sys.stderr, flush=True)
                    if attempt < max_retries - 1:
                        time.sleep(1 * (attempt + 1))  # Exponential backoff
                    continue

            # Переходимо до наступного провайдера
            print(f"[AI] {provider.name} вичерпано, пробуємо наступний...", file=sys.stderr, flush=True)

        print("[AI] Всi провайдери вичерпанi", file=sys.stderr, flush=True)
        return None

    def _parse_json_response(self, text: str) -> Optional[dict]:
        """Парсинг JSON вiдповiдi (може бути обгорнута в markdown)."""
        if not text:
            return None

        # Видаляємо markdown обгортку
        if text.startswith("```"):
            lines = text.split("\n")
            # Пропускаємо перший рядок (```json) i останнiй (```)
            text = "\n".join(lines[1:-1]) if len(lines) > 2 else text

        # Знаходимо JSON в текстi
        try:
            # Спробуємо напряму
            return json.loads(text)
        except json.JSONDecodeError:
            # Шукаємо JSON мiж фiгурними дужками
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
        return None

    def analyze_query(self, query: str, mode: str = "name") -> Optional[QueryAnalysis]:
        """
        Аналiз пошукового запиту користувача.
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
            data = self._parse_json_response(text)
            if not data:
                return None

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
            print(f"[AI] Помилка аналiзу запиту: {e}", file=sys.stderr, flush=True)
            return None

    def analyze_results(self, query: str, drugs: List[dict],
                        user_context: str = None) -> Optional[ResultsAnalysis]:
        """
        Аналiз результатiв пошуку.
        """
        if not self.is_available() or not drugs:
            return None

        drugs_info = []
        for d in drugs[:10]:
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
- Попереджай про контрольованi/забороненi речовини
- Попереджай якщо препарати мають схожi назви (ризик плутанини)
- Рекомендуй консультацiю з лiкарем для рецептурних препаратiв
- Вiдповiдай ТIЛЬКИ JSON, без додаткового тексту
- Не вигадуй iнформацiю якої немає в даних"""

        try:
            text = self._generate_with_fallback(prompt)
            data = self._parse_json_response(text)
            if not data:
                return None

            return ResultsAnalysis(
                summary=data.get("summary", ""),
                warnings=data.get("warnings", []),
                interactions=data.get("interactions", []),
                recommendations=data.get("recommendations", [])
            )

        except Exception as e:
            print(f"[AI] Помилка аналiзу результатiв: {e}", file=sys.stderr, flush=True)
            return None

    def translate_disease(self, disease: str) -> Optional[dict]:
        """
        Перекласти захворювання на англiйську та визначити ATC коди.
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
- A: травна система, A02-антациднi, A10-дiабет
- B: кров, B01-антитромботичнi, B03-анемiя
- C: серцево-судинна, C01-серце, C02-гiпертензiя, C03-дiуретики, C07-бета-блокатори, C09-РААС, C10-лiпiди
- D: шкiра, D01-протигрибковi
- G: сечостатева
- H: гормони, H03-щитовидна
- J: протимiкробнi, J01-антибiотики, J02-протигрибковi, J05-противiруснi
- L: онкологiя/iмунологiя
- M: кiстково-м'язова, M01-НПЗЗ, M05-остеопороз
- N: нервова, N02-анальгетики, N03-протиепiлептичнi, N05-психолептики, N06-антидепресанти
- P: паразити
- R: дихальна, R01-нiс, R03-астма, R05-кашель, R06-антигiстамiннi
- S: органи чуття

Вiдповiдай ТIЛЬКИ JSON."""

        try:
            text = self._generate_with_fallback(prompt)
            return self._parse_json_response(text)

        except Exception as e:
            print(f"[AI] Помилка перекладу: {e}", file=sys.stderr, flush=True)
            return None

    def explain_drug(self, drug: dict) -> Optional[str]:
        """
        Пояснення iнформацiї про препарат простою мовою.
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
            return self._generate_with_fallback(prompt)
        except Exception as e:
            print(f"[AI] Помилка пояснення: {e}", file=sys.stderr, flush=True)
            return None


# Глобальний екземпляр
_ai_service: Optional[AIService] = None


def get_ai_service() -> AIService:
    """Отримати екземпляр AIService (singleton)."""
    global _ai_service
    if _ai_service is None:
        from config import Config
        _ai_service = AIService(
            gemini_key=getattr(Config, 'GEMINI_API_KEY', None),
            groq_key=getattr(Config, 'GROQ_API_KEY', None),
            openrouter_key=getattr(Config, 'OPENROUTER_API_KEY', None)
        )
    return _ai_service


def init_ai_service(
    gemini_key: str = None,
    groq_key: str = None,
    openrouter_key: str = None
) -> AIService:
    """Iнiцiалiзувати AI сервiс з ключами."""
    global _ai_service
    _ai_service = AIService(
        gemini_key=gemini_key,
        groq_key=groq_key,
        openrouter_key=openrouter_key
    )
    return _ai_service
