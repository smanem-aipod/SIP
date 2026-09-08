"""
Load the configured source datasets into PostgreSQL raw tables only.

This is useful for testing:

source loader
→ source-to-raw mapping
→ raw datatype preparation
→ raw database insertion
"""

from sip_automation import create_application
from sip_automation.core.run_context import RunContext


def main() -> None:
    with create_application() as application:
        context = RunContext.from_config(
            application.config,
            initiated_by="local-development",
        )

        results = application.container.raw_pipeline.run(
            context=context,
        )

        print()
        print("=" * 80)
        print("RAW LOADING COMPLETED")
        print("=" * 80)
        print(f"Pipeline Run ID: {context.run_id}")
        print()

        for table_name, result in results.items():
            print(
                f"{table_name:<12}"
                f"source={result.source_row_count:<8}"
                f"inserted={result.raw_row_count:<8}"
                f"columns={result.raw_column_count:<5}"
                f"target={result.schema_name}.{result.table_name}"
            )


if __name__ == "__main__":
    main()