/**
 * KhataSnap — Voice Micro-service
 * Wraps Shashwat's pattern-based voice processor (gemini.js) as a standalone Express service.
 * Port: 8002 (from .env → VOICE_SERVICE_PORT)
 *
 * Does NOT modify gemini.js. Only re-exports its functions through an HTTP API.
 */

const express = require('express');
const cors    = require('cors');
const path    = require('path');
const fs      = require('fs');

const PORT = parseInt(process.env.VOICE_SERVICE_PORT || '8002', 10);

// ── Load the voice processor from the Express backend's services dir ────
const GEMINI_PATH = path.join(
  __dirname, '..', '..', 'khatasnap (5)', 'khatasnap (2)', 'khatasnap',
  'backend', 'services', 'gemini.js'
);
const PRODUCTS_PATH = path.join(
  __dirname, '..', '..', 'khatasnap (5)', 'khatasnap (2)', 'khatasnap',
  'backend', 'data', 'products.json'
);

let processTransaction, detectMismatch;
try {
  const gemini = require(GEMINI_PATH);
  processTransaction = gemini.processTransaction;
  detectMismatch     = gemini.detectMismatch;
  console.log('✅ Voice processor loaded from:', GEMINI_PATH);
} catch (e) {
  console.error('❌ Failed to load gemini.js:', e.message);
  // Provide a stub so the service still starts
  processTransaction = async (transcript) => ({
    success: false, error: 'Voice processor not available', data: null
  });
  detectMismatch = async () => ({ mismatches: [], suggestions: [] });
}

function loadProducts() {
  try {
    return JSON.parse(fs.readFileSync(PRODUCTS_PATH, 'utf8'));
  } catch (e) {
    console.error('Products file not found, using empty list');
    return [];
  }
}

const app = express();
app.use(cors());
app.use(express.json());

// ── Health ────────────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'voice', port: PORT });
});

// ── Process voice transcript ─────────────────────────────────────────────
app.post('/process', async (req, res) => {
  try {
    const { transcript } = req.body;
    if (!transcript) {
      return res.status(400).json({ success: false, error: 'transcript required' });
    }

    console.log(`[Voice] Processing: "${transcript}"`);
    const products = loadProducts();
    const result   = await processTransaction(transcript, products);

    if (!result.success) {
      return res.status(500).json({ success: false, error: result.error });
    }

    // Add total_amount calculation
    const totalAmount = (result.data.items || []).reduce(
      (sum, i) => sum + (i.price || 0) * (i.quantity || 1), 0
    );

    res.json({
      success:   true,
      data: {
        ...result.data,
        total_amount: totalAmount,
      },
    });
  } catch (err) {
    console.error('Voice processing error:', err);
    res.status(500).json({ success: false, error: err.message });
  }
});

// ── Detect mismatch ──────────────────────────────────────────────────────
app.post('/detect-mismatch', async (req, res) => {
  try {
    const { expected, actual } = req.body;
    const result = await detectMismatch(expected, actual);
    res.json({ success: true, data: result });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// ── Start ────────────────────────────────────────────────────────────────
app.listen(PORT, () => {
  console.log(`\n🎤 Voice Service running on port ${PORT}`);
  console.log(`   POST /process — process voice transcript`);
  console.log(`   POST /detect-mismatch — detect mismatches\n`);
});
