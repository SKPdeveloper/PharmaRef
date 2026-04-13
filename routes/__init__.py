"""
Модуль маршрутiв застосунку PharmaRef.
"""

from routes.api import api_bp
from routes.search import search_bp

__all__ = ["api_bp", "search_bp"]
