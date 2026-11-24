#!/bin/sh
# Runs once, on the first start of an empty Postgres volume (docker-entrypoint-initdb.d).
# Creates the least-privilege roles and the three app databases (plan 3.15):
#   eos_owner    owns the databases and schema; runs migrations, seed, rules report
#   eos_app      the API's login: data access only (SELECT/INSERT/UPDATE/DELETE), no DDL
#   eos_readonly the startup banner's login: SELECT only
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v owner_pw="$EOS_OWNER_PASSWORD" \
  -v app_pw="$EOS_APP_PASSWORD" \
  -v ro_pw="$EOS_READONLY_PASSWORD" <<'SQL'
CREATE ROLE eos_owner    LOGIN PASSWORD :'owner_pw';
CREATE ROLE eos_app      LOGIN PASSWORD :'app_pw';
CREATE ROLE eos_readonly LOGIN PASSWORD :'ro_pw';

CREATE DATABASE eos        OWNER eos_owner;
CREATE DATABASE eos_test   OWNER eos_owner;
CREATE DATABASE eos_report OWNER eos_owner;
SQL

for db in eos eos_test eos_report; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
REVOKE ALL ON DATABASE "$db" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$db" TO eos_owner, eos_app, eos_readonly;

-- In Postgres 15+ the public schema belongs to the database owner (eos_owner).
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO eos_app, eos_readonly;

-- Tables and sequences that eos_owner creates later (migrations) get these grants automatically.
ALTER DEFAULT PRIVILEGES FOR ROLE eos_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO eos_app;
ALTER DEFAULT PRIVILEGES FOR ROLE eos_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO eos_app;
ALTER DEFAULT PRIVILEGES FOR ROLE eos_owner IN SCHEMA public
  GRANT SELECT ON TABLES TO eos_readonly;
SQL
done
