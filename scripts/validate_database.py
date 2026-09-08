from sip_automation import create_application


def main() -> None:
    with create_application() as application:
        repository = (
            application.container.reference_repository
        )

        fx_rates = repository.read_fx_rates(
            fiscal_year=2026,
            rate_basis="AOP",
            rate_type="Corporate",
        )

        print(fx_rates.columns.tolist())
        print(fx_rates.to_string(index=False))


if __name__ == "__main__":
    main()