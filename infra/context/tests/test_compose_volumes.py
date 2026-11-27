"""Keep volume expressions within Coolify v4.7.9's supported source syntax.

The upstream parser rejects ${VAR:?message} in a source even though Docker accepts
it. Confirmed using parseDockerVolumeString from coollabsio/coolify v4.7.9
bootstrap/helpers/parsers.php (MIT); required-value guards belong in environment.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import unittest


class ComposeVolumes(unittest.TestCase):
    def test_coolify_can_parse_every_profile_before_variables_are_configured(self):
        compose = Path(__file__).resolve().parents[1] / "compose.yml"
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "--profile", "*", "config",
             "--no-interpolate", "--no-path-resolution", "--no-consistency", "--format", "json"],
            capture_output=True, text=True, encoding="utf-8", check=True)
        config = json.loads(result.stdout)
        for name in ("backup", "backup-scheduler", "restore"):
            service = config["services"][name]
            with self.subTest(service=name):
                mounts = {v["target"]: v for v in service["volumes"]}
                self.assertNotIn("/ops", mounts, "Backup scripts must come from the image")
                self.assertEqual(mounts["/backups"]["type"], "bind")
                self.assertFalse(mounts["/backups"]["bind"]["create_host_path"])
                self.assertEqual(mounts["/backups"].get("read_only", False), name == "restore")
                self.assertIn("build", service)
        for service in config["services"].values():
            for volume in service.get("volumes", []):
                source = volume.get("source", "")
                if "${" in source:
                    self.assertRegex(source, r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}(/[\w.-]+)*$",
                                     "Coolify rejects required-value operators in volume sources")
                self.assertNotIn("${", volume["target"])
        self.assertTrue(config["services"]["backup-scheduler"]["environment"]["CONTEXT_BACKUP_DIR"].startswith(
            "${CONTEXT_BACKUP_DIR:?"))

    def test_config_resolves_backup_bind_and_rejects_missing_directory_variable(self):
        compose = Path(__file__).resolve().parents[1] / "compose.yml"
        command = ["docker", "compose", "-f", str(compose), "--profile", "*", "config",
                   "--no-path-resolution", "--format", "json"]
        environment = {**os.environ, "CONTEXT_DB_PASSWORD": "synthetic_test_only",
                       "CONTEXT_DATABASE_URL": "postgresql://korda:synthetic_test_only@postgres/korda",
                       "CONTEXT_IMAGE_TAG": "synthetic-test", "CONTEXT_BACKUP_DIR": "/private/synthetic-backups"}
        result = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8", check=True)
        config = json.loads(result.stdout)
        for name in ("backup", "backup-scheduler", "restore"):
            mount = next(v for v in config["services"][name]["volumes"] if v["target"] == "/backups")
            self.assertEqual(mount["source"], environment["CONTEXT_BACKUP_DIR"])
            self.assertEqual(mount["type"], "bind")
        environment["CONTEXT_BACKUP_DIR"] = ""
        result = subprocess.run(command, env=environment, capture_output=True, text=True, encoding="utf-8")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CONTEXT_BACKUP_DIR", result.stderr)
