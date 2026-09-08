from sip_automation.core.config import ConfigManager
from sip_automation.core.run_context import RunContext


def test_calculation_parameters_load_live_yaml_defaults() -> None:
    config = ConfigManager()

    params = config.get_calculation_parameters()

    assert params["target_q2_multiplier"] == 0.5
    assert params["revenue_incentive_weight"] == 0.65
    assert params["gp_incentive_weight"] == 0.35


def test_runtime_override_takes_precedence_over_yaml_defaults() -> None:
    config = ConfigManager()

    context = RunContext.from_config(
        config,
        initiated_by="test",
        overrides={"target_q2_multiplier": 0.75},
    )

    assert context.parameters["target_q2_multiplier"] == 0.75
