"""Captura e promoção local dos arquivos de resultado após o fim da sandbox."""

import errno
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from contextlib import ExitStack, contextmanager
from pathlib import Path


LIMITES = {"kpis.json": 1024**2, "por_pedido.csv": 32 * 1024**2, "por_viagem.csv": 32 * 1024**2}
DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
# Infra construída na sandbox: modelos SQL e o que o dbt registrou sobre eles. O catalog
# só existe quando `dbt docs generate` funcionou; manifest e run_results vêm do build.
LIMITES_INFRA = {"target/manifest.json": 32 * 1024**2, "target/catalog.json": 32 * 1024**2,
                 "target/run_results.json": 16 * 1024**2}
INFRA_OBRIGATORIA = ("target/manifest.json", "target/run_results.json")
LIMITE_MODELO = 1024**2
MAX_MODELOS = 200
SEGMENTO = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
# Tabelas prata exportadas em Parquet (exportar_prata.py) e a contagem de linhas de cada uma.
CAMINHO_PRATA = re.compile(r"prata/(?:[a-z0-9_]{1,64}\.parquet|linhas\.json)")
LIMITE_PRATA, LIMITE_PRATA_TOTAL = 64 * 1024**2, 256 * 1024**2
CAMINHO_MODELO = re.compile(r"models/(?:[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}/){0,6}[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\.sql")


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


def _copiar(origem, nome, limite, destino=None):
    """Lê (e copia, se houver destino) um arquivo regular exclusivo sem seguir links."""
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
    return {"bytes": tamanho, "sha256": digest.hexdigest()}


def _ler_arquivos(origem, destino=None):
    return {"arquivos": {nome: _copiar(origem, nome, limite, destino) for nome, limite in LIMITES.items()}}


def _arvore(origem, aceitar, destino=None, prefixo="", inventario=None, profundidade=0, *, subpastas=True):
    """Percorre uma árvore por descritores, sem seguir links, e devolve {caminho: {bytes, sha256}}.

    `aceitar(caminho_relativo)` devolve o limite em bytes do arquivo ou levanta ValueError.
    """
    inventario = {} if inventario is None else inventario
    if profundidade > 8:
        raise ValueError("árvore de artefatos profunda demais")
    for nome in sorted(os.listdir(origem)):
        relativo = prefixo + nome
        if not SEGMENTO.fullmatch(nome):
            raise ValueError(f"nome de artefato inválido: {relativo!r}")
        meta = os.stat(nome, dir_fd=origem, follow_symlinks=False)
        if stat.S_ISDIR(meta.st_mode):
            if not subpastas:
                raise ValueError(f"subpasta não permitida: {relativo}")
            with ExitStack() as abertos:
                sub = os.open(nome, DIR, dir_fd=origem)
                abertos.callback(os.close, sub)
                novo = None
                if destino is not None:
                    os.mkdir(nome, mode=0o700, dir_fd=destino)
                    novo = os.open(nome, DIR, dir_fd=destino)
                    abertos.callback(os.close, novo)
                _arvore(sub, aceitar, novo, relativo + "/", inventario, profundidade + 1)
            continue
        inventario[relativo] = _copiar(origem, nome, aceitar(relativo), destino)
    return inventario


def _lote(destino, preencher, *, comparar):
    """Monta um lote num diretório temporário irmão e o publica com um único rename.

    `preencher(fd_do_lote)` copia e devolve o inventário. Se o destino já existe, ele só é
    aceito quando `comparar(fd_existente)` devolve o mesmo inventário (publicação idempotente).
    """
    destino = Path(destino)
    if destino.name in ("", ".", ".."):
        raise ValueError("nome de diretório de artefatos inválido")
    temporario = ".parcial-" + uuid.uuid4().hex
    with _diretorio(destino.parent, criar=True) as pai:
        os.mkdir(temporario, mode=0o700, dir_fd=pai)
        lote = os.open(temporario, DIR, dir_fd=pai)
        publicado = False
        try:
            inventario = preencher(lote)
            os.fsync(lote)
            try:
                os.rename(temporario, destino.name, src_dir_fd=pai, dst_dir_fd=pai)
                publicado = True
                os.fsync(pai)
                return inventario
            except OSError as erro:
                if erro.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                    raise
            existente = os.open(destino.name, DIR, dir_fd=pai)
            try:
                if comparar(existente) != inventario:
                    raise ValueError("o destino já existe com conteúdo divergente")
            finally:
                os.close(existente)
            return inventario
        finally:
            os.close(lote)
            if not publicado:
                shutil.rmtree(temporario, dir_fd=pai)


def _aceitar_modelo(relativo):
    if not CAMINHO_MODELO.fullmatch(relativo):
        raise ValueError(f"models/ só pode conter arquivos .sql: {relativo}")
    return LIMITE_MODELO


def _aceitar_prata(relativo):
    if not CAMINHO_PRATA.fullmatch(relativo):
        raise ValueError(f"prata/ só pode conter <tabela>.parquet e linhas.json: {relativo}")
    return LIMITE_PRATA


def _aceitar_infra(relativo):
    if relativo in LIMITES_INFRA:
        return LIMITES_INFRA[relativo]
    if relativo.startswith("prata/"):
        return _aceitar_prata(relativo)
    return _aceitar_modelo(relativo)


def capturar_infra(models: Path, target: Path, destino: Path, *, prata: Path | None = None) -> dict:
    """Congela os modelos escritos na sandbox, manifest/catalog/run_results do dbt e a prata exportada.

    Roda no host depois de parar o contêiner. Tudo o que vem de lá é tratado como não
    confiável: sem links, só arquivos regulares exclusivos, com teto por arquivo e por lote.
    """
    def preencher(lote):
        inventario = {}
        with _diretorio(models) as src:
            os.mkdir("models", mode=0o700, dir_fd=lote)
            alvo = os.open("models", DIR, dir_fd=lote)
            try:
                _arvore(src, _aceitar_modelo, alvo, "models/", inventario)
            finally:
                os.close(alvo)
        if not inventario:
            raise ValueError("a sandbox não deixou nenhum modelo em models/")
        if len(inventario) > MAX_MODELOS:
            raise ValueError("models/ excede o número de arquivos permitido")
        os.mkdir("target", mode=0o700, dir_fd=lote)
        alvo = os.open("target", DIR, dir_fd=lote)
        try:
            with _diretorio(target) as src:
                presentes = set(os.listdir(src))
                for relativo, limite in LIMITES_INFRA.items():
                    nome = relativo.removeprefix("target/")
                    if nome not in presentes:
                        if relativo in INFRA_OBRIGATORIA:
                            raise ValueError(f"o dbt não produziu {relativo}")
                        continue
                    inventario[relativo] = _copiar(src, nome, limite, alvo)
        finally:
            os.close(alvo)
        if prata is not None:
            os.mkdir("prata", mode=0o700, dir_fd=lote)
            alvo = os.open("prata", DIR, dir_fd=lote)
            try:
                with _diretorio(prata) as src:
                    _arvore(src, _aceitar_prata, alvo, "prata/", inventario, subpastas=False)
            finally:
                os.close(alvo)
            if sum(m["bytes"] for c, m in inventario.items() if c.startswith("prata/")) > LIMITE_PRATA_TOTAL:
                raise ValueError("tabelas prata exportadas acima do limite")
        return inventario

    return _lote(destino, preencher, comparar=lambda fd: _arvore(fd, _aceitar_infra))


def _meta_valida(meta, limite):
    return (isinstance(meta, dict) and set(meta) == {"sha256", "bytes"}
            and type(meta["bytes"]) is int and 0 < meta["bytes"] <= limite
            and isinstance(meta["sha256"], str) and re.fullmatch("[a-f0-9]{64}", meta["sha256"]))


def inventario(pasta: Path, limite: int = 64 * 1024**2) -> dict:
    """{caminho: {bytes, sha256}} de uma árvore, sem seguir links (usado para conferir o pacote)."""
    with _diretorio(pasta) as fd:
        return _arvore(fd, lambda _relativo: limite)


def _validar(manifesto):
    """`arquivos` são os três resultados; `infra` (opcional em runs antigas) os modelos e o target."""
    if not isinstance(manifesto, dict) or set(manifesto) not in ({"arquivos"}, {"arquivos", "infra"}):
        raise ValueError("formato de manifesto inválido")
    itens = manifesto["arquivos"]
    if not isinstance(itens, dict) or set(itens) != set(LIMITES):
        raise ValueError("manifesto deve conter exatamente os três resultados")
    for nome, meta in itens.items():
        if not _meta_valida(meta, LIMITES[nome]):
            raise ValueError(f"tamanho ou hash inválido: {nome}")
    infra = manifesto.get("infra")
    if infra is None:
        return
    if not isinstance(infra, dict) or not set(INFRA_OBRIGATORIA) <= set(infra):
        raise ValueError("infra do manifesto sem manifest ou run_results do dbt")
    modelos = [c for c in infra if c not in LIMITES_INFRA and not str(c).startswith("prata/")]
    if not modelos or len(modelos) > MAX_MODELOS:
        raise ValueError("infra do manifesto sem modelos ou com modelos demais")
    for caminho, meta in infra.items():
        try:
            limite = _aceitar_infra(caminho) if isinstance(caminho, str) else None
        except ValueError:
            limite = None
        if limite is None or not _meta_valida(meta, limite):
            raise ValueError(f"tamanho, hash ou caminho de infra inválido: {caminho!r}")


def _publicar(origem, destino):
    destino = Path(destino)
    if destino.name in ("", ".", ".."):
        raise ValueError("nome de diretório de artefatos inválido")
    temporario = ".parcial-" + uuid.uuid4().hex
    with _diretorio(origem) as src, _diretorio(destino.parent, criar=True) as pai:
        # As saídas extras internas da sandbox nunca são copiadas.
        os.mkdir(temporario, mode=0o700, dir_fd=pai)
        lote = os.open(temporario, DIR, dir_fd=pai)
        publicado = False
        try:
            manifesto = _ler_arquivos(src, lote)
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


LIMITE_PACOTE = 512 * 1024**2


def _conferir_pacote(lote, aprovado):
    """O pacote copiado bate com o próprio manifesto.json e com os bytes da aprovação 2."""
    inventario = _arvore(lote, lambda _relativo: 64 * 1024**2)
    if sum(m["bytes"] for m in inventario.values()) > LIMITE_PACOTE:
        raise ValueError("pacote de entrega acima do limite")
    fd = os.open("manifesto.json", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=lote)
    with os.fdopen(fd, "rb") as arquivo:
        selado = json.loads(arquivo.read(4 * 1024**2 + 1))
    if not isinstance(selado, dict) or selado.get("aprovado") != aprovado:
        raise ValueError("manifesto.json do pacote não corresponde à aprovação 2")
    if {c: m for c, m in inventario.items() if c != "manifesto.json"} != selado.get("arquivos"):
        raise ValueError("pacote difere do próprio manifesto.json")

    def secao(prefixo, novo):
        return {novo + c.removeprefix(prefixo): m for c, m in inventario.items() if c.startswith(prefixo)}

    resultados = {c: m for c, m in secao("dados/", "").items() if not c.startswith("prata/")}
    if resultados != aprovado["arquivos"]:
        raise ValueError("resultados do pacote diferem do manifesto aprovado")
    if "infra" in aprovado:
        infra = secao("projeto_dbt/models/", "models/") | secao("docs_dbt/", "target/") | secao("dados/prata/", "prata/")
        if infra != aprovado["infra"]:
            raise ValueError("modelos ou target do pacote diferem do manifesto aprovado")
    return inventario


def entregar(registro, raiz: Path, run_id: str, destino: str) -> Path:
    """Publica o pacote de entrega (revisao/<run>/entrega) sob a autorização da aprovação 2.

    Dados e infra do pacote têm que ser exatamente os bytes aprovados; o resto (página,
    decisões, projeto) tem que bater com o manifesto.json selado pelo empacotar.
    """
    if not isinstance(run_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", run_id):
        raise ValueError("identificador de execução inválido")
    if not isinstance(destino, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", destino):
        raise ValueError("identificador de destino inválido")
    pasta = Path(raiz) / "entregas" / destino / run_id
    pacote = Path(raiz) / "revisao" / run_id / "entrega"
    with registro.promover(run_id, destino) as aprovado:
        _validar(aprovado)

        def preencher(lote):
            with _diretorio(pacote) as src:
                _arvore(src, lambda _relativo: 64 * 1024**2, lote)
            return _conferir_pacote(lote, aprovado)

        def comparar(existente):
            try:
                return _conferir_pacote(existente, aprovado)
            except (OSError, ValueError):
                raise ValueError("o destino já existe com conteúdo divergente") from None

        _lote(pasta, preencher, comparar=comparar)
    return pasta
