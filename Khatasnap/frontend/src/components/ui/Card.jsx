import React from 'react';

export default function Card({ title, shadow, children, className = '', style = {}, ...props }) {
  return (
    <div className={`card ${shadow ? 'card-shadow' : ''} ${className}`} style={style} {...props}>
      {title && <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '16px' }}>{title}</div>}
      {children}
    </div>
  );
}
