// KhataSnap — shared JS utilities

// Auto-detect API base from current page origin (works on any host/port)
const API = window.location.origin + '/api';

async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options
    });
    setServerStatus(true);
    return await res.json();
  } catch (e) {
    setServerStatus(false);
    toast('Cannot reach server', 'err');
    return null;
  }
}

function setServerStatus(online) {
  const dot = document.getElementById('sdot');
  const lbl = document.getElementById('slabel');
  if (!dot) return;
  dot.className = 'sdot' + (online ? '' : ' offline');
  if (lbl) lbl.textContent = online ? 'Server online' : 'Offline';
}

function toast(msg, type = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.className = `toast ${type} show`;
  setTimeout(() => el.classList.remove('show'), 3000);
}

function open_(id) { document.getElementById(id).classList.add('open'); }
function close_(id) { document.getElementById(id).classList.remove('open'); }

function x(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function rupee(n) {
  return '₹' + parseFloat(n || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 });
}

function qtyClass(qty, low) {
  if (qty === 0) return 'qty-out';
  if (qty <= low) return 'qty-low';
  return 'qty-ok';
}

function statusBadge(qty, low) {
  if (qty === 0) return '<span class="badge b-out">❌ Out</span>';
  if (qty <= low) return '<span class="badge b-low">⚠️ Low</span>';
  return '<span class="badge b-ok">✅ OK</span>';
}

// Close modal on backdrop click
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.overlay').forEach(el =>
    el.addEventListener('click', e => { if (e.target === el) el.classList.remove('open'); })
  );
});
