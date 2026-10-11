from xinjian_serial_bridge.parser import parse_line


def test_actual_readings_and_negative_temperature():
    first = parse_line("温度: 26.56 ℃ | 湿度: 40.80 %RH\n")
    second = parse_line("温度: 25.29 ℃ | 湿度: 42.06 %RH\r\n")
    negative = parse_line("温度: -3.25 ℃ | 湿度: 42.06 %RH")
    assert first.kind == "reading" and first.temperature == 26.56 and first.humidity == 40.8
    assert second.kind == "reading" and second.temperature == 25.29
    assert negative.kind == "reading" and negative.temperature == -3.25


def test_boot_failure_and_unknown_logs():
    assert parse_line("SHT31 传感器启动!\n").kind == "boot"
    assert parse_line("读取失败！检查接线或者把地址改成0x45\n").kind == "failure"
    assert parse_line("I (123) main_task: started\n") is None
    assert parse_line("温度: 26.56 ℃ | 湿度: 40.80 %RH") is not None
    assert parse_line("温度: 26.56 ℃ | 湿度: 40.80 %RH\x00") is None
    assert parse_line("温度: 26.56") is None
