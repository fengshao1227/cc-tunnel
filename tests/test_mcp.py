"""End-to-end tests for cc-tunnel-mcp: each test talks JSON-RPC to the real server.

Run with the interpreter a non-interactive SSH session would use on macOS,
which is the one that matters:

    /usr/bin/python3 -m unittest discover -s tests -v
"""
import json
import os
import pathlib
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SERVER = pathlib.Path(__file__).resolve().parent.parent / "local" / "bin" / "cc-tunnel-mcp"
HAS_RG = any(p and pathlib.Path(p).exists() for p in (shutil.which("rg"), "/opt/homebrew/bin/rg", "/usr/local/bin/rg"))


class Server:
    """One MCP session: a server process and a line-oriented JSON-RPC client."""

    def __init__(self, root: pathlib.Path, cache: pathlib.Path):
        env = dict(os.environ, XDG_CACHE_HOME=str(cache))
        self.proc = subprocess.Popen([sys.executable, str(SERVER), "--root", str(root)], env=env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     universal_newlines=True, bufsize=1)
        self.next_id = 0

    def request(self, method, params=None):
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.next_id, "method": method,
                                          "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def notify(self, method):
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.proc.stdin.flush()

    def call(self, tool, **arguments):
        reply = self.request("tools/call", {"name": tool, "arguments": arguments})
        result = reply["result"]
        return result["content"][0]["text"], bool(result.get("isError"))

    def close(self):
        try:
            self.proc.stdin.close()
        except BrokenPipeError:  # the test already killed it
            pass
        self.proc.wait(timeout=10)
        self.proc.stdout.close()
        self.proc.stderr.close()


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.root = self.tmp / "project"
        self.cache = self.tmp / "cache"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text("one\ntwo\nthree\ntwo\n")
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.close()
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def server(self):
        server = Server(self.root, self.cache)
        self.servers.append(server)
        server.request("initialize", {"protocolVersion": "2024-11-05"})
        server.notify("notifications/initialized")
        return server

    # ---- protocol -------------------------------------------------------

    def test_lists_every_tool(self):
        tools = {t["name"] for t in self.server().request("tools/list")["result"]["tools"]}
        self.assertEqual(tools, {"workspace_status", "workspace_read", "workspace_find", "workspace_patch",
                                 "workspace_write", "workspace_exec", "workspace_job", "workspace_lock",
                                 "workspace_unlock"})

    def test_ping_and_unknown_method(self):
        s = self.server()
        self.assertEqual(s.request("ping")["result"], {})
        self.assertEqual(s.request("resources/list")["error"]["code"], -32601)

    def test_unknown_tool_is_a_protocol_error(self):
        reply = self.server().request("tools/call", {"name": "nope", "arguments": {}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_tool_failure_is_a_result_with_is_error(self):
        text, failed = self.server().call("workspace_read", path="missing.txt")
        self.assertTrue(failed)
        self.assertIn("does not exist", text)

    def test_root_must_already_exist(self):
        missing = self.tmp / "nowhere"
        proc = subprocess.run([sys.executable, str(SERVER), "--root", str(missing)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, timeout=10)
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(missing.exists(), "the server must not create a root it was pointed at")

    # ---- containment ----------------------------------------------------

    def test_paths_outside_the_root_are_refused(self):
        s = self.server()
        for path in ("../outside.txt", "/etc/hosts", "src/../../outside.txt"):
            text, failed = s.call("workspace_read", path=path)
            self.assertTrue(failed, path)
            self.assertIn("outside the workspace root", text)

    def test_symlinks_cannot_escape_the_root(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("outside data\n")
        (self.root / "dirlink").symlink_to(outside)
        (self.root / "filelink").symlink_to(outside / "secret.txt")
        s = self.server()
        for tool, args in (("workspace_read", {"path": "dirlink/secret.txt"}),
                           ("workspace_read", {"path": "filelink"}),
                           ("workspace_write", {"path": "dirlink/new.txt", "content": "x"}),
                           ("workspace_patch", {"path": "filelink", "old_text": "outside", "new_text": "pwned"}),
                           ("workspace_exec", {"command": "true", "cwd": "dirlink"})):
            text, failed = s.call(tool, **args)
            self.assertTrue(failed, f"{tool} {args} escaped through a symlink: {text}")
            self.assertIn("outside the workspace root", text)
        self.assertFalse((outside / "new.txt").exists())
        self.assertEqual((outside / "secret.txt").read_text(), "outside data\n")

    def test_sensitive_files_are_refused_by_file_tools(self):
        (self.root / ".env").write_text("TOKEN=x\n")
        (self.root / "deploy").mkdir()
        (self.root / "deploy" / ".gitlab-token").write_text("glpat-x\n")
        s = self.server()
        for path in (".env", "deploy/.gitlab-token", "src/.env.local"):
            text, failed = s.call("workspace_read", path=path)
            self.assertTrue(failed, path)
            self.assertIn("sensitive", text)
        text, failed = s.call("workspace_write", path=".env", content="x")
        self.assertTrue(failed)

    @unittest.skipUnless(HAS_RG, "ripgrep not installed")
    def test_search_does_not_leak_sensitive_files(self):
        # Regression: search used to exclude only .env*, so this printed the
        # token file's contents even though workspace_read refused the file.
        (self.root / ".gitlab-token").write_text("needle-secret\n")
        (self.root / "id_ed25519").write_text("needle-secret\n")
        (self.root / "notes.txt").write_text("needle-secret\n")
        text, failed = self.server().call("workspace_find", pattern="needle-secret")
        self.assertFalse(failed, text)
        self.assertIn("notes.txt", text)
        self.assertNotIn(".gitlab-token", text)
        self.assertNotIn("id_ed25519", text)

    @unittest.skipUnless(HAS_RG, "ripgrep not installed")
    def test_find_returns_relative_paths_and_files_only_globs(self):
        s = self.server()
        text, _ = s.call("workspace_find", pattern="three")
        self.assertEqual(text, "src/app.py:3:three")
        text, _ = s.call("workspace_find", pattern="**/*.py", files_only=True)
        self.assertEqual(text, "src/app.py")

    # ---- read / patch / write ------------------------------------------

    def test_read_reports_hash_and_range(self):
        text, failed = self.server().call("workspace_read", path="src/app.py", start_line=2, end_line=3)
        self.assertFalse(failed)
        header, body = text.split("\n", 1)
        self.assertRegex(header, r"^src/app.py sha256:[0-9a-f]{16} lines 2-3 of 4$")
        self.assertEqual(body, "2: two\n3: three")

    def test_patch_requires_a_unique_match(self):
        s = self.server()
        text, failed = s.call("workspace_patch", path="src/app.py", old_text="two", new_text="2")
        self.assertTrue(failed)
        self.assertIn("matches 2 places", text)
        text, failed = s.call("workspace_patch", path="src/app.py", old_text="three", new_text="3")
        self.assertFalse(failed, text)
        self.assertEqual((self.root / "src" / "app.py").read_text(), "one\ntwo\n3\ntwo\n")

    def test_stale_expected_sha256_refuses_and_leaves_file_untouched(self):
        s = self.server()
        before = (self.root / "src" / "app.py").read_bytes()
        text, failed = s.call("workspace_write", path="src/app.py", content="new", expected_sha256="0" * 16)
        self.assertTrue(failed)
        self.assertIn("changed since it was read", text)
        self.assertEqual((self.root / "src" / "app.py").read_bytes(), before)

    def test_write_keeps_the_executable_bit(self):
        script = self.root / "run.sh"
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
        text, failed = self.server().call("workspace_write", path="run.sh", content="#!/bin/sh\necho hi\n")
        self.assertFalse(failed, text)
        self.assertTrue(script.stat().st_mode & stat.S_IXUSR)

    # ---- lease ------------------------------------------------------------

    def test_lock_is_enforced_across_sessions(self):
        holder, other = self.server(), self.server()
        self.assertIn("acquired", holder.call("workspace_lock", reason="refactor")[0])
        text, failed = other.call("workspace_patch", path="src/app.py", old_text="one", new_text="1")
        self.assertTrue(failed, "a write from another session must be refused while the lock is held")
        self.assertIn("refactor", text)
        text, failed = holder.call("workspace_patch", path="src/app.py", old_text="one", new_text="1")
        self.assertFalse(failed, text)
        holder.call("workspace_unlock")
        text, failed = other.call("workspace_patch", path="src/app.py", old_text="1", new_text="uno")
        self.assertFalse(failed, text)

    def test_lock_dies_with_its_holder(self):
        holder, other = self.server(), self.server()
        holder.call("workspace_lock", reason="crash test")
        holder.proc.kill()
        holder.proc.wait(timeout=10)
        text, failed = other.call("workspace_write", path="after.txt", content="ok")
        self.assertFalse(failed, text)

    def test_lock_file_lives_outside_the_project(self):
        self.server().call("workspace_lock")
        self.assertFalse((self.root / ".ai").exists(), "the lock must not litter the user's repository")

    # ---- exec ---------------------------------------------------------------

    def test_exec_reports_exit_status(self):
        text, failed = self.server().call("workspace_exec", command="echo hi; exit 3")
        self.assertFalse(failed)
        self.assertEqual(text, "exit: 3\nhi\n")

    def test_exec_timeout_warns_about_side_effects(self):
        text, _ = self.server().call("workspace_exec", command="echo started; sleep 5", timeout_seconds=1)
        self.assertIn("timed out after 1s", text)
        self.assertIn("check before retrying", text)
        self.assertIn("started", text)

    def test_background_job(self):
        s = self.server()
        text, _ = s.call("workspace_exec", command="sleep 0.3; echo done", background=True)
        job_id = text.split()[1]
        text, _ = s.call("workspace_job", id=job_id, wait_seconds=10)
        self.assertIn("exit 0", text)
        self.assertTrue(text.rstrip().endswith("done"))


if __name__ == "__main__":
    unittest.main()
