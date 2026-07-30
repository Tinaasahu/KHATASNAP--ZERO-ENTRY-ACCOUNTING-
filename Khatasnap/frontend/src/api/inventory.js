import client from './client';

export const getSnapshot = () => client.get('/api/inventory').then(res => res.data.data);
export const searchInventory = (q) => client.get(`/api/inventory/search?q=${encodeURIComponent(q)}`).then(res => res.data.data);

export const update = (delta) => client.post('/api/inventory/update', delta).then(res => res.data.data);
export const deleteProduct = (id) => client.delete(`/api/products/${id}`).then(res => res.data);
export const updateProduct = (id, data) => client.put(`/api/products/${id}`, data).then(res => res.data);
export const addPriceAlias = (payload) => client.post('/api/inventory/add-price-alias', payload).then(res => res.data.data);

export const addProduct = (data) => client.post('/api/products', data).then(res => res.data.data);
export const getCategories = () => client.get('/api/categories').then(res => res.data.data);
export const getSuppliers = () => client.get('/api/suppliers').then(res => res.data.data);
export const bulkUpdateProducts = (ids, fields) =>
  client.post('/api/products/bulk-update', { ids, fields }).then(res => res.data.data);

export const getInventoryAlerts = (days = 30) =>
  client.get(`/api/inventory/alerts?days=${days}`).then(res => res.data.data);
