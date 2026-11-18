#!/bin/sh
# Database dei test e dei dati reali (eseguito solo alla prima creazione del volume).
set -e
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE ${POSTGRES_DB}_test;"
# Dati reali, separati dai dati mock del database principale
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE DATABASE ${POSTGRES_DB}_real;"
