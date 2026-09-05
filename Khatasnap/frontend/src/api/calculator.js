import client from './client';

export const resolvePrice = (price, hour, day, cart_item_ids = [], asr_transcript = '') => {
  return client.post('/api/calculator/resolve-price', { price, hour, day, cart_item_ids, asr_transcript })
    .then(res => res.data.data);
};

export const predictItem = (price, hour, day, cart_item_ids = [], asr_transcript = '') => {
  return client.post('/api/calculator/predict-item', { price, hour, day, cart_item_ids, asr_transcript })
    .then(res => res.data.data);
};

export const predictConfidence = (price, asr_transcript = '', hour = null) => {
  return client.post('/api/calculator/predict-confidence', { price, asr_transcript, hour })
    .then(res => res.data.data || res.data);
};

export const recordFeedback = (product_id, product_name, price, hour = null, day = null) => {
  return client.post('/api/calculator/record-feedback', { product_id, product_name, price, hour, day })
    .then(res => res.data.data || res.data);
};

export const selectItem = (price, item_id, item_name, hour, day) => {
  return client.post('/api/calculator/select-item', { price, item_id, item_name, hour, day })
    .then(res => res.data.data);
};

export const submitSession = (entries, expression, result, spoken_context, unresolved_operands) => {
  return client.post('/api/calculator/submit-session', { entries, expression, result, spoken_context, unresolved_operands })
    .then(res => res.data.data);
};

export const getHistory = (limit = 20, offset = 0) => {
  return client.get(`/api/calculator/history?limit=${limit}&offset=${offset}`)
    .then(res => res.data.data);
};

export const getPatternConfidence = (price) => {
  return client.get(`/api/calculator/pattern-confidence/${price}`)
    .then(res => res.data.data);
};

export const getLearningStats = () => {
  return client.get(`/api/calculator/learning-stats`)
    .then(res => res.data.data);
};

export const assignItem = (sessionId, payload) => {
  return client.patch(`/api/calculator/session/${sessionId}/assign-item`, payload)
    .then(res => res.data.data);
};

// ── Transaction Buffer API (parallel ASR + Calculator + Inventory) ────────

export const startBuffer = (txn_id) =>
  client.post('/api/txn-buffer/start', { txn_id }).then(r => r.data.data);

export const asrUpdate = (txn_id, segment) =>
  client.post('/api/txn-buffer/asr-update', { txn_id, segment }).then(r => r.data.data);

export const amountUpdate = (txn_id, amounts) =>
  client.post('/api/txn-buffer/amount-update', { txn_id, amounts }).then(r => r.data.data);

export const finalizeBuffer = (txn_id, amounts) =>
  client.post('/api/txn-buffer/finalize', { txn_id, amounts }).then(r => r.data.data);

export const commitBuffer = (txn_id, entries, expression, result, spoken_context, confidence_score) =>
  client.post('/api/txn-buffer/commit', {
    txn_id, entries, expression, result, spoken_context, confidence_score,
  }).then(r => r.data.data);

export const flagBuffer = (txn_id, reason, confidence_score, payload) =>
  client.post('/api/txn-buffer/flag', { txn_id, reason, confidence_score, payload })
    .then(r => r.data.data);

export const discardBuffer = (txn_id) =>
  client.post('/api/txn-buffer/discard', { txn_id }).then(r => r.data.data);

// ── Night Reconciliation API ──────────────────────────────────────────────

export const getNightReconciliation = (status = 'pending', limit = 50, offset = 0) =>
  client.get(`/api/night-reconciliation?status=${status}&limit=${limit}&offset=${offset}`)
    .then(r => r.data.data);

export const resolveNightReconciliation = (id, resolution, confirmedEntries = [], notes = '') =>
  client.post(`/api/night-reconciliation/${id}/resolve`, {
    resolution, confirmed_entries: confirmedEntries, notes,
  }).then(r => r.data.data);

export const getNightReconciliationStats = () =>
  client.get('/api/night-reconciliation/stats').then(r => r.data.data);

