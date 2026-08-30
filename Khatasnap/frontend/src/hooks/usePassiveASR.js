/**
 * usePassiveASR — Improved Version
 *
 * Key improvements over original:
 *  1. Unlimited restarts with exponential backoff (500ms → 1s → 2s → 4s max)
 *  2. Pause detection: fires onSpeechPause after 8s silence
 *  3. Interim transcript exposed separately from buffer (for live display)
 *  4. Segment expiry: removes segments older than 90s from rolling buffer
 *  5. Proper cleanup on unmount via abortController pattern
 *  6. Optional onSegment callback for real-time ASR-update pushes
 */
import { useState, useRef, useEffect, useCallback } from 'react';

const BACKOFF_STEPS  = [500, 1000, 2000, 4000]; // ms between restarts
const SEGMENT_TTL_MS = 90_000;   // discard segments older than 90 seconds
const PAUSE_DELAY_MS = 8_000;    // fire onSpeechPause after 8s of silence

export function usePassiveASR({ onSegment, onSpeechPause } = {}) {
  const [status, setStatus]           = useState('idle');
  const [interimText, setInterimText] = useState('');   // live display only

  const statusRef          = useRef('idle');
  const bufferRef          = useRef([]);   // [{ text: string, ts: number }]
  const [lastUpdated, setLastUpdated] = useState(null);

  const recognitionRef      = useRef(null);
  const backoffIdxRef       = useRef(0);
  const restartTimerRef     = useRef(null);
  const pauseTimerRef       = useRef(null);
  const isIntentionalRef    = useRef(false);
  const mountedRef          = useRef(true);

  // Keep statusRef in sync
  useEffect(() => { statusRef.current = status; }, [status]);

  // ── Clear the pause timer and reset it ──────────────────────────────────
  const _resetPauseTimer = useCallback(() => {
    if (pauseTimerRef.current) clearTimeout(pauseTimerRef.current);
    pauseTimerRef.current = setTimeout(() => {
      if (statusRef.current === 'listening' && onSpeechPause) {
        onSpeechPause();
      }
    }, PAUSE_DELAY_MS);
  }, [onSpeechPause]);

  // ── Prune expired segments ───────────────────────────────────────────────
  const _pruneBuffer = () => {
    const cutoff = Date.now() - SEGMENT_TTL_MS;
    bufferRef.current = bufferRef.current.filter(s => s.ts > cutoff);
  };

  // ── Schedule a restart with backoff ─────────────────────────────────────
  const _scheduleRestart = useCallback(() => {
    if (!mountedRef.current || isIntentionalRef.current) return;
    const delay = BACKOFF_STEPS[Math.min(backoffIdxRef.current, BACKOFF_STEPS.length - 1)];
    backoffIdxRef.current = Math.min(backoffIdxRef.current + 1, BACKOFF_STEPS.length - 1);
    restartTimerRef.current = setTimeout(() => {
      if (!mountedRef.current || isIntentionalRef.current) return;
      if (statusRef.current !== 'error' && statusRef.current !== 'unavailable') {
        _startRecognition();
      }
    }, delay);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Core start function ──────────────────────────────────────────────────
  const _startRecognition = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      if (mountedRef.current) setStatus('unavailable');
      return;
    }

    // Abort any existing instance
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch (_) {}
    }

    const r = new SR();
    r.continuous      = true;
    r.interimResults  = true;
    r.lang            = 'en-IN';
    recognitionRef.current = r;

    r.onstart = () => {
      if (!mountedRef.current) return;
      setStatus('listening');
      statusRef.current = 'listening';
      backoffIdxRef.current = 0; // reset backoff on successful start
      _resetPauseTimer();
    };

    r.onresult = (event) => {
      if (!mountedRef.current) return;
      let interim = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          const text = event.results[i][0].transcript.trim();
          if (text) {
            const segment = { text, ts: Date.now() };
            _pruneBuffer();
            bufferRef.current.push(segment);
            setLastUpdated(Date.now());
            _resetPauseTimer();
            // Notify parent (for real-time backend ASR-update push)
            if (onSegment) onSegment(text);
          }
        } else {
          interim += event.results[i][0].transcript;
        }
      }
      if (mountedRef.current) setInterimText(interim);
    };

    r.onerror = (event) => {
      if (!mountedRef.current) return;
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
        setStatus('error');
        statusRef.current = 'error';
        isIntentionalRef.current = true;
      }
      // For network / aborted errors — let onend handle restart
    };

    r.onend = () => {
      if (!mountedRef.current) return;
      if (mountedRef.current) setInterimText('');
      if (isIntentionalRef.current) {
        if (mountedRef.current && statusRef.current !== 'error') {
          setStatus('idle');
          statusRef.current = 'idle';
        }
        return;
      }
      // Auto-restart with backoff (no cap on restarts)
      if (statusRef.current !== 'error' && statusRef.current !== 'unavailable') {
        _scheduleRestart();
      }
    };

    try {
      r.start();
    } catch (_) {
      _scheduleRestart();
    }
  }, [_resetPauseTimer, _scheduleRestart, onSegment]);

  // ── Initialise on mount ──────────────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) setStatus('unavailable');

    return () => {
      mountedRef.current = false;
      isIntentionalRef.current = true;
      if (restartTimerRef.current) clearTimeout(restartTimerRef.current);
      if (pauseTimerRef.current) clearTimeout(pauseTimerRef.current);
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch (_) {}
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Public API ───────────────────────────────────────────────────────────
  const start = useCallback(() => {
    if (statusRef.current === 'listening') return;
    if (statusRef.current === 'unavailable' || statusRef.current === 'error') return;
    isIntentionalRef.current = false;
    backoffIdxRef.current = 0;
    _startRecognition();
  }, [_startRecognition]);

  const stop = useCallback(() => {
    isIntentionalRef.current = true;
    if (restartTimerRef.current) {
      clearTimeout(restartTimerRef.current);
      restartTimerRef.current = null;
    }
    if (pauseTimerRef.current) {
      clearTimeout(pauseTimerRef.current);
      pauseTimerRef.current = null;
    }
    if (recognitionRef.current) {
      try {
        recognitionRef.current.abort(); // Immediately release microphone hardware
      } catch (_) {}
      recognitionRef.current = null;
    }
    if (mountedRef.current) {
      setStatus('idle');
      statusRef.current = 'idle';
      setInterimText('');
    }
  }, []);

  const clearBuffer = useCallback(() => {
    bufferRef.current = [];
    setLastUpdated(Date.now());
  }, []);

  /** Returns the full accumulated transcript text (all non-expired segments joined). */
  const getBuffer = useCallback(() => {
    _pruneBuffer();
    return bufferRef.current.map(s => s.text).join(' ').trim();
  }, []);

  /** Returns raw segment array (for backend submission). */
  const getSegments = useCallback(() => {
    _pruneBuffer();
    return [...bufferRef.current];
  }, []);

  return {
    status,
    interimText,
    lastUpdated,
    start,
    stop,
    getBuffer,
    getSegments,
    clearBuffer,
  };
}

