import client from './client';

export const transcribe = (transcript) => {
  return client.post('/api/voice/transcribe', { transcript }).then(res => res.data.data);
};

export const transcribeInventory = (transcript) => {
  return client.post('/api/voice/inventory', { transcript }).then(res => res.data.data);
};

export const confirmVoice = (contractData) => {
  return client.post('/api/voice/confirm', contractData).then(res => res.data.data);
};
