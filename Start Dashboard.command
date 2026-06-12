#!/bin/bash
# Double-click this file to start the Embroidery Opportunity Finder dashboard.
cd "$(dirname "$0")"

echo "Starting Embroidery Opportunity Finder..."

# Pick a free port (5050 default; macOS AirPlay uses 5000)
PORT=5050

# Stop any old instance on this port
lsof -ti :$PORT 2>/dev/null | xargs kill -9 2>/dev/null

# Start the server in the background
PORT=$PORT python3 app.py > /tmp/embro_dashboard.log 2>&1 &
SERVER_PID=$!

# Wait for it to come up
echo "Launching server (pid $SERVER_PID)..."
for i in {1..15}; do
  if curl -s -o /dev/null "http://localhost:$PORT/"; then break; fi
  sleep 1
done

URL="http://localhost:$PORT"
echo ""
echo "  Dashboard is running at: $URL"
echo "  (Keep this window open. Close it to stop the dashboard.)"
echo ""

# Open in the default browser
open "$URL"

# Keep the window alive so the server keeps running
wait $SERVER_PID
