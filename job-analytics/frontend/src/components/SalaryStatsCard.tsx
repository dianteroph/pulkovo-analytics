import React from 'react';

type Salaries = {
  min?: number | null;
  median?: number | null;
  avg?: number | null;
  max?: number | null;
};

export const SalaryStatsCard: React.FC<{ salaries?: Salaries }> = ({ salaries }) => {
  const s = salaries || {};
  const fmt = (v?: number | null) => (typeof v === 'number' ? Math.round(v).toLocaleString('ru-RU') + ' ₽' : '—');
  return (
    <div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div className="miniCard"><div>Мин.</div><b>{fmt(s.min)}</b></div>
        <div className="miniCard"><div>Медиана</div><b>{fmt(s.median)}</b></div>
        <div className="miniCard"><div>Средняя</div><b>{fmt(s.avg)}</b></div>
        <div className="miniCard"><div>Макс.</div><b>{fmt(s.max)}</b></div>
      </div>
    </div>
  );
};






