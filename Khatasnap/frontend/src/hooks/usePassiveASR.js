import { useState, useRef, useEffect, useCallback } from 'react';

export function usePassiveASR() {
  const [status, setStatus] = useState('idle'); // 'idle' | 'listening' | 'error' | 'unavailable'
  const statusRef = useRef(status);
  useEffect(() => { statusRef.current = status; }, [status]);

  const bufferRef = useRef('');
  const [lastUpdated, setLastUpdated] = useState(null);
  
  const recognitionRef = useRef(null);
  const restartCountRef = useRef(0);
  const isIntentionalStopRef = useRef(false);

  useEffect(() => {
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      setStatus('unavailable');
      return;
    }

    const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new SpeechRecognitionAPI();
    
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-IN';

    recognition.onresult = (event) => {
      let finalTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; ++i) {
        if (event.results[i].isFinal) {
          finalTranscript += event.results[i][0].transcript + ' ';
        }
      }
      
      if (finalTranscript) {
         let newBuffer = bufferRef.current + ' ' + finalTranscript;
         if (newBuffer.length > 800) {
            newBuffer = newBuffer.substring(newBuffer.length - 600);
         }
         bufferRef.current = newBuffer.trim();
         setLastUpdated(Date.now());
      }
    };

    recognition.onerror = (event) => {
      if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
         setStatus('error');
         isIntentionalStopRef.current = true;
      }
    };

    recognition.onend = () => {
      if (!isIntentionalStopRef.current && statusRef.current !== 'error' && restartCountRef.current < 2) {
         restartCountRef.current += 1;
         try { recognition.start(); } catch(e) {}
      } else if (statusRef.current !== 'error' && statusRef.current !== 'unavailable') {
         setStatus('idle');
      }
    };

    recognitionRef.current = recognition;

    return () => {
       isIntentionalStopRef.current = true;
       if (recognitionRef.current) recognitionRef.current.stop();
    };
  }, []);

  const start = useCallback(() => {
    if (status === 'unavailable' || status === 'error' || status === 'listening') return;
    try {
      isIntentionalStopRef.current = false;
      restartCountRef.current = 0;
      recognitionRef.current.start();
      setStatus('listening');
    } catch (e) {}
  }, [status]);

  const stop = useCallback(() => {
    if (recognitionRef.current && status === 'listening') {
      isIntentionalStopRef.current = true;
      recognitionRef.current.stop();
      setStatus('idle');
    }
  }, [status]);

  const clearBuffer = useCallback(() => {
    bufferRef.current = '';
    setLastUpdated(Date.now());
  }, []);

  const getBuffer = useCallback(() => {
    return bufferRef.current;
  }, []);

  return { status, lastUpdated, start, stop, getBuffer, clearBuffer };
}
