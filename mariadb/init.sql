-- MariaDB init script
--
-- Table creation is handled by MariaDBClient's schema sync on app startup
-- (see app/data/mysql/model.py and .agent-docs/adr/0005-additive-only-schema-sync.md).
-- This file only needs to guarantee the database itself exists.

CREATE DATABASE IF NOT EXISTS octopus;
