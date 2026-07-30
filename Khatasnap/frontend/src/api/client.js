import axios from 'axios';

const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE || 'http://localhost:8000',
  headers: {
    'Content-Type': 'application/json',
  },
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    let message = 'An unknown error occurred on the server';
    let detail = null;
    let status = error.response ? error.response.status : 500;

    if (error.response) {
      if (error.response.data) {
        message = error.response.data.error || error.response.data.detail || message;
        detail = error.response.data;
      }
    } else if (error.request) {
      message = 'Network error or service unavailable. Check your connection.';
      status = 503;
    } else {
      message = error.message;
    }

    const structuredError = {
      message,
      detail,
      status,
    };
    
    return Promise.reject(structuredError);
  }
);

export default client;
