#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_version="${RELEASE_VERSION:-0.1.0}"
release_version="${release_version#v}"
export RELEASE_VERSION="$release_version"
architecture="$(uname -m)"
artifact="$project_root/dist/DeskFocusTracker-${release_version}-macOS-${architecture}.dmg"

notary_values=0
[[ -n "${APPLE_ID:-}" ]] && ((notary_values += 1))
[[ -n "${APPLE_TEAM_ID:-}" ]] && ((notary_values += 1))
[[ -n "${APPLE_APP_PASSWORD:-}" ]] && ((notary_values += 1))
if [[ "$notary_values" -ne 0 && "$notary_values" -ne 3 ]]; then
  echo "Set APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD together." >&2
  exit 2
fi
if [[ "$notary_values" -eq 3 && -z "${APPLE_CODESIGN_IDENTITY:-}" ]]; then
  echo "Set APPLE_CODESIGN_IDENTITY before notarization." >&2
  exit 2
fi

cd "$project_root"
python packaging/build_icon.py packaging/generated
iconutil -c icns packaging/generated/desk-focus.iconset \
  -o packaging/generated/desk-focus.icns
python -m PyInstaller --clean --noconfirm packaging/desk_focus.spec

if [[ -n "${APPLE_CODESIGN_IDENTITY:-}" ]]; then
  codesign --verify --deep --strict --verbose=2 "dist/Desk Focus Tracker.app"
fi

hdiutil create \
  -volname "Desk Focus Tracker" \
  -srcfolder "dist/Desk Focus Tracker.app" \
  -ov \
  -format UDZO \
  "$artifact"

if [[ "$notary_values" -eq 3 ]]; then
  xcrun notarytool submit "$artifact" \
    --apple-id "$APPLE_ID" \
    --team-id "$APPLE_TEAM_ID" \
    --password "$APPLE_APP_PASSWORD" \
    --wait
  xcrun stapler staple "$artifact"
fi

hdiutil verify "$artifact"

(
  cd "$(dirname "$artifact")"
  artifact_name="$(basename "$artifact")"
  shasum -a 256 "$artifact_name" > "$artifact_name.sha256"
)
