"""Current ESP-IDF project configuration matches the ESP32-S3 hardware contract."""

from pathlib import Path


def test_current_sht31_idf_project_declares_esp32s3_and_i2c_pins():
    root = Path(__file__).resolve().parents[2] / "firmware/esp32s3_sht31"
    assert (root / "CMakeLists.txt").is_file()
    assert "project(esp32s3_sht31)" in (root / "CMakeLists.txt").read_text()
    source = (root / "main/main.c").read_text()
    assert "#define I2C_SDA_GPIO 8" in source
    assert "#define I2C_SCL_GPIO 9" in source
    assert "#define SHT31_ADDR 0x44" in source
    assert ".master.clk_speed = 100000" in source
    assert "uint8_t cmd[2] = {0x24, 0x00}" in source
