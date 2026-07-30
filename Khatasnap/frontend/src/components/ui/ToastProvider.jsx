import React, { useState, useCallback } from 'react';
import { ToastContext } from '../../hooks/useToast';
import { Info, CheckCircle, AlertTriangle, AlertCircle, X } from 'lucide-react';

export default function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const addToast = useCallback((msg, variant = 'info') => {
    const id = Date.now().toString();
    setToasts(prev => [...prev, { id, msg, variant }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  }, []);

  const toast = {
    success: (msg) => addToast(msg, 'success'),
    error: (msg) => addToast(msg, 'error'),
    warning: (msg) => addToast(msg, 'warning'),
    info: (msg) => addToast(msg, 'info')
  };

  const removeToast = (id) => setToasts(prev => prev.filter(t => t.id !== id));

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toast-container">
        {toasts.map(t => (
          <div key={t.id} className="toast" style={{
            borderLeft: `4px solid ${
              t.variant === 'success' ? 'var(--success)' :
              t.variant === 'error' ? 'var(--danger)' :
              t.variant === 'warning' ? 'var(--warning)' : 'var(--accent)'
            }`
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
               {t.variant === 'success' && <CheckCircle size={20} color="var(--success)" />}
               {t.variant === 'error' && <AlertCircle size={20} color="var(--danger)" />}
               {t.variant === 'warning' && <AlertTriangle size={20} color="var(--warning)" />}
               {t.variant === 'info' && <Info size={20} color="var(--accent)" />}
            </div>
            <div style={{ flex: 1, fontSize: '14px' }}>{t.msg}</div>
            <button style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--text-hint)' }} onClick={() => removeToast(t.id)}>
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
