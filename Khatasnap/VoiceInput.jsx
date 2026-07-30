import React, { useState, useRef, useEffect } from 'react';
import { confirmAndSaveTransaction } from '../../services/api';
import {
  resolveTranscript,
  saveNickname,
  getNicknames,
  deleteNickname,
  getNicknameCount
} from '../../services/nicknames';

const MAX_RETRIES = 3;

const speak = (text, onEnd) => {
  window.speechSynthesis.cancel();
  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'hi-IN';
  utter.rate = 0.88;
  utter.pitch = 1;
  if (onEnd) {
    utter.onend = () => setTimeout(onEnd, 1500);
  }
  window.speechSynthesis.speak(utter);
};

const buildConfirmationText = (items, paymentMode, totalAmount) => {
  if (!items || items.length === 0) return 'Koi item nahi mila. Dobara boliye.';
  const itemText = items.map(i => `${i.quantity} ${i.product_name}`).join(', ');
  const payment = paymentMode === 'upi' ? 'UPI' : 'cash';
  return `${itemText}. Total ${totalAmount} rupaye. ${payment} payment. Sahi hai?`;
};

const parseConfirmation = (text) => {
  const t = text.toLowerCase().trim();
  const YES = ['haan', 'han', 'ha', 'yes', 'sahi', 'theek', 'correct',
               'bilkul', 'okay', 'ok', 'done', 'save', 'right'];
  const NO  = ['nahi', 'nhi', 'no', 'galat', 'wrong', 'change',
               'nope', 'cancel', 'ghalat', 'nai'];
  if (YES.some(w => t.includes(w))) return 'yes';
  if (NO.some(w => t.includes(w)))  return 'no';
  return null;
};

const parseCorrection = (text, currentItems) => {
  const t = text.toLowerCase();
  const numWords = {
    'ek':1,'one':1,'do':2,'two':2,'teen':3,'three':3,'char':4,'four':4,
    'paanch':5,'five':5,'chhe':6,'six':6,'saat':7,'seven':7,
    'aath':8,'eight':8,'nau':9,'nine':9,'das':10,'ten':10
  };
  let newQty = null;
  const digitMatch = t.match(/\b(\d+)\b/);
  if (digitMatch) newQty = parseInt(digitMatch[1]);
  if (!newQty) {
    for (const [word, val] of Object.entries(numWords)) {
      if (t.includes(word)) { newQty = val; break; }
    }
  }
  if (!newQty || currentItems.length === 0) return null;
  if (currentItems.length === 1) {
    return currentItems.map(i => ({ ...i, quantity: newQty }));
  }
  for (const item of currentItems) {
    const nameWords = item.product_name.toLowerCase().split(' ');
    if (nameWords.some(w => t.includes(w))) {
      return currentItems.map(i =>
        i.product_name === item.product_name ? { ...i, quantity: newQty } : i
      );
    }
  }
  return null;
};

const extractProductWords = (transcript) => {
  const stopWords = new Set([
    'and','with','upi','cash','paytm','gpay','phonepe','payment',
    'ka','ke','ki','de','dena','lena','please','bhai','yaar',
    'ek','do','teen','char','paanch','chhe','saat','aath','nau','das',
    'one','two','three','four','five','six','seven','eight','nine','ten',
    'to','too'
  ]);
  return transcript.toLowerCase()
    .replace(/\d+/g, '')
    .split(/\s+/)
    .filter(w => w.length > 2 && !stopWords.has(w));
};

const calcTotal = (items) =>
  items.reduce((sum, i) => sum + (i.price || 0) * i.quantity, 0);

const isTranscriptValid = (text) => {
  const t = text.trim().toLowerCase();
  const words = t.split(/\s+/);
  if (words.length < 1 || t.length < 3) return false;
  const hasNumber = /\d/.test(t) || [
    'ek','do','teen','char','paanch','chhe','saat','aath','nau','das',
    'one','two','three','four','five','six','seven','eight','nine','ten'
  ].some(n => t.includes(n));
  if (hasNumber) return true;
  const fillers = ['hmm','uh','um','ah','oh','ha','hm','err','okay','test'];
  if (words.length === 1 && fillers.includes(words[0])) return false;
  if (words.length === 1 && words[0].length >= 4) return true;
  return words.length >= 2;
};

const VoiceInput = ({ onTransactionProcessed, onItemsExtracted }) => {
  const [stage, setStage]                   = useState('idle');
  const [transcript, setTranscript]         = useState('');
  const [billData, setBillData]             = useState(null);
  const [errorMsg, setErrorMsg]             = useState('');
  const [savedTxn, setSavedTxn]             = useState(null);
  const [correctionHint, setCorrectionHint] = useState('');
  const [retryCount, setRetryCount]         = useState(0);
  const [retryMsg, setRetryMsg]             = useState('');
  const [nicknameCount, setNicknameCount]   = useState(getNicknameCount());
  const [showNicknames, setShowNicknames]   = useState(false);
  const [nicknames, setNicknames]           = useState(getNicknames());

  const originalTranscriptRef = useRef('');
  const recognitionRef        = useRef(null);
  const noSpeechTimerRef      = useRef(null);
  const cancelledRef          = useRef(false);

  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      window.speechSynthesis.cancel();
      if (noSpeechTimerRef.current) {
        clearTimeout(noSpeechTimerRef.current);
        noSpeechTimerRef.current = null;
      }
      if (recognitionRef.current) {
        try { recognitionRef.current.abort(); } catch(e) {}
        recognitionRef.current = null;
      }
    };
  }, []);

  // ── Updated startListening with continuous mode ───────────────────────────
  const startListening = (onResult, onNoSpeech) => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
      setStage('error');
      setErrorMsg('Speech recognition not supported. Use Chrome browser.');
      return;
    }
    if (noSpeechTimerRef.current) {
      clearTimeout(noSpeechTimerRef.current);
      noSpeechTimerRef.current = null;
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
      recognitionRef.current = null;
    }
    setTimeout(() => {
      if (cancelledRef.current) return;

      const r = new SR();
      r.continuous     = true;  // keeps mic open while owner speaks
      r.interimResults = true;  // shows live transcript as owner speaks
      r.lang           = 'en-IN';
      recognitionRef.current = r;
      window.speechSynthesis.cancel();

      // 8s initial no-speech timeout
      noSpeechTimerRef.current = setTimeout(() => {
        if (cancelledRef.current) return;
        console.log('No speech timeout fired after 8s');
        try { r.stop(); } catch(e) {}
        noSpeechTimerRef.current = null;
        if (onNoSpeech) onNoSpeech();
      }, 8000);

      let finalTranscript = '';

      r.onresult = (e) => {
        if (cancelledRef.current) return;

        // Reset timer — owner is speaking, extend window
        if (noSpeechTimerRef.current) {
          clearTimeout(noSpeechTimerRef.current);
          // 2s silence after last word = done speaking
          noSpeechTimerRef.current = setTimeout(() => {
            if (cancelledRef.current) return;
            console.log('Silence detected — processing transcript');
            try { r.stop(); } catch(e) {}
            noSpeechTimerRef.current = null;
            if (finalTranscript.trim()) {
              console.log('Heard:', finalTranscript.trim());
              onResult(finalTranscript.trim());
            } else if (onNoSpeech) {
              onNoSpeech();
            }
          }, 2000);
        }

        let interim = '';
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const text = e.results[i][0].transcript;
          if (e.results[i].isFinal) {
            finalTranscript += text + ' ';
          } else {
            interim += text;
          }
        }

        // Show live transcript — owner sees what Chrome heard in real time
        const display = finalTranscript.trim()
          ? finalTranscript.trim() + (interim ? ' ' + interim : '')
          : interim;
        if (display) setTranscript(display);
      };

      r.onerror = (e) => {
        if (noSpeechTimerRef.current) {
          clearTimeout(noSpeechTimerRef.current);
          noSpeechTimerRef.current = null;
        }
        console.error('SR error:', e.error);
        if (e.error === 'aborted') return;
        if (e.error === 'no-speech') {
          if (!cancelledRef.current) onNoSpeech?.();
          return;
        }
        if (!cancelledRef.current) {
          setStage('error');
          setErrorMsg('Microphone error: ' + e.error);
        }
      };

      r.onend = () => {
        // Chrome stopped — process whatever we have
        if (cancelledRef.current) return;
        if (noSpeechTimerRef.current) {
          clearTimeout(noSpeechTimerRef.current);
          noSpeechTimerRef.current = null;
        }
        if (finalTranscript.trim()) {
          console.log('Heard:', finalTranscript.trim());
          onResult(finalTranscript.trim());
        } else if (onNoSpeech) {
          onNoSpeech();
        }
      };

      try {
        r.start();
        console.log('Mic opened successfully');
      } catch(e) {
        console.error('SR start failed:', e);
        if (noSpeechTimerRef.current) {
          clearTimeout(noSpeechTimerRef.current);
          noSpeechTimerRef.current = null;
        }
        if (!cancelledRef.current) {
          setStage('error');
          setErrorMsg('Mic start failed. Reset karein aur dobara try karein.');
        }
      }
    }, 300);
  };

  const recordBill = (currentRetry) => {
    setStage('listening');
    startListening(
      async (text) => {
        if (!isTranscriptValid(text)) {
          if (currentRetry < MAX_RETRIES) {
            const next = currentRetry + 1;
            setRetryCount(next);
            setRetryMsg(`Noise detected. Retry ${next}/${MAX_RETRIES}...`);
            speak('Sahi se suna nahi. Dobara boliye.', () => {
              if (!cancelledRef.current) recordBill(next);
            });
          } else {
            setRetryCount(0); setRetryMsg('');
            setStage('error');
            setErrorMsg('Kaafi noise hai. Thoda paas aake boliye.');
          }
          return;
        }

        originalTranscriptRef.current = text;
        const resolvedText = resolveTranscript(text);
        if (resolvedText !== text) {
          console.log(`Nickname resolved: "${text}" → "${resolvedText}"`);
        }

        setTranscript(resolvedText);
        setRetryMsg('');
        setStage('processing');
        const response = await processVoiceTransaction(resolvedText);

        if (!response.success) {
          setStage('error');
          setErrorMsg(response.error || 'Processing failed');
          return;
        }

        const analysis = response.ai_analysis || response.data;
        const total    = response.total_amount || calcTotal(analysis.items);

        if (!analysis.items || analysis.items.length === 0) {
          if (currentRetry < MAX_RETRIES) {
            const next = currentRetry + 1;
            setRetryCount(next);
            setRetryMsg(`Item samajh nahi aaya. Retry ${next}/${MAX_RETRIES}...`);
            setStage('listening');
            speak('Koi item nahi mila. Dobara clearly boliye.', () => {
              if (!cancelledRef.current) recordBill(next);
            });
          } else {
            setRetryCount(0); setRetryMsg('');
            setStage('error');
            setErrorMsg('Item detect nahi hua. Product ka naam clearly boliye.');
          }
          return;
        }

        if (analysis.total_confidence < 0.5 && currentRetry < MAX_RETRIES) {
          const next = currentRetry + 1;
          setRetryCount(next);
          setRetryMsg(`Low confidence (${(analysis.total_confidence*100).toFixed(0)}%). Retry ${next}/${MAX_RETRIES}...`);
          setStage('listening');
          speak('Achhe se samajh nahi aaya. Ek baar aur boliye.', () => {
            if (!cancelledRef.current) recordBill(next);
          });
          return;
        }

        setRetryCount(0); setRetryMsg('');
        const bill = {
          items:        analysis.items,
          payment_mode: analysis.payment_mode,
          total_amount: total,
          raw:          analysis
        };
        setBillData(bill);
        setStage('confirming');
        const confirmText = buildConfirmationText(
          bill.items, bill.payment_mode, total.toFixed(0)
        );
        speak(confirmText, () => {
          if (!cancelledRef.current) listenForConfirmation(bill);
        });
      },
      () => {
        if (cancelledRef.current) return;
        if (currentRetry < MAX_RETRIES) {
          const next = currentRetry + 1;
          setRetryCount(next);
          setRetryMsg(`Awaaz nahi aayi. Retry ${next}/${MAX_RETRIES}...`);
          speak('Suna nahi. Dobara boliye.', () => {
            if (!cancelledRef.current) recordBill(next);
          });
        } else {
          setRetryCount(0); setRetryMsg('');
          setStage('error');
          setErrorMsg('3 baar try kiya, awaaz nahi aayi. Mic check karein.');
        }
      }
    );
  };

  const handleStartRecording = () => {
    cancelledRef.current = false;
    setTranscript('');
    setBillData(null);
    setErrorMsg('');
    setSavedTxn(null);
    setRetryCount(0);
    setRetryMsg('');
    originalTranscriptRef.current = '';
    recordBill(0);
  };

  const listenForConfirmation = (bill) => {
    if (cancelledRef.current) return;
    console.log('Opening mic for confirmation...');
    startListening(
      async (text) => {
        if (cancelledRef.current) return;
        console.log('Confirmation heard:', text);
        const answer = parseConfirmation(text);
        if (answer === 'yes') {
          learnNicknames(originalTranscriptRef.current, bill.items);
          await saveTransaction(bill);
        } else if (answer === 'no') {
          setStage('correcting');
          setCorrectionHint('');
          speak('Kya badalna hai? Boliye.', () => {
            if (!cancelledRef.current) listenForCorrection(bill);
          });
        } else {
          speak('Samaj nahi aaya. Haan ya nahi boliye.', () => {
            if (!cancelledRef.current) listenForConfirmation(bill);
          });
        }
      },
      () => {
        if (cancelledRef.current) return;
        speak('Haan ya nahi boliye.', () => {
          if (!cancelledRef.current) listenForConfirmation(bill);
        });
      }
    );
  };

  const listenForCorrection = (bill) => {
    if (cancelledRef.current) return;
    console.log('Opening mic for correction...');
    startListening(
      async (text) => {
        if (cancelledRef.current) return;
        setCorrectionHint(text);
        const correctedItems = parseCorrection(text, bill.items);
        if (!correctedItems) {
          speak('Samaj nahi aaya. Phir se boliye.', () => {
            if (!cancelledRef.current) listenForCorrection(bill);
          });
          return;
        }
        const newTotal = calcTotal(correctedItems);
        const newBill  = { ...bill, items: correctedItems, total_amount: newTotal };
        setBillData(newBill);
        setStage('confirming');
        const confirmText = buildConfirmationText(
          newBill.items, newBill.payment_mode, newTotal.toFixed(0)
        );
        speak(confirmText, () => {
          if (!cancelledRef.current) listenForConfirmation(newBill);
        });
      },
      () => {
        if (cancelledRef.current) return;
        speak('Kuch suna nahi. Dobara boliye.', () => {
          if (!cancelledRef.current) listenForCorrection(bill);
        });
      }
    );
  };

  const learnNicknames = (originalText, items) => {
    if (!originalText || !items || items.length === 0) return;
    if (items.length !== 1) return;

    const spokenWords = extractProductWords(originalText);
    if (spokenWords.length === 0) return;

    const item = items[0];
    const productNameLower = item.product_name.toLowerCase();
    const productWords = productNameLower.split(/\s+/);
    const numberWords = [
      'ek','do','teen','char','paanch','chhe','saat','aath','nau','das',
      'one','two','three','four','five','six','seven','eight','nine','ten',
      'to','too','tu','tuu'
    ];

    spokenWords.forEach(word => {
      if (
        word !== productNameLower &&
        !productWords.some(pw => pw.includes(word) || word.includes(pw)) &&
        word.length > 3 &&
        !numberWords.includes(word)
      ) {
        saveNickname(word, item.product_name);
        setNicknameCount(getNicknameCount());
        setNicknames(getNicknames());
        console.log(`Learned: "${word}" → "${item.product_name}"`);
      }
    });
  };

  const saveTransaction = async (bill) => {
    setStage('processing');
    const cleanItems = bill.items.map(i => ({
      product_name: i.product_name,
      product_id:   i.product_id,
      price:        i.price,
      quantity:     i.quantity
    }));
    const result = await confirmAndSaveTransaction(
      { items: cleanItems, payment_mode: bill.payment_mode },
      bill.total_amount
    );
    if (!result.success) {
      setStage('error');
      setErrorMsg('Save nahi hua: ' + (result.error || 'Unknown error'));
      speak('Save nahi hua. Dobara try karein.');
      return;
    }
    setSavedTxn(result.data);
    setStage('saved');
    speak('Bill save ho gaya. Shukriya.');
    if (onItemsExtracted && bill.items) onItemsExtracted(bill.items, bill.payment_mode);
    if (onTransactionProcessed) onTransactionProcessed(result);
    setTimeout(() => setStage('idle'), 4000);
  };

  const handleManualConfirm = () => {
    if (!billData) return;
    cancelledRef.current = true;
    if (noSpeechTimerRef.current) {
      clearTimeout(noSpeechTimerRef.current);
      noSpeechTimerRef.current = null;
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
      recognitionRef.current = null;
    }
    learnNicknames(originalTranscriptRef.current, billData.items);
    saveTransaction(billData);
  };

  const handleManualCorrect = () => {
    if (billData) {
      cancelledRef.current = false;
      setStage('correcting');
      speak('Kya badalna hai? Boliye.', () => {
        if (!cancelledRef.current) listenForCorrection(billData);
      });
    }
  };

  const handleReset = () => {
    cancelledRef.current = true;
    window.speechSynthesis.cancel();
    if (noSpeechTimerRef.current) {
      clearTimeout(noSpeechTimerRef.current);
      noSpeechTimerRef.current = null;
    }
    if (recognitionRef.current) {
      try { recognitionRef.current.abort(); } catch(e) {}
      recognitionRef.current = null;
    }
    setStage('idle');
    setTranscript('');
    setBillData(null);
    setErrorMsg('');
    setSavedTxn(null);
    setCorrectionHint('');
    setRetryCount(0);
    setRetryMsg('');
    originalTranscriptRef.current = '';
  };

  const handleDeleteNickname = (key) => {
    deleteNickname(key);
    setNicknames(getNicknames());
    setNicknameCount(getNicknameCount());
  };

  const confColor = (c) => {
    if (c >= 0.8) return 'text-green-600 bg-green-50';
    if (c >= 0.6) return 'text-yellow-600 bg-yellow-50';
    return 'text-red-600 bg-red-50';
  };

  const isSRSupported = !!(window.SpeechRecognition || window.webkitSpeechRecognition);

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">🎤 Voice Input</h2>
        {nicknameCount > 0 && (
          <button
            onClick={() => setShowNicknames(!showNicknames)}
            className="text-xs bg-purple-100 text-purple-700 px-2 py-1 rounded-full hover:bg-purple-200 transition-colors"
          >
            🧠 {nicknameCount} shortcuts saved
          </button>
        )}
      </div>

      {showNicknames && (
        <div className="mb-4 border border-purple-200 rounded-lg overflow-hidden">
          <div className="bg-purple-50 px-3 py-2 text-xs font-semibold text-purple-800">
            Saved Shortcuts
          </div>
          <div className="px-3 py-2 space-y-1 max-h-32 overflow-y-auto">
            {Object.entries(nicknames).map(([nick, real]) => (
              <div key={nick} className="flex justify-between items-center text-xs">
                <span>
                  <span className="text-purple-600 font-medium">"{nick}"</span>
                  <span className="text-gray-400 mx-1">→</span>
                  <span className="text-gray-700">{real}</span>
                </span>
                <button
                  onClick={() => handleDeleteNickname(nick)}
                  className="text-red-400 hover:text-red-600 ml-2"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mb-3 flex items-center gap-2 text-sm flex-wrap">
        {['idle','listening','processing','confirming','correcting','saved','error'].map(s => (
          <span key={s} className={`px-2 py-0.5 rounded-full text-xs font-medium transition-all ${
            stage === s
              ? s === 'saved'      ? 'bg-green-500 text-white'
              : s === 'error'      ? 'bg-red-500 text-white'
              : s === 'confirming' ? 'bg-blue-500 text-white'
              : s === 'correcting' ? 'bg-yellow-500 text-white'
              : 'bg-gray-700 text-white'
              : 'bg-gray-100 text-gray-400'
          }`}>{s}</span>
        ))}
      </div>

      {retryMsg !== '' && (
        <div className="mb-3 bg-yellow-50 border border-yellow-300 rounded-lg px-3 py-2 text-xs text-yellow-700 flex items-center gap-2">
          <span className="animate-spin">🔄</span>
          {retryMsg}
          <span className="ml-auto text-yellow-500">
            {'●'.repeat(retryCount)}{'○'.repeat(MAX_RETRIES - retryCount)}
          </span>
        </div>
      )}

      {/* ── Transcript display with live interim text ── */}
      <div className="bg-gray-100 rounded-lg p-4 mb-4 min-h-16">
        {transcript ? (
          <div>
            <p className="text-lg font-medium">{transcript}</p>
            {stage === 'listening' && (
              <p className="text-xs text-green-600 mt-1 animate-pulse">
                🎙️ Bol rahe hain... ruk jaiye bolne ke baad
              </p>
            )}
          </div>
        ) : (
          <p className="text-gray-400 italic">
            {stage === 'listening'  ? '🎙️ Sun raha hoon... boliye'
           : stage === 'confirming' ? '🔊 Bill sun lijiye...'
           : stage === 'correcting' ? '🎙️ Correction sun raha hoon...'
           : 'Microphone button dabayein aur bolein...'}
          </p>
        )}
        {correctionHint && stage === 'correcting' && (
          <p className="text-xs text-yellow-600 mt-1">Heard: "{correctionHint}"</p>
        )}
      </div>

      {billData && (stage === 'confirming' || stage === 'correcting') && (
        <div className="mb-4 border border-blue-200 rounded-lg overflow-hidden">
          <div className="bg-blue-50 px-4 py-2 flex justify-between items-center">
            <span className="font-semibold text-blue-800 text-sm">Current Bill</span>
            <span className="text-xs text-blue-600 uppercase font-bold">{billData.payment_mode}</span>
          </div>
          <div className="px-4 py-3 space-y-1">
            {billData.items.map((item, i) => (
              <div key={i}>
                <div className="flex justify-between text-sm">
                  <span>{item.quantity}× {item.product_name}</span>
                  <span className="text-gray-600">₹{((item.price || 0) * item.quantity).toFixed(2)}</span>
                </div>
                {(() => {
                  const name = item.product_name.toLowerCase();
                  let maxQty = 30;
                  if (['anda','egg','eggs'].some(w => name.includes(w)))       maxQty = 144;
                  else if (['biscuit','parle','bourbon','marie'].some(w => name.includes(w))) maxQty = 50;
                  else if (['cola','pepsi','sprite','bisleri','water'].some(w => name.includes(w))) maxQty = 48;
                  else if (['maggi','noodles'].some(w => name.includes(w)))    maxQty = 20;
                  else if (['milk','doodh'].some(w => name.includes(w)))       maxQty = 30;
                  else if (['oil','tel','ghee'].some(w => name.includes(w)))   maxQty = 10;
                  return item.quantity > maxQty ? (
                    <div className="text-xs text-yellow-600 mt-0.5">
                      ⚠️ Itni zyada quantity — sahi hai?
                    </div>
                  ) : null;
                })()}
              </div>
            ))}
            <div className="border-t pt-2 flex justify-between font-bold text-sm mt-2">
              <span>Total</span>
              <span>₹{billData.total_amount.toFixed(2)}</span>
            </div>
          </div>
          {billData.raw?.total_confidence !== undefined && (
            <div className={`px-4 py-2 text-xs font-medium ${confColor(billData.raw.total_confidence)}`}>
              <div className="flex justify-between">
                <span>Confidence: {(billData.raw.total_confidence * 100).toFixed(0)}%</span>
                {!['upi','cash','paytm','gpay','phonepe'].some(kw =>
                  billData.raw.raw_transcript?.toLowerCase().includes(kw)
                ) && (
                  <span className="text-yellow-600">⚠️ Payment mode not mentioned</span>
                )}
              </div>
            </div>
          )}
          {stage === 'confirming' && (
            <div className="px-4 py-3 bg-gray-50 flex gap-2">
              <button onClick={handleManualConfirm}
                className="flex-1 bg-green-500 hover:bg-green-600 text-white text-sm font-medium py-2 rounded-lg transition-colors">
                ✅ Haan, Save Karo
              </button>
              <button onClick={handleManualCorrect}
                className="flex-1 bg-yellow-500 hover:bg-yellow-600 text-white text-sm font-medium py-2 rounded-lg transition-colors">
                ✏️ Badlo
              </button>
              <button onClick={handleReset}
                className="flex-1 bg-gray-400 hover:bg-gray-500 text-white text-sm font-medium py-2 rounded-lg transition-colors">
                ❌ Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {stage === 'saved' && (
        <div className="mb-4 bg-green-50 border border-green-200 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <span className="text-2xl">✅</span>
            <div>
              <div className="font-semibold text-green-800">Bill Save Ho Gaya!</div>
              <div className="text-sm text-green-600 mt-0.5">
                {billData?.items?.length} item(s) •{' '}
                {billData?.payment_mode?.toUpperCase()} •{' '}
                ₹{billData?.total_amount?.toFixed(2)}
              </div>
              {nicknameCount > 0 && (
                <div className="text-xs text-purple-600 mt-1">
                  🧠 {nicknameCount} shortcuts active
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {stage === 'error' && (
        <div className="mb-4 bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-600">
          ❌ {errorMsg}
        </div>
      )}

      <div>
        {stage === 'idle' || stage === 'saved' || stage === 'error' ? (
          <button onClick={handleStartRecording}
            className="w-full bg-green-500 hover:bg-green-600 text-white font-semibold py-3 rounded-lg transition-colors flex items-center justify-center gap-2">
            🎤 Bolna Shuru Karein
          </button>
        ) : stage === 'listening' ? (
          <button disabled className="w-full bg-red-500 text-white font-semibold py-3 rounded-lg animate-pulse">
            🔴 Sun raha hoon... bolne ke baad ruk jaiye
          </button>
        ) : stage === 'processing' ? (
          <button disabled className="w-full bg-gray-400 text-white font-semibold py-3 rounded-lg">
            ⏳ Process ho raha hai...
          </button>
        ) : stage === 'confirming' ? (
          <button disabled className="w-full bg-blue-400 text-white font-semibold py-3 rounded-lg animate-pulse">
            🔊 Bill sun lijiye... phir HAAN ya NAHI bolein
          </button>
        ) : stage === 'correcting' ? (
          <button disabled className="w-full bg-yellow-400 text-white font-semibold py-3 rounded-lg animate-pulse">
            🎙️ Correction sun raha hoon...
          </button>
        ) : null}
      </div>

      {stage !== 'idle' && stage !== 'saved' && (
        <button onClick={handleReset}
          className="mt-2 w-full text-gray-500 hover:text-gray-700 text-sm py-1">
          Reset
        </button>
      )}

      {stage === 'idle' && (
        <div className="mt-4 text-xs text-gray-500 space-y-1">
          <p className="font-semibold">Kaise use karein:</p>
          <p>1. Button dabayein aur bolein: "2 Parle G 1 Maggi UPI"</p>
          <p>2. Bolna band karein — system automatically process karega</p>
          <p>3. "Haan" bolein → save. "Nahi" bolein → correction</p>
          <p>4. Apna shortcut bolein — system seekh lega</p>
        </div>
      )}

      {!isSRSupported && (
        <div className="mt-3 p-3 bg-yellow-100 border border-yellow-400 rounded-lg text-sm">
          ⚠️ Chrome ya Edge browser use karein voice ke liye.
        </div>
      )}
    </div>
  );
};

export default VoiceInput;