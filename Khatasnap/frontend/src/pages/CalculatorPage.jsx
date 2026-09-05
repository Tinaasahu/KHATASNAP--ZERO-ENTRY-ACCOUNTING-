import React, { useState, useEffect, useRef, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { useSRE } from '../hooks/useSRE';
import { useVoice } from '../hooks/useVoice';
import { useToast } from '../hooks/useToast';
import { resolvePrice, selectItem, submitSession, getHistory, assignItem, predictItem } from '../api/calculator';
import MicButton from '../components/voice/MicButton';
import SREFlagList from '../components/sre/SREFlagList';
import { CheckCircle, Mic, Sun, Sparkles, Volume2, Zap } from 'lucide-react';
import Divider from '../components/ui/Divider';
import { usePassiveASR } from '../hooks/usePassiveASR';
import { useTransactionBuffer } from '../hooks/useTransactionBuffer';
import { extractItemMentions, matchMentionsToOperands } from '../utils/speechMatcher';
import { getSnapshot, addPriceAlias } from '../api/inventory';
import { findCombinations } from '../utils/compositeResolver';
import ConfidenceBar from '../components/ui/ConfidenceBar';

const RenderChip = ({ entry, onClick, isActive }) => {
  const isSpeech = entry.resolution_method === 'speech' || entry.resolution_method === 'speech_ambiguous';
  const isAutoPattern = entry.status === 'auto' && !isSpeech;

  const border = isActive ? '2px solid var(--primary)' 
                 : isSpeech ? '1.5px solid #6366f1'
                 : isAutoPattern ? '1.5px solid #22c55e'
                 : entry.status === 'ambiguous' ? '1px solid var(--warning)' 
                 : entry.status === 'not_found' ? '1px dashed var(--border)' 
                 : '1px solid var(--border)';

  const glow = isActive ? '0 0 10px rgba(99, 102, 241, 0.4)'
               : isSpeech ? '0 0 8px rgba(99, 102, 241, 0.25)'
               : isAutoPattern ? '0 0 8px rgba(34, 197, 94, 0.2)'
               : entry.status === 'ambiguous' ? '0 0 6px var(--warning)' : 'none';

  const name = entry.name || entry.item_name;
  const isMultiple = entry.qty && entry.qty > 1;
  const price = entry.price || entry.value;
  
  return (
     <div onClick={onClick} style={{
        position: 'relative',
        background: isSpeech ? 'rgba(99, 102, 241, 0.08)' : isAutoPattern ? 'rgba(34, 197, 94, 0.06)' : 'var(--surface)',
        border,
        borderRadius: 'var(--radius-md)',
        padding: '6px 10px',
        minWidth: '76px',
        maxWidth: '135px',
        cursor: 'pointer',
        boxShadow: glow,
        transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)'
     }}>
        {isMultiple && entry.status === 'resolved' && (
            <div style={{ position: 'absolute', top: '-6px', right: '-6px', background: 'var(--warning)', color: 'var(--surface)', fontSize: '10px', fontWeight: 'bold', padding: '2px 5px', borderRadius: '8px', zIndex: 2 }}>
                ×{entry.qty}
            </div>
        )}
        {entry.status === 'ambiguous' ? (
            <>
              <div style={{ fontSize: '11px', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '3px' }}>
                <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: 'var(--warning)' }} />
                Pending ?
              </div>
              <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>₹{entry.value}</div>
            </>
        ) : entry.status === 'not_found' ? (
            <>
              <div style={{ fontSize: '10px', color: 'var(--warning)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>🆕 New item</div>
              <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-hint)' }}>₹{entry.value}</div>
            </>
        ) : (
            <>
              <div style={{ fontSize: '11px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: '4px' }} title={entry.reason || name}>
                {isSpeech && <Mic size={11} color="var(--primary)" />}
                {isAutoPattern && <Sparkles size={11} color="#22c55e" />}
                <span>{entry.emoji || '📦'} {name}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
                <div style={{ fontSize: '16px', fontWeight: 600, color: 'var(--text-primary)' }}>₹{price}</div>
                {entry.confidence ? (
                  <div style={{ fontSize: '10px', fontWeight: 600, color: entry.confidence >= 0.85 ? '#22c55e' : '#f59e0b' }}>
                    {Math.round(entry.confidence * 100)}%
                  </div>
                ) : null}
              </div>
            </>
        )}
     </div>
  );
};

// ── Expression parser: split "5+36+55" into tokens with types ──
const parseExpressionTokens = (expr) => {
  if (!expr) return [];
  const tokens = [];
  let current = '';
  for (const ch of expr) {
    if (['+', '-', '×', '÷', '*', '/'].includes(ch)) {
      if (current) tokens.push({ type: 'number', value: current });
      tokens.push({ type: 'operator', value: ch });
      current = '';
    } else {
      current += ch;
    }
  }
  if (current) tokens.push({ type: 'number', value: current });
  return tokens;
};

export default function CalculatorPage() {
  const [expression, setExpression] = useState('');
  const [currentOperand, setCurrentOperand] = useState('');
  const [entries, setEntries] = useState([]);
  const [result, setResult] = useState(0);
  const [history, setHistory] = useState([]);
  const [showSuccess, setShowSuccess] = useState(false);
  const [activeEntryId, setActiveEntryId] = useState(null);
  const [pendingSession, setPendingSession] = useState(null);
  const [expandedRow, setExpandedRow] = useState(null);

  // New item detection state
  const [newItemEntryId, setNewItemEntryId] = useState(null);
  const [newItemName, setNewItemName] = useState('');
  const [pendingSubmitData, setPendingSubmitData] = useState(null);

  // Retroactive assignment state (for history rows)
  const [retroAssignRow, setRetroAssignRow] = useState(null);   // history index
  const [retroAssignPrice, setRetroAssignPrice] = useState(null); // price being assigned
  const [retroAssignIndex, setRetroAssignIndex] = useState(null); // token index for the operand
  const [retroProducts, setRetroProducts] = useState([]);
  const [retroSearch, setRetroSearch] = useState('');
  const [retroError, setRetroError] = useState(null);
  const [retroLoading, setRetroLoading] = useState(false);

  const { flags, setFlags, resolveFlag, areAllResolved } = useSRE();
  const voice = useVoice();
  const toast = useToast();

  const [historyOpen, setHistoryOpen] = useState(false);
  const [isDayMode, setIsDayMode] = useState(() => {
    return localStorage.getItem('khatasnap_day_mode') === 'true';
  });

  // ── Live pattern prediction for currently typed operand ───────────────
  const [livePrediction, setLivePrediction] = useState(null);
  const [explainablePrediction, setExplainablePrediction] = useState(null);
  const [confidenceResult, setConfidenceResult] = useState(null);
  const [showConfidenceCard, setShowConfidenceCard] = useState(false);

  // ── Buffer hook wires ASR + amounts → confidence engine ───────────────
  const txBuffer = useTransactionBuffer();

  // ── Passive ASR — push each segment into the buffer in real-time ──────
  const handleAsrSegment = useCallback((text) => {
    txBuffer.pushAsrSegment(text);
  }, [txBuffer]);

  const passive = usePassiveASR({ onSegment: handleAsrSegment });
  const [inventory, setInventory] = useState([]);

  // Auto-start Day Mode ASR on mount if enabled
  useEffect(() => {
    if (isDayMode && passive.status === 'idle') {
      passive.start();
    }
  }, [isDayMode, passive]);

  // Real-time pattern prediction as user types numbers
  useEffect(() => {
    if (!currentOperand || isNaN(parseInt(currentOperand, 10))) {
      setLivePrediction(null);
      setExplainablePrediction(null);
      return;
    }
    const timer = setTimeout(async () => {
      const val = parseInt(currentOperand, 10);
      const cartIds = entries.map(e => e.item_id).filter(Boolean);
      try {
        const pred = await predictItem(val, new Date().getHours(), new Date().getDay(), cartIds, passive.getBuffer());
        if (pred && pred.best_match) {
          setLivePrediction(pred.best_match);
        } else {
          setLivePrediction(null);
        }
      } catch {
        setLivePrediction(null);
      }

      try {
        const exp = await predictConfidence(val, passive.getBuffer(), new Date().getHours());
        if (exp && exp.prediction && exp.prediction.confidence > 0) {
          setExplainablePrediction(exp);
        } else {
          setExplainablePrediction(null);
        }
      } catch {
        setExplainablePrediction(null);
      }
    }, 150);
    return () => clearTimeout(timer);
  }, [currentOperand, entries, passive]);

  const toggleDayMode = () => {
    if (isDayMode) {
      setIsDayMode(false);
      localStorage.setItem('khatasnap_day_mode', 'false');
      passive.stop();
      toast.info("Day Mode Paused — Continuous voice listening is off.");
    } else {
      setIsDayMode(true);
      localStorage.setItem('khatasnap_day_mode', 'true');
      passive.start();
      txBuffer.beginSession();
      toast.success("☀️ Day Mode Active! AI is continuously listening for speech and calculations in the background.");
    }
  };

  // Passive history-based unassigned entries state
  const [dismissedUnassigned, setDismissedUnassigned] = useState(new Set());

  const unassignedFlags = React.useMemo(() => {
    const arr = [];
    history.forEach((h, hIdx) => {
      // parseExpressionTokens is globally available in the file
      const exprTokens = parseExpressionTokens(h.expression || '');
      const numTokens = exprTokens.filter(t => t.type === 'number');

      (h.unresolved_operands || []).forEach((idxVal) => {
        const price = numTokens[idxVal]?.value;
        if (!price) return;
        const id = `unr-${h.id}-${idxVal}`;
        if (!dismissedUnassigned.has(id)) {
           arr.push({
             flag_type: 'UNRESOLVED_ENTRY',
             flag_id: id,
             session_id: h.id,
             operand: parseInt(price, 10),
             message: `₹${price} entry was skipped. Assign it when you have time.`,
             original_idx: { hIdx, pIdx: idxVal }
           });
        }
      });
    });
    return arr;
  }, [history, dismissedUnassigned]);

  const wakeASR = () => {
    if (passive.status === 'idle') passive.start();
    // Begin the transaction buffer on first key press
    if (!txBuffer.sessionActive) txBuffer.beginSession();
  };

  const handleChar = (c) => { wakeASR(); setCurrentOperand(prev => prev + c); };
  const handleClear = () => {
    if (entries.length > 0 && !window.confirm('Clear this session? Inventory has not been updated yet.')) return;
    if (!isDayMode) {
      passive.stop();
    }
    passive.clearBuffer();
    txBuffer.discard();
    if (isDayMode) {
      txBuffer.beginSession();
    }
    setExpression(''); setCurrentOperand(''); setResult(0); setFlags([]);
    setPendingSession(null); setEntries([]); setActiveEntryId(null);
    setNewItemEntryId(null); setNewItemName(''); setPendingSubmitData(null);
    setConfidenceResult(null); setShowConfidenceCard(false); setPendingCommitData(null);
    setLivePrediction(null);
    window._isSubmitting = false;
  };
  const handleBackspace = () => { wakeASR(); setCurrentOperand(prev => prev.slice(0, -1)); };

  const entriesRef = useRef(entries);
  useEffect(() => { entriesRef.current = entries; }, [entries]);

  useEffect(() => {
     getHistory(10).then(setHistory).catch(console.error);
     getSnapshot().then(setInventory).catch(()=>{});
  }, []);

  // ── Coordination: Active MicButton suspends background Day Mode ASR ───
  const prevVoiceStateRef = useRef(voice.state);
  useEffect(() => {
    const prevState = prevVoiceStateRef.current;
    prevVoiceStateRef.current = voice.state;

    if (voice.state === 'listening' || voice.state === 'transcribing') {
      passive.stop();
    } else if (['listening', 'transcribing'].includes(prevState) && ['idle', 'done'].includes(voice.state)) {
      if (isDayMode && passive.status !== 'listening') {
        const timer = setTimeout(() => {
          passive.start();
        }, 350);
        return () => clearTimeout(timer);
      }
    }
  }, [voice.state, isDayMode]);

  useEffect(() => {
    if (voice.intent && voice.intent.items && voice.state === 'done') {
        const rawItems = Array.isArray(voice.intent.items) ? voice.intent.items : [];
        if (rawItems.length === 0) {
          toast.info("No matching products detected in voice command.");
          voice.reset();
          return;
        }
        const newEntries = rawItems.map(item => {
           const price = Number(item.price || item.amount || 0);
           const qty = Number(item.qty || 1);
           const pName = item.name || item.matched_name || 'Item';
           return {
               id: Date.now().toString() + '-' + Math.random().toString(36).substr(2, 9),
               value: price,
               price: price,
               item_id: item.id || item.product_id || null, 
               item_name: pName,
               name: pName,
               qty: qty,
               emoji: item.emoji || '📦',
               status: 'resolved',
               resolve_status: 'speech_direct',
               resolution_method: 'speech',
               confidence: item.confidence || 0.95,
               reason: `Voice: "${pName}" (x${qty})`
           };
        });

        if (newEntries.length > 0) {
           setEntries(prev => [...prev, ...newEntries]);
           const sum = newEntries.reduce((acc, curr) => acc + (curr.value * curr.qty), 0);
           setResult(prev => (Number(prev) || 0) + sum);
           
           const adds = newEntries.map(e => {
               if (e.qty > 1) return Array(e.qty).fill(e.value).join('+');
               return e.value;
           }).join('+');
           setExpression(prev => prev ? prev + '+' + adds + '+' : adds + '+');
           
           newEntries.forEach(e => {
             for (let q = 0; q < e.qty; q++) {
               txBuffer.pushAmount(e.value, e.id);
             }
           });
           
           toast.success(`Voice added: ${newEntries.map(e => `${e.name} (x${e.qty})`).join(', ')}`);
        }
        voice.reset();
    }
  }, [voice.intent, voice.state]);

  const finalizeOperand = async (valStr, opChar) => {
    if (!valStr) {
      if (opChar && expression) setExpression(prev => prev.slice(0, -1) + opChar);
      return;
    }
    const price = parseInt(valStr, 10);
    const entryId = Date.now().toString() + '-' + Math.random().toString(36).substr(2, 9);
    const newEntry = { id: entryId, value: price, status: 'resolving', qty: 1 };

    setEntries(prev => [...prev, newEntry]);
    setExpression(prev => prev + valStr + (opChar || ''));
    setCurrentOperand('');
    setLivePrediction(null);

    // Sync new amount into the transaction buffer
    txBuffer.pushAmount(price, entryId);

    const now = new Date();
    try {
       const cartItemIds = entries.map(e => e.item_id).filter(Boolean);
       const currentTranscript = passive.getBuffer() || passive.interimText || '';

       // 1. Direct Speech Matching: Prioritized pipeline check
       let speechItem = null;
       let speechConfidence = 0.95;
       let speechReason = '';

       if (currentTranscript && inventory.length > 0) {
          const mentions = extractItemMentions(currentTranscript, inventory);
          // Stage 2 Price Match: Prioritize exact or within price tolerance matches
          const directMatch = mentions.find(m => Math.abs((m.price || 0) - price) <= 2);
          if (directMatch) {
             speechItem = directMatch;
             speechConfidence = 0.95;
             speechReason = `Voice + Price: "${directMatch.item_name}" (₹${price})`;
          } else {
             // Composite check (e.g. 2 x 10 = 20)
             const compositeMatch = mentions.find(m => m.price > 0 && price % m.price === 0 && (price / m.price === (m.detected_qty || 1)));
             if (compositeMatch) {
                speechItem = { ...compositeMatch, calc_qty: price / compositeMatch.price };
                speechConfidence = 0.90;
                speechReason = `Voice: "${compositeMatch.item_name}" (${price / compositeMatch.price}x ₹${compositeMatch.price})`;
             } else if (mentions.length > 0) {
                // Pick candidate closest to entered price
                let bestCand = mentions[0];
                let minDiff = Math.abs((bestCand.price || 0) - price);
                for (const m of mentions) {
                   const diff = Math.abs((m.price || 0) - price);
                   if (diff < minDiff) {
                      minDiff = diff;
                      bestCand = m;
                   }
                }
                if (minDiff <= 5) {
                   speechItem = { ...bestCand, calc_qty: 1 };
                   speechConfidence = 0.85;
                   speechReason = `Voice: "${bestCand.item_name}" heard @ entered ₹${price}`;
                }
             }
          }
       }

       if (speechItem) {
          // Immediately allot item to entry with high confidence prioritized score
          const itemObj = speechItem.item_obj || speechItem;
          const assignedQty = speechItem.calc_qty || speechItem.detected_qty || 1;
          setEntries(prev => prev.map(e => {
             if (e.id !== entryId) return e;
             return {
                ...e,
                status: 'resolved',
                resolve_status: 'speech_direct',
                item_id: itemObj.id || speechItem.item_id,
                name: itemObj.name || speechItem.item_name,
                item_name: itemObj.name || speechItem.item_name,
                price: price,
                qty: assignedQty,
                emoji: itemObj.emoji || '📦',
                confidence: speechConfidence,
                resolution_method: 'speech',
                reason: speechReason || `Voice: "${speechItem.item_name}" heard`
             };
          }));
          toast.success(`Voice allotted: ${speechItem.item_name} (₹${price})`);
          return;
       }

       // 2. Pattern and Inventory Engine Resolution
       const res = await resolvePrice(price, now.getHours(), now.getDay(), cartItemIds, currentTranscript);
       const combinations = findCombinations(price, inventory);

       setEntries(prev => prev.map(e => {
          if (e.id !== entryId) return e;
          if (res.status === 'not_found') {
             return { ...e, status: 'not_found', resolve_status: res.status, alternatives: [], combinations: [] };
          }
          if (res.status === 'unique') {
             return {
                ...e,
                status: 'resolved',
                resolve_status: res.status,
                ...res.item,
                qty: 1,
                reason: res.reason || 'Unique price'
             };
          }
          if (res.status === 'auto' && res.item) {
             return {
                ...e,
                status: 'resolved',
                resolve_status: res.status,
                ...res.item,
                confidence: res.confidence,
                alternatives: res.alternatives,
                qty: 1,
                reason: res.reason || 'Pattern match'
             };
          }
          // If ambiguous, auto-allot best guess so user isn't stuck in "Pending ?"
          const topAlt = res.best_guess || (res.items && res.items[0]);
          if (topAlt) {
             return {
                ...e,
                status: 'resolved',
                resolve_status: 'auto_allotted',
                ...topAlt,
                confidence: topAlt.confidence || 0.7,
                alternatives: res.items || [],
                combinations: combinations,
                qty: 1,
                reason: topAlt.reason || 'Smart prediction'
             };
          }
          return { ...e, status: 'ambiguous', resolve_status: res.status, alternatives: res.items || [], combinations: combinations };
       }));
    } catch {
       setEntries(prev => prev.map(e => e.id === entryId ? { ...e, status: 'error' } : e));
    }
  };

  const handleOperator = (opChar) => { wakeASR(); finalizeOperand(currentOperand, opChar); };

  // Check for not_found entries and prompt user to name them
  const promptNextNewItem = (entriesList) => {
    const notFoundEntry = entriesList.find(e => e.status === 'not_found');
    if (notFoundEntry) {
      setNewItemEntryId(notFoundEntry.id);
      setNewItemName('');
      setTimeout(() => newItemInputRef.current?.focus(), 100);
      return true; // there are still items to name
    }
    setNewItemEntryId(null);
    setNewItemName('');
    return false; // all items named
  };

  // Handle naming a new item
  const handleNewItemSave = async (name, existingProduct = null) => {
    if (!name.trim() && !existingProduct) return;
    
    const itemName = existingProduct ? existingProduct.name : name.trim();
    const itemId = existingProduct ? existingProduct.id : null;
    const emoji = existingProduct ? existingProduct.emoji : '📦';
    
    const currentEntries = entriesRef.current;
    
    if (existingProduct) {
        const entry = currentEntries.find(e => e.id === newItemEntryId);
        if (entry) {
            try {
                await addPriceAlias({ item_id: itemId, item_name: itemName, alias_price: entry.value });
                const now = new Date();
                await selectItem(entry.value, itemId, itemName, now.getHours(), now.getDay());
                
                setInventory(prev => {
                   const newLocal = [...prev];
                   const upId = newLocal.findIndex(x => x.id === itemId);
                   if (upId >= 0 && !newLocal[upId].aliases) newLocal[upId].aliases = [];
                   if (upId >= 0) newLocal[upId].aliases.push(entry.value.toString());
                   return newLocal;
                });
                toast.success(`₹${entry.value} grouped with ${itemName}.`);
            } catch(e) {
                toast.error("Failed to add price alias");
                return;
            }
        }
    }

    const updated = currentEntries.map(e => {
      if (e.id !== newItemEntryId) return e;
      return { ...e, status: 'resolved', name: itemName, item_name: itemName, item_id: itemId, emoji, resolution_method: 'manual', alias_used: !!existingProduct, alias_price: !!existingProduct ? e.value : null };
    });
    
    setEntries(updated);
    
    const hasMore = promptNextNewItem(updated);
    if (!hasMore && pendingSubmitData) {
      setTimeout(() => proceedWithSubmission(updated, pendingSubmitData), 100);
    }
  };

  const handleNewItemSkip = () => {
    const currentEntries = entriesRef.current;
    const updated = currentEntries.map(e => {
      if (e.id !== newItemEntryId) return e;
      return { ...e, status: 'resolved', name: `Item ₹${e.value}`, item_name: `Item ₹${e.value}`, item_id: null, emoji: '📦', resolution_method: 'skipped' };
    });
    
    setEntries(updated);
    
    const hasMore = promptNextNewItem(updated);
    if (!hasMore && pendingSubmitData) {
      setTimeout(() => proceedWithSubmission(updated, pendingSubmitData), 100);
    }
  };

  // Fuzzy matching for new item name against inventory
  const getInventoryMatches = (typed) => {
    if (!typed || typed.trim().length === 0) return [];
    const lower = typed.toLowerCase();
    return inventory.filter(p => p.name.toLowerCase().includes(lower) || (p.aliases && p.aliases.some(a => a.toLowerCase().includes(lower))));
  };

  const proceedWithSubmission = (finalEntries, submitData) => {
    if (!submitData) return;
    
    if (window._isSubmitting) return; // Prevent duplicate submissions
    window._isSubmitting = true;
    
    // Step 5: Remove BOTH cards from below the calculator immediately
    setActiveEntryId(null); 
    setNewItemEntryId(null);
    setNewItemName('');
    
    const { spoken_context, evalString, fullExpression } = submitData;

    const combined = [];
    finalEntries.forEach(e => {
       const qty = e.qty || 1;
       if (qty === 0) return; 
       const existing = combined.find(x => x.item_id && x.item_id === (e.item_id || e.id) && x.price === e.value && x.alias_used === e.alias_used);
       if (existing) existing.qty += qty;
       else combined.push({ item_id: e.item_id || null, item_name: e.name || e.item_name || 'Unknown Item', price: e.value, qty: qty, alias_used: !!e.alias_used, alias_price: e.alias_price });
    });

    // eslint-disable-next-line
    const evalResult = evalString ? eval(evalString) : 0;
    setResult(evalResult);

    const sessionData = { combined, fullExpression, evalResult, spoken_context };
    setPendingSession(sessionData);
    setPendingSubmitData(null);

    submitSession(sessionData.combined, sessionData.fullExpression, sessionData.evalResult, sessionData.spoken_context)
      .then(payload => {
          window._isSubmitting = false;

          // Build UNRESOLVED_ENTRY flags for skipped operands
          const unresolvedFlags = [];
          const unresolvedIndices = [];
          
          finalEntries.forEach((e, idx) => {
              if (e.item_id || (e.resolution_method && e.resolution_method !== 'skipped')) return;
              const p = e.value;
              
              unresolvedIndices.push(idx);
              
              unresolvedFlags.push({
                flag_type: 'UNRESOLVED_ENTRY',
                flag_id: `unresolved-${idx}-${p}`,
                confidence: 1,
                severity: 'info',
                blocking: false,
                field: 'operand',
                operand: p,
                operand_index: idx,
                session_id: payload.session_id,
                message: `₹${p} was skipped — inventory not updated for this sale.`,
                is_new_item: e.resolve_status === 'not_found' || e.status === 'not_found',
                candidate_items: e.alternatives || [],
                combinations: e.combinations || [],
                typed_name: e.status === 'not_found' ? newItemName : null
              });
          });

          // Always inject these unresolved flags natively into Smart Checks
          setFlags(prev => {
              const activeSRE = (payload.sre_flags || []).filter(f => f.flag_type !== 'HIGH_TOTAL' && f.flag_type !== 'unknown_product');
              return [...activeSRE, ...unresolvedFlags];
          });

          // Always add completed session immediately to Today's Sessions history
          triggerSuccess({ ...sessionData, session_id: payload.session_id, unresolved_operands: unresolvedIndices });
      }).catch((err) => {
          console.error("Submission error:", err);
          window._isSubmitting = false;
          // Even on offline/catch, record locally to Today's Sessions
          triggerSuccess({ ...sessionData, session_id: `LOCAL-${Date.now()}`, unresolved_operands: [] });
      });
  };

  const handleEquals = async () => {
    if (currentOperand) await finalizeOperand(currentOperand, '');

    // Wait 150ms for finalizeOperand async state to settle
    setTimeout(async () => {
      const currentEntries = entriesRef.current;
      const transcript = passive.getBuffer();
      let finalEntries = [...currentEntries];
      let spoken_context = { raw_transcript: '', mentions: [], resolution_method: 'pattern' };

      // ── Step 1: Apply local ASR matching (fast, offline) ──────────────
      if (transcript && inventory.length > 0) {
        const mentions = extractItemMentions(transcript, inventory);
        const ops = currentEntries.map(e => e.value);
        const matchMap = matchMentionsToOperands(mentions, ops, inventory);
        const assignedViaSpeech = [];

        finalEntries = currentEntries.map((e, idx) => {
          const match = matchMap[idx];
          if (match && match.confidence >= 0.85 && match.source === 'speech') {
            assignedViaSpeech.push(match.item.name);
            return { ...e, status: 'resolved', ...match.item, confidence: match.confidence, resolution_method: 'speech', qty: match.item.qty || 1 };
          } else if (match && match.confidence >= 0.70) {
            assignedViaSpeech.push(match.item.name);
            return { ...e, status: 'resolved', ...match.item, confidence: match.confidence, resolution_method: 'speech_ambiguous', qty: match.item.qty || 1 };
          }
          return { ...e, resolution_method: e.resolution_method || 'none' };
        });

        spoken_context = {
          raw_transcript: transcript,
          mentions: mentions.map(m => ({ item_id: m.item_id, item_name: m.item_name, price: m.price, match_score: m.match_score, matched_alias: m.matched_alias })),
          resolution_method: finalEntries.some(e => ['speech', 'speech_ambiguous'].includes(e.resolution_method)) ? 'speech' : 'pattern',
        };
        if (assignedViaSpeech.length > 0) toast.success(`Voice captured: ${assignedViaSpeech.join(', ')}`);
      }

      if (!isDayMode) {
        passive.stop();
      }
      passive.clearBuffer();
      setEntries(finalEntries);

      // ── Step 2: Calculate total and prepare submission ─────────────────
      const amounts = finalEntries.map(e => e.value);
      let evalString = (expression + currentOperand).replace(/×/g, '*').replace(/÷/g, '/');
      evalString = evalString.replace(/[+\-*/]+$/, '');
      // eslint-disable-next-line no-eval
      const evalResult = evalString ? eval(evalString) : 0;
      setResult(evalResult);

      const submitData = {
        spoken_context, evalString,
        fullExpression: expression + currentOperand,
        evalResult, finalEntries,
      };

      const hasNotFound = finalEntries.some(e => e.status === 'not_found');
      if (hasNotFound) promptNextNewItem(finalEntries);

      // ── Step 3: Run Confidence Engine and Commit ──────────────────────
      try {
        const finalRes = (await txBuffer.finalize(amounts)) || {};
        const conf = finalRes.confidence || { score: 0.95, decision: 'high' };
        setConfidenceResult(conf);

        await _commitTransaction(finalEntries, submitData, conf.score ?? 0.95, spoken_context);
      } catch (_) {
        // Direct fallback commit
        proceedWithSubmission(finalEntries, submitData);
      }
    }, 150);
  };

  /** Commits transaction and adds to Today's Sessions */
  const _commitTransaction = async (finalEntries, submitData, confidenceScore, spokenContext) => {
    if (window._isSubmitting) return;
    window._isSubmitting = true;
    setActiveEntryId(null);
    setNewItemEntryId(null);
    setNewItemName('');

    const combined = [];
    finalEntries.forEach(e => {
      const qty = e.qty || 1;
      const existing = combined.find(x => x.item_id && x.item_id === (e.item_id || e.id) && x.price === e.value && x.alias_used === e.alias_used);
      if (existing) existing.qty += qty;
      else combined.push({ item_id: e.item_id || null, item_name: e.name || e.item_name || 'Unknown Item', price: e.value, qty, alias_used: !!e.alias_used });
    });

    try {
      const res = await txBuffer.commit({
        entries: combined,
        expression: submitData.fullExpression,
        result: submitData.evalResult,
        spokenContext: spokenContext || {},
        confidenceScore,
      });
      window._isSubmitting = false;
      triggerSuccess({
        session_id: res?.session_id || `TXN-${Date.now()}`,
        fullExpression: submitData.fullExpression,
        evalResult: submitData.evalResult,
        combined,
        unresolved_operands: [],
      });
    } catch (err) {
      window._isSubmitting = false;
      // Fallback to submission path
      proceedWithSubmission(finalEntries, submitData);
    }
  };

  const triggerSuccess = (sessionData) => {
      setShowSuccess(true);
      setHistory(prev => [{
         id: sessionData.session_id,
         expression: sessionData.fullExpression,
         result: sessionData.evalResult,
         entries: sessionData.combined,
         unresolved_operands: sessionData.unresolved_operands || [],
         timestamp: new Date().toISOString(),
      }, ...prev]);

      setTimeout(() => {
         setExpression(''); setCurrentOperand(''); setResult(0); setFlags([]); setPendingSession(null); setEntries([]); setActiveEntryId(null); setNewItemEntryId(null); setNewItemName(''); setPendingSubmitData(null);
         setConfidenceResult(null); setShowConfidenceCard(false); setPendingCommitData(null);
         setShowSuccess(false);
         if (isDayMode) {
           txBuffer.beginSession();
         }
      }, 500);
  };

  // Called from SREFlagCard / SREFlagList when a retroactive assign succeeds
  const handleSREAssign = (info) => {
      if (!info) return;
      // Refresh history
      getHistory(10).then(setHistory).catch(console.error);
      if (info.toastMessage) {
          toast.success(info.toastMessage);
      } else if (info.item_name) {
          toast.success(`₹${info.operand} assigned to ${info.item_name}. Inventory updated.`);
      } else {
          toast.success(`₹${info.operand} assigned. Inventory updated.`);
      }
  };

  // Retroactive assignment from a history row
  const openRetroAssign = (historyIdx, price, tokenIndex, ev) => {
      ev?.stopPropagation();
      setRetroAssignRow(historyIdx);
      setRetroAssignPrice(price);
      setRetroAssignIndex(tokenIndex);
      setRetroSearch('');
      setRetroError(null);
      getSnapshot().then(setRetroProducts).catch(() => {});
  };

  const handleRetroSelect = async (product) => {
      const h = history[retroAssignRow];
      if (!h || !h.id) return;
      setRetroLoading(true);
      setRetroError(null);
      try {
          const res = await assignItem(h.id, {
              operand_index: retroAssignIndex,
              operand: retroAssignPrice,
              item_id: product.id,
              item_name: product.name,
              qty: 1,
          });
          // Update local history
          setHistory(prev => prev.map((row, idx) => {
              if (idx !== retroAssignRow) return row;
              return {
                  ...row,
                  unresolved_operands: res.unresolved_operands || [],
                  entries: row.entries.map(e => {
                      if (e.price === retroAssignPrice && !e.item_id) {
                          return { ...e, item_id: product.id, item_name: product.name, qty: 1 };
                      }
                      return e;
                  }),
              };
          }));
          toast.success(`₹${retroAssignPrice} assigned to ${product.name}. Inventory updated.`);
          setRetroAssignRow(null);
          setRetroAssignPrice(null);
          setRetroAssignIndex(null);
      } catch (e) {
          if (e?.status === 409) {
              setRetroError(e.message || `${product.name} is out of stock.`);
          } else {
              setRetroError(e?.message || 'Failed to assign item. Try again.');
          }
      } finally {
          setRetroLoading(false);
      }
  };

  useEffect(() => {
    if (pendingSession && flags.length > 0 && areAllResolved()) {
       const hasCorrected = flags.some(f => f.resolution === 'corrected' && f.corrected_value);
       
       if (!hasCorrected) {
         // All flags accepted or ignored — just proceed with success, no re-submit
         triggerSuccess(pendingSession);
         return;
       }

       // Apply corrections and re-submit
       let updatedCombined = [...pendingSession.combined];
       flags.forEach(f => {
           if (f.resolution === 'corrected' && f.corrected_value) {
               const fieldMatch = f.field.match(/items\[(\d+)\]/);
               if (fieldMatch) {
                   const idx = parseInt(fieldMatch[1], 10);
                   if (updatedCombined[idx]) {
                       updatedCombined[idx].item_id = f.corrected_value.id || f.corrected_value.item_id;
                       updatedCombined[idx].item_name = f.corrected_value.name || f.corrected_value.item_name;
                       if (f.corrected_value.qty) {
                           updatedCombined[idx].qty = f.corrected_value.qty;
                       }
                   }
               }
           }
       });

       submitSession(updatedCombined, pendingSession.fullExpression, pendingSession.evalResult, pendingSession.spoken_context)
         .then(p => {
            if (p.status === 'confirmed') triggerSuccess({ ...pendingSession, combined: updatedCombined });
            else if (p.status === 'flags_detected') {
              const filtered = (p.sre_flags || []).filter(f => f.flag_type !== 'HIGH_TOTAL' && f.flag_type !== 'unknown_product');
              if (filtered.length > 0) setFlags(filtered);
              else triggerSuccess({ ...pendingSession, combined: updatedCombined });
            }
         });
    }
    // eslint-disable-next-line
  }, [flags]);

  const handleSelectItem = async (entryId, alt, isComplexCombo = false) => {
      const entry = entries.find(e => e.id === entryId);
      
      let resUpdate = { 
         ...alt, 
         qty: isComplexCombo ? alt.qty : 1 ,
         name: isComplexCombo ? alt.item_name : alt.name
      };

      setEntries(prev => prev.map(e => e.id === entryId ? { ...e, status: 'resolved', ...resUpdate } : e));
      
      const nextPending = entries.find(e => e.id !== entryId && e.status === 'ambiguous');
      setActiveEntryId(nextPending ? nextPending.id : null);

      if (entry) {
          try {
             const now = new Date();
             await selectItem(entry.value, isComplexCombo ? alt.item_id : alt.id, isComplexCombo ? alt.item_name : alt.name, now.getHours(), now.getDay());
          } catch(e) {
             console.warn("Pattern log failed", e);
          }
      }
  };

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;

      let key = e.key;
      if (e.code && e.code.startsWith('Numpad')) {
          if (e.code === 'NumpadEnter') key = 'Enter';
          else if (e.code === 'NumpadAdd') key = '+';
          else if (e.code === 'NumpadSubtract') key = '-';
          else if (e.code === 'NumpadMultiply') key = '*';
          else if (e.code === 'NumpadDivide') key = '/';
          else if (e.code === 'NumpadDecimal') key = '.';
          else if (e.code.length === 7) {
              const num = e.code[6];
              if (/[0-9]/.test(num)) key = num;
          }
      }

      if (/^[0-9\.]$/.test(key)) {
         e.preventDefault();
         handleChar(key);
      }
      else if (['+', '-', '*', '/'].includes(key)) {
         e.preventDefault();
         if (key === '*') handleOperator('×');
         else if (key === '/') handleOperator('÷');
         else handleOperator(key);
      } else if (key === 'Enter' || key === '=') {
        e.preventDefault();
        handleEquals();
      } else if (key === 'Backspace') {
        e.preventDefault();
        handleBackspace();
      } else if (key === 'Escape' || key.toLowerCase() === 'c') {
        e.preventDefault();
        handleClear();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

  const numpadButtons = [
    ['7','8','9','÷'],
    ['4','5','6','×'],
    ['1','2','3','-'],
    ['C','0','.','+'
    ]
  ];

  const inventoryMatches = getInventoryMatches(newItemName);
  const activeNewItemEntry = entries.find(e => e.id === newItemEntryId);
  const showInlineResolutionPanels = !pendingSession;

  const shouldAutoPick = (entry) => {
    if (!entry || entry.status !== 'ambiguous') return false;
    const alts = entry.alternatives || [];
    if (alts.length === 1) return true;
    if (alts.length >= 2) {
      const a0 = alts[0];
      const a1 = alts[1];
      const s0 = Number(a0?.confidence ?? a0?.score ?? 0);
      const s1 = Number(a1?.confidence ?? a1?.score ?? 0);
      // Auto-pick only when clearly dominant.
      if (s0 >= 0.92 && (s0 - s1) >= 0.12) return true;
    }
    return false;
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(400px, 560px) 1fr', gap: '32px' }}>
      <div>
        <Card shadow style={{ padding: 0, overflow: 'hidden' }}>
          {/* Header Bar with Start Day / Live ASR Button */}
          <div style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--border)',
            background: 'var(--surface-elevated, #1c1f2e)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <Sparkles size={16} color="var(--primary)" /> Smart Khata Calculator
              </span>
              {isDayMode && (
                <span style={{
                  fontSize: '10px', fontWeight: '700', padding: '2px 8px', borderRadius: '12px',
                  background: 'rgba(34, 197, 94, 0.15)', color: '#22c55e', border: '1px solid rgba(34, 197, 94, 0.3)',
                  display: 'flex', alignItems: 'center', gap: '5px'
                }}>
                  <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#22c55e' }} />
                  DAY LISTENING ON
                </span>
              )}
            </div>

            {/* TOP RIGHT CORNER: Day Mode Toggle Button */}
            <button
              id="btn-start-day-mode"
              onClick={toggleDayMode}
              title={isDayMode ? "Click to pause continuous day listening" : "Click to start continuous ASR for the day"}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px',
                padding: '6px 14px', borderRadius: '20px',
                fontSize: '12px', fontWeight: '600', cursor: 'pointer',
                border: isDayMode ? '1px solid rgba(34, 197, 94, 0.5)' : '1px solid var(--border)',
                background: isDayMode ? 'linear-gradient(135deg, rgba(34, 197, 94, 0.2), rgba(16, 185, 129, 0.1))' : 'var(--surface, #232736)',
                color: isDayMode ? '#22c55e' : 'var(--text-primary)',
                boxShadow: isDayMode ? '0 0 14px rgba(34, 197, 94, 0.25)' : 'none',
                transition: 'all 0.25s ease'
              }}
            >
              {isDayMode ? (
                <>
                  <Sun size={14} color="#22c55e" />
                  <span>Day Mode: Active</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '2px', marginLeft: '3px' }}>
                    <motion.div animate={{ height: ['4px', '12px', '4px'] }} transition={{ repeat: Infinity, duration: 0.8 }} style={{ width: '2px', background: '#22c55e', borderRadius: '1px' }} />
                    <motion.div animate={{ height: ['8px', '4px', '14px', '8px'] }} transition={{ repeat: Infinity, duration: 0.7 }} style={{ width: '2px', background: '#22c55e', borderRadius: '1px' }} />
                    <motion.div animate={{ height: ['4px', '10px', '4px'] }} transition={{ repeat: Infinity, duration: 0.9 }} style={{ width: '2px', background: '#22c55e', borderRadius: '1px' }} />
                  </div>
                </>
              ) : (
                <>
                  <Mic size={14} color="var(--primary)" />
                  <span>Start Day</span>
                </>
              )}
            </button>
          </div>

          <div style={{ backgroundColor: 'var(--surface-2)', padding: '16px 20px', minHeight: '130px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
            {showSuccess && (
              <div style={{ position: 'absolute', top: 12, left: 12, zIndex: 10 }}>
                <CheckCircle size={24} color="var(--success)" />
              </div>
            )}

            {/* ── Status badges + confidence badge ── */}
            <div style={{ position: 'absolute', top: 10, right: 12, display: 'flex', alignItems: 'center', gap: '8px' }}>
              {passive.status === 'listening' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                  <motion.div
                    animate={{ opacity: [1, 0.3, 1], scale: [1, 1.3, 1] }}
                    transition={{ repeat: Infinity, duration: 1.6 }}
                    style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: 'var(--success)' }}
                  />
                  <span style={{ fontSize: '10px', color: 'var(--text-hint)' }}>Listening</span>
                </div>
              )}
              {passive.status === 'error' && (
                <div style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: 'var(--danger)' }} title="Mic denied" />
              )}
              {/* Compact confidence badge once finalized */}
              {confidenceResult && !showSuccess && (
                <ConfidenceBar confidence={confidenceResult} compact />
              )}
            </div>

            {/* Live Floating Voice Transcript Preview */}
            <AnimatePresence>
              {(passive.interimText || (passive.status === 'listening' && passive.getBuffer())) && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: '6px',
                    padding: '3px 10px', borderRadius: '10px',
                    background: 'rgba(99, 102, 241, 0.12)', border: '1px solid rgba(99, 102, 241, 0.25)',
                    color: 'var(--primary)', fontSize: '11px', fontWeight: '500', marginBottom: '8px', width: 'fit-content'
                  }}
                >
                  <Volume2 size={11} />
                  <span>AI Voice: <em>"{passive.interimText || passive.getBuffer().slice(-40)}"</em></span>
                </motion.div>
              )}
            </AnimatePresence>
            
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: 'auto' }}>
               <AnimatePresence>
                  {entries.map(e => (
                     <motion.div key={e.id} layout initial={{scale:0.8, opacity:0}} animate={{scale:1, opacity:1}}>
                        <RenderChip entry={e} isActive={activeEntryId === e.id || newItemEntryId === e.id} onClick={() => {
                          if (e.status === 'not_found') {
                            setNewItemEntryId(e.id);
                            setNewItemName('');
                          } else {
                            setActiveEntryId(activeEntryId === e.id ? null : e.id);
                          }
                        }} />
                     </motion.div>
                  ))}
               </AnimatePresence>
            </div>

            {/* Live Multimodal AI Pattern Prediction Preview */}
            {currentOperand && livePrediction && !explainablePrediction && (
              <motion.div
                initial={{ opacity: 0, y: 4 }}
                animate={{ opacity: 1, y: 0 }}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '6px 12px', borderRadius: '8px',
                  background: 'linear-gradient(90deg, rgba(245, 158, 11, 0.1), rgba(34, 197, 94, 0.08))',
                  border: '1px solid rgba(245, 158, 11, 0.3)',
                  marginTop: '12px', fontSize: '12px'
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <Sparkles size={13} color="#f59e0b" />
                  <span>Predicted for ₹{currentOperand}: <strong>{livePrediction.emoji} {livePrediction.name}</strong></span>
                  <span style={{ fontSize: '10px', color: 'var(--text-hint)' }}>({livePrediction.reason})</span>
                </div>
                <span style={{ fontSize: '11px', fontWeight: '700', color: livePrediction.confidence >= 0.8 ? '#22c55e' : '#f59e0b' }}>
                  {Math.round(livePrediction.confidence * 100)}% Match
                </span>
              </motion.div>
            )}

            {/* Premium Explainable Confidence Score Card */}
            {currentOperand && explainablePrediction && (
              <ConfidenceScoreCard
                predictionResult={explainablePrediction}
                enteredPrice={currentOperand}
                onConfirmPrediction={async (pred) => {
                  if (pred && pred.id) {
                    const val = parseInt(currentOperand, 10);
                    try {
                      await selectItem(val, pred.id, pred.name, new Date().getHours(), new Date().getDay());
                      await recordFeedback(pred.id, pred.name, val, new Date().getHours(), new Date().getDay());
                      toast.success(`Confirmed ${pred.name} for ₹${val}`);
                    } catch {
                      toast.info(`Selected ${pred.name}`);
                    }
                  }
                }}
                onSelectAlternative={async (alt) => {
                  if (alt && alt.id) {
                    const val = parseInt(currentOperand, 10);
                    try {
                      await selectItem(val, alt.id, alt.name, new Date().getHours(), new Date().getDay());
                      await recordFeedback(alt.id, alt.name, val, new Date().getHours(), new Date().getDay());
                      toast.info(`Selected ${alt.name} for ₹${val}`);
                    } catch {
                      toast.info(`Selected ${alt.name}`);
                    }
                  }
                }}
              />
            )}

            <div style={{ fontFamily: 'var(--mono)', fontSize: '13px', color: 'var(--text-hint)', marginTop: '16px', textAlign: 'right' }}>
              {expression}{currentOperand}
            </div>
            <div style={{ fontFamily: 'var(--mono)', fontSize: '32px', color: 'var(--text-primary)', fontWeight: '600', textAlign: 'right' }}>
              {result ? `₹${result}` : ''}
            </div>
          </div>

          <div style={{ padding: '24px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
              {numpadButtons.flat().map(btn => (
                <Button
                  key={btn}
                  variant={['÷','×','-','+'].includes(btn) ? 'secondary' : btn === 'C' ? 'danger' : 'surface'}
                  size="lg"
                  style={{ fontSize: '20px', fontFamily: 'var(--mono)', height: '64px' }}
                  onClick={() => {
                    if (btn === 'C') handleClear();
                    else if (['÷','×','-','+'].includes(btn)) handleOperator(btn);
                    else handleChar(btn);
                  }}
                >
                  {btn}
                </Button>
              ))}
              <Button variant="surface" size="lg" style={{ height: '52px' }} onClick={handleBackspace}>⌫</Button>
              <Button
                variant="primary"
                size="lg"
                style={{ gridColumn: 'span 3', fontSize: '24px', height: '52px', position: 'relative' }}
                onClick={handleEquals}
              >
                =
                {txBuffer.isCommitting && (
                  <span style={{ position: 'absolute', right: '10px', top: '50%', transform: 'translateY(-50%)', fontSize: '12px', opacity: 0.7 }}>
                    saving…
                  </span>
                )}
              </Button>
            </div>

            {/* Item Selector / Alternative Changer Panel (shows all items for entered amount) */}
            <AnimatePresence>
              {showInlineResolutionPanels && activeEntryId && !newItemEntryId && (
                <motion.div initial={{y: 20, opacity: 0, height: 0}} animate={{y: 0, opacity: 1, height: 'auto'}} exit={{y: 20, opacity: 0, height: 0}} style={{ background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius-lg)', marginTop: '24px', border: '1px solid var(--border)' }}>
                   {(() => {
                     const currentEntry = entries.find(e => e.id === activeEntryId);
                     if (!currentEntry) return null;
                     const price = currentEntry.value;
                     const directMatching = inventory.filter(p => Number(p.selling_price || p.price) === price);
                     const combos = findCombinations(price, inventory);

                     return (
                       <>
                         <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                           <div style={{ fontSize: '14px', fontWeight: 'bold' }}>
                             Change item for <span style={{ color: 'var(--primary)' }}>₹{price}</span>:
                           </div>
                           <button 
                             onClick={() => { setNewItemEntryId(activeEntryId); setNewItemName(''); }}
                             style={{ background: 'transparent', border: 'none', color: 'var(--primary)', fontSize: '12px', fontWeight: 600, cursor: 'pointer' }}
                           >
                             + Name New Item
                           </button>
                         </div>

                         {directMatching.length > 0 ? (
                           <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                             {directMatching.map(item => (
                               <Button 
                                 key={item.id} 
                                 variant={currentEntry.item_id === item.id ? 'primary' : 'surface'} 
                                 size="sm" 
                                 style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px' }} 
                                 onClick={() => handleSelectItem(activeEntryId, item)}
                               >
                                  <span style={{ fontWeight: 600 }}>{item.emoji || '📦'} {item.name}</span>
                                  <span style={{ fontSize: '11px', color: item.current_qty === 0 ? 'var(--danger)' : 'var(--text-hint)' }}>{item.current_qty} left</span>
                               </Button>
                             ))}
                           </div>
                         ) : (
                           <div style={{ fontSize: '12px', color: 'var(--text-hint)', marginBottom: '12px' }}>
                             No single item found for ₹{price}. Choose a combo below or add a new name.
                           </div>
                         )}

                         {combos.filter(c => c.type === 'multiple').length > 0 && (
                           <>
                              <div style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '8px 0' }}>Or multiple item packs:</div>
                              <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px' }}>
                                {combos.filter(c => c.type === 'multiple').slice(0, 4).map((comb, idx) => (
                                   <Button 
                                     key={`comb-${idx}`} 
                                     variant="surface" 
                                     size="sm" 
                                     style={{ display: 'flex', justifyContent: 'space-between', padding: '8px 12px' }} 
                                     onClick={() => handleSelectItem(activeEntryId, comb, true)}
                                   >
                                      <span>{comb.item_emoji} {comb.qty}× {comb.item_name} (₹{comb.price_per_unit} each)</span>
                                      <span style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Total ₹{price}</span>
                                   </Button>
                                ))}
                              </div>
                           </>
                         )}

                         <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
                            <Button variant="ghost" size="sm" onClick={() => setActiveEntryId(null)}>Done</Button>
                         </div>
                       </>
                     );
                   })()}
                </motion.div>
              )}
            </AnimatePresence>

            {/* New Item Detection Panel */}
            <AnimatePresence>
              {showInlineResolutionPanels && newItemEntryId && activeNewItemEntry && (
                <motion.div 
                  initial={{y: 20, opacity: 0, height: 0}} 
                  animate={{y: 0, opacity: 1, height: 'auto'}} 
                  exit={{y: 20, opacity: 0, height: 0}} 
                  style={{ background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius-lg)', marginTop: '24px', border: '1px solid var(--warning)' }}
                >
                   <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '4px', color: 'var(--warning)' }}>
                     🆕 New item detected — what is this?
                   </div>
                   <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
                     ₹{activeNewItemEntry.value} is not in your inventory. Type a name for it:
                   </div>
                   
                   <input 
                     ref={newItemInputRef}
                     type="text" 
                     autoFocus
                     placeholder="Type item name..."
                     value={newItemName} 
                     onChange={(e) => setNewItemName(e.target.value)}
                     onKeyDown={(e) => {
                       if (e.key === 'Enter' && newItemName.trim()) {
                         handleNewItemSave(newItemName);
                       }
                     }}
                     style={{ width: '100%', height: '40px', padding: '0 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)', fontSize: '14px', marginBottom: '8px', boxSizing: 'border-box' }}
                   />
                   
                   {/* Show inventory matches as user types */}
                   {inventoryMatches.length > 0 && (
                     <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '12px', marginBottom: '8px' }}>
                       <div style={{ fontSize: '12px', color: 'var(--warning)', fontWeight: 600, marginBottom: '8px' }}>
                         ⚠️ This exists in inventory! You can group it with an existing item (multiple prices for same item) or save as a new item.
                       </div>
                       <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                         {inventoryMatches.slice(0, 5).map(p => (
                           <Button 
                             key={p.id} 
                             size="sm" 
                             variant="secondary" 
                             onClick={() => handleNewItemSave(p.name, p)}
                             style={{ fontSize: '12px' }}
                           >
                             {p.emoji} Group as "{p.name}" (₹{p.selling_price})
                           </Button>
                         ))}
                       </div>
                     </div>
                   )}
                   
                   <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                     <Button size="sm" variant="ghost" onClick={handleNewItemSkip}>Skip</Button>
                     <Button 
                       size="sm" 
                       variant="primary" 
                       disabled={!newItemName.trim()} 
                       onClick={() => handleNewItemSave(newItemName)}
                     >
                       Save as "{newItemName || '...'}"
                     </Button>
                   </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* ── Confidence Review Card (medium confidence) ── */}
            <AnimatePresence>
              {showConfidenceCard && confidenceResult && !showSuccess && (
                <motion.div
                  initial={{ y: 16, opacity: 0, height: 0 }}
                  animate={{ y: 0, opacity: 1, height: 'auto' }}
                  exit={{ y: 16, opacity: 0, height: 0 }}
                  style={{ marginTop: '20px' }}
                >
                  <ConfidenceBar confidence={confidenceResult} />
                  <div style={{ display: 'flex', gap: '8px', marginTop: '10px', justifyContent: 'flex-end' }}>
                    <Button
                      size="sm" variant="ghost"
                      onClick={() => {
                        setShowConfidenceCard(false);
                        setConfidenceResult(null);
                        setPendingCommitData(null);
                        txBuffer.flagForReconciliation('manual_dismiss', {});
                        toast.warn('Saved for tonight\'s review');
                      }}
                    >
                      Queue for Review
                    </Button>
                    <Button
                      size="sm" variant="primary"
                      onClick={async () => {
                        setShowConfidenceCard(false);
                        if (pendingCommitData) {
                          const { finalEntries, submitData, spoken_context, confidence } = pendingCommitData;
                          await _commitTransaction(finalEntries, submitData, confidence?.score ?? 0, spoken_context);
                          setPendingCommitData(null);
                        }
                      }}
                    >
                      ✓ Confirm &amp; Save
                    </Button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div style={{ display: 'flex', justifyContent: 'center', marginTop: '24px' }}>
               <MicButton
                 state={voice.state}
                 onToggle={() => {
                   if (voice.state === 'listening') {
                     voice.stop();
                   } else {
                     passive.stop();
                     setTimeout(() => {
                       voice.start();
                     }, 150);
                   }
                 }}
                 transcript={voice.transcript}
                 intent={voice.intent}
                 timeLeft={voice.timeLeft}
                 maxSeconds={voice.listeningSeconds}
               />
            </div>
          </div>
        </Card>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        <div style={{ marginBottom: '24px' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px' }}>
            Smart Checks
          </div>
          <SREFlagList 
            flags={flags} 
            unassignedFlags={unassignedFlags}
            onResolve={resolveFlag} 
            onAssign={handleSREAssign} 
            onDismissUnassigned={(id) => setDismissedUnassigned(prev => new Set([...prev, id]))}
          />
        </div>

        <Divider style={{ marginBottom: '24px' }} />

        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px' }}>
            Today's Sessions
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {history.map((h, i) => {
              const unresolved = h.unresolved_operands || []; // is now an array of indices
              const tokens = parseExpressionTokens(h.expression?.length > 40 ? h.expression.slice(0,40)+'...' : h.expression);
              
              const resolvedChips = h.entries?.filter(e => e.item_id) || [];
              
              // Map unresolved indices to their actual token objects so we can display them
              const numTokens = tokens.filter(t => t.type === 'number');
              const unresolvedChips = unresolved.map(idxVal => {
                  const pStr = numTokens[idxVal]?.value || '0';
                  return { price: parseFloat(pStr), index: idxVal };
              });

              let numberTokenIndex = 0; // To track exact Nth number

              return (
              <Card key={h.id || i} style={{ padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: '8px', cursor: 'pointer' }} onClick={() => setExpandedRow(expandedRow === i ? null : i)}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                   <div style={{ display: 'flex', flexDirection: 'column' }}>
                      <span style={{ fontSize: '12px', color: 'var(--text-hint)' }}>{new Date(h.created_at || h.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</span>
                      {/* Colored expression: red for unresolved operands based on matching token indices */}
                      <span style={{ fontFamily: 'var(--mono)', fontSize: '14px' }}>
                        {tokens.map((tok, ti) => {
                          if (tok.type === 'operator') {
                            return <span key={ti} style={{ color: 'var(--text-hint)' }}>{tok.value}</span>;
                          }
                          const currentNumIdx = numberTokenIndex++;
                          const isUnresolved = unresolved.includes(currentNumIdx);
                          const numVal = parseFloat(tok.value);
                          
                          return (
                            <span
                              key={ti}
                              title={isUnresolved ? 'Not tracked — click to assign item' : ''}
                              style={{
                                color: isUnresolved ? 'var(--danger)' : 'var(--text-primary)',
                                fontWeight: isUnresolved ? 500 : 'normal',
                                cursor: isUnresolved ? 'pointer' : 'default',
                              }}
                              onClick={isUnresolved ? (ev) => openRetroAssign(i, numVal, currentNumIdx, ev) : undefined}
                            >
                              {tok.value}
                            </span>
                          );
                        })}
                      </span>
                   </div>
                   <span style={{ fontWeight: 'bold', fontSize: '18px' }}>₹{h.result}</span>
                </div>
                
                {/* Visual Preview Row */}
                {expandedRow !== i ? (
                  <div style={{ display: 'flex', gap: '4px', overflow: 'hidden', flexWrap: 'wrap' }}>
                    {resolvedChips.slice(0, 4).map((e, idx) => (
                       <span key={idx} style={{ fontSize: '10px', background: 'var(--surface-2)', padding: '2px 6px', borderRadius: '4px', whiteSpace: 'nowrap' }}>{e.item_name} ×{e.qty}</span>
                    ))}
                    {resolvedChips.length > 4 && <span style={{ fontSize: '10px', padding: '2px' }}>+{resolvedChips.length - 4}</span>}
                    {unresolvedChips.map((e, idx) => (
                       <span
                         key={`u-${idx}`}
                         onClick={(ev) => openRetroAssign(i, e.price, e.index, ev)}
                         style={{
                           fontSize: '10px', padding: '2px 6px', borderRadius: '4px', whiteSpace: 'nowrap',
                           background: 'var(--danger-light, rgba(239, 68, 68, 0.1))',
                           border: '1px dashed var(--danger)',
                           color: 'var(--danger)', cursor: 'pointer',
                           fontWeight: 500,
                         }}
                       >
                         ₹{e.price} ?
                       </span>
                    ))}
                  </div>
                ) : (
                  <div style={{ marginTop: '8px', borderTop: '1px solid var(--border)', paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {/* The history entries map has no original index tracking so we render normally but can't assign accurately from here. We use visual preview row instead which maps to unassigned item chips explicitly. */}
                    {h.entries?.map((e, idx) => {
                       if (!e.item_id) return null; // Only show resolved grouped entries
                       return (
                         <div key={idx} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                           <span>{e.item_name} (₹{e.price}) ×{e.qty}</span>
                           <span style={{ fontWeight: '500' }}>₹{e.price * (e.qty || 1)}</span>
                         </div>
                       )
                    })}
                    {unresolvedChips.map((e, idx) => (
                       <div key={`ur-${idx}`} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                         <span
                           style={{ color: 'var(--danger)', cursor: 'pointer' }}
                           onClick={(ev) => openRetroAssign(i, e.price, e.index, ev)}
                         >
                           ₹{e.price} — not tracked (click to assign)
                         </span>
                         <span style={{ fontWeight: '500' }}>₹{e.price}</span>
                       </div>
                    ))}
                  </div>
                )}

                {/* Inline retroactive assignment panel */}
                {retroAssignRow === i && (
                  <div onClick={(ev) => ev.stopPropagation()} style={{
                    marginTop: '8px', padding: '12px',
                    background: 'var(--surface-2)', borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border)',
                  }}>
                    <div style={{ fontSize: '13px', fontWeight: 600, marginBottom: '8px' }}>
                      Assign item for ₹{retroAssignPrice}
                    </div>
                    <input
                      type="text"
                      autoFocus
                      placeholder="Search item..."
                      value={retroSearch}
                      onChange={(ev) => setRetroSearch(ev.target.value)}
                      onClick={(ev) => ev.stopPropagation()}
                      style={{
                        width: '100%', height: '32px', padding: '0 10px',
                        borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                        background: 'var(--surface)', fontSize: '13px', marginBottom: '6px',
                        boxSizing: 'border-box',
                      }}
                    />
                    {retroError && (
                      <div style={{ fontSize: '12px', color: 'var(--danger)', marginBottom: '6px', padding: '6px', background: 'var(--danger-light)', borderRadius: 'var(--radius-sm)' }}>
                        {retroError}
                      </div>
                    )}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '150px', overflowY: 'auto' }}>
                      {(retroSearch.trim()
                        ? retroProducts.filter(p => p.name.toLowerCase().includes(retroSearch.toLowerCase()))
                        : retroProducts.slice(0, 8)
                      ).map(p => (
                        <Button
                          key={p.id}
                          variant="surface"
                          size="sm"
                          style={{ display: 'flex', justifyContent: 'space-between', opacity: retroLoading ? 0.5 : 1 }}
                          onClick={(ev) => { ev.stopPropagation(); if (!retroLoading) handleRetroSelect(p); }}
                        >
                          <span>{p.emoji} {p.name}</span>
                          <span style={{ color: p.current_qty === 0 ? 'var(--danger)' : 'var(--text-hint)' }}>{p.current_qty} left</span>
                        </Button>
                      ))}
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '6px' }}>
                      <Button size="sm" variant="ghost" onClick={(ev) => { ev.stopPropagation(); setRetroAssignRow(null); setRetroError(null); }}>Cancel</Button>
                    </div>
                  </div>
                )}
              </Card>
              );
            })}
            {history.length === 0 && <div style={{ color: 'var(--text-secondary)', fontSize: '14px' }}>No history yet</div>}
          </div>
        </div>
      </div>
    </div>
  );
}
