import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SPEC = importlib.util.spec_from_file_location("uad_cleanup", Path(__file__).parents[1] / "uad-dynamic-plugin-cleaner.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def wrapped(value):
    return {"value": value}


def payload(state="full_active", licenses=None, name="Example Alpha", manifest=None):
    return {"data": {"properties": {
        "plugin_name": wrapped(name),
        "license_state": wrapped(state),
        "cloud_licenses": wrapped(licenses if licenses is not None else []),
        "manifest": wrapped(manifest or {}),
    }}}


FULL = [{"name": "full", "is_demo": False, "deposit_status": "deposited"}]


class CleanupTests(unittest.TestCase):
    def test_license_requires_all_verified_fields(self):
        self.assertTrue(MODULE.parse_helper_plugin("api", payload(licenses=FULL)).licensed)
        self.assertFalse(MODULE.parse_helper_plugin("api", payload(state="demo_available", licenses=FULL)).licensed)
        self.assertFalse(MODULE.parse_helper_plugin("api", payload()).licensed)
        self.assertFalse(MODULE.parse_helper_plugin("api", payload(licenses=[{"name": "full", "is_demo": True, "deposit_status": "deposited"}])).licensed)

    def test_hybrid_classification(self):
        helper = [MODULE.parse_helper_plugin("alpha", payload(licenses=FULL, manifest={"short_names": ["Alpha Compressor"]}))]
        paths = [Path("UAD Example Alpha.component"), Path("UAD Example Beta.vst3"), Path("UAD Example Gamma.vst3")]
        result = MODULE.classify(paths, {MODULE.normalize_name("Example Beta")}, helper)
        self.assertEqual([item.action for item in result], ["keep", "keep", "unknown"])

    def test_only_explicit_negative_helper_match_is_candidate(self):
        negative = MODULE.parse_helper_plugin("gamma", payload(state="not_licensed", name="Example Gamma"))
        result = MODULE.classify([Path("UAD Example Gamma.vst3")], set(), [negative])
        self.assertEqual(result[0].action, "candidate")

    def test_inconclusive_helper_state_is_unknown(self):
        inconclusive = MODULE.parse_helper_plugin("uaudio_example", payload(state="not_wrapped", name="Example"))
        result = MODULE.classify([Path("uaudio_example.vst3")], set(), [inconclusive])
        self.assertEqual(result[0].action, "unknown")

    def test_uadx_package_id_matches_helper(self):
        licensed = MODULE.parse_helper_plugin("uaudio_example", payload(licenses=FULL, name="Different Display Name"))
        result = MODULE.classify([Path("uaudio_example.component")], set(), [licensed])
        self.assertEqual(result[0].action, "keep")

    def test_uad2_profile_parser_accepts_authorized_device_variants(self):
        profile = """Private hardware details above this line
UAD-2 Plug-in Authorizations

UAD Example Alpha Compressor: Authorized for all devices
Example Beta Amplifier: Authorized for device 1 only
UAD Example Gamma: Demo not started
-----------------------------------
Private details below this line
"""
        result = MODULE.parse_uad2_profile(profile)
        self.assertEqual([item.licensed for item in result], [True, True, False])

    def test_uad2_profile_stops_when_no_device_is_connected(self):
        profile = """UAD-2 Plug-in Authorizations
UAD Example Alpha: No UAD-2 devices found
UAD Example Beta: No UAD-2 devices found
-----------------------------------
"""
        with self.assertRaises(MODULE.SafetyError):
            MODULE.parse_uad2_profile(profile)

    def test_inconclusive_uad2_status_is_never_a_candidate(self):
        disk = MODULE.DiskPlugin(
            "uad_example",
            "uad2",
            MODULE.normalize_name("UAD Example"),
            (MODULE.normalize_name("UAD Example"),),
        )
        auth = [MODULE.UAD2Authorization("UAD Example", "No UAD-2 devices found", False)]
        result = MODULE.classify([Path("UAD Example.component")], set(), [], auth, [disk])
        self.assertEqual(result[0].action, "unknown")

    def test_disk_manifest_bridges_filename_to_meter_profile_name(self):
        disk_payload = {"data": {"properties": {
            "plugin_name": wrapped("UAD Example Alpha"),
            "plugin_type": wrapped("uad2"),
            "manifest": wrapped({"meter_display_name": "UAD Example Alpha Vintage Compressor"}),
        }}}
        disk = MODULE.parse_disk_plugin("uad_example_alpha", disk_payload)
        auth = [MODULE.UAD2Authorization("UAD Example Alpha Vintage Compressor", "Authorized for all devices", True)]
        result = MODULE.classify([Path("UAD Example Alpha.component")], set(), [], auth, [disk])
        self.assertEqual(result[0].action, "keep")
        self.assertIn("UAD-2/Apollo", result[0].reason)

    def test_uad2_demo_is_candidate_only_after_manifest_match(self):
        disk = MODULE.DiskPlugin("uad_example", "uad2", MODULE.normalize_name("UAD Example"), (MODULE.normalize_name("UAD Example"), MODULE.normalize_name("UAD Example Suite")))
        auth = [MODULE.UAD2Authorization("UAD Example Suite", "Demo not started", False)]
        result = MODULE.classify([Path("UAD Example.vst3")], set(), [], auth, [disk])
        self.assertEqual(result[0].action, "candidate")

    def test_positive_license_source_wins_over_negative_source(self):
        cloud = [MODULE.parse_helper_plugin("example", payload(licenses=FULL, name="Example"))]
        disk = [MODULE.DiskPlugin("uad_example", "uad2", MODULE.normalize_name("UAD Example"), (MODULE.normalize_name("UAD Example"),))]
        auth = [MODULE.UAD2Authorization("UAD Example", "Demo not started", False)]
        result = MODULE.classify([Path("UAD Example.component")], set(), cloud, auth, disk)
        self.assertEqual(result[0].action, "keep")

    def test_scan_nested_uad_and_uadx_host_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "UAD Example.vst3").mkdir()
            category = root / "Universal Audio" / "Compressors"
            category.mkdir(parents=True)
            (category / "UAD Example(m).vst").mkdir()
            (root / "uaudio_example.component").mkdir()
            (root / "UAD Example.aaxplugin").mkdir()
            (root / "Other.component").mkdir()
            (root / "UAD note.txt").write_text("x")
            self.assertEqual(
                [p.name for p in MODULE.scan_plugins([root])],
                ["UAD Example.aaxplugin", "UAD Example.vst3", "uaudio_example.component", "UAD Example(m).vst"],
            )

    def test_normalize_all_supported_formats_and_mono_variant(self):
        expected = MODULE.normalize_name("UAD API 2500")
        for name in (
            "UAD API 2500.component",
            "UAD API 2500(m).vst",
            "UAD API 2500.vst3",
            "UAD API 2500.aaxplugin",
            "uaudio_api_2500.vst3",
        ):
            self.assertEqual(MODULE.normalize_name(name), expected)

    def test_empty_allowlist_is_valid_for_dynamic_only_use(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "allowlist.txt"
            path.write_text("# optional\n")
            self.assertEqual(MODULE.load_allowlist(path), set())

    def test_unknown_items_are_never_moved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "UAD Example Legacy.component"
            plugin.mkdir()
            backup = root / "backup"
            decisions = [MODULE.Decision(str(plugin), "unknown", "manual review")]
            result = MODULE.move_candidates(decisions, backup)
            self.assertTrue(plugin.exists())
            self.assertFalse(backup.exists())
            self.assertEqual(result, decisions)


if __name__ == "__main__":
    unittest.main()
