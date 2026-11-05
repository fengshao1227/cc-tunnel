"""Run remote/install.sh in a throwaway HOME, twice, and check what it leaves.

A fake `claude` on PATH records its arguments instead of touching a real
configuration. The HOME starts with content a real user would have - a
`Host *` block, other hooks, their own rules - because preserving those is the
part that is easy to get wrong.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
START, END = "# >>> cc-tunnel >>>", "# <<< cc-tunnel <<<"


class RemoteInstallTest(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        stage = self.home / ".local/share/cc-tunnel/stage"
        stage.mkdir(parents=True)
        shutil.copytree(str(REPO / "remote"), str(stage / "remote"))
        shutil.copytree(str(REPO / "skills"), str(stage / "skills"))
        fakebin = self.home / "fakebin"
        fakebin.mkdir()
        (fakebin / "claude").write_text('#!/bin/sh\necho "$@" >> "$HOME/claude-calls.log"\n')
        (fakebin / "claude").chmod(0o755)
        (self.home / ".ssh").mkdir(mode=0o700)
        (self.home / ".ssh/config").write_text("Host *\n    ServerAliveInterval 60\n")
        (self.home / ".claude").mkdir()
        (self.home / ".claude/settings.json").write_text(json.dumps(
            {"theme": "dark", "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "keep-me"}]}]}}))
        (self.home / ".claude/CLAUDE.md").write_text("# my own rules\n")
        self.env = dict(os.environ, HOME=str(self.home), PATH=f"{fakebin}:{os.environ['PATH']}",
                        CC_TUNNEL_MAC_USER="me", CC_TUNNEL_MAC_BIN="/Users/me/.local/bin",
                        CC_TUNNEL_MAC_CONFIG_DIR="/Users/me/.config/cc-tunnel",
                        CC_TUNNEL_MAC_PATH="/opt/homebrew/bin", CC_TUNNEL_TUNNEL_PORT="22022",
                        CC_TUNNEL_AGENT="claude")
        self.outputs = [self.install(), self.install()]

    def tearDown(self):
        shutil.rmtree(str(self.home), ignore_errors=True)

    def install(self):
        proc = subprocess.run(["bash", str(self.home / ".local/share/cc-tunnel/stage/remote/install.sh"),
                               "--with-codegraph"], env=self.env, cwd=str(self.home),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        return proc.stdout

    def test_ssh_block_is_first_and_not_duplicated(self):
        text = (self.home / ".ssh/config").read_text()
        self.assertTrue(text.startswith(START), "the block must precede any Host * to take effect")
        self.assertEqual(text.count(START), 1)
        self.assertIn("Host *\n    ServerAliveInterval 60", text)
        self.assertIn("Port 22022", text)
        self.assertIn("HostKeyAlias cc-tunnel-mac", text)
        self.assertEqual(oct((self.home / ".ssh/config").stat().st_mode & 0o777), "0o600")

    def test_session_end_hook_added_once_and_other_settings_kept(self):
        data = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(data["theme"], "dark")
        self.assertEqual(data["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "keep-me")
        session_end = data["hooks"]["SessionEnd"]
        self.assertEqual(len(session_end), 1)
        self.assertTrue(session_end[0]["hooks"][0]["command"].endswith("cc-tunnel-sync-home"))
        self.assertTrue((self.home / ".claude/settings.json.cc-tunnel-bak").exists())

    def test_rules_block_appended_once_after_the_users_rules(self):
        text = (self.home / ".claude/CLAUDE.md").read_text()
        self.assertTrue(text.startswith("# my own rules\n"))
        self.assertEqual(text.count(START), 1)
        self.assertIn("workspace_status", text)

    def test_mcp_registered_at_user_scope(self):
        calls = (self.home / "claude-calls.log").read_text().splitlines()
        adds = [c for c in calls if c.startswith("mcp add")]
        self.assertIn("mcp add --scope user cc-tunnel-workspace -- "
                      f"{self.home}/.local/share/cc-tunnel/bin/cc-tunnel-workspace", adds)
        self.assertTrue(any("cc-tunnel-codegraph" in c for c in adds))
        self.assertFalse(any("fast-context" in c for c in adds), "not requested, not registered")

    def test_skills_wrappers_env_and_key(self):
        for skill in ("cc-tunnel-workspace", "cc-tunnel-doctor", "cc-tunnel-handoff"):
            self.assertTrue((self.home / ".claude/skills" / skill / "SKILL.md").exists(), skill)
        wrapper = self.home / ".local/share/cc-tunnel/bin/cc-tunnel-workspace"
        self.assertTrue(os.access(str(wrapper), os.X_OK))
        env = (self.home / ".config/cc-tunnel/remote.env").read_text()
        self.assertIn("CC_TUNNEL_MAC_BIN=/Users/me/.local/bin", env)
        self.assertEqual(oct((self.home / ".config/cc-tunnel/remote.env").stat().st_mode & 0o777), "0o600")
        pubkey = (self.home / ".ssh/cc-tunnel_mac.pub").read_text().strip()
        self.assertIn(f"PUBKEY {pubkey}", self.outputs[1])
        # The key is generated once; a re-run must not replace it.
        self.assertIn("generated ~/.ssh/cc-tunnel_mac", self.outputs[0])
        self.assertNotIn("generated", self.outputs[1])


class FreshHomeTest(unittest.TestCase):
    """A first install: no ~/.ssh/config, no ~/.claude, no claude on PATH.

    The paths that only a brand-new host takes - creating every file rather
    than editing one - are the ones the main test never reaches.
    """

    def test_installs_into_an_empty_home(self):
        home = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(home), True)
        stage = home / ".local/share/cc-tunnel/stage"
        stage.mkdir(parents=True)
        shutil.copytree(str(REPO / "remote"), str(stage / "remote"))
        shutil.copytree(str(REPO / "skills"), str(stage / "skills"))
        env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin:/usr/sbin:/sbin",
                   CC_TUNNEL_MAC_USER="me", CC_TUNNEL_MAC_BIN="/Users/me/.local/bin",
                   CC_TUNNEL_MAC_CONFIG_DIR="/Users/me/.config/cc-tunnel", CC_TUNNEL_TUNNEL_PORT="22022")
        proc = subprocess.run(["bash", str(stage / "remote/install.sh")], env=env, cwd=str(home),
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        config = (home / ".ssh/config").read_text()
        self.assertTrue(config.startswith(START) and config.rstrip().endswith(END))
        self.assertIn("not Claude Code (or not on PATH)", proc.stdout)
        self.assertIn("PUBKEY ssh-ed25519 ", proc.stdout)


if __name__ == "__main__":
    unittest.main()
