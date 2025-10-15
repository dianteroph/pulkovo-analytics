import React, { useEffect, useMemo, useState } from 'react';
import { fetchAnalyze, fetchResumeStats } from './api/client';
import { SalaryBubbleChart } from './components/SalaryBubbleChart';
import { SalaryStatsCard } from './components/SalaryStatsCard';

export const App: React.FC = () => {
  const [query, setQuery] = useState('контролер кпп');
  const [area] = useState<number>(2);
  const [pages] = useState<number>(2);
  const [perPage] = useState<number>(50);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<any>(null);
  const [resumeStats, setResumeStats] = useState<any>(null);

  const presets = useMemo(() => [
    { value: 'контролер кпп', label: 'Инспекторы-контролёры' },
    { value: 'инспектор досмотр', label: 'Инспекторы по досмотру' },
    { value: 'инспектор перрон', label: 'Инспекторы перронного контроля' },
    { value: 'гбр, охрана', label: 'Инспектор ГБР' }
  ], []);

  const load = async () => {
    setLoading(true);
    try {
      const [analyze, resumes] = await Promise.all([
        fetchAnalyze({ query, area, pages, per_page: perPage }),
        fetchResumeStats({ vacancy_query: query, area, pages, per_page: perPage })
      ]);
      setData(analyze);
      setResumeStats(resumes);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="container">
      <h1>Аналитика вакансий</h1>
      <div className="meta">📍 Санкт-Петербург</div>

      <div className="controls">
        <select value={query} onChange={(e) => setQuery(e.target.value)}>
          <option value="">Выберите вакансию</option>
          {presets.map(p => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>
        <button onClick={load} disabled={loading}>Найти</button>
      </div>

      {data && (
        <div className="row">
          <div className="card">
            <h3>Зарплата vs Рейтинг работодателя</h3>
            <SalaryBubbleChart items={data.items || []} />
          </div>
          <div className="card">
            <h3>Статистика зарплат</h3>
            <SalaryStatsCard salaries={data.salaries} />
          </div>
        </div>
      )}

      {resumeStats && (
        <div className="card" style={{ marginTop: 24 }}>
          <h3>Статистика резюме</h3>
          <div className="meta">Резюме (всего: {resumeStats.total_resumes || 0}, активные: {resumeStats.active_resumes || 0})</div>
          <div className="grid4">
            <div className="miniCard"><div>Активные резюме</div><b>{resumeStats.active_resumes ?? '—'}</b></div>
            <div className="miniCard"><div>Доля активных</div><b>{typeof resumeStats.active_share === 'number' ? Math.round(resumeStats.active_share * 100) + '%' : '—'}</b></div>
            <div className="miniCard"><div>Вакансий по запросу</div><b>{resumeStats.vacancy_count ?? '—'}</b></div>
            <div className="miniCard"><div>Резюме на вакансию</div><b>{typeof resumeStats.resumes_per_vacancy === 'number' ? resumeStats.resumes_per_vacancy.toFixed(2) : '—'}</b></div>
          </div>
        </div>
      )}
    </div>
  );
};



