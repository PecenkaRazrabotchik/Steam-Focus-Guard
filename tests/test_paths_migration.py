import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import src.paths as project_paths


class ProjectMigrationTests(unittest.TestCase):
    def test_legacy_files_are_copied_without_deleting_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old_config = root / "config.json"
            old_state = root / "state.json"
            old_log = root / "activity_log.csv"
            old_config.write_text('{"legacy": true}', encoding="utf-8")
            old_state.write_text('{"mode": "timed"}', encoding="utf-8")
            old_log.write_text("legacy log", encoding="utf-8")

            config_dir = root / "config"
            data_dir = root / "data"
            destinations = (
                (old_state, data_dir / "state.json"),
                (old_log, data_dir / "activity_log.csv"),
                (root / "guard.lock", data_dir / "guard.lock"),
                (root / "stop.request", data_dir / "stop.request"),
            )
            with (
                patch.object(project_paths, "PROJECT_ROOT", root),
                patch.object(project_paths, "CONFIG_DIR", config_dir),
                patch.object(project_paths, "DATA_DIR", data_dir),
                patch.object(project_paths, "SCRIPTS_DIR", root / "scripts"),
                patch.object(project_paths, "DOCS_DIR", root / "docs"),
                patch.object(project_paths, "CONFIG_PATH", config_dir / "config.json"),
                patch.object(project_paths, "DEFAULT_CONFIG_PATH", config_dir / "config.example.json"),
                patch.object(project_paths, "STATE_PATH", data_dir / "state.json"),
                patch.object(project_paths, "LOG_PATH", data_dir / "activity_log.csv"),
                patch.object(project_paths, "LOCK_PATH", data_dir / "guard.lock"),
                patch.object(project_paths, "STOP_REQUEST_PATH", data_dir / "stop.request"),
                patch.object(project_paths, "LEGACY_FILES", destinations),
            ):
                project_paths.ensure_project_layout()

            self.assertEqual((config_dir / "config.json").read_text(encoding="utf-8"), '{"legacy": true}')
            self.assertEqual((data_dir / "state.json").read_text(encoding="utf-8"), '{"mode": "timed"}')
            self.assertEqual((data_dir / "activity_log.csv").read_text(encoding="utf-8"), "legacy log")
            self.assertTrue(old_config.exists())
            self.assertTrue(old_state.exists())
            self.assertTrue(old_log.exists())

    def test_existing_new_configuration_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "config").mkdir()
            old_config = root / "config.json"
            old_config.write_text('{"source": "old"}', encoding="utf-8")
            active_config = root / "config" / "config.json"
            active_config.write_text('{"source": "new"}', encoding="utf-8")

            with (
                patch.object(project_paths, "PROJECT_ROOT", root),
                patch.object(project_paths, "CONFIG_DIR", root / "config"),
                patch.object(project_paths, "DATA_DIR", root / "data"),
                patch.object(project_paths, "SCRIPTS_DIR", root / "scripts"),
                patch.object(project_paths, "DOCS_DIR", root / "docs"),
                patch.object(project_paths, "CONFIG_PATH", active_config),
                patch.object(project_paths, "DEFAULT_CONFIG_PATH", root / "config" / "config.example.json"),
                patch.object(project_paths, "STATE_PATH", root / "data" / "state.json"),
                patch.object(project_paths, "LOG_PATH", root / "data" / "activity_log.csv"),
                patch.object(project_paths, "LOCK_PATH", root / "data" / "guard.lock"),
                patch.object(project_paths, "STOP_REQUEST_PATH", root / "data" / "stop.request"),
                patch.object(project_paths, "LEGACY_FILES", ()),
            ):
                project_paths.ensure_project_layout()

            self.assertEqual(active_config.read_text(encoding="utf-8"), '{"source": "new"}')


if __name__ == "__main__":
    unittest.main()
