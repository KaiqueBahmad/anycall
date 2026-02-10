#!/bin/bash

# Script para fazer requisições de teste ao AnyCall Consumer

# Cores para output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# URL do consumer
CONSUMER_URL="http://localhost:8080"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  AnyCall - Test Request Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Verifica se o consumer está rodando
echo -e "${YELLOW}Checking if consumer is running on port 8080...${NC}"

# Tenta verificar se a porta está aberta
if command -v nc > /dev/null 2>&1; then
    # Usa netcat se disponível
    if ! nc -z localhost 8080 2>/dev/null; then
        echo -e "${RED}ERROR: Nothing is listening on port 8080${NC}"
        echo -e "${YELLOW}Please start the consumer first:${NC}"
        echo "  cd example-consumer && mvn spring-boot:run"
        exit 1
    fi
else
    # Fallback: tenta fazer um request simples
    if ! curl -s --connect-timeout 2 "${CONSUMER_URL}" > /dev/null 2>&1; then
        echo -e "${RED}ERROR: Cannot connect to ${CONSUMER_URL}${NC}"
        echo -e "${YELLOW}Please start the consumer first:${NC}"
        echo "  cd example-consumer && mvn spring-boot:run"
        exit 1
    fi
fi

echo -e "${GREEN}Consumer is running!${NC}"
echo ""

# Faz a requisição
echo -e "${YELLOW}Sending request to create a new product...${NC}"
echo -e "${BLUE}POST ${CONSUMER_URL}/products${NC}"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "${CONSUMER_URL}/products" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Mechanical Keyboard",
    "priceInCents": 15000
  }')

# Separa o corpo da resposta e o status code
HTTP_BODY=$(echo "$RESPONSE" | head -n -1)
HTTP_CODE=$(echo "$RESPONSE" | tail -n 1)

echo -e "${YELLOW}Response Status: ${NC}${HTTP_CODE}"
echo ""

if [ "$HTTP_CODE" -eq 200 ]; then
    echo -e "${GREEN}Success!${NC}"
    echo -e "${YELLOW}Response Body:${NC}"
    echo "$HTTP_BODY" | jq '.' 2>/dev/null || echo "$HTTP_BODY"
else
    echo -e "${RED}Request failed!${NC}"
    echo -e "${YELLOW}Response Body:${NC}"
    echo "$HTTP_BODY"
fi

echo ""
echo -e "${BLUE}========================================${NC}"
