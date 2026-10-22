#!/bin/bash
# Retries run_eval_sweep.py until eval_prompts.json's full prompt count is
# present for the target model in the results file, since transient host
# memory pressure on this shared box has been killing the sweep process
# mid-run (not the container, not the model) -- run_eval_sweep.py's own
# per-record checkpointing means each retry just resumes where it left off.
MODEL="$1"
shift
ARGS="$@"
TOTAL=$(python3 -c "import json; print(len(json.load(open('scratchpad/eval_prompts.json'))))")
RESULTS_FILE="scratchpad/eval_results.json"
if [[ "$ARGS" == *"--router"* ]]; then
  RESULTS_FILE="scratchpad/eval_results_router.json"
elif [[ "$ARGS" == *"--suggest"* ]]; then
  RESULTS_FILE="scratchpad/eval_results_suggestion.json"
fi
for i in $(seq 1 15); do
  DONE=$(python3 -c "
import json
try:
    r = json.load(open('$RESULTS_FILE'))
    print(sum(1 for x in r if x['model']=='$MODEL'))
except FileNotFoundError:
    print(0)
")
  echo "=== attempt $i: $DONE/$TOTAL done for $MODEL ==="
  if [ "$DONE" -ge "$TOTAL" ]; then
    echo "=== complete ==="
    exit 0
  fi
  uv run python scratchpad/run_eval_sweep.py "$MODEL" $ARGS
  sleep 3
done
echo "=== gave up after 15 attempts ==="
exit 1
