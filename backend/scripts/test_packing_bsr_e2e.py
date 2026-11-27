import urllib.request
import json
import sys

BASE = 'http://localhost:3000'

def request(method, path, data=None, token=None):
    url = f"{BASE}{path}"
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        res = urllib.request.urlopen(req)
        return res.status, json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())

def main():
    print("1. Authenticating as admin@vspl.com on localhost:3000...")
    status, res = request('POST', '/api/v1/auth/login', {'email': 'admin@vspl.com', 'password': 'admin123'})
    if status != 200:
        print(f"FAILED: Login returned {status}: {res}")
        sys.exit(1)
    token = res['access_token']
    print("   [OK] Logged in successfully!")

    print("\n2. Fetching Packing Queue...")
    status, queue = request('GET', '/api/v1/packing/queue', token=token)
    if status != 200:
        print(f"FAILED: Fetch packing queue returned {status}: {queue}")
        sys.exit(1)
    print(f"   [OK] Retrieved {len(queue)} packing queue items.")

    # Find a work order with pending_qty > 0
    candidate = None
    for item in queue:
        if item.get('pending_qty', 0) > 0:
            candidate = item
            break

    if not candidate:
        print("   Notice: No work orders have pending_qty > 0 right now.")
        candidate = queue[0]
        print(f"   Checking existing packed WO: {candidate['wo_number']}")
    else:
        wo_number = candidate['wo_number']
        pending = candidate['pending_qty']
        pack_amount = min(5, pending)
        print(f"   Selected WO: {wo_number} (Pending: {pending}, Packing batch: {pack_amount})")

        print(f"\n3. Submitting Packing of {pack_amount} pcs for {wo_number}...")
        status, pack_res = request('POST', '/api/v1/packing/update', {
            'wo_number': wo_number,
            'packed_quantity': pack_amount,
            'box_count': 1,
            'package_type': 'Standard Wooden Box',
            'remarks': 'Automated verification test'
        }, token=token)
        if status != 200:
            print(f"FAILED: Packing update returned {status}: {pack_res}")
            sys.exit(1)
        msg = pack_res.get('message', '')
        print(f"   [OK] Staged in BSR! {msg}")

    print("\n4. Verifying BSR Endpoints...")
    status, updated_queue = request('GET', '/api/v1/packing/queue', token=token)
    assert status == 200, f"Packing queue returned {status}"
    status, bsr_stock = request('GET', '/api/v1/bsr-stock', token=token)
    assert status == 200, f"BSR stock returned {status}"

    # Filter items sitting in BSR
    in_bsr_lots = [it for it in updated_queue if (it.get('ready_for_dispatch_qty') or 0) > 0]
    print(f"   [OK] Total Committed Lots physically in BSR: {len(in_bsr_lots)}")
    total_pcs = sum(it.get('ready_for_dispatch_qty', 0) for it in in_bsr_lots)
    print(f"   [OK] Total Committed Pieces in BSR: {total_pcs} pcs")
    print(f"   [OK] Total Free Buffer Part Types in BSR: {len(bsr_stock)}")

    for it in in_bsr_lots[:3]:
        print(f"     - WO: {it['wo_number']} | Part: {it['part_number']} | In BSR: {it['ready_for_dispatch_qty']} pcs | Status: {it['status']}")

    print("\n5. Verifying Dispatch Bay Visibility...")
    status, dispatch_queue = request('GET', '/api/v1/dispatch/queue', token=token)
    assert status == 200, f"Dispatch queue returned {status}"
    print(f"   [OK] Total lots waiting at Dispatch Bay: {len(dispatch_queue)}")
    
    print("\n==========================================")
    print("SUCCESS: ALL PACKING -> BSR -> DISPATCH CHECKS PASSED!")
    print("==========================================")

if __name__ == '__main__':
    main()
