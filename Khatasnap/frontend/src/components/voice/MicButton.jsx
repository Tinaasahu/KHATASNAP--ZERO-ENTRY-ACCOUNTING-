import React from 'react';
import { Mic, Square } from 'lucide-react';
import { motion } from 'framer-motion';

const R = 22; // radius of the SVG circle
const CIRCUMFERENCE = 2 * Math.PI * R;

export default function MicButton({ state, onToggle, transcript, intent, timeLeft, maxSeconds = 10 }) {
  const isRecording = state === 'listening';
  const isDone = state === 'done';
  const isTranscribing = state === 'transcribing';

  const total = maxSeconds > 0 ? maxSeconds : 10;
  const safeLeft = typeof timeLeft === 'number' && !Number.isNaN(timeLeft) ? timeLeft : total;

  // Stroke-dashoffset goes from 0 (full ring) → CIRCUMFERENCE (empty) as time decreases
  const progress = isRecording ? safeLeft / total : 0;
  const dashOffset = CIRCUMFERENCE * (1 - progress);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px' }}>
      <div style={{ position: 'relative', width: 64, height: 64 }}>

        {/* Countdown SVG ring */}
        <svg
          width="64" height="64"
          style={{ position: 'absolute', inset: 0, transform: 'rotate(-90deg)', pointerEvents: 'none' }}
        >
          {/* Background track */}
          <circle cx="32" cy="32" r={R} fill="none" strokeWidth="3" stroke="var(--border)" />
          {/* Animated countdown arc */}
          {isRecording && (
            <circle
              cx="32" cy="32" r={R}
              fill="none"
              strokeWidth="3"
              stroke="var(--danger)"
              strokeDasharray={CIRCUMFERENCE}
              strokeDashoffset={dashOffset}
              strokeLinecap="round"
              style={{ transition: 'stroke-dashoffset 1s linear' }}
            />
          )}
          {isDone && (
            <circle cx="32" cy="32" r={R} fill="none" strokeWidth="3" stroke="var(--success)" strokeDasharray="4 4" />
          )}
        </svg>

        {/* Pulse animation when recording */}
        {isRecording && (
          <motion.div
            animate={{ scale: [1, 1.35], opacity: [0.7, 0] }}
            transition={{ repeat: Infinity, duration: 1.2 }}
            style={{
              position: 'absolute', inset: 4, borderRadius: '50%',
              backgroundColor: 'var(--danger)', zIndex: 0
            }}
          />
        )}

        {/* Main mic button */}
        <button
          id="mic-button"
          onClick={onToggle}
          title={
            isRecording ? 'Listening… tap to stop' :
            isDone ? 'Tap to listen again' :
            isTranscribing ? 'Processing…' :
            'Tap to speak your order'
          }
          style={{
            position: 'absolute',
            inset: 6,
            borderRadius: '50%',
            backgroundColor: isRecording ? 'var(--danger-light)' : isDone ? 'rgba(var(--success-rgb,52,211,153),0.15)' : 'var(--surface-2)',
            border: isDone ? '1.5px solid var(--success)' : 'none',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: isTranscribing ? 'default' : 'pointer',
            zIndex: 1,
            color: isRecording ? 'var(--danger)' : isDone ? 'var(--success)' : 'var(--text-primary)',
            boxShadow: 'var(--shadow-md)',
            transition: 'background-color 0.3s, color 0.3s',
          }}
        >
          {isRecording ? <Square size={20} /> : <Mic size={20} />}
        </button>

        {/* Countdown number badge */}
        {isRecording && (
          <motion.div
            key={safeLeft}
            initial={{ scale: 1.3, opacity: 0.5 }}
            animate={{ scale: 1, opacity: 1 }}
            style={{
              position: 'absolute', bottom: -2, right: -2,
              width: 18, height: 18, borderRadius: '50%',
              background: 'var(--danger)',
              color: '#fff',
              fontSize: '10px', fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              zIndex: 2, boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
            }}
          >
            {safeLeft}
          </motion.div>
        )}
      </div>

      {/* Status label */}
      {isRecording && (
        <div style={{ fontSize: '11px', color: 'var(--danger)', fontWeight: 600, letterSpacing: '0.5px' }}>
          🔴 Listening ({safeLeft}s / {total}s)
        </div>
      )}
      {isTranscribing && (
        <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Processing audio…</div>
      )}
      {isDone && (
        <div style={{ fontSize: '11px', color: 'var(--success)', fontWeight: 500 }}>
          ✓ Done — tap to add more
        </div>
      )}
      {!isRecording && !isTranscribing && !isDone && (
        <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Tap mic to speak</div>
      )}

      {/* Live transcript preview */}
      {transcript && isRecording && (
        <div style={{
          fontSize: '13px', fontStyle: 'italic',
          color: 'var(--text-secondary)',
          maxWidth: '200px', textAlign: 'center',
          lineHeight: 1.4,
        }}
        >
          "{transcript}"
        </div>
      )}

      {/* Success badge */}
      {intent && isDone && (
        <div className="badge badge-success">Parsed Command Ready</div>
      )}
    </div>
  );
}
