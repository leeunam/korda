"""Captura e promoção local dos arquivos de resultado após o fim da sandbox."""

import errno
import fcntl
import hashlib
import os
import re
import stat
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path


LIMITES = {"kpis.json": 1024**2, "por_pedido.csv": 32 * 1024**2, "por_viagem.csv": 32 * 1024**2}
PACOTE = "pacote.zip"
LIMITE_PACOTE = 72 * 1024**2
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@contextmanager
def _diretorio(caminho, *, criar=False):
    """Percorre até o diretório sem seguir links em nenhum componente."""
    caminho = Path(caminho).absolute()
    if ".." in caminho.parts:
        raise ValueError("diretório de artefatos com segmento inválido")
    fd = os.open(caminho.anchor, DIR)
    try:
        for parte in caminho.parts[1:]:
            if criar:
                try:
                    os.mkdir(parte, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            proximo = os.open(parte, DIR, dir_fd=fd)
            os.close(fd)
            fd = proximo
        yield fd
    finally:
        os.close(fd)


def _ler_arquivos(origem, destino=None, *, com_pacote=False):
    arquivos = {}
    limites = {**LIMITES, PACOTE: LIMITE_PACOTE} if com_pacote else LIMITES
    for nome, limite in limites.items():
        digest = hashlib.sha256()
        tamanho = 0
        with ExitStack() as abertos:
            fd = os.open(nome, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=origem)
            abertos.callback(os.close, fd)
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or not 0 < meta.st_size <= limite:
                raise ValueError(f"artefato não é arquivo regular exclusivo ou excede o tamanho permitido: {nome}")
            entrada = abertos.enter_context(os.fdopen(fd, "rb", closefd=False))
            if destino is not None:
                copia = os.open(nome, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=destino)
                saida = abertos.enter_context(os.fdopen(copia, "wb"))
            while bloco := entrada.read(128 * 1024):
                tamanho += len(bloco)
                if tamanho > limite:
                    raise ValueError(f"artefato excede o limite: {nome}")
                digest.update(bloco)
                if destino is not None:
                    saida.write(bloco)
            if tamanho != meta.st_size or os.fstat(fd).st_mtime_ns != meta.st_mtime_ns:
                raise ValueError(f"artefato mudou durante a captura: {nome}")
            if destino is not None:
                saida.flush()
                os.fsync(saida.fileno())
        arquivos[nome] = {"bytes": tamanho, "sha256": digest.hexdigest()}
    return {"arquivos": arquivos}


def _validar(manifesto):
    if not isinstance(manifesto, dict) or set(manifesto) != {"arquivos"}:
        raise ValueError("formato de manifesto inválido")
    itens = manifesto["arquivos"]
    if not isinstance(itens, dict) or set(itens) not in (set(LIMITES), set(LIMITES) | {PACOTE}):
        raise ValueError("manifesto deve conter os três resultados e, opcionalmente, o pacote de reprodução")
    for nome, meta in itens.items():
        limite = LIMITE_PACOTE if nome == PACOTE else LIMITES[nome]
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "bytes"}
                or type(meta["bytes"]) is not int or not 0 < meta["bytes"] <= limite
                or not isinstance(meta["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", meta["sha256"])):
            raise ValueError(f"tamanho ou hash inválido: {nome}")


def _publicar(origem, destino, *, esperado=None):
    destino = Path(destino)
    if destino.name in ("", ".", ".."):
        raise ValueError("nome de diretório de artefatos inválido")
    temporario = ".parcial-" + uuid.uuid4().hex
    with _diretorio(origem) as src, _diretorio(destino.parent, criar=True) as pai:
        nomes = set(esperado["arquivos"]) if esperado is not None else set(LIMITES)
        com_pacote = PACOTE in nomes
        if esperado is not None and set(os.listdir(src)) != nomes:
            raise ValueError("a lista de resultados para promoção mudou")
        os.mkdir(temporario, mode=0o700, dir_fd=pai)
        lote = os.open(temporario, DIR, dir_fd=pai)
        publicado = False
        try:
            manifesto = _ler_arquivos(src, lote, com_pacote=com_pacote)
            if esperado is not None and manifesto != esperado:
                raise ValueError("integridade dos resultados difere do manifesto aprovado")
            os.fsync(lote)
            try:
                existente = os.open(destino.name, DIR, dir_fd=pai)
            except FileNotFoundError:
                try:
                    os.rename(temporario, destino.name, src_dir_fd=pai, dst_dir_fd=pai)
                    publicado = True
                    os.fsync(pai)
                    return manifesto
                except OSError as erro:
                    # Publicação concorrente já ocupou o destino.
                    if erro.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                        raise
                existente = os.open(destino.name, DIR, dir_fd=pai)
            try:
                if set(os.listdir(existente)) != nomes or _ler_arquivos(existente, com_pacote=com_pacote) != manifesto:
                    raise ValueError("o destino já existe com conteúdo divergente")
            finally:
                os.close(existente)
            os.fsync(pai)
            return manifesto
        finally:
            try:
                if not publicado:
                    for nome in os.listdir(lote):
                        os.unlink(nome, dir_fd=lote)
                    os.rmdir(temporario, dir_fd=pai)
            finally:
                os.close(lote)


def capturar(origem: Path, staging: Path) -> dict:
    """Congela os três resultados em uma única mudança de nome no mesmo filesystem."""
    return _publicar(origem, staging)


def manifesto_revisao(resultados: Path) -> dict:
    """Sela o pacote v0.2 criado pelo host e os resultados que passaram pelo avaliador."""
    with _diretorio(resultados) as fd:
        fcntl.flock(fd, fcntl.LOCK_SH)
        if set(os.listdir(fd)) != set(LIMITES) | {PACOTE}:
            raise ValueError("inventário incompleto ou inesperado na revisão da v0.2")
        return _ler_arquivos(fd, com_pacote=True)


def entregar(registro, raiz: Path, run_id: str, destino: str) -> Path:
    """Publica exatamente os bytes revisados sob a autorização da transação do registro."""
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", run_id):
        raise ValueError("identificador de execução inválido")
    if not isinstance(destino, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", destino):
        raise ValueError("identificador de destino inválido")
    pasta = Path(raiz) / "entregas" / destino / run_id
    with registro.promover(run_id, destino) as manifesto:
        _validar(manifesto)
        _publicar(Path(raiz) / "revisao" / run_id / "resultados", pasta, esperado=manifesto)
    return pasta
