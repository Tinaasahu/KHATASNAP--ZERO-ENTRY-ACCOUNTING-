import React, { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';

export default function TopBar() {
  const [time, setTime] = useState(new Date());
  const location = useLocation();

  useEffect(() => {
    const int = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(int);
  }, []);

  const getTitle = () => {
    if (location.pathname.includes('/ocr')) return 'Bill Processor';
    if (location.pathname.includes('/calculator')) return 'Smart Calculator';
    if (location.pathname.includes('/inventory')) return 'Inventory Management';
    return 'Dashboard';
  };

  return (
    <div style={{ height: '56px', background: 'var(--surface)', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', flexShrink: 0 }}>
      <h1 style={{ fontSize: '16px', fontWeight: '500', margin: 0, color: 'var(--text-primary)' }}>{getTitle()}</h1>
      <div style={{ fontSize: '14px', color: 'var(--text-secondary)', fontWeight: '500' }}>
        {time.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true })}
      </div>
    </div>
  );
}
