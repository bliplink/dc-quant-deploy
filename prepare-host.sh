#!/usr/bin/env bash
set -euo pipefail

MODE="install"
DRY_RUN="false"
DOCKER_USER="${DOCKER_USER:-}"
DOCKER_DATA_ROOT="${DOCKER_DATA_ROOT:-}"
LEGACY_VFS_DOCKER_DATA_ROOT="${LEGACY_VFS_DOCKER_DATA_ROOT:-/opt/sumscope/docker-data}"
OS_RELEASE_FILE="${PREPARE_HOST_OS_RELEASE_FILE:-/etc/os-release}"
LEGACY_EL7_DOCKER_VERSION="26.1.4-1.el7"
LEGACY_EL7_CONTAINERD_VERSION="1.6.33-3.1.el7"
LEGACY_EL7_BUILDX_VERSION="0.14.1-1.el7"
LEGACY_EL7_COMPOSE_VERSION="2.27.1-1.el7"
LEGACY_EL7_VAULT_BASE_URL="${LEGACY_EL7_VAULT_BASE_URL:-https://mirrors.aliyun.com/centos-vault/7.9.2009}"
LEGACY_EL7_DOCKER_REPO_BASE_URL="${LEGACY_EL7_DOCKER_REPO_BASE_URL:-https://mirrors.aliyun.com/docker-ce/linux/centos/7}"
DOCKER_COMPOSE_VERSION="${DOCKER_COMPOSE_VERSION:-v2.27.1}"
DOCKER_COMPOSE_RELEASE_BASE_URL="${DOCKER_COMPOSE_RELEASE_BASE_URL:-https://github.com/docker/compose/releases/download}"
RPM_REPO_ARGS=()

usage() {
  cat <<'USAGE'
Usage:
  sudo ./prepare-host.sh [--check] [--dry-run] [--docker-user USER]

Install and verify the Docker runtime required by dc-quant-deploy.

Options:
  --check             Verify Docker Engine, Docker Compose v2, and the service.
  --dry-run           Print installation commands without changing the host.
  --docker-user USER  Add an existing user to the docker group after installation.
  -h, --help          Show this help.

Supported operating systems:
  Amazon Linux, CentOS, RHEL, Rocky Linux, AlmaLinux, Ubuntu, and Debian.

The script is idempotent. It does not deploy DC Quant or overwrite an existing
Docker daemon configuration. On a fresh legacy EL7 host where Docker falls back
to vfs, it uses /opt/sumscope/docker-data when that mount is available.
Membership in the docker group grants root-equivalent access.
USAGE
}

log() {
  printf '[prepare-host] %s\n' "$*"
}

die() {
  printf '[prepare-host] ERROR: %s\n' "$*" >&2
  exit 1
}

print_command() {
  printf '[prepare-host] DRY-RUN:'
  printf ' %q' "$@"
  printf '\n'
}

run() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    print_command "$@"
    return 0
  fi
  "$@"
}

write_file() {
  local target="$1"
  local content="$2"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY-RUN: write ${target}"
    return 0
  fi
  printf '%s\n' "${content}" > "${target}"
}

parse_args() {
  while [[ "$#" -gt 0 ]]; do
    case "$1" in
      --check)
        MODE="check"
        ;;
      --dry-run)
        DRY_RUN="true"
        ;;
      --docker-user)
        shift
        [[ "$#" -gt 0 ]] || die "--docker-user requires a username"
        DOCKER_USER="$1"
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unexpected argument: $1"
        ;;
    esac
    shift
  done
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Run this command as root or with sudo."
  fi
}

load_os_release() {
  [[ -r "${OS_RELEASE_FILE}" ]] || die "Cannot read ${OS_RELEASE_FILE}"

  # shellcheck disable=SC1090
  . "${OS_RELEASE_FILE}"
  OS_ID="${ID,,}"
  OS_VERSION_ID="${VERSION_ID:-}"
  OS_CODENAME="${VERSION_CODENAME:-}"

  case "${OS_ID}" in
    amzn|centos|rhel|rocky|almalinux|ubuntu|debian)
      ;;
    *)
      die "Unsupported operating system: ${OS_ID}. See --help for supported systems."
      ;;
  esac

  case "$(uname -m)" in
    x86_64|aarch64)
      ;;
    *)
      die "Unsupported CPU architecture: $(uname -m)"
      ;;
  esac
}

legacy_el7() {
  [[ "${OS_ID}" =~ ^(centos|rhel|rocky|almalinux)$ ]] &&
    [[ "${OS_VERSION_ID%%.*}" == "7" ]]
}

amazon_linux_2() {
  [[ "${OS_ID}" == "amzn" ]] && [[ "${OS_VERSION_ID%%.*}" == "2" ]]
}

compose_plugin_arch() {
  case "$(uname -m)" in
    x86_64)
      printf 'x86_64\n'
      ;;
    aarch64)
      printf 'aarch64\n'
      ;;
  esac
}

install_compose_plugin_binary() {
  local architecture plugin_dir plugin_path temporary_path download_url
  docker_compose_ready && return 0

  architecture="$(compose_plugin_arch)"
  plugin_dir="/usr/local/lib/docker/cli-plugins"
  plugin_path="${plugin_dir}/docker-compose"
  temporary_path="${plugin_path}.tmp"
  download_url="${DOCKER_COMPOSE_RELEASE_BASE_URL}/${DOCKER_COMPOSE_VERSION}/docker-compose-linux-${architecture}"

  log "Installing Docker Compose ${DOCKER_COMPOSE_VERSION} CLI plugin."
  run mkdir -p "${plugin_dir}"
  run curl -fsSL "${download_url}" -o "${temporary_path}"
  run chmod 0755 "${temporary_path}"
  run mv -f "${temporary_path}" "${plugin_path}"
}

docker_engine_ready() {
  command -v docker >/dev/null 2>&1
}

docker_compose_ready() {
  docker_engine_ready && docker compose version >/dev/null 2>&1
}

require_systemd() {
  command -v systemctl >/dev/null 2>&1 ||
    die "systemd is required to manage the Docker service."
}

resolve_rpm_package_manager() {
  if command -v dnf >/dev/null 2>&1; then
    printf 'dnf\n'
  elif command -v yum >/dev/null 2>&1; then
    printf 'yum\n'
  else
    die "Neither dnf nor yum is available."
  fi
}

configure_legacy_el7_repository() {
  local repository_file="/etc/yum.repos.d/dc-centos7-vault.repo"
  local repository_content

  repository_content='[dc-centos7-base]
name=DC CentOS 7.9.2009 Vault - Base
baseurl='"${LEGACY_EL7_VAULT_BASE_URL}"'/os/$basearch/
enabled=1
gpgcheck=0

[dc-centos7-updates]
name=DC CentOS 7.9.2009 Vault - Updates
baseurl='"${LEGACY_EL7_VAULT_BASE_URL}"'/updates/$basearch/
enabled=1
gpgcheck=0

[dc-centos7-extras]
name=DC CentOS 7.9.2009 Vault - Extras
baseurl='"${LEGACY_EL7_VAULT_BASE_URL}"'/extras/$basearch/
enabled=1
gpgcheck=0'

  log "Legacy EL7 detected; configuring archived CentOS repositories."
  write_file "${repository_file}" "${repository_content}"
  RPM_REPO_ARGS=(
    --disablerepo=base
    --disablerepo=updates
    --disablerepo=extras
    --enablerepo=dc-centos7-base
    --enablerepo=dc-centos7-updates
    --enablerepo=dc-centos7-extras
  )
}

configure_legacy_el7_docker_repository() {
  local repository_file="/etc/yum.repos.d/docker-ce.repo"
  local repository_content

  repository_content='[docker-ce-stable]
name=Docker CE Stable - $basearch
baseurl='"${LEGACY_EL7_DOCKER_REPO_BASE_URL}"'/$basearch/stable
enabled=1
gpgcheck=1
gpgkey=https://mirrors.aliyun.com/docker-ce/linux/centos/gpg'

  log "Configuring the archived EL7 Docker CE repository mirror."
  write_file "${repository_file}" "${repository_content}"
}

configure_rpm_repository() {
  local package_manager="$1"

  run "${package_manager}" "${RPM_REPO_ARGS[@]}" install -y ca-certificates curl
  run update-ca-trust

  if [[ "${package_manager}" == "dnf" ]]; then
    run dnf "${RPM_REPO_ARGS[@]}" install -y dnf-plugins-core
    if legacy_el7; then
      configure_legacy_el7_docker_repository
    elif [[ ! -f /etc/yum.repos.d/docker-ce.repo ]]; then
      run dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    fi
  else
    run yum "${RPM_REPO_ARGS[@]}" install -y yum-utils
    if legacy_el7; then
      configure_legacy_el7_docker_repository
    elif [[ ! -f /etc/yum.repos.d/docker-ce.repo ]]; then
      run yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
    fi
  fi
}

install_rpm_packages() {
  local package_manager
  package_manager="$(resolve_rpm_package_manager)"
  if legacy_el7; then
    configure_legacy_el7_repository
  fi
  configure_rpm_repository "${package_manager}"

  if legacy_el7; then
    log "Legacy EL7 detected; installing the final Docker CE packages published for EL7."
    if docker_engine_ready; then
      run "${package_manager}" "${RPM_REPO_ARGS[@]}" install -y \
        "docker-buildx-plugin-${LEGACY_EL7_BUILDX_VERSION}" \
        "docker-compose-plugin-${LEGACY_EL7_COMPOSE_VERSION}"
    else
      run "${package_manager}" "${RPM_REPO_ARGS[@]}" install -y \
        "docker-ce-${LEGACY_EL7_DOCKER_VERSION}" \
        "docker-ce-cli-${LEGACY_EL7_DOCKER_VERSION}" \
        "containerd.io-${LEGACY_EL7_CONTAINERD_VERSION}" \
        "docker-buildx-plugin-${LEGACY_EL7_BUILDX_VERSION}" \
        "docker-compose-plugin-${LEGACY_EL7_COMPOSE_VERSION}"
    fi
    return 0
  fi

  if docker_engine_ready; then
    log "Docker Engine already exists; installing the Compose and Buildx plugins."
    run "${package_manager}" install -y docker-buildx-plugin docker-compose-plugin
  else
    run "${package_manager}" install -y \
      docker-ce \
      docker-ce-cli \
      containerd.io \
      docker-buildx-plugin \
      docker-compose-plugin
  fi
}

install_amazon_linux_packages() {
  local package_manager
  package_manager="$(resolve_rpm_package_manager)"

  run "${package_manager}" install -y ca-certificates curl

  if docker_engine_ready; then
    log "Docker Engine already exists; checking the Compose v2 plugin."
  else
    if amazon_linux_2 && command -v amazon-linux-extras >/dev/null 2>&1; then
      run amazon-linux-extras enable docker
      run yum clean metadata
    fi
    run "${package_manager}" install -y docker
  fi

  install_compose_plugin_binary
}

configure_deb_repository() {
  local repository_os="$1"
  local keyring="/etc/apt/keyrings/docker.asc"
  local repository_file="/etc/apt/sources.list.d/docker.list"
  local temporary_keyring="${keyring}.tmp"
  local architecture
  local repository

  run apt-get update
  run apt-get install -y ca-certificates curl
  run install -m 0755 -d /etc/apt/keyrings

  run curl -fsSL "https://download.docker.com/linux/${repository_os}/gpg" -o "${temporary_keyring}"
  run mv "${temporary_keyring}" "${keyring}"
  run chmod a+r "${keyring}"

  architecture="$(dpkg --print-architecture)"
  [[ -n "${OS_CODENAME}" ]] || die "VERSION_CODENAME is missing from ${OS_RELEASE_FILE}"
  repository="deb [arch=${architecture} signed-by=${keyring}] https://download.docker.com/linux/${repository_os} ${OS_CODENAME} stable"
  write_file "${repository_file}" "${repository}"
  run apt-get update
}

install_deb_packages() {
  configure_deb_repository "${OS_ID}"

  if docker_engine_ready; then
    log "Docker Engine already exists; installing the Compose and Buildx plugins."
    run apt-get install -y docker-buildx-plugin docker-compose-plugin
  else
    run apt-get install -y \
      docker-ce \
      docker-ce-cli \
      containerd.io \
      docker-buildx-plugin \
      docker-compose-plugin
  fi
}

install_docker() {
  case "${OS_ID}" in
    amzn)
      install_amazon_linux_packages
      ;;
    centos|rhel|rocky|almalinux)
      install_rpm_packages
      ;;
    ubuntu|debian)
      install_deb_packages
      ;;
    *)
      die "Unsupported operating system: ${OS_ID}"
      ;;
  esac
}

enable_docker_service() {
  require_systemd
  run systemctl enable --now docker
}

resolve_vfs_data_root() {
  if [[ -n "${DOCKER_DATA_ROOT}" ]]; then
    printf '%s\n' "${DOCKER_DATA_ROOT}"
    return 0
  fi

  if legacy_el7 &&
     [[ -d "/opt/sumscope" ]] &&
     mountpoint -q "/opt/sumscope"; then
    printf '%s\n' "${LEGACY_VFS_DOCKER_DATA_ROOT}"
  fi
}

configure_fresh_vfs_data_root() {
  local target current_driver current_root
  target="$(resolve_vfs_data_root)"
  [[ -n "${target}" ]] || return 0
  [[ "${target}" == /* ]] || die "DOCKER_DATA_ROOT must be an absolute path."

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "DRY-RUN: configure fresh vfs Docker data root at ${target} when required."
    return 0
  fi

  current_driver="$(docker info --format '{{.Driver}}' 2>/dev/null || true)"
  current_root="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true)"
  [[ "${current_driver}" == "vfs" ]] || return 0
  [[ "${current_root}" != "${target}" ]] || return 0

  if [[ -e "/etc/docker/daemon.json" ]]; then
    log "Docker uses vfs, but /etc/docker/daemon.json already exists; leaving it unchanged."
    return 0
  fi

  if [[ -n "$(docker ps -aq 2>/dev/null)" ]] ||
     [[ -n "$(docker images -q 2>/dev/null)" ]]; then
    log "Docker uses vfs and already contains data; automatic data-root migration was skipped."
    log "Set DOCKER_DATA_ROOT and migrate Docker data during a maintenance window."
    return 0
  fi

  log "Docker uses vfs on a fresh host; moving its data root to ${target}."
  run mkdir -p "${target}" /etc/docker
  run systemctl stop docker docker.socket
  write_file "/etc/docker/daemon.json" \
    '{"data-root":"'"${target}"'","storage-driver":"vfs"}'
  run systemctl start docker
}

configure_docker_user() {
  [[ -n "${DOCKER_USER}" ]] || return 0

  getent passwd "${DOCKER_USER}" >/dev/null ||
    die "User does not exist: ${DOCKER_USER}"

  run usermod -aG docker "${DOCKER_USER}"
  log "Added ${DOCKER_USER} to the docker group."
  log "The user must log out and back in before group membership takes effect."
}

validate_runtime() {
  local failed="false"

  if ! docker_engine_ready; then
    printf '[prepare-host] ERROR: docker command is missing.\n' >&2
    failed="true"
  fi

  if ! docker_compose_ready; then
    printf '[prepare-host] ERROR: Docker Compose v2 plugin is missing.\n' >&2
    failed="true"
  fi

  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-enabled docker >/dev/null 2>&1; then
      printf '[prepare-host] ERROR: Docker is not enabled at boot.\n' >&2
      failed="true"
    fi
    if ! systemctl is-active docker >/dev/null 2>&1; then
      printf '[prepare-host] ERROR: Docker service is not active.\n' >&2
      failed="true"
    fi
  else
    printf '[prepare-host] ERROR: systemctl is missing.\n' >&2
    failed="true"
  fi

  if docker_engine_ready && ! docker info >/dev/null 2>&1; then
    printf '[prepare-host] ERROR: Docker daemon is not reachable.\n' >&2
    failed="true"
  fi

  [[ "${failed}" == "false" ]] || return 1

  log "$(docker --version)"
  log "$(docker compose version)"
  log "Docker runtime is ready for dc-quant-deploy."
}

main() {
  parse_args "$@"
  load_os_release

  if [[ "${MODE}" == "check" ]]; then
    validate_runtime
    exit 0
  fi

  require_root

  if docker_engine_ready && docker_compose_ready; then
    log "Docker Engine and Compose v2 are already installed."
  else
    install_docker
  fi

  enable_docker_service
  configure_fresh_vfs_data_root
  configure_docker_user

  if [[ "${DRY_RUN}" == "true" ]]; then
    log "Dry run completed; no host changes were made."
    exit 0
  fi

  validate_runtime
}

main "$@"
