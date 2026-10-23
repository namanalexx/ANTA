#!/usr/bin/env bash
pass=0; fail=0
check() {
  local desc="$1"; shift
  if "$@" >/dev/null 2>&1; then echo "PASS  $desc"; pass=$((pass+1))
  else echo "FAIL  $desc"; fail=$((fail+1)); fi
}
check "client -> router (10.10.1.2)"      docker exec client ping -c 2 -W 2 10.10.1.2
check "client -> firewall (10.10.2.3)"    docker exec client ping -c 2 -W 2 10.10.2.3
check "client -> dns-server (10.10.3.10)" docker exec client ping -c 2 -W 2 10.10.3.10
check "client -> web-server (10.10.3.20)" docker exec client ping -c 2 -W 2 10.10.3.20
check "web-server -> client (return path)" docker exec web-server ping -c 2 -W 2 10.10.1.10
check "DNS: web.anta.local -> 10.10.3.20" docker exec client sh -c 'dig +short +time=2 +tries=1 @10.10.3.10 web.anta.local | grep -qx 10.10.3.20'
check "HTTP 200 from web-server"          docker exec client sh -c 'test "$(curl -s -o /dev/null -w %{http_code} --max-time 3 http://10.10.3.20/)" = 200'
check "Isolation: client cannot reach 8.8.8.8" docker exec client sh -c '! ping -c 1 -W 2 8.8.8.8'
echo; echo "Path client -> web-server:"
docker exec client traceroute -n -w 1 -q 1 10.10.3.20
echo; echo "Result: $pass passed, $fail failed"
[ "$fail" -eq 0 ]
