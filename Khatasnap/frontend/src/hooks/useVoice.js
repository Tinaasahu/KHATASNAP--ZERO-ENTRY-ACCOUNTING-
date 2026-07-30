import { useState, useRef, useEffect, useCallback } from 'react';
import { transcribe } from '../api/voice';
import { useToast } from './useToast';

export function useVoice({ parseFn = transcribe, autoStopSeconds = 10 } = {}) {
  const [state, setState] = useState('idle'); // idle, listening, transcribing, done, error
  const [transcript, setTranscript] = useState('');
  const [intent, setIntent] = useState(null);
  const [timeLeft, setTimeLeft] = useState(0); // countdown seconds remaining
  const recognitionRef = useRef(null);
  const finalTranscriptRef = useRef('');
  const autoStopTimerRef = useRef(null);
  const countdownIntervalRef = useRef(null);
  const processedRef = useRef(false); // guard: ensure processTranscript called exactly once per session
  const processTranscriptRef = useRef(null); // stable ref so r.onend closure always has latest fn
  const toast = useToast();

  const clearTimers = useCallback(() => {
    if (autoStopTimerRef.current) {
      clearTimeout(autoStopTimerRef.current);
      autoStopTimerRef.current = null;
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current);
      countdownIntervalRef.current = null;
    }
    setTimeLeft(0);
  }, []);

  useEffect(() => {
    return () => {
      clearTimers();
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch(e) {}
      }
    };
  }, [clearTimers]);

  const start = useCallback(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      toast.error('Microphone not supported. Use Chrome or Edge.');
      setState('error');
      return;
    }

    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
    }

    const r = new SR();
    r.continuous = true;
    r.interimResults = true;
    r.lang = 'en-IN';
    recognitionRef.current = r;
    finalTranscriptRef.current = '';
    processedRef.current = false; // reset guard for this session

    r.onstart = () => {
      setState('listening');
      setTranscript('');
      setIntent(null);

      // Countdown + auto-stop mic after autoStopSeconds (default 10s)
      setTimeLeft(autoStopSeconds);
      let remaining = autoStopSeconds;
      countdownIntervalRef.current = setInterval(() => {
        remaining -= 1;
        setTimeLeft(remaining);
      }, 1000);

      autoStopTimerRef.current = setTimeout(() => {
        clearInterval(countdownIntervalRef.current);
        countdownIntervalRef.current = null;
        setTimeLeft(0);
        try { r.stop(); } catch(e) {}
      }, autoStopSeconds * 1000);
    };

    r.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          finalTranscriptRef.current += e.results[i][0].transcript + ' ';
        } else {
          interim += e.results[i][0].transcript;
        }
      }
      setTranscript(finalTranscriptRef.current + interim);
    };

    r.onerror = (e) => {
      clearTimers();
      if (e.error === 'aborted') return;
      toast.error('Microphone error: ' + e.error);
      setState('error');
    };

    // KEY FIX: r.onend fires whenever recognition stops — auto-timer OR manual stop.
    // processedRef prevents double-calling when manual stop already called processTranscript.
    r.onend = () => {
      clearTimers();
      if (!processedRef.current) {
        processedRef.current = true;
        processTranscriptRef.current?.(finalTranscriptRef.current);
      }
    };

    try {
      r.start();
    } catch (e) {
      toast.error('Could not start microphone');
      setState('error');
    }
  }, [toast, clearTimers, autoStopSeconds]);

  const processTranscript = useCallback(async (text) => {
    if (!text.trim()) {
      setState('idle');
      return;
    }
    setState('transcribing');
    try {
      const res = await parseFn(text);
      setIntent(res);
      setState('done');
    } catch (err) {
      setState('error');
    }
  }, [parseFn]);

  // Keep stable ref so r.onend closure always calls the latest processTranscript
  processTranscriptRef.current = processTranscript;

  const stop = useCallback(() => {
    clearTimers();
    if (recognitionRef.current && state === 'listening') {
      processedRef.current = true; // claim processing BEFORE r.stop() triggers onend
      try { recognitionRef.current.stop(); } catch(e) {}
      processTranscript(finalTranscriptRef.current);
    }
  }, [state, processTranscript, clearTimers]);

  const reset = useCallback(() => {
    setState('idle');
    setTranscript('');
    setIntent(null);
  }, []);

  return {
    state,
    transcript,
    intent,
    timeLeft,
    listeningSeconds: autoStopSeconds,
    start,
    stop,
    reset,
    setState,
  };
}
