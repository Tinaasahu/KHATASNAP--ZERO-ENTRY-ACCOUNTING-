import React, { useState, useRef } from 'react';
import { scanDistributorBill, confirmBillInventoryUpdate } from '../../api/inventory';
import { Upload, FileText, CheckCircle2, AlertTriangle, HelpCircle, Edit2, ChevronDown, ChevronUp, RefreshCw, X, Sparkles, ShieldCheck } from 'lucide-react';

const PROGRESS_STEPS = [
  { id: 1, label: 'Enhancing Document', icon: '📄', desc: 'Deskew, denoising & adaptive contrast' },
  { id: 2, label: 'Reading Text', icon: '🔍', desc: 'PaddleOCR + PP-Structure detection' },
  { id: 3, label: 'Understanding Layout', icon: '📐', desc: 'Extracting product grid & vendor metadata' },
  { id: 4, label: 'Matching Products', icon: '🧩', desc: '6-stage SKU, brand & fuzzy match' },
  { id: 5, label: 'Validating Totals', icon: '📊', desc: 'Financial math & distributor memory check' },
];

export default function BillScannerModal({ open = true, onClose, onSuccess, inline = false }) {
  const [file, setFile] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [scanResult, setScanResult] = useState(null);
  const [items, setItems] = useState([]);
  const [editingIndex, setEditingIndex] = useState(null);
  const [expandedWhy, setExpandedWhy] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');
  const [successMsg, setSuccessMsg] = useState('');
  const fileInputRef = useRef(null);

  if (!inline && !open) return null;

  const handleReset = () => {
    setFile(null);
    setPreviewUrl(null);
    setScanning(false);
    setCurrentStep(0);
    setScanResult(null);
    setItems([]);
    setEditingIndex(null);
    setExpandedWhy({});
    setSubmitting(false);
    setErrorMsg('');
    setSuccessMsg('');
  };

  const handleFileChange = (e) => {
    const selected = e.target.files?.[0];
    if (!selected) return;
    setFile(selected);
    setErrorMsg('');
    if (selected.type.startsWith('image/')) {
      setPreviewUrl(URL.createObjectURL(selected));
    } else {
      setPreviewUrl(null);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    const selected = e.dataTransfer.files?.[0];
    if (!selected) return;
    setFile(selected);
    setErrorMsg('');
    if (selected.type.startsWith('image/')) {
      setPreviewUrl(URL.createObjectURL(selected));
    } else {
      setPreviewUrl(null);
    }
  };

  const startScan = async () => {
    if (!file) {
      setErrorMsg('Please select or upload a distributor invoice file first.');
      return;
    }
    setScanning(true);
    setErrorMsg('');
    setScanResult(null);
    setCurrentStep(1);

    // Simulate multi-step progress animation while request executes
    const stepInterval = setInterval(() => {
      setCurrentStep((prev) => (prev < 4 ? prev + 1 : prev));
    }, 900);

    try {
      const res = await scanDistributorBill(file);
      clearInterval(stepInterval);
      setCurrentStep(5);

      setTimeout(() => {
        setScanning(false);
        setScanResult(res);
        setItems(res.items || []);
      }, 500);

    } catch (err) {
      clearInterval(stepInterval);
      setScanning(false);
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Failed to scan distributor bill.');
    }
  };

  const handleItemChange = (index, field, val) => {
    setItems((prev) => {
      const updated = [...prev];
      const target = { ...updated[index] };
      
      if (field === 'qty' || field === 'purchasePrice' || field === 'mrp') {
        target[field] = Number(val) || 0;
        if (field === 'qty' || field === 'purchasePrice') {
          target.lineTotal = Number((target.qty * target.purchasePrice).toFixed(2));
        }
      } else {
        target[field] = val;
      }

      // If user edits row values, update status to AUTO/REVIEW/EDIT
      target.userEdited = true;
      updated[index] = target;
      return updated;
    });
  };

  const toggleWhy = (idx) => {
    setExpandedWhy((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  const handleConfirmUpdate = async () => {
    if (!scanResult || !items.length) return;
    setSubmitting(true);
    setErrorMsg('');
    setSuccessMsg('');

    const payload = {
      vendor: scanResult.prediction?.vendor || 'Distributor Invoice',
      invoiceNo: scanResult.prediction?.invoiceNo || `INV-${Date.now()}`,
      date: scanResult.prediction?.date || new Date().toISOString().split('T')[0],
      gstin: scanResult.prediction?.gstin || '',
      grandTotal: scanResult.prediction?.grandTotal || items.reduce((s, i) => s + (i.lineTotal || 0), 0),
      items: items.map((it) => ({
        productId: it.productId,
        name: it.name,
        rawName: it.rawName,
        qty: it.qty,
        unit: it.unit || 'pcs',
        purchasePrice: it.purchasePrice,
        mrp: it.mrp,
        batch: it.batch,
        expiry: it.expiry,
        gstPercent: it.gstPercent,
        lineTotal: it.lineTotal,
      })),
    };

    try {
      const res = await confirmBillInventoryUpdate(payload);
      setSubmitting(false);
      setSuccessMsg(`✅ Inventory updated successfully! ${res.updatedItems || items.length} products updated.`);
      
      setTimeout(() => {
        onSuccess?.();
        if (onClose) onClose();
        if (inline) {
          handleReset();
        }
      }, 1200);

    } catch (err) {
      setSubmitting(false);
      setErrorMsg(err?.response?.data?.detail || err?.message || 'Failed to commit inventory changes.');
    }
  };

  const getStatusBadge = (item) => {
    const status = item.status || (item.confidence >= 90 ? 'AUTO_UPDATE' : item.confidence >= 70 ? 'REVIEW' : 'EDIT');
    if (status === 'AUTO_UPDATE') {
      return (
        <span style={{ padding: '4px 10px', borderRadius: '12px', background: '#ECFDF5', color: '#059669', fontSize: '12px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
          🟢 Auto ({item.confidence}%)
        </span>
      );
    }
    if (status === 'REVIEW') {
      return (
        <span style={{ padding: '4px 10px', borderRadius: '12px', background: '#FEF3C7', color: '#D97706', fontSize: '12px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
          🟡 Review ({item.confidence}%)
        </span>
      );
    }
    return (
      <span style={{ padding: '4px 10px', borderRadius: '12px', background: '#FEE2E2', color: '#DC2626', fontSize: '12px', fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
        🔴 Edit ({item.confidence}%)
      </span>
    );
  };

  const containerContent = (
    <div
      className="card card-shadow"
      style={{
        width: inline ? '100%' : 'min(980px, 100%)',
        maxHeight: inline ? 'none' : '92vh',
        overflowY: inline ? 'visible' : 'auto',
        borderRadius: '16px',
        background: 'var(--surface, #ffffff)',
        padding: '24px',
        border: inline ? '1px solid var(--border, #e2e8f0)' : 'none',
        boxShadow: inline ? 'var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.05))' : '0 20px 25px -5px rgba(0,0,0,0.1), 0 8px 10px -6px rgba(0,0,0,0.1)',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '20px', borderBottom: '1px solid var(--border, #e2e8f0)', pb: '16px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <h2 style={{ fontSize: '20px', fontWeight: 800, color: 'var(--text-primary, #0f172a)', margin: 0 }}>
              ⚡ Smart Bill2Inventory™ v2
            </h2>
            <span style={{ background: 'linear-gradient(135deg, #6366F1, #8B5CF6)', color: '#fff', fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '10px' }}>
              Self-Learning AI
            </span>
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary, #64748b)', margin: '4px 0 0 0' }}>
            Instant distributor invoice processing, explainable confidence matching & automatic inventory stock update
          </p>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            style={{ border: '1px solid var(--border, #cbd5e1)', background: 'transparent', borderRadius: '50%', width: '32px', height: '32px', display: 'grid', placeItems: 'center', cursor: 'pointer' }}
          >
            <X size={18} color="#64748b" />
          </button>
        )}
      </div>

      {/* Status / Alert Messages */}
      {errorMsg && (
        <div style={{ background: '#FEF2F2', border: '1px solid #FCA5A5', color: '#991B1B', padding: '12px 16px', borderRadius: '10px', fontSize: '13px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <AlertTriangle size={18} />
          <span>{errorMsg}</span>
        </div>
      )}
      {successMsg && (
        <div style={{ background: '#ECFDF5', border: '1px solid #6EE7B7', color: '#065F46', padding: '12px 16px', borderRadius: '10px', fontSize: '13px', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <CheckCircle2 size={18} />
          <span>{successMsg}</span>
        </div>
      )}

      {/* Screen 1: File Selection & Upload */}
      {!scanResult && !scanning && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            style={{
              border: '2px dashed #a5b4fc', borderRadius: '14px', padding: '40px 20px',
              textAlign: 'center', cursor: 'pointer', background: '#f8fafc',
              transition: 'all 0.2s ease', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px'
            }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/heic,application/pdf"
              onChange={handleFileChange}
              style={{ display: 'none' }}
            />
            <div style={{ width: '56px', height: '56px', borderRadius: '50%', background: '#e0e7ff', display: 'grid', placeItems: 'center' }}>
              <Upload size={28} color="#4f46e5" />
            </div>
            <div>
              <h3 style={{ fontSize: '15px', fontWeight: 700, margin: '0 0 4px 0', color: '#1e293b' }}>
                {file ? file.name : 'Upload Distributor Bill / Invoice'}
              </h3>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary, #64748b)', margin: 0 }}>
                Supports Camera Photo, JPG, PNG, HEIC & PDF formats (Max 25MB)
              </p>
            </div>
            {file && (
              <div style={{ marginTop: '8px', padding: '4px 12px', borderRadius: '8px', background: '#e0e7ff', color: '#4338ca', fontSize: '12px', fontWeight: 600 }}>
                Selected: {(file.size / 1024).toFixed(1)} KB
              </div>
            )}
          </div>

          {previewUrl && (
            <div style={{ textAlign: 'center' }}>
              <p style={{ fontSize: '12px', fontWeight: 600, color: '#475569', marginBottom: '8px' }}>Document Preview:</p>
              <img src={previewUrl} alt="Bill preview" style={{ maxHeight: '200px', borderRadius: '8px', border: '1px solid #cbd5e1' }} />
            </div>
          )}

          <button
            onClick={startScan}
            disabled={!file}
            style={{
              background: file ? 'linear-gradient(135deg, #4F46E5, #7C3AED)' : '#cbd5e1',
              color: '#fff', border: 'none', borderRadius: '12px', padding: '14px 24px',
              fontSize: '15px', fontWeight: 700, cursor: file ? 'pointer' : 'not-allowed',
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
              boxShadow: file ? '0 4px 12px rgba(79, 70, 229, 0.3)' : 'none', transition: 'all 0.2s'
            }}
          >
            <Sparkles size={20} />
            <span>Start 8-Layer AI Bill Scan</span>
          </button>
        </div>
      )}

      {/* Screen 2: Multi-step Live Processing Animation */}
      {scanning && (
        <div style={{ padding: '30px 10px', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '24px' }}>
          <div style={{ width: '64px', height: '64px', borderRadius: '50%', background: '#EEF2FF', display: 'grid', placeItems: 'center' }}>
            <RefreshCw size={32} color="#4F46E5" className="animate-spin" style={{ animation: 'spin 1.5s linear infinite' }} />
          </div>

          <div>
            <h3 style={{ fontSize: '18px', fontWeight: 800, margin: '0 0 6px 0', color: '#0f172a' }}>
              Analyzing Distributor Bill...
            </h3>
            <p style={{ fontSize: '13px', color: '#64748b', margin: 0 }}>
              Layer {currentStep} of 5 — Self-Learning AI Engine active
            </p>
          </div>

          {/* Progress Stepper */}
          <div style={{ width: '100%', maxWidth: '600px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {PROGRESS_STEPS.map((step) => {
              const isActive = step.id === currentStep;
              const isDone = step.id < currentStep;
              return (
                <div
                  key={step.id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '14px', padding: '10px 16px',
                    borderRadius: '10px', border: '1px solid',
                    borderColor: isActive ? '#818CF8' : isDone ? '#A7F3D0' : '#E2E8F0',
                    background: isActive ? '#EEF2FF' : isDone ? '#ECFDF5' : '#F8FAFC',
                    transition: 'all 0.3s ease',
                  }}
                >
                  <span style={{ fontSize: '18px' }}>{step.icon}</span>
                  <div style={{ flex: 1, textAlign: 'left' }}>
                    <div style={{ fontSize: '13px', fontWeight: 700, color: isActive ? '#3730A3' : isDone ? '#065F46' : '#64748B' }}>
                      {step.label}
                    </div>
                    <div style={{ fontSize: '11px', color: '#64748B' }}>{step.desc}</div>
                  </div>
                  {isDone && <CheckCircle2 size={18} color="#10B981" />}
                  {isActive && <div style={{ fontSize: '12px', fontWeight: 600, color: '#4F46E5' }}>Processing...</div>}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Screen 3: Results & Interactive Review Table */}
      {scanResult && !scanning && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          {/* Metadata Summary Banner */}
          <div style={{ background: '#F8FAFC', border: '1px solid #E2E8F0', borderRadius: '12px', padding: '16px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '16px' }}>
            <div>
              <div style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>Vendor</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#0F172A' }}>{scanResult.prediction?.vendor || 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>Invoice No</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#0F172A' }}>{scanResult.prediction?.invoiceNo || 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>Date</div>
              <div style={{ fontSize: '14px', fontWeight: 700, color: '#0F172A' }}>{scanResult.prediction?.date || 'N/A'}</div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>Grand Total</div>
              <div style={{ fontSize: '14px', fontWeight: 800, color: '#4F46E5' }}>₹{scanResult.prediction?.grandTotal || 0}</div>
            </div>
            <div>
              <div style={{ fontSize: '11px', color: '#64748B', fontWeight: 600, textTransform: 'uppercase' }}>AI Scan Time</div>
              <div style={{ fontSize: '13px', fontWeight: 700, color: '#10B981', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                ⚡ {scanResult.prediction?.processingTimeSec || 0.8}s
              </div>
            </div>
          </div>

          {/* Financial Validation Warnings */}
          {scanResult.financialValidation?.anomalies?.length > 0 && (
            <div style={{ background: '#FFFBEB', border: '1px solid #FCD34D', borderRadius: '12px', padding: '14px 16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#B45309', fontWeight: 700, fontSize: '13px', marginBottom: '6px' }}>
                <AlertTriangle size={18} />
                <span>Financial Validation Warnings ({scanResult.financialValidation.anomalies.length})</span>
              </div>
              <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '12px', color: '#92400E' }}>
                {scanResult.financialValidation.anomalies.map((anom, idx) => (
                  <li key={idx}>{anom}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Product Table Header */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ fontSize: '15px', fontWeight: 700, margin: 0, color: '#0F172A' }}>
              Extracted Products ({items.length})
            </h3>
            <div style={{ display: 'flex', gap: '8px', fontSize: '11px' }}>
              <span style={{ padding: '2px 8px', background: '#ECFDF5', color: '#059669', borderRadius: '8px', fontWeight: 600 }}>🟢 Auto ({items.filter(i => i.confidence >= 90).length})</span>
              <span style={{ padding: '2px 8px', background: '#FEF3C7', color: '#D97706', borderRadius: '8px', fontWeight: 600 }}>🟡 Review ({items.filter(i => i.confidence >= 70 && i.confidence < 90).length})</span>
              <span style={{ padding: '2px 8px', background: '#FEE2E2', color: '#DC2626', borderRadius: '8px', fontWeight: 600 }}>🔴 Edit ({items.filter(i => i.confidence < 70).length})</span>
            </div>
          </div>

          {/* Line Items Table */}
          <div style={{ overflowX: 'auto', border: '1px solid #E2E8F0', borderRadius: '12px' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px', textAlign: 'left' }}>
              <thead>
                <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #E2E8F0', color: '#475569', fontWeight: 700 }}>
                  <th style={{ padding: '10px 12px' }}>Product Name</th>
                  <th style={{ padding: '10px 8px', width: '70px' }}>Qty</th>
                  <th style={{ padding: '10px 8px', width: '90px' }}>Price (₹)</th>
                  <th style={{ padding: '10px 8px', width: '90px' }}>MRP (₹)</th>
                  <th style={{ padding: '10px 8px', width: '110px' }}>Batch / Exp</th>
                  <th style={{ padding: '10px 12px' }}>Confidence</th>
                  <th style={{ padding: '10px 8px', textAlign: 'center', width: '90px' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, idx) => {
                  const isEditing = editingIndex === idx || it.confidence < 70;
                  return (
                    <React.Fragment key={idx}>
                      <tr style={{ borderBottom: '1px solid #F1F5F9', background: idx % 2 === 0 ? '#FFFFFF' : '#FAFAFA' }}>
                        {/* Name */}
                        <td style={{ padding: '10px 12px' }}>
                          {isEditing ? (
                            <input
                              type="text"
                              value={it.name}
                              onChange={(e) => handleItemChange(idx, 'name', e.target.value)}
                              style={{ width: '100%', padding: '6px 8px', border: '1px solid #818CF8', borderRadius: '6px', fontSize: '12px', fontWeight: 600 }}
                            />
                          ) : (
                            <div>
                              <div style={{ fontWeight: 700, color: '#0F172A' }}>{it.name}</div>
                              {it.rawName && it.rawName !== it.name && (
                                <div style={{ fontSize: '10px', color: '#94A3B8' }}>OCR: "{it.rawName}"</div>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Qty */}
                        <td style={{ padding: '10px 8px' }}>
                          {isEditing ? (
                            <input
                              type="number"
                              value={it.qty}
                              onChange={(e) => handleItemChange(idx, 'qty', e.target.value)}
                              style={{ width: '60px', padding: '6px', border: '1px solid #818CF8', borderRadius: '6px', fontSize: '12px' }}
                            />
                          ) : (
                            <span style={{ fontWeight: 600 }}>{it.qty} {it.unit || 'pcs'}</span>
                          )}
                        </td>

                        {/* Purchase Price */}
                        <td style={{ padding: '10px 8px' }}>
                          {isEditing ? (
                            <input
                              type="number"
                              value={it.purchasePrice}
                              onChange={(e) => handleItemChange(idx, 'purchasePrice', e.target.value)}
                              style={{ width: '75px', padding: '6px', border: '1px solid #818CF8', borderRadius: '6px', fontSize: '12px' }}
                            />
                          ) : (
                            <span style={{ fontWeight: 600, color: '#0F172A' }}>₹{it.purchasePrice}</span>
                          )}
                        </td>

                        {/* MRP */}
                        <td style={{ padding: '10px 8px' }}>
                          {isEditing ? (
                            <input
                              type="number"
                              value={it.mrp}
                              onChange={(e) => handleItemChange(idx, 'mrp', e.target.value)}
                              style={{ width: '75px', padding: '6px', border: '1px solid #818CF8', borderRadius: '6px', fontSize: '12px' }}
                            />
                          ) : (
                            <span>₹{it.mrp}</span>
                          )}
                        </td>

                        {/* Batch / Expiry */}
                        <td style={{ padding: '10px 8px' }}>
                          {isEditing ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                              <input
                                type="text"
                                placeholder="Batch"
                                value={it.batch || ''}
                                onChange={(e) => handleItemChange(idx, 'batch', e.target.value)}
                                style={{ width: '100px', padding: '4px 6px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '11px' }}
                              />
                              <input
                                type="date"
                                value={it.expiry || ''}
                                onChange={(e) => handleItemChange(idx, 'expiry', e.target.value)}
                                style={{ width: '100px', padding: '4px 6px', border: '1px solid #cbd5e1', borderRadius: '4px', fontSize: '11px' }}
                              />
                            </div>
                          ) : (
                            <div>
                              <div style={{ fontSize: '11px', color: '#475569' }}>{it.batch || '—'}</div>
                              <div style={{ fontSize: '10px', color: '#94A3B8' }}>{it.expiry || 'No Exp'}</div>
                            </div>
                          )}
                        </td>

                        {/* Confidence */}
                        <td style={{ padding: '10px 12px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            {getStatusBadge(it)}
                            <button
                              onClick={() => toggleWhy(idx)}
                              style={{ border: 'none', background: 'transparent', cursor: 'pointer', padding: '2px', color: '#64748B' }}
                              title="Why? Click to see 5-signal breakdown"
                            >
                              <HelpCircle size={15} />
                            </button>
                          </div>
                        </td>

                        {/* Actions */}
                        <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                          <button
                            onClick={() => setEditingIndex(editingIndex === idx ? null : idx)}
                            style={{
                              border: '1px solid #CBD5E1', background: editingIndex === idx ? '#EEF2FF' : '#FFFFFF',
                              borderRadius: '6px', padding: '4px 8px', cursor: 'pointer', fontSize: '11px',
                              display: 'inline-flex', alignItems: 'center', gap: '4px', color: '#334155'
                            }}
                          >
                            <Edit2 size={13} />
                            <span>{editingIndex === idx ? 'Done' : 'Edit'}</span>
                          </button>
                        </td>
                      </tr>

                      {/* Explainable Why? Popover Row */}
                      {expandedWhy[idx] && (
                        <tr style={{ background: '#F8FAFC', borderBottom: '1px solid #E2E8F0' }}>
                          <td colSpan={7} style={{ padding: '10px 16px' }}>
                            <div style={{ fontSize: '11px', color: '#334155' }}>
                              <strong style={{ color: '#4F46E5' }}>Explainable Score Breakdown:</strong>
                              <ul style={{ margin: '4px 0 0 0', paddingLeft: '18px' }}>
                                {(it.reason || []).map((r, rIdx) => (
                                  <li key={rIdx}>{r}</li>
                                ))}
                              </ul>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Confirm Actions CTA */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', marginTop: '10px' }}>
            <button
              onClick={handleReset}
              disabled={submitting}
              style={{
                border: '1px solid var(--border, #cbd5e1)', background: 'var(--surface-2, #f8fafc)', color: 'var(--text-secondary, #475569)',
                borderRadius: '10px', padding: '10px 16px', fontSize: '13px', fontWeight: 600, cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: '6px'
              }}
            >
              <RefreshCw size={14} />
              <span>Upload Different Bill</span>
            </button>
            <div style={{ display: 'flex', gap: '12px' }}>
              {onClose && (
                <button
                  onClick={onClose}
                  disabled={submitting}
                  style={{
                    border: '1px solid #CBD5E1', background: '#FFFFFF', color: '#475569',
                    borderRadius: '10px', padding: '10px 18px', fontSize: '14px', fontWeight: 600, cursor: 'pointer'
                  }}
                >
                  Cancel
                </button>
              )}
              <button
                onClick={handleConfirmUpdate}
                disabled={submitting || items.length === 0}
                style={{
                  background: 'linear-gradient(135deg, #10B981, #059669)', color: '#FFFFFF',
                  border: 'none', borderRadius: '10px', padding: '10px 24px', fontSize: '14px', fontWeight: 700,
                  cursor: submitting ? 'wait' : 'pointer', display: 'flex', alignItems: 'center', gap: '8px',
                  boxShadow: '0 4px 12px rgba(16, 185, 129, 0.25)'
                }}
              >
                <ShieldCheck size={18} />
                <span>{submitting ? 'Updating Stock...' : `Confirm & Update Inventory (${items.length})`}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  if (inline) {
    return <div style={{ width: '100%' }}>{containerContent}</div>;
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, background: 'rgba(15, 23, 42, 0.65)',
        backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '16px', zIndex: 1000,
      }}
      onClick={onClose}
    >
      {containerContent}
    </div>
  );
}
