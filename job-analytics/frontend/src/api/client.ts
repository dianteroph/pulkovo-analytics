import axios from 'axios';

const api = axios.create({ baseURL: '/api' });

export async function fetchAnalyze(params: { query: string; area?: number | string; pages?: number; per_page?: number }) {
  const res = await api.get('/analyze', { params });
  return res.data;
}

export async function fetchResumeStats(params: { vacancy_query: string; area?: number | string; pages?: number; per_page?: number }) {
  const res = await api.get('/resume-stats', { params });
  return res.data;
}



