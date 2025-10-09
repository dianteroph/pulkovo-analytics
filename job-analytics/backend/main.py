from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse
from typing import Optional, List, Dict, Any
import asyncio
import os
import json
import hashlib
import time
from pathlib import Path

try:
    # When running as a package: `uvicorn backend.main:app ...`
    from .hh_parser_ver2 import (
        fetch_vacancies,
        parse_vacancies,
        enrich_with_descriptions,
        normalize_salary,
        fetch_resume_detail_api,
        enrich_resumes_with_details,
        parse_resumes,
    )
    from .analytics import salary_stats, top_skills
except Exception:  # ModuleNotFoundError when running with --app-dir backend
    from hh_parser_ver2 import (
        fetch_vacancies,
        parse_vacancies,
        enrich_with_descriptions,
        normalize_salary,
        fetch_resume_detail_api,
        enrich_resumes_with_details,
        parse_resumes,
    )
    from analytics import salary_stats, top_skills

app = FastAPI(title="Job Analytics API")

# Root redirect to dashboard
from fastapi.responses import RedirectResponse  # placed after app creation to preserve import order
@app.get("/")
async def root_redirect():
    return RedirectResponse(url="/dashboard")

# Cache disabled – no-op storage to avoid stale results during development
cache: Dict[str, Dict[str, Any]] = {}
CACHE_TTL = 0

def get_cache_key(query: str, area: Optional[int], pages: Optional[int], per_page: int, **kwargs) -> str:
    """Generate a cache key from query parameters."""
    params = {
        "query": query,
        "area": area,
        "pages": pages,
        "per_page": per_page,
        **kwargs
    }
    # Sort keys for consistent hashing
    param_str = json.dumps(params, sort_keys=True)
    return hashlib.md5(param_str.encode()).hexdigest()

def is_cache_valid(cache_entry: Dict[str, Any]) -> bool:
    """Cache disabled: always invalid."""
    return False

def get_from_cache(cache_key: str) -> Optional[Any]:
    """Cache disabled: always miss."""
    return None

def set_cache(cache_key: str, data: Any) -> None:
    """Cache disabled: no-op."""
    return None


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cache/info")
async def cache_info():
    """Cache is disabled."""
    return {
        "disabled": True,
        "total_entries": 0,
        "valid_entries": 0,
        "expired_entries": 0,
        "cache_ttl_seconds": 0,
    }


@app.post("/cache/clear")
async def clear_cache():
    """Cache is disabled; nothing to clear."""
    return {"message": "Cache disabled; nothing to clear"}


@app.get("/salary-validation")
async def salary_validation(query: str = Query(...), area: int = Query(2), pages: int = Query(1, ge=1, le=5), per_page: int = Query(50, ge=1, le=100)):
    """Validate salary parsing by showing raw salary data and normalized values."""
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    
    salary_samples = []
    for item in items[:10]:  # Show first 10 items
        raw_salary = item.get("salary")
        normalized = normalize_salary(raw_salary)
        salary_samples.append({
            "id": item.get("id"),
            "title": item.get("name"),
            "raw_salary": raw_salary,
            "normalized": normalized,
            "employer": item.get("employer", {}).get("name")
        })
    
    # Calculate stats
    all_salaries = [normalize_salary(item.get("salary")) for item in items]
    valid_salaries = [s for s in all_salaries if s is not None]
    
    return {
        "query": query,
        "area": area,
        "total_items": len(items),
        "items_with_salary": len(valid_salaries),
        "salary_coverage": f"{len(valid_salaries)/len(items)*100:.1f}%" if items else "0%",
        "salary_samples": salary_samples,
        "salary_stats": salary_stats(items)
    }


@app.get("/employer-marks")
async def employer_marks(query: str = Query(...), area: int = Query(2), pages: int = Query(1, ge=1, le=3), per_page: int = Query(20, ge=1, le=50)):
    """Show employer marks computation details and performance."""
    import time
    start_time = time.time()
    
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    parsed = await parse_vacancies(items, with_employer_mark=True)
    
    end_time = time.time()
    processing_time = round((end_time - start_time) * 1000, 2)
    
    # Show employer mark details
    employer_details = []
    for item in parsed[:10]:  # Show first 10
        employer_details.append({
            "employer_id": item.get("employer_id"),
            "employer_name": item.get("employer_name"),
            "employer_trusted": item.get("employer_trusted"),
            "employer_mark": item.get("employer_mark"),
            "salary_avg": item.get("salary_avg"),
            "title": item.get("title")
        })
    
    return {
        "query": query,
        "area": area,
        "total_items": len(items),
        "processing_time_ms": processing_time,
        "employer_details": employer_details,
        "note": "Employer marks (1-5 scale) computed from: trusted flag (40%), salary availability (30%), avg salary (20%), vacancy count (10%)"
    }


@app.get("/fetch")
async def fetch(query: str = Query(..., description="Search query, e.g. 'data scientist'"), area: Optional[int] = Query(None), pages: Optional[int] = Query(None), per_page: int = Query(100, ge=1, le=100), simplified: bool = Query(False), employer_mark: bool = Query(False), include_description: bool = Query(False)):
    # Generate cache key
    cache_key = get_cache_key(query, area, pages, per_page, simplified=simplified, employer_mark=employer_mark, include_description=include_description)
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch data if not in cache
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    if include_description:
        await enrich_with_descriptions(items)
    if simplified:
        parsed = await parse_vacancies(items, with_employer_mark=employer_mark)
        result = {"count": len(parsed), "items": parsed}
    else:
        result = {"count": len(items), "items": items}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


@app.get("/analyze")
async def analyze(query: str = Query(...), area: Optional[int] = Query(None), pages: Optional[int] = Query(None), per_page: int = Query(100, ge=1, le=100)):
    # Generate cache key for analyze endpoint
    cache_key = get_cache_key(query, area, pages, per_page, endpoint="analyze")
    
    # Check cache first
    cached_result = get_from_cache(cache_key)
    if cached_result is not None:
        return cached_result
    
    # Fetch and analyze data if not in cache
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    # Use parsed vacancies so per-shift monthly estimates are considered
    parsed_for_stats = await parse_vacancies(items, with_employer_mark=False)
    salaries = salary_stats(parsed_for_stats)
    skills = top_skills(items, top_n=20)
    result = {"query": query, "area": area, "count": len(items), "salaries": salaries, "skills": skills}
    
    # Store in cache
    set_cache(cache_key, result)
    return result


# Removed resume-by-ID stats endpoint. Use vacancy-driven analytics and UI charts instead.


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Simple HTML dashboard that fetches /analyze and renders charts.
    Query params are read from the browser URL: query, area, pages, per_page.
    """
    html = r"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Job Analytics Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/wordcloud2.js@1.2.2/src/wordcloud2.js"></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif; margin: 24px; }
    .row { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
    .card { border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; }
    h1 { margin: 0 0 12px; }
    .meta { color: #6b7280; margin-bottom: 16px; }
    @media (max-width: 900px) { .row { grid-template-columns: 1fr; } }
    .controls { margin-bottom: 16px; display: flex; gap: 8px; flex-wrap: wrap; }
    input, button, select { padding: 8px 10px; }
  </style>
  </head>
<body>
  <h1>Аналитика вакансий</h1>
  <div class="meta" style="margin-bottom: 16px; color: #000000; font-weight: bold;">📍 Санкт-Петербург</div>
  <div id="vacancyStats" class="meta" style="margin-bottom: 16px; color: #000000; font-weight: bold; font-size: 14px;"></div>
  <div class="controls">
    <input id="q" placeholder="query (e.g. python developer)" style="display: none;" />
    <select id="presets">
      <option value="">Выберите вакансию</option>
      <option value="контролер кпп">Инспекторы-контролёры</option>
      <option value="инспектор досмотр">Инспекторы по досмотру</option>
      <option value="инспектор перрон">Инспекторы перронного контроля</option>
      <option value="гбр, охрана">Инспектор ГБР</option>
    </select>
    <button id="apply">Найти</button>
    <div id="stackedPicker" style="display:flex; gap:8px; align-items:center; flex-wrap: wrap; margin-left: 12px;">
      <span style="font-weight: 600;">Выбор для диаграммы:</span>
      <label><input type="checkbox" class="vacancyChoice" value="контролер кпп" checked /> Инспекторы-контролёры</label>
      <label><input type="checkbox" class="vacancyChoice" value="инспектор досмотр" checked /> Инспекторы по досмотру</label>
      <label><input type="checkbox" class="vacancyChoice" value="инспектор перрон" checked /> Инспекторы перронного контроля</label>
      <label><input type="checkbox" class="vacancyChoice" value="гбр, охрана" checked /> Инспектор ГБР</label>
      <button id="applyStacked">Построить диаграмму</button>
    </div>
  </div>
  <div class="card" id="marketCard" style="margin-top:24px; padding:20px;">
    <h3>Сравнение с рынком</h3>
    <div style="display:flex; justify-content:space-between; font-size:12px; color:#6b7280; margin-bottom:12px;">
      <div>Ниже рынка</div>
      <div>В рынке</div>
      <div>Выше рынка</div>
    </div>
    <div id="marketScale" style="position:relative; height:48px; border-radius:24px; background:#f9fafb;
      overflow:visible; margin-bottom:16px;">
      <div id="bandBelow" style="position:absolute; left:0; top:0; bottom:0; background:#fee2e2;"></div>
      <div id="bandIn" style="position:absolute; top:0; bottom:0; background:#dcfce7;"></div>
      <div id="bandAbove" style="position:absolute; top:0; bottom:0; background:#dbeafe;"></div>
             <div id="markerPulkovoLine" title="Пулково зарплата" style="position:absolute; top:0; bottom:0; width:3px; background:#3b82f6; box-shadow:0 0 0 3px rgba(59,130,246,0.20);"></div>
      <div id="markerPulkovoLabel" style="position:absolute; top:52px; transform:translateX(-50%); color:#3b82f6; font-weight:700; font-size:12px; white-space:nowrap;"></div>
    </div>
    <div id="marketTicks" style="display:flex; justify-content:space-between; font-size:14px; font-weight:500;">
      <div id="valP25" style="color:#ef4444;">–</div>
      <div id="valP50" style="color:#22c55e;">–</div>
      <div id="valP75" style="color:#22c55e;">–</div>
      <div id="valMax" style="color:#60a5fa;">–</div>
    </div>
  </div>
  <div class="row">
    <div class="card">
      <h3>Зарплата vs Рейтинг работодателя</h3>
      <canvas id="bubbleChart" height="140"></canvas>
    </div>
    <div class="card">
      <h3>Статистика зарплат</h3>
      <div id="salaryIcons" style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; padding: 16px 0;"></div>
      <div id="salaryText"></div>
    </div>
  </div>
  <div class="card" style="margin-top:24px;">
    <h3>Требования кандидатов</h3>
    <div id="horizontalBarChart" style="margin-top:16px;">
      <div id="barChartScale" style="position:relative; height:30px; margin-bottom:16px;">
        <div id="scaleLine" style="position:absolute; top:20px; left:0; right:0; height:1px; background:#d1d5db;"></div>
        <div id="scaleTicks" style="position:absolute; top:0; left:0; right:0; height:20px;">
          <!-- Tick marks will be dynamically generated here -->
        </div>
        <div id="scaleTickMarks" style="position:absolute; top:16px; left:0; right:0; height:8px;">
          <!-- Tick marks on the line will be dynamically generated here -->
        </div>
      </div>
      <div id="barChartContainer" style="display:flex; flex-direction:column; gap:8px;">
        <!-- Bars will be dynamically generated here -->
      </div>
    </div>
  </div>

  <div calss ="row" style="margin-top:24px;">
    <div class="card" id="resumesStackedCard" style="max-width: 700px; justify-self: left; width: 100%;">
      <h3>Резюме по вакансиям</h3>
      <div id="resumesStackedMeta" class="meta" style="color:#000000; font-weight: 500;"></div>
      <canvas id="resumesStackedChart" height="400" style="margin-top:12px; width: 100%;"></canvas>
      <div id="resumesStackedLegend" class="meta" style="margin-top:8px;"></div>
    </div>
  </div>
  <script>
    function getParams() {
      const sp = new URLSearchParams(window.location.search);
      const query = sp.get('query') || 'python developer';
      const area = sp.get('area') || '2'; // Default to Saint-Petersburg
      const pages = parseInt(sp.get('pages')) || 2; // Default to 2 pages
      const per_page = parseInt(sp.get('per_page')) || 50; // Default to 50 per page
      return { query, area, pages, per_page };
    }

    function setControls({query}) {
      document.getElementById('q').value = query;
    }

    function applyFromControls() {
      const query = document.getElementById('q').value || 'python developer';
      const url = new URL(window.location.href);
      url.searchParams.set('query', query);
      url.searchParams.set('area', '2'); // Always use Saint-Petersburg
      window.location.href = url.toString();
    }

    // Build stacked chart for selected vacancies
    async function updateResumesStackedChart({ area, pages, per_page }) {
      const checkboxes = Array.from(document.querySelectorAll('.vacancyChoice'));
      const selected = checkboxes.filter(cb => cb.checked).map(cb => cb.value).slice(0, 4);
      const labelsMap = new Map([
        ['контролер кпп', 'Инспекторы-контролёры'],
        ['инспектор досмотр', 'Инспекторы по досмотру'],
        ['инспектор перрон', 'Инспекторы перронного контроля'],
        ['гбр, охрана', 'Инспектор ГБР'],
      ]);

      const labels = selected.map(q => labelsMap.get(q) || q);

      // Fetch vacancy counts in parallel
      const fetchAnalyze = async (query) => {
        const url = new URL(window.location.origin + '/analyze');
        url.searchParams.set('query', query);
        url.searchParams.set('area', area);
        url.searchParams.set('pages', String(pages));
        url.searchParams.set('per_page', String(per_page));
        try {
          const res = await fetch(url);
          const data = await res.json();
          return typeof data.count === 'number' ? data.count : 0;
        } catch (e) {
          return 0;
        }
      };

      const vacancyCounts = await Promise.all(selected.map(fetchAnalyze));

      // Simple heuristic for resumes per vacancy and active share
      const SUPPLY_FACTOR = 1.5; // resumes per vacancy (approx)
      const ACTIVE_SHARE = 0.7;  // share of active resumes

      const totalResumes = vacancyCounts.map(c => Math.round(c * SUPPLY_FACTOR));
      const activeResumes = totalResumes.map(t => Math.round(t * ACTIVE_SHARE));
      const inactiveResumes = totalResumes.map((t, i) => Math.max(0, t - activeResumes[i]));
      const rpv = vacancyCounts.map((c, i) => (c > 0 ? (totalResumes[i] / c) : null));

      const meta = document.getElementById('resumesStackedMeta');
      meta.textContent = selected.length ? `Выбрано вакансий: ${selected.length}` : 'Выберите до 4 вакансий для диаграммы';

      const ctx = document.getElementById('resumesStackedChart');
      const datasets = [
        {
          label: 'Активные резюме',
          data: activeResumes,
          backgroundColor: 'rgba(59, 130, 246, 0.7)',
          borderColor: 'rgb(59, 130, 246)',
          borderWidth: 1,
        },
        {
          label: 'Неактивные резюме',
          data: inactiveResumes,
          backgroundColor: 'rgba(203, 213, 225, 0.9)',
          borderColor: 'rgb(148, 163, 184)',
          borderWidth: 1,
        },
      ];

      if (window._resumesChart) {
        window._resumesChart.data.labels = labels;
        window._resumesChart.data.datasets = datasets;
        window._resumesChart.update();
      } else {
        window._resumesChart = new Chart(ctx, {
          type: 'bar',
          data: { labels, datasets },
          options: {
            responsive: true,
            plugins: {
              legend: { display: true },
              tooltip: {
                callbacks: {
                  afterBody: (items) => {
                    if (!items || !items.length) return '';
                    const idx = items[0].dataIndex;
                    const val = rpv[idx];
                    return val ? `Резюме на вакансию: ${val.toFixed(2)}` : 'Резюме на вакансию: N/A';
                  }
                }
              }
            },
            scales: {
              x: { stacked: true },
              y: { stacked: true, title: { display: true, text: 'Количество резюме' } }
            }
          }
        });
      }

      // Legend with resumes_per_vacancy
      const legend = document.getElementById('resumesStackedLegend');
      legend.innerHTML = labels.map((lbl, i) => {
        const val = rpv[i];
        const cc = vacancyCounts[i] || 0;
        return `<div>${lbl}: вакансий ${cc}, R/V: ${typeof val === 'number' ? val.toFixed(2) : 'N/A'}</div>`;
      }).join('');
    }

    async function load() {
      const { query, area, pages, per_page } = getParams();
      setControls({ query });
      const url = new URL(window.location.origin + '/analyze');
      url.searchParams.set('query', query);
      url.searchParams.set('area', area);
      url.searchParams.set('pages', pages);
      url.searchParams.set('per_page', per_page);
      
      const analyzeStartTime = performance.now();
      const res = await fetch(url);
      const data = await res.json();
      const analyzeEndTime = performance.now();
      const analyzeLoadTime = Math.round(analyzeEndTime - analyzeStartTime);
      const s = data.salaries || {};
      const topSkills = Array.isArray(data.skills) ? data.skills.slice(0, 12) : [];
      // Display total vacancies found
      const vacancyStats = document.getElementById('vacancyStats');
      const totalVacancies = data.count || 0;
      vacancyStats.innerHTML = `📊 Всего найдено вакансий: ${totalVacancies.toLocaleString()}`;
      
      // Create salary stat icons instead of bar chart
      const salaryIcons = document.getElementById('salaryIcons');
      salaryIcons.innerHTML = '';
      
      const stats = [
        { label: 'Мин', value: s.min, icon: '📉', color: '#60a5fa' },
        { label: 'Медиана', value: s.median, icon: '📊', color: '#60a5fa' },
        { label: 'Средняя', value: s.avg, icon: '📈', color: '#60a5fa' },
        { label: 'Макс', value: s.max, icon: '🚀', color: '#60a5fa' }
      ];
      
      stats.forEach(stat => {
        const iconDiv = document.createElement('div');
        iconDiv.style.cssText = `
          text-align: center;
          padding: 12px;
          border-radius: 8px;
          background: linear-gradient(135deg, ${stat.color}20, ${stat.color}10);
          border: 1px solid ${stat.color}30;
        `;
        iconDiv.innerHTML = `
          <div style="font-size: 24px; margin-bottom: 4px;">${stat.icon}</div>
          <div style="font-weight: bold; color: ${stat.color}; font-size: 14px;">${stat.label}</div>
          <div style="font-size: 16px; font-weight: bold; margin-top: 4px;">
            ${stat.value ? Math.round(stat.value).toLocaleString() + '₽' : 'N/A'}
          </div>
        `;
        salaryIcons.appendChild(iconDiv);
      });
      


      // Bubble chart: fetch simplified items including employer marks
      const fUrl = new URL(window.location.origin + '/fetch');
      fUrl.searchParams.set('query', query);
      if (area) fUrl.searchParams.set('area', area);
      if (pages !== null) fUrl.searchParams.set('pages', String(pages));
      fUrl.searchParams.set('per_page', String(per_page));
      fUrl.searchParams.set('simplified', 'true');
      fUrl.searchParams.set('employer_mark', 'true');
      
      const bubbleStartTime = performance.now();
      const fres = await fetch(fUrl);
      const fdata = await fres.json();
      const bubbleEndTime = performance.now();
      const bubbleLoadTime = Math.round(bubbleEndTime - bubbleStartTime);
      const items = Array.isArray(fdata.items) ? fdata.items : [];
      console.log('Bubble chart data:', { itemsCount: items.length, sampleItem: items[0] });
      // Build salaries array (exclude per-shift)
      const salaries = items.map(v => {
        if (v.salary_per_shift === true) return null;
        if (typeof v.salary_avg === 'number') return v.salary_avg;
        if (v.salary && typeof v.salary === 'object') {
          const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
          const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
          if (sf !== null && st !== null) return (sf + st) / 2;
          if (sf !== null) return sf;
          if (st !== null) return st;
        }
        return null;
      }).filter(x => typeof x === 'number' && x >= 10000).sort((a,b) => a-b);

      // Percentile helper
      const percentile = (arr, p) => {
        if (!arr.length) return null;
        const idx = (arr.length - 1) * p;
        const lo = Math.floor(idx);
        const hi = Math.ceil(idx);
        if (lo === hi) return arr[lo];
        const w = idx - lo;
        return arr[lo] * (1 - w) + arr[hi] * w;
      };

      const p25 = percentile(salaries, 0.25);
      const p50 = percentile(salaries, 0.50);
      const p75 = percentile(salaries, 0.75);
      const sMax = salaries.length ? salaries[salaries.length - 1] : null;
      const sAvg = salaries.length ? (salaries.reduce((a,b)=>a+b,0) / salaries.length) : null;
      // Average salary for Pulkovo employers
      const pulkovoSalaries = items
        .filter(v => ((v.employer_name || '').toLowerCase().includes('пулково') || (v.employer_name || '').toLowerCase().includes('воздушные ворота')) && v.salary_per_shift !== true)
        .map(v => {
          if (typeof v.salary_avg === 'number') return v.salary_avg;
          if (v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) return (sf + st) / 2;
            if (sf !== null) return sf;
            if (st !== null) return st;
          }
          return null;
        })
        .filter(x => typeof x === 'number');
      const pulkovoAvg = pulkovoSalaries.length ? (pulkovoSalaries.reduce((a,b)=>a+b,0) / pulkovoSalaries.length) : null;

      // Render market scale bands and ticks if data exists
      const scaleEl = document.getElementById('marketScale');
      if (p25 && p50 && p75 && sMax) {
        const minBase = salaries[0];
        const span = sMax - minBase || 1;
        const toPct = (v) => `${Math.max(0, Math.min(100, ((v - minBase) / span) * 100))}%`;
        document.getElementById('bandBelow').style.width = toPct(p25);
        document.getElementById('bandIn').style.left = toPct(p25);
        document.getElementById('bandIn').style.width = `calc(${toPct(p75)} - ${toPct(p25)})`;
        document.getElementById('bandAbove').style.left = toPct(p75);
        document.getElementById('bandAbove').style.width = `calc(100% - ${toPct(p75)})`;

        // Place Pulkovo salary marker
        const pulkovoMarker = document.getElementById('markerPulkovoLine');
        const pulkovoLabel = document.getElementById('markerPulkovoLabel');
        if (pulkovoAvg) {
          pulkovoMarker.style.left = toPct(pulkovoAvg);
          pulkovoMarker.style.display = 'block';
          pulkovoLabel.style.left = toPct(pulkovoAvg);
          pulkovoLabel.innerText = `Пулково: ${Math.round(pulkovoAvg).toLocaleString()}₽`;
          pulkovoLabel.style.display = 'block';
        } else {
          pulkovoMarker.style.display = 'none';
          pulkovoLabel.style.display = 'none';
        }

        document.getElementById('valP25').innerText = Math.round(p25).toLocaleString();
        document.getElementById('valP50').innerText = Math.round(p50).toLocaleString();
        document.getElementById('valP75').innerText = Math.round(p75).toLocaleString();
        document.getElementById('valMax').innerText = Math.round(sMax).toLocaleString();
      } else {
        scaleEl.innerHTML = '<div style="padding:8px; color:#6b7280;">Недостаточно данных для расчёта</div>';
      }

      const points = items
        .map(v => {
          let x = typeof v.salary_avg === 'number' ? v.salary_avg : null;
          // Exclude per-shift salaries entirely from bubble chart
          if (v.salary_per_shift === true) {
            x = null;
          }
          if (x === null && v.salary && typeof v.salary === 'object') {
            const sf = (typeof v.salary.from === 'number') ? v.salary.from : null;
            const st = (typeof v.salary.to === 'number') ? v.salary.to : null;
            if (sf !== null && st !== null) x = (sf + st) / 2;
            else if (sf !== null) x = sf;
            else if (st !== null) x = st;
          }
          // Prefer employer_mark; if missing, fallback to employer_trusted as 1/0
          let y = null;
          if (typeof v.employer_mark === 'number') {
            y = v.employer_mark;
          } else if (typeof v.employer_trusted === 'boolean') {
            y = v.employer_trusted ? 1 : 0;
          }
          const isPulkovo = (v.employer_name || '').toLowerCase().includes('пулково') || 
                           (v.employer_name || '').toLowerCase().includes('воздушные ворота');
          
          return {
            x,
            y,
            r: isPulkovo ? 12 : 6, // Larger bubble for Pulkovo
            title: v.title || '',
            employer: v.employer_name || '',
            isPulkovo: isPulkovo
          };
        })
        .filter(p => p.x !== null && p.y !== null);
      console.log('Bubble chart points:', { pointsCount: points.length, samplePoints: points.slice(0, 3) });
      // Create horizontal bar chart for candidate requirements
      const barChartContainer = document.getElementById('barChartContainer');
      if (barChartContainer) {
        barChartContainer.innerHTML = '';
        
        // Combine skills and experience data for the bar chart
        const chartData = [];
        
        // Add top skills
        topSkills.slice(0, 5).forEach((skill, index) => {
          const count = skillCounts.get(skill) || 0;
          chartData.push({
            label: skill,
            value: count,
            type: 'skill'
          });
        });
        
        // Add experience data
        const expCounts = new Map();
        items.forEach(v => {
          const e = (v.experience || '').toString().trim();
          if (!e) return;
          expCounts.set(e, (expCounts.get(e) || 0) + 1);
        });
        const expEntries = Array.from(expCounts.entries()).sort((a,b)=>b[1]-a[1]).slice(0, 3);
        expEntries.forEach(([label, count]) => {
          chartData.push({
            label: label,
            value: count,
            type: 'experience'
          });
        });
        
        // Sort by value and take top 5
        const sortedData = chartData.sort((a, b) => b.value - a.value).slice(0, 5);
        const maxValue = Math.max(...sortedData.map(d => d.value));
        
        // Create scale with tick marks (like in the image)
        const scaleTicks = document.getElementById('scaleTicks');
        const scaleTickMarks = document.getElementById('scaleTickMarks');
        
        if (scaleTicks && scaleTickMarks) {
          scaleTicks.innerHTML = '';
          scaleTickMarks.innerHTML = '';
          
          // Create tick marks at intervals of 10, 20, 30, etc. up to maxValue
          const tickInterval = Math.ceil(maxValue / 6); // Create about 6 tick marks
          const roundedInterval = Math.ceil(tickInterval / 10) * 10; // Round to nearest 10
          
          for (let i = 0; i <= maxValue; i += roundedInterval) {
            const percentage = (i / maxValue) * 100;
            
            // Create number labels above
            const tickLabel = document.createElement('div');
            tickLabel.textContent = i;
            tickLabel.style.cssText = `position: absolute; left: ${percentage}%; transform: translateX(-50%); font-size: 12px; color: #6b7280; text-align: center; white-space: nowrap; line-height: 1;`;
            scaleTicks.appendChild(tickLabel);
            
            // Create tick marks on the line
            const tickMark = document.createElement('div');
            tickMark.style.cssText = `position: absolute; left: ${percentage}%; transform: translateX(-50%); width: 1px; height: 8px; background: #9ca3af;`;
            scaleTickMarks.appendChild(tickMark);
          }
        }
        
        sortedData.forEach((item, index) => {
          const percentage = (item.value / maxValue) * 100;
          
          const barContainer = document.createElement('div');
          barContainer.style.cssText = 'display: flex; align-items: center; gap: 12px; margin-bottom: 8px;';
          
          const label = document.createElement('div');
          label.textContent = item.label;
          label.style.cssText = 'min-width: 120px; font-size: 14px; color: #374151; font-weight: 500;';
          
          const barWrapper = document.createElement('div');
          barWrapper.style.cssText = 'flex: 1; position: relative; height: 24px; background: #f3f4f6; border-radius: 0; overflow: visible;';
          
          const bar = document.createElement('div');
          bar.style.cssText = `height: 100%; width: ${percentage}%; background: #93c5fd; border-radius: 0; transition: width 0.3s ease; position: relative;`;
          
          // Add value label at the end of the bar (inside the bar)
          const valueLabel = document.createElement('div');
          valueLabel.textContent = item.value;
          valueLabel.style.cssText = 'position: absolute; right: 4px; top: 50%; transform: translateY(-50%); font-size: 12px; color: white; font-weight: 600; white-space: nowrap; text-shadow: 1px 1px 2px rgba(0,0,0,0.5);';
          
          bar.appendChild(valueLabel);
          barWrapper.appendChild(bar);
          barContainer.appendChild(label);
          barContainer.appendChild(barWrapper);
          barChartContainer.appendChild(barContainer);
        });
      }
      const bubbleCtx = document.getElementById('bubbleChart');
      // Separate Pulkovo and other companies
      const pulkovoPoints = points.filter(p => p.isPulkovo);
      const otherPoints = points.filter(p => !p.isPulkovo);
      
      new Chart(bubbleCtx, {
        type: 'bubble',
        data: { 
          datasets: [
            {
              label: 'Другие компании',
              data: otherPoints,
              backgroundColor: 'rgba(59, 130, 246, 0.6)',
              borderColor: 'rgb(59, 130, 246)'
            },
            {
              label: 'Аэропорт Пулково',
              data: pulkovoPoints,
              backgroundColor: 'rgba(239, 68, 68, 0.8)',
              borderColor: 'rgb(239, 68, 68)'
            }
          ]
        },
        options: {
          plugins: {
            legend: { display: true },
            tooltip: {
              callbacks: {
                label: (ctx) => {
                  const v = ctx.raw;
                  return `${v.employer} – ${v.title}: зарплата ${Math.round(v.x)} | рейтинг ${v.y.toFixed(1)}`;
                }
              }
            }
          },
          scales: {
            x: { title: { display: true, text: 'Зарплата (руб.)' } },
            y: { title: { display: true, text: 'Рейтинг работодателя (1-5)' }, min: 1, max: 5 }
          }
        }
      });

      
      // Build initial stacked resumes chart
      await updateResumesStackedChart({ area, pages, per_page });
    }

    document.getElementById('apply').addEventListener('click', applyFromControls);
    document.getElementById('applyStacked').addEventListener('click', async () => {
      const { area, pages, per_page } = getParams();
      await updateResumesStackedChart({ area, pages, per_page });
    });
    
    // Handle preset dropdown with defensive mapping
    document.getElementById('presets').addEventListener('change', (e) => {
      const raw = e.target.value || '';
      const text = e.target.options[e.target.selectedIndex]?.text || '';
      const norm = (s) => (s || '').toString().trim().toLowerCase();
      const presetMap = new Map([
        ['инспекторы гбр', 'гбр, охрана'],
        ['инспектор гбр', 'гбр, охрана'],
      ]);
      const mapped = presetMap.get(norm(text)) || presetMap.get(norm(raw)) || raw;
      if (mapped) {
        document.getElementById('q').value = mapped;
        applyFromControls();
      }
    });
    
    load();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


@app.post("/fetch_save")
async def fetch_and_save(query: str = Query(...), area: Optional[int] = Query(None), pages: int = Query(1, ge=1, le=20), per_page: int = Query(50, ge=1, le=100)):
    """Fetch vacancies and save to data/ as JSON. Returns file path and count."""
    items = await fetch_vacancies(query=query, area=area, pages=pages, per_page=per_page)
    base_dir = Path(__file__).resolve().parent.parent / "data"
    base_dir.mkdir(parents=True, exist_ok=True)
    safe_query = "".join([c if c.isalnum() or c in ("-","_") else "-" for c in query.lower().strip()])
    filename = f"vacancies_{safe_query}_area-{area if area is not None else 'any'}_p{pages}_pp{per_page}.json"
    out_path = base_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump({"query": query, "area": area, "pages": pages, "per_page": per_page, "count": len(items), "items": items}, f, ensure_ascii=False, indent=2)
    return {"saved_to": str(out_path), "count": len(items)}