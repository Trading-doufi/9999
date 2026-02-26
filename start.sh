#!/bin/bash

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Starting Trading Bot System...${NC}"

if [ ! -d "$HOME/kafka" ]; then
    echo -e "${YELLOW}⚠️ Kafka not found. Please install Kafka first.${NC}"
    exit 1
fi

echo -e "${GREEN}🟢 Starting ZooKeeper...${NC}"
cd ~/kafka
bin/zookeeper-server-start.sh -daemon config/zookeeper.properties
sleep 10

echo -e "${GREEN}🟢 Starting Kafka...${NC}"
bin/kafka-server-start.sh -daemon config/server.properties
sleep 15

echo -e "${GREEN}🟢 Creating Kafka topics...${NC}"
cd ~/trading-bot-pro/scripts
./create_topics.sh

echo -e "${GREEN}🟢 Starting Redis...${NC}"
sudo systemctl start redis-server 2>/dev/null || redis-server --daemonize yes
sleep 2

echo -e "${GREEN}🟢 Starting MongoDB...${NC}"
sudo systemctl start mongodb 2>/dev/null || mongod --dbpath ~/data/db --fork --logpath ~/mongodb.log
sleep 2

echo -e "${GREEN}🟢 Starting Trading Bot...${NC}"
cd ~/trading-bot-pro

if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo -e "${YELLOW}⚠️ Virtual environment not found. Creating...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
fi

nohup python src/run.py > trading_bot.log 2>&1 &

echo -e "${GREEN}✅ All services started successfully!${NC}"
echo -e "${GREEN}📝 Check logs: tail -f trading_bot.log${NC}"
echo -e "${GREEN}📊 Signal logs: tail -f logs/signals.log${NC}"
EOF
chmod +x ~/trading-bot-pro/start.sh
