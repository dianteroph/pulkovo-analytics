from typing import Any, Dict, List, Optional, Tuple
import math
from collections import Counter

try:
    from .hh_parser import normalize_salary
except Exception:
    from hh_parser import normalize_salary


def salary_stats(vacancies: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    # Prefer already computed monthly averages if available, then fall back to API salary,
    # then to estimated monthly derived from per-shift mentions.
    raw: List[Optional[float]] = []
    for v in vacancies:
        # Skip per-shift flagged vacancies
        if v.get("salary_per_shift"):
            continue
        val = v.get("salary_avg")
        if val is None:
            val = normalize_salary(v.get("salary"))
        # Do not use estimated per-shift monthly values in stats
        raw.append(val if isinstance(val, (int, float)) else None)
    # Filter out invalid/likely per-shift small values (< 10 000₽)
    MIN_VALID_MONTHLY = 10000.0
    salaries = [s for s in raw if s is not None and float(s) >= MIN_VALID_MONTHLY]
    if not salaries:
        return {"count": 0, "avg": None, "median": None, "min": None, "max": None}
    salaries.sort()
    n = len(salaries)
    avg = sum(salaries) / n
    median = salaries[n // 2] if n % 2 == 1 else (salaries[n // 2 - 1] + salaries[n // 2]) / 2
    return {
        "count": n,
        "avg": round(avg, 2),
        "median": round(median, 2),
        "min": round(salaries[0], 2),
        "max": round(salaries[-1], 2),
    }


def top_skills(vacancies: List[Dict[str, Any]], top_n: int = 20) -> List[Tuple[str, int]]:
    # skills from key_skills or parse from description if available
    counter: Counter[str] = Counter()
    for v in vacancies:
        skills = v.get("key_skills") or []
        for s in skills:
            name = s.get("name") if isinstance(s, dict) else str(s)
            if name:
                counter[name.strip().lower()] += 1
    return counter.most_common(top_n)
