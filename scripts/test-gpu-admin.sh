#!/bin/bash
# Test GPU Admin Endpoints

echo "=== GPU Admin Endpoints Test ==="
echo ""

# Test health endpoint
echo "1. Testing /admin/health..."
curl -s http://localhost:8877/admin/health 2>/dev/null | python3 -m json.tool || echo "   Failed"
echo ""

# Test restart endpoint (without auth - should work locally)
echo "2. Testing /admin/restart (no auth)..."
curl -s -X POST http://localhost:8877/admin/restart 2>/dev/null | python3 -m json.tool || echo "   Service unavailable (expected if not deployed yet)"
echo ""

echo "Test complete."
