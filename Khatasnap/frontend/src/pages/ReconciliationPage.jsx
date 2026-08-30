import React, { useEffect, useMemo, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import ConfidenceBar from '../components/ui/ConfidenceBar';
import { useToast } from '../hooks/useToast';
import { getReconFlags, resolveReconFlag, runReconciliation } from '../api/reconciliation';
import { getNightReconciliation, resolveNightReconciliation, getNightReconciliationStats } from '../api/calculator';
import { searchInventory } from '../api/inventory';

function JsonMini({ obj }) {
  return (
    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px', color: 'var(--text-secondary)' }}>
      {JSON.stringify(obj, null, 2)}
    </pre>
  );
}

// ─────────────────────────────────────────────────────────────
// Night Queue — low-confidence calculator transactions
// ─────────────────────────────────────────────────────────────
function NightQueue() {
  const toast = useToast();
  const [items, setItems]           = useState([]);
  const [loading, setLoading]       = useState(false);
  const [stats, setStats]           = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [resolving, setResolving]   = useState(false);

  // Per-item confirmed entries: { [recon_id]: [{ item_id, item_name, price, qty }] }
  const [confirmed, setConfirmed]   = useState({});

  const load = async () => {
    setLoading(true);
    try {
      const [data, s] = await Promise.all([getNightReconciliation('pending', 50), getNightReconciliationStats()]);
      setItems(data?.items || []);
      setStats(s);
    } catch {
      toast.error('Failed to load night queue');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedItem = items.find(i => i.id === selectedId);

  // Build matched items from the payload for the shopkeeper to confirm
  const payloadItems = useMemo(() => {
    if (!selectedItem) return [];
    const pay = selectedItem.payload || {};
    return pay.finalized_result?.matched_items || [];
  }, [selectedItem]);

  // Build amounts list from payload
  const payloadAmounts = useMemo(() => {
    if (!selectedItem) return [];
    const pay = selectedItem.payload || {};
    return pay.calc_amounts || [];
  }, [selectedItem]);

  const asrTranscript = useMemo(() => {
    if (!selectedItem) return '';
    const pay = selectedItem.payload || {};
    return (pay.asr_segments || []).map(s => s.text).join(' ').trim();
  }, [selectedItem]);

  const toggleConfirm = (recon_id, item) => {
    setConfirmed(prev => {
      const current = prev[recon_id] || [];
      const exists = current.find(e => e.item_id === item.item_id);
      if (exists) return { ...prev, [recon_id]: current.filter(e => e.item_id !== item.item_id) };
      return { ...prev, [recon_id]: [...current, { item_id: item.item_id, item_name: item.item_name, price: item.price, qty: item.qty }] };
    });
  };

  const handleResolve = async (resolution) => {
    if (!selectedItem) return;
    setResolving(true);
    try {
      const entries = resolution === 'resolved' ? (confirmed[selectedItem.id] || []) : [];
      await resolveNightReconciliation(selectedItem.id, resolution, entries);
      toast.success(resolution === 'resolved' ? '✓ Resolved & inventory updated' : 'Dismissed');
      setSelectedId(null);
      await load();
    } catch (e) {
      toast.error(e?.message || 'Failed to resolve');
    } finally {
      setResolving(false);
    }
  };

  if (loading) return <div style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>Loading…</div>;

  return (
    <div style={{ display: 'grid', gap: '12px' }}>
      {/* Stats bar */}
      {stats && (
        <div style={{ display: 'flex', gap: '16px', padding: '10px 14px', background: 'var(--surface)', borderRadius: '12px', border: '1px solid var(--border)' }}>
          <StatBadge label="Pending review" value={stats.pending} color="var(--warning)" />
          <StatBadge label="Resolved today" value={stats.resolved_today} color="var(--success)" />
          <StatBadge label="Total today"    value={stats.total_today}    color="var(--text-secondary)" />
        </div>
      )}

      {items.length === 0 ? (
        <div style={{ color: 'var(--text-secondary)', fontSize: '13px', padding: '20px', textAlign: 'center' }}>
          🎉 No pending transactions in night queue.
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1.3fr 0.9fr', gap: '12px' }}>
          {/* Left: list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {items.map(item => (
              <button
                key={item.id}
                onClick={() => setSelectedId(item.id)}
                style={{
                  textAlign: 'left', padding: '10px 14px', borderRadius: '12px', cursor: 'pointer',
                  border: `1px solid ${selectedId === item.id ? 'var(--primary)' : 'var(--border)'}`,
                  background: selectedId === item.id ? 'rgba(var(--primary-rgb,99,102,241),0.06)' : 'var(--surface)',
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '8px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 700, color: 'var(--text-primary)' }}>
                    #{item.id} — {item.reason?.replace(/_/g, ' ')}
                  </span>
                  <span style={{
                    fontSize: '11px', fontWeight: 600, padding: '2px 7px', borderRadius: '10px',
                    background: item.confidence_score >= 0.5 ? 'rgba(245,158,11,0.12)' : 'rgba(239,68,68,0.1)',
                    color: item.confidence_score >= 0.5 ? '#d97706' : '#dc2626',
                  }}>
                    {Math.round((item.confidence_score ?? 0) * 100)}% conf
                  </span>
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>
                  {new Date(item.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  {item.txn_id && <> · {item.txn_id}</>}
                </div>
              </button>
            ))}
          </div>

          {/* Right: detail */}
          <Card shadow style={{ padding: '14px' }}>
            {!selectedItem ? (
              <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Select a transaction to review.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ fontSize: '14px', fontWeight: 700 }}>Transaction #{selectedItem.id}</div>

                {/* Confidence bar */}
                <ConfidenceBar
                  confidence={selectedItem.payload?.finalized_result || { score: selectedItem.confidence_score, decision: selectedItem.confidence_score >= 0.75 ? 'high' : selectedItem.confidence_score >= 0.5 ? 'medium' : 'low' }}
                  animate={false}
                />

                {/* ASR transcript */}
                {asrTranscript && (
                  <div style={{ background: 'var(--surface-elevated)', borderRadius: '8px', padding: '8px 10px' }}>
                    <div style={{ fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '3px', textTransform: 'uppercase' }}>ASR heard</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-primary)', fontStyle: 'italic' }}>"{asrTranscript}"</div>
                  </div>
                )}

                {/* Calculator amounts */}
                {payloadAmounts.length > 0 && (
                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '4px' }}>Calculator amounts</div>
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                      {payloadAmounts.map((a, i) => (
                        <span key={i} style={{ fontSize: '12px', fontWeight: 600, background: 'var(--surface)', border: '1px solid var(--border)', padding: '2px 8px', borderRadius: '8px' }}>
                          ₹{typeof a === 'object' ? a.value : a}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Matched items — shopkeeper confirms */}
                {payloadItems.length > 0 && (
                  <div>
                    <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '6px' }}>
                      Confirm items to deduct inventory:
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
                      {payloadItems.map((item, i) => {
                        const isChecked = (confirmed[selectedItem.id] || []).some(e => e.item_id === item.item_id);
                        return (
                          <label key={i} style={{
                            display: 'flex', alignItems: 'center', gap: '8px',
                            padding: '6px 10px', borderRadius: '8px', cursor: 'pointer',
                            background: isChecked ? 'rgba(34,197,94,0.08)' : 'var(--surface)',
                            border: `1px solid ${isChecked ? '#22c55e' : 'var(--border)'}`,
                            transition: 'all 0.15s',
                          }}>
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleConfirm(selectedItem.id, item)}
                              style={{ width: '14px', height: '14px', accentColor: 'var(--primary)' }}
                            />
                            <span style={{ flex: 1, fontSize: '12px', color: 'var(--text-primary)' }}>
                              {item.item_name}
                              {item.qty > 1 && <span style={{ color: 'var(--text-secondary)' }}> ×{item.qty}</span>}
                            </span>
                            <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>₹{item.price}</span>
                            <span style={{
                              fontSize: '10px', padding: '1px 5px', borderRadius: '6px',
                              background: item.in_stock ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                              color: item.in_stock ? '#16a34a' : '#dc2626',
                            }}>
                              {item.in_stock ? 'In stock' : 'Out'}
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Actions */}
                <div style={{ display: 'flex', gap: '8px' }}>
                  <Button
                    size="sm" variant="primary"
                    loading={resolving}
                    disabled={!(confirmed[selectedItem.id]?.length > 0)}
                    onClick={() => handleResolve('resolved')}
                    style={{ flex: 1 }}
                  >
                    ✓ Confirm Selected
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    loading={resolving}
                    onClick={() => handleResolve('dismissed')}
                  >
                    Dismiss
                  </Button>
                </div>
              </div>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}

function StatBadge({ label, value, color }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1px' }}>
      <span style={{ fontSize: '20px', fontWeight: 800, color }}>{value}</span>
      <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>{label}</span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────
// Main ReconciliationPage (with Night Queue tab)
// ─────────────────────────────────────────────────────────────
export default function ReconciliationPage() {
  const toast = useToast();
  const [activeTab, setActiveTab]   = useState('night'); // 'night' | 'ocr'
  const [loading, setLoading]       = useState(false);
  const [running, setRunning]       = useState(false);
  const [flags, setFlags]           = useState([]);
  const [minutes, setMinutes]       = useState(60);
  const [status, setStatus]         = useState('pending');
  const [searchQ, setSearchQ]       = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [selectedFlag, setSelectedFlag] = useState(null);
  const [saving, setSaving]         = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const data = await getReconFlags(status, 100);
      setFlags(data || []);
    } catch {
      setFlags([]);
      toast.error('Failed to load reconciliation flags');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { if (activeTab === 'ocr') load(); }, [status, activeTab]); // eslint-disable-line react-hooks/exhaustive-deps

  const pendingCount = useMemo(() => (flags || []).filter((f) => f.resolution === 'pending').length, [flags]);

  const run = async () => {
    setRunning(true);
    try {
      const res = await runReconciliation(minutes);
      toast.success(`Reconciliation ran (${res.created} new flags)`);
      await load();
    } catch (e) {
      toast.error(e.message || 'Failed to run reconciliation');
    } finally {
      setRunning(false);
    }
  };

  const doSearch = async (q) => {
    setSearchQ(q);
    if (!q || q.trim().length < 2) { setSearchResults([]); return; }
    try {
      const res = await searchInventory(q.trim());
      setSearchResults(res.items || []);
    } catch { setSearchResults([]); }
  };

  const resolve = async ({ resolution, learn }) => {
    if (!selectedFlag) return;
    setSaving(true);
    try {
      const payload = selectedFlag.payload || {};
      const rawText = payload?.unresolved_items?.[0]?.raw_text || payload?.unresolved_items?.[0]?.name || payload?.raw_text || '';
      await resolveReconFlag(selectedFlag.id, {
        resolution, resolved_by: 'reconciliation_ui',
        learn: !!learn, raw_text: rawText,
        product_id: selectedProduct?.id || null,
      });
      toast.success(`Flag ${resolution}`);
      setSelectedFlag(null); setSelectedProduct(null);
      setSearchQ(''); setSearchResults([]);
      await load();
    } catch (e) {
      toast.error(e.message || 'Failed to resolve flag');
    } finally {
      setSaving(false);
    }
  };

  const tabStyle = (tab) => ({
    padding: '8px 18px', borderRadius: '20px', border: 'none', cursor: 'pointer',
    fontWeight: 600, fontSize: '13px',
    background: activeTab === tab ? 'var(--primary)' : 'transparent',
    color: activeTab === tab ? '#fff' : 'var(--text-secondary)',
    transition: 'all 0.2s',
  });

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '20px', fontWeight: 800 }}>Reconciliation</div>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>
            Resolve low-confidence transactions and OCR mismatches.
          </div>
        </div>
        {/* Tabs */}
        <div style={{ display: 'flex', gap: '4px', background: 'var(--surface)', padding: '4px', borderRadius: '24px', border: '1px solid var(--border)' }}>
          <button style={tabStyle('night')} onClick={() => setActiveTab('night')}>
            🌙 Night Queue
          </button>
          <button style={tabStyle('ocr')} onClick={() => setActiveTab('ocr')}>
            🔍 OCR Flags
          </button>
        </div>
      </div>

      {/* Night Queue Tab */}
      {activeTab === 'night' && <NightQueue />}

      {/* OCR Flags Tab */}
      {activeTab === 'ocr' && (
        <>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Status</div>
            <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}>
              <option value="pending">Pending</option>
              <option value="resolved">Resolved</option>
              <option value="ignored">Ignored</option>
            </select>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Window (min)</div>
            <input type="number" value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} style={{ width: '90px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }} />
            <Button onClick={run} loading={running}>Run now</Button>
            <Button variant="ghost" onClick={load} loading={loading}>Refresh</Button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px' }}>
            <Card shadow>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
                <div style={{ fontSize: '14px', fontWeight: 800 }}>OCR Flags</div>
                <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>{pendingCount} pending</div>
              </div>
              {(flags || []).length === 0 ? (
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No flags.</div>
              ) : (
                <div style={{ display: 'grid', gap: '8px' }}>
                  {(flags || []).map((f) => (
                    <button
                      key={f.id}
                      onClick={() => setSelectedFlag(f)}
                      style={{ textAlign: 'left', padding: '10px 12px', borderRadius: '12px', border: `1px solid ${selectedFlag?.id === f.id ? 'var(--accent)' : 'var(--border)'}`, background: 'var(--surface)', cursor: 'pointer' }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                        <div style={{ fontSize: '13px', fontWeight: 900 }}>{f.flag_type}</div>
                        <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>{f.created_at}</div>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{f.source} • {f.ref_id}</div>
                    </button>
                  ))}
                </div>
              )}
            </Card>

            <Card shadow>
              <div style={{ fontSize: '14px', fontWeight: 800, marginBottom: '10px' }}>Resolve</div>
              {!selectedFlag ? (
                <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>Select a flag to resolve.</div>
              ) : (
                <div style={{ display: 'grid', gap: '10px' }}>
                  <div style={{ padding: '10px 12px', borderRadius: '12px', border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
                    <div style={{ fontSize: '12px', fontWeight: 800, marginBottom: '6px' }}>Details</div>
                    <JsonMini obj={selectedFlag.payload} />
                  </div>
                  <div>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Pick correct product (optional)</div>
                    <input value={searchQ} onChange={(e) => doSearch(e.target.value)} placeholder="Search inventory (name/barcode)..." style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }} />
                    {(searchResults || []).length > 0 && (
                      <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
                        {searchResults.map((r) => (
                          <button key={r.id} onClick={() => setSelectedProduct(r)} style={{ textAlign: 'left', padding: '8px 10px', borderRadius: '12px', border: `1px solid ${selectedProduct?.id === r.id ? 'var(--accent)' : 'var(--border)'}`, background: 'var(--surface)', cursor: 'pointer' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                              <div style={{ fontSize: '12px', fontWeight: 900 }}>{r.emoji || '📦'} {r.name}</div>
                              <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Stock: {r.quantity}</div>
                            </div>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                    <Button onClick={() => resolve({ resolution: 'resolved', learn: false })} loading={saving}>Mark resolved</Button>
                    <Button variant="ghost" onClick={() => resolve({ resolution: 'ignored', learn: false })} loading={saving}>Ignore</Button>
                  </div>
                  <Button variant="ghost" onClick={() => resolve({ resolution: 'resolved', learn: true })} loading={saving} disabled={!selectedProduct}>Resolve + learn mapping</Button>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </div>
  );
}
