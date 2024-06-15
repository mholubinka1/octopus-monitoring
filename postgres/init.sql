CREATE SCHEMA octopus
    CREATE TABLE consumption
    (
        id varchar(50),
        energy char(1),
        period_from timestamptz,
        period_to timestamptz,
        raw_value double precision,
        unit varchar(5),
        est_kwh double precision,
        PRIMARY KEY (id)
    )
    CREATE TABLE cost
    (
        id varchar(50),
        tariff_id varchar(50),
        consumption_id varchar(50),
        energy char(1),
        is_active boolean,
        period_from timestamptz,
        period_to timestamptz,
        cost_gbp double precision,
        PRIMARY KEY (id)
    )
    CREATE TABLE tariff
    (
        id varchar(50),
        consumption_id varchar(50),
        energy char(1),
        product_code varchar(50),
        tariff_code varchar(50),
        is_active boolean,
        valid_from timestamptz,
        valid_to timestamptz,
        period_from timestamptz,
        period_to timestamptz,
        standing_charge double precision,
        unit_rate double precision,
        PRIMARY KEY (id)
    )