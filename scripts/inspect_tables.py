"""
Inspect database tables.
"""

from sqlalchemy import text

from sip_automation import create_application

TABLES = [

    "raw.employee",
    "raw.bp",
    "raw.sales",

    "canonical.employee",
    "canonical.bp",
    "canonical.sales",

    "core.fact_fx_rate",
    "core.bridge_employee_seller",
]


def main():

    with create_application() as application:

        engine = application.container.database_engine

        with engine.connect() as conn:

            print()

            for table in TABLES:

                count = conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table}"
                    )
                ).scalar()

                print(f"{table:35} {count}")


if __name__ == "__main__":
    main()