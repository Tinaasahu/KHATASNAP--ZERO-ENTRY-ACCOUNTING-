import React from 'react';

export default function Badge({ variant = 'neutral', children, className = '', style = {}, ...props }) {
  return (
    <span className={`badge badge-${variant} ${className}`} style={style} {...props}>
      {children}
    </span>
  );
}
