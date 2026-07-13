#!/bin/bash
# Start the Telegram bot in background
python main.py &

# Start the Node.js API server in foreground (this keeps the container alive)
node --enable-source-maps artifacts/api-server/dist/index.mjs
