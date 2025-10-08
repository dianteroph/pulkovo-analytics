import os
import re
import httpx
from typing import Any, Dict, List, Optional, Tuple, Set
from bs4 import BeautifulSoup

HH_API_URL = "https://api.hh.ru/vacancies"
HH_EMPLOYER_URL = "https://api.hh.ru/employers/{employer_id}"
HH_EMPLOYER_PAGE = "https://hh.ru/employer/{employer_id}"
HH_VACANCY_DETAIL_URL = "https://api.hh.ru/vacancies/{vacancy_id}"

async def fetch_vacancies(query: str, area: Optional[int] = None, pages: Optional[int] = None, per_page: int = 100) -> List[Dict[str, Any]]:
    """
    Fetch vacancies from hh.ru public API.
    - query: search text
    - area: region id (e.g., 1 for Moscow, 2 for Saint-Petersburg)
    - pages: number of pages to fetch (each page has per_page items)
    - per_page: items per page (max 100)
    """
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    params_base = {
        "text": query,
        "per_page": per_page,
    }
    if area is not None:
        params_base["area"] = area

    items: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
        page = 0
        while True:
            params = dict(params_base)
            params["page"] = page
            resp = await client.get(HH_API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            page_items = data.get("items", [])
            items.extend(page_items)
            total_pages = int(data.get("pages", 0))
            # stop if API says no more pages
            if total_pages and page >= total_pages - 1:
                break
            # stop if user requested a fixed number of pages
            if pages is not None and page + 1 >= pages:
                break
            page += 1
    return items


def normalize_salary(salary: Optional[Dict[str, Any]]) -> Optional[float]:
    if not salary:
        return None
    # salary example: {"from": 100000, "to": 150000, "currency": "RUR", "gross": True}
    amount_from = salary.get("from")
    amount_to = salary.get("to")
    values = [v for v in [amount_from, amount_to] if isinstance(v, (int, float))]
    if not values:
        return None
    return float(sum(values) / len(values))


def _parse_number(text: str) -> Optional[float]:
    """Parse a number like '3 500', '3500', '3.500', '3,500' to float.
    Returns None if not found.
    """
    try:
        cleaned = text.replace("\xa0", " ")
        # Keep digits and separators
        cleaned = cleaned.replace(" ", "").replace(",", "").replace(".", "")
        if cleaned.isdigit():
            return float(cleaned)
    except Exception:
        pass
    return None


def estimate_monthly_salary_from_text(title: str, responsibility: str, requirement: Optional[str], description_text: str) -> Optional[float]:
    """Best-effort extraction of per-shift pay and conversion to monthly estimate.
    Heuristics:
      - Detect phrases like 'за смену', 'смена', 'смены' near an amount
      - Extract one or two numbers (range). If two, average them
      - Multiply per-shift rate by a default 15 shifts/month
    """
    try:
        import re
        blob = " ".join([
            (title or ""),
            (responsibility or ""),
            (requirement or ""),
            (description_text or ""),
        ]).lower()

        # Quick guard: look for shift keywords
        if not re.search(r"\b(смена|смены|за\s+смену|посменн)\b", blob):
            return None

        # Patterns like: 'за смену 3 500', 'оплата за смену: 4000₽', 'смена 4500 руб'
        money_patterns = [
            r"за\s+смену\s*[:\-]?\s*([0-9][0-9\s\.,]{2,})",
            r"смена\s*[:\-]?\s*([0-9][0-9\s\.,]{2,})",
            r"оплата\s+за\s+смену\s*[:\-]?\s*([0-9][0-9\s\.,]{2,})",
        ]

        candidates: List[float] = []
        for pat in money_patterns:
            for m in re.finditer(pat, blob):
                val = _parse_number(m.group(1))
                if isinstance(val, (int, float)):
                    candidates.append(float(val))

        # Also try simple ranges near 'смен'
        for m in re.finditer(r"([0-9][0-9\s\.,]{2,})\s*[–\-\/]\s*([0-9][0-9\s\.,]{2,}).{0,12}(смен)", blob):
            v1 = _parse_number(m.group(1))
            v2 = _parse_number(m.group(2))
            if v1 and v2:
                candidates.append((v1 + v2) / 2.0)

        if not candidates:
            return None

        per_shift = sum(candidates) / len(candidates)
        # Conservative default: 15 shifts/month
        monthly_estimate = per_shift * 15.0
        return float(monthly_estimate)
    except Exception:
        return None


def extract_vacancy_fields(v: Dict[str, Any]) -> Dict[str, Any]:
    """Extract commonly used fields from a vacancy item."""
    employer = v.get("employer") or {}
    exp = v.get("experience") or {}
    snippet = v.get("snippet") or {}
    # Description text may be attached by enrichment under 'description_text'
    description_text = v.get("description_text") or ""
    area = v.get("area") or {}
    salary_obj = v.get("salary")
    # Base normalized salary from API object
    salary_avg_base = normalize_salary(salary_obj)

    # Detect per-shift mentions
    title = v.get("name") or ""
    responsibility_text = (snippet.get("responsibility") or "") or description_text
    requirement_text = snippet.get("requirement")
    salary_estimated_monthly = estimate_monthly_salary_from_text(
        title=title,
        responsibility=responsibility_text,
        requirement=requirement_text,
        description_text=description_text,
    )
    salary_per_shift = isinstance(salary_estimated_monthly, (int, float))

    # Do NOT substitute per-shift estimate into salary_avg; leave None to exclude
    salary_avg_final: Optional[float] = salary_avg_base

    return {
        "id": v.get("id"),
        "title": title,
        "area": area.get("name"),
        "published_at": v.get("published_at"),
        "alternate_url": v.get("alternate_url"),
        "salary": salary_obj,  # original salary object for detail
        "salary_avg": salary_avg_final,
        "salary_estimated_monthly": salary_estimated_monthly,
        "salary_per_shift": salary_per_shift,
        "experience": exp.get("name"),
        "responsibility": responsibility_text,
        "requirement": requirement_text,
        "employer_id": employer.get("id"),
        "employer_name": employer.get("name"),
        "employer_trusted": employer.get("trusted"),
    }


async def fetch_employer_ratings(employer_ids: Set[str]) -> Dict[str, Optional[float]]:
    """Fetch employer rating ("rating" field) from the employer endpoint, if available.
    Returns mapping employer_id -> rating or None if not present/failed.
    """
    if not employer_ids:
        return {}
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    results: Dict[str, Optional[float]] = {}
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        for eid in employer_ids:
            if not eid:
                continue
            try:
                url = HH_EMPLOYER_URL.format(employer_id=eid)
                r = await client.get(url)
                if r.status_code != 200:
                    results[eid] = None
                    continue
                data = r.json()
                # Try common fields that may exist on employer resource
                rating = data.get("rating") or data.get("score") or data.get("scores")
                if isinstance(rating, (int, float)):
                    results[eid] = float(rating)
                else:
                    results[eid] = None
            except Exception:
                results[eid] = None
    return results


_scrape_cache: Dict[str, Optional[float]] = {}


async def scrape_employer_mark(employer_id: str) -> Optional[float]:
    """Best-effort scrape of employer rating/mark from public employer page.
    Returns float mark or None if not found.
    """
    if not employer_id:
        return None
    if employer_id in _scrape_cache:
        return _scrape_cache[employer_id]

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }

    url = HH_EMPLOYER_PAGE.format(employer_id=employer_id)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(url)
            if r.status_code != 200:
                _scrape_cache[employer_id] = None
                return None
            html = r.text
    except Exception:
        _scrape_cache[employer_id] = None
        return None

    try:
        soup = BeautifulSoup(html, "lxml")
        # Direct selector used on hh.ru employer pages
        qa_node = soup.find(attrs={"data-qa": "employer-review-small-widget-total-rating"})
        if qa_node and qa_node.get_text(strip=True):
            txt = qa_node.get_text(strip=True).replace(",", ".")
            try:
                val = float(txt)
                _scrape_cache[employer_id] = val
                return val
            except Exception:
                pass

        # Try JSON-LD aggregateRating
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json as _json
                data = _json.loads(script.string or "{}")
                if isinstance(data, dict):
                    agg = data.get("aggregateRating")
                    if isinstance(agg, dict) and isinstance(agg.get("ratingValue"), (int, float, str)):
                        val = float(agg["ratingValue"])
                        _scrape_cache[employer_id] = val
                        return val
            except Exception:
                pass

        # Fallback: search common rating patterns (e.g., stars, rating digits)
        text = soup.get_text(" ", strip=True)
        # Look for something like "Rating 4.5" or "Оценка 4,6"
        m = re.search(r"(Rating|Оценка|Рейтинг)\s*([0-9]+[\.,][0-9]+)", text, flags=re.I)
        if m:
            val = m.group(2).replace(",", ".")
            _scrape_cache[employer_id] = float(val)
            return float(val)
    except Exception:
        pass

    _scrape_cache[employer_id] = None
    return None


def html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
        # Remove scripts/styles
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        return text
    except Exception:
        return ""


_vacancy_desc_cache: Dict[str, str] = {}


async def fetch_vacancy_description_api(vacancy_id: str) -> Optional[str]:
    if not vacancy_id:
        return None
    if vacancy_id in _vacancy_desc_cache:
        return _vacancy_desc_cache[vacancy_id]
    headers = {"User-Agent": "job-analytics-bot/1.0"}
    url = HH_VACANCY_DETAIL_URL.format(vacancy_id=vacancy_id)
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return None
            data = r.json()
            desc_html = data.get("description") or ""
            text = html_to_text(desc_html)
            _vacancy_desc_cache[vacancy_id] = text
            return text
    except Exception:
        return None


async def scrape_vacancy_description_page(alternate_url: str) -> Optional[str]:
    if not alternate_url:
        return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
        "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0, headers=headers, follow_redirects=True) as client:
            r = await client.get(alternate_url)
            if r.status_code != 200:
                return None
            soup = BeautifulSoup(r.text, "lxml")
            # Common container for vacancy description
            node = soup.find(attrs={"data-qa": "vacancy-description"}) or soup.find("div", class_=re.compile(r"vacancy-description"))
            if node:
                return html_to_text(str(node))
            return html_to_text(r.text)
    except Exception:
        return None


async def enrich_with_descriptions(items: List[Dict[str, Any]], prefer_scrape: bool = False) -> None:
    """Mutates items by adding 'description_text' using API detail or page scrape.
    prefer_scrape=False uses API first, then scrape fallback.
    """
    # Light concurrency with semaphore to avoid hammering
    import asyncio as _aio
    sem = _aio.Semaphore(8)

    async def _one(v: Dict[str, Any]):
        async with sem:
            vid = v.get("id")
            text: Optional[str] = None
            if prefer_scrape:
                text = await scrape_vacancy_description_page(v.get("alternate_url") or "")
                if not text:
                    text = await fetch_vacancy_description_api(vid)
            else:
                text = await fetch_vacancy_description_api(vid)
                if not text:
                    text = await scrape_vacancy_description_page(v.get("alternate_url") or "")
            if text:
                v["description_text"] = text

    await _aio.gather(*[_one(v) for v in items])


async def parse_vacancies(items: List[Dict[str, Any]], with_employer_mark: bool = False) -> List[Dict[str, Any]]:
    """Produce simplified vacancy dicts with selected fields.
    If with_employer_mark, compute employer marks from available data (fast approach).
    """
    parsed = [extract_vacancy_fields(v) for v in items]
    if with_employer_mark:
        # Use only fast computed marks (no web scraping)
        computed = compute_employer_marks(parsed)
        for p in parsed:
            eid = p.get("employer_id")
            p["employer_mark"] = computed.get(eid)
    return parsed


def compute_employer_marks(parsed_items: List[Dict[str, Any]]) -> Dict[str, float]:
    """Compute a 1..5 employer mark using only available vacancy signals (no scraping).
    Components:
      - trusted flag (1 or 0) [weight 0.4]
      - salary availability rate per employer [weight 0.3]
      - average salary normalized across all vacancies [weight 0.2]
      - employer vacancy count normalized by max count [weight 0.1]
    """
    # Aggregate per employer
    employer_to_salaries: Dict[str, List[float]] = {}
    employer_to_salary_present: Dict[str, int] = {}
    employer_to_total: Dict[str, int] = {}
    employer_to_trusted: Dict[str, bool] = {}

    all_salaries: List[float] = []
    for v in parsed_items:
        eid = v.get("employer_id")
        if not eid:
            continue
        employer_to_total[eid] = employer_to_total.get(eid, 0) + 1
        employer_to_trusted[eid] = bool(v.get("employer_trusted")) or employer_to_trusted.get(eid, False)
        avg = v.get("salary_avg")
        if isinstance(avg, (int, float)):
            employer_to_salaries.setdefault(eid, []).append(float(avg))
            employer_to_salary_present[eid] = employer_to_salary_present.get(eid, 0) + 1
            all_salaries.append(float(avg))

    salary_min = min(all_salaries) if all_salaries else 0.0
    salary_max = max(all_salaries) if all_salaries else 1.0
    denom = (salary_max - salary_min) if salary_max > salary_min else 1.0

    max_count = max(employer_to_total.values()) if employer_to_total else 1

    marks: Dict[str, float] = {}
    for eid, total in employer_to_total.items():
        trusted_score = 1.0 if employer_to_trusted.get(eid) else 0.0
        with_salary = employer_to_salary_present.get(eid, 0)
        salary_rate = with_salary / total if total > 0 else 0.0
        salaries = employer_to_salaries.get(eid, [])
        avg_salary = sum(salaries) / len(salaries) if salaries else salary_min
        avg_salary_norm = (avg_salary - salary_min) / denom
        count_norm = total / max_count if max_count > 0 else 0.0

        mark = 0.4 * trusted_score + 0.3 * salary_rate + 0.2 * avg_salary_norm + 0.1 * count_norm
        # Convert from [0,1] to [1,5] scale
        mark = 1.0 + (mark * 4.0)  # Maps 0->1, 1->5
        # Clamp to [1,5]
        mark = max(1.0, min(5.0, float(mark)))
        marks[eid] = mark

    return marks
