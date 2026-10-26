#!/usr/bin/env bash
# Cron wrapper: silent unless an upstream release breaks the suite.
cd "$HOME/projects/aim" || exit 1
OUT=$(bash scripts/drift_watch.sh 2>&1)
if echo "$OUT" | grep -q "TESTS FAILING"; then
  echo "⚠️ AIM drift watch: upstream harness release broke the test suite."
  echo "$OUT"
  tail -20 /tmp/aim-drift-test.log 2>/dev/null
  exit 1
fi
# NO-DRIFT or drift-with-passing-tests: stay silent (empty stdout = no message)
exit 0
