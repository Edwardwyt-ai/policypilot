# Final Response Judge V1

PolicyPilot evaluates tool execution and database state with the existing tau3
evaluators. The offline Final Response Judge adds three semantic checks without
changing the original reward:

- `correctness`: claims agree with user, policy, tool, and database evidence.
- `completeness`: the decision-bearing response covers the material task needs.
- `grounded_safety`: no unsupported live-state, policy, memory, or completion claim.

The default judge is `deepseek/deepseek-chat`. Its JSON mode is a better fit for
the short three-verdict contract than a reasoning model, and it uses the same
`DEEPSEEK_API_KEY` already configured for the main agent. Override it with:

```powershell
$env:POLICYPILOT_JUDGE_MODEL = "deepseek/deepseek-reasoner"
```

Build or refresh the evaluator-only criteria:

```powershell
python scripts/build_final_response_gold_v1.py
```

Judge every supported task in an existing run:

```powershell
python scripts/evaluate_final_responses.py `
  --run-dir data/simulations/<run-name>
```

Judge one saved result:

```powershell
python scripts/evaluate_final_responses.py `
  --results data/simulations/<run-name>/tasks/task_001/results.json `
  --task-ids task_001
```

Outputs are written to `semantic_judgments.jsonl` and
`semantic_summary.json`. Gold criteria and hidden evaluator information are
never passed into the PolicyPilot runtime.
