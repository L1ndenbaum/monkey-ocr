#!/bin/bash

# OCR Backend 一键部署脚本
# 功能：拉取git仓库，构建Docker镜像，启动OCR服务
#
# 使用方法:
#   ./deploy_ocr.sh                         # 正常部署（包含代码拉取）
#   ./deploy_ocr.sh --skip-git              # 跳过代码拉取，直接部署
#   ./deploy_ocr.sh --env-file=.env         # 指定运行时环境变量文件
#   ./deploy_ocr.sh --build-env-file=.env.build # 指定构建期环境变量文件

set -e  # 遇到错误立即退出

# 设置颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# 配置参数
PROJECT_NAME="${PROJECT_NAME:-ocr-backend}"
OCR_PORT="${OCR_PORT:-7860}"
DEPLOY_DIR="$(pwd)"
SKIP_GIT=false
RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-.env}"
BUILD_ENV_FILE="${BUILD_ENV_FILE:-.env.build}"
BUILD_ENV_EXAMPLE_FILE="${BUILD_ENV_EXAMPLE_FILE:-.env.build.example}"
BUILD_ARGS=()
RUNTIME_ARGS=()

# 解析命令行参数
for arg in "$@"; do
    case $arg in
        --skip-git)
            SKIP_GIT=true
            ;;
        --env-file=*)
            RUNTIME_ENV_FILE="${arg#*=}"
            ;;
        --build-env-file=*)
            BUILD_ENV_FILE="${arg#*=}"
            ;;
        -h|--help)
            echo "使用方法:"
            echo "  $0                         # 正常部署（包含代码拉取）"
            echo "  $0 --skip-git              # 跳过代码拉取，直接部署"
            echo "  $0 --env-file=.env         # 指定运行时环境变量文件"
            echo "  $0 --build-env-file=.env.build # 指定构建期环境变量文件"
            exit 0
            ;;
        *)
            # 未知参数
            ;;
    esac
done

# 打印带颜色的消息
print_message() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# 打印标题
print_title() {
    echo -e "${BLUE}======================================${NC}"
    echo -e "${BLUE}    $1${NC}"
    echo -e "${BLUE}======================================${NC}"
}

# 检查命令是否存在
check_command() {
    local cmd=$1
    if ! command -v "$cmd" &> /dev/null; then
        print_message "$RED" "错误: $cmd 命令未找到，请先安装 $cmd"
        exit 1
    fi
}

load_env_file() {
    local env_file=$1
    if [ -f "$env_file" ]; then
        set -a
        # shellcheck disable=SC1090
        . "$env_file"
        set +a
    fi
}

rewrite_localhost_for_build() {
    local value=$1
    value="${value//127.0.0.1/host.docker.internal}"
    value="${value//localhost/host.docker.internal}"
    echo "$value"
}

append_build_arg() {
    local key=$1
    local value=$2
    if [ -n "$value" ]; then
        BUILD_ARGS+=(--build-arg "${key}=${value}")
    fi
}

load_build_env() {
    local selected_file=""
    if [ -f "$BUILD_ENV_FILE" ]; then
        selected_file="$BUILD_ENV_FILE"
    elif [ -f "$BUILD_ENV_EXAMPLE_FILE" ]; then
        selected_file="$BUILD_ENV_EXAMPLE_FILE"
    fi

    if [ -n "$selected_file" ]; then
        print_message "$YELLOW" "加载构建环境变量: $selected_file"
        load_env_file "$selected_file"
    else
        print_message "$YELLOW" "未找到构建环境变量文件，使用Dockerfile默认值"
    fi
}

prepare_build_args() {
    BUILD_ARGS=(--add-host=host.docker.internal:host-gateway)

    local http_proxy_value="${HTTP_PROXY:-${http_proxy:-}}"
    local https_proxy_value="${HTTPS_PROXY:-${https_proxy:-}}"
    local no_proxy_value="${NO_PROXY:-${no_proxy:-}}"

    http_proxy_value="$(rewrite_localhost_for_build "$http_proxy_value")"
    https_proxy_value="$(rewrite_localhost_for_build "$https_proxy_value")"

    append_build_arg HTTP_PROXY "$http_proxy_value"
    append_build_arg HTTPS_PROXY "$https_proxy_value"
    append_build_arg http_proxy "$http_proxy_value"
    append_build_arg https_proxy "$https_proxy_value"
    append_build_arg NO_PROXY "$no_proxy_value"
    append_build_arg no_proxy "$no_proxy_value"
    append_build_arg PIP_INDEX_URL "${PIP_INDEX_URL:-}"
    append_build_arg PIP_EXTRA_INDEX_URL "${PIP_EXTRA_INDEX_URL:-}"
    append_build_arg PIP_TRUSTED_HOST "${PIP_TRUSTED_HOST:-}"
}

prepare_runtime_args() {
    RUNTIME_ARGS=()
    if [ -f "$RUNTIME_ENV_FILE" ]; then
        print_message "$YELLOW" "加载运行环境变量: $RUNTIME_ENV_FILE"
        RUNTIME_ARGS+=(--env-file "$RUNTIME_ENV_FILE")
    else
        print_message "$YELLOW" "未找到 $RUNTIME_ENV_FILE，使用应用默认运行配置"
    fi
}

# 检查并杀掉占用指定端口的进程
kill_port() {
    local port=$1
    local service_name=$2

    print_message "$YELLOW" "检查端口 $port 是否被占用..."

    # 查找占用端口的进程
    local pid
    pid=$(lsof -ti:"$port" 2>/dev/null || true)

    if [ -n "$pid" ]; then
        print_message "$RED" "发现端口 $port 被进程 $pid 占用，正在终止..."
        kill -9 $pid 2>/dev/null || true
        sleep 2

        # 再次检查是否成功终止
        local check_pid
        check_pid=$(lsof -ti:"$port" 2>/dev/null || true)
        if [ -z "$check_pid" ]; then
            print_message "$GREEN" "✓ 成功清理端口 $port"
        else
            print_message "$RED" "✗ 清理端口 $port 失败，可能需要手动处理"
        fi
    else
        print_message "$GREEN" "✓ 端口 $port 未被占用"
    fi
}

# 停止并删除现有容器
cleanup_containers() {
    print_message "$YELLOW" "清理现有容器..."

    # 停止容器
    docker stop "${PROJECT_NAME}" 2>/dev/null || true

    # 删除容器
    docker rm "${PROJECT_NAME}" 2>/dev/null || true

    print_message "$GREEN" "✓ 容器清理完成"
}

# 拉取或更新代码
update_code() {
    if [ "$SKIP_GIT" = true ]; then
        print_title "跳过代码更新"
        print_message "$YELLOW" "已跳过代码拉取，使用当前代码进行部署"
        return
    fi

    print_title "更新代码"

    if [ -d ".git" ]; then
        print_message "$YELLOW" "检测到Git仓库，正在拉取最新代码..."
        git fetch origin
        git reset --hard origin/$(git rev-parse --abbrev-ref HEAD)
        print_message "$GREEN" "✓ 代码更新完成"
    else
        print_message "$YELLOW" "未检测到Git仓库，跳过代码拉取"
        print_message "$YELLOW" "如需使用Git管理代码，请先初始化Git仓库"
    fi
}

# 构建OCR镜像
build_ocr() {
    print_title "构建OCR镜像"

    load_build_env
    prepare_build_args

    print_message "$YELLOW" "正在构建OCR Docker镜像..."
    DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}" docker build "${BUILD_ARGS[@]}" -f Dockerfile.ocr -t "${PROJECT_NAME}:latest" .
    print_message "$GREEN" "✓ OCR镜像构建完成"
}

# 启动OCR服务
start_ocr() {
    print_title "启动OCR服务"

    prepare_runtime_args

    print_message "$YELLOW" "正在启动OCR容器..."
    docker run -d \
        --name "${PROJECT_NAME}" \
        -p "${OCR_PORT}:7860" \
        --gpus all \
        -v "$(pwd)/uploads:/app/uploads" \
        -v "$(pwd)/processed:/app/processed" \
        -v "$(pwd)/docling_models:/app/docling_models" \
        -v "$(pwd)/docling_cache:/app/docling_cache" \
        "${RUNTIME_ARGS[@]}" \
        --restart unless-stopped \
        "${PROJECT_NAME}:latest"

    print_message "$GREEN" "✓ OCR服务已启动"
    print_message "$GREEN" "  - OCR服务地址: http://localhost:${OCR_PORT}"
}

# 等待服务启动
wait_for_service() {
    print_title "等待服务启动"

    print_message "$YELLOW" "等待OCR服务启动..."
    local service_ready=false
    local attempts=0
    local max_attempts=30

    while [ $attempts -lt $max_attempts ] && [ "$service_ready" = false ]; do
        if curl -s "http://localhost:${OCR_PORT}/api/health" > /dev/null 2>&1; then
            service_ready=true
            print_message "$GREEN" "✓ OCR服务已就绪"
        else
            print_message "$YELLOW" "等待OCR服务启动... (${attempts}/${max_attempts})"
            sleep 2
            attempts=$((attempts + 1))
        fi
    done

    if [ "$service_ready" = false ]; then
        print_message "$RED" "⚠ OCR服务启动超时，请检查日志"
        print_message "$YELLOW" "查看日志命令: docker logs ${PROJECT_NAME}"
    fi
}

# 显示部署结果
show_result() {
    print_title "部署完成"

    print_message "$GREEN" "🎉 OCR Backend部署成功!"
    echo ""
    print_message "$GREEN" "服务地址:"
    print_message "$GREEN" "  - OCR API: http://localhost:${OCR_PORT}"
    print_message "$GREEN" "  - 健康检查: http://localhost:${OCR_PORT}/api/health"
    print_message "$GREEN" "  - 支持的文件类型: http://localhost:${OCR_PORT}/api/supported-types"
    echo ""
    print_message "$YELLOW" "常用命令:"
    print_message "$YELLOW" "  - 查看容器状态: docker ps"
    print_message "$YELLOW" "  - 查看服务日志: docker logs ${PROJECT_NAME}"
    print_message "$YELLOW" "  - 查看实时日志: docker logs -f ${PROJECT_NAME}"
    print_message "$YELLOW" "  - 停止服务: docker stop ${PROJECT_NAME}"
    print_message "$YELLOW" "  - 重新部署: ./deploy_ocr.sh --skip-git"
    echo ""
    print_message "$BLUE" "API使用示例:"
    print_message "$BLUE" "  curl -X POST -F 'file=@example.pdf' http://localhost:${OCR_PORT}/api/process"
}

# 主函数
main() {
    if [ "$SKIP_GIT" = true ]; then
        print_title "OCR Backend一键部署 (跳过Git)"
    else
        print_title "OCR Backend一键部署"
    fi

    # 检查必要的命令
    print_message "$YELLOW" "检查系统环境..."
    check_command "docker"
    check_command "git"
    check_command "curl"
    check_command "lsof"
    print_message "$GREEN" "✓ 系统环境检查通过"

    # 检查Docker是否支持GPU
    if docker info | grep -q "nvidia"; then
        print_message "$GREEN" "✓ 检测到NVIDIA Docker支持"
    else
        print_message "$YELLOW" "⚠ 未检测到NVIDIA Docker支持，将使用CPU模式"
    fi

    # 清理端口
    print_message "$YELLOW" "清理端口..."
    kill_port "$OCR_PORT" "OCR服务"

    # 清理容器
    cleanup_containers

    # 更新代码
    update_code

    # 构建镜像
    build_ocr

    # 启动服务
    start_ocr

    # 等待服务启动
    wait_for_service

    # 显示结果
    show_result
}

# 脚本入口
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
