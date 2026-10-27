#!/usr/bin/env bash
# Tests for the project hooks. Run from the repo root: bash .claude/hooks/test_hooks.sh
set -u
cd "$(dirname "$0")/../.."
export CLAUDE_PROJECT_DIR="$PWD"
pass=0; fail=0

expect() { # expect <exit-code> <description> <hook> <json>
  local want=$1 desc=$2 hook=$3 json=$4 got
  echo "$json" | python3 ".claude/hooks/$hook" >/dev/null 2>&1; got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); echo "PASS  $desc";
  else fail=$((fail+1)); echo "FAIL  $desc (wanted exit $want, got $got)"; fi
}

P=protect_raw.py
expect 2 "block Write to data/raw"            $P '{"tool_name":"Write","tool_input":{"file_path":"data/raw/x.csv"}}'
expect 2 "block Edit to data/evidence (abs)"  $P "{\"tool_name\":\"Edit\",\"tool_input\":{\"file_path\":\"$PWD/data/evidence/a.pdf\"}}"
expect 2 "block path traversal into raw"      $P '{"tool_name":"Write","tool_input":{"file_path":"data/processed/../raw/x.csv"}}'
expect 0 "allow Write to data/processed"      $P '{"tool_name":"Write","tool_input":{"file_path":"data/processed/x.csv"}}'
expect 0 "allow Write to data/rawish"         $P '{"tool_name":"Write","tool_input":{"file_path":"data/rawish/x.csv"}}'
expect 2 "block rm in data/raw"               $P '{"tool_name":"Bash","tool_input":{"command":"rm data/raw/x.csv"}}'
expect 2 "block sed -i in data/evidence"      $P '{"tool_name":"Bash","tool_input":{"command":"sed -i s/a/b/ data/evidence/x.txt"}}'
expect 2 "block redirect into data/raw"       $P '{"tool_name":"Bash","tool_input":{"command":"echo hi > data/raw/x.csv"}}'
expect 0 "allow reading data/raw"             $P '{"tool_name":"Bash","tool_input":{"command":"head -5 data/raw/x.csv"}}'
expect 0 "allow ls data/raw with redirect out" $P '{"tool_name":"Bash","tool_input":{"command":"ls data/raw > /tmp/list.txt"}}'
expect 0 "allow scraper writing to data/raw"  $P '{"tool_name":"Bash","tool_input":{"command":"python3 scrapers/acecqa.py --out data/raw/acecqa"}}'
expect 0 "ignore unrelated tool"              $P '{"tool_name":"Read","tool_input":{"file_path":"data/raw/x.csv"}}'

V=post_edit.py
expect 0 "valid ledger passes"                $V '{"tool_name":"Write","tool_input":{"file_path":"data/gap-ledger.json"}}'
tmp=$(mktemp -d); mkdir -p "$tmp/data" "$tmp/.claude/hooks"
cp .claude/hooks/validate_ledger.py "$tmp/.claude/hooks/"
echo '{"last_updated":"2026-10-28","gaps":[{"id":"GAP-1","status":"validated","evidence":[]}]}' > "$tmp/data/gap-ledger.json"
CLAUDE_PROJECT_DIR="$tmp" expect 2 "invalid ledger is rejected" $V '{"tool_name":"Write","tool_input":{"file_path":"data/gap-ledger.json"}}'
rm -rf "$tmp"

echo; echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
