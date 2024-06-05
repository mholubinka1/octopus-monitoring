CREATE SCHEMA octopus
    CREATE TABLE consumption
    (
        energy char(1),
        serial_number varchar(50),
        mpan_mprn varchar(21),
        period_from timestamptz,
        period_to timestamptz,
        raw_value double precision,
        est_kwh double precision,
    )
    CREATE TABLE cost
    (
        energy char(1),
        tariff varchar(50),
        is_active boolean,
        period_from timestamptz,
        period_to timestamptz,
        cost_gbp double precision,
    )
    CREATE TABLE tariffs
    (
        energy char(1),
        product_code varchar(50),
        tariff varchar(50),
        is_active boolean,
        valid_from timestamptz,
        valid_to timestamptz,
        period_from timestamptz,
        period_to timestamptz,
        standing_charge double precision,
        unit_rate double precision,
    )