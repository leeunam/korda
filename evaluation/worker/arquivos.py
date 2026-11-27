"""Leitura limitada de arquivos fixos de avaliação. Apenas Linux."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def _abrir_diretorio(pasta):
    # Percorre componentes por descritores. O produtor controla os nomes dentro de saida/.
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_RDONLY
    caminho = Path(pasta).absolute()
    if ".." in caminho.parts:
        raise ValueError("caminho contém componente de retorno")
    fd = os.open("/", flags)
    try:
        for componente in caminho.parts[1:]:
            proximo = os.open(componente, flags, dir_fd=fd)
            os.close(fd)
            fd = proximo
        yield fd
    finally:
        os.close(fd)


def _ler_arquivo(fd, nome, limite=8 * 1024 * 1024):
    opcoes = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(nome, opcoes, dir_fd=fd), "rb") as arquivo:
        info = os.fstat(arquivo.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limite:
            raise ValueError(f"{nome}: exige arquivo regular, de vínculo único e até {limite} bytes")
        dados = arquivo.read(limite + 1)
        if len(dados) > limite:
            raise ValueError(f"{nome}: arquivo acima do limite")
        return dados


def _sem_repeticao(pares):
    valores = {}
    for chave, valor in pares:
        if chave in valores:
            raise ValueError("JSON contém chave duplicada")
        valores[chave] = valor
    return valores
