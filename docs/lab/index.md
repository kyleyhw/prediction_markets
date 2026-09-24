# Research Lab

Studies of the markets the platform covers. Every number on these pages is
the output of a command shown just above it, run on data the platform
builds itself; `vp lab check` reruns them all and fails if any number has
changed, and `vp lab update` records new results when the data grows. Each
study has a caveats section at least as long as its findings, because a
market study that sounds certain usually is not.

| Study | The question |
| :--- | :--- |
| [Fee-aware baselines](baselines.md) | Does any simple strategy beat Polymarket's own prices once fees are paid? |
| [The favourite-longshot bias](longshot.md) | Do cheap contracts win less often than their price says, and dear ones more? |
| [Weather against the forecast models](nwp.md) | How sharp is the weather market against numerical weather prediction? |
| [How many markets a claim needs](sample_size.md) | How many settled markets before an edge can be told from luck? |

Waiting: **committees against a single model** needs the model's API key
and a forward record (`docs/signals.md`); it is published when both exist.

## Rebuilding the data

The studies read the git-ignored `data/` folder, which starts empty in a
fresh checkout:

```bash
uv run vp build-dataset --domain epl cs2 weather --histories 500
uv run vp evidence weather-runs
uv run vp lab update
```

The first takes about half an hour; the
histories are for the 500 most recently settled markets of each domain,
which is why every study counts its markets. The second backfills the
weather forecasts as they were issued. The third reruns every study and
records its output here.
