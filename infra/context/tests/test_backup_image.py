"""Exercise the packaged scripts with PostgreSQL; never touches deployment data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid


@unittest.skipUnless(os.environ.get("CONTEXT_TEST_OPS_IMAGE"), "Set CONTEXT_TEST_OPS_IMAGE to a locally built ops image")
class BackupImage(unittest.TestCase):
    def docker(self, *args, check=True, input=None):
        result = subprocess.run(["docker", *args], input=input,
                                capture_output=True, text=True, encoding="utf-8", timeout=60)
        if check and result.returncode:
            self.fail(result.stdout + result.stderr)
        return result

    def test_scheduler_and_restore_without_repository_mount(self):
        image = os.environ["CONTEXT_TEST_OPS_IMAGE"]
        prefix = "ctx-backup-test-" + uuid.uuid4().hex[:10]
        db, scheduler = prefix + "-db", prefix + "-scheduler"
        media, restored = prefix + "-media", prefix + "-restored"
        password = "synthetic_disposable_test_password"
        checksum = hashlib.sha256(b"synthetic-audio").hexdigest()
        with tempfile.TemporaryDirectory(prefix=prefix) as directory:
            backup_dir = Path(directory)
            sentinel = backup_dir / "existing-file"
            sentinel.write_text("preserve", encoding="utf-8")
            try:
                self.docker("network", "create", prefix)
                for volume in (media, restored):
                    self.docker("volume", "create", volume)
                self.docker("run", "-d", "--name", db, "--network", prefix,
                            "--tmpfs", "/var/lib/postgresql/data", "-e", "POSTGRES_DB=korda",
                            "-e", "POSTGRES_USER=korda", "-e", "POSTGRES_PASSWORD=" + password, "postgres:17")
                for _ in range(60):
                    if self.docker("exec", db, "pg_isready", "-h", "127.0.0.1", "-U", "korda", "-d", "korda", check=False).returncode == 0:
                        break
                    time.sleep(0.5)
                else:
                    self.fail("Synthetic PostgreSQL did not become ready")
                sql = ("CREATE TABLE ctx_media(storage_path text, sha256 text); "
                       "INSERT INTO ctx_media VALUES ('/var/lib/korda/media/sample.ogg', '" + checksum + "');")
                self.docker("exec", "-i", db, "psql", "-U", "korda", "-d", "korda", "-v", "ON_ERROR_STOP=1", input=sql)
                self.docker("run", "--rm", "--network", "none", "-v", media + ":/source/media", image,
                            "bash", "-c", "printf synthetic-audio > /source/media/sample.ogg")
                common = ["--network", prefix, "--mount", "type=bind,source=" + directory + ",target=/backups",
                          "-e", "PGHOST=" + db, "-e", "PGUSER=korda", "-e", "PGDATABASE=korda",
                          "-e", "PGPASSWORD=" + password]
                self.docker("run", "-d", "--name", scheduler, *common, "-e", "SOURCE_IMAGE_TAG=synthetic-test",
                            "-v", media + ":/source/media:ro", image, "bash", "/ops/schedule.sh")
                for _ in range(60):
                    completed = [p for p in backup_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
                    if completed:
                        break
                    time.sleep(0.5)
                else:
                    self.fail("Scheduler did not complete backup: " + self.docker("logs", scheduler).stdout)
                inspection = json.loads(self.docker("inspect", scheduler).stdout)[0]
                self.assertTrue(inspection["State"]["Running"], self.docker("logs", scheduler).stdout)
                mounts = {m["Destination"]: m for m in inspection["Mounts"]}
                self.assertNotIn("/ops", mounts)
                self.assertEqual(mounts["/backups"]["Type"], "bind")
                self.docker("stop", "--time", "1", scheduler)
                backup = completed[0]
                self.assertTrue((backup / "database.dump").stat().st_size > 0)
                restore_common = [arg + ",readonly" if arg.startswith("type=bind,") else arg for arg in common]
                restore_args = ["run", "--rm", *restore_common, "-v", restored + ":/restore-media",
                                image, "bash", "/ops/restore.sh", "--disposable-target", "ctx_restore_test", backup.name]
                result = self.docker(*restore_args)
                self.assertIn("Restore drill complete", result.stdout)
                for database in ("korda", "ctx_restore_test"):
                    result = self.docker("exec", db, "psql", "-U", "korda", "-d", database, "-Atc", "SELECT sha256 FROM ctx_media")
                    self.assertEqual(result.stdout.strip(), checksum)
                self.assertNotEqual(self.docker(*restore_args, check=False).returncode, 0)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
                missing = "/__" + prefix + "/must-not-be-created"
                result = self.docker("run", "--rm", "--mount", "type=bind,source=" + missing + ",target=/backups",
                                     image, "bash", "/ops/backup.sh", check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("bind source path does not exist", result.stderr)
            finally:
                # Only resources with this invocation's random prefix are disposable.
                for container in (scheduler, db):
                    self.docker("rm", "-f", container, check=False)
                for volume in (media, restored):
                    self.docker("volume", "rm", volume, check=False)
                self.docker("network", "rm", prefix, check=False)
