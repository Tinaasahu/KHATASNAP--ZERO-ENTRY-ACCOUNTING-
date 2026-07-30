import React from 'react';

export default function Spinner({ size = 16, style = {} }) {
  return (
    <div 
      className="spinner spinner-primary" 
      style={{ width: size, height: size, ...style }} 
    />
  );
}
