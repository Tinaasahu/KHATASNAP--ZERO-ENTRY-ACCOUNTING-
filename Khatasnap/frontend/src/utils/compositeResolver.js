export function findCombinations(amount, inventoryItems, maxQty = 20) {
  if (!amount || amount <= 0 || !inventoryItems || inventoryItems.length === 0) {
    return [];
  }

  const combinations = [];

  for (const item of inventoryItems) {
    const price = item.selling_price || item.price;
    if (!price || price <= 0) continue;

    if (amount % price === 0) {
      const qty = amount / price;
      
      if (qty <= maxQty && item.current_qty >= qty) {
        let baseScore = 100;
        
        // Penalties
        if (qty > 10) baseScore -= 40;
        else if (qty > 5) baseScore -= 20;
        else if (qty > 3) baseScore -= 10;
        
        if (price === 1) baseScore -= 30;
        if (price === 2) baseScore -= 20;
        
        // We can't perfectly evaluate price_item_patterns locally right here easily 
        // without fetching it, but we handle the qty bonuses 
        // Bonus rules
        if (qty === 1) baseScore += 20;

        combinations.push({
          item_id: item.id,
          item_name: item.name,
          item_emoji: item.emoji,
          price_per_unit: price,
          qty,
          total: amount,
          type: qty === 1 ? 'single' : 'multiple',
          score: baseScore,
          item // original object for merging later if needed
        });
      }
    }
  }

  combinations.sort((a, b) => b.score - a.score);
  return combinations.slice(0, 4);
}
