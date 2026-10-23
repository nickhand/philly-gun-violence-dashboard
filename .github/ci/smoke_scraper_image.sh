#!/usr/bin/env bash
image="${1:?Pass the exact local image to test}"
set -euo pipefail
chrome_product_version="$(jq -er '.package.product_version' packages/etl/chrome-lock.json)"
test "$(docker inspect --format '{{.Config.User}}' "${image}")" = "app"
test "$(docker inspect --format '{{json .Config.Cmd}}' "${image}")" = '["gv-dashboard-etl","courts","worker"]'
image_entrypoint="$(docker inspect --format '{{json .Config.Entrypoint}}' "${image}")"
test "${image_entrypoint}" = "null" || test "${image_entrypoint}" = "[]"
test "$(docker inspect --format '{{json .Config.Volumes}}' "${image}")" = '{"/tmp":{}}'
runtime_flags=(--rm --read-only --cap-drop ALL --tmpfs "/tmp:rw,nosuid,nodev,noexec,mode=1777,size=512m")
inspection_runtime_flags=(--rm --read-only --network none --tmpfs "/tmp:rw,nosuid,nodev,noexec,mode=1777,size=512m")
docker run -i "${inspection_runtime_flags[@]}" "${image}" python - < .github/ci/check_tls_trust.py
test "$(docker run "${runtime_flags[@]}" "${image}" sh -c 'printf %s "$HOME"')" = "/tmp/app-home"
docker run "${runtime_flags[@]}" "${image}" python -c "import importlib.metadata as m, sys; assert sys.version_info >= (3, 13), sys.version; assert m.version('playwright') == '1.64.1'"
test "$(docker run "${runtime_flags[@]}" "${image}" google-chrome --product-version)" = "${chrome_product_version}"
docker run "${runtime_flags[@]}" "${image}" sh -ceu 'test ! -e /opt/google/chrome/chrome-sandbox; test ! -e /ms-playwright; test ! -e /usr/bin/pebble; test ! -e /etc/apt/sources.list.d/google-chrome.list; test ! -e /etc/cron.daily/google-chrome; test ! -e /etc/default/google-chrome; test ! -e /usr/share/keyrings/google-linux-signing-keyring.gpg; test ! -e /opt/google/chrome/cron'
docker run "${runtime_flags[@]}" "${image}" sh -ceu 'test -x /bin/false'
if docker run "${runtime_flags[@]}" "${image}" /bin/false; then
  echo "/bin/false unexpectedly returned success" >&2
  exit 1
else
  test "$?" -eq 1
fi
# Inspect as root so owner-only directories cannot hide privileged
# modes; read-only root and no network contain this inspection.
docker run "${inspection_runtime_flags[@]}" --user root "${image}" sh -ceu 'privileged_paths="$(find / -xdev -type f -perm /6000 -print)"; test -z "$privileged_paths"'
docker run "${runtime_flags[@]}" "${image}" gv-dashboard-etl --help
docker run "${runtime_flags[@]}" "${image}" gv-dashboard-etl courts monitor --help
# Match Fargate's default outer security profile: only Chrome's nested
# sandbox is disabled for this courts browser launch.
docker run "${runtime_flags[@]}" "${image}" python -c "from playwright.sync_api import sync_playwright; context = sync_playwright().start(); browser = context.chromium.launch(headless=True, channel='chrome', chromium_sandbox=False); assert browser.version == '${chrome_product_version}', browser.version; browser.close(); context.stop()"
