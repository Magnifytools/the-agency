#!/bin/bash
# Build and package the Chrome extension as a signed .crx
# Usage: ./build.sh
#
# First time only:
#   openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out dist/key.pem
#
# After packaging, get the extension ID from chrome://extensions
# and save it to dist/extension-id.txt

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KEY="$SCRIPT_DIR/dist/key.pem"
CRX="$SCRIPT_DIR/dist/agency-manager.crx"
EXT_DIR="$SCRIPT_DIR"

if [ ! -f "$KEY" ]; then
  echo "ERROR: dist/key.pem not found."
  echo "Generate it once with:"
  echo "  openssl genrsa 2048 | openssl pkcs8 -topk8 -nocrypt -out dist/key.pem"
  exit 1
fi

# Find Chrome
CHROME=""
if [ -f "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ]; then
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
elif command -v google-chrome &>/dev/null; then
  CHROME="google-chrome"
elif command -v chromium &>/dev/null; then
  CHROME="chromium"
else
  echo "ERROR: Chrome not found."
  exit 1
fi

# Pack the extension (Chrome puts the .crx next to the folder)
"$CHROME" --pack-extension="$EXT_DIR" --pack-extension-key="$KEY" 2>/dev/null || true

# Chrome creates the .crx one level up
BUILT_CRX="$(dirname "$EXT_DIR")/chrome-extension.crx"
if [ ! -f "$BUILT_CRX" ]; then
  echo "ERROR: Chrome didn't produce a .crx at $BUILT_CRX"
  exit 1
fi

mv "$BUILT_CRX" "$CRX"
VERSION=$(python3 -c "import json; print(json.load(open('$EXT_DIR/manifest.json'))['version'])")
echo "✓ Built agency-manager.crx (v$VERSION)"
echo ""
echo "Next steps:"
echo "  1. Load dist/agency-manager.crx in Chrome (chrome://extensions → drag & drop)"
echo "  2. Copy the extension ID shown in chrome://extensions"
echo "  3. Save it: echo 'YOUR_ID' > dist/extension-id.txt"
echo "  4. git add dist/agency-manager.crx dist/extension-id.txt && git push"
