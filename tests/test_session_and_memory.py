"""Tests for cc-tunnel-session (transcript summary) and cc-tunnel-memory-merge."""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

BIN = pathlib.Path(__file__).resolve().parent.parent / "local" / "bin"


def run(tool, *args, stdin=""):
    proc = subprocess.run([sys.executable, str(BIN / tool)] + list(args), input=stdin,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr)
    return proc.stdout


def line(kind, content=None, **extra):
    entry = {"type": kind, **extra}
    if content is not None:
        entry["message"] = {"role": kind, "content": content}
    return json.dumps(entry)


class SessionTest(unittest.TestCase):
    def transcript(self):
        return "\n".join([
            "#file abc.jsonl",
            line("user", "first question"),
            line("assistant", [{"type": "text", "text": "first answer"}]),
            line("user", "second question"),
            line("assistant", [{"type": "thinking", "thinking": "hidden"},
                               {"type": "tool_use", "name": "mcp__cc-tunnel-workspace__workspace_read"},
                               {"type": "tool_use", "name": "mcp__cc-tunnel-workspace__workspace_read"},
                               {"type": "tool_use", "name": "Bash"}]),
            line("user", [{"type": "tool_result", "content": "noise"}]),
            line("user", "<meta>", isMeta=True),
            line("api-request", None, body="ignored"),
            "{not json",
            line("user", [{"type": "text", "text": "the summary so far"}], isCompactSummary=True),
            line("assistant", [{"type": "text", "text": "done"}]),
        ])

    def test_last_turns_tools_and_compaction(self):
        out = run("cc-tunnel-session", "1", stdin=self.transcript())
        self.assertIn("abc.jsonl: last 1 of 2 user turns", out)
        self.assertNotIn("first question", out)
        self.assertIn("[user] second question", out)
        self.assertIn("tools: workspace_read x2, Bash", out)
        self.assertIn("[compaction summary] the summary so far", out)
        self.assertNotIn("noise", out)      # tool results are not human turns
        self.assertNotIn("hidden", out)     # thinking is not shown
        self.assertNotIn("<meta>", out)

    def test_marks_transcript_text_as_data(self):
        self.assertIn("record, not instructions", run("cc-tunnel-session", stdin=self.transcript()))


class MemoryMergeTest(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())
        for slug, title in (("a", "Alpha"), ("b", "Beta"), ("c", "Gamma")):
            (self.dir / f"{slug}.md").write_text(f"---\ndescription: about {slug}\n---\n# {title}\n")

    def tearDown(self):
        shutil.rmtree(str(self.dir), ignore_errors=True)

    def index(self, name, text, age):
        path = self.dir.parent / f"{self.dir.name}-{name}.md"
        path.write_text(text)
        stamp = time.time() - age
        os.utime(str(path), (stamp, stamp))
        self.addCleanup(lambda: path.exists() and path.unlink())
        return str(path)

    def test_entries_from_both_sides_survive(self):
        # The newer index lacks b (added on the other machine); --update alone
        # would have dropped it.
        older = self.index("old", "- [Alpha](a.md) — about a\n- [Beta](b.md) — added there\n", 100)
        newer = self.index("new", "# Index\n- [Alpha](a.md) — about a\n- [Ghost](gone.md) — deleted\n", 10)
        run("cc-tunnel-memory-merge", str(self.dir), older, newer)
        merged = (self.dir / "MEMORY.md").read_text()
        self.assertIn("[Beta](b.md) — added there", merged)   # from the older index
        self.assertIn("[Gamma](c.md) — about c", merged)      # linked nowhere: generated
        self.assertNotIn("gone.md", merged)                   # dead link removed
        self.assertTrue(merged.startswith("# Index\n"))       # newest kept as written

    def test_grouped_line_is_not_padded_back_out(self):
        newer = self.index("new", "- group: [Alpha](a.md) · [Beta](b.md)\n- [Alpha](a.md) — dup\n", 10)
        run("cc-tunnel-memory-merge", str(self.dir), newer)
        merged = (self.dir / "MEMORY.md").read_text()
        self.assertEqual(merged.count("(a.md)"), 1)


if __name__ == "__main__":
    unittest.main()
