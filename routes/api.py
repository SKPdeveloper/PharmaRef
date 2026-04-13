"""
REST API ендпоiнти для PharmaRef.
"""

from flask import Blueprint, jsonify, request

from services.search_service import get_search_service
from services.analog_finder import get_analog_finder
from services.status_resolver import get_status_resolver
from services.db import get_db_info
from services.text_processor import find_similar_names, get_search_variants
from services.ai_service import get_ai_service


api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/search")
def api_search():
    """
    GET /api/search - Головний пошуковий ендпоiнт.

    Параметри:
        q: Пошуковий запит (обов'язковий, мiн. 3 символи)
        mode: Режим пошуку (name|disease|ingredient), за замовчуванням "name"
        limit: Максимальна кiлькiсть результатiв (за замовчуванням 50)

    Повертає:
        JSON з:
        - results: масив знайдених препаратiв
        - suggestion: пропозицiя виправлення (якщо є помилка в запитi)
        - warnings: попередження про схожi назви препаратiв
        - variants_used: якi варiанти запиту використано (транслiтерацiя)
    """
    query = request.args.get("q", "").strip()
    mode = request.args.get("mode", "name").lower()
    limit = request.args.get("limit", 50, type=int)

    if not query:
        return jsonify({"error": "Параметр 'q' є обов'язковим"}), 400

    if len(query) < 3:
        return jsonify({"error": "Запит повинен мiстити мiнiмум 3 символи"}), 400

    if limit < 1 or limit > 100:
        limit = 50

    search_service = get_search_service()

    if mode == "name":
        search_result = search_service.search_by_name(query, limit=limit)
    elif mode == "disease":
        search_result = search_service.search_by_disease(query, limit=limit)
    elif mode == "ingredient":
        search_result = search_service.search_by_ingredient(query, limit=limit)
    else:
        return jsonify({"error": f"Невiдомий режим пошуку: {mode}"}), 400

    return jsonify({
        "query": query,
        "mode": mode,
        "count": len(search_result.get("results", [])),
        "results": search_result.get("results", []),
        "suggestion": search_result.get("suggestion"),
        "warnings": search_result.get("warnings", []),
        "variants_used": search_result.get("variants_used", []),
        "ai_analysis": search_result.get("ai_analysis")
    })


@api_bp.route("/suggest")
def api_suggest():
    """
    GET /api/suggest - Автодоповнення для пошукового поля.

    Параметри:
        q: Частковий запит (мiн. 3 символи)
        limit: Кiлькiсть пiдказок (за замовчуванням 10)

    Повертає:
        JSON масив пiдказок
    """
    query = request.args.get("q", "").strip()
    limit = request.args.get("limit", 10, type=int)

    if len(query) < 3:
        return jsonify([])

    search_service = get_search_service()
    suggestions = search_service.suggest(query, limit=limit)

    return jsonify(suggestions)


@api_bp.route("/similar")
def api_similar():
    """
    GET /api/similar - Знайти схожi назви препаратiв.

    Параметри:
        name: Назва для порiвняння
        limit: Кiлькiсть результатiв (за замовчуванням 5)

    Повертає:
        JSON масив схожих назв з вiдсотком схожостi
    """
    name = request.args.get("name", "").strip()
    limit = request.args.get("limit", 5, type=int)

    if not name or len(name) < 3:
        return jsonify([])

    search_service = get_search_service()
    similar = search_service.find_similar_drugs(name, limit=limit)

    return jsonify([
        {"name": n, "similarity": round(s * 100, 1)}
        for n, s in similar
    ])


@api_bp.route("/transliterate")
def api_transliterate():
    """
    GET /api/transliterate - Отримати варiанти транслiтерацiї.

    Параметри:
        q: Текст для транслiтерацiї

    Повертає:
        JSON з варiантами
    """
    query = request.args.get("q", "").strip()

    if not query:
        return jsonify({"variants": []})

    variants = get_search_variants(query)

    return jsonify({
        "original": query,
        "variants": variants
    })


@api_bp.route("/explain")
def api_explain():
    """
    GET /api/explain - AI пояснення препарату простою мовою.

    Параметри:
        name: Назва препарату
        inn: МНН (опцiонально)

    Повертає:
        JSON з поясненням
    """
    name = request.args.get("name", "").strip()
    inn = request.args.get("inn", "").strip()

    if not name:
        return jsonify({"error": "Параметр 'name' є обов'язковим"}), 400

    ai = get_ai_service()
    if not ai.is_available():
        return jsonify({"error": "AI сервiс недоступний", "available": False}), 503

    drug = {
        "trade_name": name,
        "inn": inn
    }

    explanation = ai.explain_drug(drug)

    if explanation:
        return jsonify({
            "name": name,
            "explanation": explanation,
            "available": True
        })
    else:
        return jsonify({"error": "Не вдалося отримати пояснення", "available": True}), 500


@api_bp.route("/ai/status")
def api_ai_status():
    """
    GET /api/ai/status - Перевiрка статусу AI сервiсу.

    Повертає:
        JSON з iнформацiєю про доступнiсть та активний провайдер
    """
    ai = get_ai_service()
    return jsonify({
        "available": ai.is_available(),
        "provider": ai.get_active_provider(),
        "providers_order": ["groq", "openrouter", "gemini"]
    })


@api_bp.route("/analogs")
def api_analogs():
    """
    GET /api/analogs - Пошук аналогiв.

    Параметри:
        inn: МНН (мiжнародна непатентована назва)
        atc: ATC код (опцiонально)
        exclude: Торгова назва для виключення (опцiонально)
        limit: Лiмiт результатiв (за замовчуванням 20)

    Повертає:
        JSON з аналогами за INN та ATC
    """
    inn = request.args.get("inn", "").strip()
    atc_code = request.args.get("atc", "").strip()
    exclude = request.args.get("exclude", "").strip()
    limit = request.args.get("limit", 20, type=int)

    if not inn and not atc_code:
        return jsonify({"error": "Потрiбен параметр 'inn' або 'atc'"}), 400

    analog_finder = get_analog_finder()
    result = analog_finder.find_analogs(
        inn=inn or None,
        atc_code=atc_code or None,
        trade_name=exclude or None,
        limit=limit
    )

    return jsonify(result)


@api_bp.route("/status")
def api_status():
    """
    GET /api/status - Отримати правовий статус речовини.

    Параметри:
        substance: Назва речовини (обов'язковий)

    Повертає:
        JSON з iнформацiєю про статус
    """
    substance = request.args.get("substance", "").strip()

    if not substance:
        return jsonify({"error": "Параметр 'substance' є обов'язковим"}), 400

    status_resolver = get_status_resolver()
    result = status_resolver.get_status_for_substance(substance)

    return jsonify(result)


@api_bp.route("/db/info")
def api_db_info():
    """
    GET /api/db/info - Iнформацiя про базу даних.

    Повертає:
        JSON з кiлькiстю записiв та датою оновлення DRLZ
    """
    info = get_db_info()
    return jsonify(info)


@api_bp.errorhandler(404)
def api_not_found(e):
    """Обробник 404 для API."""
    return jsonify({"error": "Ендпоiнт не знайдено"}), 404


@api_bp.errorhandler(500)
def api_server_error(e):
    """Обробник 500 для API."""
    return jsonify({"error": "Внутрiшня помилка сервера"}), 500
