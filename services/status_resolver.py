"""
Модуль визначення правового статусу лiкарських засобiв.
Прiоритет статусiв згiдно специфiкацiї.
"""

import json
from pathlib import Path
from typing import Optional, Tuple

from config import Config
from services.db import get_db_connection


# Рiвнi статусу (вiд найсуворiшого до найм'якшого)
STATUS_LEVELS = {
    "forbidden": 1,      # Заборонено в Українi (Таблиця I)
    "restricted": 2,     # Обмежений обiг (Таблиця II)
    "precursor": 3,      # Прекурсор (Таблиця III)
    "dea_i": 4,          # DEA Schedule I (тiльки США)
    "dea_ii": 5,         # DEA Schedule II
    "dea_iii": 6,        # DEA Schedule III
    "dea_iv": 7,         # DEA Schedule IV
    "dea_v": 8,          # DEA Schedule V
    "conflicting": 9,    # Конфлiкт UA/DEA статусiв
    "rx": 10,            # Рецептурний
    "otc": 11,           # Безрецептурний
}

# Конфiгурацiя бейджiв для UI
STATUS_BADGES = {
    "forbidden": {"label": "Заборонено", "color": "red", "icon": "ban"},
    "restricted": {"label": "Обмежено", "color": "orange", "icon": "exclamation-triangle"},
    "precursor": {"label": "Прекурсор", "color": "yellow", "icon": "flask"},
    "dea_i": {"label": "DEA Schedule I", "color": "red", "icon": "ban"},
    "dea_ii": {"label": "DEA Schedule II", "color": "orange", "icon": "prescription"},
    "dea_iii": {"label": "DEA Schedule III", "color": "yellow", "icon": "prescription"},
    "dea_iv": {"label": "DEA Schedule IV", "color": "blue", "icon": "prescription"},
    "dea_v": {"label": "DEA Schedule V", "color": "gray", "icon": "prescription"},
    "conflicting": {"label": "Конфлiкт статусiв", "color": "purple", "icon": "question"},
    "rx": {"label": "Рецептурний", "color": "blue", "icon": "prescription-bottle"},
    "otc": {"label": "Без рецепта", "color": "green", "icon": "check"},
}


class StatusResolver:
    """Визначає правовий статус лiкарського засобу."""

    def __init__(self, db_path=None):
        self.db_path = db_path
        self._controlled_ua = None
        self._controlled_dea = None
        self._load_controlled_substances()

    def _load_controlled_substances(self):
        """Завантажити списки контрольованих речовин з JSON."""
        data_dir = Config.DATA_DIR

        # Завантаження UA контрольованих речовин
        ua_path = data_dir / "controlled_ua.json"
        if ua_path.exists():
            with open(ua_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._controlled_ua = {}
                for table_num, table_data in data.get("tables", {}).items():
                    level = table_data.get("level", "restricted")
                    for substance in table_data.get("substances", []):
                        name_lower = substance["name"].lower()
                        name_en_lower = substance.get("name_en", "").lower()
                        self._controlled_ua[name_lower] = {
                            "table": int(table_num),
                            "list": substance.get("list"),
                            "level": level
                        }
                        if name_en_lower:
                            self._controlled_ua[name_en_lower] = {
                                "table": int(table_num),
                                "list": substance.get("list"),
                                "level": level
                            }

        # Завантаження DEA контрольованих речовин
        dea_path = data_dir / "controlled_dea.json"
        if dea_path.exists():
            with open(dea_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._controlled_dea = {}
                for schedule, schedule_data in data.get("schedules", {}).items():
                    for substance in schedule_data.get("substances", []):
                        self._controlled_dea[substance.lower()] = schedule

    def _check_ua_controlled(self, substance: str) -> Optional[dict]:
        """Перевiрка чи речовина є контрольованою в Українi."""
        if not self._controlled_ua or not substance:
            return None

        substance_lower = substance.lower()

        # Точний збiг
        if substance_lower in self._controlled_ua:
            return self._controlled_ua[substance_lower]

        # Частковий збiг (речовина може бути частиною назви)
        for controlled_name, data in self._controlled_ua.items():
            if controlled_name in substance_lower or substance_lower in controlled_name:
                return data

        return None

    def _check_dea_controlled(self, substance: str) -> Optional[str]:
        """Перевiрка чи речовина є контрольованою DEA."""
        if not self._controlled_dea or not substance:
            return None

        substance_lower = substance.lower()

        # Точний збiг
        if substance_lower in self._controlled_dea:
            return self._controlled_dea[substance_lower]

        # Частковий збiг
        for controlled_name, schedule in self._controlled_dea.items():
            if controlled_name in substance_lower or substance_lower in controlled_name:
                return schedule

        return None

    def _normalize_dispensing(self, dispensing: str) -> str:
        """Нормалiзацiя умов вiдпуску до rx/otc."""
        if not dispensing:
            return "otc"

        dispensing_lower = dispensing.lower()

        rx_markers = [
            "рецепт", "prescription", "за призначенням",
            "обмежен", "контрол", "спецiал"
        ]

        for marker in rx_markers:
            if marker in dispensing_lower:
                return "rx"

        return "otc"

    def resolve(self, drug: dict) -> Tuple[str, dict]:
        """
        Визначити правовий статус лiкарського засобу.

        Args:
            drug: Словник з даними лiку (inn, dispensing, source)

        Returns:
            Кортеж (статус, деталi)
        """
        inn = drug.get("inn", "")
        trade_name = drug.get("trade_name", "")
        dispensing = drug.get("dispensing", "")
        source = drug.get("source", "")

        # Перевiряємо по INN та торговельнiй назвi
        substances_to_check = [s for s in [inn, trade_name] if s]

        ua_status = None
        dea_status = None

        for substance in substances_to_check:
            if not ua_status:
                ua_status = self._check_ua_controlled(substance)
            if not dea_status:
                dea_status = self._check_dea_controlled(substance)

        # Прiоритет статусiв

        # 1. Заборонено в Українi (Таблиця I)
        if ua_status and ua_status.get("level") == "forbidden":
            return "forbidden", {
                "reason": f"КМУ №770, Таблиця {ua_status['table']}",
                "badge": STATUS_BADGES["forbidden"]
            }

        # 2. Обмежений обiг (Таблиця II)
        if ua_status and ua_status.get("level") == "restricted":
            return "restricted", {
                "reason": f"КМУ №770, Таблиця {ua_status['table']}",
                "badge": STATUS_BADGES["restricted"]
            }

        # 3. Прекурсор (Таблиця III)
        if ua_status and ua_status.get("level") == "precursor":
            return "precursor", {
                "reason": f"КМУ №770, Таблиця {ua_status['table']}",
                "badge": STATUS_BADGES["precursor"]
            }

        # 4. DEA Schedule (для FDA лiкiв)
        if dea_status:
            schedule_status = f"dea_{dea_status.lower()}"
            if schedule_status in STATUS_BADGES:
                return schedule_status, {
                    "reason": f"DEA Schedule {dea_status}",
                    "badge": STATUS_BADGES[schedule_status]
                }

        # 5. Конфлiкт статусiв (UA дозволено, але DEA контролює або навпаки)
        if ua_status and not dea_status and source == "fda":
            return "conflicting", {
                "reason": "Рiзний статус в UA та USA",
                "badge": STATUS_BADGES["conflicting"]
            }

        # 6. Рецептурний (за умовами вiдпуску)
        if self._normalize_dispensing(dispensing) == "rx":
            return "rx", {
                "reason": "Вiдпускається за рецептом",
                "badge": STATUS_BADGES["rx"]
            }

        # 7. Безрецептурний (за замовчуванням)
        return "otc", {
            "reason": "Безрецептурний засiб",
            "badge": STATUS_BADGES["otc"]
        }

    def get_status_for_substance(self, substance: str) -> dict:
        """
        Отримати iнформацiю про статус для окремої речовини.
        Використовується API endpoint /api/status.
        """
        ua_status = self._check_ua_controlled(substance)
        dea_status = self._check_dea_controlled(substance)

        result = {
            "substance": substance,
            "ua_controlled": ua_status is not None,
            "ua_details": ua_status,
            "dea_controlled": dea_status is not None,
            "dea_schedule": dea_status,
        }

        # Визначаємо загальний статус
        if ua_status:
            result["overall_status"] = ua_status.get("level", "restricted")
            result["badge"] = STATUS_BADGES.get(ua_status.get("level"), STATUS_BADGES["restricted"])
        elif dea_status:
            schedule_status = f"dea_{dea_status.lower()}"
            result["overall_status"] = schedule_status
            result["badge"] = STATUS_BADGES.get(schedule_status, STATUS_BADGES["rx"])
        else:
            result["overall_status"] = "not_controlled"
            result["badge"] = None

        return result


# Глобальний екземпляр для використання в iнших модулях
_resolver = None


def get_status_resolver(db_path=None) -> StatusResolver:
    """Отримати екземпляр StatusResolver (singleton)."""
    global _resolver
    if _resolver is None:
        _resolver = StatusResolver(db_path)
    return _resolver
