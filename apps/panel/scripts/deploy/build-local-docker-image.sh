#!/bin/bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
REPO_ROOT=$(cd -- "${SCRIPT_DIR}/../../../.." && pwd)
LOG_FILE=${SCRIPT_DIR}/build-local-docker-image.log
ERROR=""
IMAGE_NAME="aurorabot-panel-local"

function stop_and_remove_container() {
    # Stop and remove the existing container
    docker stop ${IMAGE_NAME} >/dev/null 2>&1
    docker rm ${IMAGE_NAME} >/dev/null 2>&1
}

function remove_image() {
    # Remove the existing image
    docker rmi ${IMAGE_NAME} >/dev/null 2>&1
}

function install_dependencies() {
    # Install all dependencies
    cd "${REPO_ROOT}"
    pnpm install --frozen-lockfile || ERROR="install_dependencies failed"
}

function build_image() {
    # build docker
    docker build "${REPO_ROOT}" -f "${SCRIPT_DIR}/Dockerfile" -t "${IMAGE_NAME}" || ERROR="build_image failed"
}

function log_message() {
    if [[ ${ERROR} != "" ]];
    then
        >&2 echo "build failed, Please check build-local-docker-image.log for more details"
        >&2 echo "ERROR: ${ERROR}"
        exit 1
    else
        echo "docker image with tag '${IMAGE_NAME}' built sussessfully. Use below sample command to run the container"
        echo ""
        echo "# 必须使用 host 网络：nginx 需要访问主机 loopback 上的后端（127.0.0.1:8765）"
        echo "docker run -d --network host --name ${IMAGE_NAME} ${IMAGE_NAME}"
        echo "# 访问 http://127.0.0.1:8080"
        echo "# 记得把 http://127.0.0.1:8080 加入后端 config/runtime.toml 的 runtime.panel.allowed_origins"
    fi
}

echo "Info: Stopping and removing existing container and image" | tee ${LOG_FILE}
stop_and_remove_container
remove_image

echo "Info: Installing dependencies" | tee -a ${LOG_FILE}
install_dependencies 1>> ${LOG_FILE} 2>> ${LOG_FILE}

if [[ ${ERROR} == "" ]]; then
    echo "Info: Building docker image" | tee -a ${LOG_FILE}
    build_image 1>> ${LOG_FILE} 2>> ${LOG_FILE}
fi

log_message | tee -a ${LOG_FILE}
