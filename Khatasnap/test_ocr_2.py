import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from orchestrator import process_invoice
import numpy as np
import cv2

# Make a dummy dummy image containing some text
img = np.zeros((400, 400, 3), dtype=np.uint8)
cv2.putText(img, 'Invoice No 123', (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

_, buf = cv2.imencode(".jpg", img)
file_bytes = buf.tobytes()

print("Testing")
try:
    res = process_invoice(file_bytes, "dummy.jpg")
    print(res)
except Exception as e:
    import traceback
    traceback.print_exc()
