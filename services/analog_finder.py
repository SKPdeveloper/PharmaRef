"""
Модуль пошуку аналогiв лiкарських засобiв.
Знаходить аналоги за INN та ATC кодом.
"""

from typing import List, Optional

from services.db import get_db_connection
from services.fda_client import FDAClient, save_fda_results_to_db
from services.status_resolver import get_status_resolver


class AnalogFinder:
    """Знаходить аналоги лiкарських засобiв."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.fda_client = FDAClient(db_path)
        self.status_resolver = get_status_resolver(db_path)

    def find_by_inn(self, inn: str, exclude_trade_name: str = None, limit: int = 20) -> List[dict]:
        """
        Знайти аналоги за МНН (International Nonproprietary Name).

        Args:
            inn: Мiжнародна непатентована назва
            exclude_trade_name: Виключити цю торгову назву з результатiв
            limit: Максимальна кiлькiсть результатiв

        Returns:
            Список аналогiв
        """
        if not inn:
            return []

        results = []
        inn_lower = inn.lower()

        # Пошук в локальнiй БД
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            if exclude_trade_name:
                cursor.execute("""
                    SELECT * FROM drugs
                    WHERE LOWER(inn) = ? AND trade_name != ?
                    ORDER BY source, trade_name
                    LIMIT ?
                """, (inn_lower, exclude_trade_name, limit))
            else:
                cursor.execute("""
                    SELECT * FROM drugs
                    WHERE LOWER(inn) = ?
                    ORDER BY source, trade_name
                    LIMIT ?
                """, (inn_lower, limit))

            for row in cursor.fetchall():
                results.append(dict(row))

        # Додатково шукаємо в FDA
        if len(results) < limit:
            fda_results = self.fda_client.search_by_substance(inn, limit=limit - len(results))
            if fda_results:
                save_fda_results_to_db(fda_results, self.db_path)
                for fda_drug in fda_results:
                    trade_name = fda_drug.get("trade_name")
                    if exclude_trade_name and trade_name == exclude_trade_name:
                        continue
                    if not any(r.get("trade_name") == trade_name for r in results):
                        results.append(fda_drug)

        # Додаємо правовий статус
        for drug in results:
            status, details = self.status_resolver.resolve(drug)
            drug["legal_status"] = status
            drug["legal_details"] = details

        return results[:limit]

    def find_by_atc(self, atc_code: str, exclude_trade_name: str = None, limit: int = 20) -> List[dict]:
        """
        Знайти аналоги за ATC кодом (фармакологiчна група).

        Args:
            atc_code: ATC код (мiнiмум перший рiвень, напр. "C09")
            exclude_trade_name: Виключити цю торгову назву
            limit: Максимальна кiлькiсть результатiв

        Returns:
            Список препаратiв з тiєї ж фармакологiчної групи
        """
        if not atc_code:
            return []

        results = []

        # Визначаємо рiвень ATC для пошуку
        # ATC коди: A (1 рiвень), A10 (2), A10B (3), A10BA (4), A10BA02 (5)
        atc_prefix = atc_code[:4] if len(atc_code) >= 4 else atc_code

        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()

            if exclude_trade_name:
                cursor.execute("""
                    SELECT * FROM drugs
                    WHERE atc_code LIKE ? AND trade_name != ?
                    ORDER BY atc_code, trade_name
                    LIMIT ?
                """, (f"{atc_prefix}%", exclude_trade_name, limit))
            else:
                cursor.execute("""
                    SELECT * FROM drugs
                    WHERE atc_code LIKE ?
                    ORDER BY atc_code, trade_name
                    LIMIT ?
                """, (f"{atc_prefix}%", limit))

            for row in cursor.fetchall():
                results.append(dict(row))

        # Додаємо правовий статус
        for drug in results:
            status, details = self.status_resolver.resolve(drug)
            drug["legal_status"] = status
            drug["legal_details"] = details

        return results

    def find_analogs(self, drug_id: int = None, inn: str = None, atc_code: str = None,
                     trade_name: str = None, limit: int = 20) -> dict:
        """
        Комплексний пошук аналогiв.
        Шукає як за INN, так i за ATC кодом.

        Args:
            drug_id: ID лiку в БД
            inn: МНН (якщо вiдомо)
            atc_code: ATC код (якщо вiдомо)
            trade_name: Торгова назва для виключення
            limit: Лiмiт для кожного типу пошуку

        Returns:
            Словник з результатами:
            - by_inn: аналоги за INN
            - by_atc: аналоги за ATC
        """
        # Якщо переданий drug_id, отримуємо данi лiку
        if drug_id:
            with get_db_connection(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM drugs WHERE id = ?", (drug_id,))
                row = cursor.fetchone()
                if row:
                    drug = dict(row)
                    inn = inn or drug.get("inn")
                    atc_code = atc_code or drug.get("atc_code")
                    trade_name = trade_name or drug.get("trade_name")

        result = {
            "by_inn": [],
            "by_atc": [],
            "original": {
                "inn": inn,
                "atc_code": atc_code,
                "trade_name": trade_name
            }
        }

        # Пошук за INN
        if inn:
            result["by_inn"] = self.find_by_inn(inn, exclude_trade_name=trade_name, limit=limit)

        # Пошук за ATC
        if atc_code:
            result["by_atc"] = self.find_by_atc(atc_code, exclude_trade_name=trade_name, limit=limit)

            # Виключаємо дублiкати (що вже є в by_inn)
            inn_names = {d.get("trade_name") for d in result["by_inn"]}
            result["by_atc"] = [d for d in result["by_atc"] if d.get("trade_name") not in inn_names]

        return result


# Глобальний екземпляр
_analog_finder = None


def get_analog_finder(db_path=None) -> AnalogFinder:
    """Отримати екземпляр AnalogFinder (singleton)."""
    global _analog_finder
    if _analog_finder is None:
        _analog_finder = AnalogFinder(db_path)
    return _analog_finder
