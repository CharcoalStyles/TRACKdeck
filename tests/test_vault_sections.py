from utils.vault import append_to_section, replace_section

BODY = """## People
- Alice

## Career
Works at Acme.
"""


def test_append_to_section_adds_after_existing_content():
    result = append_to_section(BODY, "People", "- Bob")
    assert result == "## People\n- Alice\n- Bob\n\n## Career\nWorks at Acme.\n"


def test_append_to_section_is_case_insensitive_and_does_not_duplicate_heading():
    # A differently-cased request ("people" vs "## People") must match the
    # existing section, not create a second, unreachable one.
    result = append_to_section(BODY, "people", "- Bob")
    assert result.count("## People") == 1
    assert "## people" not in result


def test_append_to_section_does_not_leak_into_next_section():
    result = append_to_section(BODY, "People", "- Bob")
    assert "Works at Acme." in result
    career_start = result.index("## Career")
    assert "Bob" not in result[career_start:]


def test_append_to_section_creates_missing_heading_at_end():
    result = append_to_section(BODY, "Health", "No known conditions.")
    assert result.endswith("## Health\nNo known conditions.\n")
    assert "## People" in result and "## Career" in result


def test_replace_section_only_touches_its_own_span():
    result = replace_section(BODY, "People", "- Carol")
    assert result == "## People\n- Carol\n\n## Career\nWorks at Acme.\n"


def test_replace_section_creates_missing_heading():
    result = replace_section(BODY, "Health", "No known conditions.")
    assert result.endswith("## Health\nNo known conditions.\n")
    assert "Works at Acme." in result
