#!/bin/bash
set -e

python3 main.py &

exec node --enable-source-maps artifacts/api-server/dist/index.mjs
