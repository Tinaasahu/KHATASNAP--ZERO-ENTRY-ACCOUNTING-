"""
KhataSnap — Smart Reconciliation Engine (SRE) v5
sre_engine.py

Upgrades over v3/v4:
  1.  History Pattern Reuse    — past Q&A paths seed question order for same amount
  2.  Temporal Decay           — recent memories weighted higher (30-day half-life)
  3.  Co-occurrence Scoring    — items always seen together get joint boost
  4.  Memory Confidence Score  — faster resolutions produce higher-weight memories
  5.  Warm Start / Instant Solve — exact-match high-frequency memory skips questions
  6.  Smart Eviction           — lowest (confidence × frequency × recency) evicted first
  7.  All v3 features retained — information gain, category/price/group questions, explainability
"""

import uuid
import math
import json
import os
from datetime import datetime

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE  = os.path.join(BASE_DIR, 'sre_memory.json')
MEMORY_LIMIT = 100
DECAY_DAYS   = 30      # exponential half-life in days

_sessions = {}
_learning = []


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY LOAD / SAVE
# ══════════════════════════════════════════════════════════════════════════════

def _load_memory():
    global _learning
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    _learning = data
            print(f"[SRE v5] Memory loaded: {len(_learning)} entries")
        except Exception as e:
            print("[SRE ERROR] Load failed:", str(e))
            _learning = []


def _save_memory():
    try:
        tmp = MEMORY_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_learning, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp, MEMORY_FILE)
    except Exception as e:
        print("[SRE ERROR] Save failed:", str(e))


_load_memory()


# ══════════════════════════════════════════════════════════════════════════════
# TEMPORAL DECAY
# ══════════════════════════════════════════════════════════════════════════════

def _decay_weight(last_seen_iso: str) -> float:
    """
    Weight in (0, 1] based on how recently this memory was used.
    Exponential decay: today=1.0, 30 days ago≈0.5, 90 days ago≈0.125
    """
    try:
        last = datetime.fromisoformat(last_seen_iso).replace(tzinfo=None)
        days = (datetime.now() - last).total_seconds() / 86400.0
        return math.exp(-math.log(2) * days / DECAY_DAYS)
    except Exception:
        return 0.5


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY CONFIDENCE SCORE
# ══════════════════════════════════════════════════════════════════════════════

def _memory_confidence(entry: dict) -> float:
    """
    Score [0.1, 1.0] reflecting how quickly/reliably this memory was confirmed.
    0 questions asked → 1.0  (instant resolve / warm start)
    1 question        → 0.5
    5 questions       → 0.167
    """
    asked = entry.get('questions_asked', 0)
    return max(round(1.0 / (1.0 + asked), 4), 0.10)


# ══════════════════════════════════════════════════════════════════════════════
# SMART EVICTION
# ══════════════════════════════════════════════════════════════════════════════

def _eviction_score(entry: dict) -> float:
    """Lower = evict first. Combines frequency, recency, and confidence."""
    freq  = math.log1p(entry.get('frequency', 1))
    decay = _decay_weight(entry.get('last_seen', entry.get('first_seen', '')))
    conf  = _memory_confidence(entry)
    return freq * decay * conf


def _enforce_memory_limit():
    global _learning
    if len(_learning) > MEMORY_LIMIT:
        _learning.sort(key=_eviction_score)
        del _learning[0]


# ══════════════════════════════════════════════════════════════════════════════
# CO-OCCURRENCE MAP
# ══════════════════════════════════════════════════════════════════════════════

def _build_cooccurrence() -> dict:
    """
    Returns {item_name: {other_item: co_count}} from the full memory log.
    Items that frequently co-appear in the same mismatch get mutual boosts.
    """
    co: dict = {}
    for entry in _learning:
        items = entry.get('items', [])
        freq  = entry.get('frequency', 1)
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                co.setdefault(a, {}).setdefault(b, 0)
                co.setdefault(b, {}).setdefault(a, 0)
                co[a][b] += freq
                co[b][a] += freq
    return co


# ══════════════════════════════════════════════════════════════════════════════
# HISTORY PATTERN — extract winning question order from past paths
# ══════════════════════════════════════════════════════════════════════════════

def _extract_yes_products(entry: dict) -> list:
    """Extract product names from question_path where answer was 'yes'."""
    order = []
    for step in entry.get('question_path', []):
        if step.get('type', 'product') == 'product' and step.get('answer') == 'yes':
            q = step.get('question', '')
            if '"' in q:
                parts = q.split('"')
                if len(parts) >= 2:
                    order.append(parts[1])
    return order


def find_history_seeds(amount: float, products: list) -> list:
    """
    Returns product names ordered by how reliably/early they appeared
    in past Q&A paths for the same mismatch amount.
    Higher-ranked seeds will be asked first in the question flow.
    """
    product_names = {p['name'] for p in products}
    amount_f      = round(float(amount), 2)
    seed_scores: dict = {}

    for entry in _learning:
        if abs(entry.get('amount', 0) - amount_f) > 0.01:
            continue
        decay  = _decay_weight(entry.get('last_seen', entry.get('first_seen', '')))
        conf   = _memory_confidence(entry)
        freq   = entry.get('frequency', 1)
        weight = decay * conf * math.log1p(freq)

        for rank, name in enumerate(_extract_yes_products(entry)):
            if name not in product_names:
                continue
            positional = 1.0 / (1.0 + rank)
            seed_scores[name] = seed_scores.get(name, 0.0) + weight * positional

    return sorted(seed_scores, key=lambda n: seed_scores[n], reverse=True)


# ══════════════════════════════════════════════════════════════════════════════
# WARM START — instant resolution from high-confidence memory
# ══════════════════════════════════════════════════════════════════════════════

def check_warm_start(amount: float, combos: list):
    """
    If any memory exactly matches a combo AND meets quality thresholds,
    return that combo immediately (0 questions asked).
    Thresholds: frequency >= 3, confidence >= 0.7, decay >= 0.6
    Returns dict {combo, entry, reason} or None.
    """
    amount_f = round(float(amount), 2)
    for entry in _learning:
        if abs(entry.get('amount', 0) - amount_f) > 0.01:
            continue
        if entry.get('frequency', 1) < 3:
            continue
        if _memory_confidence(entry) < 0.7:
            continue
        if _decay_weight(entry.get('last_seen', '')) < 0.6:
            continue
        mem_items = sorted(entry['items'])
        for combo in combos:
            if sorted(p['name'] for p in combo) == mem_items:
                return {
                    'combo':  combo,
                    'entry':  entry,
                    'reason': (
                        f"Matched memory {entry['id']} "
                        f"(seen {entry['frequency']}x, "
                        f"confidence {_memory_confidence(entry):.0%})"
                    )
                }
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 1. COMBINATION SOLVER — DFS
# ══════════════════════════════════════════════════════════════════════════════

def find_combinations(products, target_amount):
    results = []
    target  = round(float(target_amount), 2)

    def dfs(index, current_sum, combo):
        if abs(current_sum - target) < 0.01:
            results.append(list(combo))
            return
        if current_sum > target:
            return
        for i in range(index, len(products)):
            p = products[i]
            combo.append(p)
            dfs(i, round(current_sum + float(p['selling_price']), 2), combo)
            combo.pop()

    dfs(0, 0.0, [])
    return results


# ══════════════════════════════════════════════════════════════════════════════
# 2. INFORMATION GAIN ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _entropy(n_yes, n_no):
    total = n_yes + n_no
    if total == 0:
        return 0.0
    p_yes = n_yes / total
    p_no  = n_no  / total
    h = 0.0
    if p_yes > 0: h -= p_yes * math.log2(p_yes)
    if p_no  > 0: h -= p_no  * math.log2(p_no)
    return h

def _information_gain_score(n_yes, n_no):
    return _entropy(n_yes, n_no)


# ══════════════════════════════════════════════════════════════════════════════
# 3. RICH LEARNING MEMORY — save / update
# ══════════════════════════════════════════════════════════════════════════════

def save_learning(items, amount, question_history=None, final_probs=None, product_details=None):
    """
    Store / update a rich learning entry.
    - Keeps the shortest (most efficient) question_path per unique mismatch key.
    - Recalculates memory_confidence on every update.
    """
    details_map = {p['name']: p for p in (product_details or [])}

    items_meta = []
    for name in items:
        pd = details_map.get(name, {})
        items_meta.append({
            'name':     name,
            'price':    float(pd.get('selling_price', 0)),
            'category': pd.get('category') or 'Unknown',
        })

    q_path = []
    for h in (question_history or []):
        q_path.append({
            'q_num':      h.get('q_num'),
            'type':       h.get('type', 'product'),
            'question':   h.get('question', ''),
            'answer':     h.get('answer', ''),
            'eliminated': (h.get('combos_before') or 0) - (h.get('combos_after') or 0)
        })

    key_items  = sorted(items)
    key_amount = round(float(amount), 2)
    now_iso    = datetime.now().isoformat()

    # ── Update existing entry ──────────────────────────────────────────────
    for entry in _learning:
        if sorted(entry['items']) == key_items and round(entry['amount'], 2) == key_amount:
            entry['frequency']  += 1
            entry['times_seen']  = entry.get('times_seen', 1) + 1
            entry['last_seen']   = now_iso
            # Keep the shorter (more efficient) question path
            if q_path and len(q_path) < len(entry.get('question_path') or []):
                entry['question_path']   = q_path
                entry['questions_asked'] = len(q_path)
            if final_probs:
                entry['final_probs'] = final_probs[:5]
            entry['memory_confidence'] = _memory_confidence(entry)
            _save_memory()
            return entry

    # ── New entry ──────────────────────────────────────────────────────────
    new_entry = {
        'id':                f"MEM-{uuid.uuid4().hex[:8].upper()}",
        'items':             items,
        'items_meta':        items_meta,
        'amount':            key_amount,
        'frequency':         1,
        'times_seen':        1,
        'question_path':     q_path,
        'questions_asked':   len(q_path),
        'memory_confidence': round(1.0 / (1.0 + len(q_path)), 4),
        'final_probs':       (final_probs or [])[:5],
        'first_seen':        now_iso,
        'last_seen':         now_iso,
    }
    _learning.append(new_entry)
    _enforce_memory_limit()
    _save_memory()
    return new_entry


def get_learning_log():
    return sorted(_learning, key=lambda x: (-x.get('frequency', 1), x.get('last_seen', '')))


# ══════════════════════════════════════════════════════════════════════════════
# 4. PATTERN MATCHER
# ══════════════════════════════════════════════════════════════════════════════

def find_relevant_memories(amount, products):
    """
    Returns [{entry, score, reason, decay, confidence}] for memories
    relevant to the current session. Scores now factor in temporal decay
    and memory confidence so stale/unreliable memories are down-weighted.
    """
    if not _learning:
        return []

    product_cats   = {p['name']: p.get('category', '') for p in products}
    product_prices = {p['name']: float(p.get('selling_price', 0)) for p in products}
    amount_f       = float(amount)
    results        = []

    for entry in _learning:
        score   = 0.0
        reasons = []
        decay   = _decay_weight(entry.get('last_seen', entry.get('first_seen', '')))
        conf    = _memory_confidence(entry)

        if abs(entry['amount'] - amount_f) < 0.01:
            score  += 3.0 * decay * conf
            reasons.append(f"exact ₹{amount_f:.2f} mismatch seen before")
        elif amount_f > 0 and abs(entry['amount'] - amount_f) / amount_f <= 0.10:
            score  += 1.5 * decay
            reasons.append(f"similar ₹{entry['amount']:.2f} mismatch seen before")

        entry_cats   = {m['category'] for m in entry.get('items_meta', [])}
        cat_overlap  = entry_cats & set(product_cats.values())
        if cat_overlap:
            score  += len(cat_overlap) * 0.8 * decay
            reasons.append(f"same category: {', '.join(cat_overlap)}")

        entry_prices  = {m['price'] for m in entry.get('items_meta', [])}
        price_overlap = entry_prices & set(product_prices.values())
        if price_overlap:
            score  += len(price_overlap) * 0.6 * decay
            reasons.append(f"same price point(s): {', '.join('₹'+str(int(p)) for p in price_overlap)}")

        score += math.log1p(entry.get('frequency', 1)) * 0.5 * decay

        if score > 0.5:
            results.append({
                'entry':      entry,
                'score':      round(score, 3),
                'reason':     reasons[0] if reasons else '',
                'decay':      round(decay, 3),
                'confidence': round(conf, 3),
            })

    results.sort(key=lambda x: x['score'], reverse=True)
    return results[:10]


# ══════════════════════════════════════════════════════════════════════════════
# 5. BAYESIAN PROBABILITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def calculate_bayesian_probability(combos, learning_log=None, relevant_memories=None,
                                   history_seeds=None, cooccurrence=None):
    """
    Sorted list of {product, product_id, probability, count, boosted, explanation}.

    Four boost layers (all additive, final probability clamped to 1.0):
      A. Learning log frequency × decay × confidence
      B. Pattern-matched memory score × frequency
      C. History seed positional boost (items asked early in past paths)
      D. Co-occurrence boost (items that travel together)
    """
    if not combos:
        return []

    counts = {}
    total  = len(combos)

    for combo in combos:
        for item in combo:
            key = item['name']
            if key not in counts:
                counts[key] = {'count': 0, 'id': item['id'], 'boost': 0.0, 'explanations': []}
            counts[key]['count'] += 1

    # A. Full learning log boost
    if learning_log:
        for entry in learning_log:
            freq  = entry.get('frequency', 1)
            decay = _decay_weight(entry.get('last_seen', entry.get('first_seen', '')))
            conf  = _memory_confidence(entry)
            for name in entry.get('items', []):
                if name in counts:
                    counts[name]['boost'] += freq * decay * conf * 0.5

    # B. Pattern memory boost
    if relevant_memories:
        for mem in relevant_memories:
            entry  = mem['entry']
            score  = mem['score']
            reason = mem['reason']
            for name in entry.get('items', []):
                if name in counts:
                    boost = score * entry.get('frequency', 1) * 0.4
                    counts[name]['boost'] += boost
                    fw   = f"{entry['frequency']}x" if entry['frequency'] > 1 else "previously"
                    expl = f"Seen {fw} — {reason}"
                    if expl not in counts[name]['explanations']:
                        counts[name]['explanations'].append(expl)

    # C. History seed positional boost
    if history_seeds:
        n = len(history_seeds)
        for rank, name in enumerate(history_seeds):
            if name in counts:
                boost = (n - rank) / n * 0.6
                counts[name]['boost'] += boost
                expl = "Historically resolved first for this amount"
                if expl not in counts[name]['explanations']:
                    counts[name]['explanations'].append(expl)

    # D. Co-occurrence boost
    if cooccurrence:
        for name in list(counts.keys()):
            for partner, co_count in cooccurrence.get(name, {}).items():
                if partner in counts and co_count >= 2:
                    counts[partner]['boost'] += math.log1p(co_count) * 0.15
                    expl = f"Often appears with {name}"
                    if expl not in counts[partner]['explanations']:
                        counts[partner]['explanations'].append(expl)

    probabilities = []
    for name, data in counts.items():
        raw  = data['count'] / total
        b    = data['boost']
        prob = raw + (b / (total + b + 1)) * (1 - raw)
        probabilities.append({
            'product':     name,
            'product_id':  data['id'],
            'probability': min(round(prob, 4), 1.0),
            'count':       data['count'],
            'boosted':     b > 0,
            'explanation': data['explanations'][0] if data['explanations'] else None
        })

    probabilities.sort(key=lambda x: x['probability'], reverse=True)
    return probabilities


# ══════════════════════════════════════════════════════════════════════════════
# 6. QUESTION CANDIDATE GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_all_question_candidates(combos, products, asked_products, asked_types,
                                     learning_log=None, relevant_memories=None,
                                     history_seeds=None, cooccurrence=None):
    if not combos:
        return []

    candidates           = []
    all_items_in_combos  = {}
    categories_in_combos = set()
    prices_in_combos     = set()

    for combo in combos:
        for p in combo:
            name = p['name']
            if name not in all_items_in_combos:
                all_items_in_combos[name] = p
            if p.get('category'):
                categories_in_combos.add(p['category'])
            prices_in_combos.add(float(p['selling_price']))

    seed_rank = {name: rank for rank, name in enumerate(history_seeds or [])}
    n_seeds   = max(len(seed_rank), 1)

    # 1. Product questions — entropy + memory + history seed boosts
    for name, p in all_items_in_combos.items():
        if name in asked_products:
            continue
        n_yes = sum(1 for c in combos if any(px['name'] == name for px in c))
        n_no  = len(combos) - n_yes
        score = _information_gain_score(n_yes, n_no)

        boost = 0.0
        if learning_log:
            for entry in learning_log:
                if name in entry.get('items', []):
                    decay = _decay_weight(entry.get('last_seen', entry.get('first_seen', '')))
                    boost += entry.get('frequency', 1) * decay * 0.05
        if relevant_memories:
            for mem in relevant_memories:
                if name in mem['entry'].get('items', []):
                    boost += mem['score'] * 0.08

        # History seed: top seed gets +0.5 positional boost
        if name in seed_rank:
            boost += (n_seeds - seed_rank[name]) / n_seeds * 0.5

        # Co-occurrence: if partner is high-probability, bump this item too
        if cooccurrence:
            for partner, co_count in cooccurrence.get(name, {}).items():
                if partner in all_items_in_combos and co_count >= 2:
                    boost += math.log1p(co_count) * 0.04

        candidates.append({
            'type':       'product',
            'question':   f'Was "{name}" part of the mismatch?',
            'product':    name,
            'product_id': p.get('id'),
            'score':      min(score + boost, 1.5),
            'n_yes': n_yes, 'n_no': n_no,
            'eliminates': max(n_yes, n_no)
        })

    # 2. Category questions
    if 'category' not in asked_types[-2:]:
        for cat in categories_in_combos:
            n_yes = sum(1 for c in combos if any(p.get('category') == cat for p in c))
            n_no  = len(combos) - n_yes
            score = _information_gain_score(n_yes, n_no)
            if n_yes > 0 and n_no > 0:
                candidates.append({
                    'type': 'category', 'question': f'Was the item a {cat}?',
                    'category': cat, 'score': score * 0.92,
                    'n_yes': n_yes, 'n_no': n_no, 'eliminates': max(n_yes, n_no)
                })

    # 3. Price-range questions
    if 'price' not in asked_types[-2:]:
        sorted_prices = sorted(prices_in_combos)
        thresholds    = set()
        for pct in [0.25, 0.50, 0.75]:
            idx = int(len(sorted_prices) * pct)
            if 0 <= idx < len(sorted_prices):
                thresholds.add(round(sorted_prices[idx]))
        for threshold in thresholds:
            n_yes = sum(1 for c in combos if any(float(p['selling_price']) > threshold for p in c))
            n_no  = len(combos) - n_yes
            score = _information_gain_score(n_yes, n_no)
            if n_yes > 0 and n_no > 0:
                candidates.append({
                    'type': 'price', 'question': f'Was any item priced above ₹{threshold:.0f}?',
                    'threshold': threshold, 'score': score * 0.88,
                    'n_yes': n_yes, 'n_no': n_no, 'eliminates': max(n_yes, n_no)
                })

    # 4. Group questions
    if 'group' not in asked_types[-3:] and len(all_items_in_combos) >= 3:
        cat_groups = {}
        for name, p in all_items_in_combos.items():
            if name in asked_products:
                continue
            cat_groups.setdefault(p.get('category', 'Unknown'), []).append(name)
        for cat, names in cat_groups.items():
            if len(names) >= 2:
                group  = names[:3]
                n_yes  = sum(1 for c in combos if any(p['name'] in group for p in c))
                n_no   = len(combos) - n_yes
                score  = _information_gain_score(n_yes, n_no)
                if n_yes > 0 and n_no > 0:
                    joined = ' or '.join(f'"{n}"' for n in group)
                    candidates.append({
                        'type': 'group', 'question': f'Was the mismatch caused by {joined}?',
                        'group': group, 'score': score * 0.85,
                        'n_yes': n_yes, 'n_no': n_no, 'eliminates': max(n_yes, n_no)
                    })

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates


def generate_best_question(combos, products, asked_products, asked_types,
                           learning_log=None, q_number=1, relevant_memories=None,
                           history_seeds=None, cooccurrence=None):
    candidates = generate_all_question_candidates(
        combos, products, asked_products, asked_types,
        learning_log, relevant_memories, history_seeds, cooccurrence
    )
    if not candidates:
        return None

    if q_number <= 3:
        product_qs = [c for c in candidates if c['type'] == 'product']
        return product_qs[0] if product_qs else candidates[0]

    if q_number <= 6:
        top_score  = candidates[0]['score']
        diverse_qs = [c for c in candidates if c['type'] != 'product' and c['score'] >= top_score * 0.95]
        return diverse_qs[0] if diverse_qs else candidates[0]

    candidates.sort(key=lambda x: x['eliminates'], reverse=True)
    return candidates[0]


# ══════════════════════════════════════════════════════════════════════════════
# 7. COMBO FILTER
# ══════════════════════════════════════════════════════════════════════════════

def filter_combinations(combos, question, answer):
    qtype = question.get('type', 'product')

    if qtype == 'product':
        name = question['product']
        if answer == 'yes':
            return [c for c in combos if any(p['name'] == name for p in c)]
        else:
            return [c for c in combos if not any(p['name'] == name for p in c)]

    elif qtype == 'category':
        cat = question['category']
        if answer == 'yes':
            return [c for c in combos if any(p.get('category') == cat for p in c)]
        else:
            return [c for c in combos if not any(p.get('category') == cat for p in c)]

    elif qtype == 'price':
        threshold = question['threshold']
        if answer == 'yes':
            return [c for c in combos if any(float(p['selling_price']) > threshold for p in c)]
        else:
            return [c for c in combos if not any(float(p['selling_price']) > threshold for p in c)]

    elif qtype == 'group':
        group = question['group']
        if answer == 'yes':
            return [c for c in combos if any(p['name'] in group for p in c)]
        else:
            return [c for c in combos if not any(p['name'] in group for p in c)]

    return combos


# ══════════════════════════════════════════════════════════════════════════════
# 8. SESSION MANAGER
# ══════════════════════════════════════════════════════════════════════════════

def create_session(products, mismatch_amount):
    session_id = f"SRE-{uuid.uuid4().hex[:10].upper()}"
    combos     = find_combinations(products, mismatch_amount)

    # Build all intelligence for this session
    relevant      = find_relevant_memories(mismatch_amount, products)
    history_seeds = find_history_seeds(mismatch_amount, products)
    cooccurrence  = _build_cooccurrence()
    probs         = calculate_bayesian_probability(
                        combos, _learning, relevant, history_seeds, cooccurrence)

    # Warm start check
    warm = check_warm_start(mismatch_amount, combos) if combos else None

    _sessions[session_id] = {
        'products':          products,
        'mismatch_amount':   mismatch_amount,
        'combos':            combos,
        'probabilities':     probs,
        'question_count':    0,
        'asked_products':    set(),
        'asked_types':       [],
        'question_history':  [],
        'relevant_memories': relevant,
        'history_seeds':     history_seeds,
        'cooccurrence':      cooccurrence,
        'warm_start':        warm,
        'created_at':        datetime.now().isoformat(),
        'status':            'active'
    }

    return session_id, _sessions[session_id]


def get_session(session_id):
    return _sessions.get(session_id)


def answer_question(session_id, question_dict, answer):
    session = _sessions.get(session_id)
    if not session:
        return None, 'Session not found'

    filtered = filter_combinations(session['combos'], question_dict, answer)
    probs    = calculate_bayesian_probability(
                   filtered, _learning,
                   session.get('relevant_memories'),
                   session.get('history_seeds'),
                   session.get('cooccurrence'))

    if question_dict.get('type') == 'product':
        session['asked_products'].add(question_dict.get('product', ''))
    session['asked_types'].append(question_dict.get('type', 'product'))

    session['question_history'].append({
        'q_num':         session['question_count'] + 1,
        'question':      question_dict.get('question', ''),
        'type':          question_dict.get('type', 'product'),
        'answer':        answer,
        'combos_before': len(session['combos']),
        'combos_after':  len(filtered)
    })

    session['combos']         = filtered
    session['probabilities']  = probs
    session['question_count'] += 1

    # Auto-save when uniquely resolved
    if len(filtered) == 1:
        final_items = [p['name'] for p in filtered[0]]
        save_learning(
            items=final_items,
            amount=session['mismatch_amount'],
            question_history=session['question_history'],
            final_probs=probs,
            product_details=session['products']
        )

    return session, None


def get_next_question(session_id):
    session = _sessions.get(session_id)
    if not session:
        return None
    return generate_best_question(
        session['combos'],
        session['products'],
        session['asked_products'],
        session['asked_types'],
        _learning,
        q_number=session['question_count'] + 1,
        relevant_memories=session.get('relevant_memories'),
        history_seeds=session.get('history_seeds'),
        cooccurrence=session.get('cooccurrence')
    )


def should_continue_questioning(session):
    q_count   = session['question_count']
    remaining = len(session['combos'])
    if q_count < 5:   return True
    if q_count >= 10: return False
    if remaining <= 1: return False
    return True


def clear_session(session_id):
    _sessions.pop(session_id, None)


def get_session_memories(session_id):
    session = _sessions.get(session_id)
    if not session:
        return []
    return session.get('relevant_memories', [])


def get_session_warm_start(session_id):
    """Return warm start info if available (for API response)."""
    session = _sessions.get(session_id)
    if not session:
        return None
    return session.get('warm_start')


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY STATS — summary for API / UI
# ══════════════════════════════════════════════════════════════════════════════

def get_memory_stats() -> dict:
    """
    Returns aggregate stats about the current memory state.
    Used by /api/sre/smart/learning-log to enrich the response.
    """
    if not _learning:
        return {
            'total': 0,
            'total_sessions': 0,
            'avg_confidence': 0.0,
            'avg_frequency': 0.0,
            'top_items': [],
            'warm_start_eligible': 0,
        }

    total_sessions = sum(e.get('frequency', 1) for e in _learning)
    avg_conf       = sum(_memory_confidence(e) for e in _learning) / len(_learning)
    avg_freq       = total_sessions / len(_learning)

    # Count warm-start eligible entries
    warm_eligible = sum(
        1 for e in _learning
        if e.get('frequency', 1) >= 3
        and _memory_confidence(e) >= 0.7
        and _decay_weight(e.get('last_seen', e.get('first_seen', ''))) >= 0.6
    )

    # Top items by weighted frequency
    item_scores: dict = {}
    for e in _learning:
        decay  = _decay_weight(e.get('last_seen', e.get('first_seen', '')))
        conf   = _memory_confidence(e)
        weight = e.get('frequency', 1) * decay * conf
        for name in e.get('items', []):
            item_scores[name] = item_scores.get(name, 0.0) + weight

    top_items = sorted(item_scores.items(), key=lambda x: -x[1])[:5]

    return {
        'total':               len(_learning),
        'total_sessions':      total_sessions,
        'avg_confidence':      round(avg_conf, 3),
        'avg_frequency':       round(avg_freq, 2),
        'warm_start_eligible': warm_eligible,
        'top_items': [{'name': n, 'score': round(s, 2)} for n, s in top_items],
    }
