"""Fresh-device image must use the same filesystem as the production store."""

from configparser import ConfigParser
from pathlib import Path


def test_initial_image_is_explicitly_littlefs_and_contains_no_pending_batch():
    root = Path(__file__).resolve().parents[2] / "firmware/esp32_dht11"
    config = ConfigParser()
    config.read(root / "platformio.ini")
    assert config["env:esp32dev"].get("board_build.filesystem") == "littlefs"
    assert (root / "data/README.txt").is_file()
    assert not (root / "data/pending.json").exists()
    assert not (root / "data/pending.json.tmp").exists()
    assert "LittleFS.begin(false)" in (root / "src/pending_store.cpp").read_text()
