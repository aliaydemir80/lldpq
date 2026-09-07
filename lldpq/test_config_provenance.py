#!/usr/bin/env python3
"""A shipped default must be able to reach an existing host, and an operator's
value must never be taken from them.

notifications.yaml survives an update untouched, which is why the disk warning
thresholds stayed at 80/90 on hosts installed before the shipped file moved to
85/95. Adopting the shipped value unconditionally would have been worse: it
would reset every threshold an operator had tuned, and the Slack webhook lives
in the same file.

config_provenance resolves this by recording what LLDPq last shipped for each
managed key, so "untouched default" and "deliberate choice" stop looking alike.
These tests fail if a new key stops arriving, if an operator's value is ever
overwritten, if ownership stops being sticky, if the notifications/Slack section
is touched, if comments are lost, or if the rewrite drops the file's mode -- the
last one being how the shared www-data read access gets broken in practice.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config_provenance


SHIPPED = """\
notifications:
  enabled: false
  server_url: "http://100.64.1.1"
  slack:
    enabled: false
    webhook: ""
    channel: "#lldpq"

thresholds:
  system:
    # Read by the web UI disk warning bar.
    disk_usage_warning: 85    # % - Disk usage warning
    disk_usage_critical: 95   # % - Disk usage critical
    uptime_minimum_hours: 1
  network:
    bgp_down_minutes: 5
    ber_error_rate: 1e-12

alert_strategy:
  mode: "summary"
  summary_times: ["09:00", "17:00"]

alert_types:
  hardware_alerts: true
"""

# What a host installed before the disk warning bar carries: the old shipped
# thresholds, no knowledge of any key added since, and a configured webhook.
INSTALLED = """\
notifications:
  enabled: true
  server_url: "http://10.1.2.3"
  slack:
    enabled: true
    webhook: "https://hooks.example.invalid/services/T0/B0/secret"
    channel: "#netops"

thresholds:
  system:
    disk_usage_warning: 80    # % - Disk usage warning
    disk_usage_critical: 90   # % - Disk usage critical
  network:
    bgp_down_minutes: 5
    ber_error_rate: 1e-12

alert_strategy:
  mode: "summary"
  summary_times: ["08:30"]

alert_types:
  hardware_alerts: true
"""


class ProvenanceTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(self._cleanup)
        self.shipped = self.root / "shipped.yaml"
        self.target = self.root / "notifications.yaml"
        self.state = self.root / "config-provenance.json"
        self.shipped.write_text(SHIPPED, encoding="utf-8")
        self.target.write_text(INSTALLED, encoding="utf-8")

    def _cleanup(self):
        for path in sorted(self.root.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        self.root.rmdir()

    def merge(self, **kwargs):
        return config_provenance.merge(
            str(self.target), str(self.shipped), str(self.state), **kwargs
        )

    def loaded(self):
        import yaml

        return yaml.safe_load(self.target.read_text(encoding="utf-8"))

    def record(self):
        return json.loads(self.state.read_text(encoding="utf-8"))

    def keys(self):
        return self.record()["files"]["notifications.yaml"]["keys"]

    # ---------------------------------------------------------------- adoption

    def test_untouched_old_default_is_raised_to_the_shipped_value(self):
        """The case that motivated the module: 80/90 -> 85/95."""
        self.merge()
        system = self.loaded()["thresholds"]["system"]
        self.assertEqual(system["disk_usage_warning"], 85)
        self.assertEqual(system["disk_usage_critical"], 95)

    def test_key_absent_from_an_older_install_is_added(self):
        self.assertNotIn(
            "uptime_minimum_hours", self.loaded()["thresholds"]["system"]
        )
        self.merge()
        self.assertEqual(
            self.loaded()["thresholds"]["system"]["uptime_minimum_hours"], 1
        )

    def test_second_run_changes_nothing(self):
        self.merge()
        after_first = self.target.read_text(encoding="utf-8")
        report = self.merge()
        self.assertEqual(self.target.read_text(encoding="utf-8"), after_first)
        self.assertEqual([line for line in report if "adopted" in line], [])

    # ---------------------------------------------------- operator ownership

    def test_operator_value_is_kept_and_marked(self):
        self.target.write_text(
            INSTALLED.replace("disk_usage_critical: 90", "disk_usage_critical: 70"),
            encoding="utf-8",
        )
        self.merge()
        self.assertEqual(
            self.loaded()["thresholds"]["system"]["disk_usage_critical"], 70
        )
        self.assertTrue(
            self.keys()["thresholds.system.disk_usage_critical"]["operator_owned"]
        )

    def test_ownership_survives_a_shipped_default_matching_the_operator(self):
        """Sticky ownership: matching their number once must not reclaim the key.

        Without stickiness the third run would see live == recorded base and
        move the operator's 70 to 88.
        """
        self.target.write_text(
            INSTALLED.replace("disk_usage_critical: 90", "disk_usage_critical: 70"),
            encoding="utf-8",
        )
        self.merge()
        self.shipped.write_text(
            SHIPPED.replace("disk_usage_critical: 95", "disk_usage_critical: 70"),
            encoding="utf-8",
        )
        self.merge()
        self.shipped.write_text(
            SHIPPED.replace("disk_usage_critical: 95", "disk_usage_critical: 88"),
            encoding="utf-8",
        )
        self.merge()
        self.assertEqual(
            self.loaded()["thresholds"]["system"]["disk_usage_critical"], 70
        )

    def test_exponent_scalar_is_not_mistaken_for_an_operator_edit(self):
        """Both files must go through the same YAML loader.

        PyYAML reads ``1e-12`` as a string (YAML 1.1 wants a decimal point in
        the exponent form) while ruamel reads it as a float, so loading the two
        sides differently made this key compare unequal to itself and freeze as
        an operator value on every host.
        """
        self.merge()
        self.assertFalse(
            self.keys()["thresholds.network.ber_error_rate"]["operator_owned"]
        )

    def test_value_matching_current_shipped_stays_adoptable(self):
        """bgp_down_minutes already equals the shipped 5, so it is not owned."""
        self.merge()
        self.assertFalse(
            self.keys()["thresholds.network.bgp_down_minutes"]["operator_owned"]
        )
        self.shipped.write_text(
            SHIPPED.replace("bgp_down_minutes: 5", "bgp_down_minutes: 9"),
            encoding="utf-8",
        )
        self.merge()
        self.assertEqual(self.loaded()["thresholds"]["network"]["bgp_down_minutes"], 9)

    # ----------------------------------------------------------- what is safe

    def test_notifications_section_is_never_touched(self):
        self.merge()
        notifications = self.loaded()["notifications"]
        self.assertTrue(notifications["enabled"])
        self.assertEqual(notifications["server_url"], "http://10.1.2.3")
        self.assertEqual(
            notifications["slack"]["webhook"],
            "https://hooks.example.invalid/services/T0/B0/secret",
        )
        self.assertEqual(notifications["slack"]["channel"], "#netops")

    def test_list_values_are_left_alone(self):
        self.merge()
        self.assertEqual(self.loaded()["alert_strategy"]["summary_times"], ["08:30"])
        self.assertNotIn("alert_strategy.summary_times", self.keys())

    def test_comments_survive_the_rewrite(self):
        self.merge()
        text = self.target.read_text(encoding="utf-8")
        self.assertIn("# % - Disk usage warning", text)

    def test_file_mode_is_preserved(self):
        os.chmod(self.target, 0o664)
        self.merge()
        self.assertEqual(stat.S_IMODE(os.stat(self.target).st_mode), 0o664)

    def test_symlinked_target_is_written_through(self):
        """Docker links this file into a mounted config dir.

        Replacing the link with a regular file would keep the merged values but
        quietly end persistence, so the link has to survive the write.
        """
        real = self.root / "config" / "notifications.yaml"
        real.parent.mkdir()
        real.write_text(self.target.read_text(encoding="utf-8"), encoding="utf-8")
        self.target.unlink()
        self.target.symlink_to(real)
        self.merge()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(os.readlink(self.target), str(real))
        import yaml

        merged = yaml.safe_load(real.read_text(encoding="utf-8"))
        self.assertEqual(merged["thresholds"]["system"]["disk_usage_critical"], 95)

    def test_missing_target_is_a_noop(self):
        self.target.unlink()
        self.assertEqual(self.merge(), [])
        self.assertFalse(self.state.exists())

    def test_dry_run_leaves_the_file_and_record_alone(self):
        before = self.target.read_text(encoding="utf-8")
        report = self.merge(apply_changes=False)
        self.assertTrue(report)
        self.assertEqual(self.target.read_text(encoding="utf-8"), before)
        self.assertFalse(self.state.exists())

    def test_corrupt_record_does_not_hand_keys_to_the_shipped_default(self):
        self.target.write_text(
            INSTALLED.replace("disk_usage_critical: 90", "disk_usage_critical: 70"),
            encoding="utf-8",
        )
        self.state.write_text("{not json", encoding="utf-8")
        self.merge()
        self.assertEqual(
            self.loaded()["thresholds"]["system"]["disk_usage_critical"], 70
        )

    def test_true_is_not_confused_with_one(self):
        self.target.write_text(
            INSTALLED.replace("hardware_alerts: true", "hardware_alerts: false"),
            encoding="utf-8",
        )
        self.merge()
        self.assertIs(self.loaded()["alert_types"]["hardware_alerts"], False)
        self.assertTrue(self.keys()["alert_types.hardware_alerts"]["operator_owned"])

    # ------------------------------------------------------------------- seed

    def test_seed_records_without_editing_the_file(self):
        before = self.target.read_text(encoding="utf-8")
        config_provenance.seed(str(self.target), str(self.shipped), str(self.state))
        self.assertEqual(self.target.read_text(encoding="utf-8"), before)
        keys = self.keys()
        self.assertEqual(keys["thresholds.system.disk_usage_critical"]["shipped"], 95)
        self.assertFalse(
            keys["thresholds.system.disk_usage_critical"]["operator_owned"]
        )

    def test_seeded_host_keeps_its_own_later_edit(self):
        """A fresh install seeds 95; an operator lowering it must stick."""
        config_provenance.seed(str(self.target), str(self.shipped), str(self.state))
        self.target.write_text(
            INSTALLED.replace("disk_usage_critical: 90", "disk_usage_critical: 60"),
            encoding="utf-8",
        )
        self.merge()
        self.assertEqual(
            self.loaded()["thresholds"]["system"]["disk_usage_critical"], 60
        )
        self.assertTrue(
            self.keys()["thresholds.system.disk_usage_critical"]["operator_owned"]
        )


if __name__ == "__main__":
    unittest.main()
