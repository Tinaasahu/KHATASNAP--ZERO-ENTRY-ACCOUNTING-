import client from './client';

export const check = (contractData) => {
  return client.post('/api/sre/check', contractData).then(res => res.data.data);
};

export const confirmBills = (contractData) => {
  return client.post('/api/bills/confirm', contractData).then(res => res.data.data);
};
