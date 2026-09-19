from copy import deepcopy

import pytest
from test_experiment_packages import PACKAGE_ROOT

from app.experiment_packages.loader import (
    ExperimentPackageLoadError,
    load_experiment_package,
    load_experiment_package_payload,
    package_documents,
)


@pytest.mark.parametrize("constraint", [">=99.0", "not-a-version", "<2.0"])
def test_incompatible_or_invalid_engine_requirement_is_rejected(constraint):
    bundle, _ = load_experiment_package(PACKAGE_ROOT / "gpio_led_output")
    documents = deepcopy(package_documents(bundle))
    documents["metadata.yaml"]["compatibility"]["engine"] = constraint
    with pytest.raises(ExperimentPackageLoadError, match="compatibility"):
        load_experiment_package_payload(documents)
