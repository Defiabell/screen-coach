import history


def test_append_and_load_recent_most_recent_first(tmp_path):
    p = tmp_path / "history.jsonl"
    history.append_entry(p, {"sentence": "one"})
    history.append_entry(p, {"sentence": "two"})

    recent = history.load_recent(p, limit=10)

    assert [e["sentence"] for e in recent] == ["two", "one"]


def test_load_recent_missing_file_and_corrupt_line(tmp_path):
    p = tmp_path / "history.jsonl"
    assert history.load_recent(p) == []
    p.write_text('{"sentence": "ok"}\nnot json\n')
    assert [e["sentence"] for e in history.load_recent(p)] == ["ok"]
