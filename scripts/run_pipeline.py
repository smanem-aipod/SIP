"""
Run the complete SIP data preparation pipeline.

Flow:

Excel
    ↓
Raw Tables
    ↓
Canonical Tables

Future:

Workday
Snowflake
API

will use the same pipeline.
"""

from sip_automation import create_application


def main() -> None:
    with create_application() as application:

        result = application.run_data_preparation(
            initiated_by="local_development"
        )

        print()
        print("=" * 80)
        print("PIPELINE COMPLETED")
        print("=" * 80)
        print(f"Run ID      : {result.run_id}")
        print(f"Status      : {result.status}")
        print(f"Raw Rows    : {result.raw_row_count}")
        print(f"Canonical   : {result.canonical_row_count}")
        print()


if __name__ == "__main__":
    main()