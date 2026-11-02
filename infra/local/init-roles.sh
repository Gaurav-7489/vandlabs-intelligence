#!/bin/sh
set -e
psql -v ON_ERROR_STOP=1 -U postgres -f /dev/stdin <<'SQL'
CREATE ROLE vand_owner LOGIN PASSWORD 'dev_owner_pw' CREATEDB;
CREATE ROLE vand_app LOGIN PASSWORD 'dev_app_pw' NOSUPERUSER NOBYPASSRLS;
CREATE ROLE vand_worker LOGIN PASSWORD 'dev_worker_pw' NOSUPERUSER NOBYPASSRLS;
CREATE DATABASE vand_dev OWNER vand_owner;
CREATE DATABASE vand_test OWNER vand_owner;
SQL
