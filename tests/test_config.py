from nhk_recorder.config import load_config


def test_load_config_does_not_create_output_directory(tmp_path, monkeypatch):
    output_dir = tmp_path / "recordings"
    config_path = tmp_path / "config.yaml"
    config_path.write_text(f"output_dir: {output_dir}\n", encoding="utf-8")
    monkeypatch.setenv("NHK_API_KEY", "test-key")

    config = load_config(str(config_path))

    assert config.output_dir == output_dir
    assert not output_dir.exists()
