"""
PharmaRef - Довiдник лiкарських засобiв України.
Головна точка входу Flask застосунку.
"""

from datetime import datetime
from pathlib import Path

from flask import Flask

# Завантаження .env файлу
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass  # python-dotenv не встановлено, використовуємо системнi змiннi

from config import get_config
from services.db import init_db, init_app as init_db_app
from routes import api_bp, search_bp


def create_app(config=None):
    """
    Фабрика створення Flask застосунку.

    Args:
        config: Об'єкт конфiгурацiї (опцiонально)

    Returns:
        Flask застосунок
    """
    app = Flask(__name__)

    # Завантаження конфiгурацiї
    if config is None:
        config = get_config()

    app.config.from_object(config)

    # Додаємо шлях до БД як рядок
    app.config["DATABASE_PATH"] = str(config.DATABASE_PATH)

    # Iнiцiалiзацiя БД
    init_db_app(app)

    # Реєстрацiя blueprints
    app.register_blueprint(api_bp)
    app.register_blueprint(search_bp)

    # Контекстний процесор для шаблонiв
    @app.context_processor
    def inject_globals():
        return {
            "current_year": datetime.now().year
        }

    # Створення таблиць БД при першому запуску
    with app.app_context():
        init_db(config.DATABASE_PATH)

    return app


def main():
    """Запуск застосунку в режимi розробки."""
    app = create_app()

    print("=" * 50)
    print("PharmaRef - Довiдник лiкарських засобiв")
    print("=" * 50)
    print(f"Сервер запущено: http://localhost:5001")
    print(f"API доступний за адресою: http://localhost:5001/api")
    print("=" * 50)
    print()
    print("Доступнi ендпоiнти:")
    print("  GET /             - Головна сторiнка")
    print("  GET /search       - Пошук (веб)")
    print("  GET /api/search   - Пошук (API)")
    print("  GET /api/suggest  - Автодоповнення")
    print("  GET /api/analogs  - Пошук аналогiв")
    print("  GET /api/status   - Правовий статус")
    print("  GET /api/db/info  - Iнформацiя про БД")
    print()

    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
