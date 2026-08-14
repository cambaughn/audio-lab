"""Settings: tolerant loading, atomic save, per-field fallback."""

import json

from audio_lab.config.settings import AppSettings, load_settings, save_settings


class TestRoundTrip:
    def test_save_and_load(self, tmp_path):
        path = tmp_path / "settings.json"
        settings = AppSettings(
            input_device_name="MacBook Air Microphone",
            debug_mode=True,
            recognition_threshold=0.5,
            private_access_threshold=0.7,
            match_margin=0.15,
            top_k=5,
            use_fake_llm=False,
        )
        save_settings(settings, path)
        assert load_settings(path) == settings

    def test_save_creates_directories(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "settings.json"
        save_settings(AppSettings(), path)
        assert path.exists()

    def test_no_tmp_file_left_behind(self, tmp_path):
        path = tmp_path / "settings.json"
        save_settings(AppSettings(), path)
        assert not path.with_suffix(".tmp").exists()


class TestTolerantLoading:
    def test_missing_file_gives_defaults(self, tmp_path):
        assert load_settings(tmp_path / "absent.json") == AppSettings()

    def test_corrupt_json_gives_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text("{not json")
        assert load_settings(path) == AppSettings()

    def test_non_dict_gives_defaults(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps([1, 2, 3]))
        assert load_settings(path) == AppSettings()

    def test_bad_fields_fall_back_individually(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "input_device_name": "Good Mic",  # valid — kept
                    "debug_mode": "yes",  # wrong type — default
                    "recognition_threshold": 7.5,  # out of range — default
                    "private_access_threshold": 0.6,  # valid — kept
                    "match_margin": True,  # bool is not a float — default
                    "top_k": 0,  # out of range — default
                }
            )
        )
        loaded = load_settings(path)
        assert loaded.input_device_name == "Good Mic"
        assert loaded.private_access_threshold == 0.6
        assert loaded.debug_mode is False
        assert loaded.recognition_threshold == 0.40
        assert loaded.match_margin == 0.10
        assert loaded.top_k == 3

    def test_bool_rejected_for_numeric_fields(self, tmp_path):
        path = tmp_path / "settings.json"
        path.write_text(json.dumps({"recognition_threshold": True, "top_k": True}))
        loaded = load_settings(path)
        assert loaded.recognition_threshold == 0.40
        assert loaded.top_k == 3
