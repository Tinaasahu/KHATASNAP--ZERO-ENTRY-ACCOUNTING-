import React, { useEffect, useState } from 'react';
import Card from '../components/ui/Card';
import Button from '../components/ui/Button';
import { useToast } from '../hooks/useToast';
import { getDailyProfitLoss, getShopkeeperDashboard, getShopkeeperInsights } from '../api/dashboard';
import { useNavigate } from 'react-router-dom';
import { getInventoryAlerts, searchInventory, update as updateStock } from '../api/inventory';

function fmtMoney(v) {
  const n = Number(v || 0);
  return `₹${Number.isFinite(n) ? n.toFixed(2) : '0.00'}`;
}

function MiniBarChart({ data, valueKey = 'revenue', labelKey = 'day', height = 120 }) {
  const vals = (data || []).map((d) => Number(d[valueKey] || 0));
  const max = Math.max(1, ...vals);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.max(1, vals.length)}, 1fr)`, gap: '6px', alignItems: 'end', height }}>
      {(data || []).map((d) => {
        const v = Number(d[valueKey] || 0);
        const h = Math.max(2, Math.round((v / max) * (height - 20)));
        return (
          <div key={String(d[labelKey])} title={`${d[labelKey]} • ${fmtMoney(v)}`} style={{ display: 'grid', gap: '6px', alignItems: 'end' }}>
            <div style={{ height: `${h}px`, borderRadius: '10px', background: 'linear-gradient(180deg, var(--accent) 0%, rgba(99,102,241,0.35) 100%)' }} />
          </div>
        );
      })}
    </div>
  );
}

function SimpleLine({ data, xKey = 'month', yKey = 'revenue', height = 120 }) {
  const pts = (data || []).map((d) => ({ x: String(d[xKey]), y: Number(d[yKey] || 0) }));
  const maxY = Math.max(1, ...pts.map((p) => p.y));
  const w = 520;
  const h = height;
  const pad = 12;
  const n = pts.length;
  const xy = pts.map((p, i) => {
    const x = pad + (n <= 1 ? 0 : (i / (n - 1)) * (w - pad * 2));
    const y = h - pad - (p.y / maxY) * (h - pad * 2);
    return { x, y, label: p.x, value: p.y };
  });
  const d = xy.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
  return (
    <div style={{ width: '100%', overflowX: 'auto' }}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }}>
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2.5" />
        {xy.map((p) => (
          <circle key={p.label} cx={p.x} cy={p.y} r="3.5" fill="var(--accent)" />
        ))}
      </svg>
    </div>
  );
}

export default function ShopkeeperDashboardPage() {
  const toast = useToast();
  const nav = useNavigate();
  const [days, setDays] = useState(30);
  const [loading, setLoading] = useState(false);
  const [dash, setDash] = useState(null);
  const [daily, setDaily] = useState(null);
  const [insights, setInsights] = useState(null);
  const [alerts, setAlerts] = useState(null);

  const [qaOpen, setQaOpen] = useState(false);
  const [qaQuery, setQaQuery] = useState('');
  const [qaResults, setQaResults] = useState([]);
  const [qaPick, setQaPick] = useState(null);
  const [qaDelta, setQaDelta] = useState(0);
  const [qaSaving, setQaSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const [data, dailyData, insightsData] = await Promise.all([
        getShopkeeperDashboard(days),
        getDailyProfitLoss(days),
        getShopkeeperInsights(days),
      ]);
      setDash(data);
      setDaily(dailyData);
      setInsights(insightsData);
      try {
        const a = await getInventoryAlerts(days);
        setAlerts(a);
      } catch {
        setAlerts(null);
      }
    } catch (e) {
      setDash(null);
      setDaily(null);
      setInsights(null);
      toast.error('Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days]);

  const totals = dash?.totals || {};
  const pv = insights?.purchase_vs_sales || {};
  const lowStock = alerts?.low_stock || insights?.low_stock_alerts || [];
  const expiringSoon = alerts?.expiring_soon || [];

  const runSearch = async (q) => {
    setQaQuery(q);
    if (!q || q.trim().length < 2) {
      setQaResults([]);
      return;
    }
    try {
      const res = await searchInventory(q.trim());
      setQaResults(res.items || []);
    } catch {
      setQaResults([]);
    }
  };

  const applyQuickAdjust = async () => {
    if (!qaPick) return;
    const delta = Number(qaDelta || 0);
    if (!Number.isFinite(delta) || delta === 0) {
      toast.error('Enter a quantity change (e.g. +5 or -2)');
      return;
    }
    setQaSaving(true);
    try {
      await updateStock({ product_id: qaPick.id, qty_change: delta, action: 'adjust', reason: 'Quick action from dashboard' });
      toast.success('Stock updated');
      setQaOpen(false);
      setQaPick(null);
      setQaDelta(0);
      setQaQuery('');
      setQaResults([]);
      load();
    } catch {
      toast.error('Failed to update stock');
    } finally {
      setQaSaving(false);
    }
  };

  return (
    <div style={{ display: 'grid', gap: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: '12px' }}>
        <div>
          <div style={{ fontSize: '20px', fontWeight: 700 }}>Shopkeeper Dashboard</div>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>
            Profit, loss, efficiency, and top items
          </div>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Window</div>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <Button onClick={load} loading={loading}>Refresh</Button>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.6fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Daily revenue</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Last {days} days</div>
          </div>
          <MiniBarChart data={insights?.daily || []} valueKey="revenue" labelKey="day" />
        </Card>
        <Card shadow>
          <div style={{ fontSize: '14px', fontWeight: 800, marginBottom: '10px' }}>Quick actions</div>
          <div style={{ display: 'grid', gap: '8px' }}>
            <Button onClick={() => nav('/inventory')}>Open Inventory</Button>
            <Button variant="ghost" onClick={() => nav('/inventory')}>Add items / variants</Button>
            <Button variant="ghost" onClick={() => setQaOpen(true)}>Update stock (quick)</Button>
            <Button variant="ghost" onClick={() => document.getElementById('reports')?.scrollIntoView({ behavior: 'smooth' })}>
              View reports
            </Button>
          </div>
          {qaOpen && (
            <div style={{ marginTop: '12px', paddingTop: '12px', borderTop: '1px solid var(--border)' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Search item</div>
              <input
                value={qaQuery}
                onChange={(e) => runSearch(e.target.value)}
                placeholder="Type 2+ letters..."
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
              {qaResults.length > 0 && (
                <div style={{ marginTop: '8px', display: 'grid', gap: '6px' }}>
                  {qaResults.map((r) => (
                    <button
                      key={r.id}
                      onClick={() => setQaPick(r)}
                      style={{
                        textAlign: 'left',
                        padding: '8px 10px',
                        borderRadius: '12px',
                        border: `1px solid ${qaPick?.id === r.id ? 'var(--accent)' : 'var(--border)'}`,
                        background: 'var(--surface)',
                        cursor: 'pointer',
                      }}
                    >
                      <div style={{ fontSize: '13px', fontWeight: 800 }}>{r.emoji || '📦'} {r.name}</div>
                      <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Stock: {r.quantity}</div>
                    </button>
                  ))}
                </div>
              )}
              {qaPick && (
                <div style={{ marginTop: '10px', display: 'grid', gap: '8px' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Qty change</div>
                  <input
                    type="number"
                    value={qaDelta}
                    onChange={(e) => setQaDelta(Number(e.target.value))}
                    placeholder="+5 or -2"
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                  />
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <Button onClick={applyQuickAdjust} loading={qaSaving} style={{ flex: 1 }}>Apply</Button>
                    <Button variant="ghost" onClick={() => setQaOpen(false)} style={{ flex: 1 }}>Close</Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Expiry tracking</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Expiring soon</div>
          </div>
          {expiringSoon.length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              No expiring items found for this window. (Add expiry dates in Inventory.)
              <div style={{ marginTop: '10px' }}>
                <Button variant="ghost" onClick={() => nav('/inventory')}>Update expiry dates</Button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: '8px' }}>
              {expiringSoon.slice(0, 10).map((it) => (
                <div key={it.id} style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 900 }}>{it.emoji || '📦'} {it.name}</div>
                    <div style={{ fontSize: '12px', fontWeight: 800 }}>{it.expiry_date}</div>
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>
                    Stock: {it.current_qty} • Min: {it.min_stock} • {it.category}
                  </div>
                </div>
              ))}
              <Button variant="ghost" onClick={() => nav('/inventory')}>Review in Inventory</Button>
            </div>
          )}
        </Card>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Margin insights</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>From top sellers</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Profit per unit</div>
              <div style={{ fontSize: '18px', fontWeight: 900 }}>{fmtMoney(totals.profit_per_unit)}</div>
            </div>
            <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Revenue per unit</div>
              <div style={{ fontSize: '18px', fontWeight: 900 }}>{fmtMoney(totals.revenue_per_unit)}</div>
            </div>
          </div>
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <Card shadow>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Revenue</div>
          <div style={{ fontSize: '26px', fontWeight: 800 }}>₹{(totals.revenue || 0).toFixed(2)}</div>
        </Card>
        <Card shadow>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Cost</div>
          <div style={{ fontSize: '26px', fontWeight: 800 }}>₹{(totals.cost || 0).toFixed(2)}</div>
        </Card>
        <Card shadow>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Profit / Loss</div>
          <div style={{ fontSize: '26px', fontWeight: 800, color: (totals.profit || 0) >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            ₹{(totals.profit || 0).toFixed(2)}
          </div>
        </Card>
        <Card shadow>
          <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Profit Margin</div>
          <div style={{ fontSize: '26px', fontWeight: 800 }}>{(totals.profit_margin_pct || 0).toFixed(2)}%</div>
        </Card>
      </div>

      <div id="reports" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Purchase vs Sales</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Window: {days} days</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Sales revenue</div>
              <div style={{ fontSize: '18px', fontWeight: 900 }}>{fmtMoney(pv.sales_revenue)}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Units sold: {(pv.sold_units || 0).toFixed?.(0) ?? pv.sold_units}</div>
            </div>
            <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Purchases (restock cost)</div>
              <div style={{ fontSize: '18px', fontWeight: 900 }}>{fmtMoney(pv.purchase_cost)}</div>
              <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Units restocked: {(pv.restock_units || 0).toFixed?.(0) ?? pv.restock_units}</div>
            </div>
          </div>
          <div style={{ marginTop: '10px', fontSize: '12px', color: 'var(--text-hint)' }}>
            Profit proxy (sales): {fmtMoney(pv.sales_profit)}
          </div>
        </Card>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '10px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Monthly growth trend</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Last 12 months</div>
          </div>
          <SimpleLine data={(insights?.monthly_growth || []).slice(-12)} xKey="month" yKey="revenue" />
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 700 }}>Most selling items</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Units sold</div>
          </div>
          {(dash?.top_selling_items || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              No sales yet for this window.
            </div>
          ) : (
            (dash.top_selling_items || []).map((it) => (
              <div key={it.product_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', marginBottom: '10px' }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <div style={{ fontSize: '18px' }}>{it.emoji || '📦'}</div>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700 }}>{it.name}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>
                      ₹{it.purchase_price} → ₹{it.selling_price} • Margin {it.profit_margin_pct}%
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>{it.sold_qty}</div>
                  <div style={{ fontSize: '12px', fontWeight: 700 }}>₹{(it.profit || 0).toFixed(2)}</div>
                </div>
              </div>
            ))
          )}
        </Card>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 700 }}>Highest profit items</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Profit</div>
          </div>
          {(dash?.top_profit_items || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
              No profit data yet for this window.
            </div>
          ) : (
            (dash.top_profit_items || []).map((it) => (
              <div key={it.product_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', marginBottom: '10px' }}>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <div style={{ fontSize: '18px' }}>{it.emoji || '📦'}</div>
                  <div>
                    <div style={{ fontSize: '13px', fontWeight: 700 }}>{it.name}</div>
                    <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>
                      Sold {it.sold_qty} • Margin {it.profit_margin_pct}%
                    </div>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>₹{(it.profit || 0).toFixed(2)}</div>
                  <div style={{ fontSize: '12px', fontWeight: 700 }}>₹{it.purchase_price} → ₹{it.selling_price}</div>
                </div>
              </div>
            ))
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Low-stock alerts</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Top 25</div>
          </div>
          {(lowStock || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No low-stock items.</div>
          ) : (
            (lowStock || []).map((it) => (
              <div key={it.id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', marginBottom: '10px' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 800 }}>{it.emoji || '📦'} {it.name}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>{it.category}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', fontWeight: 900, color: Number(it.current_qty) === 0 ? 'var(--danger)' : 'var(--warning)' }}>
                    {it.current_qty}
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Min: {it.min_stock}</div>
                </div>
              </div>
            ))
          )}
        </Card>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Recent transactions</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Stock logs</div>
          </div>
          {(insights?.recent_transactions || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No transactions yet.</div>
          ) : (
            <div style={{ display: 'grid', gap: '8px' }}>
              {(insights.recent_transactions || []).slice(0, 12).map((t) => (
                <div key={t.transaction_id} style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '10px' }}>
                    <div style={{ fontSize: '13px', fontWeight: 800 }}>
                      {t.action_type?.toUpperCase?.() || t.action_type} • {t.product_name || '—'}
                    </div>
                    <div style={{ fontSize: '13px', fontWeight: 900, color: Number(t.qty_change) < 0 ? 'var(--danger)' : 'var(--success)' }}>
                      {Number(t.qty_change) > 0 ? '+' : ''}{t.qty_change}
                    </div>
                  </div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)', marginTop: '2px' }}>
                    {t.created_at} • {t.source}{t.reason ? ` • ${t.reason}` : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Category-wise performance</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Revenue • Profit</div>
          </div>
          {(insights?.category_performance || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No category data yet.</div>
          ) : (
            (insights.category_performance || []).slice(0, 10).map((c) => (
              <div key={c.category} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', marginBottom: '10px' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 900 }}>{c.category}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>Sold {c.sold_qty} • Margin {c.margin_pct}%</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', fontWeight: 900 }}>{fmtMoney(c.revenue)}</div>
                  <div style={{ fontSize: '12px', fontWeight: 900, color: Number(c.profit) >= 0 ? 'var(--success)' : 'var(--danger)' }}>{fmtMoney(c.profit)}</div>
                </div>
              </div>
            ))
          )}
        </Card>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
            <div style={{ fontSize: '14px', fontWeight: 800 }}>Supplier insights</div>
            <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Sales • Restock</div>
          </div>
          {(insights?.supplier_insights || []).length === 0 ? (
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>No supplier data yet.</div>
          ) : (
            (insights.supplier_insights || []).slice(0, 10).map((s) => (
              <div key={s.supplier_id} style={{ display: 'flex', justifyContent: 'space-between', padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', marginBottom: '10px' }}>
                <div>
                  <div style={{ fontSize: '13px', fontWeight: 900 }}>{s.supplier_name}</div>
                  <div style={{ fontSize: '11px', color: 'var(--text-hint)' }}>{s.products_count} products • Restocked {s.restock_units}</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: '12px', fontWeight: 900 }}>{fmtMoney(s.sales_revenue)}</div>
                  <div style={{ fontSize: '12px', fontWeight: 900, color: Number(s.sales_profit) >= 0 ? 'var(--success)' : 'var(--danger)' }}>{fmtMoney(s.sales_profit)}</div>
                </div>
              </div>
            ))
          )}
        </Card>
      </div>

      <Card shadow>
        <div style={{ fontSize: '14px', fontWeight: 700, marginBottom: '8px' }}>Efficiency</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '12px' }}>
          <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Units sold</div>
            <div style={{ fontSize: '18px', fontWeight: 800 }}>{(totals.units_sold || 0).toFixed(0)}</div>
          </div>
          <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Revenue / unit</div>
            <div style={{ fontSize: '18px', fontWeight: 800 }}>₹{(totals.revenue_per_unit || 0).toFixed(2)}</div>
          </div>
          <div style={{ padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Profit / unit</div>
            <div style={{ fontSize: '18px', fontWeight: 800 }}>₹{(totals.profit_per_unit || 0).toFixed(2)}</div>
          </div>
        </div>
      </Card>

      <Card shadow>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: '12px' }}>
          <div style={{ fontSize: '14px', fontWeight: 700 }}>Day-wise Profit & Loss</div>
          <div style={{ fontSize: '12px', color: 'var(--text-hint)' }}>Date-wise (with time captured in logs)</div>
        </div>

        {(!daily || !daily.days || daily.days.length === 0) ? (
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>
            No sales yet for this window.
          </div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Date</th>
                <th style={{ textAlign: 'right', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Units</th>
                <th style={{ textAlign: 'right', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Revenue</th>
                <th style={{ textAlign: 'right', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Cost</th>
                <th style={{ textAlign: 'right', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Profit</th>
                <th style={{ textAlign: 'right', padding: '10px', color: 'var(--text-secondary)', fontWeight: 600 }}>Margin</th>
              </tr>
            </thead>
            <tbody>
              {(daily.days || []).map((d) => (
                <tr key={d.day} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '10px', fontWeight: 700 }}>{d.day}</td>
                  <td style={{ padding: '10px', textAlign: 'right' }}>{(d.units_sold || 0).toFixed(0)}</td>
                  <td style={{ padding: '10px', textAlign: 'right' }}>₹{(d.revenue || 0).toFixed(2)}</td>
                  <td style={{ padding: '10px', textAlign: 'right' }}>₹{(d.cost || 0).toFixed(2)}</td>
                  <td style={{ padding: '10px', textAlign: 'right', fontWeight: 800, color: (d.profit || 0) >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                    ₹{(d.profit || 0).toFixed(2)}
                  </td>
                  <td style={{ padding: '10px', textAlign: 'right' }}>{(d.profit_margin_pct || 0).toFixed(2)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}

