"""Captura e promoção local dos arquivos de resultado após o fim da sandbox."""

import errno
import hashlib
import os
import re
import stat
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path


LIMITES = {"kpis.json": 1024**2, "por_pedido.csv": 32 * 1024**2, "por_viagem.csv": 32 * 1024**2}
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


def _ler_arquivos(origem, destino=None):
    arquivos = {}
    for nome, limite in LIMITES.items():
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
    if not isinstance(itens, dict) or set(itens) != set(LIMITES):
        raise ValueError("manifesto deve conter exatamente os três resultados")
    for nome, meta in itens.items():
        if (not isinstance(meta, dict) or set(meta) != {"sha256", "bytes"}
                or type(meta["bytes"]) is not int or not 0 < meta["bytes"] <= LIMITES[nome]
                or not isinstance(meta["sha256"], str) or not re.fullmatch("[a-f0-9]{64}", meta["sha256"])):
            raise ValueError(f"tamanho ou hash inválido: {nome}")


def _publicar(origem, destino, *, esperado=None):
    destino = Path(destino)
    if destino.name in ("", ".", ".."):
        raise ValueError("nome de diretório de artefatos inválido")
    temporario = ".parcial-" + uuid.uuid4().hex
    with _diretorio(origem) as src, _diretorio(destino.parent, criar=True) as pai:
        # As saídas extras internas da sandbox nunca são copiadas. Em revisão, só os
        # três artefatos congelados são aceitos para a segunda aprovação.
        if esperado is not None and set(os.listdir(src)) != set(LIMITES):
            raise ValueError("a lista de resultados para promoção mudou")
        os.mkdir(temporario, mode=0o700, dir_fd=pai)
        lote = os.open(temporario, DIR, dir_fd=pai)
        publicado = False
        try:
            manifesto = _ler_arquivos(src, lote)
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
                if set(os.listdir(existente)) != set(LIMITES) or _ler_arquivos(existente) != manifesto:
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
