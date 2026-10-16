#!/usr/bin/env bash
# Rehearse the pinned standalone frontend in local WSL systemd only.
set -Eeuo pipefail

if [[ $# -ne 5 ]]; then
  echo "usage: $0 ARCHIVE NODE_BINARY ARCHIVE_SHA256 NODE_SHA256 BUILD_ID" >&2
  exit 2
fi
if [[ $(id -u) -ne 0 ]] || ! grep -qi microsoft /proc/sys/kernel/osrelease; then
  echo "This rehearsal is restricted to local root-owned WSL." >&2
  exit 2
fi

archive=$(realpath -- "$1")
node_source=$(realpath -- "$2")
expected_archive=$3
expected_node=$4
expected_build=$5
port=13100
unit="crm-acc001-frontend-probe-$$.service"
probe_dir=""
started=0

cleanup() {
  local result=$?
  trap - EXIT
  if (( started )) && (( result != 0 )); then
    journalctl -u "$unit" -n 20 --no-pager >&2 || true
  fi
  if (( started )); then
    systemctl stop "$unit" >/dev/null 2>&1 || true
    systemctl reset-failed "$unit" >/dev/null 2>&1 || true
  fi
  if [[ -n "$probe_dir" && -d "$probe_dir" ]]; then
    local resolved
    resolved=$(realpath -- "$probe_dir")
    if [[ "$resolved" =~ ^/run/crm-acc001-systemd-[A-Za-z0-9]{8}$ ]]; then
      rm -rf -- "$resolved"
    else
      echo "Refusing to remove unexpected probe path: $resolved" >&2
      result=1
    fi
  fi
  exit "$result"
}
trap cleanup EXIT

[[ -f "$archive" && -f "$node_source" ]] || { echo "Missing pinned artifact" >&2; exit 2; }
[[ $(sha256sum "$archive" | cut -d ' ' -f 1) == "$expected_archive" ]] || {
  echo "Standalone archive checksum mismatch" >&2; exit 2;
}
[[ $(sha256sum "$node_source" | cut -d ' ' -f 1) == "$expected_node" ]] || {
  echo "Node binary checksum mismatch" >&2; exit 2;
}
if ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .; then
  echo "Loopback probe port is already occupied" >&2
  exit 2
fi

probe_dir=$(mktemp -d /run/crm-acc001-systemd-XXXXXXXX)
chmod 755 "$probe_dir"
install -m 755 "$node_source" "$probe_dir/node"
mkdir "$probe_dir/frontend"
tar -xzf "$archive" -C "$probe_dir/frontend"
[[ $("$probe_dir/node" --version) == v22.22.3 ]] || {
  echo "Node runtime version differs from the observed target" >&2; exit 2;
}
[[ $(cat "$probe_dir/frontend/.next/BUILD_ID") == "$expected_build" ]] || {
  echo "Standalone BUILD_ID mismatch" >&2; exit 2;
}

cat > "$probe_dir/probe.service" <<EOF
[Unit]
Description=CRM-ACC-001 isolated standalone frontend rehearsal
[Service]
Type=simple
DynamicUser=yes
WorkingDirectory=$probe_dir/frontend
ExecStart=$probe_dir/node $probe_dir/frontend/server.js
Environment=PORT=$port
Environment=HOSTNAME=127.0.0.1
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
Restart=no
EOF
systemd-analyze verify "$probe_dir/probe.service"

systemd-run --unit="$unit" --collect \
  --property=Type=simple \
  --property=DynamicUser=yes \
  --property="WorkingDirectory=$probe_dir/frontend" \
  --property=NoNewPrivileges=yes \
  --property=PrivateTmp=yes \
  --property=ProtectSystem=strict \
  --property=Restart=no \
  --property=IPAddressDeny=any \
  --property=IPAddressAllow=localhost \
  --setenv="PORT=$port" \
  --setenv=HOSTNAME=127.0.0.1 \
  --setenv=NODE_ENV=production \
  --setenv=NEXT_PUBLIC_AUTH_MODE=oidc \
  --setenv=NEXT_PUBLIC_KEYCLOAK_ISSUER=https://auth.belakb.by/realms/aios \
  --setenv=NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=aios-backend \
  --setenv=NEXT_PUBLIC_APP_ORIGIN=https://belakb.by \
  --setenv=BACKEND_URL=http://127.0.0.1:9 \
  "$probe_dir/node" "$probe_dir/frontend/server.js" >/dev/null
started=1

for _ in {1..20}; do
  if curl --silent --output /dev/null --max-time 2 "http://127.0.0.1:$port/"; then
    break
  fi
  [[ $(systemctl show "$unit" --value --property=ActiveState) == active ]] || break
  sleep 1
done
[[ $(systemctl show "$unit" --value --property=ActiveState) == active ]] || {
  echo "Transient unit did not become active" >&2; exit 1;
}
systemctl show "$unit" --value --property=ExecStart | grep -Fq "$probe_dir/node" || {
  echo "systemd resolved a different executable" >&2; exit 1;
}
systemctl show "$unit" --value --property=WorkingDirectory | grep -Fxq "$probe_dir/frontend" || {
  echo "systemd resolved a different working directory" >&2; exit 1;
}
ss -ltn "( sport = :$port )" | grep -Fq "127.0.0.1:$port" || {
  echo "Frontend is not bound to the loopback address" >&2; exit 1;
}

http_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
  "http://127.0.0.1:$port/erp/accounting")
[[ $http_status == 30[1278] ]] || {
  echo "Expected anonymous accounting redirect, got HTTP $http_status" >&2; exit 1;
}
static_file=$(find "$probe_dir/frontend/.next/static" -type f -name '*.js' -print -quit)
[[ -n "$static_file" ]] || { echo "No static JS in archive" >&2; exit 1; }
static_path=${static_file#"$probe_dir/frontend/.next/static/"}
static_status=$(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 5 \
  "http://127.0.0.1:$port/_next/static/$static_path")
[[ $static_status == 200 ]] || {
  echo "Expected static JS 200, got HTTP $static_status" >&2; exit 1;
}

systemctl stop "$unit"
started=0
for _ in {1..10}; do
  if ! ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .; then
    break
  fi
  sleep 1
done
if ss -ltn "( sport = :$port )" | tail -n +2 | grep -q .; then
  echo "Loopback probe listener remained after stop" >&2
  exit 1
fi
echo "PASS systemd start/stop; Node v22.22.3; BUILD_ID=$expected_build; accounting HTTP $http_status; static JS HTTP $static_status; loopback listener removed"
