"""
Модуль обробки тексту для пошуку.
Транслiтерацiя, fuzzy matching, перевiрка схожих назв.
"""

from typing import List, Tuple, Optional
import re


# Таблицi транслiтерацiї українська/росiйська <-> латиниця
# Базується на стандартi транслiтерацiї + фармацевтичнi особливостi

CYRILLIC_TO_LATIN = {
    # Українська
    'а': 'a', 'б': 'b', 'в': 'v', 'г': 'h', 'ґ': 'g',
    'д': 'd', 'е': 'e', 'є': 'ye', 'ж': 'zh', 'з': 'z',
    'и': 'y', 'і': 'i', 'ї': 'yi', 'й': 'y', 'к': 'k',
    'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o', 'п': 'p',
    'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
    'х': 'kh', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'shch',
    'ь': '', 'ю': 'yu', 'я': 'ya',
    # Росiйська (додатковi)
    'ы': 'y', 'э': 'e', 'ё': 'yo', 'ъ': '',
}

# Фармацевтичнi варiанти транслiтерацiї (латиниця -> кирилиця)
# Один латинський варiант може мати кiлька кириличних
LATIN_TO_CYRILLIC_VARIANTS = {
    'ph': ['ф'],
    'f': ['ф'],
    'th': ['т'],
    'c': ['ц', 'к', 'с'],  # citalopram -> циталопрам, cocaine -> кокаїн
    'x': ['кс'],
    'qu': ['кв'],
    'q': ['к'],
    'w': ['в'],
    'y': ['i', 'и', 'й'],
    'j': ['дж', 'й'],
    'ch': ['ч', 'х'],  # chlor -> хлор, но change -> ченж
    'sh': ['ш'],
    'zh': ['ж'],
    'sch': ['ш', 'сх'],
    'kh': ['х'],
    'ts': ['ц'],
    'tz': ['ц'],
    'a': ['а', 'е'],  # варiацiї вимови
    'e': ['е', 'i', 'є'],
    'i': ['i', 'и', 'ай'],
    'o': ['о', 'а'],  # metoprolol -> метопролол
    'u': ['у', 'ю'],
    'b': ['б'],
    'd': ['д'],
    'g': ['г', 'ґ', 'дж'],
    'h': ['г', 'х'],
    'k': ['к'],
    'l': ['л'],
    'm': ['м'],
    'n': ['н'],
    'p': ['п'],
    'r': ['р'],
    's': ['с', 'з'],  # диазепам
    't': ['т'],
    'v': ['в'],
    'z': ['з', 'ц'],
}

# Вiдомi фармацевтичнi назви та їх транслiтерацiї
# Для випадкiв коли стандартна транслiтерацiя не працює
PHARMA_TRANSLATIONS = {
    # Кирилиця -> латиниця (вiдомi бренди та речовини)
    'виагра': ['viagra', 'sildenafil'],
    'вiагра': ['viagra', 'sildenafil'],
    'ефедрин': ['ephedrine', 'efedrin'],
    'ефедрін': ['ephedrine', 'efedrin'],
    'парацетамол': ['paracetamol', 'acetaminophen'],
    'аспiрин': ['aspirin'],
    'аспірін': ['aspirin'],
    'аспирин': ['aspirin'],
    'iбупрофен': ['ibuprofen'],
    'ібупрофен': ['ibuprofen'],
    'ибупрофен': ['ibuprofen'],
    'диклофенак': ['diclofenac'],
    'амоксицилiн': ['amoxicillin'],
    'амоксицилін': ['amoxicillin'],
    'омепразол': ['omeprazole'],
    'метформiн': ['metformin'],
    'метформін': ['metformin'],
    'лоратадин': ['loratadine'],
    'цетиризин': ['cetirizine'],
    'сiльденафiл': ['sildenafil'],
    'сільденафіл': ['sildenafil'],
    'силденафил': ['sildenafil'],
    'тадалафiл': ['tadalafil'],
    'тадалафіл': ['tadalafil'],
    'морфiн': ['morphine'],
    'морфін': ['morphine'],
    'кодеїн': ['codeine'],
    'кодеин': ['codeine'],
    'трамадол': ['tramadol'],
    'фентанiл': ['fentanyl'],
    'фентаніл': ['fentanyl'],
    'оксикодон': ['oxycodone'],
    'метадон': ['methadone'],
    'героїн': ['heroin'],
    'героин': ['heroin'],
    'кокаїн': ['cocaine'],
    'кокаин': ['cocaine'],
    'амфетамiн': ['amphetamine'],
    'амфетамін': ['amphetamine'],
    'метамфетамiн': ['methamphetamine'],
    'метамфетамін': ['methamphetamine'],
}

# Типовi фармацевтичнi суфiкси та їх варiанти
PHARMA_SUFFIXES = {
    # Латинськi -> можливi кириличнi варiанти
    'ol': ['ол'],
    'il': ['iл', 'ил'],
    'al': ['ал'],
    'in': ['iн', 'ин'],
    'an': ['ан'],
    'en': ['ен'],
    'one': ['он'],
    'ine': ['iн', 'ин'],
    'ate': ['ат'],
    'ide': ['iд', 'ид'],
    'ase': ['аза'],
    'ose': ['оза'],
    'mab': ['маб'],  # моноклональнi антитiла
    'nib': ['нiб', 'ниб'],  # iнгiбiтори
    'vir': ['вiр', 'вир'],  # противiруснi
    'cillin': ['цилiн', 'цилин'],
    'mycin': ['мiцин', 'мицин'],
    'statin': ['статин'],
    'pril': ['прил'],
    'sartan': ['сартан'],
    'dipine': ['дипiн', 'дипин'],
    'olol': ['олол'],
    'azole': ['азол'],
    'prazole': ['празол'],
    'setron': ['сетрон'],
    'triptan': ['триптан'],
}


def normalize_text(text: str) -> str:
    """
    Нормалiзацiя тексту: нижнiй регiстр, видалення зайвих символiв.
    """
    if not text:
        return ""
    # Нижнiй регiстр
    text = text.lower().strip()
    # Видаляємо все крiм букв, цифр та пробiлiв
    text = re.sub(r'[^\w\s]', '', text, flags=re.UNICODE)
    # Замiнюємо множиннi пробiли на один
    text = re.sub(r'\s+', ' ', text)
    return text


def is_cyrillic(text: str) -> bool:
    """Перевiрка чи текст мiстить кирилицю."""
    return bool(re.search(r'[а-яіїєґёыэ]', text, re.IGNORECASE))


def is_latin(text: str) -> bool:
    """Перевiрка чи текст мiстить латиницю."""
    return bool(re.search(r'[a-z]', text, re.IGNORECASE))


def cyrillic_to_latin(text: str) -> str:
    """
    Транслiтерацiя кирилицi в латиницю.
    """
    result = []
    text_lower = text.lower()

    for char in text_lower:
        if char in CYRILLIC_TO_LATIN:
            result.append(CYRILLIC_TO_LATIN[char])
        else:
            result.append(char)

    return ''.join(result)


def latin_to_cyrillic_variants(text: str) -> List[str]:
    """
    Генерує можливi кириличнi варiанти латинського тексту.
    Повертає список варiантiв (може бути багато через неоднозначнiсть).
    """
    text_lower = text.lower()

    # Спочатку замiнюємо багатосимвольнi комбiнацiї
    multi_char = ['sch', 'shch', 'kh', 'zh', 'sh', 'ch', 'th', 'ph', 'qu', 'ts', 'tz']
    multi_char.sort(key=len, reverse=True)  # Довшi спочатку

    variants = [text_lower]

    for combo in multi_char:
        new_variants = []
        for variant in variants:
            if combo in variant:
                replacements = LATIN_TO_CYRILLIC_VARIANTS.get(combo, [combo])
                for repl in replacements:
                    new_variants.append(variant.replace(combo, repl, 1))
            else:
                new_variants.append(variant)
        variants = new_variants if new_variants else variants

    # Потiм замiнюємо односимвольнi
    final_variants = []
    for variant in variants:
        result = []
        for char in variant:
            if char in LATIN_TO_CYRILLIC_VARIANTS:
                # Беремо перший варiант (найбiльш ймовiрний)
                result.append(LATIN_TO_CYRILLIC_VARIANTS[char][0])
            else:
                result.append(char)
        final_variants.append(''.join(result))

    # Видаляємо дублiкати
    return list(set(final_variants))


def get_search_variants(query: str) -> List[str]:
    """
    Генерує всi варiанти пошукового запиту для пошуку в БД.
    Включає оригiнал, транслiтерацiю, та основнi варiацiї.
    """
    query_normalized = normalize_text(query)
    if not query_normalized:
        return []

    variants = {query_normalized}

    # Перевiряємо вiдомi фармацевтичнi назви
    if query_normalized in PHARMA_TRANSLATIONS:
        variants.update(PHARMA_TRANSLATIONS[query_normalized])

    if is_cyrillic(query_normalized):
        # Кирилиця -> латиниця (стандартна транслiтерацiя)
        latin = cyrillic_to_latin(query_normalized)
        variants.add(latin)

        # Додатковi варiанти для фармацевтичних назв
        # "і" може бути "i" або "y"
        latin_alt = latin.replace('i', 'y')
        if latin_alt != latin:
            variants.add(latin_alt)

        # "ф" може бути "f" або "ph"
        latin_ph = latin.replace('f', 'ph')
        if latin_ph != latin:
            variants.add(latin_ph)

    elif is_latin(query_normalized):
        # Латиниця -> кирилицi
        cyrillic_variants = latin_to_cyrillic_variants(query_normalized)
        variants.update(cyrillic_variants)

    # Варiанти без подвоєних букв
    for v in list(variants):
        no_double = re.sub(r'(.)\1', r'\1', v)
        if no_double != v:
            variants.add(no_double)

    # Верхнiй регiстр (DRLZ зберiгає у верхньому)
    for v in list(variants):
        variants.add(v.upper())

    return list(variants)


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Обчислення вiдстанi Левенштейна мiж двома рядками.
    Це кiлькiсть односимвольних змiн (вставка, видалення, замiна)
    для перетворення одного рядка в iнший.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)

    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # вартiсть вставки, видалення, замiни
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_ratio(s1: str, s2: str) -> float:
    """
    Коефiцiєнт схожостi двох рядкiв (0.0 - 1.0).
    1.0 = iдентичнi, 0.0 = повнiстю рiзнi.
    """
    if not s1 or not s2:
        return 0.0

    s1 = normalize_text(s1)
    s2 = normalize_text(s2)

    if s1 == s2:
        return 1.0

    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))

    return 1.0 - (distance / max_len)


def find_similar_names(query: str, names: List[str], threshold: float = 0.7,
                       max_results: int = 5) -> List[Tuple[str, float]]:
    """
    Знайти схожi назви в списку.

    Args:
        query: Пошуковий запит
        names: Список назв для порiвняння
        threshold: Мiнiмальний поріг схожостi (0.0-1.0)
        max_results: Максимальна кiлькiсть результатiв

    Returns:
        Список кортежiв (назва, коефiцiєнт_схожостi), вiдсортований за схожiстю
    """
    query_normalized = normalize_text(query)
    query_latin = cyrillic_to_latin(query_normalized) if is_cyrillic(query_normalized) else query_normalized

    results = []

    for name in names:
        name_normalized = normalize_text(name)
        name_latin = cyrillic_to_latin(name_normalized) if is_cyrillic(name_normalized) else name_normalized

        # Порiвнюємо в обох варiантах (оригiнал та транслiтерацiя)
        ratio1 = similarity_ratio(query_normalized, name_normalized)
        ratio2 = similarity_ratio(query_latin, name_latin)
        ratio = max(ratio1, ratio2)

        if ratio >= threshold and ratio < 1.0:  # Виключаємо точнi збiги
            results.append((name, ratio))

    # Сортуємо за схожiстю (найбiльш схожi спочатку)
    results.sort(key=lambda x: x[1], reverse=True)

    return results[:max_results]


def check_dangerous_similarity(query: str, found_name: str, all_names: List[str],
                               similarity_threshold: float = 0.85) -> List[dict]:
    """
    Перевiрка на небезпечно схожi назви препаратiв.
    Попереджає користувача якщо є препарати з дуже схожими назвами.

    Args:
        query: Оригiнальний запит користувача
        found_name: Назва знайденого препарату
        all_names: Всi назви в базi
        similarity_threshold: Порiг для попередження

    Returns:
        Список попереджень з iнформацiєю про схожi препарати
    """
    warnings = []
    query_normalized = normalize_text(query)
    found_normalized = normalize_text(found_name)

    for name in all_names:
        name_normalized = normalize_text(name)

        # Пропускаємо знайдений препарат
        if name_normalized == found_normalized:
            continue

        ratio = similarity_ratio(found_normalized, name_normalized)

        # Якщо назви дуже схожi - попереджаємо
        if ratio >= similarity_threshold:
            # Визначаємо рiзницю
            diff = get_name_difference(found_name, name)

            warnings.append({
                "similar_name": name,
                "similarity": round(ratio * 100, 1),
                "difference": diff,
                "warning": f"Увага! Iснує препарат з схожою назвою: {name}. "
                          f"Переконайтесь, що ви шукаєте саме {found_name}."
            })

    return warnings


def get_name_difference(name1: str, name2: str) -> str:
    """
    Опис рiзницi мiж двома назвами для користувача.
    """
    n1 = normalize_text(name1)
    n2 = normalize_text(name2)

    if len(n1) != len(n2):
        return f"рiзна довжина ({len(n1)} vs {len(n2)} символiв)"

    diff_positions = []
    for i, (c1, c2) in enumerate(zip(n1, n2)):
        if c1 != c2:
            diff_positions.append(f"позицiя {i+1}: '{c1}' vs '{c2}'")

    if diff_positions:
        return "; ".join(diff_positions)

    return "вiдмiнностi у регiстрi або пробiлах"


def suggest_corrections(query: str, known_names: List[str],
                        threshold: float = 0.6) -> Optional[dict]:
    """
    Пропозицiя виправлення для можливо неправильно написаного запиту.

    Args:
        query: Запит користувача
        known_names: Список вiдомих назв
        threshold: Мiнiмальний порiг схожостi

    Returns:
        Словник з пропозицiєю або None
    """
    query_normalized = normalize_text(query)

    # Шукаємо найбiльш схожу назву
    best_match = None
    best_ratio = 0.0

    for name in known_names:
        ratio = similarity_ratio(query_normalized, normalize_text(name))
        if ratio > best_ratio and ratio >= threshold and ratio < 1.0:
            best_ratio = ratio
            best_match = name

    if best_match:
        return {
            "original": query,
            "suggestion": best_match,
            "confidence": round(best_ratio * 100, 1),
            "message": f"Можливо, ви мали на увазi: {best_match}?"
        }

    return None


class TextProcessor:
    """
    Клас для обробки тексту в контекстi пошуку лiкiв.
    Кешує данi для швидшої роботи.
    """

    def __init__(self):
        self._known_names_cache = None
        self._known_inns_cache = None

    def set_known_names(self, names: List[str]):
        """Встановити список вiдомих торгових назв."""
        self._known_names_cache = [normalize_text(n) for n in names if n]

    def set_known_inns(self, inns: List[str]):
        """Встановити список вiдомих МНН."""
        self._known_inns_cache = [normalize_text(i) for i in inns if i]

    def process_query(self, query: str) -> dict:
        """
        Повна обробка пошукового запиту.

        Returns:
            Словник з:
            - normalized: нормалiзований запит
            - variants: варiанти для пошуку (транслiтерацiя)
            - suggestion: пропозицiя виправлення (якщо є)
            - is_cyrillic: чи запит кирилицею
            - is_latin: чи запит латиницею
        """
        normalized = normalize_text(query)
        variants = get_search_variants(query)

        result = {
            "original": query,
            "normalized": normalized,
            "variants": variants,
            "is_cyrillic": is_cyrillic(query),
            "is_latin": is_latin(query),
            "suggestion": None
        }

        # Шукаємо пропозицiю виправлення
        all_known = []
        if self._known_names_cache:
            all_known.extend(self._known_names_cache)
        if self._known_inns_cache:
            all_known.extend(self._known_inns_cache)

        if all_known:
            suggestion = suggest_corrections(query, all_known)
            if suggestion:
                result["suggestion"] = suggestion

        return result

    def check_result_safety(self, query: str, found_drugs: List[dict]) -> List[dict]:
        """
        Перевiрка безпеки результатiв - попередження про схожi назви.

        Args:
            query: Оригiнальний запит
            found_drugs: Список знайдених препаратiв

        Returns:
            Список попереджень
        """
        if not found_drugs or not self._known_names_cache:
            return []

        warnings = []

        for drug in found_drugs[:5]:  # Перевiряємо перших 5
            trade_name = drug.get("trade_name", "")
            if trade_name:
                drug_warnings = check_dangerous_similarity(
                    query, trade_name, self._known_names_cache
                )
                warnings.extend(drug_warnings)

        # Видаляємо дублiкати
        seen = set()
        unique_warnings = []
        for w in warnings:
            key = w.get("similar_name", "")
            if key not in seen:
                seen.add(key)
                unique_warnings.append(w)

        return unique_warnings[:3]  # Максимум 3 попередження


# Глобальний екземпляр
_text_processor = None


def get_text_processor() -> TextProcessor:
    """Отримати екземпляр TextProcessor (singleton)."""
    global _text_processor
    if _text_processor is None:
        _text_processor = TextProcessor()
    return _text_processor
