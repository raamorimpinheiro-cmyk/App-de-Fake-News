import os
import json
import threading
import difflib
from datetime import datetime
from urllib.parse import urlparse, unquote

from dotenv import load_dotenv

# Carrega o .env da pasta do projeto ANTES de importar o modelo
PASTA_PROJETO = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(PASTA_PROJETO, ".env"))

try:
    from modelo import verificar_noticia, verificar_imagem, status_configuracao
    ERRO_MODELO = status_configuracao()
except Exception as e:
    verificar_noticia = verificar_imagem = None
    ERRO_MODELO = f"Não foi possível carregar o módulo do ChatGPT:\n{e}"

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.progressbar import ProgressBar
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.clock import Clock
from kivy.graphics import Color, RoundedRectangle

try:
    import requests
    from bs4 import BeautifulSoup
    WEB_OK = True
except ImportError:
    WEB_OK = False

ARQUIVO_HISTORICO = os.path.join(PASTA_PROJETO, "historico.json")

EXTENSOES_IMAGEM = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp"
)

FILTROS_IMAGEM = [
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.webp"
]

TEMAS = {
    "claro": {
        "fundo": (0.95, 0.97, 1, 1),
        "texto": (0.15, 0.15, 0.20, 1),
        "texto_sec": (0.25, 0.25, 0.30, 1),
        "input_bg": (1, 1, 1, 1),
        "input_fg": (0.10, 0.10, 0.10, 1),
        "azul": (0.10, 0.35, 0.75, 1),
        "roxo": (0.40, 0.25, 0.75, 1),
        "verde": (0.20, 0.60, 0.40, 1),
        "laranja": (0.80, 0.40, 0.10, 1),
        "card": (0.88, 0.92, 0.98, 1),
        "cinza": (0.45, 0.45, 0.45, 1),
        "vermelho": (0.75, 0.20, 0.20, 1),
    },
    "escuro": {
        "fundo": (0.10, 0.11, 0.15, 1),
        "texto": (0.95, 0.95, 1.00, 1),
        "texto_sec": (0.72, 0.75, 0.82, 1),
        "input_bg": (0.18, 0.20, 0.26, 1),
        "input_fg": (0.95, 0.95, 1.00, 1),
        "azul": (0.30, 0.55, 0.95, 1),
        "roxo": (0.55, 0.40, 0.90, 1),
        "verde": (0.30, 0.70, 0.50, 1),
        "laranja": (0.95, 0.60, 0.25, 1),
        "card": (0.16, 0.18, 0.24, 1),
        "cinza": (0.60, 0.60, 0.60, 1),
        "vermelho": (0.90, 0.30, 0.30, 1),
    },
}


class FakeNewsApp(App):

    # ============================================================
    # INICIALIZAÇÃO
    # ============================================================
    def build(self):
        self.title = "Detector de Fake News"
        self.tema_escuro = False
        self.cores = TEMAS["claro"]
        self.tela_atual = "fake_news"

        self.lista_imagens = []
        self.caminho_imagem = None

        self._drop_em_andamento = False
        self._arquivos_drop = []

        # Barra de progresso global (reaproveitada em todas as telas)
        self.progresso = ProgressBar(max=100, value=0, size_hint_y=None, height=6)
        self.progresso.opacity = 0
        self._prog_event = None
        self._tarefas_ativas = 0

        Window.clearcolor = self.cores["fundo"]

        self.tela_principal = BoxLayout(
            orientation="vertical",
            padding=20,
            spacing=10
        )

        self._configurar_drag_drop()

        self.mostrar_fake_news()

        return self.tela_principal

    def _ia_disponivel(self, label):
        """Mostra o erro de configuração do ChatGPT no label, se houver."""
        if ERRO_MODELO or verificar_noticia is None:
            label.text = ERRO_MODELO or "Módulo do ChatGPT indisponível."
            label.color = self.cores["vermelho"]
            return False
        return True

    # ============================================================
    # TEMA (Modo claro / escuro)
    # ============================================================
    def alternar_tema(self, *args):
        # Guarda textos digitados e resultados antes de reconstruir a tela
        guardado = {}
        for nome in ("noticia", "texto_ia", "texto_a", "texto_b", "url_input",
                     "resultado", "resultado_ia", "resultado_imagem",
                     "resultado_comp"):
            widget = getattr(self, nome, None)
            if widget is not None and widget.get_root_window() is not None:
                guardado[nome] = widget.text

        self.tema_escuro = not self.tema_escuro
        self.cores = TEMAS["escuro" if self.tema_escuro else "claro"]
        Window.clearcolor = self.cores["fundo"]

        # Reconstrói a tela atual
        if self.tela_atual == "fake_news":
            self.mostrar_fake_news()
        elif self.tela_atual == "ia":
            self.mostrar_detector_ia()
        elif self.tela_atual == "imagem":
            self.mostrar_detector_imagem()
        elif self.tela_atual == "comparacao":
            self.mostrar_comparacao()
        elif self.tela_atual == "historico":
            self.mostrar_historico()

        # Restaura textos
        for nome, valor in guardado.items():
            if hasattr(self, nome):
                getattr(self, nome).text = valor

    def _botao_tema(self):
        c = self.cores
        bt = Button(
            text="Modo Claro" if self.tema_escuro else "Modo Escuro",
            font_size=13,
            bold=True,
            size_hint=(None, None),
            size=(130, 36),
            background_normal="",
            background_color=c["card"],
            color=c["texto"]
        )
        bt.bind(on_press=self.alternar_tema)
        return bt

    def _barra_topo(self, com_voltar=False):
        c = self.cores
        barra = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=40
        )
        if com_voltar:
            bt_voltar = Button(
                text="Voltar",
                font_size=14,
                bold=True,
                size_hint=(None, None),
                size=(100, 40),
                background_normal="",
                background_color=c["azul"],
                color=(1, 1, 1, 1)
            )
            bt_voltar.bind(on_press=lambda i: self.mostrar_fake_news())
            barra.add_widget(bt_voltar)
        barra.add_widget(Label())
        barra.add_widget(self._botao_tema())
        return barra

    # ============================================================
    # NAVEGAÇÃO
    # ============================================================
    def _barra_navegacao(self, atual=""):
        c = self.cores
        grid = GridLayout(cols=4, size_hint_y=None, height=48, spacing=8)

        def criar(texto, cor_key, destino, ativo):
            bt = Button(
                text=texto,
                font_size=13,
                bold=True,
                background_normal="",
                background_color=c["cinza"] if ativo else c[cor_key],
                color=(1, 1, 1, 1)
            )
            if not ativo:
                bt.bind(on_press=lambda i: destino())
            return bt

        grid.add_widget(criar("Detector IA", "roxo",
                              self.mostrar_detector_ia, atual == "ia"))
        grid.add_widget(criar("Imagem", "verde",
                              self.mostrar_detector_imagem, atual == "imagem"))
        grid.add_widget(criar("Comparar", "azul",
                              self.mostrar_comparacao, atual == "comparacao"))
        grid.add_widget(criar("Histórico", "laranja",
                              self.mostrar_historico, atual == "historico"))
        return grid

    # ============================================================
    # HELPERS GERAIS
    # ============================================================
    def _area_resultado(self, texto, font_size):
        """
        Cria um Label de resultado dentro de um ScrollView, para que
        textos longos (explicações, análise em lote) não fiquem cortados.
        Retorna (scroll, label).
        """
        scroll = ScrollView(do_scroll_x=False, bar_width=6)
        label = Label(
            text=texto,
            font_size=font_size,
            bold=True,
            color=self.cores["texto"],
            halign="center",
            valign="middle",
            size_hint_y=None,
            padding=(6, 6)
        )

        def ajustar(*_):
            label.text_size = (max(scroll.width - 16, 50), None)
            label.height = max(label.texture_size[1], scroll.height)
            label.text_size = (max(scroll.width - 16, 50), label.height)

        scroll.bind(size=ajustar)
        label.bind(text=lambda *_: Clock.schedule_once(ajustar, 0))
        scroll.add_widget(label)
        Clock.schedule_once(ajustar, 0)
        return scroll, label

    def _copiar(self, botao, texto):
        try:
            Clipboard.copy(texto or "")
            original = botao.text
            botao.text = "Copiado!"
            Clock.schedule_once(lambda dt: setattr(botao, "text", original), 1.5)
        except Exception as e:
            print("Erro ao copiar:", e)

    def _botao_copiar(self):
        c = self.cores
        bt = Button(
            text="Copiar resultado",
            font_size=13,
            bold=True,
            size_hint=(None, None),
            size=(160, 34),
            background_normal="",
            background_color=c["card"],
            color=c["texto"]
        )
        bt.bind(on_press=lambda i: self._copiar(i, self._texto_resultado_atual()))
        linha = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=36
        )
        linha.add_widget(Label())
        linha.add_widget(bt)
        return linha

    def _texto_resultado_atual(self):
        nomes = {
            "fake_news": "resultado",
            "ia": "resultado_ia",
            "imagem": "resultado_imagem",
            "comparacao": "resultado_comp",
        }
        widget = getattr(self, nomes.get(self.tela_atual, ""), None)
        return widget.text if widget is not None else ""

    # ============================================================
    # BARRA DE PROGRESSO ANIMADA
    # ============================================================
    def _iniciar_progresso(self):
        self._tarefas_ativas += 1
        if self._prog_event:
            Clock.unschedule(self._prog_event)
            self._prog_event = None
        self.progresso.value = 0
        self.progresso.opacity = 1
        self._prog_event = Clock.schedule_interval(self._animar_progresso, 0.08)

    def _animar_progresso(self, dt):
        if self.progresso.value < 90:
            self.progresso.value += 1.5
        return True

    def _parar_progresso(self):
        self._tarefas_ativas = max(0, self._tarefas_ativas - 1)
        if self._tarefas_ativas:
            return
        if self._prog_event:
            Clock.unschedule(self._prog_event)
            self._prog_event = None
        self.progresso.value = 100
        Clock.schedule_once(self._esconder_progresso, 0.4)

    def _esconder_progresso(self, dt):
        if not self._tarefas_ativas:
            self.progresso.opacity = 0

    # ============================================================
    # THREAD HELPER
    # ============================================================
    def _executar_em_thread(self, tarefa, ao_terminar, ao_erro):
        """Roda `tarefa` em segundo plano e devolve para a thread da UI."""
        def trabalho():
            try:
                resultado = tarefa()
                Clock.schedule_once(lambda dt: ao_terminar(resultado), 0)
            except Exception as e:
                Clock.schedule_once(lambda dt, err=e: ao_erro(err), 0)
        threading.Thread(target=trabalho, daemon=True).start()

    # ============================================================
    # HISTÓRICO (JSON)
    # ============================================================
    def _carregar_historico(self):
        if not os.path.exists(ARQUIVO_HISTORICO):
            return []
        try:
            with open(ARQUIVO_HISTORICO, "r", encoding="utf-8") as f:
                dados = json.load(f)
            return dados if isinstance(dados, list) else []
        except Exception:
            return []

    def _adicionar_historico(self, tipo, entrada, resultado, extra=""):
        historico = self._carregar_historico()
        historico.insert(0, {
            "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "tipo": tipo,
            "entrada": (entrada or "")[:200],
            "resultado": (resultado or "")[:300],
            "extra": extra,
        })
        # Limita a 100 entradas
        historico = historico[:100]
        try:
            with open(ARQUIVO_HISTORICO, "w", encoding="utf-8") as f:
                json.dump(historico, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Erro ao salvar histórico:", e)

    def _limpar_historico(self, *args):
        try:
            if os.path.exists(ARQUIVO_HISTORICO):
                os.remove(ARQUIVO_HISTORICO)
        except Exception as e:
            print("Erro ao limpar histórico:", e)
        self.mostrar_historico()

    def mostrar_historico(self):
        self.tela_atual = "historico"
        self.tela_principal.clear_widgets()
        c = self.cores

        titulo = Label(
            text="Histórico de Análises",
            font_size=26,
            bold=True,
            color=c["laranja"],
            size_hint_y=None,
            height=50
        )

        subtitulo = Label(
            text="Últimas análises realizadas neste dispositivo",
            font_size=13,
            color=c["texto_sec"],
            size_hint_y=None,
            height=28
        )

        self.tela_principal.add_widget(self._barra_topo())
        self.tela_principal.add_widget(titulo)
        self.tela_principal.add_widget(subtitulo)

        scroll = ScrollView()
        conteudo = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=6,
            padding=5
        )
        conteudo.bind(minimum_height=conteudo.setter("height"))

        historico = self._carregar_historico()

        if not historico:
            conteudo.add_widget(Label(
                text="Nenhuma análise registrada ainda.",
                font_size=14,
                color=c["texto_sec"],
                size_hint_y=None,
                height=60
            ))
        else:
            for item in historico:
                bloco = BoxLayout(
                    orientation="vertical",
                    size_hint_y=None,
                    height=125,
                    padding=8,
                    spacing=2
                )
                with bloco.canvas.before:
                    Color(*c["card"])
                    bg = RoundedRectangle(pos=bloco.pos, size=bloco.size,
                                          radius=[8])
                bloco.bind(
                    pos=lambda w, v, r=bg: setattr(r, "pos", v),
                    size=lambda w, v, r=bg: setattr(r, "size", v)
                )

                extra = item.get("extra", "")
                cab = Label(
                    text=f"[{item.get('data', '')}]  {item.get('tipo', '')}"
                         + (f"  —  {extra}" if extra else ""),
                    font_size=13,
                    bold=True,
                    color=c["laranja"],
                    size_hint_y=None,
                    height=22,
                    halign="left",
                    valign="middle",
                    shorten=True
                )
                cab.bind(size=lambda i, v: setattr(i, "text_size", v))

                ent = Label(
                    text=f"Entrada: {item.get('entrada', '')}",
                    font_size=11,
                    color=c["texto_sec"],
                    size_hint_y=None,
                    height=36,
                    halign="left",
                    valign="top",
                    shorten=True
                )
                ent.bind(size=lambda i, v: setattr(i, "text_size", v))

                res = Label(
                    text=f"Resultado: {item.get('resultado', '')}",
                    font_size=11,
                    color=c["texto"],
                    size_hint_y=None,
                    height=40,
                    halign="left",
                    valign="top",
                    shorten=True
                )
                res.bind(size=lambda i, v: setattr(i, "text_size", v))

                bloco.add_widget(cab)
                bloco.add_widget(ent)
                bloco.add_widget(res)
                conteudo.add_widget(bloco)

        scroll.add_widget(conteudo)
        self.tela_principal.add_widget(scroll)

        botoes = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=48,
            spacing=10
        )

        bt_limpar = Button(
            text="Limpar Histórico",
            font_size=14,
            bold=True,
            background_normal="",
            background_color=c["vermelho"],
            color=(1, 1, 1, 1)
        )
        bt_limpar.bind(on_press=self._limpar_historico)

        bt_voltar = Button(
            text="Voltar",
            font_size=14,
            bold=True,
            background_normal="",
            background_color=c["azul"],
            color=(1, 1, 1, 1)
        )
        bt_voltar.bind(on_press=lambda i: self.mostrar_fake_news())

        botoes.add_widget(bt_limpar)
        botoes.add_widget(bt_voltar)

        self.tela_principal.add_widget(botoes)
        self.tela_principal.add_widget(self.progresso)
        self.tela_principal.add_widget(self._barra_navegacao(atual="historico"))

    # ============================================================
    # TELA PRINCIPAL — FAKE NEWS
    # ============================================================
    def mostrar_fake_news(self):
        self.tela_atual = "fake_news"
        self.tela_principal.clear_widgets()
        c = self.cores

        titulo = Label(
            text="Detector de Fake News",
            font_size=28,
            bold=True,
            color=c["azul"],
            size_hint_y=None,
            height=55
        )

        subtitulo = Label(
            text="Cole uma notícia ou um link para analisar",
            font_size=15,
            color=c["texto_sec"],
            size_hint_y=None,
            height=28
        )

        # --- Linha de URL ---
        linha_url = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=44,
            spacing=8
        )

        self.url_input = TextInput(
            hint_text="Ou cole aqui um link (https://...)",
            multiline=False,
            font_size=14,
            padding=[10, 10],
            background_color=c["input_bg"],
            foreground_color=c["input_fg"],
            cursor_color=c["azul"]
        )
        self.url_input.bind(on_text_validate=self.buscar_url)

        bt_url = Button(
            text="Buscar Link",
            font_size=13,
            bold=True,
            size_hint=(None, None),
            size=(120, 44),
            background_normal="",
            background_color=c["laranja"],
            color=(1, 1, 1, 1)
        )
        bt_url.bind(on_press=self.buscar_url)

        linha_url.add_widget(self.url_input)
        linha_url.add_widget(bt_url)

        instrucao = Label(
            text="Ou cole/escreva a notícia abaixo:",
            font_size=14,
            bold=True,
            color=c["texto"],
            size_hint_y=None,
            height=26
        )

        self.noticia = TextInput(
            hint_text="Digite ou cole a notícia aqui...",
            multiline=True,
            font_size=15,
            padding=[15, 15],
            background_color=c["input_bg"],
            foreground_color=c["input_fg"],
            cursor_color=c["azul"]
        )

        botao = Button(
            text="VERIFICAR NOTÍCIA",
            font_size=18,
            bold=True,
            size_hint_y=None,
            height=55,
            background_normal="",
            background_color=c["azul"],
            color=(1, 1, 1, 1)
        )
        botao.bind(on_press=self.verificar)

        area, self.resultado = self._area_resultado(
            "O resultado aparecerá aqui", 16
        )
        # Avisa logo de cara se a chave da OpenAI não estiver configurada
        self._ia_disponivel(self.resultado)

        self.tela_principal.add_widget(self._barra_topo())
        self.tela_principal.add_widget(titulo)
        self.tela_principal.add_widget(subtitulo)
        self.tela_principal.add_widget(linha_url)
        self.tela_principal.add_widget(instrucao)
        self.tela_principal.add_widget(self.noticia)
        self.tela_principal.add_widget(botao)
        self.tela_principal.add_widget(area)
        self.tela_principal.add_widget(self._botao_copiar())
        self.tela_principal.add_widget(self.progresso)
        self.tela_principal.add_widget(self._barra_navegacao(atual=""))

    def _cor_veredito(self, veredito):
        if "FALSA" in veredito:
            return self.cores["vermelho"]
        if "VERDADEIRA" in veredito:
            return self.cores["verde"]
        return self.cores["laranja"]

    def verificar(self, instance):
        texto = self.noticia.text.strip()
        label = self.resultado

        if not texto:
            label.text = "Ops!\n\nDigite ou cole uma notícia para começar."
            label.color = self.cores["laranja"]
            return

        if not self._ia_disponivel(label):
            return

        label.text = "Analisando notícia com o ChatGPT...\n\nAguarde."
        label.color = self.cores["azul"]
        self._iniciar_progresso()

        def tarefa():
            return verificar_noticia(texto)

        def sucesso(res):
            self._parar_progresso()
            veredito, confianca, explicacao, numero_api = res
            label.text = (
                "Resultado da análise\n\n"
                f"{veredito}\n\n"
                f"Confiança do modelo: {confianca:.1f}%\n"
                f"API usada: {numero_api} ({len(texto)} caracteres)"
                + (f"\n\n{explicacao}" if explicacao else "")
            )
            label.color = self._cor_veredito(veredito)
            self._adicionar_historico(
                "Notícia (texto)",
                texto,
                veredito,
                f"Confiança: {confianca:.1f}% | API {numero_api}"
            )

        def erro(e):
            self._parar_progresso()
            label.text = f"Erro ao analisar:\n\n{e}"
            label.color = self.cores["vermelho"]

        self._executar_em_thread(tarefa, sucesso, erro)

    # ============================================================
    # URL — EXTRAÇÃO E ANÁLISE
    # ============================================================
    def _extrair_texto_url(self, url):
        if not WEB_OK:
            raise Exception(
                "Instale as bibliotecas:\n\n"
                "pip install requests beautifulsoup4"
            )
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        }
        r = requests.get(url, timeout=15, headers=headers)
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        titulo = ""
        if soup.title and soup.title.string:
            titulo = soup.title.string.strip()

        paragrafos = [
            p.get_text(" ", strip=True)
            for p in soup.find_all("p")
        ]
        texto = "\n".join(p for p in paragrafos if len(p) > 30)
        return titulo, texto

    def buscar_url(self, instance):
        url = self.url_input.text.strip()
        label = self.resultado

        if not url:
            label.text = "Cole um link no campo acima."
            label.color = self.cores["laranja"]
            return

        if not self._ia_disponivel(label):
            return

        label.text = "Buscando conteúdo do link...\n\nAguarde."
        label.color = self.cores["azul"]
        self._iniciar_progresso()

        def tarefa():
            titulo, texto = self._extrair_texto_url(url)
            if len(texto.split()) < 30:
                raise Exception(
                    "Não foi possível extrair texto suficiente do link."
                )
            veredito, confianca, explicacao, numero_api = verificar_noticia(texto)
            return titulo, texto, veredito, confianca, explicacao, numero_api

        def sucesso(res):
            self._parar_progresso()
            titulo, texto, veredito, confianca, explicacao, numero_api = res
            # Preenche o campo de notícia com o texto extraído
            if self.tela_atual == "fake_news":
                self.noticia.text = texto[:5000]
            label.text = (
                f"Link: {titulo[:80]}\n\n"
                "Resultado da análise\n\n"
                f"{veredito}\n\n"
                f"Confiança do modelo: {confianca:.1f}%\n"
                f"API usada: {numero_api} ({len(texto)} caracteres)"
                + (f"\n\n{explicacao}" if explicacao else "")
            )
            label.color = self._cor_veredito(veredito)
            self._adicionar_historico(
                "Notícia (link)",
                url,
                veredito,
                f"Confiança: {confianca:.1f}% | API {numero_api}"
            )

        def erro(e):
            self._parar_progresso()
            label.text = f"Erro ao buscar link:\n\n{e}"
            label.color = self.cores["vermelho"]

        self._executar_em_thread(tarefa, sucesso, erro)

    # ============================================================
    # DETECTOR DE IA (com explicabilidade)
    # ============================================================
    def mostrar_detector_ia(self):
        self.tela_atual = "ia"
        self.tela_principal.clear_widgets()
        c = self.cores

        titulo = Label(
            text="Detector de Texto de IA",
            font_size=26,
            bold=True,
            color=c["roxo"],
            size_hint_y=None,
            height=55
        )

        subtitulo = Label(
            text="Estima se um texto parece gerado por IA com base em características linguísticas",
            font_size=13,
            color=c["texto_sec"],
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=48
        )
        subtitulo.bind(size=lambda i, v: setattr(i, "text_size", v))

        self.texto_ia = TextInput(
            hint_text="Digite ou cole o texto que deseja analisar...",
            multiline=True,
            font_size=15,
            padding=[15, 15],
            background_color=c["input_bg"],
            foreground_color=c["input_fg"],
            cursor_color=c["roxo"]
        )

        botao_analisar = Button(
            text="ANALISAR TEXTO",
            font_size=18,
            bold=True,
            size_hint_y=None,
            height=55,
            background_normal="",
            background_color=c["roxo"],
            color=(1, 1, 1, 1)
        )
        botao_analisar.bind(on_press=self.verificar_ia)

        area, self.resultado_ia = self._area_resultado(
            "O resultado aparecerá aqui", 15
        )

        self.tela_principal.add_widget(self._barra_topo(com_voltar=True))
        self.tela_principal.add_widget(titulo)
        self.tela_principal.add_widget(subtitulo)
        self.tela_principal.add_widget(self.texto_ia)
        self.tela_principal.add_widget(botao_analisar)
        self.tela_principal.add_widget(area)
        self.tela_principal.add_widget(self._botao_copiar())
        self.tela_principal.add_widget(self.progresso)
        self.tela_principal.add_widget(self._barra_navegacao(atual="ia"))

    def _analisar_texto_ia(self, texto):
        """Retorna (pontuacao, classificacao, lista_de_razoes)."""
        palavras = texto.split()
        quantidade = max(len(palavras), 1)

        frases = texto.replace("!", ".").replace("?", ".").split(".")
        frases = [f.strip() for f in frases if f.strip()]
        palavras_por_frase = quantidade / max(len(frases), 1)

        palavras_longas = [
            p for p in palavras
            if len(p.strip(".,!?;:")) >= 10
        ]
        porcentagem_longas = (len(palavras_longas) / quantidade) * 100

        pontuacao = 30
        razoes = ["Pontuação base: 30"]

        if palavras_por_frase > 20:
            pontuacao += 25
            razoes.append(f"Frases muito longas (média {palavras_por_frase:.1f} palavras): +25")
        elif palavras_por_frase > 14:
            pontuacao += 15
            razoes.append(f"Frases longas (média {palavras_por_frase:.1f} palavras): +15")
        else:
            razoes.append(f"Média de {palavras_por_frase:.1f} palavras por frase: +0")

        if porcentagem_longas > 15:
            pontuacao += 20
            razoes.append(f"Muitas palavras longas ({porcentagem_longas:.1f}%): +20")
        elif porcentagem_longas > 8:
            pontuacao += 10
            razoes.append(f"Palavras longas moderadas ({porcentagem_longas:.1f}%): +10")
        else:
            razoes.append(f"Poucas palavras longas ({porcentagem_longas:.1f}%): +0")

        if 10 <= palavras_por_frase <= 22:
            pontuacao += 10
            razoes.append("Estrutura uniforme das frases: +10")

        if palavras_por_frase < 8:
            pontuacao -= 15
            razoes.append("Frases muito curtas (típico de escrita humana): -15")

        pontuacoes = texto.count(",") + texto.count(";") + texto.count(":")
        if quantidade > 50 and pontuacoes >= 5:
            pontuacao += 10
            razoes.append(f"Uso rico de pontuação ({pontuacoes} marcas): +10")

        pontuacao = max(0, min(100, pontuacao))

        if pontuacao >= 65:
            classificacao = "Provavelmente gerado por IA"
        elif pontuacao >= 40:
            classificacao = "Inconclusivo — pode ser IA ou humano"
        else:
            classificacao = "Provavelmente escrito por humano"

        return pontuacao, classificacao, razoes

    def verificar_ia(self, instance):
        texto = self.texto_ia.text.strip()
        label = self.resultado_ia

        if not texto:
            label.text = "Digite ou cole um texto para começar."
            label.color = self.cores["laranja"]
            return

        if len(texto.split()) < 30:
            label.text = (
                "Texto muito curto!\n\n"
                "Para uma análise útil, use pelo menos 30 palavras."
            )
            label.color = self.cores["laranja"]
            return

        label.text = "Analisando texto...\n\nAguarde."
        label.color = self.cores["roxo"]
        self._iniciar_progresso()

        def tarefa():
            return self._analisar_texto_ia(texto)

        def sucesso(res):
            self._parar_progresso()
            pontuacao, classificacao, razoes = res

            if pontuacao >= 65:
                label.color = self.cores["roxo"]
            elif pontuacao >= 40:
                label.color = self.cores["laranja"]
            else:
                label.color = self.cores["verde"]

            detalhes = "\n".join(f"  • {r}" for r in razoes)

            label.text = (
                "Resultado da análise\n\n"
                f"{classificacao}\n\n"
                f"Estimativa: {pontuacao:.1f}%\n\n"
                "Fatores considerados:\n"
                f"{detalhes}\n\n"
                "Esta análise é uma estimativa e não determina "
                "com certeza se um texto foi escrito por IA."
            )

            self._adicionar_historico(
                "Texto de IA",
                texto,
                classificacao,
                f"Estimativa: {pontuacao:.1f}%"
            )

        def erro(e):
            self._parar_progresso()
            label.text = f"Erro ao analisar:\n\n{e}"
            label.color = self.cores["vermelho"]

        self._executar_em_thread(tarefa, sucesso, erro)

    # ============================================================
    # DETECTOR DE IMAGENS (com análise em lote)
    # ============================================================
    def mostrar_detector_imagem(self):
        self.tela_atual = "imagem"
        self.tela_principal.clear_widgets()
        c = self.cores

        titulo = Label(
            text="Detector de Imagens",
            font_size=26,
            bold=True,
            color=c["verde"],
            size_hint_y=None,
            height=55
        )

        subtitulo = Label(
            text="Analise uma ou várias imagens para verificar sinais de IA ou manipulação.\n"
                 "Você também pode ARRASTAR imagens para a janela.",
            font_size=13,
            color=c["texto_sec"],
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=48
        )
        subtitulo.bind(size=lambda i, v: setattr(i, "text_size", v))

        self.imagem_selecionada = Image(
            allow_stretch=True,
            keep_ratio=True
        )

        self.texto_arrastar = Label(
            text="Arraste uma imagem aqui ou use o botão abaixo",
            font_size=13,
            color=c["texto_sec"],
            size_hint_y=None,
            height=28
        )

        # Mantém a seleção anterior (ex.: ao trocar o tema), se os arquivos ainda existirem
        self.lista_imagens = [p for p in self.lista_imagens if os.path.isfile(p)]
        self.caminho_imagem = self.lista_imagens[0] if self.lista_imagens else None
        if self.caminho_imagem:
            self.imagem_selecionada.source = self.caminho_imagem

        bt_selecionar = Button(
            text="SELECIONAR IMAGEM (ou várias)",
            font_size=16,
            bold=True,
            size_hint_y=None,
            height=50,
            background_normal="",
            background_color=c["verde"],
            color=(1, 1, 1, 1)
        )
        bt_selecionar.bind(on_press=self.selecionar_imagem)

        bt_analisar = Button(
            text="ANALISAR IMAGEM",
            font_size=17,
            bold=True,
            size_hint_y=None,
            height=52,
            background_normal="",
            background_color=c["roxo"],
            color=(1, 1, 1, 1)
        )
        bt_analisar.bind(on_press=self.analisar_imagem)

        area, self.resultado_imagem = self._area_resultado(
            "Selecione uma imagem para começar.", 14
        )
        self._ia_disponivel(self.resultado_imagem)

        self.tela_principal.add_widget(self._barra_topo(com_voltar=True))
        self.tela_principal.add_widget(titulo)
        self.tela_principal.add_widget(subtitulo)
        self.tela_principal.add_widget(self.imagem_selecionada)
        self.tela_principal.add_widget(self.texto_arrastar)
        self.tela_principal.add_widget(bt_selecionar)
        self.tela_principal.add_widget(bt_analisar)
        self.tela_principal.add_widget(area)
        self.tela_principal.add_widget(self._botao_copiar())
        self.tela_principal.add_widget(self.progresso)
        self.tela_principal.add_widget(self._barra_navegacao(atual="imagem"))

    def selecionar_imagem(self, instance):
        chooser = FileChooserListView(
            filters=FILTROS_IMAGEM,
            path=os.path.expanduser("~"),
            multiselect=True
        )

        layout = BoxLayout(orientation="vertical", spacing=5, padding=5)

        bt_usar = Button(
            text="USAR ESTA(S) IMAGEM(NS)",
            size_hint_y=None,
            height=50,
            background_normal="",
            background_color=self.cores["verde"],
            color=(1, 1, 1, 1)
        )

        layout.add_widget(chooser)
        layout.add_widget(bt_usar)

        popup = Popup(
            title="Escolha uma ou várias imagens",
            content=layout,
            size_hint=(0.9, 0.9)
        )

        def usar(instance):
            selecionados = list(chooser.selection or [])
            if not selecionados:
                return
            popup.dismiss()
            self._carregar_imagens(selecionados)

        bt_usar.bind(on_press=usar)
        popup.open()

    def analisar_imagem(self, instance):
        label = self.resultado_imagem

        if not self.lista_imagens and not self.caminho_imagem:
            label.text = (
                "Nenhuma imagem selecionada.\n\n"
                "Selecione ou arraste uma imagem primeiro."
            )
            label.color = self.cores["laranja"]
            return

        if not self._ia_disponivel(label):
            return

        imagens = list(self.lista_imagens or [self.caminho_imagem])

        label.text = f"Analisando {len(imagens)} imagem(ns)...\n\nAguarde."
        label.color = self.cores["roxo"]
        self._iniciar_progresso()

        def tarefa():
            resultados = []
            for caminho in imagens:
                try:
                    resultado, confianca, motivo = verificar_imagem(caminho)
                    resultados.append((caminho, resultado, confianca, motivo))
                except Exception as e:
                    resultados.append((caminho, "ERRO", 0.0, str(e)))
            return resultados

        def sucesso(resultados):
            self._parar_progresso()

            linhas = []
            for caminho, resultado, confianca, motivo in resultados:
                nome = os.path.basename(caminho)
                linhas.append(
                    f"• {nome}\n"
                    f"  Resultado: {resultado}\n"
                    f"  Confiança: {confianca:.1f}%\n"
                    f"  Motivo: {motivo}"
                )
                if resultado != "ERRO":
                    self._adicionar_historico(
                        "Imagem",
                        nome,
                        resultado,
                        f"Confiança: {confianca:.1f}%"
                    )

            if len(resultados) == 1:
                resultado = resultados[0][1]
                if resultado == "PROVAVELMENTE IA":
                    label.color = self.cores["roxo"]
                elif resultado == "POSSIVELMENTE MANIPULADA":
                    label.color = self.cores["laranja"]
                elif resultado == "PROVAVELMENTE REAL":
                    label.color = self.cores["verde"]
                else:
                    label.color = self.cores["vermelho"]
            else:
                label.color = self.cores["texto"]

            label.text = (
                "RESULTADO DA ANÁLISE\n\n"
                + "\n\n".join(linhas)
                + "\n\nEsta análise é uma estimativa."
            )

        def erro(e):
            self._parar_progresso()
            label.text = f"ERRO AO ANALISAR:\n\n{e}"
            label.color = self.cores["vermelho"]

        self._executar_em_thread(tarefa, sucesso, erro)

    # ============================================================
    # DRAG & DROP
    # ============================================================
    def _configurar_drag_drop(self):
        """
        Configura drag & drop de arquivos.

        Kivy >= 2.1: on_drop_begin / on_drop_file / on_drop_end
        Kivy antigo: on_dropfile
        """
        try:
            Window.bind(
                on_drop_begin=self._inicio_drop,
                on_drop_file=self.soltar_imagem,
                on_drop_end=self._fim_drop
            )
            self._drag_drop_moderno = True
        except Exception as e:
            print("[DROP] Usando modo de compatibilidade:", e)
            self._drag_drop_moderno = False
            try:
                Window.bind(on_dropfile=self._soltar_imagem_legado)
            except Exception as erro:
                print("[DROP] Drag & drop indisponível:", erro)

    def _inicio_drop(self, window, x, y, *args):
        """Chamado quando o usuário começa a soltar arquivos."""
        if self.tela_atual != "imagem":
            return
        self._drop_em_andamento = True
        self._arquivos_drop = []

    def _normalizar_caminho_drop(self, file_path):
        """
        Converte o caminho recebido pelo Kivy para um caminho
        válido do sistema operacional.
        """
        try:
            caminho = os.fsdecode(file_path)
        except Exception:
            caminho = str(file_path)

        caminho = (
            caminho
            .replace("\x00", "")
            .strip()
            .strip('"')
            .strip("'")
        )

        # Suporte caso venha no formato file://
        if caminho.lower().startswith("file://"):
            parsed = urlparse(caminho)
            caminho = unquote(parsed.path)

            # Windows: /C:/Users/... -> C:/Users/...
            if (
                os.name == "nt"
                and len(caminho) > 2
                and caminho[0] == "/"
                and caminho[2] == ":"
            ):
                caminho = caminho[1:]

        return os.path.normpath(caminho)

    def soltar_imagem(self, window, file_path, x=None, y=None, *args):
        """Recebe um arquivo arrastado para a janela."""

        # Só aceita drag & drop na tela de imagens
        if self.tela_atual != "imagem":
            return

        caminho = self._normalizar_caminho_drop(file_path)
        print(f"[DROP] Arquivo recebido: {caminho}")

        if not caminho.lower().endswith(EXTENSOES_IMAGEM):
            self.resultado_imagem.text = (
                "ARQUIVO INVÁLIDO!\n\n"
                "Use uma imagem PNG, JPG, JPEG ou WEBP."
            )
            self.resultado_imagem.color = self.cores["laranja"]
            return

        if not os.path.isfile(caminho):
            self.resultado_imagem.text = f"ARQUIVO NÃO ENCONTRADO!\n\n{caminho}"
            self.resultado_imagem.color = self.cores["vermelho"]
            return

        if caminho not in self._arquivos_drop:
            self._arquivos_drop.append(caminho)

        # Algumas versões/plataformas podem não emitir
        # on_drop_begin/on_drop_end corretamente.
        if not self._drop_em_andamento:
            self._carregar_imagens(list(self._arquivos_drop))
            self._arquivos_drop = []

    def _fim_drop(self, window, x, y, *args):
        """
        Chamado quando termina o drag & drop.
        Permite inclusive arrastar várias imagens juntas.
        """
        if self.tela_atual == "imagem" and self._arquivos_drop:
            self._carregar_imagens(list(self._arquivos_drop))

        self._drop_em_andamento = False
        self._arquivos_drop = []

    def _soltar_imagem_legado(self, window, file_path):
        """Compatibilidade com versões antigas do Kivy."""
        self.soltar_imagem(window, file_path)

    def _carregar_imagens(self, caminhos):
        """
        Atualiza a interface depois que imagens foram selecionadas
        (pelo botão ou arrastando para a janela).
        """
        caminhos_validos = []
        for caminho in caminhos:
            if not os.path.isfile(caminho):
                continue
            if not caminho.lower().endswith(EXTENSOES_IMAGEM):
                continue
            if caminho not in caminhos_validos:
                caminhos_validos.append(caminho)

        if not caminhos_validos:
            return

        self.lista_imagens = caminhos_validos
        self.caminho_imagem = caminhos_validos[0]

        # Mostra a primeira como preview
        self.imagem_selecionada.source = self.caminho_imagem
        self.imagem_selecionada.reload()

        quantidade = len(caminhos_validos)

        if quantidade == 1:
            self.texto_arrastar.text = (
                "Imagem carregada! Você pode arrastar outra imagem aqui."
            )
            self.resultado_imagem.text = (
                "Imagem carregada com sucesso!\n\n"
                "Clique em ANALISAR IMAGEM."
            )
        else:
            self.texto_arrastar.text = f"{quantidade} imagens carregadas."
            self.resultado_imagem.text = (
                f"{quantidade} imagens carregadas com sucesso!\n\n"
                "Clique em ANALISAR IMAGEM para fazer a análise em lote."
            )

        self.resultado_imagem.color = self.cores["verde"]

    # ============================================================
    # COMPARAÇÃO DE DUAS NOTÍCIAS
    # ============================================================
    def mostrar_comparacao(self):
        self.tela_atual = "comparacao"
        self.tela_principal.clear_widgets()
        c = self.cores

        titulo = Label(
            text="Comparar Duas Notícias",
            font_size=26,
            bold=True,
            color=c["azul"],
            size_hint_y=None,
            height=50
        )

        subtitulo = Label(
            text="Verifica o grau de semelhança entre dois textos (possível plágio ou desinformação duplicada)",
            font_size=12,
            color=c["texto_sec"],
            halign="center",
            valign="middle",
            size_hint_y=None,
            height=40
        )
        subtitulo.bind(size=lambda i, v: setattr(i, "text_size", v))

        lbl_a = Label(
            text="Notícia A:", font_size=13, bold=True,
            color=c["texto"], size_hint_y=None, height=22,
            halign="left"
        )
        lbl_a.bind(size=lambda i, v: setattr(i, "text_size", v))

        self.texto_a = TextInput(
            hint_text="Cole a primeira notícia aqui...",
            multiline=True,
            font_size=13,
            padding=[10, 10],
            background_color=c["input_bg"],
            foreground_color=c["input_fg"],
            cursor_color=c["azul"]
        )

        lbl_b = Label(
            text="Notícia B:", font_size=13, bold=True,
            color=c["texto"], size_hint_y=None, height=22,
            halign="left"
        )
        lbl_b.bind(size=lambda i, v: setattr(i, "text_size", v))

        self.texto_b = TextInput(
            hint_text="Cole a segunda notícia aqui...",
            multiline=True,
            font_size=13,
            padding=[10, 10],
            background_color=c["input_bg"],
            foreground_color=c["input_fg"],
            cursor_color=c["azul"]
        )

        bt_comparar = Button(
            text="COMPARAR TEXTOS",
            font_size=16,
            bold=True,
            size_hint_y=None,
            height=50,
            background_normal="",
            background_color=c["azul"],
            color=(1, 1, 1, 1)
        )
        bt_comparar.bind(on_press=self.comparar)

        area, self.resultado_comp = self._area_resultado(
            "O resultado aparecerá aqui", 14
        )

        self.tela_principal.add_widget(self._barra_topo(com_voltar=True))
        self.tela_principal.add_widget(titulo)
        self.tela_principal.add_widget(subtitulo)
        self.tela_principal.add_widget(lbl_a)
        self.tela_principal.add_widget(self.texto_a)
        self.tela_principal.add_widget(lbl_b)
        self.tela_principal.add_widget(self.texto_b)
        self.tela_principal.add_widget(bt_comparar)
        self.tela_principal.add_widget(area)
        self.tela_principal.add_widget(self._botao_copiar())
        self.tela_principal.add_widget(self.progresso)
        self.tela_principal.add_widget(self._barra_navegacao(atual="comparacao"))

    def comparar(self, instance):
        a = self.texto_a.text.strip()
        b = self.texto_b.text.strip()
        label = self.resultado_comp

        if not a or not b:
            label.text = "Preencha os dois campos com textos para comparar."
            label.color = self.cores["laranja"]
            return

        label.text = "Comparando textos...\n\nAguarde."
        label.color = self.cores["azul"]
        self._iniciar_progresso()

        def tarefa():
            return difflib.SequenceMatcher(
                None, a.lower(), b.lower()
            ).ratio() * 100

        def sucesso(razao):
            self._parar_progresso()

            if razao >= 80:
                veredito = "TEXTOS MUITO SEMELHANTES — provável cópia ou variação."
                cor = self.cores["vermelho"]
            elif razao >= 50:
                veredito = "TEXTOS PARCIALMENTE SEMELHANTES — pode haver trechos em comum."
                cor = self.cores["laranja"]
            else:
                veredito = "TEXTOS DIFERENTES — semelhança baixa."
                cor = self.cores["verde"]

            label.color = cor
            label.text = (
                "Resultado da comparação\n\n"
                f"{veredito}\n\n"
                f"Semelhança textual: {razao:.1f}%"
            )

            self._adicionar_historico(
                "Comparação",
                f"A: {a[:60]}... | B: {b[:60]}...",
                veredito,
                f"Semelhança: {razao:.1f}%"
            )

        def erro(e):
            self._parar_progresso()
            label.text = f"Erro:\n\n{e}"
            label.color = self.cores["vermelho"]

        self._executar_em_thread(tarefa, sucesso, erro)


if __name__ == "__main__":
    FakeNewsApp().run()