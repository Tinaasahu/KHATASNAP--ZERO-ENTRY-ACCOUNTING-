import React, { useState, useRef } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { useToast } from '../hooks/useToast';
import { uploadBill, confirmBill } from '../api/ocr';
import { check } from '../api/sre';
import { useSRE } from '../hooks/useSRE';
import SREFlagList from '../components/sre/SREFlagList';
import { UploadCloud, Plus, Trash2 } from 'lucide-react';
import { buildBillPayload } from '../utils/contract';
import Divider from '../components/ui/Divider';
import { searchInventory } from '../api/inventory';

export default function OCRPage() {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [ocrResult, setOcrResult] = useState(null);
  const [formData, setFormData] = useState({});
  const fileInputRef = useRef(null);
  const toast = useToast();
  const { flags, setFlags, resolveFlag, areAllResolved } = useSRE();
  const [saving, setSaving] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [searchingIdx, setSearchingIdx] = useState(null);
  const [searchQ, setSearchQ] = useState({});
  const [searchResults, setSearchResults] = useState({});

  const hasUnresolvedVariants = () => {
    const items = formData.items || [];
    return items.some((it) => {
      if (it.product_id) return false;
      const status = it.match_status;
      const candidates = it.match_candidates || [];
      if (!candidates.length) return false;

      // Only block when ambiguity is *high-confidence* (i.e., we might accidentally create a duplicate
      // or pick the wrong variant). Low-confidence suggestions shouldn't block auto-create.
      const top = candidates[0];
      const second = candidates[1];
      const topScore = Number(top?.score || 0);
      const secondScore = Number(second?.score || 0);

      const isHighConfidence = topScore >= 0.86;
      const isCloseSecond = second && (topScore - secondScore) < 0.08 && secondScore >= 0.78;
      const flaggedAmbiguous = (status === 'ambiguous' || status === 'needs_selection' || it.needs_user_selection);

      if (flaggedAmbiguous && isHighConfidence && (isCloseSecond || it.needs_user_selection)) return true;
      return false;
    });
  };

  const handleFileChange = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    setFile(f);
    if (f.type.startsWith('image/')) {
       setPreview(URL.createObjectURL(f));
    } else {
       setPreview(null);
    }
  };

  const handleExtract = async () => {
    if (!file) return;
    setLoading(true);
    try {
      const res = await uploadBill(file);
      setOcrResult(res);
      setFormData({
        vendor_name: res.vendor_name || '',
        invoice_date: res.invoice_date || '',
        total_amount: res.total_amount || 0,
        items: res.items.map(i => ({...i}))
      });
      
      const payload = buildBillPayload({ ...res, source: 'ocr' });
      try {
        const sreRes = await check({ items: payload.items, payment_mode: 'cash', total_amount: payload.total_amount});
        setFlags(sreRes.sre_flags || []);
      } catch(e) {
        toast.error('Failed to run smart checks');
      }
      
      toast.success('Extraction complete');
    } catch (e) {
      toast.error(e.message || 'Failed to extract bill');
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateItem = (index, field, value) => {
    const newItems = [...formData.items];
    newItems[index][field] = value;
    if (field === 'qty' || field === 'price') {
       newItems[index].amount = (newItems[index].qty || 0) * (newItems[index].price || 0);
    }
    setFormData({ ...formData, items: newItems });
  };

  const runSearch = async (idx, q) => {
    setSearchingIdx(idx);
    setSearchQ((p) => ({ ...p, [idx]: q }));
    if (!q || q.trim().length < 2) {
      setSearchResults((p) => ({ ...p, [idx]: [] }));
      setSearchingIdx(null);
      return;
    }
    try {
      const res = await searchInventory(q.trim());
      setSearchResults((p) => ({ ...p, [idx]: res.items || [] }));
    } catch {
      setSearchResults((p) => ({ ...p, [idx]: [] }));
    } finally {
      setSearchingIdx(null);
    }
  };

  const pickCandidate = (idx, cand) => {
    const newItems = [...formData.items];
    newItems[idx] = {
      ...newItems[idx],
      product_id: cand.id,
      matched_name: cand.name,
      match_method: 'manual_pick',
      match_status: 'matched',
      // prefer DB price if OCR didn't have one
      price: newItems[idx].price || cand.selling_price || 0,
    };
    newItems[idx].amount = (newItems[idx].qty || 0) * (newItems[idx].price || 0);
    setFormData({ ...formData, items: newItems });
  };

  const handleConfirm = async () => {
    if (!areAllResolved()) {
       toast.warning('Please resolve all smart checks first');
       return;
    }
    if (hasUnresolvedVariants()) {
      toast.warning('Please select the correct variant for all ambiguous items.');
      return;
    }
    setSaving(true);
    try {
      // Integrate corrections to form payload
      const updatedItems = formData.items.map((item, idx) => {
         const flag = flags.find(f => f.field === `items[${idx}].qty` && f.resolution === 'corrected');
         if (flag && flag.corrected_value) {
            return { ...item, qty: Number(flag.corrected_value) };
         }
         return item;
      });

      const payload = buildBillPayload({ ...ocrResult, ...formData, items: updatedItems, source: 'ocr' });
      payload.sre_flags = flags;
      
      await confirmBill(payload);
      toast.success('Bill confirmed and saved successfully');
      setFile(null);
      setPreview(null);
      setOcrResult(null);
      setFlags([]);
    } catch (e) {
       toast.error(e.message || 'Failed to confirm bill');
    } finally {
       setSaving(false);
    }
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: ocrResult ? '1fr 1fr' : '1fr', gap: '32px' }}>
      
      <Card style={{ alignSelf: 'start' }}>
        <h2 style={{ fontSize: '18px', fontWeight: '500', marginBottom: '16px' }}>Upload Bill</h2>
        
        <div 
          onClick={() => fileInputRef.current?.click()}
          style={{
            border: '2px dashed var(--border-strong)',
            borderRadius: 'var(--radius-xl)',
            padding: '48px 24px',
            textAlign: 'center',
            cursor: 'pointer',
            backgroundColor: 'var(--surface-2)',
            transition: 'all 150ms ease',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '12px'
          }}
        >
           <UploadCloud size={48} color="var(--text-hint)" />
           {file ? (
             <div style={{ fontWeight: '500', color: 'var(--accent)' }}>{file.name}</div>
           ) : (
             <div style={{ fontWeight: '500', color: 'var(--text-secondary)' }}>Click or drag to select Image/PDF</div>
           )}
           <input type="file" ref={fileInputRef} onChange={handleFileChange} style={{ display: 'none' }} accept="image/*,application/pdf" />
        </div>

        {preview && (
          <div style={{ marginTop: '16px', borderRadius: 'var(--radius-md)', overflow: 'hidden' }}>
            <img src={preview} alt="Bill Preview" style={{ width: '100%', maxHeight: '300px', objectFit: 'contain', backgroundColor: '#f0f0f0' }} />
          </div>
        )}

        {file && (
          <Button loading={loading} onClick={handleExtract} style={{ width: '100%', marginTop: '24px' }}>
            Extract Bill Data
          </Button>
        )}
      </Card>

      {ocrResult && (
        <Card shadow style={{ alignSelf: 'start' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
             <h2 style={{ fontSize: '18px', fontWeight: '500' }}>Extraction Results</h2>
             <Button variant="ghost" size="sm" onClick={() => setShowRaw(!showRaw)}>{showRaw ? 'Hide Raw' : 'Show Raw OCR'}</Button>
          </div>

          {showRaw && ocrResult.raw_data && (
            <div style={{ backgroundColor: 'var(--bg)', padding: '12px', borderRadius: 'var(--radius-md)', fontFamily: 'monospace', fontSize: '12px', marginBottom: '16px', maxHeight: '150px', overflowY: 'auto' }}>
              {JSON.stringify(ocrResult.raw_data, null, 2)}
            </div>
          )}

          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <div style={{ flex: 1 }}>
               <label style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Vendor</label>
               <input style={{ width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }} value={formData.vendor_name} onChange={e => setFormData({...formData, vendor_name: e.target.value})} />
            </div>
            <div style={{ flex: 1 }}>
               <label style={{ fontSize: '12px', color: 'var(--text-secondary)', display: 'block', marginBottom: '4px' }}>Date</label>
               <input type="date" style={{ width: '100%', padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }} value={formData.invoice_date} onChange={e => setFormData({...formData, invoice_date: e.target.value})} />
            </div>
          </div>

          <h3 style={{ fontSize: '14px', fontWeight: '500', marginBottom: '8px', borderBottom: '1px solid var(--border)', paddingBottom: '8px' }}>Line Items</h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
             {formData.items.map((item, idx) => (
                <div key={idx} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: '10px', background: 'var(--surface)' }}>
                  <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                    <input style={{ flex: 2, padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }} value={item.name} onChange={e => handleUpdateItem(idx, 'name', e.target.value)} />
                    <input type="number" style={{ flex: 1, padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }} value={item.qty} onChange={e => handleUpdateItem(idx, 'qty', Number(e.target.value))} />
                    <input type="number" style={{ flex: 1, padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }} value={item.price} onChange={e => handleUpdateItem(idx, 'price', Number(e.target.value))} />
                    <Button variant="ghost" size="sm" onClick={() => {
                      setFormData(prev => ({ ...prev, items: prev.items.filter((_, i) => i !== idx) }));
                    }}><Trash2 size={16} color="var(--danger)" /></Button>
                  </div>

                  {(item.needs_user_selection || item.match_status === 'ambiguous' || item.match_status === 'needs_selection') && !item.product_id && (
                    <div style={{ marginTop: '10px', padding: '10px', borderRadius: 'var(--radius-md)', background: 'var(--surface-2)', border: '1px solid var(--border)' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', alignItems: 'baseline', marginBottom: '8px' }}>
                        <div style={{ fontSize: '12px', fontWeight: 700 }}>Variant selection required</div>
                        <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>{item.variant ? `OCR: ${item.variant}` : 'OCR: variant unclear'}</div>
                      </div>

                      {(item.match_candidates || []).length > 0 && (
                        <div style={{ display: 'grid', gap: '6px', marginBottom: '10px' }}>
                          {(item.match_candidates || []).map((c) => (
                            <button
                              key={c.id}
                              onClick={() => pickCandidate(idx, c)}
                              style={{ textAlign: 'left', padding: '8px 10px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--surface)', cursor: 'pointer' }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                                <div style={{ fontSize: '12px', fontWeight: 800 }}>
                                  {c.emoji || '📦'} {c.name}{c.variant_label ? ` • ${c.variant_label}` : ''}
                                </div>
                                <div style={{ fontSize: '12px', fontWeight: 800 }}>₹{Number(c.selling_price || 0).toFixed(2)}</div>
                              </div>
                              <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>score: {c.score}</div>
                            </button>
                          ))}
                        </div>
                      )}

                      <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                        <input
                          placeholder="Search inventory (name/barcode)..."
                          value={searchQ[idx] || ''}
                          onChange={(e) => runSearch(idx, e.target.value)}
                          style={{ flex: 1, padding: '8px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)' }}
                        />
                        <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>
                          {searchingIdx === idx ? 'Searching…' : ''}
                        </div>
                      </div>

                      {(searchResults[idx] || []).length > 0 && (
                        <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
                          {(searchResults[idx] || []).map((r) => (
                            <button
                              key={r.id}
                              onClick={() => pickCandidate(idx, { id: r.id, name: r.name, emoji: r.emoji, selling_price: r.price, variant_label: '' })}
                              style={{ textAlign: 'left', padding: '8px 10px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--surface)', cursor: 'pointer' }}
                            >
                              <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                                <div style={{ fontSize: '12px', fontWeight: 800 }}>{r.emoji || '📦'} {r.name}</div>
                                <div style={{ fontSize: '12px', fontWeight: 800 }}>Stock: {r.quantity}</div>
                              </div>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
             ))}
             <Button variant="ghost" size="sm" onClick={() => {
                setFormData(prev => ({ ...prev, items: [...prev.items, { name: 'New Item', qty: 1, price: 0 }]}));
             }} style={{ alignSelf: 'flex-start' }}><Plus size={16}/> Add Row</Button>
          </div>

          <Divider />

          <div style={{ marginBottom: '24px' }}>
            <h3 style={{ fontSize: '12px', color: 'var(--text-hint)', textTransform: 'uppercase', letterSpacing: '1px', marginBottom: '12px' }}>Smart Checks</h3>
            <SREFlagList flags={flags} onResolve={resolveFlag} />
          </div>

          <Button loading={saving} disabled={!areAllResolved() || hasUnresolvedVariants()} onClick={handleConfirm} style={{ width: '100%' }}>
            Confirm & Save
          </Button>

        </Card>
      )}
    </div>
  );
}
