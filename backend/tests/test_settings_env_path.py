from pathlib import Path

from app.core.config import Settings


def test_backend_env_file_is_independent_of_process_cwd(monkeypatch, tmp_path):
    expected = Path(__file__).resolve().parents[1] / ".env"
    assert Settings.model_config["env_file"] == expected

    from_backend = Settings()
    monkeypatch.chdir(tmp_path)
    from_other_directory = Settings()

    assert from_other_directory.web_search_enabled == from_backend.web_search_enabled
    assert bool(from_other_directory.tavily_api_key) == bool(from_backend.tavily_api_key)
