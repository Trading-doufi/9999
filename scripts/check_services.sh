#!/bin/bash

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}🔍 Checking services status...${NC}\n"

echo -n "Kafka: "
if nc -z localhost 9092 2>/dev/null; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

echo -n "ZooKeeper: "
if nc -z localhost 2181 2>/dev/null; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

echo -n "Redis: "
if redis-cli ping 2>/dev/null | grep -q "PONG"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

echo -n "MongoDB: "
if mongosh --eval "db.runCommand({ping:1})" 2>/dev/null | grep -q "ok"; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${RED}❌ Not running${NC}"
fi

echo -n "Trading Bot: "
if pgrep -f "python.*run.py" > /dev/null; then
    echo -e "${GREEN}✅ Running${NC}"
else
    echo -e "${YELLOW}⚠️ Not running${NC}"
fi

echo -e "\n${GREEN}📊 Kafka Topics:${NC}"
~/kafka/bin/kafka-topics.sh --list --bootstrap-server localhost:9092 2>/dev/null || echo "Kafka not available"
