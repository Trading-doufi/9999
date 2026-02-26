#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${RED}🛑 Stopping Trading Bot System...${NC}"

pkill -f "python.*run.py"
sleep 2

cd ~/kafka
bin/kafka-server-stop.sh
sleep 5
bin/zookeeper-server-stop.sh

sudo systemctl stop redis-server 2>/dev/null || pkill redis-server
sudo systemctl stop mongodb 2>/dev/null || pkill mongod

echo -e "${GREEN}✅ All services stopped${NC}"
EOF
chmod +x ~/trading-bot-pro/stop.sh
