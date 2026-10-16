import os
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backup_verify as bv  # noqa: E402


class BackupVerifyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "db").mkdir()
        (self.root / "db" / "dump.sql").write_text("select 1;\n")
        (self.root / "files.tar").write_bytes(b"abc" * 1000)

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_then_verify_ok(self):
        self.assertEqual(bv.build_manifest(self.root), 2)
        self.assertEqual(bv.verify(self.root), (bv.OK, []))

    def test_changed_file_fails(self):
        bv.build_manifest(self.root)
        (self.root / "db" / "dump.sql").write_text("select 2;\n")
        verdict, problems = bv.verify(self.root)
        self.assertEqual(verdict, bv.FAIL)
        self.assertTrue(problems[0].startswith("CHANGED"))

    def test_missing_file_fails(self):
        bv.build_manifest(self.root)
        (self.root / "files.tar").unlink()
        self.assertEqual(bv.verify(self.root)[0], bv.FAIL)

    def test_extra_file_warns(self):
        bv.build_manifest(self.root)
        (self.root / "new.txt").write_text("x")
        self.assertEqual(bv.verify(self.root)[0], bv.WARN)

    def test_no_manifest_fails(self):
        self.assertEqual(bv.verify(self.root)[0], bv.FAIL)

    def test_freshness(self):
        self.assertEqual(bv.freshness(self.root, 30)[0], bv.OK)
        old = time.time() - 31 * 3600
        for rel in bv.list_files(self.root):
            os.utime(self.root / rel, (old, old))
        self.assertEqual(bv.freshness(self.root, 30)[0], bv.FAIL)
        self.assertEqual(bv.freshness(self.root, 48)[0], bv.OK)

    def test_empty_folder_fails_freshness(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(bv.freshness(Path(d), 30)[0], bv.FAIL)

    def test_rsync_codes(self):
        self.assertEqual(bv.rsync_verdict(0)[0], bv.OK)
        self.assertEqual(bv.rsync_verdict(24)[0], bv.WARN)
        self.assertEqual(bv.rsync_verdict(23)[0], bv.FAIL)
        self.assertEqual(bv.rsync_verdict(12)[0], bv.FAIL)

    def test_cli_exit_codes(self):
        bv.build_manifest(self.root)
        self.assertEqual(bv.main(["report", str(self.root), "--rsync-exit", "24"]), bv.WARN)
        self.assertEqual(bv.main(["freshness", str(self.root), "--rsync-exit", "23"]), bv.FAIL)
        self.assertEqual(bv.main(["verify", str(self.root / "nope")]), bv.FAIL)

    def test_oserror_becomes_fail(self):
        with mock.patch.object(bv, "sha256_file", side_effect=FileNotFoundError("gone")):
            self.assertEqual(bv.main(["manifest", str(self.root)]), bv.FAIL)

    def test_manifest_refuses_symlink(self):
        target = self.root / "elsewhere.txt"
        target.write_text("keep")
        (self.root / bv.MANIFEST).symlink_to(target)
        self.assertEqual(bv.main(["manifest", str(self.root)]), bv.FAIL)
        self.assertEqual(target.read_text(), "keep")

    def test_manifest_atomic_leaves_no_tmp(self):
        bv.build_manifest(self.root)
        self.assertFalse((self.root / bv.TMP).exists())

    @unittest.skipIf(os.geteuid() == 0, "root can read chmod 000 dirs")
    def test_unreadable_dir_fails(self):
        locked = self.root / "locked"
        locked.mkdir()
        (locked / "x").write_text("x")
        locked.chmod(0)
        try:
            self.assertEqual(bv.main(["manifest", str(self.root)]), bv.FAIL)
            self.assertEqual(bv.main(["verify", str(self.root)]), bv.FAIL)
        finally:
            locked.chmod(0o700)

    def test_unreadable_dir_fails_simulated(self):
        err = PermissionError(13, "Permission denied", "/x/locked")
        real_walk = os.walk

        def fake_walk(top, onerror=None, **kw):
            onerror(err)
            return real_walk(top, onerror=onerror, **kw)

        with mock.patch.object(bv.os, "walk", fake_walk):
            self.assertEqual(bv.main(["manifest", str(self.root)]), bv.FAIL)

    def test_future_mtime_warns(self):
        future = time.time() + 5 * 3600
        for rel in bv.list_files(self.root):
            os.utime(self.root / rel, (future, future))
        self.assertEqual(bv.freshness(self.root, 30)[0], bv.WARN)

    def test_bad_hours_rejected(self):
        for bad in ("nan", "inf", "0", "-5", "abc"):
            with self.assertRaises(SystemExit) as cm, mock.patch("sys.stderr"):
                bv.main(["freshness", str(self.root), "--hours", bad])
            self.assertEqual(cm.exception.code, 2)

    def test_marker(self):
        marker = self.root / "LAST_BACKUP_OK"
        marker.write_text("")
        old = time.time() - 40 * 3600
        os.utime(marker, (old, old))
        self.assertEqual(bv.freshness(self.root, 30, marker)[0], bv.FAIL)
        self.assertEqual(bv.freshness(self.root, 30, self.root / "nope")[0], bv.FAIL)

    def test_odd_filename_roundtrip(self):
        (self.root / "a\nb\\c.txt").write_text("odd")
        bv.build_manifest(self.root)
        self.assertEqual(bv.verify(self.root), (bv.OK, []))

    def test_bad_digest_and_duplicate_fail(self):
        good = "a" * 64
        for body in (f"{'z' * 64}  db/dump.sql\n", f"abc  db/dump.sql\n",
                     f"{good}  x\n{good}  x\n"):
            (self.root / bv.MANIFEST).write_text(body)
            self.assertEqual(bv.verify(self.root)[0], bv.FAIL, body)

    def test_empty_everything_warns(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / bv.MANIFEST).write_text("")
            self.assertEqual(bv.verify(Path(d))[0], bv.WARN)


if __name__ == "__main__":
    unittest.main()
