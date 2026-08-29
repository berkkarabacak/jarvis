from app.runner.parse import parse_job_output, strip_code_fences


def test_parse_plain_json():
    out = parse_job_output('{"result": "hello", "memory": "# mem"}')
    assert out.result == "hello"
    assert out.memory == "# mem"


def test_parse_fenced_json():
    text = """```json
{"result": {"ok": true}, "memory": "kept"}
```"""
    out = parse_job_output(text)
    assert out.result == {"ok": True}
    assert out.memory == "kept"


def test_strip_fences():
    assert strip_code_fences('```\n{"a":1}\n```') == '{"a":1}'


def test_parse_memory_optional():
    out = parse_job_output('{"result": 1}')
    assert out.result == 1
    assert out.memory == ""
    assert out.update_memory is True


def test_parse_rejects_missing_result():
    try:
        parse_job_output('{"memory": "only"}')
        assert False, "expected error"
    except ValueError as exc:
        assert "result" in str(exc).lower()
