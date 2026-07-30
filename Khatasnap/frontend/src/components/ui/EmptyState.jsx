import React from 'react';

export default function EmptyState({ icon, message, description, action }) {
  return (
    <div style={{ padding: '32px 16px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
      {icon && <div style={{ color: 'var(--text-hint)', marginBottom: '8px', display: 'flex' }}>{icon}</div>}
      {message && <div style={{ fontSize: '16px', fontWeight: '500', color: 'var(--text-primary)' }}>{message}</div>}
      {description && <div style={{ fontSize: '14px', color: 'var(--text-secondary)' }}>{description}</div>}
      {action && <div style={{ marginTop: '8px' }}>{action}</div>}
    </div>
  );
}
