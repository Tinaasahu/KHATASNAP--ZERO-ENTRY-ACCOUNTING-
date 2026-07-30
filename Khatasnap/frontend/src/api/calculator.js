import client from './client';

export const resolvePrice = (price, hour, day) => {
  return client.post('/api/calculator/resolve-price', { price, hour, day })
    .then(res => res.data.data);
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
