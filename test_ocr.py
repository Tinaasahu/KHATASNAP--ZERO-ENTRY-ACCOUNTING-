import sys
import os

# Ensure we import the actual OCR pipeline orchestrator used by the backend
ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT, "Khatasnap")
sys.path.insert(0, BACKEND_DIR)

from orchestrator import process_invoice
import numpy as np
import cv2
import traceback

img = np.zeros((100, 100, 3), dtype=np.uint8)
# We can't really call process_invoice with a dummy np.array directly since it wants bytes,
# Let's encode to bytes:
_, buf = cv2.imencode(".jpg", img)
file_bytes = buf.tobytes()

try:
    print(process_invoice(file_bytes, "dummy.jpg"))
except Exception as e:
    traceback.print_exc()
