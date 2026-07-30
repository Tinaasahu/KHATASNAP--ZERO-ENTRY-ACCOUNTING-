import requests

# Test PUT
resp = requests.put("http://localhost:8000/api/products/656", json={"selling_price": 2.5})
print("PUT Status:", resp.status_code)
print("PUT Response:", resp.text)

# Test DELETE
resp2 = requests.delete("http://localhost:8000/api/products/656")
print("DELETE Status:", resp2.status_code)
print("DELETE Response:", resp2.text)
