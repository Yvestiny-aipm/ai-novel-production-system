"""Frozen book-level character facts. Previous-scene state cannot override this."""
from __future__ import annotations
import re

CHARACTER_CANON_VERSION = 1
CHARACTER_CANON_RULE = "character_canon_v1"
CHARACTER_CANON_REASON = "character_canon_conflict"
PRONOUN_LOOKAHEAD = 48
PRONOUN_LOOKBACK = 48
SUBJECT_TA = re.compile(r"[。！？\n，；、]他")
KINSHIP_FAIL = (
    re.compile(r"你姐姐"),
    re.compile(r"姐姐林澜"),
    re.compile(r"林澜姐姐"),
    re.compile(r"林澜是她的姐姐"),
    re.compile(r"林澜是姐姐"),
    re.compile(r"姐姐是林澜"),
)
MALE_OTHERS = ("老陈", "守灯的", "守夜人", "老人", "男人", "老头")
GENERIC_MALE_NOUNS = ("男人", "老人", "老头", "男子", "男孩", "小伙子", "大叔", "先生")
OBJECT_TA = ("问他", "让他", "把他", "对他", "向他", "等他", "送他", "拦他", "请他", "看了他")
OBJECT_NAME_PREFIXES = ("当着", "送", "带", "领", "对", "向")
NAME_INTRODUCERS = ("找到", "见到", "看见", "看到", "遇到", "碰到", "联系", "叫作", "名叫", "找过")
TITLE_EXCLUDE = frozenset({"人员", "成员", "员工", "队员"})
TITLE_ROLE = re.compile(r"[\u4e00-\u9fff]{2,3}员")
HANDOFF_MARKERS = ("递过去", "交给", "递上")
ENTRANCE_TIME_MARKERS = ("进来时", "进门时", "走进来时", "推门进来时")
CLOSING_QUOTES = frozenset("”\"」』")
DIALOGUE_SAID_HE = re.compile(r"[”\"」』]他说")
NAME_PUNCT = frozenset("。！？\n，；、：\"\"「」 ")
NAME_SPEECH = frozenset("说答问道")
NAME_PREV_ONE = frozenset("叫请找见")
COMMON_SURNAMES = frozenset(
    "王李张刘陈杨赵黄周吴徐孙胡朱高林何郭马罗梁宋郑谢韩唐冯于董萧程曹袁邓许傅沈曾彭吕苏卢蒋蔡贾丁魏薛叶阎余潘杜戴夏钟汪田任姜范方石姚谭廖邹熊金陆郝孔白崔康毛邱秦江史顾侯邵孟万段雷钱汤尹黎易常武乔贺赖龚文向俞"
)


def character_canon_snapshot(*, version: int = CHARACTER_CANON_VERSION) -> dict:
    return {
        "canon_version": version,
        "rule": CHARACTER_CANON_RULE,
        "characters": [
            {
                "name": "林照",
                "gender": "female",
                "pronoun": "她",
                "kinship": {"林澜": "妹妹"},
            },
            {
                "name": "林澜",
                "gender": "female",
                "pronoun": "她",
                "relation": "林照的妹妹",
            },
        ],
        "male_others": list(MALE_OTHERS),
    }


def _female_characters(snapshot: dict) -> list[dict]:
    return [
        item for item in snapshot.get("characters") or []
        if item.get("gender") == "female" and item.get("pronoun") == "她" and item.get("name")
    ]


def character_canon_instruction(snapshot: dict | None = None) -> str:
    snap = snapshot or character_canon_snapshot()
    females = _female_characters(snap)
    female_names = [item["name"] for item in females]
    parts = ["代词和亲属称谓以 context_pack.character_canon 为准，禁止写反。"]
    for person in females:
        name = person["name"]
        parts.append(f"{name}是女性，代词用她，不得用他承接{name}。")
        for other, relation in (person.get("kinship") or {}).items():
            if relation == "妹妹":
                parts.append(
                    f"{other}是{name}的妹妹，不得写成姐姐，不得对{name}称{other}为你姐姐。"
                )
    named_males = [
        name for name in (snap.get("male_others") or [])
        if name not in GENERIC_MALE_NOUNS
    ]
    if named_males and female_names:
        for male in named_males:
            parts.append(f"{male}是男性，他不指{female_names[0]}。")
    parts.append("换指前先写出被指的人。两人都在、容易混时用名字，不要只用代词。")
    return "".join(parts)


def _excerpt(text: str, start: int, end: int) -> str:
    return text[max(0, start - 4):min(len(text), end + 12)]


def _after_closing_quote(text: str, ta_at: int) -> bool:
    index = ta_at - 1
    while index >= 0 and text[index].isspace():
        index -= 1
    return index >= 0 and text[index] in CLOSING_QUOTES


def _dialogue_attribution_he(text: str, start: int, ta_at: int) -> bool:
    if _after_closing_quote(text, ta_at):
        return True
    return DIALOGUE_SAID_HE.search(text[start:ta_at + 1]) is not None


def _name_used_as_object(text: str, name_at: int) -> bool:
    before = text[max(0, name_at - 4):name_at]
    return any(before.endswith(prefix) for prefix in OBJECT_NAME_PREFIXES)


def _asked_then_answered(between: str, after_ta: str) -> bool:
    return "问" in between and after_ta.startswith(("答", "说"))


def _overlaps_female_name(candidate: str, female_names: tuple[str, ...]) -> bool:
    return any(name in candidate or candidate in name for name in female_names)


def _isolated_other_name(span: str, index: int, length: int, female_names: tuple[str, ...]) -> bool:
    candidate = span[index:index + length]
    if len(candidate) < length or not all("\u4e00" <= char <= "\u9fff" for char in candidate):
        return False
    if candidate[0] not in COMMON_SURNAMES:
        return False
    if _overlaps_female_name(candidate, female_names):
        return False
    previous = span[index - 1] if index else ""
    nxt = span[index + length] if index + length < len(span) else ""
    introduced = any(
        index >= len(marker) and span[index - len(marker):index] == marker
        for marker in NAME_INTRODUCERS
    )
    previous_ok = index == 0 or previous in NAME_PUNCT or previous in NAME_PREV_ONE or introduced
    if not previous_ok:
        return False
    if length >= 3:
        return True
    return nxt == "" or nxt in NAME_PUNCT or nxt in NAME_SPEECH or nxt == "员"


def _span_has_other_male(span: str, female_names: tuple[str, ...], male_others: tuple[str, ...]) -> bool:
    if any(marker in span for marker in male_others):
        return True
    if any(noun in span for noun in GENERIC_MALE_NOUNS):
        return True
    for match in TITLE_ROLE.finditer(span):
        if match.group(0) not in TITLE_EXCLUDE:
            return True
    for index, char in enumerate(span):
        if char not in COMMON_SURNAMES:
            continue
        if _isolated_other_name(span, index, 3, female_names):
            return True
        if _isolated_other_name(span, index, 2, female_names):
            return True
    return False


def _pronoun_conflicts(text: str, snapshot: dict) -> list[dict]:
    conflicts = []
    female_names = tuple(item["name"] for item in _female_characters(snapshot))
    male_others = tuple(snapshot.get("male_others") or [])
    for name in female_names:
        start = 0
        while True:
            index = text.find(name, start)
            if index < 0:
                break
            window = text[index:index + PRONOUN_LOOKAHEAD + 2]
            lookback_at = max(0, index - PRONOUN_LOOKBACK)
            for match in SUBJECT_TA.finditer(window):
                ta_at = index + match.start() + 1
                between = text[index:ta_at]
                span = text[lookback_at:ta_at]
                if _span_has_other_male(span, female_names, male_others):
                    continue
                if _name_used_as_object(text, index):
                    continue
                if any(marker in between for marker in OBJECT_TA):
                    continue
                if _asked_then_answered(between, text[ta_at + 1:ta_at + 3]):
                    continue
                if any(marker in between for marker in HANDOFF_MARKERS):
                    continue
                if any(marker in between for marker in ENTRANCE_TIME_MARKERS):
                    continue
                if _dialogue_attribution_he(text, index, ta_at):
                    continue
                conflicts.append({
                    "kind": "pronoun",
                    "name": name,
                    "expected": "她",
                    "found": "他",
                    "excerpt": _excerpt(text, index, ta_at + 1),
                })
                break
            start = index + len(name)
    return conflicts


def _linlan_kinship_conflicts(text: str) -> list[dict]:
    conflicts = []
    for pattern in KINSHIP_FAIL:
        match = pattern.search(text)
        if not match:
            continue
        conflicts.append({
            "kind": "kinship",
            "name": "林澜",
            "expected": "妹妹",
            "found": match.group(0),
            "excerpt": _excerpt(text, match.start(), match.end()),
        })
    return conflicts


def validate_character_canon(text: str | None, snapshot: dict | None = None) -> dict:
    """Conservative content gate. Nearby male 他 and 妹妹-for-林澜 must pass."""
    source = text if isinstance(text, str) else ""
    snap = snapshot or character_canon_snapshot()
    conflicts = _pronoun_conflicts(source, snap) + _linlan_kinship_conflicts(source)
    if conflicts:
        return {
            "status": "failed",
            "reason": CHARACTER_CANON_REASON,
            "rule": CHARACTER_CANON_RULE,
            "conflicts": conflicts,
        }
    return {
        "status": "passed",
        "reason": None,
        "rule": CHARACTER_CANON_RULE,
        "conflicts": [],
    }
