"""
Offline robustness test for Forge's write-time defenses.

Validates that `_normalize_llm_page_output` rejects all known LLM failure
modes WITHOUT calling any model. Runs in <2s with zero cost. Intended to
be re-run by hand after any change to `forge/_wiki.py`, `forge/_llm.py`
or `forge/_lint.py`.

Usage:
  python test_forge_robustness.py

Exit code 0 on success, 1 on first failure.
"""
import re
import sys

import forge._wiki as wiki
import forge._lint as lint


FAILED = 0
PASSED = 0


def expect_ok(label: str, content: str):
    global PASSED, FAILED
    try:
        out = wiki._normalize_llm_page_output(content)
        assert out.startswith("---\n"), "output should start with frontmatter"
        assert "\n---\n" in out, "output should have a closing ---"
        print(f"  PASS  {label}")
        PASSED += 1
    except Exception as e:
        print(f"  FAIL  {label}: unexpectedly raised {type(e).__name__}: {e}")
        FAILED += 1


def expect_reject(label: str, content: str, expected_msg: str | None = None):
    global PASSED, FAILED
    try:
        wiki._normalize_llm_page_output(content)
        print(f"  FAIL  {label}: should have raised, but accepted")
        FAILED += 1
    except ValueError as e:
        if expected_msg and expected_msg not in str(e):
            print(f"  FAIL  {label}: raised but message wrong: got {e!r}, expected to contain {expected_msg!r}")
            FAILED += 1
        else:
            print(f"  PASS  {label}: rejected as expected ({e})")
            PASSED += 1
    except Exception as e:
        print(f"  FAIL  {label}: raised {type(e).__name__} instead of ValueError: {e}")
        FAILED += 1


# ── Group 1: should be accepted ──────────────────────────────────────────────

print("Group 1 — valid output (must be accepted):")
expect_ok("clean output", """---
title: "Working Memory"
slug: working-memory
summary: "A multicomponent system for active maintenance and manipulation."
tags: [working-memory, central-executive, attention]
---

# Working Memory

> Some body content here.
""")

expect_ok("code-fence wrapper", """```markdown
---
title: "X"
slug: x
summary: "Y"
tags: [a, b, c]
---

# X
body
```""")

expect_ok("preamble before frontmatter", """Here is the wiki page:

---
title: "X"
slug: x
summary: "Y"
tags: [a, b, c]
---

# X
body
""")

expect_ok("title with colon (unquoted, auto-repaired)", """---
title: Chomsky (1959): critiques
slug: chomsky-1959
summary: "A summary"
tags: [chomsky, linguistics, behaviorism]
---

# X
body
""")

expect_ok("tags with hyphenated multi-word entries", """---
title: "X"
slug: x
summary: "A summary"
tags: [parallel-distributed-processing, machine-learning, attention]
---

# X
body
""")

# ── Group 2: must be rejected (LLM template leakage) ─────────────────────────

print("\nGroup 2 — must be rejected:")
expect_reject(
    "summary = old REPLACE WITH placeholder",
    """---
title: "X"
slug: x
summary: "REPLACE WITH ONE SENTENCE — must be a single quoted string, NEVER a YAML list or bullet block."
tags: [a, b, c]
---

# X
body
""",
    expected_msg="template placeholder",
)

expect_reject(
    "summary = new <<WRITE>> placeholder",
    """---
title: "X"
slug: x
summary: "<<WRITE_ONE_SENTENCE_SUMMARY_FROM_THE_SOURCE>>"
tags: [a, b, c]
---

# X
body
""",
    expected_msg="template placeholder",
)

expect_reject(
    "tags = old [3-5 relevant lowercase keywords] placeholder",
    """---
title: "X"
slug: x
summary: "A summary"
tags: [3-5 relevant lowercase keywords]
---

# X
body
""",
    expected_msg="template placeholder",
)

expect_reject(
    "tags = new <<TAG1>> placeholders",
    """---
title: "X"
slug: x
summary: "A summary"
tags: [<<TAG1>>, <<TAG2>>, <<TAG3>>]
---

# X
body
""",
    expected_msg="template placeholder",
)

expect_reject(
    "tags = instructional string (too many words)",
    """---
title: "X"
slug: x
summary: "A summary"
tags: ["replace this with three to five real keywords from the body"]
---

# X
body
""",
)

expect_reject(
    "title contains REPLACE WITH",
    """---
title: "REPLACE WITH a real title"
slug: x
summary: "A summary"
tags: [a, b, c]
---

# X
body
""",
    expected_msg="template placeholder",
)

expect_reject(
    "empty content",
    "",
    expected_msg="empty",
)

expect_reject(
    "no frontmatter at all",
    "Just some text without frontmatter.",
    expected_msg="frontmatter opener",
)

expect_reject(
    "opener but no closing",
    "---\ntitle: X\nno closer",
    expected_msg="closing",
)


# ── Group 3: stale `### See Also` is stripped from body ──────────────────────

print("\nGroup 3 — stale `### See Also` cleanup:")

stale_input = """---
title: "X"
slug: x
summary: "A summary"
tags: [a, b, c]
---

# X

Some body.

### See Also

_To be linked after compilation._

## See Also

_To be linked after compilation._

## Sources
- bla
"""

try:
    out = wiki._normalize_llm_page_output(stale_input)
    # Body should still have the `## See Also` (two hashes) but NOT the
    # `### See Also` (three hashes) carrying the placeholder.
    assert "### See Also" not in out, "stale ### See Also should have been stripped"
    assert "## See Also" in out, "proper ## See Also must remain"
    print("  PASS  stale ### See Also stripped, ## See Also preserved")
    PASSED += 1
except Exception as e:
    print(f"  FAIL  stale ### See Also cleanup: {e}")
    FAILED += 1


# ── Group 4: lint Q3 detection of dirty existing pages ───────────────────────

print("\nGroup 4 — lint Q3 detection on synthetic page list:")

dirty_page = {
    "path": None,
    "rel_path": "wiki/concepts/dirty-summary.md",
    "text": "",
    "body": "",
    "frontmatter": {
        "title": "Some Real Title",
        "slug": "dirty-summary",
        "category": "concept",
        "summary": "REPLACE WITH ONE SENTENCE — must be a single quoted string",
        "tags": ["a", "b", "c"],
    },
}
dirty_tags_page = {
    "path": None,
    "rel_path": "wiki/concepts/dirty-tags.md",
    "text": "",
    "body": "",
    "frontmatter": {
        "title": "Another Title",
        "slug": "dirty-tags",
        "category": "concept",
        "summary": "Real summary.",
        "tags": ["3-5 relevant lowercase keywords"],
    },
}
stale_see_also_page = {
    "path": None,
    "rel_path": "wiki/concepts/stale-see-also.md",
    "text": "",
    "body": "\n### See Also\n\n_To be linked after compilation._\n",
    "frontmatter": {
        "title": "Title",
        "slug": "stale-see-also",
        "category": "concept",
        "summary": "Real summary.",
        "tags": ["a", "b", "c"],
    },
}
clean_page = {
    "path": None,
    "rel_path": "wiki/concepts/clean.md",
    "text": "",
    "body": "Body without stale section.",
    "frontmatter": {
        "title": "Clean Title",
        "slug": "clean",
        "category": "concept",
        "summary": "A real summary in one sentence.",
        "tags": ["machine-learning", "attention", "memory"],
    },
}

issues = []
lint._check_q3_template_leakage(
    [dirty_page, dirty_tags_page, stale_see_also_page, clean_page], issues, fix=False
)
q3_codes = {(i["path"], i["severity"]) for i in issues if i.get("code") == "Q3"}
expected = {
    ("wiki/concepts/dirty-summary.md", "critical"),
    ("wiki/concepts/dirty-tags.md", "critical"),
    ("wiki/concepts/stale-see-also.md", "warning"),
}
if q3_codes == expected:
    print(f"  PASS  Q3 flagged 3 dirty pages, no false positive on the clean one")
    PASSED += 1
else:
    print(f"  FAIL  Q3 mismatch: got {q3_codes!r}, expected {expected!r}")
    FAILED += 1


# ── Summary ──────────────────────────────────────────────────────────────────

print()
print(f"Total: {PASSED} passed, {FAILED} failed")
sys.exit(0 if FAILED == 0 else 1)
