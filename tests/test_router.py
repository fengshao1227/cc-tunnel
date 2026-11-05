"""Tests for cc-tunnel-router: remote path -> local root resolution."""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROUTER = pathlib.Path(__file__).resolve().parent.parent / "local" / "bin" / "cc-tunnel-router"


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.config = self.tmp / "config"
        self.config.mkdir()
        # Stand-in for cc-tunnel-mcp: print the root it would have been given.
        self.fake = self.tmp / "fake-mcp"
        self.fake.write_text('#!/bin/sh\nprintf "%s\\n" "$2"\n')
        self.fake.chmod(0o755)

    def tearDown(self):
        shutil.rmtree(str(self.tmp), ignore_errors=True)

    def route(self, remote, mapping):
        (self.config / "projects.conf").write_text(mapping)
        env = dict(os.environ, CC_TUNNEL_CONFIG_DIR=str(self.config), CC_TUNNEL_MCP_BIN=str(self.fake))
        proc = subprocess.run(["bash", str(ROUTER), "--remote-root", remote], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()

    def test_longest_prefix_wins(self):
        mapping = "/Users/me/work|/home/agent/projects/work\n/Users/me/work/api|/home/agent/projects/work/api\n"
        self.assertEqual(self.route("/home/agent/projects/work/api/cmd", mapping)[1], "/Users/me/work/api/cmd")
        self.assertEqual(self.route("/home/agent/projects/work/web", mapping)[1], "/Users/me/work/web")

    def test_prefix_must_end_at_a_path_boundary(self):
        # /projects/app must not capture /projects/app-fix: the sibling-name trap.
        code, _, err = self.route("/home/agent/projects/app-fix", "/Users/me/app|/home/agent/projects/app\n")
        self.assertEqual(code, 1)
        self.assertIn("unmapped", err)

    def test_comments_blank_lines_crlf_and_third_column(self):
        mapping = "# local|remote\n\n/Users/me/app|/home/agent/projects/app|/ignored\r\n"
        self.assertEqual(self.route("/home/agent/projects/app", mapping)[1], "/Users/me/app")

    def test_last_line_without_newline_is_read(self):
        self.assertEqual(self.route("/r/app", "/l/app|/r/app")[1], "/l/app")

    def test_dot_dot_cannot_escape_the_mapped_root(self):
        code, out, err = self.route("/home/agent/projects/app/../../../etc", "/Users/me/app|/home/agent/projects/app\n")
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("refusing", err)

    def test_paths_with_spaces_survive(self):
        mapping = "/Users/me/My Projects/app|/home/agent/projects/app\n"
        self.assertEqual(self.route("/home/agent/projects/app/a b", mapping)[1], "/Users/me/My Projects/app/a b")


if __name__ == "__main__":
    unittest.main()
