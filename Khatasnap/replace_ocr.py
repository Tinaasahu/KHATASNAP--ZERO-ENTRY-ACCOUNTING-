import os
import io

file_path = "khatasnap (5)/khatasnap (2)/khatasnap/frontend/src/components/shashwat/OCRScanner.jsx"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

index = content.find("  return (")
if index == -1:
    print("Could not find start of return block.")
    exit(1)

new_return = """  return (
    <div className="ocr-hero-card">
        <div className="ocr-card-header">
          <div className="ocr-card-label">📸 Receipt Scanner</div>
          <div className="ocr-status-pill" id="ocr-status-pill">{processing ? 'Processing...' : ocrQuality === 'high' ? 'High Quality' : ocrQuality === 'unknown' ? 'Ready' : ocrQuality}</div>
        </div>
        
        {!showResults ? (
          <>
            <div className="ocr-scan-zone" id="ocr-zone" onClick={() => document.getElementById('ocr-file-input').click()}>
              <div className="ocr-corner tl"></div><div className="ocr-corner tr"></div>
              <div className="ocr-corner bl"></div><div className="ocr-corner br"></div>
              <span className="ocr-scan-icon">📸</span>
              <div className="ocr-scan-title">Scan Receipt or Bill</div>
              <div className="ocr-scan-sub">Upload photo — AI reads all items<br/>and adds them to your bill instantly</div>
            </div>
            <input type="file" id="ocr-file-input" accept="image/*" style={{display:'none'}} onChange={handleImageUpload}/>
            
            {processing && (
              <div className="ocr-progress-wrap" id="ocr-progress-wrap" style={{display:'block'}}>
                <div className="ocr-progress-fill" id="ocr-progress-fill" style={{width: `${progress}%`}}></div>
              </div>
            )}
            
            <div className="ocr-actions">
              <button className="ocr-btn ocr-btn-primary" onClick={() => document.getElementById('ocr-file-input').click()}>📷 Upload Photo</button>
              <button className="ocr-btn ocr-btn-secondary" onClick={loadSampleReceipt}>✨ Sample Receipt</button>
            </div>
          </>
        ) : (
          <div style={{padding: '10px 18px 18px'}}>
            <div style={{marginBottom: '10px', fontSize: '13px', fontWeight: 'bold'}}>Found {extractedItems.length} items</div>
            <div style={{maxHeight:'250px', overflowY:'auto', border:'1px solid var(--border)', borderRadius:'var(--r)', padding:'8px'}}>
              {extractedItems.map((item, index) => (
                <div key={index} style={{display:'flex', gap:'8px', marginBottom: '8px', paddingBottom: '8px', borderBottom: '1px dashed var(--border2)'}}>
                  <div style={{flex:1}}>
                    <input type="text" value={item.product_name} onChange={(e) => handleEditItem(index, 'product_name', e.target.value)} style={{width:'100%', fontSize:'11px', padding:'4px', border:'1px solid var(--border)', borderRadius:'4px', marginBottom:'4px'}} />
                    <div style={{display:'flex', gap:'4px'}}>
                      <input type="number" value={item.quantity} onChange={(e) => handleEditItem(index, 'quantity', e.target.value)} style={{width:'40px', fontSize:'11px', padding:'4px', border:'1px solid var(--border)', borderRadius:'4px'}} />
                      <input type="number" value={item.price} onChange={(e) => handleEditItem(index, 'price', e.target.value)} style={{width:'60px', fontSize:'11px', padding:'4px', border:'1px solid var(--border)', borderRadius:'4px'}} />
                    </div>
                  </div>
                  <div style={{display:'flex', flexDirection:'column', alignItems:'flex-end', justifyContent:'space-between'}}>
                    <div style={{fontSize:'12px', fontWeight:'bold', color:'var(--g600)'}}>₹{(item.quantity * item.price).toFixed(2)}</div>
                    <button onClick={() => handleRemoveItem(index)} style={{background:'none', border:'none', color:'var(--danger)', fontSize:'10px', cursor:'pointer'}}>Remove</button>
                  </div>
                </div>
              ))}
            </div>
            <div style={{display:'flex', justifyContent:'space-between', margin:'10px 0', fontWeight:'bold'}}>
              <span>Total:</span>
              <span>₹{calculateTotal().toFixed(2)}</span>
            </div>
            <div style={{display:'flex', gap:'8px'}}>
              <button onClick={handleAddItems} style={{flex:1, padding:'10px', background:'var(--accent)', color:'#fff', borderRadius:'var(--r-lg)', border:'none', fontWeight:'bold', cursor:'pointer'}}>✓ Add All to Bill</button>
              <button onClick={handleReset} style={{padding:'10px', background:'var(--surface2)', color:'var(--text2)', borderRadius:'var(--r-lg)', border:'none', fontWeight:'bold', cursor:'pointer'}}>Cancel</button>
            </div>
          </div>
        )}
    </div>
  );
};

export default OCRScanner;
"""

new_content = content[:index] + new_return
with open(file_path, "w", encoding="utf-8") as f:
    f.write(new_content)
    
print("Updated OCRScanner successfully.")
