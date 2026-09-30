# Local Laya Acquisition Routing

PolicyPilot uses Laya only to classify the authoritative acquisition required
for semantic-planner Needs. Laya does not execute tools, authorize writes, or
replace the main decision model.

## Install

From the repository root:

```powershell
uv sync --extra laya
```

For the existing project virtual environment, `laya==0.3.20` is already
installed. The first inference downloads the public checkpoint; later runs use
the local Hugging Face cache.

## Configure

```env
POLICYPILOT_LAYA_ENABLED=1
POLICYPILOT_LAYA_MODEL=convaiinnovations/laya
POLICYPILOT_LAYA_DEVICE=cuda
POLICYPILOT_LAYA_CACHE_DIR=.cache/huggingface
```

Set `POLICYPILOT_LAYA_ENABLED=0` to retain planner hints without loading Laya.
Use `POLICYPILOT_LAYA_DEVICE=auto` for automatic CUDA/CPU selection.

No API key is required. Model weights remain local and the cache directory is
ignored by Git.

## Verify

The deterministic unit suite does not need model inference:

```powershell
python -m pytest tests/policypilot/test_acquisition.py -q -m "not integration"
```

Run the real cached model smoke explicitly:

```powershell
$env:POLICYPILOT_RUN_LOCAL_LAYA="1"
$env:POLICYPILOT_LAYA_DEVICE="cuda"
python -m pytest tests/policypilot/test_acquisition.py::test_real_local_laya_smoke -q -s
```

## Runtime Boundary

Laya receives canonical Need fields, available fact field names, hard-criterion
field names, and a bounded list of eligible read tools. Fact values and raw
messages are excluded. A plan and its tool selection must each meet the
configured 0.75 threshold; otherwise PolicyPilot preserves the existing
planner hint. Tool schemas and permissions are validated locally after Laya.
