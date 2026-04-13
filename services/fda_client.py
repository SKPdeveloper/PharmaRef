"""
Клiєнт для роботи з OpenFDA API.
Включає кешування запитiв на 24 години.
"""

import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

import requests

from config import Config
from services.db import get_db_connection


class FDAClient:
    """Клiєнт для OpenFDA Drug Label API."""

    def __init__(self, db_path=None):
        self.base_url = Config.FDA_API_BASE
        self.cache_ttl = Config.FDA_CACHE_TTL
        self.db_path = db_path

    def _get_cache_key(self, query: str) -> str:
        """Генерує унiкальний ключ кешу для запиту."""
        return hashlib.md5(query.encode()).hexdigest()

    def _get_cached(self, cache_key: str) -> Optional[dict]:
        """Отримати закешований результат."""
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT value FROM cache
                WHERE key = ? AND expires_at > datetime('now')
            """, (cache_key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
        return None

    def _set_cache(self, cache_key: str, value: dict):
        """Зберегти результат в кеш."""
        expires_at = datetime.now() + timedelta(seconds=self.cache_ttl)
        with get_db_connection(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache (key, value, expires_at)
                VALUES (?, ?, ?)
            """, (cache_key, json.dumps(value), expires_at))

    def _clean_expired_cache(self):
        """Видалити застарiлi записи кешу."""
        with get_db_connection(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE expires_at < datetime('now')")

    def search(self, query: str, limit: int = 10) -> list:
        """
        Пошук лiкiв в OpenFDA.

        Args:
            query: Пошуковий запит (назва, INN, показання)
            limit: Максимальна кiлькiсть результатiв

        Returns:
            Список знайдених лiкiв
        """
        cache_key = self._get_cache_key(f"{query}:{limit}")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Формуємо запит до API
        # Шукаємо по brand_name, generic_name, substance_name
        search_query = f'(openfda.brand_name:"{query}" OR openfda.generic_name:"{query}" OR openfda.substance_name:"{query}")'

        params = {
            "search": search_query,
            "limit": limit
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=30,
                headers={"User-Agent": "PharmaRef/1.0"}
            )

            if response.status_code == 404:
                # Немає результатiв
                result = []
                self._set_cache(cache_key, result)
                return result

            response.raise_for_status()
            data = response.json()

            results = self._parse_results(data.get("results", []))
            self._set_cache(cache_key, results)
            return results

        except requests.RequestException:
            # При помилцi повертаємо порожнiй список
            return []

    def search_by_indication(self, indication: str, limit: int = 10) -> list:
        """
        Пошук лiкiв за показаннями.

        Args:
            indication: Текст показання (захворювання)
            limit: Максимальна кiлькiсть результатiв
        """
        cache_key = self._get_cache_key(f"indication:{indication}:{limit}")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params = {
            "search": f'indications_and_usage:"{indication}"',
            "limit": limit
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=30,
                headers={"User-Agent": "PharmaRef/1.0"}
            )

            if response.status_code == 404:
                result = []
                self._set_cache(cache_key, result)
                return result

            response.raise_for_status()
            data = response.json()

            results = self._parse_results(data.get("results", []))
            self._set_cache(cache_key, results)
            return results

        except requests.RequestException:
            return []

    def search_by_substance(self, substance: str, limit: int = 20) -> list:
        """
        Пошук лiкiв за дiючою речовиною (для аналогiв).

        Args:
            substance: Назва дiючої речовини (INN)
            limit: Максимальна кiлькiсть результатiв
        """
        cache_key = self._get_cache_key(f"substance:{substance}:{limit}")
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        params = {
            "search": f'openfda.substance_name:"{substance}"',
            "limit": limit
        }

        try:
            response = requests.get(
                self.base_url,
                params=params,
                timeout=30,
                headers={"User-Agent": "PharmaRef/1.0"}
            )

            if response.status_code == 404:
                result = []
                self._set_cache(cache_key, result)
                return result

            response.raise_for_status()
            data = response.json()

            results = self._parse_results(data.get("results", []))
            self._set_cache(cache_key, results)
            return results

        except requests.RequestException:
            return []

    def _parse_results(self, results: list) -> list:
        """
        Витягує потрiбнi поля з результатiв OpenFDA.
        Повертає унiфiкований формат.
        """
        parsed = []
        seen_names = set()

        for item in results:
            openfda = item.get("openfda", {})

            # Беремо перше значення з кожного поля
            brand_name = self._get_first(openfda.get("brand_name"))
            generic_name = self._get_first(openfda.get("generic_name"))
            substance_name = self._get_first(openfda.get("substance_name"))

            # Унiкальний iдентифiкатор
            trade_name = brand_name or generic_name or substance_name
            if not trade_name or trade_name in seen_names:
                continue
            seen_names.add(trade_name)

            # Показання
            indications = self._get_first(item.get("indications_and_usage"))
            purpose = self._get_first(item.get("purpose"))
            if not indications and purpose:
                indications = purpose

            # set_id для зв'язку
            set_id = item.get("set_id")

            parsed.append({
                "source": "fda",
                "trade_name": trade_name,
                "inn": generic_name or substance_name,
                "atc_code": None,  # OpenFDA не надає ATC коди
                "indications": indications,
                "dispensing": None,
                "reg_number": None,
                "status": None,
                "fda_set_id": set_id,
            })

        return parsed

    def _get_first(self, value) -> Optional[str]:
        """Повертає перший елемент списку або сам рядок."""
        if isinstance(value, list) and value:
            return value[0]
        if isinstance(value, str):
            return value
        return None


def save_fda_results_to_db(results: list, db_path=None) -> int:
    """
    Зберегти результати FDA до бази даних.
    Уникає дублiкатiв за trade_name.
    """
    if not results:
        return 0

    count = 0
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        insert_sql = """
            INSERT INTO drugs (source, trade_name, inn, atc_code, indications,
                             dispensing, reg_number, status, fda_set_id)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM drugs
                WHERE trade_name = ? AND source = 'fda'
            )
        """

        for drug in results:
            cursor.execute(insert_sql, (
                drug["source"],
                drug["trade_name"],
                drug["inn"],
                drug["atc_code"],
                drug["indications"],
                drug["dispensing"],
                drug["reg_number"],
                drug["status"],
                drug["fda_set_id"],
                drug["trade_name"],  # для перевiрки дублiкатiв
            ))
            if cursor.rowcount > 0:
                count += 1

    return count
