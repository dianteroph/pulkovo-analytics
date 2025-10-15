import React, { useMemo } from 'react';
import { Bubble } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  Tooltip,
  Legend,
  LinearScale,
  PointElement,
  Title,
} from 'chart.js';

ChartJS.register(Tooltip, Legend, LinearScale, PointElement, Title);

type Item = {
  salary_avg?: number | null;
  employer_mark?: number | null;
  title?: string;
  employer_name?: string;
};

export const SalaryBubbleChart: React.FC<{ items: Item[] }> = ({ items }) => {
  const data = useMemo(() => {
    const points = (items || [])
      .filter((i) => typeof i.salary_avg === 'number' && typeof i.employer_mark === 'number')
      .map((i) => ({
        x: i.employer_mark as number,
        y: (i.salary_avg as number) / 1000,
        r: 6,
        title: i.title,
        employer: i.employer_name,
      }));

    return {
      datasets: [
        {
          label: 'Вакансии',
          data: points as any,
          backgroundColor: 'rgba(37, 99, 235, 0.5)',
          borderColor: 'rgba(37, 99, 235, 1)',
        },
      ],
    };
  }, [items]);

  const options = useMemo(() => ({
    responsive: true,
    plugins: {
      legend: { display: false },
      title: { display: false, text: '' },
      tooltip: {
        callbacks: {
          label: (ctx: any) => {
            const d = ctx.raw;
            return `${d?.title || ''} – ${d?.employer || ''}: ${Math.round((d?.y || 0))} тыс.`;
          },
        },
      },
    },
    scales: {
      x: { title: { display: true, text: 'Рейтинг работодателя' }, min: 0, max: 5 },
      y: { title: { display: true, text: 'Зарплата, тыс. ₽' } },
    },
  }), []);

  return <Bubble data={data} options={options as any} />;
};



