import client from './client';

export const uploadBill = (file) => {
  const formData = new FormData();
  formData.append('file', file);
  return client.post('/api/ocr/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  }).then(res => res.data.data);
};

export const confirmBill = (contractData) => {
  return client.post('/api/ocr/confirm', contractData).then(res => res.data.data);
};
