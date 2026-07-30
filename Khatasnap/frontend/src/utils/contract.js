export const buildBillPayload = ({ source, vendor_name, invoice_no, invoice_date, items, payment_mode }) => {
  const subtotal = items.reduce((sum, item) => sum + (item.price * (item.qty || item.quantity || 1)), 0);
  
  return {
    source: source || 'manual',
    vendor_name: vendor_name || null,
    invoice_no: invoice_no || null,
    invoice_date: invoice_date || null,
    items: items.map(i => ({
      name: i.name || i.product_name || 'Unknown',
      qty: i.qty || i.quantity || 1,
      unit: i.unit || 'pcs',
      price: i.price || 0,
      amount: (i.price || 0) * (i.qty || i.quantity || 1),
      confidence: i.confidence || 1.0,
      product_id: i.product_id || null,
      matched_name: i.matched_name || null
    })),
    subtotal: subtotal,
    tax: 0,
    total_amount: subtotal,
    payment_mode: payment_mode || 'cash',
  };
};
