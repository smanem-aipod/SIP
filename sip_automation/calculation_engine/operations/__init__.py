"""
Reusable operations for the SIP calculation engine.
"""

from sip_automation.calculation_engine.operations.aggregate import (
    AggregateAverageOperation,
    AggregateCountOperation,
    AggregateMaximumOperation,
    AggregateMinimumOperation,
    AggregateSumOperation,
    WeightedAverageOperation,
    WeightedAllocationSumOperation,
)
from sip_automation.calculation_engine.operations.arithmetic import (
    AbsoluteOperation,
    AddOperation,
    DivideOperation,
    MaximumOperation,
    MinimumOperation,
    MultiplyOperation,
    SubtractOperation,
)
from sip_automation.calculation_engine.operations.base import (
    BaseOperation,
    OperationExecutionError,
)
from sip_automation.calculation_engine.operations.conditional import (
    CaseWhenOperation,
    IfElseOperation,
)
from sip_automation.calculation_engine.operations.constant import (
    ConstantOperation,
)
from sip_automation.calculation_engine.operations.financial import (
    CapOperation,
    ClampOperation,
    FloorOperation,
    ProrateOperation,
    RoundOperation,
    NacsRegionCurrencyOperation,
    OverpaymentOperation,
)
from sip_automation.calculation_engine.operations.fiscal import (
    MonthsEligibleOperation,
)
from sip_automation.calculation_engine.operations.lookup import (
    ExistsOperation,
    LookupOperation,
)


DEFAULT_OPERATIONS: tuple[BaseOperation, ...] = (
    # Constants
    ConstantOperation(),

    # Arithmetic
    AddOperation(),
    SubtractOperation(),
    MultiplyOperation(),
    DivideOperation(),
    MinimumOperation(),
    MaximumOperation(),
    AbsoluteOperation(),

    # Aggregations
    AggregateSumOperation(),
    AggregateAverageOperation(),
    AggregateMinimumOperation(),
    AggregateMaximumOperation(),
    AggregateCountOperation(),
    WeightedAverageOperation(),
    WeightedAllocationSumOperation(),

    # Conditions
    IfElseOperation(),
    CaseWhenOperation(),

    # Lookups
    LookupOperation(),
    ExistsOperation(),

    # Financial controls
    CapOperation(),
    FloorOperation(),
    ClampOperation(),
    ProrateOperation(),
    RoundOperation(),
    NacsRegionCurrencyOperation(),
    OverpaymentOperation(),

    # Fiscal calculations
    MonthsEligibleOperation(),
)


__all__ = [
    "BaseOperation",
    "OperationExecutionError",
    "DEFAULT_OPERATIONS",
]