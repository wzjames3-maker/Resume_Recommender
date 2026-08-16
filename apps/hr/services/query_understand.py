# coding=utf-8
"""
    @project: MaxKB
    @file： query_understand.py
    @date：2026/8/16
    @desc：查询理解 v1（T4）：规则槽位抽取——年限/学历/城市/语义词。
          设计见 docs/superpowers/specs/2026-08-16-resume-rag-v2-design.md §3.4；
          计划见 docs/superpowers/plans/2026-08-16-resume-rag-v2-implementation.md T4。
          已知限制：城市槽为子串匹配（"北京"可误中"北京师范大学"），v1 接受、评测暴露后收紧。
"""
import re

# 年限：1-2 位数字 + 年（可带"以上"），前后不得为数字（排除 "2023年" 等年份语境）
_YEARS_RE = re.compile(r"(?<!\d)(\d{1,2})\s*年(?:以上)?(?!\d)")
# 学历词表（按层级，>= 语义：查"本科"含本科及以上）
_DEGREE_LEVELS = {"大专": 1, "专科": 1, "本科": 2, "硕士": 3, "博士": 4}


def norm_city(city):
    """城市归一：去「市」后缀（北京/北京市 双向归一）。"""
    return city[:-1] if city and city.endswith("市") else city


def degree_words(level):
    """学历层级 >= level 的候选词表（SQL 用）。"""
    return [w for w, lvl in _DEGREE_LEVELS.items() if lvl >= level]


def extract_slots(query, city_list=None):
    """
    规则槽位抽取。
    :param query: 用户查询
    :param city_list: 候选城市集合（None 则不抽城市槽）
    :return: {years_min, degree_level, cities, semantic_query}
    """
    semantic = query
    years_min = None
    m = _YEARS_RE.search(query)
    if m:
        years_min = int(m.group(1))
        semantic = semantic.replace(m.group(0), " ")
    degree_level = None
    for word in sorted(_DEGREE_LEVELS, key=lambda w: -len(w)):
        if word in semantic:
            degree_level = _DEGREE_LEVELS[word]
            semantic = semantic.replace(word, " ")
    cities = []
    for city in sorted(city_list or [], key=len, reverse=True):
        norm = norm_city(city)
        if norm and norm in semantic:
            cities.append(city)
            # F7 修复：先替换完整城市串再替换归一形（长度降序处理），
            # 避免「北京市」先被 norm「北京」替换残留「市」字污染语义词
            semantic = semantic.replace(city, " ").replace(norm, " ")
    semantic = re.sub(r"\s+", " ", semantic).strip()
    return {
        "years_min": years_min,
        "degree_level": degree_level,
        "cities": cities,
        "semantic_query": semantic,
    }
