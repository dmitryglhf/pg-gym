from postgres_gym.core.reward import score


def solved_record():
    return {
        "gates": {
            "nonempty_diff": {"ok": True},
            "no_test_edits": {"ok": True},
        },
        "build": {"ok": True},
        "install": {"ok": True},
        "callable": {"ok": True},
        "check_names": ["callable"],
        "check": {"total": 10},
        "func_ok": True,
        "noregress_ok": True,
        "pass": True,
    }


def test_solved_is_one():
    graded = score(solved_record())
    assert graded.reward == 1.0
    assert graded.rung == "noregress_ok"


def test_solved_without_named_checks_is_one():
    record = solved_record()
    record["check_names"] = []
    del record["callable"]

    graded = score(record)

    assert graded.reward == 1.0
    assert graded.rung == "noregress_ok"
    assert "checks" not in graded.reached


def test_missing_check_names_is_unusable():
    record = solved_record()
    del record["check_names"]

    graded = score(record)

    assert graded.reward is None
    assert not graded.usable


def test_test_edit_is_hard_zero():
    record = solved_record()
    record["gates"]["no_test_edits"] = {"ok": False, "violations": ["src/test/x"]}
    graded = score(record)
    assert graded.reward == 0.0
    assert graded.blocked_by == "no_test_edits"


def test_zero_tests_cannot_reach_func_ok():
    record = solved_record()
    record["check"]["total"] = 0
    graded = score(record)
    assert graded.reward == 0.6
    assert graded.blocked_by == "func_ok"
