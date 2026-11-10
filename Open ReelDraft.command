#!/bin/zsh
# Starts ReelDraft and opens it in your browser. Restarts an old copy so you always see the latest version.
cd "${0:A:h}" || exit 1
url=http://127.0.0.1:5023

pid=$(lsof -nP -tiTCP:5023 -sTCP:LISTEN 2>/dev/null | head -1)
if [[ -n "$pid" ]]; then
  if ps -o command= -p "$pid" | grep -q "app/app.py"; then
    kill "$pid"
    for i in {1..25}; do lsof -nP -tiTCP:5023 -sTCP:LISTEN >/dev/null 2>&1 || break; sleep 0.2; done
  else
    echo "Port 5023 is used by another program, so ReelDraft can't start."
    read '?Press Enter to close.'
    exit 1
  fi
fi

py=.venv/bin/python
[[ -x "$py" ]] || py=python3
"$py" app/app.py &
server=$!
for i in {1..40}; do curl -fs -o /dev/null "$url/" && break; sleep 0.25; done
open "$url"
echo "ReelDraft is running at $url. Close this window to stop it."
wait $server
