#!/bin/bash
# The application role, with its password, before the first migration runs.
# Migration 0001 creates the role without one if it is missing; a server
# that accepts connections over the network needs the password set here.
set -euo pipefail
psql -v ON_ERROR_STOP=1 --username postgres --dbname vp <<SQL
create role vp_app login password '${VP_APP_PASSWORD}';
SQL
