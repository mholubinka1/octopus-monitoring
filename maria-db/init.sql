-- MariaDB init script

CREATE DATABASE IF NOT EXISTS octopus;

USE octopus;

CREATE TABLE IF NOT EXISTS consumption
(
    id VARCHAR(50) NOT NULL,
    energy CHAR,
    period_from TIMESTAMP NOT NULL,
    period_to TIMESTAMP NOT NULL,
    raw_value DECIMAL UNSIGNED NOT NULL,
    unit VARCHAR(5),
    est_kwh DECIMAL UNSIGNED NOT NULL,
    PRIMARY KEY (id)
);


DROP TABLE IF EXISTS cost;
CREATE TABLE cost
(
    id VARCHAR(50) NOT NULL,
    tariff_id VARCHAR(50) NOT NULL,
    consumption_id VARCHAR(50) NOT NULL,
    energy CHAR,
    is_active BOOLEAN NOT NULL,
    period_from TIMESTAMP NOT NULL,
    period_to TIMESTAMP,
    cost_gbp DECIMAL NOT NULL,
    PRIMARY KEY (id)
);

DROP TABLE IF EXISTS tariff;

CREATE TABLE tariff
(
    id VARCHAR(50) NOT NULL,
    consumption_id VARCHAR(50),
    energy CHAR,
    product_code VARCHAR(50),
    tariff_code VARCHAR(50),
    is_active BOOLEAN NOT NULL,
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP,
    period_from TIMESTAMP NOT NULL,
    period_to TIMESTAMP,
    standing_charge DECIMAL NOT NULL,
    unit_rate DECIMAL NOT NULL,
    PRIMARY KEY (id)
);