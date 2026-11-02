"""Начальная форма слова и группы синонимов для поиска."""

import re
from functools import lru_cache
from pathlib import Path

try:
    import pymorphy3
    _MORPH = pymorphy3.MorphAnalyzer()
except Exception:
    _MORPH = None

_WORD = re.compile(r"[a-zа-яё0-9]+(?:-[a-zа-яё0-9]+)*", re.I)
# Термины, которые словарь принимает за обычные слова: «Ид» → «ида», «сверх-я» → «сверхть».
_KEEP = {
    "ид": "ид",
    "эго": "эго",
    "суперэго": "суперэго",
    "сверхя": "сверхя",
}


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    word = word.lower().replace("ё", "е").replace("-", "")
    if word in _KEEP:
        return _KEEP[word]
    if not re.search("[а-я]", word) or _MORPH is None:
        return word
    return _MORPH.parse(word)[0].normal_form.replace("ё", "е")


def is_weak_word(text: str) -> bool:
    """Местоимения и частицы слишком частые, чтобы искать их по всей базе."""
    words = (text or "").split()
    if len(words) != 1 or _MORPH is None or not re.search("[а-я]", words[0]):
        return False
    parsed = _MORPH.parse(words[0])
    if not parsed:
        return False
    tag = parsed[0].tag
    return "NPRO" in tag or "PRCL" in tag


def lemmatize(text: str) -> str:
    return " ".join(lemma(word) for word in _WORD.findall(text or ""))


def load_synonyms(path) -> tuple[list, dict, set]:
    """Группы, словарь «лемма → номер» и слабые слова (тильда в файле или местоимение)."""
    groups = []
    index = {}
    weak = set()
    file = Path(path)
    if not file.is_file():
        return groups, index, weak
    for line in file.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = []
        for piece in raw.split(","):
            piece = piece.strip()
            marked = piece.startswith("~")
            if marked:
                piece = piece[1:].strip()
            folded = lemmatize(piece)
            if not folded or folded in parts:
                continue
            parts.append(folded)
            if marked or is_weak_word(folded):
                weak.add(folded)
        if not parts:
            continue
        number = len(groups)
        groups.append(parts)
        for part in parts:
            index.setdefault(part, number)
    return groups, index, weak


def ensure_synonyms(path) -> None:
    file = Path(path)
    if file.is_file():
        return
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        "\n".join([
            "# Одна строка — одна группа синонимов.",
            "# Тильда помечает слабое слово: оно не ищется по всей базе само по себе.",
            "ид, ~оно, id",
            "эго, ~я, ego",
            "суперэго, сверх-я, сверхя, superego",
            "когнитивное искажение, ошибка мышления",
            "",
        ]),
        encoding="utf-8",
    )
