import React from 'react';
import Spinner from './Spinner';

export default function Button({ 
  variant = 'primary', 
  size = 'md', 
  loading = false, 
  disabled = false, 
  icon, 
  children, 
  style = {}, 
  onClick, 
  ...props 
}) {
  const className = `btn btn-${variant} btn-${size} ${props.className || ''}`;

  return (
    <button 
      className={className} 
      style={style} 
      onClick={onClick} 
      disabled={disabled || loading} 
      {...props}
    >
      {loading && <Spinner size={size === 'sm' ? 14 : 18} style={{ marginRight: '8px' }} />}
      {!loading && icon && <span style={{ marginRight: '8px', display: 'flex' }}>{icon}</span>}
      {children}
    </button>
  );
}
