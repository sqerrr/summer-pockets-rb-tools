from __future__ import annotations

from conftest import run


def test_empty_project_commands_are_safe(project):
    run(
        project,
        "tools/vnctl.py",
        "init",
        "--title",
        "Empty Project",
        "--source-language",
        "source",
        "--target-language",
        "target",
    )
    validate = run(project, "tools/vnctl.py", "validate")
    assert "0 errors" in validate.stdout
    run(project, "tools/vnctl.py", "index")
    stats = run(project, "tools/vnctl.py", "stats")
    assert "Segments: 0" in stats.stdout
    questions = run(project, "tools/vnctl.py", "questions")
    assert "0 total" in questions.stdout
    brief = run(project, "tools/vnctl.py", "brief")
    assert "Round trip verified: no" in brief.stdout
    assert "private_reason" not in brief.stdout
    run(project, "tools/validate_skills.py")
