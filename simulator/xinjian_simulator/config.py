import os
from dataclasses import dataclass, field


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _positive_float_env(name: str, default: str) -> float:
    value = float(os.getenv(name, default))
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


@dataclass(frozen=True)
class SimulationConfig:
    api_base_url: str
    device_id: str
    device_token: str = field(repr=False)
    interval_seconds: float = 5.0
    sensor_type: str = "generic-test-sensor"
    primary_metric_key: str = "test_metric_primary"
    primary_unit: str = "test-unit"
    secondary_metric_key: str = "test_metric_secondary"
    secondary_unit: str = "test-unit"
    normal_primary_value: float = 42.0
    normal_secondary_value: float = 24.0
    out_of_range_primary_value: float = 999.0
    out_of_range_secondary_value: float = -999.0
    stuck_value: float = 17.0
    firmware_version: str = "phase3-test-simulator"
    request_timeout_seconds: float = 8.0

    @classmethod
    def from_env(cls) -> "SimulationConfig":
        return cls(
            api_base_url=os.getenv("XINJIAN_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            device_id=_required_env("XINJIAN_DEVICE_ID"),
            device_token=_required_env("XINJIAN_DEVICE_TOKEN"),
            interval_seconds=_positive_float_env("XINJIAN_INTERVAL_SECONDS", "5"),
            sensor_type=os.getenv("XINJIAN_SENSOR_TYPE", "generic-test-sensor"),
            primary_metric_key=os.getenv("XINJIAN_PRIMARY_METRIC_KEY", "test_metric_primary"),
            primary_unit=os.getenv("XINJIAN_PRIMARY_UNIT", "test-unit"),
            secondary_metric_key=os.getenv("XINJIAN_SECONDARY_METRIC_KEY", "test_metric_secondary"),
            secondary_unit=os.getenv("XINJIAN_SECONDARY_UNIT", "test-unit"),
            normal_primary_value=float(os.getenv("XINJIAN_NORMAL_PRIMARY_VALUE", "42")),
            normal_secondary_value=float(os.getenv("XINJIAN_NORMAL_SECONDARY_VALUE", "24")),
            out_of_range_primary_value=float(
                os.getenv("XINJIAN_OUT_OF_RANGE_PRIMARY_VALUE", "999")
            ),
            out_of_range_secondary_value=float(
                os.getenv("XINJIAN_OUT_OF_RANGE_SECONDARY_VALUE", "-999")
            ),
            stuck_value=float(os.getenv("XINJIAN_STUCK_VALUE", "17")),
            firmware_version=os.getenv("XINJIAN_FIRMWARE_VERSION", "phase3-test-simulator"),
            request_timeout_seconds=_positive_float_env("XINJIAN_REQUEST_TIMEOUT_SECONDS", "8"),
        )
