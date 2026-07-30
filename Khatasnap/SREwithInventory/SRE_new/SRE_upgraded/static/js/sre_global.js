/**
 * KhataSnap — Global SRE Session Store + Floating Widget
 * sre_global.js  (loaded on every page via base injection)
 *
 * Architecture:
 *   SREStore  — singleton state manager backed by localStorage
 *   SREWidget — floating UI rendered into #sre-float-root
 */

// ════════════════════════════════════════════════════════════════
//  STATE STORE  (localStorage-backed, event-driven)
// ════════════════════════════════════════════════════════════════

const SREStore = (() => {
  const KEY   = 'khatasnap_sre_session';
  const EMPTY = {
    active:          false,
    sessionId:       null,
    mismatchAmount:  0,
    questionCount:   0,
    currentQuestion: null,
    probabilities:   [],
    remainingCombos: null,
    totalCombos:     null,
    history:         [],
    status:          'idle',   // idle | questioning | solved | no_match
    result:          null,
    minimized:       false,
    startedAt:       null,
  };

  let _state = { ...EMPTY };
  const _listeners = [];

  function _persist() {
    try { localStorage.setItem(KEY, JSON.stringify(_state)); } catch(e) {}
  }

  function _notify() {
    _listeners.forEach(fn => fn({ ..._state }));
  }

  function load() {
    try {
      const raw = localStorage.getItem(KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        _state = { ...EMPTY, ...parsed };
      }
    } catch(e) { _state = { ...EMPTY }; }
    _notify();
  }

  function get() { return { ..._state }; }

  function set(patch) {
    _state = { ..._state, ...patch };
    _persist();
    _notify();
  }

  function reset() {
    _state = { ...EMPTY };
    _persist();
    _notify();
  }

  function subscribe(fn) {
    _listeners.push(fn);
    fn({ ..._state }); // immediate call with current state
    return () => { const i = _listeners.indexOf(fn); if (i > -1) _listeners.splice(i, 1); };
  }

  return { load, get, set, reset, subscribe };
})();


// ════════════════════════════════════════════════════════════════
//  API HELPER  (uses same base as app.js)
// ════════════════════════════════════════════════════════════════

async function sreApiFetch(path, options = {}) {
  const API = 'http://127.0.0.1:8000/api';
  try {
    const res = await fetch(API + path, {
      headers: { 'Content-Type': 'application/json' },
      ...options
    });
    return await res.json();
  } catch(e) { return null; }
}


// ════════════════════════════════════════════════════════════════
//  FLOATING WIDGET
// ════════════════════════════════════════════════════════════════

const SREWidget = (() => {

  let _root = null;

  // ── Inject CSS ──────────────────────────────────────────────
  function _injectCSS() {
    if (document.getElementById('sre-float-css')) return;
    const style = document.createElement('style');
    style.id = 'sre-float-css';
    style.textContent = `
      /* ── FLOATING WIDGET ROOT ── */
      #sre-float-root {
        position: fixed;
        bottom: 28px;
        right: 28px;
        z-index: 8000;
        font-family: 'Plus Jakarta Sans', sans-serif;
        display: none;
      }
      #sre-float-root.sre-visible { display: block; }

      /* ── MINIMIZED PILL ── */
      .sre-pill {
        display: none;
        align-items: center;
        gap: 10px;
        background: #1c1917;
        border: 1.5px solid #d4420a;
        border-radius: 50px;
        padding: 10px 18px 10px 12px;
        cursor: pointer;
        box-shadow: 0 8px 32px rgba(212,66,10,0.35), 0 2px 8px rgba(0,0,0,0.3);
        transition: transform .2s, box-shadow .2s;
        user-select: none;
        animation: sre-pillin .3s cubic-bezier(.34,1.56,.64,1);
      }
      .sre-pill:hover {
        transform: translateY(-2px);
        box-shadow: 0 12px 40px rgba(212,66,10,0.45), 0 4px 12px rgba(0,0,0,0.3);
      }
      #sre-float-root.sre-minimized .sre-pill { display: flex; }
      #sre-float-root.sre-minimized .sre-panel { display: none; }

      .sre-pill-pulse {
        width: 10px; height: 10px;
        border-radius: 50%;
        background: #f97316;
        flex-shrink: 0;
        animation: sre-pulse 1.6s ease-in-out infinite;
      }
      .sre-pill-text {
        font-size: 12px;
        font-weight: 700;
        color: white;
        white-space: nowrap;
      }
      .sre-pill-amt {
        font-family: 'JetBrains Mono', monospace;
        font-size: 12px;
        color: #f97316;
        font-weight: 700;
      }
      .sre-pill-q {
        background: rgba(212,66,10,0.3);
        color: #f97316;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 20px;
      }

      /* ── EXPANDED PANEL ── */
      .sre-panel {
        width: 360px;
        background: #1c1917;
        border: 1.5px solid rgba(212,66,10,0.4);
        border-radius: 18px;
        box-shadow: 0 24px 64px rgba(0,0,0,0.4), 0 0 0 1px rgba(212,66,10,0.1);
        overflow: hidden;
        animation: sre-panelin .3s cubic-bezier(.34,1.56,.64,1);
        color: white;
      }

      /* ── PANEL HEADER ── */
      .sre-panel-header {
        padding: 14px 16px 12px;
        background: rgba(212,66,10,0.12);
        border-bottom: 1px solid rgba(212,66,10,0.2);
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .sre-header-icon {
        width: 32px; height: 32px;
        background: rgba(212,66,10,0.2);
        border: 1px solid rgba(212,66,10,0.3);
        border-radius: 9px;
        display: flex; align-items: center; justify-content: center;
        font-size: 16px;
        flex-shrink: 0;
      }
      .sre-header-info { flex: 1; min-width: 0; }
      .sre-header-title {
        font-size: 12px;
        font-weight: 800;
        color: white;
        letter-spacing: .3px;
      }
      .sre-header-sub {
        font-size: 10px;
        color: rgba(255,255,255,0.4);
        margin-top: 1px;
        font-family: 'JetBrains Mono', monospace;
      }
      .sre-header-actions { display: flex; gap: 5px; flex-shrink: 0; }
      .sre-hbtn {
        width: 26px; height: 26px;
        border-radius: 7px;
        border: 1px solid rgba(255,255,255,0.12);
        background: rgba(255,255,255,0.07);
        color: rgba(255,255,255,0.6);
        cursor: pointer;
        font-size: 13px;
        display: flex; align-items: center; justify-content: center;
        transition: all .15s;
        line-height: 1;
      }
      .sre-hbtn:hover { background: rgba(255,255,255,0.14); color: white; }
      .sre-hbtn.sre-hbtn-danger:hover { background: rgba(185,28,28,0.3); color: #fca5a5; border-color: rgba(185,28,28,0.4); }

      /* ── PANEL BODY ── */
      .sre-panel-body { padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }

      /* ── AMOUNT ROW ── */
      .sre-amt-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
        background: rgba(212,66,10,0.1);
        border: 1px solid rgba(212,66,10,0.2);
        border-radius: 10px;
        padding: 10px 13px;
      }
      .sre-amt-label { font-size: 10px; color: rgba(255,255,255,0.45); text-transform: uppercase; letter-spacing: .8px; font-weight: 600; }
      .sre-amt-val {
        font-family: 'JetBrains Mono', monospace;
        font-size: 22px;
        font-weight: 700;
        color: #f97316;
        line-height: 1;
      }
      .sre-progress-wrap {
        display: flex;
        align-items: center;
        gap: 8px;
      }
      .sre-progress-track {
        flex: 1;
        height: 4px;
        background: rgba(255,255,255,0.1);
        border-radius: 2px;
        overflow: hidden;
      }
      .sre-progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #f97316, #d4420a);
        border-radius: 2px;
        transition: width .4s ease;
      }
      .sre-q-label {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: rgba(255,255,255,0.4);
        white-space: nowrap;
        flex-shrink: 0;
      }

      /* ── QUESTION BLOCK ── */
      .sre-question-block {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 12px 14px;
      }
      .sre-q-meta {
        display: flex;
        align-items: center;
        gap: 7px;
        margin-bottom: 9px;
      }
      .sre-q-num {
        background: #d4420a;
        color: white;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 700;
        padding: 2px 7px;
        border-radius: 4px;
      }
      .sre-q-type {
        font-size: 10px;
        font-family: 'JetBrains Mono', monospace;
        padding: 2px 7px;
        border-radius: 4px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: .5px;
      }
      .sre-qt-product  { background: rgba(29,78,216,.25);  color: #93c5fd; }
      .sre-qt-category { background: rgba(109,40,217,.25); color: #c4b5fd; }
      .sre-qt-price    { background: rgba(21,128,61,.25);  color: #86efac; }
      .sre-qt-group    { background: rgba(180,83,9,.25);   color: #fcd34d; }

      .sre-q-combos {
        margin-left: auto;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: rgba(255,255,255,0.3);
      }
      .sre-q-text {
        font-size: 13px;
        font-weight: 600;
        color: rgba(255,255,255,0.92);
        line-height: 1.5;
        margin-bottom: 11px;
      }
      .sre-q-highlight { color: #f97316; }
      .sre-q-btns { display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
      .sre-btn-yes {
        padding: 9px 8px;
        border-radius: 9px;
        border: 1px solid rgba(21,128,61,.4);
        background: rgba(21,128,61,.15);
        color: #86efac;
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-weight: 700;
        font-size: 12px;
        cursor: pointer;
        transition: all .15s;
      }
      .sre-btn-yes:hover { background: rgba(21,128,61,.28); transform: translateY(-1px); }
      .sre-btn-no {
        padding: 9px 8px;
        border-radius: 9px;
        border: 1px solid rgba(185,28,28,.35);
        background: rgba(185,28,28,.12);
        color: #fca5a5;
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-weight: 700;
        font-size: 12px;
        cursor: pointer;
        transition: all .15s;
      }
      .sre-btn-no:hover { background: rgba(185,28,28,.25); transform: translateY(-1px); }

      /* ── SOLVED STATE ── */
      .sre-solved-block {
        background: rgba(21,128,61,.1);
        border: 1px solid rgba(21,128,61,.3);
        border-radius: 12px;
        padding: 12px 14px;
      }
      .sre-solved-title {
        font-size: 13px;
        font-weight: 800;
        color: #86efac;
        margin-bottom: 8px;
      }
      .sre-solved-chips { display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 10px; }
      .sre-solved-chip {
        background: rgba(21,128,61,.2);
        border: 1px solid rgba(21,128,61,.35);
        color: #86efac;
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 20px;
      }
      .sre-solved-btns { display: flex; gap: 6px; flex-wrap: wrap; }
      .sre-btn-confirm {
        flex: 1;
        padding: 8px;
        border-radius: 8px;
        border: 1px solid rgba(21,128,61,.4);
        background: rgba(21,128,61,.2);
        color: #86efac;
        font-family: 'Plus Jakarta Sans', sans-serif;
        font-weight: 700;
        font-size: 11px;
        cursor: pointer;
        transition: all .15s;
        white-space: nowrap;
      }
      .sre-btn-confirm:hover { background: rgba(21,128,61,.35); }

      /* ── PROBABILITY BARS ── */
      .sre-prob-section {}
      .sre-prob-label {
        font-size: 10px;
        font-weight: 700;
        color: rgba(255,255,255,0.35);
        text-transform: uppercase;
        letter-spacing: .8px;
        margin-bottom: 7px;
      }
      .sre-prob-list { display: flex; flex-direction: column; gap: 5px; }
      .sre-prob-row { display: flex; align-items: center; gap: 8px; }
      .sre-prob-name {
        font-size: 11px;
        font-weight: 600;
        color: rgba(255,255,255,0.7);
        width: 100px;
        flex-shrink: 0;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .sre-prob-track {
        flex: 1;
        height: 5px;
        background: rgba(255,255,255,0.07);
        border-radius: 3px;
        overflow: hidden;
      }
      .sre-prob-fill { height: 100%; border-radius: 3px; transition: width .5s ease; }
      .sre-prob-pct {
        font-family: 'JetBrains Mono', monospace;
        font-size: 10px;
        color: rgba(255,255,255,0.35);
        width: 30px;
        text-align: right;
        flex-shrink: 0;
      }

      /* ── PANEL FOOTER ── */
      .sre-panel-footer {
        padding: 10px 16px 14px;
        border-top: 1px solid rgba(255,255,255,0.06);
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .sre-footer-nav {
        font-size: 11px;
        color: rgba(255,255,255,0.35);
        font-family: 'JetBrains Mono', monospace;
      }
      .sre-goto-btn {
        padding: 6px 12px;
        background: rgba(212,66,10,0.2);
        border: 1px solid rgba(212,66,10,0.35);
        border-radius: 7px;
        color: #f97316;
        font-size: 11px;
        font-weight: 700;
        cursor: pointer;
        text-decoration: none;
        font-family: 'Plus Jakarta Sans', sans-serif;
        transition: all .15s;
        display: inline-block;
      }
      .sre-goto-btn:hover { background: rgba(212,66,10,0.35); }

      /* ── NO MATCH ── */
      .sre-nomatch-block {
        background: rgba(180,83,9,.1);
        border: 1px solid rgba(180,83,9,.3);
        border-radius: 12px;
        padding: 12px 14px;
        font-size: 12px;
        color: #fcd34d;
        font-weight: 600;
      }

      /* ── HISTORY STRIP ── */
      .sre-history-strip {
        display: flex;
        gap: 4px;
        flex-wrap: wrap;
        padding-top: 4px;
      }
      .sre-hist-chip {
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px;
        padding: 2px 6px;
        border-radius: 4px;
        font-weight: 700;
        border: 1px solid transparent;
      }
      .sre-hist-yes { background: rgba(21,128,61,.15); color: #86efac; border-color: rgba(21,128,61,.25); }
      .sre-hist-no  { background: rgba(185,28,28,.12); color: #fca5a5; border-color: rgba(185,28,28,.2); }

      /* ── ANIMATIONS ── */
      @keyframes sre-pillin {
        from { opacity: 0; transform: scale(.7) translateY(10px); }
        to   { opacity: 1; transform: scale(1) translateY(0); }
      }
      @keyframes sre-panelin {
        from { opacity: 0; transform: scale(.92) translateY(12px); }
        to   { opacity: 1; transform: scale(1) translateY(0); }
      }
      @keyframes sre-pulse {
        0%, 100% { opacity: 1; transform: scale(1); }
        50%       { opacity: .5; transform: scale(1.3); }
      }
      @keyframes sre-questionslide {
        from { opacity: 0; transform: translateX(8px); }
        to   { opacity: 1; transform: translateX(0); }
      }
      .sre-question-block { animation: sre-questionslide .2s ease; }
    `;
    document.head.appendChild(style);
  }

  // ── Build DOM structure ──────────────────────────────────────
  function _buildDOM() {
    if (document.getElementById('sre-float-root')) {
      _root = document.getElementById('sre-float-root');
      return;
    }
    _root = document.createElement('div');
    _root.id = 'sre-float-root';
    _root.innerHTML = `
      <!-- MINIMIZED PILL -->
      <div class="sre-pill" id="sre-pill" onclick="SREWidget.expand()">
        <div class="sre-pill-pulse"></div>
        <span class="sre-pill-text">⚖️ Hisab Milaan</span>
        <span class="sre-pill-amt" id="sre-pill-amt">₹0</span>
        <span class="sre-pill-q" id="sre-pill-q">Q0</span>
      </div>

      <!-- EXPANDED PANEL -->
      <div class="sre-panel" id="sre-panel">
        <!-- Header -->
        <div class="sre-panel-header">
          <div class="sre-header-icon">⚖️</div>
          <div class="sre-header-info">
            <div class="sre-header-title">Hisab Milaan — Active</div>
            <div class="sre-header-sub" id="sre-hdr-sub">Session running</div>
          </div>
          <div class="sre-header-actions">
            <button class="sre-hbtn" title="Minimize" onclick="SREWidget.minimize()">−</button>
            <button class="sre-hbtn sre-hbtn-danger" title="Reset Session" onclick="SREWidget.confirmReset()">✕</button>
          </div>
        </div>

        <!-- Body -->
        <div class="sre-panel-body" id="sre-panel-body">

          <!-- Amount + progress -->
          <div class="sre-amt-row">
            <div>
              <div class="sre-amt-label">Mismatch</div>
              <div class="sre-amt-val" id="sre-w-amt">₹0</div>
            </div>
            <div style="text-align:right">
              <div class="sre-amt-label" style="text-align:right">Combos</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:rgba(255,255,255,0.6)" id="sre-w-combos">—</div>
            </div>
          </div>

          <!-- Progress bar -->
          <div class="sre-progress-wrap">
            <span class="sre-q-label">5</span>
            <div class="sre-progress-track">
              <div class="sre-progress-fill" id="sre-w-progress" style="width:0%"></div>
            </div>
            <span class="sre-q-label" id="sre-w-q-label">Q0/10</span>
          </div>

          <!-- Q History strip -->
          <div class="sre-history-strip" id="sre-w-history" style="display:none"></div>

          <!-- Question block (shown during questioning) -->
          <div class="sre-question-block" id="sre-w-question" style="display:none">
            <div class="sre-q-meta">
              <span class="sre-q-num" id="sre-w-qnum">Q1</span>
              <span class="sre-q-type sre-qt-product" id="sre-w-qtype">Product</span>
              <span class="sre-q-combos" id="sre-w-qcombos"></span>
            </div>
            <div class="sre-q-text" id="sre-w-qtext">—</div>
            <div class="sre-q-btns">
              <button class="sre-btn-yes" onclick="SREWidget.answer('yes')">✓ Yes</button>
              <button class="sre-btn-no"  onclick="SREWidget.answer('no')">✗ No</button>
            </div>
          </div>

          <!-- Solved block -->
          <div class="sre-solved-block" id="sre-w-solved" style="display:none">
            <div class="sre-solved-title">🎯 Mismatch Found!</div>
            <div class="sre-solved-chips" id="sre-w-solved-chips"></div>
            <div class="sre-solved-btns">
              <button class="sre-btn-confirm" onclick="SREWidget.confirmLearn()">✓ Confirm &amp; Learn</button>
              <button class="sre-btn-confirm" onclick="SREWidget.reset()" style="border-color:rgba(185,28,28,.4);background:rgba(185,28,28,.15);color:#fca5a5">✕ Reset</button>
            </div>
          </div>

          <!-- No match block -->
          <div class="sre-nomatch-block" id="sre-w-nomatch" style="display:none">
            ⚠️ No combination found for this amount.
            <div style="margin-top:6px"><button class="sre-btn-confirm" onclick="SREWidget.reset()" style="border-color:rgba(180,83,9,.4);background:rgba(180,83,9,.15);color:#fcd34d;width:100%">↺ Try New Amount</button></div>
          </div>

          <!-- Probability bars -->
          <div class="sre-prob-section" id="sre-w-probs-section" style="display:none">
            <div class="sre-prob-label">Suspect Items</div>
            <div class="sre-prob-list" id="sre-w-probs"></div>
          </div>

        </div>

        <!-- Footer -->
        <div class="sre-panel-footer">
          <span class="sre-footer-nav" id="sre-footer-nav">Reconciliation in progress</span>
          <a href="/sre/smart" class="sre-goto-btn">Open Full View →</a>
        </div>
      </div>
    `;
    document.body.appendChild(_root);
  }

  // ── RENDER (called on every state change) ───────────────────
  const BAR_COLORS = ['#f97316','#d4420a','#15803d','#1d4ed8','#7c3aed','#0891b2','#b45309','#be185d'];

  const Q_TYPE_CONFIG = {
    product:  { label: 'Product',    cls: 'sre-qt-product'  },
    category: { label: 'Category',   cls: 'sre-qt-category' },
    price:    { label: 'Price Range','cls': 'sre-qt-price'  },
    group:    { label: 'Group',      cls: 'sre-qt-group'    },
  };

  function _render(state) {
    if (!_root) return;

    // Show/hide root
    if (!state.active) {
      _root.classList.remove('sre-visible', 'sre-minimized');
      return;
    }
    _root.classList.add('sre-visible');
    _root.classList.toggle('sre-minimized', !!state.minimized);

    // Pill
    const pillAmt = document.getElementById('sre-pill-amt');
    const pillQ   = document.getElementById('sre-pill-q');
    if (pillAmt) pillAmt.textContent = '₹' + parseFloat(state.mismatchAmount||0).toFixed(2);
    if (pillQ)   pillQ.textContent   = 'Q' + (state.questionCount||0);

    // Header sub
    const hdrSub = document.getElementById('sre-hdr-sub');
    if (hdrSub) {
      if (state.status === 'solved')   hdrSub.textContent = 'Mismatch identified ✓';
      else if (state.status === 'no_match') hdrSub.textContent = 'No combination found';
      else hdrSub.textContent = `${state.questionCount||0} questions asked`;
    }

    // Amount
    const wAmt = document.getElementById('sre-w-amt');
    if (wAmt) wAmt.textContent = '₹' + parseFloat(state.mismatchAmount||0).toFixed(2);

    // Combos
    const wCombos = document.getElementById('sre-w-combos');
    if (wCombos) wCombos.textContent = state.remainingCombos !== null ? state.remainingCombos : '—';

    // Progress bar
    const wProg = document.getElementById('sre-w-progress');
    const wQL   = document.getElementById('sre-w-q-label');
    const q     = state.questionCount || 0;
    if (wProg) wProg.style.width = Math.min((q / 9) * 100, 100) + '%';
    if (wQL)   wQL.textContent   = `Q${q}/10`;

    // History strip
    const histEl = document.getElementById('sre-w-history');
    if (histEl && state.history && state.history.length) {
      histEl.style.display = 'flex';
      histEl.innerHTML = state.history.slice(-8).map(h =>
        `<span class="sre-hist-chip ${h.answer==='yes'?'sre-hist-yes':'sre-hist-no'}" title="${_esc(h.question)}">
          Q${h.q_num} ${h.answer==='yes'?'✓':'✗'}
        </span>`
      ).join('');
    }

    // Blocks visibility
    const isQ       = state.status === 'questioning';
    const isSolved  = state.status === 'solved';
    const isNoMatch = state.status === 'no_match';

    _show('sre-w-question', isQ);
    _show('sre-w-solved',   isSolved);
    _show('sre-w-nomatch',  isNoMatch);
    _show('sre-w-probs-section', state.probabilities && state.probabilities.length > 0 && !isSolved && !isNoMatch);

    // Question content
    if (isQ && state.currentQuestion) {
      const q = state.currentQuestion;
      const qtype = q.type || 'product';
      const cfg = Q_TYPE_CONFIG[qtype] || Q_TYPE_CONFIG['product'];

      const qnum  = document.getElementById('sre-w-qnum');
      const qtype_el = document.getElementById('sre-w-qtype');
      const qtext = document.getElementById('sre-w-qtext');
      const qcombos = document.getElementById('sre-w-qcombos');

      if (qnum)    qnum.textContent = `Q${state.questionCount + 1}`;
      if (qtype_el) { qtype_el.textContent = cfg.label; qtype_el.className = `sre-q-type ${cfg.cls}`; }
      if (qcombos) qcombos.textContent = state.remainingCombos !== null ? `${state.remainingCombos} left` : '';
      if (qtext)   qtext.innerHTML = _formatQText(q);
    }

    // Solved chips
    if (isSolved && state.result) {
      const chipsEl = document.getElementById('sre-w-solved-chips');
      if (chipsEl) {
        chipsEl.innerHTML = state.result.map(p =>
          `<span class="sre-solved-chip" data-name="${_esc(p.name)}">₹${parseFloat(p.selling_price).toFixed(2)} — ${_esc(p.name)}</span>`
        ).join('');
      }
    }

    // Probabilities
    if (state.probabilities && state.probabilities.length) {
      const probsEl = document.getElementById('sre-w-probs');
      if (probsEl) {
        probsEl.innerHTML = state.probabilities.slice(0, 5).map((item, i) => {
          const pct = Math.round((item.probability || 0) * 100);
          return `<div class="sre-prob-row">
            <div class="sre-prob-name" title="${_esc(item.product)}">${_esc(item.product)}</div>
            <div class="sre-prob-track">
              <div class="sre-prob-fill" style="width:${pct}%;background:${BAR_COLORS[i%BAR_COLORS.length]}"></div>
            </div>
            <div class="sre-prob-pct">${pct}%</div>
          </div>`;
        }).join('');
      }
    }

    // Footer nav
    const footerNav = document.getElementById('sre-footer-nav');
    if (footerNav) {
      if (isSolved)       footerNav.textContent = `Found in ${state.questionCount} question(s)`;
      else if (isNoMatch) footerNav.textContent = 'No match — check prices';
      else                footerNav.textContent = `${state.remainingCombos || '?'} combos remain`;
    }
  }

  function _formatQText(q) {
    const qtype = q.type || 'product';
    if (qtype === 'product')
      return `Was <span class="sre-q-highlight">"${_esc(q.product)}"</span> involved?`;
    if (qtype === 'category')
      return `Was the item a <span class="sre-q-highlight">${_esc(q.category)}</span>?`;
    if (qtype === 'price')
      return `Was any item priced above <span class="sre-q-highlight">₹${q.threshold}</span>?`;
    if (qtype === 'group') {
      const names = (q.group||[]).map(n=>`<span class="sre-q-highlight">"${_esc(n)}"</span>`).join(' or ');
      return `Was it ${names}?`;
    }
    return _esc(q.question || '');
  }

  function _show(id, visible) {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? '' : 'none';
  }
  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── PUBLIC API ───────────────────────────────────────────────
  function init() {
    _injectCSS();
    _buildDOM();
    SREStore.load();
    SREStore.subscribe(state => _render(state));
  }

  function minimize() {
    SREStore.set({ minimized: true });
  }

  function expand() {
    SREStore.set({ minimized: false });
  }

  function confirmReset() {
    if (confirm('Reset current Hisab Milaan session? This cannot be undone.')) {
      reset();
    }
  }

  async function reset() {
    const state = SREStore.get();
    if (state.sessionId) {
      await sreApiFetch('/sre/smart/reset', {
        method: 'POST',
        body: JSON.stringify({ session_id: state.sessionId })
      });
    }
    SREStore.reset();
    if (typeof toast === 'function') toast('Session reset', 'info');
  }

  async function answer(ans) {
    const state = SREStore.get();
    if (!state.currentQuestion || !state.sessionId) return;

    // Disable buttons immediately to prevent double-click
    document.querySelectorAll('.sre-btn-yes, .sre-btn-no').forEach(b => b.disabled = true);

    const data = await sreApiFetch('/sre/smart/answer', {
      method: 'POST',
      body: JSON.stringify({
        session_id:    state.sessionId,
        question_dict: state.currentQuestion,
        answer:        ans
      })
    });

    document.querySelectorAll('.sre-btn-yes, .sre-btn-no').forEach(b => b.disabled = false);
    if (!data) return;

    const newHistory = data.history || state.history || [];

    if (data.status === 'SOLVED') {
      SREStore.set({
        status:          'solved',
        result:          data.result,
        probabilities:   data.probabilities || [],
        questionCount:   data.question_count || state.questionCount,
        currentQuestion: null,
        history:         newHistory,
        remainingCombos: data.remaining_combos || null,
      });
    } else if (data.status === 'NO_MATCH') {
      SREStore.set({
        status:        'no_match',
        questionCount: data.question_count || state.questionCount,
        history:       newHistory,
      });
    } else {
      SREStore.set({
        status:          'questioning',
        currentQuestion: data.question,
        probabilities:   data.probabilities || [],
        questionCount:   data.question_count || state.questionCount,
        remainingCombos: data.remaining_combos,
        history:         newHistory,
      });
    }
  }

  async function confirmLearn() {
    const state = SREStore.get();
    if (!state.result) return;
    const items = state.result.map(p => p.name);
    await sreApiFetch('/sre/smart/learn', {
      method: 'POST',
      body: JSON.stringify({ items, amount: state.mismatchAmount })
    });
    if (typeof toast === 'function') toast('✓ Learned! System updated.', 'ok');
    SREStore.reset();
  }

  // Called by sre_smart page to start/update a session
  function syncSession(sessionData) {
    SREStore.set({
      active:          true,
      sessionId:       sessionData.sessionId,
      mismatchAmount:  sessionData.mismatchAmount,
      questionCount:   sessionData.questionCount || 0,
      currentQuestion: sessionData.currentQuestion || null,
      probabilities:   sessionData.probabilities || [],
      remainingCombos: sessionData.remainingCombos,
      totalCombos:     sessionData.totalCombos,
      history:         sessionData.history || [],
      status:          sessionData.status || 'questioning',
      result:          sessionData.result || null,
      minimized:       false,
      startedAt:       sessionData.startedAt || new Date().toISOString(),
    });
  }

  return { init, minimize, expand, confirmReset, reset, answer, confirmLearn, syncSession };
})();


// ════════════════════════════════════════════════════════════════
//  AUTO-INIT on every page load
// ════════════════════════════════════════════════════════════════
document.addEventListener('DOMContentLoaded', () => {
  SREWidget.init();
});


// ════════════════════════════════════════════════════════════════
//  SIDEBAR NAV BADGE  — glows when SRE session is active
// ════════════════════════════════════════════════════════════════

function _updateSidebarBadge(state) {
  // Find the Smart SRE nav link
  const navLink = document.querySelector('a[href="/sre/smart"]');
  if (!navLink) return;

  let badge = document.getElementById('sre-nav-badge');

  if (state.active && state.status !== 'idle') {
    if (!badge) {
      badge = document.createElement('span');
      badge.id = 'sre-nav-badge';
      badge.style.cssText = `
        display: inline-flex; align-items: center; justify-content: center;
        background: #d4420a; color: white;
        font-family: 'JetBrains Mono', monospace;
        font-size: 9px; font-weight: 700;
        padding: 1px 5px; border-radius: 20px;
        margin-left: auto; animation: sre-pulse 1.6s ease-in-out infinite;
        flex-shrink: 0;
      `;
      navLink.style.position = 'relative';
      navLink.appendChild(badge);
    }
    badge.textContent = state.status === 'solved' ? '✓' : `Q${state.questionCount}`;
    navLink.style.borderLeftColor = '#f97316';
    navLink.style.background = 'rgba(212,66,10,0.15)';
    navLink.style.color = 'white';
  } else {
    if (badge) badge.remove();
    navLink.style.borderLeftColor = '';
    navLink.style.background = '';
    navLink.style.color = '';
  }
}

// Subscribe sidebar badge to store changes
document.addEventListener('DOMContentLoaded', () => {
  SREStore.subscribe(state => _updateSidebarBadge(state));
});
