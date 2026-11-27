"""Keep volume expressions within Coolify v4.7.9's supported source syntax.

The upstream parser rejects ${VAR:?message} in a source even though Docker accepts
it. Confirmed using parseDockerVolumeString from coollabsio/coolify v4.7.9
bootstrap/helpers/parsers.php (MIT); required-value guards belong in environment.
"""
import json
from pathlib import Path
import re
import subprocess
import unittest


class ComposeVolumes(unittest.TestCase):
    def test_coolify_can_parse_every_profile_before_variables_are_configured(self):
        compose = Path(__file__).resolve().parents[1] / "compose.yml"
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose), "--profile", "*", "config",
             "--no-interpolate", "--no-consistency", "--format", "json"],
            capture_output=True, text=True, encoding="utf-8", check=True)
        config = json.loads(result.stdout)
        for service in config["services"].values():
            for volume in service.get("volumes", []):
                source = volume.get("source", "")
                if "${" in source:
                    self.assertRegex(source, r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}(/[\w.-]+)*$",
                                     "Coolify rejects required-value operators in volume sources")
                self.assertNotIn("${", volume["target"])
        self.assertTrue(config["services"]["backup-scheduler"]["environment"]["CONTEXT_BACKUP_DIR"].startswith(
            "${CONTEXT_BACKUP_DIR:?"))
