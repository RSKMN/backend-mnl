#!/bin/bash
# scripts/check_local_services.sh
# Verifies the health and status of all local QuDrugForge services.

echo "=============================================="
echo "   QuDrugForge Service Health Checker"
echo "=============================================="

# 1. q-ai-drug compute engine (port 8000)
echo -n "1. Checking q-ai-drug compute engine (127.0.0.1:8000)... "
q_res=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/research/health 2>/dev/null)
if [ "$q_res" = "200" ] || [ "$q_res" = "404" ]; then
    echo "ONLINE (Status: $q_res)"
else
    echo "OFFLINE / UNREACHABLE"
fi

# 2. backend-ml server (port 8001)
echo -n "2. Checking QuDrugForge Backend (127.0.0.1:8001)... "
be_res=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8001/api/v1/integrations/q-ai-drug/health 2>/dev/null)
# Allow 401 Unauthorized as successful server discovery
if [ "$be_res" = "200" ] || [ "$be_res" = "401" ] || [ "$be_res" = "403" ]; then
    echo "ONLINE (Status: $be_res)"
else
    echo "OFFLINE / UNREACHABLE"
fi

# 3. frontend-ml server (port 3001)
echo -n "3. Checking QuDrugForge Frontend (localhost:3001)... "
fe_res=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:3001/login 2>/dev/null)
if [ "$fe_res" = "200" ] || [ "$fe_res" = "302" ]; then
    echo "ONLINE"
else
    echo "OFFLINE / UNREACHABLE"
fi

echo "=============================================="
echo "Health check complete."
echo "=============================================="
