"""
Сервiс пошуку лiкарських засобiв.
Реалiзує три режими пошуку: за назвою, за захворюванням, за iнгредiєнтом.
Пiдтримує транслiтерацiю, fuzzy search та попередження про схожi назви.
"""

import json
from pathlib import Path
from typing import List, Optional, Tuple

from config import Config
from services.db import get_db, get_db_connection
from services.fda_client import FDAClient, save_fda_results_to_db
from services.status_resolver import get_status_resolver
from services.text_processor import (
    get_text_processor,
    get_search_variants,
    normalize_text,
    find_similar_names,
    suggest_corrections,
    check_dangerous_similarity,
    is_cyrillic,
    cyrillic_to_latin,
    levenshtein_distance,
)
from services.ai_service import get_ai_service, init_ai_service


class SearchService:
    """Сервiс пошуку з трьома режимами та розумною обробкою тексту."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.fda_client = FDAClient(db_path)
        self.status_resolver = get_status_resolver(db_path)
        self.text_processor = get_text_processor()
        self._disease_mappings = None
        self._known_names = []
        self._known_inns = []
        self._load_disease_mappings()
        self._load_known_names()

        # Iнiцiалiзацiя AI сервiсу (Groq -> OpenRouter -> Gemini)
        ai_enabled = getattr(Config, 'AI_ENABLED', True)
        if ai_enabled:
            self.ai = init_ai_service(
                gemini_key=getattr(Config, 'GEMINI_API_KEY', None),
                groq_key=getattr(Config, 'GROQ_API_KEY', None),
                openrouter_key=getattr(Config, 'OPENROUTER_API_KEY', None)
            )
        else:
            self.ai = get_ai_service()

    def _load_disease_mappings(self):
        """Завантажити маппiнг захворювань на ATC коди."""
        atc_path = Config.DATA_DIR / "atc_codes.json"
        if atc_path.exists():
            with open(atc_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._disease_mappings = data.get("disease_mappings", {})

    def _load_known_names(self):
        """Завантажити вiдомi назви препаратiв для fuzzy search."""
        try:
            with get_db_connection(self.db_path) as conn:
                cursor = conn.cursor()

                # Завантажуємо торговi назви
                cursor.execute("SELECT DISTINCT trade_name FROM drugs WHERE trade_name IS NOT NULL")
                self._known_names = [row[0] for row in cursor.fetchall()]

                # Завантажуємо МНН
                cursor.execute("SELECT DISTINCT inn FROM drugs WHERE inn IS NOT NULL")
                self._known_inns = [row[0] for row in cursor.fetchall()]

                # Кешуємо в text_processor
                self.text_processor.set_known_names(self._known_names)
                self.text_processor.set_known_inns(self._known_inns)

        except Exception:
            # БД ще не iнiцiалiзована
            pass

    def refresh_known_names(self):
        """Оновити кеш вiдомих назв (викликати пiсля завантаження даних)."""
        self._load_known_names()

    def _enrich_with_status(self, drugs: List[dict]) -> List[dict]:
        """Додати правовий статус до кожного лiку."""
        for drug in drugs:
            status, details = self.status_resolver.resolve(drug)
            drug["legal_status"] = status
            drug["legal_details"] = details
        return drugs

    def _build_fts_query(self, variants: List[str]) -> str:
        """
        Побудувати FTS5 запит з усiх варiантiв.
        """
        # Екрануємо спецсимволи FTS5
        safe_variants = []
        for v in variants:
            # Видаляємо символи що можуть зламати FTS5
            safe = v.replace('"', '').replace("'", "").replace('*', '').replace('-', ' ')
            if safe:
                safe_variants.append(safe)

        if not safe_variants:
            return ""

        # Об'єднуємо через OR з prefix-пошуком
        parts = [f'"{v}"*' for v in safe_variants]
        return " OR ".join(parts)

    def _fuzzy_search_in_db(self, query: str, limit: int = 50) -> List[dict]:
        """
        Fuzzy пошук в БД - знаходить схожi назви навiть з помилками.
        """
        results = []
        query_normalized = normalize_text(query)
        query_variants = get_search_variants(query)

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            # Отримуємо кандидатiв (препарати що починаються на тi ж букви)
            first_chars = set()
            for v in query_variants:
                if v:
                    first_chars.add(v[:2])  # Першi 2 символи

            if not first_chars:
                return []

            like_conditions = " OR ".join([f"LOWER(trade_name) LIKE ?" for _ in first_chars])
            like_params = [f"{c}%" for c in first_chars]

            cursor.execute(f"""
                SELECT * FROM drugs
                WHERE {like_conditions}
                LIMIT 200
            """, like_params)

            candidates = [dict(row) for row in cursor.fetchall()]

        # Рахуємо схожiсть для кожного кандидата
        scored_results = []
        for drug in candidates:
            trade_name = drug.get("trade_name", "")
            inn = drug.get("inn", "")

            # Порiвнюємо з усiма варiантами запиту
            best_score = 0
            for variant in query_variants:
                # Схожiсть з торговою назвою
                name_normalized = normalize_text(trade_name)
                if name_normalized:
                    distance = levenshtein_distance(variant, name_normalized)
                    max_len = max(len(variant), len(name_normalized))
                    score = 1 - (distance / max_len) if max_len > 0 else 0
                    best_score = max(best_score, score)

                # Схожiсть з INN
                if inn:
                    inn_normalized = normalize_text(inn)
                    distance = levenshtein_distance(variant, inn_normalized)
                    max_len = max(len(variant), len(inn_normalized))
                    score = 1 - (distance / max_len) if max_len > 0 else 0
                    best_score = max(best_score, score)

            # Додаємо якщо схожiсть >= 60%
            if best_score >= 0.6:
                drug["_search_score"] = best_score
                scored_results.append(drug)

        # Сортуємо за схожiстю
        scored_results.sort(key=lambda x: x.get("_search_score", 0), reverse=True)

        # Видаляємо службове поле та обмежуємо результати
        for drug in scored_results[:limit]:
            drug.pop("_search_score", None)
            results.append(drug)

        return results

    def search_by_name(self, query: str, limit: int = 50) -> dict:
        """
        F-01: Пошук за назвою препарату (торгова назва + МНН).
        Пiдтримує транслiтерацiю та fuzzy search.

        Returns:
            Словник з результатами та метаiнформацiєю:
            - results: список знайдених препаратiв
            - suggestion: пропозицiя виправлення (якщо запит з помилкою)
            - warnings: попередження про схожi назви
            - variants_used: якi варiанти запиту використано
        """
        if not query or len(query) < Config.MIN_SEARCH_LENGTH:
            return {"results": [], "suggestion": None, "warnings": [], "variants_used": []}

        # Обробляємо запит - отримуємо варiанти транслiтерацiї
        query_info = self.text_processor.process_query(query)
        variants = query_info["variants"]

        results = []
        seen_ids = set()

        # Пошук в локальнiй БД (FTS5) по всiх варiантах
        fts_query = self._build_fts_query(variants)

        if fts_query:
            with get_db_connection(self.db_path) as conn:
                cursor = conn.cursor()

                try:
                    cursor.execute("""
                        SELECT d.*, bm25(drugs_fts) as rank
                        FROM drugs d
                        JOIN drugs_fts ON d.id = drugs_fts.rowid
                        WHERE drugs_fts MATCH ?
                        ORDER BY rank
                        LIMIT ?
                    """, (fts_query, limit))

                    for row in cursor.fetchall():
                        drug = dict(row)
                        if drug["id"] not in seen_ids:
                            seen_ids.add(drug["id"])
                            results.append(drug)
                except Exception:
                    # FTS5 може впасти на деяких запитах
                    pass

        # Якщо FTS не дав результатiв, пробуємо fuzzy search
        if len(results) < 5:
            fuzzy_results = self._fuzzy_search_in_db(query, limit=limit - len(results))
            for drug in fuzzy_results:
                if drug.get("id") not in seen_ids:
                    seen_ids.add(drug.get("id"))
                    results.append(drug)

        # Шукаємо в FDA по всiх варiантах
        if len(results) < limit // 2:
            for variant in variants[:2]:  # Перших 2 варiанти
                fda_results = self.fda_client.search(variant, limit=limit - len(results))
                if fda_results:
                    save_fda_results_to_db(fda_results, self.db_path)
                    for drug in fda_results:
                        if not any(r.get("trade_name") == drug.get("trade_name") for r in results):
                            results.append(drug)

        # Додаємо правовий статус
        results = self._enrich_with_status(results)

        # Формуємо вiдповiдь з метаiнформацiєю
        response = {
            "results": results[:limit],
            "variants_used": variants,
            "suggestion": query_info.get("suggestion"),
            "warnings": []
        }

        # Перевiряємо на небезпечно схожi назви
        if results and self._known_names:
            warnings = self.text_processor.check_result_safety(query, results)
            response["warnings"] = warnings

        # Якщо немає результатiв, пропонуємо виправлення
        if not results and self._known_names:
            all_known = self._known_names + self._known_inns
            suggestion = suggest_corrections(query, all_known, threshold=0.5)
            if suggestion:
                response["suggestion"] = suggestion

        # AI аналiз через Gemini
        response["ai_analysis"] = None
        if self.ai.is_available():
            # Аналiз запиту
            query_analysis = self.ai.analyze_query(query, mode="name")
            if query_analysis:
                # Якщо AI знайшов помилку i ми не маємо suggestion
                if query_analysis.corrected_query and not response["suggestion"]:
                    response["suggestion"] = {
                        "original": query,
                        "suggestion": query_analysis.corrected_query,
                        "confidence": query_analysis.confidence * 100,
                        "message": f"Можливо, ви мали на увазi: {query_analysis.corrected_query}?"
                    }
                # Додаємо AI попередження
                if query_analysis.warnings:
                    response["warnings"].extend([
                        {"warning": w, "source": "ai"} for w in query_analysis.warnings
                    ])

            # Аналiз результатiв
            if results:
                results_analysis = self.ai.analyze_results(query, results)
                if results_analysis:
                    response["ai_analysis"] = {
                        "summary": results_analysis.summary,
                        "warnings": results_analysis.warnings,
                        "interactions": results_analysis.interactions,
                        "recommendations": results_analysis.recommendations
                    }

        return response

    def search_by_disease(self, disease: str, limit: int = 50) -> dict:
        """
        F-02: Пошук за захворюванням/показанням.
        Використовує Gemini для перекладу та визначення ATC кодiв.
        """
        if not disease or len(disease) < Config.MIN_SEARCH_LENGTH:
            return {"results": [], "suggestion": None, "warnings": [], "variants_used": [], "ai_analysis": None}

        results = []
        seen_ids = set()
        atc_codes = []
        search_terms = [disease]
        variants = get_search_variants(disease)  # Для FTS пошуку
        ai_explanation = None

        # Використовуємо Gemini для розумного пошуку
        if self.ai.is_available():
            translation = self.ai.translate_disease(disease)
            if translation:
                # Отримуємо англiйськi термiни для пошуку в FDA
                if translation.get("english_term"):
                    search_terms.append(translation["english_term"])
                if translation.get("search_terms"):
                    search_terms.extend(translation["search_terms"])
                # Отримуємо ATC коди
                if translation.get("atc_codes"):
                    atc_codes = translation["atc_codes"]
                # Пояснення для користувача
                ai_explanation = translation.get("explanation")

        # Fallback на статичний словник якщо Gemini недоступний або не дав результату
        if not atc_codes and self._disease_mappings:
            variants = get_search_variants(disease)
            matched_codes = set()
            for variant in variants:
                variant_lower = variant.lower()
                for pattern, codes in self._disease_mappings.items():
                    pattern_lower = pattern.lower()
                    if pattern_lower in variant_lower or variant_lower in pattern_lower:
                        for code in codes:
                            matched_codes.add(code)
                        atc_codes.extend(codes)

            # Знаходимо англiйськi еквiваленти для FDA пошуку
            # Шукаємо всi патерни з такими ж ATC кодами
            if matched_codes:
                for pattern, codes in self._disease_mappings.items():
                    # Якщо патерн латиницею i має спiльнi ATC коди
                    if pattern.isascii() and set(codes) & matched_codes:
                        if pattern not in search_terms:
                            search_terms.append(pattern)

        atc_codes = list(set(atc_codes))

        # Пошук за ATC кодами
        if atc_codes:
            with get_db_connection(self.db_path) as conn:
                cursor = conn.cursor()

                atc_conditions = " OR ".join([f"atc_code LIKE ?" for _ in atc_codes])
                atc_params = [f"{code}%" for code in atc_codes]

                cursor.execute(f"""
                    SELECT DISTINCT * FROM drugs
                    WHERE {atc_conditions}
                    LIMIT ?
                """, atc_params + [limit])

                for row in cursor.fetchall():
                    drug = dict(row)
                    if drug["id"] not in seen_ids:
                        seen_ids.add(drug["id"])
                        results.append(drug)

        # Пошук за показаннями в локальнiй БД (FTS5)
        fts_query = self._build_fts_query(variants)
        if fts_query and len(results) < limit:
            with get_db_connection(self.db_path) as conn:
                cursor = conn.cursor()

                try:
                    cursor.execute("""
                        SELECT d.* FROM drugs d
                        JOIN drugs_fts ON d.id = drugs_fts.rowid
                        WHERE drugs_fts.indications MATCH ?
                        LIMIT ?
                    """, (fts_query, limit - len(results)))

                    for row in cursor.fetchall():
                        drug = dict(row)
                        if drug["id"] not in seen_ids:
                            seen_ids.add(drug["id"])
                            results.append(drug)
                except Exception:
                    pass

        # Шукаємо в FDA за показаннями (використовуємо англiйськi термiни)
        if len(results) < limit // 2:
            for term in search_terms[:3]:  # Перших 3 термiни
                fda_results = self.fda_client.search_by_indication(
                    term, limit=limit - len(results)
                )
                if fda_results:
                    save_fda_results_to_db(fda_results, self.db_path)
                    for drug in fda_results:
                        if not any(r.get("trade_name") == drug.get("trade_name") for r in results):
                            results.append(drug)

        results = self._enrich_with_status(results)

        return {
            "results": results[:limit],
            "variants_used": search_terms,
            "suggestion": None,
            "warnings": [],
            "ai_analysis": {"explanation": ai_explanation} if ai_explanation else None
        }

    def search_by_ingredient(self, ingredient: str, limit: int = 50) -> dict:
        """
        F-03: Пошук за дiючою речовиною (INN).
        """
        if not ingredient or len(ingredient) < Config.MIN_SEARCH_LENGTH:
            return {"results": [], "suggestion": None, "warnings": [], "variants_used": []}

        # Отримуємо варiанти транслiтерацiї
        variants = get_search_variants(ingredient)

        results = []
        seen_ids = set()

        # Пошук в локальнiй БД за INN (по всiх варiантах)
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            for variant in variants:
                cursor.execute("""
                    SELECT * FROM drugs
                    WHERE LOWER(inn) LIKE ? OR LOWER(inn) LIKE ?
                    ORDER BY source, trade_name
                    LIMIT ?
                """, (f"%{variant.lower()}%", variant.lower(), limit))

                for row in cursor.fetchall():
                    drug = dict(row)
                    if drug["id"] not in seen_ids:
                        seen_ids.add(drug["id"])
                        results.append(drug)

        # Fuzzy search якщо мало результатiв
        if len(results) < 5:
            fuzzy_results = self._fuzzy_search_in_db(ingredient, limit=limit - len(results))
            for drug in fuzzy_results:
                if drug.get("id") not in seen_ids:
                    seen_ids.add(drug.get("id"))
                    results.append(drug)

        # Шукаємо в FDA за substance
        if len(results) < limit // 2:
            for variant in variants[:2]:
                fda_results = self.fda_client.search_by_substance(
                    variant, limit=limit - len(results)
                )
                if fda_results:
                    save_fda_results_to_db(fda_results, self.db_path)
                    for drug in fda_results:
                        if not any(r.get("trade_name") == drug.get("trade_name") for r in results):
                            results.append(drug)

        results = self._enrich_with_status(results)

        # Перевiряємо на схожi INN
        response = {
            "results": results[:limit],
            "variants_used": variants,
            "suggestion": None,
            "warnings": []
        }

        # Пропозицiя виправлення якщо немає результатiв
        if not results and self._known_inns:
            suggestion = suggest_corrections(ingredient, self._known_inns, threshold=0.5)
            if suggestion:
                response["suggestion"] = suggestion

        return response

    def suggest(self, query: str, limit: int = 10) -> List[str]:
        """
        Автодоповнення для пошукового поля.
        Пiдтримує транслiтерацiю.
        """
        if not query or len(query) < Config.MIN_SEARCH_LENGTH:
            return []

        # Отримуємо варiанти запиту
        variants = get_search_variants(query)

        suggestions = set()

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            for variant in variants:
                # Пошук по trade_name
                cursor.execute("""
                    SELECT DISTINCT trade_name FROM drugs
                    WHERE LOWER(trade_name) LIKE ?
                    LIMIT ?
                """, (f"{variant.lower()}%", limit))

                for row in cursor.fetchall():
                    if row[0]:
                        suggestions.add(row[0])

                # Пошук по INN
                if len(suggestions) < limit:
                    cursor.execute("""
                        SELECT DISTINCT inn FROM drugs
                        WHERE LOWER(inn) LIKE ? AND inn IS NOT NULL
                        LIMIT ?
                    """, (f"{variant.lower()}%", limit - len(suggestions)))

                    for row in cursor.fetchall():
                        if row[0]:
                            suggestions.add(row[0])

        return sorted(list(suggestions))[:limit]

    def find_similar_drugs(self, name: str, limit: int = 5) -> List[Tuple[str, float]]:
        """
        Знайти препарати зi схожими назвами.
        Корисно для попередження користувача.

        Returns:
            Список кортежiв (назва, вiдсоток_схожостi)
        """
        if not self._known_names:
            return []

        return find_similar_names(name, self._known_names, threshold=0.7, max_results=limit)


# Глобальний екземпляр
_search_service = None


def get_search_service(db_path=None) -> SearchService:
    """Отримати екземпляр SearchService (singleton)."""
    global _search_service
    if _search_service is None:
        _search_service = SearchService(db_path)
    return _search_service
