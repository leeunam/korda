import importlib.util
import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from korda_execution.eventos import EmissorEventos
from korda_execution.ferramentas import FONTES, FerramentasRestritas
from korda_execution.sandbox import ErroSandbox, LocalDockerSandbox, ResultadoComando, docker_disponivel, imagem_existe


ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("korda_perfil", ROOT / "infra/sandbox/perfil.py")
perfil = importlib.util.module_from_spec(spec)
spec.loader.exec_module(perfil)


class TestFerramentas(unittest.TestCase):
    def setUp(self):
        temporario = tempfile.TemporaryDirectory()
        self.addCleanup(temporario.cleanup)
        self.eventos = EmissorEventos(Path(temporario.name) / "eventos.jsonl", "teste")
        self.sandbox = Mock()

    def test_plano_e_escopo_de_escrita_sao_fixados_pelo_coordenador(self):
        caminho = "models/prata/pedidos.sql"
        plano = {"plan_version": 4, "etapas": [{"modelo": caminho}]}
        ferramentas = FerramentasRestritas(
            self.sandbox, self.eventos, plano_aprovado=plano, modelos_permitidos=frozenset([caminho])
        )
        plano["etapas"].clear()
        leitura = ferramentas.ler_plano()
        self.assertEqual(leitura["plano"]["etapas"], [{"modelo": caminho}])
        leitura["plano"]["etapas"].clear()
        self.assertEqual(len(ferramentas.ler_plano()["plano"]["etapas"]), 1)
        self.assertFalse(ferramentas.escrever_modelo("models/outro.sql", "select 1")["ok"])
        self.assertTrue(ferramentas.escrever_modelo(caminho, "select 1")["ok"])
        self.sandbox.enviar_arquivos.assert_called_once_with({f"/work/projeto/{caminho}": b"select 1"})
        self.assertEqual(self.eventos.ler()[-1]["type"], "file_written")

    def test_padrao_do_plano_autoriza_qualquer_sql_em_models(self):
        ferramentas = FerramentasRestritas(self.sandbox, self.eventos, plano_aprovado={"plan_version": 1},
                                           modelos_permitidos=frozenset(["models/*"]))
        self.assertTrue(ferramentas.escrever_modelo("models/ouro_kpis.sql", "select 1")["ok"])
        self.assertFalse(ferramentas.escrever_modelo("tests/chave_fiscal_unica.sql", "select 1")["ok"])
        self.assertFalse(ferramentas.escrever_modelo("models/fontes.yml", "x")["ok"])
        self.sandbox.enviar_arquivos.assert_called_once_with({"/work/projeto/models/ouro_kpis.sql": b"select 1"})

    def test_sem_plano_e_sem_modelos_autorizados(self):
        self.assertFalse(FerramentasRestritas(self.sandbox, self.eventos).ler_plano()["ok"])
        ferramentas = FerramentasRestritas(self.sandbox, self.eventos, plano_aprovado={"version": 1})
        self.assertFalse(ferramentas.escrever_modelo("models/x.sql", "select 1")["ok"])
        self.sandbox.enviar_arquivos.assert_not_called()

    def test_perfil_e_consulta_recusam_saida_incompleta(self):
        ferramentas = FerramentasRestritas(self.sandbox, self.eventos)
        self.assertFalse(ferramentas.inspecionar_fonte("_gerador")["ok"])
        self.sandbox.rodar_comando.assert_not_called()
        self.sandbox.rodar_comando.return_value = ResultadoComando(0, "[... truncado ...]", "", 0.1, False)
        self.assertFalse(ferramentas.inspecionar_fonte("cte")["ok"])
        self.assertFalse(ferramentas.consultar_sql("select 1")["ok"])
        corpo = {"fonte": "erp_pedidos", "formato": "csv", "colunas": ["pedido"]}
        self.sandbox.rodar_comando.return_value = ResultadoComando(0, json.dumps(corpo), "", 0.1, False)
        self.assertEqual(ferramentas.inspecionar_fonte("erp_pedidos")["perfil"], corpo)
        self.sandbox.rodar_comando.assert_called_with(["python", "/opt/korda/perfil.py", "erp_pedidos"],
                                                     timeout_s=30)


class TestPerfil(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.raiz = Path(tmp.name).resolve()

    def test_csv_limita_registros_cobre_dialetos_e_nao_devolve_valores(self):
        pasta = self.raiz / "tms"
        pasta.mkdir()
        self.assertEqual(set(perfil.CSV) | {"cte"}, FONTES)
        for separador in (";", ",", "|"):
            with self.subTest(separador=separador):
                (pasta / "tms_viagens.csv").write_text(
                    f"viagem{separador}trecho\n" + f"123{separador}\n" * 100 + f"456{separador}CONFIDENCIAL\n"
                )
                resultado = perfil.inspecionar(self.raiz, "tms_viagens")
                self.assertEqual(resultado["separador"], separador)
                self.assertEqual(resultado["nulos_na_amostra"], {"viagem": 0, "trecho": 100})
                self.assertEqual(resultado["registros_analisados"], 100)
                self.assertTrue(resultado["amostra_parcial"])
                self.assertNotIn("CONFIDENCIAL", json.dumps(resultado))
        (pasta / "tms_viagens.csv").unlink()
        (self.raiz / "privado").write_text("fora da origem")
        (pasta / "tms_viagens.csv").symlink_to(self.raiz / "privado")
        with self.assertRaises(ValueError):
            perfil.inspecionar(self.raiz, "tms_viagens")

    def test_xml_distingue_tipos_sem_incluir_arquivos_fora_do_catalogo(self):
        pasta = self.raiz / "cte"
        pasta.mkdir()
        for nome, tipo in [("cte", "cteProc"), ("canc-110111", "procEventoCTe")]:
            (pasta / f"{'0' * 44}-{nome}.xml").write_text(f'<{tipo} xmlns="{perfil.NS_CTE}" />')
        (pasta / "anotacoes.xml").write_text("fora das exportações fiscais")
        resultado = perfil.inspecionar(self.raiz, "cte")
        self.assertEqual(resultado["arquivos_elegiveis"], 2)
        self.assertEqual(resultado["tipos_na_amostra"], {"cteProc": 1, "procEventoCTe": 1})
        self.assertFalse(resultado["amostra_parcial"])
        with self.assertRaises(ValueError):
            perfil.inspecionar(self.raiz, "../_gerador")


class TestPropriedadeDaExecucao(unittest.TestCase):
    def test_construcao_monta_apenas_os_cinco_sql_vazios_do_plano(self):
        permitidos = ("models/prata_ctes.sql", "models/prata_rateios.sql", "models/ouro_por_pedido.sql",
                      "models/ouro_por_viagem.sql", "models/ouro_kpis.sql")
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            projeto = raiz / "projeto"
            (projeto / "models").mkdir(parents=True)
            (projeto / "dbt_project.yml").write_text("name: teste")
            (projeto / permitidos[0]).write_text("select 17")
            (projeto / "models/outro.sql").write_text("select 18")
            sb = LocalDockerSandbox("construcao", projeto, raiz, raiz_runs=raiz / "runs",
                                    modelos_permitidos=permitidos, modelos_vazios=True, exigir_manifesto=False)
            with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
                 patch("korda_execution.sandbox.os.getuid", return_value=1000), \
                 patch("korda_execution.sandbox.subprocess.run") as docker:
                docker.return_value.returncode = 0
                docker.return_value.stdout = "a" * 64
                sb.criar()
                argv = docker.call_args.args[0]
                gravaveis = [argv[i + 1].split("dst=")[1] for i, arg in enumerate(argv)
                             if arg == "--mount" and "readonly" not in argv[i + 1]]
                self.assertCountEqual(gravaveis, ["/work/saida", *("/work/projeto/" + p for p in permitidos)])
                copia = sb.dir_run / "projeto"
                self.assertEqual({str(p.relative_to(copia)): p.read_bytes() for p in (copia / "models").iterdir()},
                                 dict.fromkeys(permitidos, b""))
                sb.destruir()

    def test_glob_publica_novo_sql_em_models_vazio_com_o_projeto_somente_leitura(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            projeto = raiz / "projeto"
            modelos = projeto / "models"
            (modelos / "sub").mkdir(parents=True)
            (projeto / "tests").mkdir()
            (projeto / "dbt_project.yml").write_text("name: teste")
            (projeto / "tests" / "aceite.sql").write_text("select 1 where false")
            (modelos / "feito_a_mao.sql").write_text("select 7")
            (modelos / "sub" / "outro.sql").write_text("select 9")
            for padrao in ("tests/*", "models/**", "models/x.yml"):
                with self.assertRaises(ErroSandbox):
                    LocalDockerSandbox("restrita", projeto, raiz, modelos_permitidos=(padrao,))
            sb = LocalDockerSandbox("restrita", projeto, raiz, raiz_runs=raiz/"runs",
                                    modelos_permitidos=("models/*",), exigir_manifesto=False)
            with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
                 patch("korda_execution.sandbox.os.getuid", return_value=1000), \
                 patch("korda_execution.sandbox.subprocess.run") as docker:
                docker.return_value.returncode = 0
                docker.return_value.stdout = "a" * 64
                sb.criar()
                argv = docker.call_args.args[0]
                montagens = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--mount"]
                gravaveis = [arg.split("dst=")[1] for arg in montagens if "readonly" not in arg]
                self.assertEqual(gravaveis, ["/work/saida"])
                self.assertTrue(any(arg.endswith("dst=/work/projeto,readonly") for arg in montagens))
                self.assertEqual(list((sb.dir_run / "projeto/models").iterdir()), [])
                self.assertTrue((sb.dir_run / "projeto/tests/aceite.sql").is_file())
                sb.enviar_arquivos({"/work/projeto/models/sub/novo.sql": b"select 3"})
                self.assertEqual((sb.dir_run / "projeto/models/sub/novo.sql").read_bytes(), b"select 3")
                with self.assertRaises(ErroSandbox):
                    sb.enviar_arquivos({"/work/projeto/models/config.yml": b"fora do plano"})
                sb.destruir()

    def test_modelo_exato_do_plano_historico_preserva_os_demais_como_leitura(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            projeto = raiz / "projeto"
            modelos = projeto / "models"
            modelos.mkdir(parents=True)
            (projeto / "dbt_project.yml").write_text("name: teste")
            (modelos / "aprovado.sql").write_text("select 7")
            (modelos / "protegido.sql").write_text("select 9")
            (modelos / "indireto.sql").symlink_to(modelos / "protegido.sql")
            for nome in ("models/indireto.sql", "models/ausente.sql"):
                with self.assertRaises(ErroSandbox):
                    LocalDockerSandbox("restrita", projeto, raiz, modelos_permitidos=(nome,))
            sb = LocalDockerSandbox("historica", projeto, raiz, raiz_runs=raiz / "runs",
                                    modelos_permitidos=("models/aprovado.sql",), exigir_manifesto=False)
            with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
                 patch("korda_execution.sandbox.os.getuid", return_value=1000), \
                 patch("korda_execution.sandbox.subprocess.run") as docker:
                docker.return_value.returncode = 0
                docker.return_value.stdout = "a" * 64
                sb.criar()
                argv = docker.call_args.args[0]
                gravaveis = [argv[i+1].split("dst=")[1] for i, arg in enumerate(argv)
                              if arg == "--mount" and "readonly" not in argv[i+1]]
                self.assertCountEqual(gravaveis, ["/work/saida", "/work/projeto/models/aprovado.sql"])
                self.assertEqual((sb.dir_run / "projeto/models/aprovado.sql").read_text(), "select 7")
                self.assertEqual((sb.dir_run / "projeto/models/protegido.sql").read_text(), "select 9")
                with self.assertRaises(ErroSandbox):
                    sb.enviar_arquivos({"/work/projeto/models/protegido.sql": b"select 4"})
                sb.destruir()

    def test_duas_instancias_com_mesmo_id_preservam_o_dono(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            (raiz / "dbt_project.yml").write_text("name: teste\n")
            runs = raiz / "runs"
            primeira = LocalDockerSandbox("mesmo", raiz, raiz, raiz_runs=runs, exigir_manifesto=False)
            segunda = LocalDockerSandbox("mesmo", raiz, raiz, raiz_runs=runs, exigir_manifesto=False)
            with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
                 patch("korda_execution.sandbox.os.getuid", return_value=1000), \
                 patch.object(primeira, "_iniciar"), patch("korda_execution.sandbox.subprocess.run") as docker:
                primeira.criar()
                with self.assertRaises(ErroSandbox):
                    segunda.criar()
                segunda.destruir()
                self.assertTrue(primeira.dir_run.is_dir())
                docker.assert_not_called()
                primeira.destruir(apagar_diretorio=False)
                self.assertTrue(primeira.dir_run.is_dir())
                primeira.destruir()
                self.assertFalse(primeira.dir_run.exists())

    def test_preparacao_interrompida_libera_somente_a_reserva_da_instancia(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            (raiz / "dbt_project.yml").write_text("name: teste\n")
            sb = LocalDockerSandbox("parcial", raiz, raiz, raiz_runs=raiz / "runs", exigir_manifesto=False)
            with patch("korda_execution.sandbox.imagem_existe", return_value=True), \
                 patch("korda_execution.sandbox.os.getuid", return_value=1000), \
                 patch.object(sb, "_iniciar", side_effect=OSError("falha durante preparação")):
                with self.assertRaises(OSError):
                    sb.criar()
                self.assertFalse(sb.dir_run.exists())


@unittest.skipUnless(docker_disponivel() and imagem_existe(), "Docker ou imagem da sandbox indisponível")
class TestFerramentasNaSandbox(unittest.TestCase):
    def test_perfil_e_consulta_passam_pela_imagem_do_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            raiz = Path(temp)
            fontes = raiz / "fontes"
            (fontes / "erp").mkdir(parents=True)
            (fontes / "erp/erp_pedidos.csv").write_text("pedido;peso\n1;\n2;17\n")
            projeto = raiz / "projeto"
            shutil.copytree(ROOT / "services/execution/tests/fixtures/projeto_minimo", projeto)
            (projeto / "models/aprovado.sql").write_text("select 1")
            (projeto / "models/protegido.sql").write_text("select 2")
            run_id = f"ferramentas-{uuid.uuid4().hex[:12]}"
            with LocalDockerSandbox(run_id, projeto, fontes, raiz_runs=raiz / "runs",
                                    modelos_permitidos=("models/aprovado.sql",), exigir_manifesto=False) as sb:
                ferramentas = FerramentasRestritas(sb, EmissorEventos(raiz / "eventos.jsonl", run_id),
                                                   modelos_permitidos=frozenset(["models/aprovado.sql"]))
                self.assertEqual((sb.dir_run / "projeto/models/aprovado.sql").read_text(), "select 1")
                self.assertEqual((sb.dir_run / "projeto/models/protegido.sql").read_text(), "select 2")
                self.assertFalse(sb.rodar_comando(["test", "-w", "/work/projeto/models/protegido.sql"]).ok)
                sb.enviar_arquivos({"/work/projeto/models/aprovado.sql": b"select 3"})
                with self.assertRaises(ErroSandbox):
                    sb.enviar_arquivos({"/work/projeto/tests/novo.sql": b"select 4"})
                self.assertEqual((projeto / "models/aprovado.sql").read_text(), "select 1")
                self.assertFalse(ferramentas.escrever_modelo("models/protegido.sql", "select 4")["ok"])
                perfil_csv = ferramentas.inspecionar_fonte("erp_pedidos")
                self.assertTrue(perfil_csv["ok"], perfil_csv)
                self.assertEqual(perfil_csv["perfil"]["nulos_na_amostra"], {"pedido": 0, "peso": 1})
                criar = sb.rodar_comando(["python", "-c", "import duckdb; duckdb.connect('/work/saida/korda.duckdb').close()"])
                self.assertTrue(criar.ok, criar.stderr)
                consulta = ferramentas.consultar_sql("with dado as (select 7 as n) select n from dado")
                self.assertTrue(consulta["ok"], consulta)
                self.assertEqual(consulta["linhas"], [[7]])
                self.assertFalse(ferramentas.consultar_sql("select 1; select 2")["ok"])


if __name__ == "__main__":
    unittest.main()
