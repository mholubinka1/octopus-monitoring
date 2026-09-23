from libs.common.common.logging import logging_config


def test_logging_config_configures_a_logger_with_the_given_name() -> None:
    config = logging_config("octopus-monitor")

    assert "octopus-monitor" in config["loggers"]
    assert "hive-monitor" not in config["loggers"]


def test_logging_config_is_parameterized_by_logger_name_not_hardcoded() -> None:
    octopus_config = logging_config("octopus-monitor")
    hive_config = logging_config("hive-monitor")

    assert set(octopus_config["loggers"]) == {"octopus-monitor"}
    assert set(hive_config["loggers"]) == {"hive-monitor"}
