from __future__ import annotations

import time
import traceback
from datetime import UTC, datetime

from postgres_gym import settings, stands
from postgres_gym.core import agents, payload, recall, records, reward, scoring
from postgres_gym.core import judge as judging
from postgres_gym.core import langfuse as lf
from postgres_gym.core.activity import emit


def _agent_calls(meta: dict, since_ms: int) -> dict | None:
    if (meta or {}).get("profile") != "opencode":
        return None
    from postgres_gym.core import opencode_store

    try:
        return opencode_store.summarise(since_ms=since_ms)
    except Exception as exc:  # noqa: BLE001
        return {"source": "opencode", "error": f"{type(exc).__name__}: {exc}"}


def run_one(
    suite,
    name: str,
    agent_name: str,
    *,
    keep_tree: bool = False,
    judge: bool = False,
    judge_model: str | None = None,
    judge_base_url: str | None = None,
    **agent_kwargs,
) -> dict:
    stand = stands.load(suite.stand)
    task, oracle = suite.load(name)
    started = time.time()

    trace_id = lf.new_trace_id()
    if agent_name.startswith("cli:"):
        agent_kwargs.setdefault(
            "extra_env",
            lf.trace_env(
                trace_id,
                func=name,
                agent=agent_name,
                level=agent_kwargs.get("level", "L0"),
                metadata={"pg_sha": stand.anchor()[:12], "harness": "postgres_gym"},
            ),
        )
    agent = agents.make(agent_name, **agent_kwargs)

    record: dict = {
        "func": name,
        "suite": suite.id,
        "stand": stand.name,
        "agent": agent_name,
        "trace_id": trace_id,
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    if meta := payload.metadata():
        if meta.get("task_hash"):
            record["task_hash"] = meta["task_hash"]
        if meta.get("execution"):
            record["execution"] = meta["execution"]

    emit("phase", phase="preparing", task=name)
    origin = stand.reset()

    if base := suite.base(oracle):
        stand.reset_to(base)
        record["base"] = base[:12]
    patch_text = suite.mutation(oracle)
    applied = stand.apply(patch_text)
    if not applied.ok:
        record["error"] = f"mutation did not apply: {applied.output[-2000:]}"

        stand.reset_to(origin)
        return record

    mutation_changed = stand.changed_files()
    stand.commit_baseline(f"postgres_gym: {name}")

    emit("phase", phase="prebuild", task=name)
    pre = stand.build(mutation_changed)
    pre_install = stand.install() if pre.ok else pre
    if not (pre.ok and pre_install.ok):
        broken = pre if not pre.ok else pre_install
        record["error"] = f"mutated tree did not build: {broken.output[-2000:]}"
        stand.reset_to(origin)
        return record
    record["prebuild"] = {"seconds": round(pre.seconds + pre_install.seconds, 1)}

    with stand.hide(suite.hide(task, oracle)) as hidden:
        origin = stand.sever_history()
        agent_started_ms = int(time.time() * 1000)
        emit("phase", phase="agent", task=name)
        record["agent_meta"] = agent.run(task, oracle, suite=suite, stand=stand)
        if calls := _agent_calls(record["agent_meta"], agent_started_ms):
            record["agent_calls"] = calls

        changed = stand.changed_files()
        diff_text = stand.diff()

    record["hidden_tests"] = {"files": hidden.files, "recreated": hidden.recreated}
    record["gates"] = scoring.gates(stand, changed, hidden.recreated)
    record["diff_size"] = len(diff_text.splitlines())

    record["recall"] = recall.measure(patch_text, diff_text)

    record["diff"] = diff_text

    checks = list(suite.check_names)
    record["check_names"] = checks
    emit("phase", phase="build", task=name)
    b = stand.build(changed)
    record["build"] = {"ok": b.ok, "seconds": round(b.seconds, 1)}
    if not b.ok:
        record["build"]["tail"] = b.output[-4000:]
        record["func_ok"] = record["noregress_ok"] = False
        for check_name in checks:
            record[check_name] = {"ok": False}
    else:
        inst = stand.install()
        record["install"] = {"ok": inst.ok, "seconds": round(inst.seconds, 1)}
        record.update(suite.checks(task, stand))
        expected = suite.expected_failures(oracle)
        emit("phase", phase="tests", task=name)
        reports = [stand.test()]
        targeted = suite.test_names(oracle)
        statuses = getattr(reports[0], "statuses", None) or {}
        if targeted and not all(statuses.get(name) in ("passed", "failed")
                                for name in targeted):
            reports.append(stand.test(targeted))
        report = scoring.combine_reports(reports)
        record.update(scoring.outcome(stand, report, expected))

    if judge:
        try:
            record["judge"] = judging.review(
                suite.specification(task),
                suite.reference(oracle),
                diff_text,
                model=judge_model,
                base_url=judge_base_url,
                key=payload.judge_key(),
            )
        except Exception as exc:  # noqa: BLE001
            record["judge"] = {"error": type(exc).__name__, "detail": str(exc)[:500]}

    emit("phase", phase="scoring", task=name)
    record["gates_ok"] = all(g["ok"] for g in record["gates"].values())
    record["pass"] = scoring.verdict(record, checks)
    graded = reward.score(record, checks)
    record["reward"] = graded.reward
    record["reward_rung"] = graded.rung
    record["seconds"] = round(time.time() - started, 1)

    if lf.enabled():
        record["langfuse"] = lf.publish(trace_id, record, task)

    if not keep_tree:
        stand.reset_to(origin)

        if stand.restore_history():
            stand.reset()
    return record


def guarded(suite, name: str, agent: str, **kwargs) -> dict:
    try:
        return run_one(suite, name, agent, **kwargs)
    except Exception as exc:  # noqa: BLE001
        record = {
            "func": name,
            "suite": suite.id,
            "agent": agent,
            "pass": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc()[-4000:],
        }
        try:
            stand = stands.load(suite.stand)
            if stand.restore_history():
                stand.reset()
            else:
                stand.reset_to()
        except Exception as restore:  # noqa: BLE001
            record["restore_error"] = f"{type(restore).__name__}: {restore}"
        return record


def verify(suite, name: str) -> dict:
    rec = run_one(suite, name, "noop")
    check = rec.get("check", {})
    failed = check.get("failed", [])

    if rec.get("error"):
        status = "mutation_failed"
    elif not rec.get("build", {}).get("ok"):
        status = "build_failed"
    elif not rec.get("install", {}).get("ok", True):
        status = "install_failed"
    elif not check.get("total"):
        status = "check_did_not_run"
    elif failed:
        status = "usable"
    else:
        status = "no_coverage"

    suite.record_verification(name, status, check)
    return {
        "func": name,
        "status": status,
        "failing_tests": failed,
        "usable": status == "usable",
        "tests_run": check.get("total", 0),
        "build_ok": rec.get("build", {}).get("ok"),
        "seconds": rec.get("seconds"),
        "tail": (
            rec.get("error") or rec.get("build", {}).get("tail") or check.get("tail")
        ),
    }


def sweep(
    suite,
    agent: str,
    level: str,
    *,
    index: int | None = None,
    judge: bool = False,
    resume: str | None = None,
    **kwargs,
) -> list[dict]:
    names = suite.runnable()
    if not names:
        raise SystemExit("no runnable tasks: run `prepare` and `verify` first")

    if index is not None:
        if not 0 <= index < len(names):
            listing = "\n".join(f"  {i}  {n}" for i, n in enumerate(names))
            raise SystemExit(f"no task at index {index}. Available:\n{listing}")
        names = [names[index]]
    if resume:
        done = records.done_since(agent, level, resume)
        skipped = [n for n in names if n in done]
        names = [n for n in names if n not in done]
        print(f"resume: {len(skipped)} already done, {len(names)} to go", flush=True)
        if not names:
            return []

    written = []
    for position, name in enumerate(names, 1):
        print(f"[{position}/{len(names)}] {name} · {agent} · {level}", flush=True)
        agent_kwargs = {} if agent in agents.REGISTRY else {"level": level}
        record = guarded(suite, name, agent, judge=judge, **agent_kwargs, **kwargs)
        records.save(record, name, agent, level)
        written.append(record)
        print(
            f"    {'PASS' if record.get('pass') else 'fail'} · "
            f"{record.get('seconds', '?')}s"
            f"{' · ' + record['error'] if record.get('error') else ''}",
            flush=True,
        )
    return written


def scored_run_is_allowed(agent: str) -> None:
    if not agent.startswith("cli:") or settings.DISPOSABLE_GIT:
        return
    raise SystemExit(
        "refusing to score an agent on a stand whose git directory is not "
        "disposable: the pre-sever history would sit next to it, readable. "
        "Run in a container (`just bench`), or set POSTGRES_GYM_DISPOSABLE_GIT=1 if "
        "this checkout really is throwaway."
    )


def require_provider_key(agent: str) -> None:
    if (
        not agent.startswith("cli:")
        or not settings.REQUIRE_MARKOV_KEY
        or settings.PROVIDER_KEY
    ):
        return
    raise SystemExit(
        f"{settings.MARKOV_KEY_ENV} is not set. A scored run needs the provider "
        f"key; set MARKOV_API_KEY in .env (it reaches the container as "
        f"PGPRO_API_KEY) or set POSTGRES_GYM_REQUIRE_MARKOV_KEY=0 to run keyless."
    )


def print_summary(written: list[dict]) -> None:
    from postgres_gym.core import report

    report.render_all(written, report.console())
