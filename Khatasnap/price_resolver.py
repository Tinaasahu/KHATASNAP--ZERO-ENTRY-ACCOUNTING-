"""
Price Resolver Module for Smart Calculator
Resolves heuristic mappings for input prices based on time, day, and inventory.
"""
from database import get_conn

class PriceResolver:

    def get_items_for_price(self, price: int) -> list:
        """Return all items where price = given price OR via price_aliases."""
        conn = get_conn()
        # Query 1: Direct price match
        direct = conn.execute("""
            SELECT id, name, selling_price as price, current_qty as quantity, emoji
            FROM products 
            WHERE is_active=1 AND selling_price=?
        """, (price,)).fetchall()
        
        # Query 2: Alias price match
        alias = conn.execute("""
            SELECT i.id, i.name, i.selling_price as price, i.current_qty as quantity, i.emoji,
                   pa.alias_price
            FROM products i
            JOIN price_aliases pa ON i.id = pa.item_id
            WHERE pa.alias_price=? AND i.is_active=1
        """, (price,)).fetchall()
        
        conn.close()
        
        # Merge and deduplicate by item id
        seen_ids = set()
        result = []
        for row in direct:
            d = dict(row)
            seen_ids.add(d['id'])
            result.append(d)
        for row in alias:
            d = dict(row)
            if d['id'] not in seen_ids:
                seen_ids.add(d['id'])
                d['alias_used'] = True
                d['alias_price'] = d.pop('alias_price', price)
                result.append(d)
        return result

    def is_unique(self, price: int) -> bool:
        """Return True if only one item maps to this price."""
        return len(self.get_items_for_price(price)) == 1

    def get_best_guess(self, price: int, hour: int, day: int) -> dict | None:
        """
        Query price_item_patterns. Filter by price, hour_of_day (±2 hour window), day_of_week.
        Sum selection_count per item_id. 
        Calculate confidence = item_count / total_count for this price+time.
        Return highest confidence if >= 0.70.
        """
        conn = get_conn()
        
        # ±2 hour window
        lower_bound = (hour - 2) % 24
        upper_bound = (hour + 2) % 24
        
        if lower_bound > upper_bound:
            time_clause = "(hour_of_day >= ? OR hour_of_day <= ?)"
        else:
            time_clause = "(hour_of_day >= ? AND hour_of_day <= ?)"

        query = f"""
            SELECT item_id, item_name, SUM(selection_count) as total_selections
            FROM price_item_patterns
            WHERE price=? AND day_of_week=? AND {time_clause}
            GROUP BY item_id, item_name
            ORDER BY total_selections DESC
        """
        rows = conn.execute(query, (price, day, lower_bound, upper_bound)).fetchall()
        conn.close()

        if not rows:
            return None
            
        total_count = sum(r['total_selections'] for r in rows)
        if total_count == 0:
            return None
            
        best = rows[0]
        confidence = best['total_selections'] / total_count
        
        if confidence >= 0.70:
            return {
                "item_id": best['item_id'],
                "item_name": best['item_name'],
                "confidence": confidence,
                "price": price
            }
        return None

    def record_selection(self, price: int, item_id: int, item_name: str, hour: int, day: int):
        """Upsert into price_item_patterns."""
        conn = get_conn()
        row = conn.execute("""
            SELECT id FROM price_item_patterns 
            WHERE price=? AND item_id=? AND hour_of_day=? AND day_of_week=?
        """, (price, item_id, hour, day)).fetchone()
        
        if row:
            conn.execute("""
                UPDATE price_item_patterns 
                SET selection_count = selection_count + 1, last_selected_at = datetime('now')
                WHERE id=?
            """, (row['id'],))
        else:
            conn.execute("""
                INSERT INTO price_item_patterns 
                (price, item_id, item_name, hour_of_day, day_of_week, selection_count, last_selected_at)
                VALUES (?, ?, ?, ?, ?, 1, datetime('now'))
            """, (price, item_id, item_name, hour, day))
            
        conn.commit()
        conn.close()

    def get_pattern_stats(self, price: int) -> list:
        """Return all patterns for a price sorted by selection_count desc."""
        conn = get_conn()
        rows = conn.execute("""
            SELECT item_name, SUM(selection_count) as count
            FROM price_item_patterns
            WHERE price=?
            GROUP BY item_id, item_name
            ORDER BY count DESC
        """, (price,)).fetchall()
        conn.close()
        
        total = sum(r['count'] for r in rows)
        result = []
        for r in rows:
            result.append({
                "item_name": r['item_name'],
                "count": r['count'],
                "confidence": round(r['count'] / total, 2) if total > 0 else 0
            })
        return result
