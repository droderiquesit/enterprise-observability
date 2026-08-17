"""Policy lint passes on the committed policy; runbook templates carry every
mandatory section; renderer is deterministic."""
import publish_runbooks as pr
import validate_policy as vp
import obs_common as oc


def test_policy_lint_clean():
    assert vp.lint() == []


def test_runbook_template_sections_enforced():
    src = oc.REPO_ROOT / "platform" / "runbooks" / "slo-error-budget-burn.md"
    assert pr.validate_template(src.read_text()) == []


def test_runbook_template_missing_section_fails():
    text = "# Runbook: X\n## Purpose and affected service\nonly one section"
    errs = pr.validate_template(text)
    assert len(errs) == len(pr.SECTION_ORDER) - 1


def test_runbook_render_deterministic_with_hash():
    src = (oc.REPO_ROOT / "platform" / "runbooks" / "slo-error-budget-burn.md").read_text()
    c1, c2 = pr.render_cells(src), pr.render_cells(src)
    assert c1 == c2
    assert "content_hash:" in c1[-1]["attributes"]["definition"]["text"]
