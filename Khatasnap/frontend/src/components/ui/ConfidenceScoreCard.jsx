import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { ChevronDown, ChevronUp, CheckCircle, Sparkles, AlertCircle, HelpCircle, ArrowRight } from 'lucide-react';

/**
 * ConfidenceScoreCard — Premium UI component for KhataSnap's Explainable Confidence Engine.
 * Displays prediction, green/status badge, animated progress bar, expandable "Why this prediction?",
 * 5 signal score rows, explanation bullet points, auto-select banner, one-tap confirmation button,
 * and top alternatives list.
 */
export default function ConfidenceScoreCard({
  predictionResult,
  onConfirmPrediction,
  onSelectAlternative,
  enteredPrice
}) {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!predictionResult || !predictionResult.prediction) {
    return null;
  }

  const { prediction, reasons = {}, explanation = [], alternatives = [] } = predictionResult;
  const { name, confidence = 0, status = 'LOW', emoji = '📦', price } = prediction;

  // Status Styling Config
  const isHigh = status === 'HIGH' || confidence >= 90;
  const isMedium = status === 'MEDIUM' || (confidence >= 75 && confidence < 90);
  const isLow = status === 'LOW' || confidence < 75;

  const getStatusColor = () => {
    if (isHigh) return { bg: 'rgba(34, 197, 94, 0.1)', border: 'rgba(34, 197, 94, 0.3)', text: '#16a34a', bar: '#22c55e', badge: 'High Match' };
    if (isMedium) return { bg: 'rgba(245, 158, 11, 0.1)', border: 'rgba(245, 158, 11, 0.3)', text: '#d97706', bar: '#f59e0b', badge: 'Review Needed' };
    return { bg: 'rgba(100, 116, 139, 0.1)', border: 'rgba(148, 163, 184, 0.3)', text: '#64748b', bar: '#94a3b8', badge: 'Low Confidence' };
  };

  const styleConfig = getStatusColor();

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -8 }}
      style={{
        background: 'var(--surface, #ffffff)',
        border: `1.5px solid ${styleConfig.border}`,
        borderRadius: '16px',
        padding: '16px',
        marginTop: '12px',
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.05)',
        display: 'flex',
        flexDirection: 'column',
        gap: '12px'
      }}
    >
      {/* Header Row: Product Info & Confidence Badge */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            fontSize: '24px',
            width: '40px',
            height: '40px',
            borderRadius: '10px',
            background: styleConfig.bg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            {emoji}
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: '15px', color: 'var(--text-primary, #0f172a)' }}>
              {name}
            </div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary, #64748b)' }}>
              {price ? `Listed Price: ₹${price}` : ''} {enteredPrice ? `(Entered: ₹${enteredPrice})` : ''}
            </div>
          </div>
        </div>

        {/* Green / Status Badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '4px 10px',
          borderRadius: '20px',
          background: styleConfig.bg,
          border: `1px solid ${styleConfig.border}`,
          color: styleConfig.text,
          fontSize: '12px',
          fontWeight: 700
        }}>
          {isHigh ? <CheckCircle size={14} color="#16a34a" /> : isMedium ? <Sparkles size={14} color="#d97706" /> : <HelpCircle size={14} color="#64748b" />}
          <span>{confidence}% Match</span>
        </div>
      </div>

      {/* Animated Progress Bar */}
      <div style={{
        height: '8px',
        borderRadius: '4px',
        background: 'var(--surface-elevated, #f1f5f9)',
        overflow: 'hidden',
        position: 'relative'
      }}>
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${confidence}%` }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          style={{
            height: '100%',
            background: `linear-gradient(90deg, ${styleConfig.bar}, ${styleConfig.text})`,
            borderRadius: '4px'
          }}
        />
      </div>

      {/* Threshold Action Banner / Button */}
      {isHigh && (
        <div style={{
          fontSize: '12px',
          color: '#16a34a',
          background: 'rgba(34, 197, 94, 0.08)',
          padding: '8px 12px',
          borderRadius: '8px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          fontWeight: 600
        }}>
          <span>✨ Auto-selected with high confidence!</span>
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>Tap alternatives to change</span>
        </div>
      )}

      {isMedium && (
        <button
          onClick={() => onConfirmPrediction && onConfirmPrediction(prediction)}
          style={{
            width: '100%',
            padding: '10px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #f59e0b, #d97706)',
            color: '#ffffff',
            border: 'none',
            fontWeight: 700,
            fontSize: '13px',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            boxShadow: '0 2px 8px rgba(245, 158, 11, 0.3)'
          }}
        >
          <span>One-Tap Confirm: {name}</span>
          <ArrowRight size={15} />
        </button>
      )}

      {/* Expandable "Why this prediction?" Section */}
      <div style={{ borderTop: '1px solid var(--border, #e2e8f0)', paddingTop: '8px' }}>
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-secondary, #64748b)',
            fontSize: '12px',
            fontWeight: 600,
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '4px 0'
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <HelpCircle size={13} color="var(--primary, #3b82f6)" />
            Why this prediction?
          </span>
          {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              style={{ overflow: 'hidden', marginTop: '8px' }}
            >
              {/* 5 Signal Rows Breakdown */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(2, 1fr)',
                gap: '8px',
                background: 'var(--surface-elevated, #f8fafc)',
                padding: '10px',
                borderRadius: '10px',
                marginBottom: '10px'
              }}>
                <SignalScoreRow label="🎙️ ASR Similarity" score={reasons.asr ?? 0} maxScore={40} />
                <SignalScoreRow label="🏷️ Price Match" score={reasons.price ?? 0} maxScore={25} />
                <SignalScoreRow label="📦 Inventory" score={reasons.inventory ?? 0} maxScore={15} />
                <SignalScoreRow label="📊 Sales Pattern" score={reasons.salesPattern ?? 0} maxScore={10} />
                <SignalScoreRow label="⏰ Time Pattern" score={reasons.timePattern ?? 0} maxScore={10} />
              </div>

              {/* Explanation Bullets */}
              {explanation.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', paddingLeft: '4px' }}>
                  <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-hint, #94a3b8)', marginBottom: '2px' }}>
                    KEY REASONS:
                  </div>
                  {explanation.map((item, idx) => (
                    <div key={idx} style={{ fontSize: '11px', color: 'var(--text-primary, #334155)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                      <span style={{ color: '#22c55e' }}>•</span>
                      <span>{item}</span>
                    </div>
                  ))}
                </div>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Alternatives List */}
      {alternatives.length > 0 && (
        <div style={{ borderTop: '1px dotted var(--border, #e2e8f0)', paddingTop: '8px' }}>
          <div style={{ fontSize: '11px', fontWeight: 700, color: 'var(--text-hint, #94a3b8)', marginBottom: '6px' }}>
            TOP ALTERNATIVES:
          </div>
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            {alternatives.map((alt, idx) => (
              <button
                key={alt.id || idx}
                onClick={() => onSelectAlternative && onSelectAlternative(alt)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '4px 10px',
                  borderRadius: '12px',
                  background: 'var(--surface-elevated, #f1f5f9)',
                  border: '1px solid var(--border, #cbd5e1)',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-primary, #334155)',
                  cursor: 'pointer',
                  transition: 'all 0.2s'
                }}
              >
                <span>{alt.name}</span>
                <span style={{ color: '#3b82f6', fontWeight: 700 }}>{alt.confidence}%</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}

function SignalScoreRow({ label, score, maxScore }) {
  const pct = Math.round((score / maxScore) * 100);
  const color = pct >= 80 ? '#22c55e' : pct >= 50 ? '#f59e0b' : '#94a3b8';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: 'var(--text-secondary, #64748b)' }}>
        <span>{label}</span>
        <span style={{ fontWeight: 700, color }}>{score}/{maxScore}</span>
      </div>
      <div style={{ height: '4px', background: '#e2e8f0', borderRadius: '2px', overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: '2px' }} />
      </div>
    </div>
  );
}
