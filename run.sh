#!/usr/bin/env bash
# SHG Reports - Mac / Linux launcher:   bash run.sh
# First run installs everything into the .venv folder (a few minutes, about 70-90 MB
# download - do it the day before, on a good connection). Ctrl+C stops the app.
# Works with Python 3.10 to 3.14; Python 3.13 is the one to install.

cd "$(dirname "$0")" || exit 1

fail() {                      # print a friendly message and stop
  echo
  for line in "$@"; do echo "$line"; done
  echo
  exit 1
}

# --- find Python 3.10-3.14, 3.13 first (every library has a ready-made wheel for it) ----
INSTALL_URL="https://www.python.org/downloads/release/python-31316/"
usable() {
  # On a Mac without the developer tools, /usr/bin/python3 only opens an installer: skip it.
  if [ "$(uname)" = "Darwin" ] && [ "$(command -v "$1")" = "/usr/bin/python3" ] \
     && ! xcode-select -p >/dev/null 2>&1; then
    return 2
  fi
  # 0: usable; 3: too new (3.15+: some libraries have no ready-made wheel for it yet,
  # so pip would need a compiler); anything else: too old or not a working Python.
  "$1" -c 'import sys; v = sys.version_info[:2]; raise SystemExit(0 if (3, 10) <= v < (3, 15) else 3 if v >= (3, 15) else 1)' >/dev/null 2>&1
}
PY=""; TOO_NEW=""
for candidate in python3.13 python3.12 python3.11 python3.14 python3.10 python3 python; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  usable "$candidate"; status=$?
  if [ "$status" -eq 0 ]; then PY="$candidate"; break; fi
  if [ "$status" -eq 3 ] && [ -z "$TOO_NEW" ]; then TOO_NEW="$candidate"; fi
done
if [ -z "$PY" ] && [ -n "$TOO_NEW" ]; then
  fail "The only Python on this computer is too new for SHG Reports: $("$TOO_NEW" --version 2>&1)." \
       "Some of the libraries it needs have no ready-made version for it yet." \
       "Install Python 3.13 as well (you can keep the newer one):" \
       "  Mac: the macOS installer on $INSTALL_URL" \
       "  Linux: your package manager's python3.13 (with its venv package), or pyenv" \
       "then run:  bash run.sh   (it finds python3.13 by itself)."
fi
[ -n "$PY" ] || fail "Python 3.10 to 3.14 was not found." \
  "Install Python 3.13 (Mac: the macOS installer on $INSTALL_URL;" \
  "Linux: your package manager's python3.13) and run:  bash run.sh"

# --- create the environment (again, if a previous attempt was left half-made) ---------
# (also one made with a Python this app can't use, e.g. 3.15 before this check existed)
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] < (3, 15) else 1)' >/dev/null 2>&1; then
  echo "Removing a half-made or unusable .venv folder..."
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
  echo "Installing libraries (about 70-90 MB). This takes a few minutes the first time..."
  echo
  .venv/bin/python -m pip install --disable-pip-version-check -q --upgrade pip
  if ! .venv/bin/python -m pip install --disable-pip-version-check --prefer-binary -r backend/requirements.txt; then
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
