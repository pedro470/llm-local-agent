#!/usr/bin/env bash
# Confere os pré-requisitos do HOST (Ubuntu no WSL2) antes do `docker compose up`.
#
# O compose descreve o container; ele não instala nada na máquina. Este script confere o que
# precisa existir por baixo e para com uma mensagem clara se faltar algo.
#
# Uso (no WSL, da raiz do projeto):  bash docker/check-host.sh
# Saída: 0 = pode subir; 1 = falta pré-requisito (as linhas FALHA dizem o quê).
#
# Os caminhos podem ser trocados por variável de ambiente (útil para testar o próprio script):
#   DXG_DEVICE, LIBDXCORE, LIBROCDXG, OLLAMA_VOLUME, OLLAMA_CONTAINER

set -u

DXG_DEVICE="${DXG_DEVICE:-/dev/dxg}"
LIBDXCORE="${LIBDXCORE:-/usr/lib/wsl/lib/libdxcore.so}"
LIBROCDXG="${LIBROCDXG:-/opt/rocm/lib/librocdxg.so}"
OLLAMA_VOLUME="${OLLAMA_VOLUME:-ollama_data}"
OLLAMA_CONTAINER="${OLLAMA_CONTAINER:-ollama}"

falhas=0
avisos=0
ok()    { printf '  [ OK ]  %s\n' "$1"; }
falha() { printf '  [FALHA] %s\n          -> %s\n' "$1" "$2"; falhas=$((falhas + 1)); }
aviso() { printf '  [AVISO] %s\n          -> %s\n' "$1" "$2"; avisos=$((avisos + 1)); }

# Um bind cuja origem não existe vira PASTA VAZIA (o Docker cria). O container sobe, fica
# "healthy" e o Ollama roda na CPU sem avisar. Por isso a checagem é "arquivo regular", não "existe".
checa_arquivo() {  # $1 = caminho, $2 = o que é, $3 = como resolver
    if [ -f "$1" ]; then
        ok "$2: $1"
    elif [ -d "$1" ]; then
        falha "$2: $1 é uma PASTA (sobra de um bind sem origem)" "rmdir '$1' (com sudo) e depois: $3"
    else
        falha "$2 não encontrada: $1" "$3"
    fi
}

echo "== GPU (caminho ROCm -> librocdxg -> libdxcore -> /dev/dxg -> Windows)"
if [ -c "$DXG_DEVICE" ]; then
    ok "device de paravirtualização: $DXG_DEVICE"
else
    falha "$DXG_DEVICE não existe" \
          "isto vem do Windows: WSL2 atualizado (wsl --update) e driver AMD Adrenalin instalado"
fi
checa_arquivo "$LIBDXCORE" "libdxcore (Microsoft)" \
              "vem do Windows com o WSL2; rode wsl --update no PowerShell"
checa_arquivo "$LIBROCDXG" "librocdxg (ponte AMD)" \
              "instale o pacote rocdxg-roct (.deb da AMD); confira com: dpkg -L rocdxg-roct"

echo "== Docker"
if ! command -v docker >/dev/null 2>&1; then
    falha "comando docker não encontrado" "instale o Docker Engine no Ubuntu (Fase 1); não use o Docker Desktop"
elif ! docker info >/dev/null 2>&1; then
    falha "o dockerd não responde (ou falta permissão no /run/docker.sock)" \
          "sudo systemctl start docker; e o usuário no grupo: sudo usermod -aG docker \$USER (relogar)"
else
    ok "dockerd respondendo, sem sudo"
    if docker compose version >/dev/null 2>&1; then
        ok "docker compose: $(docker compose version --short)"
    else
        falha "plugin docker compose ausente" "sudo apt install docker-compose-plugin"
    fi
    if docker volume inspect "$OLLAMA_VOLUME" >/dev/null 2>&1; then
        ok "volume dos modelos: $OLLAMA_VOLUME"
    else
        falha "volume $OLLAMA_VOLUME não existe (o compose o declara como external)" \
              "docker volume create $OLLAMA_VOLUME; depois baixe os modelos: docker exec $OLLAMA_CONTAINER ollama pull gemma4:12b"
    fi
fi

echo "== Início automático"
if [ "$(ps -p 1 -o comm= 2>/dev/null)" = "systemd" ]; then
    ok "systemd é o PID 1"
    if systemctl is-enabled docker >/dev/null 2>&1; then
        ok "docker.service habilitado no boot"
    else
        aviso "docker.service não sobe no boot" "sudo systemctl enable docker"
    fi
else
    aviso "systemd não está ativo: o dockerd não sobe sozinho" \
          "em /etc/wsl.conf: [boot] systemd=true; depois wsl --shutdown no PowerShell"
fi

# O .wslconfig mora no Windows. Sem o instanceIdleTimeout em [general], a distro cai ~15 s depois
# do último wsl.exe e leva o container junto.
winprofile=""
if command -v cmd.exe >/dev/null 2>&1; then
    winprofile="$(cd /mnt/c 2>/dev/null && cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r')"
fi
if [ -n "$winprofile" ] && wslconfig="$(wslpath "$winprofile")/.wslconfig" && [ -f "$wslconfig" ]; then
    # O arquivo é do Windows (CRLF): tira o \r ANTES do awk, senão "[general]\r" != "[general]".
    secao_general="$(tr -d '\r' < "$wslconfig" | awk '/^\[/{s=$0} s=="[general]"')"
    if printf '%s\n' "$secao_general" | grep -Eq '^[[:space:]]*instanceIdleTimeout[[:space:]]*=[[:space:]]*-1'; then
        ok "distro fica ligada sem terminal ([general] instanceIdleTimeout=-1)"
    else
        aviso "a distro desliga quando o último wsl.exe fecha (o container cai junto)" \
              "em $winprofile\\.wslconfig: [general] instanceIdleTimeout=-1 (em [wsl2] é ignorada); depois wsl --shutdown"
    fi
else
    aviso "não achei o .wslconfig do Windows" \
          "crie %USERPROFILE%\\.wslconfig com [general] instanceIdleTimeout=-1"
fi

# Se o container já está de pé, confere o que importa de verdade: o Ollama achou a GPU?
if [ "$falhas" -eq 0 ] && docker inspect "$OLLAMA_CONTAINER" >/dev/null 2>&1 \
   && [ "$(docker inspect -f '{{.State.Running}}' "$OLLAMA_CONTAINER")" = "true" ]; then
    echo "== Container $OLLAMA_CONTAINER (já rodando)"
    if docker exec "$OLLAMA_CONTAINER" test -f /usr/lib/librocdxg.so; then
        ok "librocdxg montada como arquivo dentro do container"
    else
        falha "dentro do container a librocdxg não é um arquivo" \
              "corrija o host e recrie: docker compose -f docker/docker-compose.yml up -d --force-recreate"
    fi
    gpu="$(docker logs "$OLLAMA_CONTAINER" 2>&1 | grep 'inference compute' | tail -1)"
    if printf '%s' "$gpu" | grep -q 'library=ROCm'; then
        ok "Ollama na GPU: $(printf '%s' "$gpu" | grep -o 'description="[^"]*"')"
    else
        falha "o Ollama não achou a GPU (vai rodar na CPU)" \
              "veja: docker logs $OLLAMA_CONTAINER | grep -iE 'inference compute|rocm|dxg'"
    fi
fi

echo
if [ "$falhas" -eq 0 ]; then
    echo "Pronto para subir ($avisos aviso(s)): docker compose -f docker/docker-compose.yml up -d"
    exit 0
fi
echo "Faltam $falhas pré-requisito(s) e há $avisos aviso(s). Resolva as linhas FALHA antes do compose."
exit 1
