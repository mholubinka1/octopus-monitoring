-- MariaDB init script

CREATE DATABASE IF NOT EXISTS octopus;

USE octopus;

CREATE TABLE IF NOT EXISTS consumption
(
    id VARCHAR(50) NOT NULL,
    energy CHAR,
    period_from TIMESTAMP NOT NULL,
    period_to TIMESTAMP NOT NULL,
    raw_value DECIMAL(8,5) UNSIGNED NOT NULL,
    unit VARCHAR(5),
    est_kwh DECIMAL(8,5) UNSIGNED NOT NULL,
    PRIMARY KEY (id)
);


DROP TABLE IF EXISTS cost;
DROP TABLE IF EXISTS tariff;

CREATE TABLE IF NOT EXISTS agreement
(
    id VARCHAR(50) NOT NULL,
    energy CHAR,
    product_code VARCHAR(50),
    tariff_code VARCHAR(50),
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS product
(
    product_code VARCHAR(50) NOT NULL,
    display_name VARCHAR(200),
    direction VARCHAR(10),
    PRIMARY KEY (product_code)
);

CREATE TABLE IF NOT EXISTS product_rate
(
    id VARCHAR(70) NOT NULL,
    product_code VARCHAR(50) NOT NULL,
    region CHAR,
    valid_from TIMESTAMP NOT NULL,
    valid_to TIMESTAMP,
    unit_rate DECIMAL(9,6) NOT NULL,
    standing_charge DECIMAL(9,6) NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS job_run
(
    id INT NOT NULL AUTO_INCREMENT,
    job_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    ran_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    error_message VARCHAR(1000),
    PRIMARY KEY (id)
);
