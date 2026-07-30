import React, { useMemo, useState, useEffect } from 'react';
import Card from '../components/ui/Card';
import Badge from '../components/ui/Badge';
import Button from '../components/ui/Button';
import { addProduct, bulkUpdateProducts, getCategories, getSnapshot, getSuppliers, update, deleteProduct, updateProduct } from '../api/inventory';
import { useVoice } from '../hooks/useVoice';
import { transcribeInventory } from '../api/voice';
import MicButton from '../components/voice/MicButton';
import { useToast } from '../hooks/useToast';
import { ChevronDown, ChevronRight, Edit, Plus, Trash2, X } from 'lucide-react';

function fmtMoney(v) {
  const n = Number(v || 0);
  return `₹${Number.isFinite(n) ? n.toFixed(2) : '0.00'}`;
}

function marginInfo(purchase, selling) {
  const buy = Number(purchase || 0);
  const sell = Number(selling || 0);
  const margin = sell - buy;
  const pct = sell > 0 ? (margin / sell) * 100 : 0;
  return { buy, sell, margin, pct };
}

function normKey(s) {
  return String(s || '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim()
    .replace(/\s+/g, '_');
}

function defaultVariantGroupId({ name, brand }) {
  const nk = normKey(name);
  const bk = normKey(brand);
  if (!nk) return null;
  return `vg_${bk ? `${bk}_` : ''}${nk}`;
}

function Modal({ open, title, onClose, children, footer }) {
  if (!open) return null;
  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.35)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '24px', zIndex: 50
      }}
      onClick={onClose}
    >
      <div
        className="card card-shadow"
        style={{ width: 'min(720px, 100%)', maxHeight: '85vh', overflow: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <div style={{ fontSize: '16px', fontWeight: 700 }}>{title}</div>
          <button
            onClick={onClose}
            style={{ border: '1px solid var(--border)', background: 'var(--surface)', borderRadius: '10px', height: '36px', width: '36px', display: 'grid', placeItems: 'center', cursor: 'pointer' }}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>
        {children}
        {footer && <div style={{ marginTop: '14px' }}>{footer}</div>}
      </div>
    </div>
  );
}

export default function InventoryPage() {
  const [items, setItems] = useState([]);
  const [search, setSearch] = useState('');
  const [stats, setStats] = useState({ total: 0, low: 0, out: 0, value: 0 });
  const [highlightedRow, setHighlightedRow] = useState(null);
  const [expandedGroups, setExpandedGroups] = useState({});
  const [isNarrow, setIsNarrow] = useState(false);
  const [categories, setCategories] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [selectedIds, setSelectedIds] = useState({});

  const [editing, setEditing] = useState(null);
  const [editForm, setEditForm] = useState({
    name: '',
    category: 'Other',
    brand: '',
    variant_group_id: '',
    variant_label: '',
    unit_type: 'pcs',
    barcode: '',
    supplier_id: '',
    gst_rate: 0,
    discount_pct: 0,
    expiry_date: '',
    min_stock: 5,
    purchase_price: 0,
    selling_price: 0,
    mrp: 0,
    notes: '',
    emoji: '📦',
    desired_qty: null,
  });
  const [savingEdit, setSavingEdit] = useState(false);

  const [adding, setAdding] = useState(false);
  const [addForm, setAddForm] = useState({
    name: '',
    category: 'Other',
    brand: '',
    variant_group_id: '',
    variant_label: '',
    unit_type: 'pcs',
    barcode: '',
    supplier_id: '',
    gst_rate: 0,
    discount_pct: 0,
    expiry_date: '',
    min_stock: 5,
    purchase_price: 0,
    selling_price: 0,
    mrp: 0,
    stock: 0,
    notes: '',
    emoji: '📦',
  });
  const [savingAdd, setSavingAdd] = useState(false);

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkForm, setBulkForm] = useState({
    category: '',
    supplier_id: '',
    gst_rate: '',
    discount_pct: '',
    unit_type: '',
    purchase_price: '',
    selling_price: '',
    min_stock: '',
  });
  const [savingBulk, setSavingBulk] = useState(false);
  
  const voice = useVoice({ parseFn: transcribeInventory, autoStopSeconds: 10 });
  const toast = useToast();

  const fetchStock = async (isPoll = false) => {
    try {
      const data = await getSnapshot();
      let diffFound = false;
      
      setItems(prevItems => {
         if (isPoll && prevItems.length > 0) {
             for (const item of data) {
                 const prev = prevItems.find(p => p.id === item.id);
                 if (prev && prev.current_qty !== item.current_qty) {
                     setHighlightedRow(item.id);
                     setTimeout(() => setHighlightedRow(null), 2000);
                     diffFound = true;
                     break;
                 }
             }
         }
         return data;
      });

      const total = data.length;
      const out = data.filter(i => i.stock_status === 'out').length;
      const low = data.filter(i => i.stock_status === 'low').length;
      const value = data.reduce((sum, i) => sum + (i.selling_price * i.current_qty || 0), 0);
      setStats({ total, low, out, value });
    } catch (e) {
      if (!isPoll) toast.error('Failed to load inventory');
    }
  };

  useEffect(() => {
    fetchStock();
    let int = null;
    const start = () => {
      if (int) return;
      int = setInterval(() => fetchStock(true), 5000);
    };
    const stop = () => {
      if (int) clearInterval(int);
      int = null;
    };
    const onVis = () => (document.visibilityState === 'hidden' ? stop() : start());
    start();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const [cats, sups] = await Promise.all([getCategories(), getSuppliers()]);
        setCategories(cats || []);
        setSuppliers(sups || []);
      } catch {
        // non-blocking
      }
    })();
  }, []);

  useEffect(() => {
    const mql = window.matchMedia('(max-width: 1100px)');
    const onChange = () => setIsNarrow(!!mql.matches);
    onChange();
    if (mql.addEventListener) mql.addEventListener('change', onChange);
    else mql.addListener(onChange);
    return () => {
      if (mql.removeEventListener) mql.removeEventListener('change', onChange);
      else mql.removeListener(onChange);
    };
  }, []);


  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this variant?")) return;
    try {
      await deleteProduct(id);
      toast.success("Item deleted");
      fetchStock();
    } catch (e) {
      toast.error("Failed to delete item");
    }
  };

  const openEdit = (row) => {
    setEditing(row);
    setEditForm({
      name: row.name || '',
      category: row.category || 'Other',
      brand: row.brand || '',
      variant_group_id: row.variant_group_id || defaultVariantGroupId({ name: row.name, brand: row.brand }) || '',
      variant_label: row.variant_label || '',
      unit_type: row.unit_type || 'pcs',
      barcode: row.barcode || '',
      supplier_id: row.supplier_id ?? '',
      gst_rate: Number(row.gst_rate || 0),
      discount_pct: Number(row.discount_pct || 0),
      expiry_date: row.expiry_date || '',
      min_stock: Number(row.min_stock ?? 5),
      purchase_price: Number(row.purchase_price || 0),
      selling_price: Number(row.selling_price || 0),
      mrp: Number(row.mrp || 0),
      notes: row.notes || '',
      emoji: row.emoji || '📦',
      desired_qty: row.current_qty,
    });
  };

  const saveEdit = async () => {
    if (!editing) return;
    setSavingEdit(true);
    try {
      await updateProduct(editing.id, {
        name: editForm.name,
        category: editForm.category,
        brand: editForm.brand,
        variant_group_id: (editForm.variant_group_id || defaultVariantGroupId({ name: editForm.name, brand: editForm.brand }) || null),
        variant_label: (editForm.variant_label || null),
        unit_type: editForm.unit_type,
        barcode: editForm.barcode,
        supplier_id: editForm.supplier_id === '' ? null : Number(editForm.supplier_id),
        gst_rate: Number(editForm.gst_rate || 0),
        discount_pct: Number(editForm.discount_pct || 0),
        expiry_date: editForm.expiry_date || null,
        min_stock: Number(editForm.min_stock ?? 5),
        purchase_price: Number(editForm.purchase_price || 0),
        selling_price: Number(editForm.selling_price || 0),
        mrp: Number(editForm.mrp || 0),
        notes: editForm.notes,
        emoji: (editForm.emoji || '📦').slice(0, 2),
      });

      // Stock set (logged) using delta
      const desired = Number(editForm.desired_qty);
      if (Number.isFinite(desired) && desired !== Number(editing.current_qty || 0)) {
        await update({
          product_id: editing.id,
          qty_change: desired - Number(editing.current_qty || 0),
          action: 'adjust',
          reason: 'Set stock from inventory editor',
        });
      }

      toast.success('Item updated');
      setEditing(null);
      fetchStock();
    } catch (e) {
      toast.error('Failed to update item');
    } finally {
      setSavingEdit(false);
    }
  };

  const openAdd = (prefill = {}) => {
    setAddForm((p) => ({
      ...p,
      ...prefill,
      category: prefill.category || 'Other',
      unit_type: prefill.unit_type || 'pcs',
      emoji: prefill.emoji || '📦',
      variant_group_id: prefill.variant_group_id || defaultVariantGroupId({ name: prefill.name || p.name, brand: prefill.brand || p.brand }) || '',
    }));
    setAdding(true);
  };

  const saveAdd = async () => {
    if (!addForm.name.trim()) {
      toast.error('Product name is required');
      return;
    }
    setSavingAdd(true);
    try {
      await addProduct({
        ...addForm,
        variant_group_id: (addForm.variant_group_id || defaultVariantGroupId({ name: addForm.name, brand: addForm.brand }) || null),
        variant_label: (addForm.variant_label || null),
        supplier_id: addForm.supplier_id === '' ? null : Number(addForm.supplier_id),
      });
      toast.success('Item added');
      setAdding(false);
      fetchStock();
    } catch (e) {
      toast.error('Failed to add item');
    } finally {
      setSavingAdd(false);
    }
  };

  const selectedList = Object.entries(selectedIds).filter(([, v]) => v).map(([k]) => Number(k));

  const toggleSelected = (id) => setSelectedIds((p) => ({ ...p, [id]: !p[id] }));
  const clearSelected = () => setSelectedIds({});
  const selectVisible = () => {
    const m = {};
    for (const it of filtered) m[it.id] = true;
    setSelectedIds(m);
  };

  const saveBulk = async () => {
    if (selectedList.length === 0) {
      toast.error('Select items first');
      return;
    }
    const fields = {};
    for (const [k, v] of Object.entries(bulkForm)) {
      if (v === '' || v === null || typeof v === 'undefined') continue;
      fields[k] = v;
    }
    setSavingBulk(true);
    try {
      await bulkUpdateProducts(selectedList, fields);
      toast.success(`Bulk updated ${selectedList.length} items`);
      setBulkOpen(false);
      clearSelected();
      fetchStock();
    } catch {
      toast.error('Bulk update failed');
    } finally {
      setSavingBulk(false);
    }
  };

  const handleVoiceConfirm = async () => {
    const inv = voice.intent;
    if (!inv) return;
    const rows = (inv.items && inv.items.length)
      ? inv.items
      : (inv.bill?.items?.length ? inv.bill.items : (inv.product_id != null ? [inv] : []));
    if (!rows.length) return;
    try {
      for (const item of rows) {
        const pid = item.product_id ?? item.id;
        if (pid == null) continue;
        const qty = Math.abs(Number(item.qty ?? item.quantity ?? 0));
        if (!qty) continue;
        const delta = item.action === 'add' ? qty : -qty;
        await update({
          product_id: pid,
          qty_change: delta,
          action: 'adjust',
          reason: item.action === 'add' ? `Voice: add ${qty}` : `Voice: deduct ${qty}`,
        });
      }
      toast.success('Inventory updated from voice command');
      voice.reset();
      fetchStock();
    } catch (e) {
      toast.error('Failed to apply voice update');
    }
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return items;
    return items.filter(i => (i.name || '').toLowerCase().includes(q));
  }, [items, search]);

  const grouped = useMemo(() => Object.values(filtered.reduce((acc, i) => {
    const key = (i.variant_group_id || '').trim() ? `vg:${i.variant_group_id}` : `nm:${(i.name || '').toLowerCase()}`;
    if (!acc[key]) {
      acc[key] = { groupName: i.name, emoji: i.emoji, items: [], totalQty: 0, stockStatuses: new Set(), key };
    }
    acc[key].items.push(i);
    acc[key].totalQty += i.current_qty;
    acc[key].stockStatuses.add(i.stock_status);
    return acc;
  }, {})), [filtered]);

  const toggleGroup = (key) => {
    setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div style={{ display: 'grid', gridTemplateColumns: isNarrow ? 'minmax(0, 1fr)' : 'minmax(0, 1fr) 280px', gap: '32px' }}>
      
      <div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px', marginBottom: '24px' }}>
          <Card shadow><div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Total Items</div><div style={{ fontSize: '24px', fontWeight: 'bold' }}>{stats.total}</div></Card>
          <Card shadow><div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Low Stock</div><div style={{ fontSize: '24px', fontWeight: 'bold', color: 'var(--warning)' }}>{stats.low}</div></Card>
          <Card shadow><div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Out of Stock</div><div style={{ fontSize: '24px', fontWeight: 'bold', color: 'var(--danger)' }}>{stats.out}</div></Card>
          <Card shadow><div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Est. Value</div><div style={{ fontSize: '24px', fontWeight: 'bold' }}>{fmtMoney(stats.value)}</div></Card>
        </div>

        <Card shadow>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '16px' }}>
            <input 
               placeholder="Search inventory..." 
               style={{ padding: '10px 12px', width: 'min(420px, 100%)', flex: '1 1 260px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
               value={search}
               onChange={e => setSearch(e.target.value)}
            />
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
              <Button variant="ghost" onClick={selectVisible}>Select visible</Button>
              <Button variant="ghost" onClick={() => setBulkOpen(true)} disabled={selectedList.length === 0}>
                Bulk edit {selectedList.length ? `(${selectedList.length})` : ''}
              </Button>
              <Button variant="ghost" onClick={clearSelected} disabled={selectedList.length === 0}>Clear selection</Button>
              <Button variant="ghost" onClick={() => setSearch('')}>Clear</Button>
              <Button icon={<Plus size={16} />} onClick={() => openAdd()}>Add item</Button>
              <Button onClick={fetchStock}>Refresh</Button>
            </div>
          </div>

          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', minWidth: '980px', borderCollapse: 'separate', borderSpacing: 0, textAlign: 'left' }}>
              <thead>
                <tr style={{ position: 'sticky', top: 0, background: 'var(--surface)', zIndex: 1 }}>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '4%' }}></th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '34%' }}>Item Name</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '10%' }}>Quantity</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '12%' }}>Cost</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '12%' }}>Price</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '14%' }}>Margin</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, width: '10%' }}>Status</th>
                  <th style={{ padding: '12px', color: 'var(--text-secondary)', fontWeight: 500, textAlign: 'right', width: '4%' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
              {grouped.map(g => {
                if (g.items.length === 1) {
                  const i = g.items[0];
                  const { buy, sell, margin, pct } = marginInfo(i.purchase_price, i.selling_price);
                  const marginVariant = margin >= 0 ? 'success' : 'danger';
                  return (
                    <tr key={i.id} style={{ 
                        borderBottom: '1px solid var(--border)',
                        borderLeft: i.stock_status === 'out' ? '3px solid var(--danger)' : i.stock_status === 'low' ? '3px solid var(--warning)' : '3px solid transparent',
                        backgroundColor: highlightedRow === i.id ? 'var(--accent-light)' : 'transparent',
                        transition: 'background-color 0.5s ease-out'
                    }}>
                      <td style={{ padding: '12px' }}>
                        <input type="checkbox" checked={!!selectedIds[i.id]} onChange={() => toggleSelected(i.id)} />
                      </td>
                      <td style={{ padding: '12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <div>{i.emoji} {i.name}</div>
                          {i.variant_label && (
                            <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-secondary)' }}>
                              {i.variant_label}
                            </span>
                          )}
                        </div>
                      </td>
                      <td style={{ padding: '12px' }}>{i.current_qty}</td>
                      <td style={{ padding: '12px' }}>{fmtMoney(buy)}</td>
                      <td style={{ padding: '12px' }}>{fmtMoney(sell)}</td>
                      <td style={{ padding: '12px' }}>
                        <Badge variant={marginVariant}>{fmtMoney(margin)} ({pct.toFixed(1)}%)</Badge>
                      </td>
                      <td style={{ padding: '12px' }}>
                        <Badge variant={i.stock_status === 'out' ? 'danger' : i.stock_status === 'low' ? 'warning' : 'success'}>
                          {i.stock_status === 'out' ? 'Out of Stock' : i.stock_status === 'low' ? 'Low Stock' : 'In Stock'}
                        </Badge>
                      </td>
                      <td style={{ padding: '12px', textAlign: 'right' }}>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(i); }} title="Edit item"><Edit size={16} /></Button>
                          <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(i.id); }} style={{ color: 'var(--danger)', padding: '0 8px' }}><Trash2 size={16} /></Button>
                        </div>
                      </td>
                    </tr>
                  );
                }

                const groupStatus = g.stockStatuses.has('out') ? 'out' : g.stockStatuses.has('low') ? 'low' : 'ok';
                const isExpanded = expandedGroups[g.groupName.toLowerCase()];
                const prices = [...new Set(g.items.map(i => i.selling_price))];
                const buys = [...new Set(g.items.map(i => i.purchase_price || 0))];
                const priceStr = prices.length === 1 ? `₹${prices[0]}` : `₹${Math.min(...prices)} - ₹${Math.max(...prices)}`;
                const buyStr = buys.length === 1 ? `₹${buys[0]}` : `₹${Math.min(...buys)} - ₹${Math.max(...buys)}`;

                return (
                  <React.Fragment key={g.groupName}>
                    <tr onClick={() => toggleGroup(g.groupName.toLowerCase())} style={{ 
                        borderBottom: isExpanded ? 'none' : '1px solid var(--border)',
                        borderLeft: groupStatus === 'out' ? '3px solid var(--danger)' : groupStatus === 'low' ? '3px solid var(--warning)' : '3px solid transparent',
                        cursor: 'pointer',
                        backgroundColor: 'var(--surface-1)'
                    }}>
                      <td style={{ padding: '12px' }} />
                      <td style={{ padding: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                        {g.emoji} {g.groupName} <span style={{ fontSize: '12px', color: 'var(--text-hint)'}}>({g.items.length} variants)</span>
                      </td>
                      <td style={{ padding: '12px', fontWeight: 'bold' }}>{g.totalQty}</td>
                      <td style={{ padding: '12px' }}>{buyStr}</td>
                      <td style={{ padding: '12px' }}>{priceStr}</td>
                      <td style={{ padding: '12px', color: 'var(--text-hint)' }}>—</td>
                      <td style={{ padding: '12px' }}>
                        <Badge variant={groupStatus === 'out' ? 'danger' : groupStatus === 'low' ? 'warning' : 'success'}>
                          {groupStatus === 'out' ? 'Out of Stock' : groupStatus === 'low' ? 'Low Stock' : 'In Stock'}
                        </Badge>
                      </td>
                      <td style={{ padding: '12px' }}></td>
                    </tr>
                    {isExpanded && g.items.map((i, idx) => (
                      (() => {
                        const { buy, sell, margin, pct } = marginInfo(i.purchase_price, i.selling_price);
                        const marginVariant = margin >= 0 ? 'success' : 'danger';
                        return (
                      <tr key={i.id} style={{ 
                          borderBottom: idx === g.items.length - 1 ? '1px solid var(--border)' : '1px dashed var(--border)',
                          borderLeft: i.stock_status === 'out' ? '3px solid var(--danger)' : i.stock_status === 'low' ? '3px solid var(--warning)' : '3px solid transparent',
                          backgroundColor: highlightedRow === i.id ? 'var(--accent-light)' : 'transparent',
                          transition: 'background-color 0.5s ease-out'
                      }}>
                        <td style={{ padding: '12px' }}>
                          <input type="checkbox" checked={!!selectedIds[i.id]} onChange={() => toggleSelected(i.id)} />
                        </td>
                        <td style={{ padding: '12px', paddingLeft: '40px', color: 'var(--text-secondary)' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <div>Variant {idx + 1}</div>
                            {i.variant_label && (
                              <span style={{ fontSize: '11px', padding: '3px 8px', borderRadius: '999px', border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-secondary)' }}>
                                {i.variant_label}
                              </span>
                            )}
                          </div>
                        </td>
                        <td style={{ padding: '12px' }}>{i.current_qty}</td>
                        <td style={{ padding: '12px' }}>{fmtMoney(buy)}</td>
                        <td style={{ padding: '12px' }}>{fmtMoney(sell)}</td>
                        <td style={{ padding: '12px' }}>
                          <Badge variant={marginVariant}>{fmtMoney(margin)} ({pct.toFixed(1)}%)</Badge>
                        </td>
                        <td style={{ padding: '12px' }}>
                          <Badge variant={i.stock_status === 'out' ? 'danger' : i.stock_status === 'low' ? 'warning' : 'success'}>
                            {i.stock_status === 'out' ? 'Out' : i.stock_status === 'low' ? 'Low' : 'OK'}
                          </Badge>
                        </td>
                        <td style={{ padding: '12px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); openEdit(i); }} title="Edit item"><Edit size={16} /></Button>
                            <Button variant="ghost" size="sm" onClick={(e) => { e.stopPropagation(); handleDelete(i.id); }} style={{ color: 'var(--danger)', padding: '0 8px' }}><Trash2 size={16} /></Button>
                          </div>
                        </td>
                      </tr>
                        );
                      })()
                    ))}
                  </React.Fragment>
                );
              })}
              </tbody>
            </table>
          </div>
        </Card>

      </div>

      <div>
        <Card shadow style={{ position: isNarrow ? 'relative' : 'sticky', top: isNarrow ? undefined : 0 }}>
           <h3 style={{ fontSize: '14px', fontWeight: 500, marginBottom: '24px', textAlign: 'center' }}>Voice Assistant</h3>
           <MicButton 
             state={voice.state}
             onToggle={() => voice.state === 'listening' ? voice.stop() : voice.start()}
             transcript={voice.transcript}
             intent={null}
             timeLeft={voice.timeLeft}
             maxSeconds={voice.listeningSeconds}
           />
           
           {voice.state === 'idle' && !voice.intent && (
             <div style={{ marginTop: '24px', fontSize: '12px', color: 'var(--text-secondary)', textAlign: 'center' }}>
               <div style={{ marginBottom: '12px' }}>Hold mic or click to say:</div>
               <div style={{ fontSize: '11px', color: 'var(--text-hint)', marginBottom: '10px' }}>
                 Mic turns off automatically after {voice.listeningSeconds} seconds.
               </div>
               <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                 <div style={{ background: 'var(--surface-2)', padding: '6px 12px', borderRadius: 'var(--radius-xl)' }}>"Add 20kg rice"</div>
                 <div style={{ background: 'var(--surface-2)', padding: '6px 12px', borderRadius: 'var(--radius-xl)' }}>"Deduct 5 bottles oil"</div>
               </div>
             </div>
           )}

           {voice.intent && voice.state === 'done' && (
             <div style={{ marginTop: '24px' }}>
               <div style={{ fontSize: '14px', fontWeight: '500', marginBottom: '8px' }}>Preview Updates</div>
               
               {(voice.intent.items || (voice.intent.bill && voice.intent.bill.items) || (voice.intent.product_id != null ? [voice.intent] : [])).map((it, idx) => (
                 <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '12px', padding: '8px', background: 'var(--surface-2)', borderRadius: 'var(--radius-md)', marginBottom: '8px' }}>
                    <span>{it.product_name || it.name}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <span style={{ fontWeight: 'bold' }}>
                        {it.action === 'add' ? '+' : '−'}{Math.abs(Number(it.qty || it.quantity || 0))}
                      </span>
                    </div>
                 </div>
               ))}

               <div style={{ display: 'flex', gap: '8px', marginTop: '16px' }}>
                 <Button style={{ flex: 1 }} size="sm" onClick={handleVoiceConfirm}>Confirm Update</Button>
                 <Button style={{ flex: 1 }} size="sm" variant="ghost" onClick={voice.reset}>Cancel</Button>
               </div>
             </div>
           )}
        </Card>
      </div>

      <Modal
        open={!!editing}
        title={editing ? `Edit: ${editing.emoji || '📦'} ${editing.name}` : 'Edit item'}
        onClose={() => setEditing(null)}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
            <Button onClick={saveEdit} loading={savingEdit}>Save</Button>
          </div>
        }
      >
        {editing && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Product name</div>
                  <input
                    value={editForm.name}
                    onChange={(e) => setEditForm((p) => ({ ...p, name: e.target.value }))}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                  />
                </div>
                <div style={{ width: '120px' }}>
                  <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Emoji</div>
                  <input
                    value={editForm.emoji}
                    onChange={(e) => setEditForm((p) => ({ ...p, emoji: e.target.value }))}
                    style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
                  />
                </div>
              </div>
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Category</div>
              <select
                value={editForm.category}
                onChange={(e) => setEditForm((p) => ({ ...p, category: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              >
                {(categories?.length ? categories : [{ name: 'Other' }]).map((c) => (
                  <option key={c.id ?? c.name} value={c.name}>{c.name}</option>
                ))}
              </select>
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Brand</div>
              <input
                value={editForm.brand}
                onChange={(e) => setEditForm((p) => ({ ...p, brand: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Unit</div>
              <select
                value={editForm.unit_type}
                onChange={(e) => setEditForm((p) => ({ ...p, unit_type: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              >
                {['pcs', 'kg', 'g', 'L', 'ml'].map((u) => <option key={u} value={u}>{u}</option>)}
              </select>
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Supplier</div>
              <select
                value={editForm.supplier_id === null ? '' : String(editForm.supplier_id ?? '')}
                onChange={(e) => setEditForm((p) => ({ ...p, supplier_id: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              >
                <option value="">—</option>
                {(suppliers || []).map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
              </select>
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Barcode</div>
              <input
                value={editForm.barcode}
                onChange={(e) => setEditForm((p) => ({ ...p, barcode: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Expiry date</div>
              <input
                type="date"
                value={(editForm.expiry_date || '').slice(0, 10)}
                onChange={(e) => setEditForm((p) => ({ ...p, expiry_date: e.target.value }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>GST rate (%)</div>
              <input
                type="number"
                value={editForm.gst_rate}
                onChange={(e) => setEditForm((p) => ({ ...p, gst_rate: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Discount (%)</div>
              <input
                type="number"
                value={editForm.discount_pct}
                onChange={(e) => setEditForm((p) => ({ ...p, discount_pct: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Purchase cost</div>
              <input
                type="number"
                value={editForm.purchase_price}
                onChange={(e) => setEditForm((p) => ({ ...p, purchase_price: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Selling price</div>
              <input
                type="number"
                value={editForm.selling_price}
                onChange={(e) => setEditForm((p) => ({ ...p, selling_price: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>MRP</div>
              <input
                type="number"
                value={editForm.mrp}
                onChange={(e) => setEditForm((p) => ({ ...p, mrp: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Stock quantity</div>
              <input
                type="number"
                value={editForm.desired_qty ?? ''}
                onChange={(e) => setEditForm((p) => ({ ...p, desired_qty: e.target.value === '' ? null : Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Minimum stock alert</div>
              <input
                type="number"
                value={editForm.min_stock}
                onChange={(e) => setEditForm((p) => ({ ...p, min_stock: Number(e.target.value) }))}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div style={{ gridColumn: '1 / -1' }}>
              <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Notes</div>
              <textarea
                value={editForm.notes}
                onChange={(e) => setEditForm((p) => ({ ...p, notes: e.target.value }))}
                rows={3}
                style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
              />
            </div>

            <div style={{ gridColumn: '1 / -1', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', background: 'var(--surface-2)' }}>
              {(() => {
                const { margin, pct } = marginInfo(editForm.purchase_price, editForm.selling_price);
                const variant = margin >= 0 ? 'success' : 'danger';
                return (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>Computed margin</div>
                    <Badge variant={variant}>{fmtMoney(margin)} ({pct.toFixed(1)}%)</Badge>
                  </div>
                );
              })()}
            </div>

            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
              <Button
                variant="ghost"
                onClick={() => openAdd({ name: editForm.name, category: editForm.category, brand: editForm.brand, unit_type: editForm.unit_type })}
                title="Add a new variant (same name, different prices/barcode)"
              >
                Add variant
              </Button>
            </div>
          </div>
        )}
      </Modal>

      <Modal
        open={adding}
        title="Add item"
        onClose={() => setAdding(false)}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <Button variant="ghost" onClick={() => setAdding(false)}>Cancel</Button>
            <Button onClick={saveAdd} loading={savingAdd}>Create</Button>
          </div>
        }
      >
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Product name</div>
            <input
              value={addForm.name}
              onChange={(e) => setAddForm((p) => ({ ...p, name: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Category</div>
            <select
              value={addForm.category}
              onChange={(e) => setAddForm((p) => ({ ...p, category: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              {(categories?.length ? categories : [{ name: 'Other' }]).map((c) => (
                <option key={c.id ?? c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Brand</div>
            <input
              value={addForm.brand}
              onChange={(e) => setAddForm((p) => ({ ...p, brand: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Unit</div>
            <select
              value={addForm.unit_type}
              onChange={(e) => setAddForm((p) => ({ ...p, unit_type: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              {['pcs', 'kg', 'g', 'L', 'ml'].map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Supplier</div>
            <select
              value={addForm.supplier_id === null ? '' : String(addForm.supplier_id ?? '')}
              onChange={(e) => setAddForm((p) => ({ ...p, supplier_id: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              <option value="">—</option>
              {(suppliers || []).map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Barcode</div>
            <input
              value={addForm.barcode}
              onChange={(e) => setAddForm((p) => ({ ...p, barcode: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>GST rate (%)</div>
            <input
              type="number"
              value={addForm.gst_rate}
              onChange={(e) => setAddForm((p) => ({ ...p, gst_rate: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Discount (%)</div>
            <input
              type="number"
              value={addForm.discount_pct}
              onChange={(e) => setAddForm((p) => ({ ...p, discount_pct: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Purchase cost</div>
            <input
              type="number"
              value={addForm.purchase_price}
              onChange={(e) => setAddForm((p) => ({ ...p, purchase_price: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Selling price</div>
            <input
              type="number"
              value={addForm.selling_price}
              onChange={(e) => setAddForm((p) => ({ ...p, selling_price: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Opening stock</div>
            <input
              type="number"
              value={addForm.stock}
              onChange={(e) => setAddForm((p) => ({ ...p, stock: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Minimum stock alert</div>
            <input
              type="number"
              value={addForm.min_stock}
              onChange={(e) => setAddForm((p) => ({ ...p, min_stock: Number(e.target.value) }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Expiry date</div>
            <input
              type="date"
              value={(addForm.expiry_date || '').slice(0, 10)}
              onChange={(e) => setAddForm((p) => ({ ...p, expiry_date: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Notes</div>
            <textarea
              value={addForm.notes}
              onChange={(e) => setAddForm((p) => ({ ...p, notes: e.target.value }))}
              rows={3}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
        </div>
      </Modal>

      <Modal
        open={bulkOpen}
        title={`Bulk edit (${selectedList.length} items)`}
        onClose={() => setBulkOpen(false)}
        footer={
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
            <Button variant="ghost" onClick={() => setBulkOpen(false)}>Cancel</Button>
            <Button onClick={saveBulk} loading={savingBulk}>Apply</Button>
          </div>
        }
      >
        <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
          Only fields you fill will be applied.
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Category</div>
            <select
              value={bulkForm.category}
              onChange={(e) => setBulkForm((p) => ({ ...p, category: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              <option value="">—</option>
              {(categories || []).map((c) => <option key={c.id ?? c.name} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Supplier</div>
            <select
              value={bulkForm.supplier_id}
              onChange={(e) => setBulkForm((p) => ({ ...p, supplier_id: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              <option value="">—</option>
              {(suppliers || []).map((s) => <option key={s.id} value={String(s.id)}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>GST rate (%)</div>
            <input
              type="number"
              placeholder="e.g. 5"
              value={bulkForm.gst_rate}
              onChange={(e) => setBulkForm((p) => ({ ...p, gst_rate: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Discount (%)</div>
            <input
              type="number"
              placeholder="e.g. 2"
              value={bulkForm.discount_pct}
              onChange={(e) => setBulkForm((p) => ({ ...p, discount_pct: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Unit</div>
            <select
              value={bulkForm.unit_type}
              onChange={(e) => setBulkForm((p) => ({ ...p, unit_type: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            >
              <option value="">—</option>
              {['pcs', 'kg', 'g', 'L', 'ml'].map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Min stock</div>
            <input
              type="number"
              placeholder="e.g. 5"
              value={bulkForm.min_stock}
              onChange={(e) => setBulkForm((p) => ({ ...p, min_stock: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Purchase cost</div>
            <input
              type="number"
              placeholder="e.g. 40"
              value={bulkForm.purchase_price}
              onChange={(e) => setBulkForm((p) => ({ ...p, purchase_price: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
          <div>
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '6px' }}>Selling price</div>
            <input
              type="number"
              placeholder="e.g. 50"
              value={bulkForm.selling_price}
              onChange={(e) => setBulkForm((p) => ({ ...p, selling_price: e.target.value }))}
              style={{ width: '100%', padding: '10px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'var(--surface)' }}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}
