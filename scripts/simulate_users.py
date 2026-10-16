"""Initialize a private synthetic customer; opt in explicitly to paid rollout."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from policypilot.api.runtime import (  # noqa: E402
    BackendRuntimeSettings,
    DefaultRuntimeFactory,
)
from policypilot.simulation.rollout import SimulatedUser, run_rollout  # noqa: E402
from policypilot.simulation.users import UserScenario, initialize_user  # noqa: E402
from tau2.domains.banking_knowledge.data_model import TransactionalDB  # noqa: E402
from tau2.domains.banking_knowledge.environment import get_db  # noqa: E402


def main() -> int:
    """Default to initialization only; never call an LLM without --run."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--user-id")
    parser.add_argument("--scenario", type=Path, help="Reuse a saved private scenario")
    parser.add_argument(
        "--database", type=Path, help="Use a saved synthetic DB snapshot"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--user-model")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--run", action="store_true", help="Allow paid model calls")
    args = parser.parse_args()
    if not 1 <= args.max_turns <= 50:
        parser.error("--max-turns must be between 1 and 50")
    if args.run and not args.user_model:
        parser.error("--run requires explicit --user-model")
    load_dotenv(ROOT / ".env")
    db = (
        TransactionalDB.model_validate_json(args.database.read_text(encoding="utf-8"))
        if args.database
        else get_db()
    )
    scenario = (
        UserScenario.model_validate_json(args.scenario.read_text(encoding="utf-8"))
        if args.scenario
        else initialize_user(db, args.seed, args.user_id)
    )
    if scenario.user_id not in db.users.data:
        parser.error("Scenario user is absent from the current synthetic database")
    actual_identity = initialize_user(
        db, scenario.seed, scenario.user_id
    ).known_identity
    if scenario.known_identity != actual_identity:
        parser.error("Scenario identity does not match the selected database snapshot")
    output = args.output or ROOT / "data" / "simulations" / (
        "open_rollout_"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "_"
        + uuid4().hex[:8]
    )
    if output.exists():
        parser.error("Output already exists; choose a new directory")
    if not args.run:
        output.mkdir(parents=True, exist_ok=False)
        (output / "scenario.private.json").write_text(
            scenario.model_dump_json(indent=2), encoding="utf-8"
        )
        (output / "database.private.json").write_text(
            db.model_dump_json(), encoding="utf-8"
        )
        print(f"Initialized only (no model calls): {output}")
        return 0
    settings = replace(
        BackendRuntimeSettings.from_env(), memory_enabled=False, laya_enabled=False
    )
    os.environ["POLICYPILOT_LAYA_ENABLED"] = "0"
    if not settings.agent_model:
        parser.error("Configure POLICYPILOT_AGENT_MODEL before --run")
    factory = DefaultRuntimeFactory(settings)
    factory.prepare(ROOT)
    runtime = factory(scenario.user_id, "simulation_" + uuid4().hex)
    # Both toolkits must share the same isolated initial database.
    runtime.environment.tools.db = db.model_copy(deep=True)
    runtime.environment.user_tools.db = runtime.environment.tools.db
    runtime.environment.sync_tools()
    result = run_rollout(
        runtime, SimulatedUser(scenario, args.user_model), output, args.max_turns
    )
    print(json.dumps({"status": result["status"], "output": str(output)}))
    return 1 if result["error_type"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
