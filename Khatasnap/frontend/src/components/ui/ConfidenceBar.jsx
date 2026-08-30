/**
 * ConfidenceBar — Visual representation of the 3-signal confidence score.
 *
 * Props:
 *   confidence {object} — result from /api/txn-buffer/finalize
 *   compact    {bool}   — smaller inline variant for the calculator header
 *   animate    {bool}   — animate fill on mount (default true)
 */
import React, { useEffect, useRef, useState } from 'react';

const THRESHOLDS = { high: 0.75, medium: 0.50 };

function pct(score) {
  return Math.round(Math.min(1, Math.max(0, score)) * 100);
}

function decisionColor(decision) {
  if (decision === 'high')   return { bar: '#22c55e', text: '#16a34a', bg: 'rgba(34,197,94,0.1)' };
  if (decision === 'medium') return { bar: '#f59e0b', text: '#d97706', bg: 'rgba(245,158,11,0.1)' };
  return                             { bar: '#ef4444', text: '#dc2626', bg: 'rgba(239,68,68,0.1)'  };
}

function decisionLabel(decision) {
  if (decision === 'high')   return '✅ High Confidence';
  if (decision === 'medium') return '⚠️ Medium — Review';
  return '🔴 Low — Queued';
}

export default function ConfidenceBar({ confidence, compact = false, animate = true }) {
  const [displayPct, setDisplayPct] = useState(0);
  const rafRef = useRef(null);

  const score    = confidence?.score ?? 0;
  const decision = confidence?.decision ?? 'low';
  const signals  = confidence?.signals ?? {};
  const matched  = confidence?.matched_items ?? [];
  const unmatched = confidence?.unmatched_amounts ?? [];
  const colors   = decisionColor(decision);
  const target   = pct(score);

  // Animate bar fill
  useEffect(() => {
    if (!animate) { setDisplayPct(target); return; }
    let current = 0;
    const step = () => {
      current = Math.min(current + 2, target);
      setDisplayPct(current);
      if (current < target) rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [target, animate]);

  if (compact) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: '6px',
        padding: '4px 8px', borderRadius: '20px',
        background: colors.bg, border: `1px solid ${colors.bar}30`,
        fontSize: '11px', fontWeight: 600, color: colors.text,
        transition: 'all 0.3s',
      }}>
        <div style={{
          width: '40px', height: '4px', borderRadius: '2px',
          background: 'var(--border)', overflow: 'hidden',
        }}>
          <div style={{
            height: '100%', width: `${displayPct}%`,
            background: colors.bar, borderRadius: '2px',
            transition: 'width 0.1s linear',
          }} />
        </div>
        <span>{displayPct}%</span>
      </div>
    );
  }

  return (
    <div style={{
      background: 'var(--surface)',
      border: `1px solid ${colors.bar}40`,
      borderRadius: 'var(--radius-lg)',
      padding: '14px 16px',
      display: 'flex', flexDirection: 'column', gap: '10px',
    }}>
      {/* Header row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: colors.text }}>
          {decisionLabel(decision)}
        </span>
        <span style={{ fontSize: '20px', fontWeight: 700, color: colors.text }}>
          {displayPct}%
        </span>
      </div>

      {/* Bar */}
      <div style={{
        height: '8px', borderRadius: '4px',
        background: 'var(--surface-elevated)',
        overflow: 'hidden', position: 'relative',
      }}>
        {/* Threshold markers */}
        <div style={{
          position: 'absolute', left: `${pct(THRESHOLDS.medium)}%`,
          top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.3)',
          zIndex: 1,
        }} />
        <div style={{
          position: 'absolute', left: `${pct(THRESHOLDS.high)}%`,
          top: 0, bottom: 0, width: '1px', background: 'rgba(255,255,255,0.3)',
          zIndex: 1,
        }} />
        <div style={{
          height: '100%',
          width: `${displayPct}%`,
          background: `linear-gradient(90deg, #ef4444 0%, #f59e0b ${pct(THRESHOLDS.medium)}%, #22c55e ${pct(THRESHOLDS.high)}%)`,
          borderRadius: '4px',
          transition: 'width 0.1s linear',
          position: 'relative', zIndex: 2,
        }} />
      </div>

      {/* Signal breakdown */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <SignalPill icon="🎙️" label="ASR Price" score={signals.asr_price ?? 0} />
        <SignalPill icon="🗣️" label="ASR Name"  score={signals.asr_name  ?? 0} />
        <SignalPill icon="📦" label="Inventory" score={signals.inventory  ?? 0} />
        <SignalPill icon="📈" label="Pattern"   score={signals.pattern    ?? 0} />
      </div>

      {/* Matched items */}
      {matched.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {matched.map((item, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              fontSize: '12px', padding: '3px 6px', borderRadius: '6px',
              background: item.in_stock ? 'rgba(34,197,94,0.07)' : 'rgba(239,68,68,0.07)',
            }}>
              <span style={{ color: 'var(--text-primary)' }}>
                {item.item_name}
                {item.qty > 1 && <span style={{ color: 'var(--text-secondary)' }}> ×{item.qty}</span>}
              </span>
              <span style={{ display: 'flex', gap: '6px', color: 'var(--text-secondary)' }}>
                <span>₹{item.price}</span>
                <span style={{ color: item.in_stock ? '#22c55e' : '#ef4444' }}>
                  {item.in_stock ? '✓ In stock' : '✗ Out'}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Unmatched amounts */}
      {unmatched.length > 0 && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
          ⚠️ {unmatched.length} amount{unmatched.length > 1 ? 's' : ''} not matched: {unmatched.map(a => `₹${a}`).join(', ')}
        </div>
      )}

      {/* Summary */}
      {confidence?.summary && (
        <div style={{ fontSize: '11px', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
          {confidence.summary}
        </div>
      )}
    </div>
  );
}

function SignalPill({ icon, label, score }) {
  const pctVal = pct(score);
  const color = pctVal >= 75 ? '#22c55e' : pctVal >= 50 ? '#f59e0b' : pctVal > 0 ? '#94a3b8' : '#475569';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: '4px',
      fontSize: '10px', padding: '2px 7px', borderRadius: '12px',
      background: 'var(--surface-elevated)',
      color: 'var(--text-secondary)',
    }}>
      <span>{icon}</span>
      <span>{label}</span>
      <span style={{ fontWeight: 700, color }}>{pctVal}%</span>
    </div>
  );
}
