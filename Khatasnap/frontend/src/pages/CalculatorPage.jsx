import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { useSRE } from '../hooks/useSRE';
import { useVoice } from '../hooks/useVoice';
import { useToast } from '../hooks/useToast';
import { resolvePrice, selectItem, submitSession, getHistory, assignItem } from '../api/calculator';
import MicButton from '../components/voice/MicButton';
import SREFlagList from '../components/sre/SREFlagList';
import { CheckCircle, Mic } from 'lucide-react';
import Divider from '../components/ui/Divider';
import { usePassiveASR } from '../hooks/usePassiveASR';
import { extractItemMentions, matchMentionsToOperands } from '../utils/speechMatcher';
import { getSnapshot, addPriceAlias } from '../api/inventory';
import { findCombinations } from '../utils/compositeResolver';

const RenderChip = ({ entry, onClick, isActive }) => {
  const border = isActive ? '2px solid var(--primary)' 
                 : entry.status === 'ambiguous' ? '1px solid var(--warning)' 
                 : entry.status === 'not_found' ? '1px dashed var(--border)' 
                 : '1px solid var(--border)';
  const glow = entry.status === 'ambiguous' ? '0 0 5px var(--warning)' : 'none';
  const name = entry.name || entry.item_name;
  const isMultiple = entry.qty && entry.qty > 1;
  const price = entry.price || entry.value;
  
  return (
     <div onClick={onClick} style={{ position: 'relative', background: 'var(--surface)', border, borderRadius: 'var(--radius-md)', padding: '6px 10px', minWidth: '72px', maxWidth: '120px', cursor: 'pointer', boxShadow: glow, transition: 'all 0.2s' }}>
        {isMultiple && entry.status === 'resolved' && (
            <div style={{ position: 'absolute', top: '-6px', right: '-6px', background: 'var(--warning)', color: 'var(--surface)', fontSize: '10px', fontWeight: 'bold', padding: '2px 4px', borderRadius: '8px' }}>
                ×{entry.qty}
            </div>
        )}
        {entry.status === 'ambiguous' ? (
            <>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Pending</div>
              <div style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-primary)' }}>₹{entry.value} ?</div>
            </>
        ) : entry.status === 'not_found' ? (
            <>
              <div style={{ fontSize: '10px', color: 'var(--warning)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>New item</div>
              <div style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-hint)' }}>₹{entry.value}</div>
            </>
        ) : (
            <>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'flex', alignItems: 'center', gap: '4px' }}>
                {entry.resolution_method === 'speech' && <Mic size={10} color="var(--primary)" />}
                {entry.resolution_method === 'speech_ambiguous' && <Mic size={10} color="var(--warning)" />}
                {entry.emoji} {entry.status === 'auto' && entry.resolution_method !== 'speech' ? '~' : ''}{name}
                {entry.status === 'auto' && entry.resolution_method !== 'speech' && (
                    <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: entry.confidence > 0.85 ? 'var(--success)' : 'var(--warning)', flexShrink: 0 }} />
                )}
              </div>
              <div style={{ fontSize: '16px', fontWeight: 500, color: 'var(--text-primary)' }}>₹{price}</div>
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
  
  const passive = usePassiveASR();
  const [inventory, setInventory] = useState([]);
  const newItemInputRef = useRef(null);

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

  const wakeASR = () => { if (passive.status === 'idle') passive.start(); };

  const handleChar = (c) => { wakeASR(); setCurrentOperand(prev => prev + c); };
  const handleClear = () => { 
     wakeASR(); passive.clearBuffer();
     if (entries.length > 0 && !window.confirm("Clear this session? Inventory has not been updated yet.")) return;
     setExpression(''); setCurrentOperand(''); setResult(0); setFlags([]); setPendingSession(null); setEntries([]); setActiveEntryId(null); setNewItemEntryId(null); setNewItemName(''); setPendingSubmitData(null);
     window._isSubmitting = false;
  };
  const handleBackspace = () => { wakeASR(); setCurrentOperand(prev => prev.slice(0, -1)); };

  const entriesRef = useRef(entries);
  useEffect(() => { entriesRef.current = entries; }, [entries]);

  useEffect(() => {
     getHistory(10).then(setHistory).catch(console.error);
     getSnapshot().then(setInventory).catch(()=>{});
  }, []);

  useEffect(() => {
    if (voice.intent && voice.intent.items && voice.state === 'done') {
        const newEntries = voice.intent.items.map(item => {
           return {
               id: Date.now().toString() + '-' + Math.random().toString(36).substr(2, 9),
               value: item.price,
               item_id: item.id || null, 
               item_name: item.name,
               name: item.name,
               qty: item.qty,
               status: 'resolved',
               resolution_method: 'speech'
           };
        });
        if (newEntries.length > 0) {
           setEntries(prev => [...prev, ...newEntries]);
           const sum = newEntries.reduce((acc, curr) => acc + (curr.value * curr.qty), 0);
           setResult(prev => prev + sum);
           
           const adds = newEntries.map(e => {
               if (e.qty > 1) return Array(e.qty).fill(e.value).join('+');
               return e.value;
           }).join('+');
           setExpression(prev => prev ? prev + '+' + adds + '+' : adds + '+');
           
           toast.success("Voice items added to calculator");
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

    const now = new Date();
    try {
       const res = await resolvePrice(price, now.getHours(), now.getDay());
       const combinations = findCombinations(price, inventory);
       const hasMultiples = combinations.some(c => c.type === 'multiple');

       setEntries(prev => prev.map(e => {
          if (e.id !== entryId) return e;
          if (res.status === 'not_found') {
             return { ...e, status: 'not_found', resolve_status: res.status, alternatives: [], combinations: [] };
          }
          
          if (hasMultiples || res.status === 'ambiguous') {
             setActiveEntryId(entryId);
             return { ...e, status: 'ambiguous', resolve_status: res.status, alternatives: res.items || [], combinations: combinations };
          }
          if (res.status === 'unique') return { ...e, status: 'resolved', resolve_status: res.status, ...res.item, qty: 1 };
          if (res.status === 'auto') {
             setTimeout(() => {
                 toast.success(`Auto-assigned: ${res.item.item_name || res.item.name}`, { duration: 3000 });
             }, 0);
             return { ...e, status: 'auto', resolve_status: res.status, ...res.item, confidence: res.confidence, alternatives: res.alternatives, qty: 1 };
          }
          setActiveEntryId(entryId);
          return { ...e, status: 'ambiguous', resolve_status: res.status, alternatives: res.items || [], combinations: [] };
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

          if (payload.status === 'flags_detected' || unresolvedFlags.length > 0) {
              setPendingSession({ ...sessionData, session_id: payload.session_id, unresolved_operands: unresolvedIndices });
          } else {
              triggerSuccess({ ...sessionData, session_id: payload.session_id, unresolved_operands: unresolvedIndices });
          }
      }).catch(() => {
          window._isSubmitting = false;
          toast.error("Failed to submit session");
      });
  };

  const handleEquals = async () => {
    if (currentOperand) await finalizeOperand(currentOperand, '');
    
    // Give async state update from finalizeOperand time to settle
    setTimeout(async () => {
        const currentEntries = entriesRef.current;
        const transcript = passive.getBuffer();
        let finalEntries = [...currentEntries];
        let spoken_context = { raw_transcript: '', mentions: [], resolution_method: 'pattern' };

        if (transcript && inventory.length > 0) {
           const mentions = extractItemMentions(transcript, inventory);
           const ops = currentEntries.map(e => e.value);
           const matchMap = matchMentionsToOperands(mentions, ops, inventory);

           let assignedViaSpeech = [];

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
               resolution_method: finalEntries.some(e => ['speech', 'speech_ambiguous'].includes(e.resolution_method)) ? 'speech' : 'pattern'
           };
           
           if (assignedViaSpeech.length > 0) {
              toast.success(`Voice captured: ${assignedViaSpeech.join(", ")}`);
           }
        }

        passive.stop();
        passive.clearBuffer();
        setEntries(finalEntries);

        const hasNotFound = finalEntries.some(e => e.status === 'not_found');
        let evalString = (expression + currentOperand).replace(/×/g, '*').replace(/÷/g, '/');
        evalString = evalString.replace(/[\+\-\*\/]+$/, '');
        
        const submitData = { spoken_context, evalString, fullExpression: expression + currentOperand };

        if (hasNotFound) {
          promptNextNewItem(finalEntries);
        }

        proceedWithSubmission(finalEntries, submitData);

    }, 200); // Wait 200ms for finalizeOperand state to batch and update
  };

  const triggerSuccess = (sessionData) => {
      setShowSuccess(true);
      setTimeout(() => {
         setHistory(prev => [{
            id: sessionData.session_id,
            expression: sessionData.fullExpression,
            result: sessionData.evalResult,
            entries: sessionData.combined,
            unresolved_operands: sessionData.unresolved_operands || [],
            timestamp: new Date().toISOString(),
         }, ...prev]);
         setExpression(''); setCurrentOperand(''); setResult(0); setFlags([]); setPendingSession(null); setEntries([]); setActiveEntryId(null); setNewItemEntryId(null); setNewItemName(''); setPendingSubmitData(null);
         setShowSuccess(false);
      }, 1500);
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
          <div style={{ backgroundColor: 'var(--surface-2)', padding: '16px 20px', minHeight: '120px', display: 'flex', flexDirection: 'column', position: 'relative' }}>
            {showSuccess && (
              <div style={{ position: 'absolute', top: 12, left: 12 }}>
                <CheckCircle size={24} color="var(--success)" />
              </div>
            )}
            
            <div style={{ position: 'absolute', top: 12, right: 12 }} title={passive.status === 'listening' ? 'Listening for item names...' : passive.status === 'error' ? 'Microphone access denied' : ''}>
               {passive.status === 'listening' && <motion.div animate={{ opacity: [1, 0.4, 1] }} transition={{ repeat: Infinity, duration: 2 }} style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--success)' }} />}
               {passive.status === 'error' && <div style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: 'var(--danger)' }} />}
            </div>
            
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginBottom: 'auto' }}>
               <AnimatePresence>
                  {entries.map(e => (
                     <motion.div key={e.id} layout initial={{scale:0.8, opacity:0}} animate={{scale:1, opacity:1}}>
                        <RenderChip entry={e} isActive={activeEntryId === e.id || newItemEntryId === e.id} onClick={() => {
                          if (e.status === 'not_found') {
                            setNewItemEntryId(e.id);
                            setNewItemName('');
                          } else {
                            // Less-click workflow: if we have a single clear match, auto-assign on click.
                            if (shouldAutoPick(e)) {
                              const pick = (e.alternatives || [])[0];
                              if (pick) {
                                handleSelectItem(e.id, pick);
                                return;
                              }
                            }
                            setActiveEntryId(e.id);
                          }
                        }} />
                     </motion.div>
                  ))}
               </AnimatePresence>
            </div>

            <div style={{ fontFamily: 'var(--mono)', fontSize: '13px', color: 'var(--text-hint)', marginTop: '24px', textAlign: 'right' }}>
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
              <Button variant="primary" size="lg" style={{ gridColumn: 'span 3', fontSize: '24px', height: '52px' }} onClick={handleEquals}>=</Button>
            </div>

            {/* Ambiguous item picker (existing items with same price) */}
            <AnimatePresence>
              {showInlineResolutionPanels && activeEntryId && !newItemEntryId && (
                <motion.div initial={{y: 20, opacity: 0, height: 0}} animate={{y: 0, opacity: 1, height: 'auto'}} exit={{y: 20, opacity: 0, height: 0}} style={{ background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius-lg)', marginTop: '24px' }}>
                   <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '12px' }}>What did you sell for ₹{entries.find(e => e.id === activeEntryId)?.value}?</div>
                    {entries.find(e => e.id === activeEntryId)?.alternatives?.length > 0 && (
                      <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px' }}>Single item</div>
                    )}
                   <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                     {entries.find(e => e.id === activeEntryId)?.alternatives?.slice(0, 6).map(alt => (
                        <Button key={alt.id} variant="surface" size="sm" style={{ display: 'flex', justifyContent: 'space-between' }} onClick={() => handleSelectItem(activeEntryId, alt)}>
                           <span>{alt.emoji} {alt.name}</span>
                           <span style={{ color: alt.current_qty === 0 ? 'var(--danger)' : 'var(--text-hint)' }}>{alt.current_qty} left</span>
                        </Button>
                     ))}
                   </div>

                   {entries.find(e => e.id === activeEntryId)?.combinations?.filter(c => c.type === 'multiple').length > 0 && (
                     <>
                        <div style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '16px 0 8px 0' }}>Or multiple items?</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px' }}>
                          {entries.find(e => e.id === activeEntryId)?.combinations.filter(c => c.type === 'multiple').slice(0, 4).map((comb, idx) => (
                             <Button key={`comb-${idx}`} variant="surface" size="sm" style={{ display: 'flex', justifyContent: 'space-between' }} onClick={() => handleSelectItem(activeEntryId, comb, true)}>
                                <span>{comb.item_emoji} {comb.qty}× {comb.item_name} (₹{comb.price_per_unit} each)</span>
                             </Button>
                          ))}
                        </div>
                     </>
                   )}
                   <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
                      <Button variant="ghost" size="sm" onClick={() => setActiveEntryId(null)}>Skip</Button>
                   </div>
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

            <div style={{ display: 'flex', justifyContent: 'center', marginTop: '24px' }}>
               <MicButton 
                 state={voice.state} 
                 onToggle={() => {
                   if (voice.state === 'listening') {
                     voice.stop();
                   } else if (voice.state === 'done' || voice.state === 'idle' || voice.state === 'error') {
                     voice.start();
                   }
                   // 'transcribing' → do nothing, wait for it to finish
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
