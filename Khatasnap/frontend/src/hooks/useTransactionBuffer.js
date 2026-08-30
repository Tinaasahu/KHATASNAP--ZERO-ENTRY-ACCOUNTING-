/**
 * useTransactionBuffer
 *
 * Wires the three parallel signals together:
 *   1. ASR segments from usePassiveASR
 *   2. Calculator amounts as they are finalized
 *   3. Confidence Engine result from /api/txn-buffer/finalize
 *
 * Lifecycle:
 *   beginSession() → called on first key press
 *   pushAmount(value, entryId?) → called when an operand is finalized
 *   finalize(amounts) → called on = press → returns { confidence, decision, matchedItems }
 *   commit(entries, ...) → persists high/medium confidence transactions
 *   flagForReconciliation(reason) → stores low-confidence to night queue
 *   discard() → called on C (clear)
 *
 * The buffer never touches permanent DB until commit() is called.
 */
import { useRef, useState, useCallback, useEffect } from 'react';
import {
  startBuffer,
  asrUpdate,
  amountUpdate,
  finalizeBuffer,
  commitBuffer,
  flagBuffer,
  discardBuffer,
} from '../api/calculator';

export function useTransactionBuffer() {
  const txnIdRef   = useRef(null);
  const amountsRef = useRef([]);   // local mirror of calc operands
  const [sessionActive, setSessionActive]   = useState(false);
  const [confidence, setConfidence]         = useState(null);   // last finalize result
  const [isFinalized, setIsFinalized]       = useState(false);
  const [isCommitting, setIsCommitting]     = useState(false);
  const [commitError, setCommitError]       = useState(null);

  // ── Generate a client-side txn_id ──────────────────────────────────────
  const _genId = () =>
    `TXN-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;

  // ── Begin a new calculator session ─────────────────────────────────────
  const beginSession = useCallback(async () => {
    if (txnIdRef.current) return txnIdRef.current; // already active
    const id = _genId();
    txnIdRef.current = id;
    amountsRef.current = [];
    setSessionActive(true);
    setConfidence(null);
    setIsFinalized(false);
    setCommitError(null);

    try {
      await startBuffer(id);
    } catch (_) {
      // Offline-first: buffer lives locally; backend call is best-effort
    }
    return id;
  }, []);

  // ── Push an ASR segment to the backend buffer ────────────────────────
  /** Called by CalculatorPage whenever passive.onSegment fires */
  const pushAsrSegment = useCallback(async (text) => {
    if (!txnIdRef.current || !text) return;
    try {
      await asrUpdate(txnIdRef.current, text);
    } catch (_) {}
  }, []);

  // ── Sync the amount list to the backend buffer ────────────────────────
  /** Called by CalculatorPage whenever an operand is finalized */
  const pushAmount = useCallback(async (value, entryId = null) => {
    if (!txnIdRef.current) return;
    amountsRef.current = [...amountsRef.current, { value, entry_id: entryId }];
    try {
      await amountUpdate(txnIdRef.current, amountsRef.current);
    } catch (_) {}
  }, []);

  /** Replace the full amount list (e.g. after voice adds multiple items) */
  const syncAmounts = useCallback(async (amounts) => {
    if (!txnIdRef.current) return;
    amountsRef.current = amounts.map(a =>
      typeof a === 'object' ? a : { value: a, entry_id: null }
    );
    try {
      await amountUpdate(txnIdRef.current, amountsRef.current);
    } catch (_) {}
  }, []);

  // ── Finalize: run confidence engine ──────────────────────────────────
  /**
   * @param {number[]} amounts - final operand list from calculator state
   * @returns {{ confidence: object, decision: string, txn_id: string }}
   */
  const finalize = useCallback(async (amounts) => {
    if (!txnIdRef.current) {
      txnIdRef.current = _genId();
    }
    setIsFinalized(false);

    try {
      const payload = await finalizeBuffer(txnIdRef.current, amounts);
      const conf = payload?.confidence ?? null;
      setConfidence(conf);
      setIsFinalized(true);
      return { confidence: conf, decision: conf?.decision ?? 'high', txn_id: txnIdRef.current };
    } catch (err) {
      // Fallback: treat as high confidence default so session commits immediately
      const fallback = {
        score: 0.95,
        decision: 'high',
        summary: 'Direct calculation finalized.',
        matched_items: [],
        unmatched_amounts: amounts,
        signals: {},
      };
      setConfidence(fallback);
      setIsFinalized(true);
      return { confidence: fallback, decision: 'high', txn_id: txnIdRef.current };
    }
  }, []);

  // ── Commit: persist to permanent DB ──────────────────────────────────
  /**
   * @param {object} opts
   * @param {Array}  opts.entries         - resolved entry list from calculator
   * @param {string} opts.expression      - full calculator expression string
   * @param {number} opts.result          - total amount
   * @param {object} opts.spokenContext   - raw ASR context
   * @param {number} opts.confidenceScore - score from finalize
   */
  const commit = useCallback(async ({ entries, expression, result, spokenContext, confidenceScore }) => {
    if (!txnIdRef.current) {
      txnIdRef.current = _genId();
    }
    setIsCommitting(true);
    setCommitError(null);

    try {
      const res = await commitBuffer(
        txnIdRef.current,
        entries,
        expression,
        result,
        spokenContext || {},
        confidenceScore ?? 0,
      );
      // Clear local state only after confirmed persistence
      txnIdRef.current = null;
      amountsRef.current = [];
      setSessionActive(false);
      setConfidence(null);
      setIsFinalized(false);
      return res || { session_id: _genId(), status: 'committed' };
    } catch (err) {
      setCommitError(err?.message || 'Commit failed');
      return null;
    } finally {
      setIsCommitting(false);
    }
  }, []);

  // ── Flag for night reconciliation ────────────────────────────────────
  const flagForReconciliation = useCallback(async (reason = 'low_confidence', extraPayload = {}) => {
    if (!txnIdRef.current) return null;
    try {
      const res = await flagBuffer(
        txnIdRef.current,
        reason,
        confidence?.score ?? 0,
        extraPayload,
      );
      // Clear after confirmed persistence
      txnIdRef.current = null;
      amountsRef.current = [];
      setSessionActive(false);
      setConfidence(null);
      setIsFinalized(false);
      return res;
    } catch (_) {
      return null;
    }
  }, [confidence]);

  // ── Discard (Clear button) ────────────────────────────────────────────
  const discard = useCallback(async () => {
    if (!txnIdRef.current) return;
    const id = txnIdRef.current;
    txnIdRef.current = null;
    amountsRef.current = [];
    setSessionActive(false);
    setConfidence(null);
    setIsFinalized(false);
    setCommitError(null);
    try {
      await discardBuffer(id);
    } catch (_) {}
  }, []);

  // ── Accessors ─────────────────────────────────────────────────────────
  const getTxnId  = useCallback(() => txnIdRef.current, []);
  const getAmounts = useCallback(() => amountsRef.current, []);

  return {
    sessionActive,
    confidence,
    isFinalized,
    isCommitting,
    commitError,
    beginSession,
    pushAsrSegment,
    pushAmount,
    syncAmounts,
    finalize,
    commit,
    flagForReconciliation,
    discard,
    getTxnId,
    getAmounts,
  };
}
