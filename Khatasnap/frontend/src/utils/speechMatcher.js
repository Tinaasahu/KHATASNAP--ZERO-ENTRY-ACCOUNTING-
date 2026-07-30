

const quantityWords = {
   "ek": 1, "do": 2, "teen": 3, "char": 4, 
   "paanch": 5, "chhe": 6, "saat": 7, "aath": 8,
   "nau": 9, "das": 10, "one": 1, "two": 2, 
   "three": 3, "four": 4, "five": 5, "six": 6,
   "seven": 7, "eight": 8, "nine": 9, "ten": 10,
   "half": 0.5, "dhai": 2.5, "couple": 2
};

function similarity(s1, s2) {
  let longer = s1; let shorter = s2;
  if (s1.length < s2.length) { longer = s2; shorter = s1; }
  let longerLength = longer.length;
  if (longerLength === 0) return 1.0;
  return (longerLength - editDistance(longer, shorter)) / parseFloat(longerLength);
}

function editDistance(s1, s2) {
  s1 = s1.toLowerCase(); s2 = s2.toLowerCase();
  let costs = new Array();
  for (let i = 0; i <= s1.length; i++) {
    let lastValue = i;
    for (let j = 0; j <= s2.length; j++) {
      if (i == 0) costs[j] = j;
      else {
        if (j > 0) {
          let newValue = costs[j - 1];
          if (s1.charAt(i - 1) != s2.charAt(j - 1))
            newValue = Math.min(Math.min(newValue, lastValue), costs[j]) + 1;
          costs[j - 1] = lastValue;
          lastValue = newValue;
        }
      }
    }
    if (i > 0) costs[s2.length] = lastValue;
  }
  return costs[s2.length];
}


function normalizeStr(text) {
  if (!text) return '';
  let norm = text.toLowerCase().replace(/[^\w\s\.]/gi, '').replace(/\s+/g, ' ');
  norm = norm.replace(/\b(grams|gram|gm)\b/g, 'g')
             .replace(/\b(kilograms|kilo|kilogram|kgs)\b/g, 'kg')
             .replace(/\b(milliliters|milliliter)\b/g, 'ml')
             .replace(/\b(liters|liter|litres|litre)\b/g, 'l')
             .replace(/(\d+)\s+(g|kg|ml|l)\b/g, '$1$2');
  return norm.trim();
}

export function extractItemMentions(transcript, inventoryItems) {
  if (!transcript) return [];
  
  const normTrans = normalizeStr(transcript);
  const mentions = [];
  const words = normTrans.split(' ');
  
  for (const item of inventoryItems) {
     const itemName = normalizeStr(item.name);
     let matchScore = 0;
     let matchedAlias = '';
     
     if (normTrans.includes(itemName)) {
        matchScore = 1.0;
        matchedAlias = itemName;
     } else {
        const aliases = item.aliases ? item.aliases.map(normalizeStr) : [];
        for (const alias of aliases) {
           if (normTrans.includes(alias)) {
              matchScore = 0.85;
              matchedAlias = alias;
              break;
           }
        }
        
        if (matchScore === 0) {
           const firstWord = itemName.split(' ')[0];
           if (itemName.length > 4 && normTrans.includes(firstWord)) {
               matchScore = 0.6;
               matchedAlias = firstWord;
           } else {
               // Add fuzzy phonetic matching for similar-sounding ASR errors
               const candidates = [itemName, ...aliases];
               for (const word of words) {
                   if (word.length > 3) {
                       for (const cand of candidates) {
                           const candFirst = cand.split(' ')[0];
                           if (candFirst.length > 3 && similarity(word, candFirst) >= 0.75) {
                               matchScore = 0.55;
                               matchedAlias = candFirst;
                               break;
                           }
                       }
                   }
                   if (matchScore > 0) break;
               }
           }
        }
     }
     
     if (matchScore > 0) {
        mentions.push({
           item_id: item.id,
           item_name: item.name,
           price: item.selling_price || item.price,
           match_score: matchScore,
           matched_alias: matchedAlias,
           item_obj: item
        });
     }
  }
  
  mentions.sort((a, b) => b.match_score - a.match_score);
  
  const seenIds = new Set();
  const seenAliases = new Set();
  const deduped = [];
  for (const m of mentions) {
     if (!seenIds.has(m.item_id) && (!m.matched_alias || !seenAliases.has(m.matched_alias))) {
        seenIds.add(m.item_id);
        if (m.matched_alias) seenAliases.add(m.matched_alias);
        
        // Find if any quantity word occurs before or after the alias mention
        let detectedQty = 1;
        if (m.matched_alias) {
            const indexAlias = words.indexOf(m.matched_alias.split(' ')[0]);
            
            if (indexAlias > 0 && quantityWords[words[indexAlias - 1]]) {
                detectedQty = quantityWords[words[indexAlias - 1]];
            } else if (indexAlias < words.length - 1 && quantityWords[words[indexAlias + 1]]) {
                detectedQty = quantityWords[words[indexAlias + 1]];
            } else if (indexAlias > 0 && !isNaN(parseInt(words[indexAlias - 1], 10))) {
                detectedQty = parseInt(words[indexAlias - 1], 10);
            }
        }
        
        m.detected_qty = detectedQty;
        deduped.push(m);
     }
  }
  
  return deduped;
}

export function matchMentionsToOperands(mentions, operands, inventoryItems) {
   return operands.map(op => {
      // First try direct price matches
      let matchingMentions = mentions.filter(m => m.price === op);
      
      // If no direct price match, look for composite amounts (e.g. op is 15, item price is 5, qty is 3)
      if (matchingMentions.length === 0) {
          const composites = mentions.filter(m => op % m.price === 0 && op / m.price === (m.detected_qty || 1));
          if (composites.length > 0) {
              matchingMentions = composites.map(m => ({...m, composite_match: true, calc_qty: op / m.price}));
          }
      }
      
      if (matchingMentions.length === 1) {
         const m = matchingMentions[0];
         return {
            operand: op,
            item: m.composite_match ? { ...m.item_obj, qty: m.calc_qty } : m.item_obj,
            confidence: Math.min(1.0, 0.90 + (m.match_score * 0.10) + (m.composite_match ? 0.05 : 0)),
            source: 'speech'
         };
      } else if (matchingMentions.length > 1) {
         const best = matchingMentions[0];
         return {
            operand: op,
            item: best.composite_match ? { ...best.item_obj, qty: best.calc_qty } : best.item_obj,
            confidence: 0.75,
            source: 'speech_ambiguous'
         };
      } else {
         return {
            operand: op,
            item: null,
            confidence: 0,
            source: 'none'
         };
      }
   });
}
