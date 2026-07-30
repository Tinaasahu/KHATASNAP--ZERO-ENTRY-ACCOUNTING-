import React, { useEffect, useMemo, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { useToast } from '../hooks/useToast';
import { getReconFlags, resolveReconFlag, runReconciliation } from '../api/reconciliation';
import { searchInventory } from '../api/inventory';

function JsonMini({ obj }) {
  return (
    <pre style={{ margin: 0, whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '11px', color: 'var(--text-secondary)' }}>
      {JSON.stringify(obj, null, 2)}
    </pre>
  );
}

export default function ReconciliationPage() {
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [flags, setFlags] = useState([]);
  const [minutes, setMinutes] = useState(60);
  const [status, setStatus] = useState('pending');

  const [searchQ, setSearchQ] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [selectedFlag, setSelectedFlag] = useState(null);
  const [saving, setSaving] = useState(false);

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

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

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
    if (!q || q.trim().length < 2) {
      setSearchResults([]);
      return;
    }
    try {
      const res = await searchInventory(q.trim());
      setSearchResults(res.items || []);
    } catch {
      setSearchResults([]);
    }
  };

  const resolve = async ({ resolution, learn }) => {
    if (!selectedFlag) return;
    setSaving(true);
    try {
      const payload = selectedFlag.payload || {};
      // Try best-effort to learn from an unresolved OCR line
      const rawText =
        payload?.unresolved_items?.[0]?.raw_text ||
        payload?.unresolved_items?.[0]?.name ||
        payload?.raw_text ||
        '';
      await resolveReconFlag(selectedFlag.id, {
        resolution,
        resolved_by: 'reconciliation_ui',
        learn: !!learn,
        raw_text: rawText,
        product_id: selectedProduct?.id || null,
      });
      toast.success(`Flag ${resolution}`);
      setSelectedFlag(null);
      setSelectedProduct(null);
      setSearchQ('');
      setSearchResults([]);
      await load();
    } catch (e) {
      toast.error(e.message || 'Failed to resolve flag');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'grid', gap: '12px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '12px' }}>
        <div>
          <div style={{ fontSize: '20px', fontWeight: 800 }}>Reconciliation</div>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>
            Detect and resolve mismatches. Learn from fixes for better OCR mapping.
          </div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Status</div>
          <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}>
            <option value="pending">Pending</option>
            <option value="resolved">Resolved</option>
            <option value="ignored">Ignored</option>
          </select>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Window (min)</div>
          <input
            type="number"
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            style={{ width: '90px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
          />
          <Button onClick={run} loading={running}>Run now</Button>
          <Button variant="ghost" onClick={load} loading={loading}>Refresh</Button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Flags</div>
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
                  style={{
                    textAlign: 'left',
                    padding: '10px 12px',
                    borderRadius: '12px',
                    border: `1px solid ${selectedFlag?.id === f.id ? 'var(--accent)' : 'var(--border)'}`,
                    background: 'var(--surface)',
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 900 }}>{f.flag_type}</div>
                    <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>{f.created_at}</div>
                  </div>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                    {f.source} • {f.ref_id}
                  </div>
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
                <input
                  value={searchQ}
                  onChange={(e) => doSearch(e.target.value)}
                  placeholder="Search inventory (name/barcode)..."
                  style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                />
                {(searchResults || []).length > 0 && (
                  <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
                    {searchResults.map((r) => (
                      <button
                        key={r.id}
                        onClick={() => setSelectedProduct(r)}
                        style={{
                          textAlign: 'left',
                          padding: '8px 10px',
                          borderRadius: '12px',
                          border: `1px solid ${selectedProduct?.id === r.id ? 'var(--accent)' : 'var(--border)'}`,
                          background: 'var(--surface)',
                          cursor: 'pointer',
                        }}
                      >
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
                <Button onClick={() => resolve({ resolution: 'resolved', learn: false })} loading={saving}>
                  Mark resolved
                </Button>
                <Button variant="ghost" onClick={() => resolve({ resolution: 'ignored', learn: false })} loading={saving}>
                  Ignore
                </Button>
              </div>
              <Button
                variant="ghost"
                onClick={() => resolve({ resolution: 'resolved', learn: true })}
                loading={saving}
                disabled={!selectedProduct}
              >
                Resolve + learn mapping
              </Button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}

