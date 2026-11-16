import compare


def test_baseline_score_coin_flip_is_zero_and_sure_right_is_100():
    assert abs(compare.baseline_score(0.5, True)) < 1e-9
    assert abs(compare.baseline_score(0.999999, True) - 100) < 0.01
    assert compare.baseline_score(0.9, False) < compare.baseline_score(0.1, False)


def test_brier():
    assert compare.brier(1.0, True) == 0 and compare.brier(0.0, True) == 1


def test_bootstrap_range_contains_the_mean_difference():
    a = [10, 12, 8, 11, 9, 10, 13, 7]
    b = [9, 11, 9, 10, 8, 10, 12, 8]
    m, lo, hi = compare.boot_diff(a, b)
    assert lo <= m <= hi


def test_report_compares_only_questions_every_arm_answered(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "ROOT", tmp_path)
    rows = {"m1|ours": [dict(q=1, yes=True, p=0.8), dict(q=2, yes=False, p=0.3)],
            "m2|ours": [dict(q=1, yes=True, p=0.6)]}
    compare.write_report(rows, 1, False, 0.42)
    text = (tmp_path / "docs" / "model-choice.md").read_text()
    assert "1 resolved binary questions" in text and "$0.42" in text
