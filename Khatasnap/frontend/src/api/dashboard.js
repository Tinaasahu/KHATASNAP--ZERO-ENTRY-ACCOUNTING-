import client from './client';

export const getShopkeeperDashboard = (days = 30) => {
  return client.get(`/api/dashboard/shopkeeper?days=${days}`).then(res => res.data.data);
};

export const getDailyProfitLoss = (days = 30) => {
  return client.get(`/api/dashboard/shopkeeper/daily?days=${days}`).then(res => res.data.data);
};

export const getShopkeeperInsights = (days = 30) => {
  return client.get(`/api/dashboard/shopkeeper/insights?days=${days}`).then(res => res.data.data);
};

