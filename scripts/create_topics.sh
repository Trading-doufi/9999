#!/bin/bash

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}🚀 Creating Kafka topics...${NC}"

KAFKA_HOME=~/kafka

topics=(
    "depth:3:1"
    "trades:3:1"
    "liquidations:1:1"
    "signals:1:1"
)

for topic_config in "${topics[@]}"; do
    IFS=':' read -r topic partitions replication <<< "$topic_config"
    
    echo "Creating topic: $topic"
    $KAFKA_HOME/bin/kafka-topics.sh --create \
        --bootstrap-server localhost:9092 \
        --topic "$topic" \
        --partitions "$partitions" \
        --replication-factor "$replication" 2>/dev/null
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✅ Topic $topic created${NC}"
    else
        echo "⚠️ Topic $topic might already exist"
    fi
done

echo -e "\n${GREEN}📋 Existing topics:${NC}"
$KAFKA_HOME/bin/kafka-topics.sh --list --bootstrap-server localhost:9092
EOF

