"""Тексты интерфейса на двух языках.

Шаблон — строка с подстановками `{name}` и `{name:word}`: вторая форма ставит
слово `word` в нужном числе для значения `name` («5 прогонов», «5 runs»).
Тот же каталог уходит в дашборд, и страница форматирует его тем же правилом —
источник текстов один.
"""

import re

from .messages import MESSAGES, WORDS

LANGS = ("ru", "en")
DEFAULT_LANG = "ru"

_lang = DEFAULT_LANG
PLACEHOLDER = re.compile(r"\{(\w+)(?::(\w+))?\}")


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGS else DEFAULT_LANG


def get_lang() -> str:
    return _lang


def plural_index(n: int, lang: str) -> int:
    """Номер формы слова: русский — три формы (1, 2–4, 5+), английский — две."""
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return 0
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return 1
        return 2
    return 0 if n == 1 else 1


def word(key: str, n: int, lang: str | None = None) -> str:
    lang = lang or _lang
    forms = WORDS[key][lang]
    return forms[min(plural_index(n, lang), len(forms) - 1)]


def render(template: str, params: dict, lang: str) -> str:
    def sub(m: re.Match) -> str:
        value = params.get(m.group(1), m.group(0))
        return word(m.group(2), value, lang) if m.group(2) else str(value)
    return PLACEHOLDER.sub(sub, template)


def t(key: str, /, lang: str | None = None, **params) -> str:
    """Текст по ключу. Нет перевода — русский; нет ключа — сам ключ (видно в выводе).

    key — только позиционный: подстановка с именем {key} (например, имя настройки)
    не должна с ним конфликтовать.
    """
    lang = lang or _lang
    entry = MESSAGES.get(key)
    if entry is None:
        return key
    return render(entry.get(lang) or entry[DEFAULT_LANG], params, lang)


def catalog() -> dict:
    """Каталог для дашборда: тексты и формы слов обоих языков."""
    return {"messages": MESSAGES, "words": WORDS, "default": _lang}
