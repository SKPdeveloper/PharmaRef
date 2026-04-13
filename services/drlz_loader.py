"""
Завантажувач даних з реєстру DRLZ (Державний реєстр лiкарських засобiв України).
"""

import csv
import io
from datetime import datetime
from typing import Generator

import requests

from config import Config
from services.db import get_db_connection, rebuild_fts_index


# Маппiнг колонок CSV на поля бази даних
# Структура CSV може змiнюватися, тому використовуємо гнучкий пiдхiд
COLUMN_MAPPING = {
    "Торговельна назва": "trade_name",
    "Торгова назва": "trade_name",
    "МНН": "inn",
    "Код АТС": "atc_code",
    "Код АТХ": "atc_code",
    "Умови відпуску": "dispensing",
    "Умови вiдпуску": "dispensing",
    "Реєстраційний номер": "reg_number",
    "Реєстрацiйний номер": "reg_number",
    "Номер реєстрації": "reg_number",
    "Стан реєстрації": "status",
    "Стан реєстрацiї": "status",
    "Статус": "status",
}


def download_drlz_csv() -> str:
    """
    Завантажити CSV файл з сайту DRLZ.
    Повертає вмiст файлу як рядок.
    """
    response = requests.get(
        Config.DRLZ_CSV_URL,
        timeout=60,
        headers={"User-Agent": "PharmaRef/1.0"}
    )
    response.raise_for_status()
    # Декодуємо з windows-1251
    return response.content.decode(Config.DRLZ_ENCODING)


def parse_drlz_csv(csv_content: str) -> Generator[dict, None, None]:
    """
    Парсинг CSV контенту DRLZ.
    Генератор повертає словники з даними лiкiв.
    """
    reader = csv.DictReader(
        io.StringIO(csv_content),
        delimiter=Config.DRLZ_DELIMITER
    )

    # Визначаємо вiдповiднiсть колонок
    field_map = {}
    if reader.fieldnames:
        for csv_col in reader.fieldnames:
            csv_col_clean = csv_col.strip()
            for pattern, field in COLUMN_MAPPING.items():
                if pattern.lower() in csv_col_clean.lower():
                    field_map[csv_col] = field
                    break

    for row in reader:
        drug = {
            "source": "ua",
            "trade_name": None,
            "inn": None,
            "atc_code": None,
            "indications": None,  # DRLZ не мiстить показань
            "dispensing": None,
            "reg_number": None,
            "status": None,
            "fda_set_id": None,
        }

        for csv_col, db_field in field_map.items():
            value = row.get(csv_col, "").strip()
            if value:
                drug[db_field] = value

        # Пропускаємо записи без торговельної назви
        if drug["trade_name"]:
            yield drug


def load_drlz_to_db(csv_content: str = None, db_path=None) -> int:
    """
    Завантажити данi DRLZ до бази даних.
    Повертає кiлькiсть завантажених записiв.
    """
    if csv_content is None:
        csv_content = download_drlz_csv()

    count = 0
    with get_db_connection(db_path) as conn:
        cursor = conn.cursor()

        # Очищаємо старi данi UA
        cursor.execute("DELETE FROM drugs WHERE source = 'ua'")

        # Вставляємо новi данi
        insert_sql = """
            INSERT INTO drugs (source, trade_name, inn, atc_code, indications,
                             dispensing, reg_number, status, fda_set_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        for drug in parse_drlz_csv(csv_content):
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
            ))
            count += 1

        # Оновлюємо метаданi
        cursor.execute("""
            INSERT OR REPLACE INTO metadata (key, value, updated_at)
            VALUES ('drlz_updated_at', ?, CURRENT_TIMESTAMP)
        """, (datetime.now().isoformat(),))

    # Перебудовуємо FTS iндекс
    rebuild_fts_index(db_path)

    return count


def load_drlz_from_file(file_path: str, db_path=None) -> int:
    """
    Завантажити DRLZ з локального файлу.
    Корисно для тестування та офлайн роботи.
    """
    with open(file_path, "r", encoding=Config.DRLZ_ENCODING) as f:
        csv_content = f.read()
    return load_drlz_to_db(csv_content, db_path)
