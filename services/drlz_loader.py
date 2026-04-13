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


# Iндекси колонок в CSV файлi DRLZ (фiксованi)
# Це надiйнiше нiж пошук за назвою через проблеми з кодуванням
COLUMN_INDICES = {
    0: None,           # ID - не потрібен
    1: "trade_name",   # Торгiвельне найменування
    2: "inn",          # Мiжнародне непатентоване найменування
    3: None,           # Форма випуску
    4: "dispensing",   # Умови вiдпуску
    5: None,           # Склад (доза)
    6: "reg_number",   # Реєстрацiйне посвiдчення
    32: "atc_code",    # Код АТС
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
    Використовує iндекси колонок для надiйностi.
    """
    reader = csv.reader(
        io.StringIO(csv_content),
        delimiter=Config.DRLZ_DELIMITER
    )

    # Пропускаємо заголовок
    try:
        next(reader)
    except StopIteration:
        return

    for row in reader:
        if not row or len(row) < 5:
            continue

        drug = {
            "source": "ua",
            "trade_name": None,
            "inn": None,
            "atc_code": None,
            "indications": None,
            "dispensing": None,
            "reg_number": None,
            "status": "active",  # Все що в реєстрi - активне
            "fda_set_id": None,
        }

        # Витягуємо данi за iндексами
        for idx, field in COLUMN_INDICES.items():
            if field and idx < len(row):
                value = row[idx].strip().strip('"')
                if value:
                    drug[field] = value

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
