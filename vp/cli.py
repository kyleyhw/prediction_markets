"""Command-line entry point for vibe-predict.

Subcommands:

* ``vp build-dataset``: discover closed markets in a domain, keep those with
  a settlement label, store them and their price histories, and print the
  retrievability report. Run it with ``--max-markets`` for a quick check.
* ``vp snapshot``: write one snapshot of a domain's open markets with book
  depth.
* ``vp backtest``: forecast every resolved market of a domain at a cutoff,
  score against the market, simulate bets, and write a report directory.
* ``vp paper run|settle|leakage``: one forward paper-trading cycle, the
  settlement pass over open positions, and the forward-versus-backtest
  leakage check, all recorded in a hash-chained ledger.
* ``vp signals list|check|bench``: the signal library, its gates, and each
  signal against the market on a domain (docs/signals.md).
* ``vp evidence weather-runs|football|ensemble``: fill the evidence
  archive in the data root from the point-in-time weather source and the
  football results, and capture the ensemble for open markets
  (docs/evidence.md).
* ``vp strategy check|diff|preview|backtest``: a strategy spec (a JSON
  file): its problems, plain-language rendering and hash; what changed
  between two versions; what it would touch and cost; its backtest on each
  of its domains. ``vp strategy eval`` runs the compiler's held-out prompts
  (``--live`` against the real model).
* ``vp ui``: a local, read-only browser dashboard over the data root.
* ``vp serve``: the platform web service, with sign-in, over Postgres.
* ``vp db migrate``: apply the platform's pending database migrations.
* ``vp worker``: a pool of job runners for some kinds of job.
* ``vp ingest``: the market-data service.
* ``vp jobs``, ``vp admin``: the operator's commands (as the owner).

The platform commands import ``vp.platform`` lazily, inside their own
branches: this module is the composition root, and the engine commands
never load the platform.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from importlib.metadata import version
from pathlib import Path

from vp.backtest.run import BacktestConfig, run_backtest
from vp.domains import DOMAINS
from vp.forecast import FORECASTER_NAMES, make_forecaster
from vp.markets.dataset import build_resolved_dataset
from vp.markets.polymarket import PolymarketSource
from vp.markets.schema import utc_now_iso
from vp.markets.snapshot import collect_snapshot
from vp.paper import leakage
from vp.paper.ledger import Ledger
from vp.paper.loop import run_cycle, settle


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--domain",
        required=True,
        choices=sorted(DOMAINS),
        nargs="+",
        help="one or more domains to process",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data"),
        help="data root directory (default: data/)",
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=None,
        help="stop after this many markets per domain (default: all)",
    )


def main() -> None:
    """Parse arguments and dispatch."""
    parser = argparse.ArgumentParser(
        prog="vp",
        description="vibe-predict: LLM forecasting of Polymarket binary contracts.",
    )
    parser.add_argument(
        "--version", action="version", version=f"vp {version('vibe-predict')}"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser(
        "build-dataset", help="store resolved markets and their price histories"
    )
    _add_common(build)
    build.add_argument(
        "--no-history", action="store_true", help="skip the price-history requests"
    )

    snap = sub.add_parser("snapshot", help="write one snapshot of open markets")
    _add_common(snap)
    snap.add_argument(
        "--depth", type=int, default=5, help="book levels per side (default: 5)"
    )

    back = sub.add_parser("backtest", help="score forecasters on resolved markets")
    back.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    back.add_argument("--root", type=Path, default=Path("data"))
    back.add_argument(
        "--forecasters",
        nargs="+",
        default=["market", "constant"],
        type=_forecaster,
        help="forecasters to run: one of "
        + ", ".join(FORECASTER_NAMES)
        + ", signal:<id> or blend:<id>+<id>; market is the reference "
        "(default: market constant)",
    )
    back.add_argument(
        "--hours-before-close",
        type=float,
        default=24.0,
        help="cutoff this many hours before settlement (default: 24)",
    )
    back.add_argument(
        "--kinds", nargs="*", default=[], help="parsed kinds to include (default: all)"
    )
    back.add_argument("--max-markets", type=int, default=None)
    back.add_argument("--seed", type=int, default=0)
    back.add_argument("--fee-rate", type=float, default=0.0)
    back.add_argument(
        "--market-fees",
        action="store_true",
        help="charge each market's own taker fee; --fee-rate where none is stated",
    )
    back.add_argument("--half-spread", type=float, default=0.01)
    back.add_argument(
        "--min-edge", type=float, default=0.0, help="edge required to bet (default 0)"
    )
    back.add_argument(
        "--out", type=Path, default=None, help="report directory (default: under root)"
    )

    sig = sub.add_parser("signals", help="the signal library")
    sig_sub = sig.add_subparsers(dest="signals_command", required=True)
    sig_sub.add_parser("list", help="every signal with its metadata and hash")
    scheck = sig_sub.add_parser("check", help="the contribution checklist")
    scheck.add_argument("ids", nargs="*", help="signals to check (default: all)")
    scheck.add_argument(
        "--root", type=Path, default=Path("data"), help="where the benches are"
    )
    sbench = sig_sub.add_parser("bench", help="every signal against the market")
    sbench.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    sbench.add_argument("--root", type=Path, default=Path("data"))
    sbench.add_argument("--hours", type=float, default=24.0)
    sbench.add_argument("--window", default=None, help="YYYY-MM..YYYY-MM")
    sbench.add_argument("--max-markets", type=int, default=2000)
    sbench.add_argument("--seed", type=int, default=0)
    sbench.add_argument(
        "--blend", action="append", default=[], help="a blend, e.g. elo+platt_market"
    )

    evid = sub.add_parser("evidence", help="the evidence archive")
    evid_sub = evid.add_subparsers(dest="evidence_command", required=True)
    runs = evid_sub.add_parser(
        "weather-runs", help="point-in-time forecasts at every named station"
    )
    runs.add_argument("--root", type=Path, default=Path("data"))
    runs.add_argument("--domain", default=None, help="default: every such domain")
    runs.add_argument("--station", action="append", default=None)
    runs.add_argument("--lead-in", type=int, default=90)
    foot = evid_sub.add_parser("football", help="fixtures and results by season")
    foot.add_argument("--root", type=Path, default=Path("data"))
    foot.add_argument("--season", action="append", required=True, help="2025-26")
    chk = evid_sub.add_parser(
        "recheck", help="read recent point-in-time rows again and compare"
    )
    chk.add_argument("--root", type=Path, default=Path("data"))
    chk.add_argument("--days", type=int, default=30)
    ens = evid_sub.add_parser("ensemble", help="the ensemble for open markets")
    ens.add_argument("--root", type=Path, default=Path("data"))
    ens.add_argument("--domain", default=None, help="default: every such domain")

    shadow = sub.add_parser(
        "shadow", help="a public address's record as a report card (docs/shadow.md)"
    )
    shadow.add_argument("address")
    shadow.add_argument("--root", type=Path, default=Path("data"))
    shadow.add_argument("--max-activity", type=int, default=50_000)
    shadow.add_argument("--max-histories", type=int, default=300)
    shadow.add_argument("--out", type=Path, default=None, help="write the card here")

    strat = sub.add_parser("strategy", help="a strategy spec (JSON)")
    strat_sub = strat.add_subparsers(dest="strategy_command", required=True)
    strat_sub.add_parser("check", help="validate, render and hash").add_argument(
        "spec", type=Path
    )
    sdiff = strat_sub.add_parser("diff", help="what changed between two versions")
    sdiff.add_argument("old", type=Path)
    sdiff.add_argument("new", type=Path)
    sprev = strat_sub.add_parser("preview", help="what a spec would touch")
    sprev.add_argument("spec", type=Path)
    sprev.add_argument("--root", type=Path, default=Path("data"))
    seval = strat_sub.add_parser("eval", help="the compiler's held-out prompts")
    seval.add_argument("--cases", type=Path, default=Path("tests/evals/compiler.json"))
    seval.add_argument(
        "--live", action="store_true", help="ask the real model (needs a key)"
    )
    sback = strat_sub.add_parser("backtest", help="backtest a spec")
    sback.add_argument("spec", type=Path)
    sback.add_argument("--root", type=Path, default=Path("data"))
    sback.add_argument("--max-markets", type=int, default=None)
    sback.add_argument("--out", type=Path, default=None)

    paper = sub.add_parser("paper", help="paper trading")
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)
    prun = paper_sub.add_parser("run", help="one cycle: snapshot, forecast, order")
    _add_common(prun)
    prun.add_argument("--forecasters", nargs="+", default=["market", "constant"])
    prun.add_argument("--depth", type=int, default=5)
    prun.add_argument("--min-edge", type=float, default=0.0)
    psettle = paper_sub.add_parser("settle", help="settle resolved open positions")
    psettle.add_argument("--root", type=Path, default=Path("data"))
    pleak = paper_sub.add_parser("leakage", help="forward vs backtest scores")
    pleak.add_argument("--root", type=Path, default=Path("data"))
    pleak.add_argument("--domain", required=True, choices=sorted(DOMAINS))
    pleak.add_argument("--backtest", type=Path, required=True, help="backtest dir")

    ui = sub.add_parser("ui", help="serve the browser dashboard")
    ui.add_argument("--root", type=Path, default=Path("data"))
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)

    srv = sub.add_parser("serve", help="run the platform web service (Postgres)")
    srv.add_argument("--host", default="127.0.0.1")
    srv.add_argument("--port", type=int, default=8000)
    srv.add_argument(
        "--workers", type=int, default=1, help="web processes sharing the port"
    )

    dbp = sub.add_parser("db", help="the platform database")
    db_sub = dbp.add_subparsers(dest="db_command", required=True)
    db_sub.add_parser("migrate", help="apply pending migrations as the owner")

    sub.add_parser("setup", help="migrate the database and prepare the store")

    wrk = sub.add_parser("worker", help="run platform jobs (Postgres)")
    wrk.add_argument("--kinds", nargs="*", default=None, help="job kinds (default all)")
    wrk.add_argument("--concurrency", type=int, default=2)
    wrk.add_argument("--metrics-port", type=int, default=None)

    ing = sub.add_parser("ingest", help="run the market-data service (Postgres)")
    ing.add_argument("--domains", nargs="*", default=None, choices=sorted(DOMAINS))
    ing.add_argument("--metrics-port", type=int, default=None)
    ing.add_argument("--snapshot-minutes", type=float, default=15.0)
    ing.add_argument("--discover-minutes", type=float, default=10.0)

    jb = sub.add_parser("jobs", help="the job queue, for the operator")
    jb_sub = jb.add_subparsers(dest="jobs_command", required=True)
    jl = jb_sub.add_parser("list", help="recent jobs")
    jl.add_argument("--state", default=None)
    jl.add_argument("--kind", default=None)
    jl.add_argument("--limit", type=int, default=30)
    for name, text in (("show", "one job"), ("retry", "requeue a dead job")):
        jb_sub.add_parser(name, help=text).add_argument("job_id")
    for name, text in (("drain", "stop claiming a kind"), ("undrain", "resume a kind")):
        jb_sub.add_parser(name, help=text).add_argument("kind")
    jb_sub.add_parser("stats", help="queue depth and age by kind and state")

    adm = sub.add_parser("admin", help="operator commands")
    adm_sub = adm.add_subparsers(dest="admin_command", required=True)
    adm_sub.add_parser("halt", help="halt the platform").add_argument(
        "--reason", required=True
    )
    adm_sub.add_parser("resume", help="clear the platform halt")
    ap = adm_sub.add_parser("pause", help="pause one workspace")
    ap.add_argument("workspace")
    ap.add_argument("--reason", required=True)
    adm_sub.add_parser("unpause", help="clear a workspace pause").add_argument(
        "workspace"
    )
    adm_sub.add_parser("halts", help="the halts in force")
    ab = adm_sub.add_parser("budget", help="set a workspace's monthly model budget")
    ab.add_argument("workspace")
    ab.add_argument("usd")
    adm_sub.add_parser("costs", help="model spend this month").add_argument(
        "--month", default=None, help="YYYY-MM"
    )
    au = adm_sub.add_parser("unit-costs", help="cost per person-day by component")
    au.add_argument("--days", type=int, default=7)
    au.add_argument("--cpu-hour", type=float, default=None, help="$ per vCPU-hour")
    au.add_argument("--db-gb-month", type=float, default=None, help="$ per GB-month")
    ar = adm_sub.add_parser("refresh", help="refresh a domain's data now")
    ar.add_argument("domain", choices=sorted(DOMAINS))
    ar.add_argument("--what", nargs="+", default=["dataset", "snapshot"])
    aa = adm_sub.add_parser("archive", help="move old months to object storage")
    aa.add_argument("--before", required=True, help="YYYY-MM: archive months before it")
    adm_sub.add_parser("audit", help="verify the audit chain and show its tail")
    adm_sub.add_parser("evals", help="the evals harness over stored answers and runs")
    adm_sub.add_parser(
        "verify-ledgers", help="verify every paper ledger from its first entry (daily)"
    )

    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if args.command == "ui":
        from vp.ui.server import serve

        serve(args.root, args.host, args.port)
        return

    if args.command == "serve":
        from vp.platform.run import serve as serve_platform

        serve_platform(args.host, args.port, args.workers)
        return

    if args.command == "setup":
        from vp.platform.run import setup

        applied = setup()
        print("applied: " + ", ".join(applied) if applied else "up to date")
        return

    if args.command == "worker":
        from vp.platform.run import work

        work(args.kinds, args.concurrency, args.metrics_port)
        return

    if args.command == "ingest":
        from vp.platform.run import ingest

        ingest(
            args.domains,
            args.metrics_port,
            args.snapshot_minutes,
            args.discover_minutes,
        )
        return

    if args.command in ("jobs", "admin"):
        from vp.platform.console import operator_command

        operator_command(args)
        return

    if args.command == "db":
        from vp.platform.run import migrate_database

        applied = migrate_database()
        print("applied: " + ", ".join(applied) if applied else "up to date")
        return

    if args.command == "paper":
        ledger = Ledger(args.root / "paper" / "ledger.jsonl")
        broken = ledger.verify()
        if broken is not None:
            raise SystemExit(f"ledger chain broken at entry {broken}; refusing to run")
        if args.paper_command == "settle":
            print(settle(PolymarketSource(), ledger))
        elif args.paper_command == "leakage":
            rows = leakage.gaps(
                leakage.backtest_scores(args.backtest, args.root, args.domain),
                leakage.forward_scores(ledger),
            )
            print(leakage.summary(rows) if rows else "no forecaster settled in both")
        else:
            for name in args.domain:
                forecasters = [make_forecaster(f, name) for f in args.forecasters]
                counts = run_cycle(
                    DOMAINS[name],
                    forecasters,
                    PolymarketSource(),
                    args.root,
                    ledger,
                    depth=args.depth,
                    max_markets=args.max_markets,
                    min_edge=args.min_edge,
                )
                print(f"{name}: {counts}")
        return

    if args.command == "signals":
        _signals(args)
        return
    if args.command == "strategy":
        _strategy(args)
        return
    if args.command == "shadow":
        from vp.shadow.card import from_venue

        card = from_venue(
            args.address,
            args.root,
            cap=args.max_activity,
            max_histories=args.max_histories,
            progress=lambda f, m: print(f"{f:4.0%} {m}", file=sys.stderr),
        )
        text = json.dumps(card, indent=1)
        if args.out:
            args.out.write_text(text)
        print(
            text
            if not args.out
            else json.dumps(card["diagnostics"]["overall"], indent=1)
        )
        return
    if args.command == "evidence":
        import os

        from vp.sources import backfill

        # The paid plan's key, when there is one (docs/evidence.md, F9).
        key = os.environ.get("VP_OPEN_METEO_KEY") or None
        if args.evidence_command == "weather-runs":
            out = backfill.weather_runs(
                args.root,
                args.domain,
                key=key,
                lead_in=args.lead_in,
                only=args.station,
            )
        elif args.evidence_command == "recheck":
            out = backfill.recheck(args.root, days=args.days, key=key)
        elif args.evidence_command == "football":
            out = backfill.football(args.root, args.season)
        else:
            out = backfill.ensembles(args.root, args.domain, key=key)
        print(json.dumps(out, indent=1))
        return
    if args.command == "backtest":
        config = BacktestConfig(
            domain=args.domain,
            forecasters=tuple(args.forecasters),
            hours_before_close=args.hours_before_close,
            kinds=tuple(args.kinds),
            max_markets=args.max_markets,
            seed=args.seed,
            fee_rate=args.fee_rate,
            market_fees=args.market_fees,
            half_spread=args.half_spread,
            min_edge=args.min_edge,
        )
        stamp = utc_now_iso().replace("-", "").replace(":", "")
        out = args.out or args.root / "backtests" / args.domain / stamp
        run_backtest(config, args.root, out)
        print((out / "summary.md").read_text())
        print(f"written: {out}")
        return

    source = PolymarketSource()

    for name in args.domain:
        domain = DOMAINS[name]
        if args.command == "build-dataset":
            report = build_resolved_dataset(
                domain,
                source,
                args.root,
                max_markets=args.max_markets,
                with_history=not args.no_history,
            )
            print(report.summary())
        else:
            path, count = collect_snapshot(
                domain,
                source,
                args.root,
                depth=args.depth,
                max_markets=args.max_markets,
            )
            print(f"{name}: {count} markets written to {path}")


def _strategy(args: argparse.Namespace) -> None:
    from vp.strategy import run
    from vp.strategy.spec import Spec, diff, render, spec_hash, validate

    def load(path: Path) -> Spec:
        return Spec.model_validate_json(path.read_text())

    if args.strategy_command == "eval":
        from vp.strategy import evals

        cases = evals.load_cases(args.cases)
        if args.live:
            import anthropic

            client = anthropic.Anthropic()
        else:
            client = evals.Recorded(cases)
        print(json.dumps(evals.compiler(cases, client), indent=1))
        return
    if args.strategy_command == "diff":
        for path, old, new in diff(load(args.old), load(args.new)):
            print(f"{path}: {old!r} -> {new!r}")
        return
    spec = load(args.spec)
    problems = validate(spec)
    print("\n".join(render(spec)))
    print(f"version {spec_hash(spec)}")
    for problem in problems:
        print(f"problem: {problem}")
    if problems:
        raise SystemExit(1)
    if args.strategy_command == "preview":
        from vp.strategy.preview import preview

        print(json.dumps(preview(spec, args.root).as_json(), indent=1))
    if args.strategy_command == "backtest":
        out = args.out or args.root / "strategies" / spec_hash(spec)[:12]
        results = run.backtest(spec, args.root, out, max_markets=args.max_markets)
        for domain, result in results.items():
            print(f"{domain}: {result.common} markets scored; {out / domain}")
            print((out / domain / "summary.md").read_text())


def _forecaster(name: str) -> str:
    from vp.forecast import known

    if not known(name):
        raise argparse.ArgumentTypeError(f"no forecaster, signal or blend {name!r}")
    return name


def _signals(args: argparse.Namespace) -> None:
    import tempfile

    from vp.signals import gates, registry

    if args.signals_command == "list":
        print(json.dumps(registry.manifest(), indent=1))
        return
    if args.signals_command == "check":
        failed = False
        benched = {
            k
            for f in (args.root / "signals" / "bench").glob("*.json")
            for k in json.loads(f.read_text())["signals"]
        }
        with tempfile.TemporaryDirectory() as tmp:
            plain, guarded = gates.fixtures(Path(tmp))
            for signal_id in args.ids or registry.ids():
                make = lambda i=signal_id: registry.load(i)  # noqa: E731
                problems = (
                    gates.purity(make())
                    + gates.metadata(make())
                    + gates.cutoff_sentinel(make, plain, guarded)
                    + ([] if signal_id in benched else ["no bench on any domain"])
                )
                failed |= bool(problems)
                print(
                    f"{signal_id}: {'passes' if not problems else '; '.join(problems)}"
                )
        raise SystemExit(1 if failed else 0)
    from vp.signals.bench import bench

    window = tuple(args.window.split("..")) if args.window else None
    out = bench(
        args.root,
        args.domain,
        hours=args.hours,
        window=window,  # type: ignore[arg-type]
        max_markets=args.max_markets,
        seed=args.seed,
        blends=args.blend,
    )
    path = args.root / "signals" / "bench" / f"{args.domain}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1))
    for signal_id, r in out["signals"].items():
        adv = r.get("advantage")
        span = f"[{adv['low']:+.4f}, {adv['high']:+.4f}]" if adv else ""
        print(f"{signal_id:18} n={r['n']:5} {r['verdict']:8} {span}")
    print(f"written to {path}")
