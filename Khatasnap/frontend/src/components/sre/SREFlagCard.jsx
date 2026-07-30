import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import Button from '../ui/Button';
import { addPriceAlias, getSnapshot, searchInventory } from '../../api/inventory';
import { assignItem, resolvePrice } from '../../api/calculator';
import { findCombinations } from '../../utils/compositeResolver';
import client from '../../api/client';

// ─── UNRESOLVED ENTRY CARD ─────────────────────────────────────────────────
function UnresolvedEntryCard({ flag, onAccept, onDismiss }) {
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [duplicatePrompt, setDuplicatePrompt] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  
  const [alternatives, setAlternatives] = useState([]);
  const [combinations, setCombinations] = useState([]);
  
  // New Item State
  const [newItemName, setNewItemName] = useState(flag.typed_name || '');

  useEffect(() => {
    const fetchOptions = async () => {
       try {
          let itemsToUse = [];
          
          if (flag.candidate_items && flag.candidate_items.length > 0) {
              itemsToUse = flag.candidate_items;
          } else {
              const now = new Date();
              const res = await resolvePrice(flag.operand, now.getHours(), now.getDay());
              if (res && res.items) itemsToUse = res.items;
              else if (res && res.item) itemsToUse = [res.item];
          }

          // Deduplicate
          const deduped = itemsToUse.filter((item, index, self) =>
              index === self.findIndex(t => t.id === item.id || t.item_id === item.item_id)
          );
          setAlternatives(deduped);

          if (flag.combinations && flag.combinations.length > 0) {
              setCombinations(flag.combinations);
          } else {
              const snapshot = await getSnapshot();
              const combos = findCombinations(flag.operand, snapshot);
              if (combos) setCombinations(combos);
          }
       } catch (err) {
          console.error("Failed to load options for unresolved entry", err);
       }
    };
    if (!flag.is_new_item) fetchOptions();
  }, [flag]);

  useEffect(() => {
    if (!flag.is_new_item) return;

    const typed = newItemName.trim();
    if (typed.length < 2) {
      setSuggestions([]);
      return;
    }

    const timeoutId = setTimeout(async () => {
      try {
        const payload = await searchInventory(typed);
        setSuggestions(payload?.items || []);
      } catch {
        setSuggestions([]);
      }
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [flag.is_new_item, newItemName]);

  const operandIndex = flag.original_idx?.pIdx !== undefined ? flag.original_idx.pIdx : flag.operand_index;

  const normalizeExistingItem = (item) => ({
    id: item.id || item.item_id,
    name: item.name || item.item_name,
    price: item.price ?? item.selling_price,
    quantity: item.quantity ?? item.current_qty,
    emoji: item.emoji || '📦',
  });

  const handleSelect = async (item_id, item_name, qty = 1) => {
    setError(null);
    setLoading(true);
    try {
      await assignItem(flag.session_id, {
        operand_index: operandIndex,
        operand:   flag.operand,
        item_id:   item_id,
        item_name: item_name,
        qty:       qty,
      });
      onAccept?.(item_name); 
    } catch (e) {
      if (e?.status === 409) {
        setError(e.message || `${item_name} is out of stock.`);
      } else {
        setError(e?.message || 'Failed to assign item. Try again.');
      }
      setLoading(false);
    }
  };
  
  const proceedWithCreatedItem = async (item, displayName) => {
      const itemName = item.name || displayName;
      const itemId = item.id || item.item_id;

      await assignItem(flag.session_id, {
        operand_index: operandIndex,
        operand:   flag.operand,
        item_id:   itemId,
        item_name: itemName,
        qty:       1,
        allow_out_of_stock: true,
      });

      onAccept?.(itemName, {
        toastMessage: `${itemName} added to inventory and sale recorded.`,
      });
  };

  const showExistsPrompt = (item, typedName = newItemName.trim()) => {
      const existing = normalizeExistingItem(item);
      const newPrice = flag.operand;

      setDuplicatePrompt({
        existing_item: existing,
        new_price: newPrice,
        typed_name: typedName || existing.name,
        message: `${existing.name} already exists in your inventory at ₹${existing.price}. Add ₹${newPrice} as another price for it?`,
      });
      setSuggestions([]);
      setError(null);
  };
  
  const handleSaveNewItem = async (overrideName) => {
      const nameToSave = (overrideName || newItemName).trim();
      if (!nameToSave) return;
      setError(null);
      setLoading(true);
      try {
          const res = await client.post('/api/inventory/add-new-item', { name: nameToSave, price: flag.operand });
          const payload = res.data?.data || res.data;

          if (payload.status === 'exists') {
            showExistsPrompt(payload.existing_item, nameToSave);
            setLoading(false);
            return;
          }

          const createdItem = payload.item || payload;
          await proceedWithCreatedItem(createdItem, nameToSave);
      } catch (err) {
          setError(err.message || err?.detail || 'Failed to add item');
          setLoading(false);
      }
  };

  const handleGroupExisting = async () => {
      if (!duplicatePrompt?.existing_item) return;

      const existing = duplicatePrompt.existing_item;
      const newPrice = duplicatePrompt.new_price;

      setError(null);
      setLoading(true);
      try {
          await addPriceAlias({
            item_id: existing.id,
            item_name: existing.name,
            alias_price: newPrice,
          });

          await assignItem(flag.session_id, {
            operand_index: operandIndex,
            operand: flag.operand,
            item_id: existing.id,
            item_name: existing.name,
            qty: 1,
          });

          onAccept?.(existing.name, {
            toastMessage: `₹${newPrice} grouped with ${existing.name}. Inventory updated.`,
          });
      } catch (err) {
          setError(err.message || err?.detail || 'Failed to group item');
          setLoading(false);
      }
  };

  const handleSaveDuplicateAsNew = () => {
      const baseName = duplicatePrompt?.typed_name || newItemName.trim();
      const newName = `${baseName} (₹${flag.operand})`;

      setNewItemName(newName);
      setDuplicatePrompt(null);
      handleSaveNewItem(newName);
  };

  if (flag.is_new_item) {
      return (
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
          className="card"
          style={{ background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius-lg)', marginBottom: '12px', border: '1px solid var(--warning)' }}
        >
           <div style={{ fontSize: '14px', fontWeight: 'bold', marginBottom: '4px', color: 'var(--warning)' }}>
             New item detected — what is this?
           </div>
           <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '12px' }}>
             ₹{flag.operand} is not in your inventory. Give it a name to track it.
           </div>
           
           <input 
             type="text" 
             value={newItemName}
             onChange={e => {
               setNewItemName(e.target.value);
               setDuplicatePrompt(null);
               setError(null);
             }}
             placeholder="Type item name..."
             autoFocus
             style={{
               width: '100%', height: '40px', padding: '0 12px',
               borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
               background: 'var(--surface)', boxSizing: 'border-box',
               fontSize: '14px', marginBottom: '12px'
             }}
           />

           {!duplicatePrompt && suggestions.length > 0 && (
             <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
               <span>Did you mean:</span>
               {suggestions.map(item => {
                 const existing = normalizeExistingItem(item);
                 return (
                   <Button
                     key={existing.id}
                     variant="secondary"
                     size="sm"
                     onClick={() => {
                       setNewItemName(existing.name);
                       showExistsPrompt(existing, existing.name);
                     }}
                     disabled={loading}
                   >
                     {existing.name}
                   </Button>
                 );
               })}
             </div>
           )}

           {duplicatePrompt && (
             <div style={{ background: 'var(--warning-light)', border: '1px solid var(--warning)', borderRadius: 'var(--radius-md)', padding: '10px 14px', marginBottom: '12px' }}>
               <div style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '10px' }}>
                 {duplicatePrompt.message}
               </div>
               <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px', flexWrap: 'wrap' }}>
                 <Button variant="secondary" size="sm" onClick={handleSaveDuplicateAsNew} disabled={loading}>
                   Save as new item
                 </Button>
                 <Button variant="primary" size="sm" onClick={handleGroupExisting} disabled={loading}>
                   Yes, group it
                 </Button>
               </div>
             </div>
           )}
           
           {error && (
             <div style={{ fontSize: '12px', color: 'var(--danger)', marginBottom: '12px', padding: '8px', background: 'var(--danger-light)', borderRadius: 'var(--radius-sm)' }}>
               {error}
             </div>
           )}
           
           <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <Button variant="ghost" size="sm" onClick={onDismiss} disabled={loading}>Skip</Button>
              {!duplicatePrompt && (
                <Button variant="primary" size="sm" onClick={() => handleSaveNewItem()} disabled={loading || !newItemName.trim()}>
                   {loading ? 'Saving...' : `Save as ${newItemName.trim() || 'item'}`}
                </Button>
              )}
           </div>
        </motion.div>
      );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
      className="card"
      style={{ background: 'var(--surface-2)', padding: '16px', borderRadius: 'var(--radius-lg)', marginBottom: '12px' }}
    >
       <div style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', alignItems: 'center', marginBottom: '12px' }}>
         <div style={{ fontSize: '14px', fontWeight: 'bold' }}>What did you sell for ₹{flag.operand}?</div>
         {alternatives?.length > 0 && (
           <Button
             size="sm"
             onClick={() => {
               const alt = alternatives[0];
               if (!alt || loading) return;
               const itemName = alt.name || alt.item_name || alt.product_name || alt.label || `Item ₹${alt.price || flag.operand}`;
               handleSelect(alt.id || alt.item_id, itemName, 1);
             }}
             disabled={loading}
           >
             Assign best
           </Button>
         )}
       </div>
        {alternatives?.length > 0 && (
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '8px' }}>Single item</div>
        )}
       <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
         {alternatives?.slice(0, 6).map(alt => {
            const itemName = alt.name || alt.item_name || alt.product_name || alt.label || `Item ₹${alt.price || flag.operand}`;
            const stockLeft = alt.quantity !== undefined ? alt.quantity : (alt.stock !== undefined ? alt.stock : (alt.qty !== undefined ? alt.qty : (alt.quantity_left !== undefined ? alt.quantity_left : alt.current_qty)));
            return (
                <Button key={alt.id || alt.item_id} variant="surface" size="sm" style={{ display: 'flex', justifyContent: 'space-between', opacity: loading ? 0.5 : 1 }} onClick={() => !loading && handleSelect(alt.id || alt.item_id, itemName, 1)}>
                   <span>{alt.emoji || '📦'} {itemName}</span>
                   {stockLeft !== null && stockLeft !== undefined ? (
                       <span style={{ color: stockLeft === 0 ? 'var(--danger)' : 'var(--text-hint)' }}>{stockLeft} left</span>
                   ) : (
                       <span style={{ color: 'var(--text-hint)' }}>stock unknown</span>
                   )}
                </Button>
            );
         })}
       </div>

       {combinations?.filter(c => c.type === 'multiple').length > 0 && (
         <>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: '16px 0 8px 0' }}>Or multiple items?</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '8px' }}>
              {combinations.filter(c => c.type === 'multiple').slice(0, 4).map((comb, idx) => (
                 <Button key={`comb-${idx}`} variant="surface" size="sm" style={{ display: 'flex', justifyContent: 'space-between', opacity: loading ? 0.5 : 1 }} onClick={() => !loading && handleSelect(comb.item_id, comb.item_name, comb.qty)}>
                    <span>{comb.item_emoji} {comb.qty}× {comb.item_name} (₹{comb.price_per_unit} each)</span>
                 </Button>
              ))}
            </div>
         </>
       )}
       
       {error && (
         <div style={{ fontSize: '12px', color: 'var(--danger)', marginTop: '8px', padding: '8px', background: 'var(--danger-light)', borderRadius: 'var(--radius-sm)' }}>
           {error}
         </div>
       )}

       {alternatives.length === 0 && combinations.length === 0 && !loading && (
          <div style={{ fontSize: '13px', color: 'var(--text-hint)', marginBottom: '12px' }}>
              No matches found in inventory.
          </div>
       )}

       <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', marginTop: '12px' }}>
          <Button variant="ghost" size="sm" onClick={onDismiss}>Ignore</Button>
       </div>
    </motion.div>
  );
}

// ─── MAIN EXPORT ───────────────────────────────────────────────────────────
export default function SREFlagCard({ flag, onAccept, onCorrect, onDismiss, autoAcceptSeconds, onAssign }) {
  // UNRESOLVED_ENTRY gets a completely different, neutral card
  if (flag.flag_type === 'UNRESOLVED_ENTRY') {
    return (
      <UnresolvedEntryCard
        flag={flag}
        onAccept={(itemName, info = {}) => {
          // Notify parent so history row can update immediately
          onAssign?.({ session_id: flag.session_id, operand: flag.operand, item_name: itemName, toastMessage: info.toastMessage });
          onAccept?.();
        }}
        onDismiss={onDismiss}
      />
    );
  }

  // ── Existing flag card (unchanged) ─────────────────────────────────────
  const [isEditing, setIsEditing] = useState(false);
  const [editValue, setEditValue] = useState(flag.actual || '');
  const [products, setProducts]   = useState([]);
  const [timeLeft, setTimeLeft]   = useState(autoAcceptSeconds || null);

  useEffect(() => {
    let interval;
    if (timeLeft !== null && timeLeft > 0 && !isEditing) {
       interval = setInterval(() => setTimeLeft(prev => prev - 1), 1000);
    } else if (timeLeft === 0) {
       onAccept();
    }
    return () => clearInterval(interval);
  }, [timeLeft, isEditing, onAccept]);

  const cancelTimer = () => setTimeLeft(null);

  useEffect(() => {
    if (isEditing && flag.flag_type === 'unknown_product') {
       getSnapshot().then(data => setProducts(data)).catch(() => {});
    }
  }, [isEditing, flag.flag_type]);

  const borderColor = flag.severity === 'critical' ? 'var(--danger)' : 'var(--warning)';
  const bgColor     = flag.severity === 'critical' ? 'var(--danger-light)' : 'var(--warning-light)';
  const textColor   = flag.severity === 'critical' ? 'var(--danger)' : 'var(--warning)';

  // Parse price from actual to find exact matches
  const match       = String(flag.actual).match(/₹([0-9\.]+)/);
  const targetPrice = match ? Number(match[1]) : null;
  const recommended = targetPrice ? products.filter(p => p.selling_price === targetPrice) : [];

  return (
    <motion.div 
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, height: 0, overflow: 'hidden' }}
      className="card"
      style={{ borderLeft: `3px solid ${borderColor}`, marginBottom: '12px', position: 'relative' }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
        <span className="badge" style={{ background: bgColor, color: textColor }}>
          {flag.flag_type.replace(/_/g, ' ').toUpperCase()}
        </span>
        <span style={{ fontSize: '12px', color: 'var(--text-hint)' }}>
          {Math.round((flag.confidence || 0) * 100)}% confidence
        </span>
      </div>
      
      <div style={{ fontSize: '14px', marginBottom: '16px', color: 'var(--text-primary)' }}>
        {flag.message}
      </div>

      <AnimatePresence mode="wait">
        {!isEditing ? (
          <motion.div key="buttons" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            {timeLeft !== null && (
               <div style={{ fontSize: '12px', color: 'var(--warning)', marginBottom: '8px' }}>
                 Auto-accepting in {timeLeft}s...
               </div>
            )}
            {flag.options && flag.options.length > 0 ? (
               <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                 {flag.options.map((opt, i) => (
                    <Button key={opt.id || i} size="sm" variant={i === 0 ? "ghost" : "secondary"} onClick={() => { cancelTimer(); onCorrect(opt); }}>
                      Confirm: {opt.name}
                    </Button>
                 ))}
               </div>
            ) : (
               <div style={{ display: 'flex', gap: '8px' }}>
                 <Button size="sm" variant="ghost" onClick={() => { cancelTimer(); onAccept(); }}>Looks correct</Button>
                 <Button size="sm" variant="secondary" onClick={() => { cancelTimer(); setIsEditing(true); }}>Fix it</Button>
               </div>
            )}
          </motion.div>
        ) : (
          <motion.div key="input" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }}>
            {flag.flag_type === 'unknown_product' ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                 <input 
                   type="text" 
                   autoFocus
                   placeholder="Type item name..."
                   value={typeof editValue === 'object' ? editValue.name : editValue} 
                   onChange={(e) => setEditValue(e.target.value)}
                   style={{ width: '100%', height: '36px', padding: '0 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                 />
                 
                 {typeof editValue === 'string' && editValue.trim().length > 0 && products.filter(p => p.name.toLowerCase().includes(editValue.toLowerCase())).length > 0 && (
                   <div style={{ fontSize: '13px', color: 'var(--text-secondary)', padding: '12px', background: 'var(--surface-2)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)' }}>
                     <p style={{ margin: '0 0 8px 0' }}>This exists in inventory but if you want to save this then it is ok create multiple prices for same items and group them in inventory</p>
                     <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                       {products.filter(p => p.name.toLowerCase().includes(editValue.toLowerCase())).slice(0, 5).map(p => (
                         <Button key={p.id} size="sm" variant="secondary" onClick={() => onCorrect({ ...p, price: targetPrice || p.price })}>
                           {p.emoji} Group as {p.name}
                         </Button>
                       ))}
                     </div>
                   </div>
                 )}
                 
                 <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                   <Button size="sm" variant="primary" onClick={() => onCorrect(typeof editValue === 'object' ? { ...editValue, price: targetPrice || editValue.price } : { name: editValue, id: null, price: targetPrice })}>Save</Button>
                   <Button size="sm" variant="ghost" onClick={() => setIsEditing(false)}>Cancel</Button>
                 </div>
              </div>
            ) : (
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input 
                    type="text" 
                    value={editValue} 
                    onChange={(e) => setEditValue(e.target.value)}
                    style={{ flex: 1, height: '32px', padding: '0 8px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)' }}
                  />
                  <Button size="sm" variant="primary" onClick={() => onCorrect(editValue)}>Apply fix</Button>
                  <Button size="sm" variant="ghost" onClick={() => setIsEditing(false)}>Cancel</Button>
                </div>
            )}
            
          </motion.div>
        )}
      </AnimatePresence>
      
      {timeLeft !== null && autoAcceptSeconds && (
         <div style={{ position: 'absolute', bottom: 0, left: 0, height: '3px', background: 'var(--warning)', width: `${(timeLeft / autoAcceptSeconds) * 100}%`, transition: 'width 1s linear' }} />
      )}
    </motion.div>
  );
}
