#!/bin/bash
# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Forçar locale para usar ponto como separador decimal
export LC_NUMERIC="en_US.UTF-8"

# Função para log
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[ERRO]${NC} $1"
    exit 1
}

# Função para matar processos em uma porta
kill_port() {
    local port=$1
    local pid=$(lsof -t -i:$port 2>/dev/null)
    
    if [ -n "$pid" ]; then
        log "Matando processo na porta $port (PID: $pid)..."
        kill -9 $pid 2>/dev/null
        sleep 2
        
        # Verificar se ainda está rodando
        if lsof -t -i:$port > /dev/null 2>&1; then
            error "Não foi possível liberar a porta $port"
        else
            log "Porta $port liberada com sucesso"
        fi
    fi
}

# Diretórios dos projetos (relativos ao diretório dev/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
LIB_DIR="$BASE_DIR/lib"
EMISSOR_DIR="$BASE_DIR/example-supplier"
RECEPTOR_DIR="$BASE_DIR/example-consumer"

# Função para aguardar inicialização do Spring Boot
wait_spring_boot() {
    local log_file=$1
    local app_name=$2
    local max_attempts=120  # 2 minutos
    local attempt=0
    
    log "Aguardando $app_name iniciar..."
    
    while [ $attempt -lt $max_attempts ]; do
        if grep -q "Started.*Application in" "$log_file" 2>/dev/null; then
            log "$app_name iniciado com sucesso!"
            return 0
        fi
        
        # Verificar se houve erro
        if grep -qi "APPLICATION FAILED TO START" "$log_file" 2>/dev/null; then
            error "$app_name falhou ao iniciar. Verifique $log_file"
        fi
        
        sleep 1
        attempt=$((attempt + 1))
    done
    
    error "Timeout aguardando $app_name iniciar. Verifique $log_file"
}

# Limpar portas antes de começar
log "Verificando e liberando portas..."
kill_port 8080
kill_port 8081

# Passo 1: Recompilar e instalar biblioteca no repositório local Maven
log "Recompilando e instalando biblioteca no repositório local..."
cd "$LIB_DIR" || error "Diretório da biblioteca não encontrado: $LIB_DIR"
mvn clean install -DskipTests || error "Falha ao compilar biblioteca"

# Passo 2: Forçar projetos a usarem a nova versão local
log "Atualizando projeto emissor para usar nova versão..."
cd "$EMISSOR_DIR" || error "Diretório do emissor não encontrado: $EMISSOR_DIR"
mvn clean package -DskipTests -U || error "Falha ao compilar emissor"

log "Atualizando projeto receptor para usar nova versão..."
cd "$RECEPTOR_DIR" || error "Diretório do receptor não encontrado: $RECEPTOR_DIR"
mvn clean package -DskipTests -U || error "Falha ao compilar receptor"

# Limpar logs antigos
rm -f "$RECEPTOR_DIR/receptor.log" "$EMISSOR_DIR/emissor.log"

# Passo 3: Iniciar aplicações Spring Boot
log "Iniciando aplicação receptora..."
cd "$RECEPTOR_DIR"
mvn spring-boot:run > receptor.log 2>&1 &
RECEPTOR_PID=$!
wait_spring_boot "$RECEPTOR_DIR/receptor.log" "Receptor"

log "Iniciando aplicação emissora..."
cd "$EMISSOR_DIR"
mvn spring-boot:run > emissor.log 2>&1 &
EMISSOR_PID=$!
wait_spring_boot "$EMISSOR_DIR/emissor.log" "Emissor"

# Verificar se os processos ainda estão rodando
if ! ps -p $RECEPTOR_PID > /dev/null; then
    error "Receptor não está mais rodando. Verifique $RECEPTOR_DIR/receptor.log"
fi

if ! ps -p $EMISSOR_PID > /dev/null; then
    error "Emissor não está mais rodando. Verifique $EMISSOR_DIR/emissor.log"
fi

log "Aplicações iniciadas com sucesso!"
echo ""
echo "================================================"
echo "  RECEPTOR PID: $RECEPTOR_PID"
echo "  EMISSOR PID: $EMISSOR_PID"
echo "  RECEPTOR LOG: $RECEPTOR_DIR/receptor.log"
echo "  EMISSOR LOG: $EMISSOR_DIR/emissor.log"
echo "================================================"
echo ""

# Aquecimento (warm-up)
log "Fazendo warm-up (5 requisições)..."
for i in {1..5}; do
    curl -s -X POST http://localhost:8080/ping -H "Content-Type: application/json" -d '{}' > /dev/null
    sleep 0.1
done

echo ""
log "Executando 50 requisições de teste..."
echo ""

# Array para armazenar resultados
declare -a latencies=()
failed=0

# Fazer 50 requisições
for i in {1..50}; do
    printf "${CYAN}Requisição %2d:${NC} " "$i"
    
    response=$(curl -s -X POST http://localhost:8080/ping \
        -H "Content-Type: application/json" \
        -d '{}' \
        -w "\n%{http_code}" 2>/dev/null)
    
    http_code=$(echo "$response" | tail -n 1)
    latency_raw=$(echo "$response" | head -n 1)
    
    # Extrair apenas o número da resposta (remove "ms", espaços, etc)
    latency=$(echo "$latency_raw" | grep -oE '[0-9]+\.?[0-9]*' | head -n 1)
    
    if [ "$http_code" = "200" ] && [ -n "$latency" ] && [ "$latency" != "" ]; then
        latencies+=("$latency")
        printf "${GREEN}%s ms${NC}\n" "$latency"
    else
        failed=$((failed + 1))
        printf "${RED}FALHOU${NC} (HTTP: %s, Raw: %s)\n" "$http_code" "$latency_raw"
    fi
    
    # Pequeno delay para não sobrecarregar
    sleep 0.05
done

echo ""
echo "================================================"
echo -e "${BLUE}         RESULTADOS DO TESTE${NC}"
echo "================================================"
echo ""

# Calcular estatísticas
if [ ${#latencies[@]} -gt 0 ]; then
    # Ordenar array
    IFS=$'\n' sorted=($(sort -n <<<"${latencies[*]}"))
    unset IFS
    
    # Total de requisições bem-sucedidas
    total=${#latencies[@]}
    
    # Mínimo e máximo
    min=${sorted[0]}
    max=${sorted[$((total - 1))]}
    
    # Média
    sum=0
    for lat in "${latencies[@]}"; do
        sum=$(echo "$sum + $lat" | bc -l)
    done
    avg=$(echo "scale=2; $sum / $total" | bc -l)
    
    # Mediana
    mid=$((total / 2))
    if [ $((total % 2)) -eq 0 ]; then
        median=$(echo "scale=2; (${sorted[$((mid - 1))]} + ${sorted[$mid]}) / 2" | bc -l)
    else
        median=${sorted[$mid]}
    fi
    
    # Percentis
    p50_idx=$((total * 50 / 100))
    p90_idx=$((total * 90 / 100))
    p95_idx=$((total * 95 / 100))
    p99_idx=$((total * 99 / 100))
    
    # Garantir que índices não ultrapassem o limite
    [ $p50_idx -ge $total ] && p50_idx=$((total - 1))
    [ $p90_idx -ge $total ] && p90_idx=$((total - 1))
    [ $p95_idx -ge $total ] && p95_idx=$((total - 1))
    [ $p99_idx -ge $total ] && p99_idx=$((total - 1))
    
    p50=${sorted[$p50_idx]}
    p90=${sorted[$p90_idx]}
    p95=${sorted[$p95_idx]}
    p99=${sorted[$p99_idx]}
    
    # Exibir resultados
    echo -e "${YELLOW}Requisições totais:${NC}      50"
    echo -e "${GREEN}Bem-sucedidas:${NC}           $total"
    echo -e "${RED}Falhas:${NC}                  $failed"
    echo ""
    echo -e "${YELLOW}Estatísticas de Latência (ms):${NC}"
    echo "----------------------------"
    printf "Mínimo:          %10.2f ms\n" "$min"
    printf "Máximo:          %10.2f ms\n" "$max"
    printf "Média:           %10.2f ms\n" "$avg"
    printf "Mediana:         %10.2f ms\n" "$median"
    echo ""
    echo -e "${YELLOW}Percentis:${NC}"
    echo "----------------------------"
    printf "P50:             %10.2f ms\n" "$p50"
    printf "P90:             %10.2f ms\n" "$p90"
    printf "P95:             %10.2f ms\n" "$p95"
    printf "P99:             %10.2f ms\n" "$p99"
    
    # Distribuição visual simples
    echo ""
    echo -e "${YELLOW}Distribuição (faixas de latência):${NC}"
    echo "----------------------------"
    
    # Contadores para faixas
    range_0_10=0
    range_10_50=0
    range_50_100=0
    range_100_500=0
    range_500_plus=0
    
    for lat in "${latencies[@]}"; do
        # Converter para inteiro usando bc
        lat_int=$(echo "$lat / 1" | bc -l | cut -d. -f1)
        
        # Garantir que lat_int é um número válido
        if [ -z "$lat_int" ]; then
            lat_int=0
        fi
        
        if [ "$lat_int" -lt 10 ]; then
            range_0_10=$((range_0_10 + 1))
        elif [ "$lat_int" -lt 50 ]; then
            range_10_50=$((range_10_50 + 1))
        elif [ "$lat_int" -lt 100 ]; then
            range_50_100=$((range_50_100 + 1))
        elif [ "$lat_int" -lt 500 ]; then
            range_100_500=$((range_100_500 + 1))
        else
            range_500_plus=$((range_500_plus + 1))
        fi
    done
    
    printf "  0-10 ms:       %3d requisições\n" $range_0_10
    printf " 10-50 ms:       %3d requisições\n" $range_10_50
    printf " 50-100 ms:      %3d requisições\n" $range_50_100
    printf "100-500 ms:      %3d requisições\n" $range_100_500
    printf "500+ ms:         %3d requisições\n" $range_500_plus
    
else
    echo -e "${RED}Nenhuma requisição bem-sucedida!${NC}"
fi

echo ""
echo "================================================"
echo ""

# Aguardar input do usuário antes de fechar
read -p "Pressione ENTER para encerrar as aplicações..."

# Fechar aplicações
log "Encerrando aplicações..."
kill $EMISSOR_PID 2>/dev/null
kill $RECEPTOR_PID 2>/dev/null

# Aguardar processos finalizarem
wait $EMISSOR_PID 2>/dev/null
wait $RECEPTOR_PID 2>/dev/null

log "Aplicações encerradas"