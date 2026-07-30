import client from './client';

export const runReconciliation = (minutes = 60) =>
  client.post('/api/reconciliation/run', { minutes }).then((res) => res.data.data);

export const getReconFlags = (status = 'pending', limit = 50) =>
  client.get(`/api/reconciliation/flags?status=${encodeURIComponent(status)}&limit=${limit}`).then((res) => res.data.data);

export const resolveReconFlag = (id, payload) =>
  client.post(`/api/reconciliation/flags/${id}/resolve`, payload).then((res) => res.data.data);

