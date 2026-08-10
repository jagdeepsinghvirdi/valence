#!/bin/bash
# Double-clickable / Terminal-runner for Valence full setup
cd /Users/ajitsingh/Documents/techno/valence || exit 1
unset PREFIX
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

echo "======================================================"
echo "  Valence full setup — this may take 20–40 minutes"
echo "  You may be asked for your Mac password (Homebrew)"
echo "  Log: ~/valence-setup.log"
echo "======================================================"
echo ""

bash ./setup-frappe.sh
STATUS=$?

echo ""
if [ $STATUS -eq 0 ]; then
  echo "SUCCESS. Next:"
  echo "  cd ~/frappe/valence-bench && bench start"
  echo "  Open http://127.0.0.1:8000  (Administrator / admin)"
else
  echo "FAILED (exit $STATUS). Check ~/valence-setup.log"
fi

echo ""
echo "Press Enter to close this window..."
read -r
exit $STATUS
