#!/usr/bin/env bash
# SHG Reports - Mac / Linux launcher:   bash run.sh
# First run installs everything into the .venv folder (a few minutes, about 100 MB
# download - do it the day before, on a good connection). Ctrl+C stops the app.

cd "$(dirname "$0")" || exit 1

fail() {                      # print a friendly message and stop
  echo
  for line in "$@"; do echo "$line"; done
  echo
  exit 1
}

# --- find Python 3.10 or newer ------------------------------------------------------
is_ok_python() {
  # On a Mac without the developer tools, /usr/bin/python3 only opens an installer: skip it.
  if [ "$(uname)" = "Darwin" ] && [ "$(command -v "$1")" = "/usr/bin/python3" ] \
     && ! xcode-select -p >/dev/null 2>&1; then
    return 1
  fi
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}
PY=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && is_ok_python "$candidate"; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.10 or newer was not found." \
  "Install Python 3.12 from https://www.python.org/downloads/ and run:  bash run.sh"

# --- create the environment (again, if a previous attempt was left half-made) ---------
if [ -d .venv ] && ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  echo "Removing a half-made .venv folder..."
  rm -rf .venv
fi
if [ ! -d .venv ]; then
  echo "Creating the Python environment..."
  if ! "$PY" -m venv .venv || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    rm -rf .venv
    if [ -f /etc/debian_version ]; then
      ver=$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
      fail "Could not create the Python environment: Python's 'venv' part is missing." \
           "Install it with:  sudo apt install python3-venv   (or python${ver}-venv)" \
           "then run:  bash run.sh"
    fi
    fail "Could not create the Python environment in the .venv folder (see the messages above)." \
         "Try moving the shg-digitiser folder somewhere simple, like your home folder."
  fi
fi

# --- install the libraries when requirements.txt is new or has changed ----------------
# .venv/installed.txt holds a fingerprint of backend/requirements.txt
fingerprint() {
  .venv/bin/python -c 'import hashlib, pathlib; print(hashlib.sha256(pathlib.Path("backend/requirements.txt").read_bytes()).hexdigest())'
}
if [ "$(cat .venv/installed.txt 2>/dev/null)" != "$(fingerprint)" ]; then
  echo
  echo "Installing libraries. This takes a few minutes the first time..."
  echo
  .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
  if ! .venv/bin/python -m pip install --disable-pip-version-check -r backend/requirements.txt; then
    fail "Installing the libraries failed - see the messages above." \
         "Check your internet connection and run:  bash run.sh" \
         "If it still fails, delete the .venv folder and try once more."
  fi
  fingerprint > .venv/installed.txt
fi

# --- is port 8000 free? -----------------------------------------------------------------
if ! .venv/bin/python -c 'import socket, sys; s = socket.socket(); s.settimeout(3); sys.exit(0 if s.connect_ex(("127.0.0.1", 8000)) else 1)'; then
  fail "SHG Reports is probably already running: open http://localhost:8000," \
       "or close the other SHG Reports window and run:  bash run.sh" \
       "(Another program is using port 8000.)"
fi

# --- start ---------------------------------------------------------------------------------
open_when_ready() {           # ask the app every second, for up to 90 s, then open the browser
  for _ in $(seq 1 90); do
    if .venv/bin/python -c 'import urllib.request as u; u.urlopen("http://localhost:8000/api/status", timeout=2)' >/dev/null 2>&1; then
      # (on Linux, "open" can be a different program: only use it on a Mac)
      if [ "$(uname)" = "Darwin" ]; then open http://localhost:8000 >/dev/null 2>&1
      elif command -v xdg-open >/dev/null 2>&1; then xdg-open http://localhost:8000 >/dev/null 2>&1
      else echo "Ready: open http://localhost:8000 in your browser."
      fi
      return
    fi
    sleep 1
  done
  echo
  echo "The app is taking longer than usual. When this window says"
  echo "\"Application startup complete\", open http://localhost:8000 in your browser."
}

echo
echo "============================================================"
echo "  SHG Reports is starting..."
echo "  Your browser opens http://localhost:8000 by itself once the"
echo "  app is ready (up to a minute the first time)."
echo "  Keep this window open. Press Ctrl+C here to stop the app."
echo "============================================================"
echo
open_when_ready &
waiter=$!
trap 'true' INT               # Ctrl+C stops the app cleanly; this script then says so
(cd backend && exec ../.venv/bin/python -m uvicorn app.api:app --port 8000)
rc=$?
kill "$waiter" 2>/dev/null
if [ "$rc" -eq 0 ] || [ "$rc" -eq 130 ]; then
  echo
  echo "SHG Reports has stopped."
else
  fail "The app stopped with an error - see the messages above."
fi
