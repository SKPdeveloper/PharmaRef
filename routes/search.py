"""
Веб-маршрути для пошуку лiкарських засобiв.
"""

from flask import Blueprint, render_template, request
from pathlib import Path

from services.search_service import get_search_service


search_bp = Blueprint("search", __name__)


@search_bp.route("/guide")
def guide():
    """Сторiнка довiдки."""
    guide_path = Path(__file__).parent.parent / "docs" / "GUIDE.md"
    content = ""
    if guide_path.exists():
        content = guide_path.read_text(encoding="utf-8")
    return render_template("guide.html", content=content)


@search_bp.route("/")
def index():
    """Головна сторiнка з формою пошуку."""
    return render_template("index.html")


@search_bp.route("/search")
def search():
    """
    GET /search - Сторiнка результатiв пошуку.

    Параметри:
        q: Пошуковий запит
        mode: Режим пошуку (name|disease|ingredient)
    """
    query = request.args.get("q", "").strip()
    mode = request.args.get("mode", "name").lower()

    # Валiдацiя режиму
    if mode not in ("name", "disease", "ingredient"):
        mode = "name"

    results = []
    suggestion = None
    warnings = []
    variants_used = []
    ai_analysis = None
    error = None

    if query:
        if len(query) < 3:
            error = "Введiть мiнiмум 3 символи для пошуку"
        else:
            search_service = get_search_service()

            if mode == "name":
                search_result = search_service.search_by_name(query)
            elif mode == "disease":
                search_result = search_service.search_by_disease(query)
            elif mode == "ingredient":
                search_result = search_service.search_by_ingredient(query)

            results = search_result.get("results", [])
            suggestion = search_result.get("suggestion")
            warnings = search_result.get("warnings", [])
            variants_used = search_result.get("variants_used", [])
            ai_analysis = search_result.get("ai_analysis")

    # Назви режимiв для вiдображення
    mode_names = {
        "name": "за назвою",
        "disease": "за захворюванням",
        "ingredient": "за дiючою речовиною"
    }

    return render_template(
        "results.html",
        query=query,
        mode=mode,
        mode_name=mode_names.get(mode, ""),
        results=results,
        count=len(results),
        suggestion=suggestion,
        warnings=warnings,
        variants_used=variants_used,
        ai_analysis=ai_analysis,
        error=error
    )
