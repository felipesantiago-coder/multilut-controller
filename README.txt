MULTILUT CONTROLLER 1.8
=======================

Aplicativo nativo GTK4/Libadwaita para selecionar e aplicar os 25 perfis do
MultiLUT Insurgency Optimized v1.8 no vkBasalt. A lista de perfis aparece em
duas seções — "Efeitos de mapa" e "Efeitos utilitários" — cada uma em ordem
alfabética, para encontrar o efeito desejado rapidamente. Os recursos de
treino de mira, progresso, mira na tela e ampliação de lunetas (theaters)
foram removidos nesta versão.

COMPATIBILIDADE TESTADA COMO ALVO
--------------------------------

- Solus 4.9 Serenity x86_64
- GNOME 50 / Mutter / Wayland
- Tela 1366 x 768 ou superior
- Python 3, GTK 4, PyGObject e libadwaita
- vkBasalt com suporte a ReShade FX

INSTALACAO
----------

1. Extraia o ZIP.
2. Abra a pasta MultiLUT_Controller.
3. No terminal, execute:

   chmod +x install.sh
   ./install.sh

4. Abra "MultiLUT Controller" pelo ícone da área de trabalho ou pelo menu de
   aplicativos.

Se o instalador indicar dependencias ausentes, abra o Centro de Programas do
Solus e instale os componentes PyGObject para Python 3, GTK 4 e libadwaita.

O instalador funciona somente dentro da sua conta e nao usa sudo. Ele instala
o aplicativo em ~/.local/share e nao altera o shader automaticamente.

PRIMEIRO USO
------------

Se o shader v1.8 ja estiver instalado no caminho padrao, o aplicativo o detecta
automaticamente. Para instalar ou substituir uma versao anterior, clique em
"Instalar/atualizar pacote MultiLUT v1.8".
O pacote interno contem:

- MultiLUT_Insurgency_Optimized.fx
- MultiLut_Insurgency_Optimized.png
- vkBasalt_MultiLUT_TEST.conf como referencia

Arquivos existentes recebem extensao .bak antes de serem substituidos.

A v1.4 remove o aspecto lavado dos perfis: evita a recuperacao duplicada de
sombras, preserva crominancia em baixa luminancia e restaura densidade de cor
sem sacrificar a visibilidade competitiva.

A v1.5 remove o filtro sepia residual: elimina deslocamentos fixos de
temperatura e reforco artificial de tons terrosos, preservando a matiz original.

A v1.6 separa melhor cores proximas, reforca o contraste local e clareia os
perfis Heights, Station e Verticality sem aumentar os brancos intensos.

A v1.8 adiciona perfis dedicados para Market, Ministry, Peak, Revolt, Siege,
Tell, Uprising e Kandagal sem alterar a geometria 1024 x 544 do atlas.

COMO USAR
---------

1. Escolha um perfil na lista. Ele esta em uma de duas secoes:

   - "Efeitos de mapa": perfis criados para um mapa especifico (Buhriz,
     Contact, District, Dry Canal, Embassy, Heights, Kandagal, Market,
     Ministry, Panj, Peak, Revolt, Siege, Sinjar, Station, Tell, Uprising
     e Verticality). Cada perfil aparece como um cartao com a foto oficial
     do mapa ao fundo e o nome do mapa em destaque; o painel de detalhes
     tambem mostra a foto em tamanho maior.
   - "Efeitos utilitarios": perfis que valem em qualquer cenario —
     interiores escuros, longa distancia, competitivos e o neutro de
     referencia.

   As duas secoes sao alfabeticas; a busca no topo cobre as duas.

   Sobre as fotos dos cartoes: sao as artes oficiais de selecao de mapa do
   proprio Insurgency, extraidas dos depots do servidor dedicado no Steam
   (materials/vgui/maps/<mapa>_large.vtf) e embaladas junto ao aplicativo
   em assets/maps/. Sao propriedade da New World Interactive, usadas aqui
   apenas como referencia visual em uma ferramenta gratuita para o jogo;
   nenhuma parte do jogo e modificada por elas. Se algum arquivo estiver
   ausente, o cartao cai num degradê com a cor de destaque do tema e o
   aplicativo segue funcionando normalmente.
2. Leia a indicacao e o comportamento visual esperado.
3. Clique em "Aplicar perfil".
4. Inicie o jogo normalmente ou use "Aplicar e iniciar o jogo".

O modo "Aplicar ao selecionar" grava cada perfil imediatamente no arquivo.
O botao de desfazer no cabecalho restaura o ultimo backup.

TROCA EM TEMPO REAL
-------------------

Na instalacao-alvo com Solus, Proton e vkBasalt, foi confirmado que alterar o
perfil no arquivo .fx faz efeito no Insurgency enquanto o jogo esta aberto.
O controlador aproveita esse recarregamento automatico:

- Com o jogo fechado: escolha o perfil e use "Aplicar e iniciar o jogo".
- Com o jogo aberto: escolha o perfil e pressione "Aplicar agora".
- Com "Aplicar ao selecionar" ativo: clicar em outro perfil grava a alteracao
  imediatamente, sem precisar pressionar outro botao.
- F3 continua ativando ou desativando todo o efeito MultiLUT.

O programa detecta o processo do Insurgency e indica "tempo real" na interface.

AUTOMACAO E INTEGRACAO
----------------------

- CLI sem interface: multilut-ctl list, multilut-ctl set <perfil>,
  multilut-ctl active e multilut-ctl status. O casamento aceita id, nome
  sem acentos ou slug do mapa (ex.: multilut-ctl set drycanal). A CLI e
  instalada em $XDG_DATA_HOME/bin/multilut-ctl pelo install.sh e aceita
  --shader para um arquivo alternativo e --no-history para nao registrar a
  troca.
- Historico local: cada troca fica em
  ~/.local/state/multilut-controller/history.jsonl (com rotacao automatica)
  e aparece na pagina "Historico" do aplicativo, com a origem da troca
  (manual, piloto automatico por mapa, inicio do jogo ou CLI) e botao de
  limpeza.
- Notificacao do desktop: quando a troca vem de automacao (CLI, piloto
  automatico, inicio do jogo ou processo externo) o aplicativo mostra um
  aviso discreto. O interruptor "Notificar ao trocar de perfil" desliga isso.
- Aplicar ultimo perfil ao abrir o jogo: com o interruptor ligado, o
  aplicativo detecta a inicializacao do Insurgency e aplica o ultimo perfil
  automaticamente.
- Trocas externas: mudancas feitas fora da janela (por exemplo
  "multilut-ctl set") sao percebidas pelo aplicativo via monitor de arquivo.
- Piloto automatico por mapa: com o interruptor ligado, o aplicativo acompanha
  o console.log do jogo (o monitor e rearmado quando o jogo recria o arquivo)
  e, ao detectar o mapa carregado (ex.: 'Loading map "sinjar"'), aplica
  automaticamente o perfil daquele mapa. Requer -condebug na opcao de
  inicializacao (a pagina Sistema diagnostica e corrige isso). A troca entra
  no historico com a origem "Piloto automatico".
- Atalho global de proximo perfil: registra um atalho do GNOME pelo portal
  org.freedesktop.portal.GlobalShortcuts (GNOME 46+). Ao ligar o interruptor,
  o GNOME abre o dialogo para confirmar/alterar a combinacao sugerida
  (Ctrl+Alt+L). O atalho aplica o proximo perfil (0 a 24, ciclando) mesmo
  quando a janela nao esta em foco; a troca entra no historico com a origem
  "Atalho global". Sem portal na sessao (ou recusa), o interruptor volta para
  desligado com um aviso — nada quebra.
- Verificador de atualizacoes: o aplicativo consulta a release mais recente
  no GitHub em segundo plano e avisa com um toast quando existe versao nova;
  a pagina Sistema tem o botao "Verificar atualizacoes agora".

PAGINA SISTEMA
--------------

A pagina "Sistema" concentra o diagnostico e a manutencao:

- Checklist de diagnostico: shader MultiLUT, camada Vulkan do vkBasalt,
  runtime Vulkan, opcao de inicializacao do Steam, console.log do jogo,
  dependencias opcionais de simulacao (Pillow/numpy) e instalacoes do jogo
  encontradas. O botao "Reverificar" refaz a checagem.
- Opcao de inicializacao: se o jogo estiver sem "%command%" ou sem
  "ENABLE_VKBASALT=1" nas propriedades do Steam, o item aparece em amarelo
  com o botao "Corrigir". A correcao acrescenta apenas o que falta, exige o
  Steam fechado (ele regravaria a configuracao), cria um backup
  localconfig.vdf.multilut.bak antes de gravar e e idempotente.
- Instalacoes do jogo: com mais de uma biblioteca Steam detectada, um
  seletor permite escolher qual instalacao o aplicativo considera.
- Backup do aplicativo: "Exportar..." empacota config.json e history.jsonl
  em um .zip portatil; "Importar..." restaura o backup. Caminhos de maquina
  vindos do arquivo so sao mantidos se existirem neste sistema.

SIMULACAO DE LUT (OPCIONAL)
---------------------------

Com python3-numpy e python3-pillow instalados, o painel de detalhes ganha o
card "Pre-visualizacao (simulacao)": lado a lado, a foto do mapa original e a
foto processada pela simulacao em CPU do pipeline completo do shader
(recuperacao de sombras, brilho protegido, LUT trilinear do atlas v1.8,
mistura luma/croma, contraste local, saturacao, separacao de cores e
compressao de highlights). As constantes de cada perfil (P_CHROMA, P_LUMA...)
sao lidas do proprio shader .fx, entao a simulacao acompanha o arquivo
instalado; o perfil 0 e bypass real, igual no jogo.

- O seletor no card escolhe a foto-base da simulacao (qualquer mapa com foto
  oficial). Perfis de mapa selecionam a propria foto automaticamente; perfis
  utilitarios/competitivos mantem a ultima escolhida. A escolha fica salva no
  config.json.
- O campo "Resolucao do jogo" no card (padrao 1366x768, salvo no config.json)
  informa a resolucao de render configurada no jogo. O raio do contraste local
  do shader (P_RADIUS, em pixels da resolucao nativa) e escalado por ela na
  simulacao, com interpolacao bilinear igual ao filtro LINEAR da GPU — o
  mesmo deslocamento fisico do jogo e reproduzido na previa.
- A simulacao roda em segundo plano (o perfil atual e trocado sem travar a
  interface) e o texto abaixo da imagem mostra o tempo gasto e a resolucao
  usada. Continua sendo uma aproximacao em CPU (sem antialiasing do jogo,
  texturas ou HDR), mas o contraste local acompanha a resolucao configurada.
- Sem numpy/Pillow o aplicativo funciona normalmente: o card informa como
  instalar e o item "Simulacao de LUT (Pillow/numpy)" da pagina Sistema fica
  informativo.
- A CLI tambem simula, sem abrir janela:

    multilut-ctl preview 6                  # Heights sobre a propria foto
    multilut-ctl preview 14 --mapa sinjar   # Competitivo neutro em Sinjar
    multilut-ctl preview 3 --resolucao 1920x1080   # raio escalado para 1080p
    multilut-ctl preview 3 -o /tmp/district.png --atlas caminho/atlas.png

  O PNG de saida traz "original | simulado" lado a lado.

ATLAS: SUBSTITUICAO DE LINHAS (.CUBE) E REINDEXACAO (LOTE 2)
------------------------------------------------------------

O atlas v1.8 tem 17 LUTs (linhas de 1024x32 com 32 fatias azuis). A aba
"Atlas" mostra cada linha com a miniatura da faixa, o nome da LUT-base e os
perfis que a usam (extraidos do bloco P_LUT_ROW do shader instalado).

- Substituir linha por .cube: selecione a linha e clique "Substituir por
  .cube...". O arquivo e interpretado (LUT_3D_SIZE 2 a 256, vermelho variando
  primeiro, LUT_3D_INPUT_RANGE respeitada), reamostrado para 32^3 por
  interpolacao trilinear e gravado no layout do shader. A gravacao e atomica
  e o atlas anterior fica em .bak. Requer numpy e Pillow.
- Restaurar: "Restaurar linha do pacote" devolve a LUT original da linha
  selecionada; "Restaurar atlas do pacote" copia o atlas completo do pacote
  interno; "Restaurar backup (.bak)" traz de volta o atlas anterior.
- Reindexacao: o cartao inferior reescreve o bloco P_LUT_ROW do shader para
  apontar qualquer perfil (0-24) a qualquer linha (0-16), com backup e
  verificacao apos a gravacao. "Restaurar padrao" devolve o mapeamento
  original do shader v1.8. A pre-visualizacao, o card "Atlas do perfil" e a
  lista da aba acompanham o mapeamento atual automaticamente.
- Os dois atlas sao independentes: o pacote interno (bundle) nunca e
  alterado, entao "Instalar/atualizar pacote" devolve tudo ao original.

Na CLI:

    multilut-ctl rows                          # linhas do atlas e perfis donos
    multilut-ctl atlas 3 minha.cube            # substitui a linha 3 (backup em .bak)
    multilut-ctl atlas 3 minha.cube --atlas caminho/atlas.png
    multilut-ctl reindex 14 1                  # perfil 14 passa a usar a linha 1
    multilut-ctl reindex --reset               # mapeamento padrao do v1.8

LIMPEZA DA FUNCIONALIDADE DE LUNETAS (VERSOES ANTERIORES)
--------------------------------------------------------

Versoes anteriores incluiam a aba "Lunetas", que gravava theaters e blocos de
ativacao dentro da pasta do jogo. Essa funcionalidade foi removida: dependia
de alterar theaters, e nos servidores com checagem de consistencia
(sv_consistency) o arquivo alterado e recusado na conexao ("SERVER IS
ENFORCING CONSISTENCY FOR THIS FILE"). Se voce chegou a usa-la, limpe os
residuos — caso contrario o jogo continua carregando o theater
multilut_zoom nas partidas locais:

   cd ~/.local/share/Steam/steamapps/common/insurgency2/insurgency

   # 1. restaura cada theater alterado a partir do backup e apaga o backup
   for bak in scripts/theaters/*.theater.multilut.bak; do
     [ -e "$bak" ] && mv -f "$bak" "${bak%.multilut.bak}"
   done

   # 2. remove os theaters gerados pelo aplicativo
   rm -f scripts/theaters/multilut_zoom.theater
   rm -f scripts/theaters/multilut_zoom_fov.theater

   # 3. remove os blocos marcados do autoexec.cfg e do listenserver.cfg
   for cfg in cfg/autoexec.cfg cfg/listenserver.cfg; do
     [ -e "$cfg" ] && sed -i '/>>> MultiLUT Controller - lunetas ampliadas >>>/,/<<< MultiLUT Controller - lunetas ampliadas <<</d' "$cfg"
   done

Se a pasta do jogo estiver em outra biblioteca Steam, ajuste o caminho do
primeiro comando. Por fim, confira as opcoes de inicializacao no Steam
(clique direito no jogo > Propriedades > Geral): se existir
"+mp_theater_override multilut_zoom", apague.

SEGURANCA DOS ARQUIVOS
----------------------

- Apenas a linha ACTIVE_LUT_PROFILE e alterada.
- Valores fora de 0 a 24 sao recusados.
- A gravacao e atomica para evitar arquivo parcial.
- Um backup .bak e criado antes de cada mudanca.
- O shader e validado antes e depois da gravacao.
- Caminhos alternativos podem ser escolhidos manualmente.

DESINSTALACAO
-------------

Execute:

   ~/.local/share/multilut-controller/uninstall.sh

O desinstalador remove somente o aplicativo e o atalho. Shader, atlas,
configuracoes e backups em ~/.config/vkBasalt sao preservados.

ARQUIVOS E PASTAS
-----------------

Aplicativo:
  ~/.local/share/multilut-controller

Preferencias:
  ~/.config/multilut-controller/config.json

Historico local:
  ~/.local/state/multilut-controller/history.jsonl

CLI (apos ./install.sh):
  ~/.local/share/bin/multilut-ctl

Shader padrao:
  ~/.config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx

Atlas padrao:
  ~/.config/vkBasalt/reshade-shaders/Textures/MultiLut_Insurgency_Optimized.png

ATLAS DO PERFIL E DIAGNOSTICO EXTRAS
------------------------------------

- O painel de detalhes mostra a faixa da LUT usada pelo perfil no atlas
  v1.8 (32 fatias x 17 linhas) e confere a geometria do PNG.
- A busca aceita o numero do perfil (ex.: "7" ou "07") e mostra um
  contador "X de 25 perfis".
- O caminho do shader pode ser copiado com um clique (botao ao lado do
  campo, junto de Selecionar...).
- O rotulo abaixo de "Instalar/atualizar pacote" compara o shader
  instalado com o pacote interno por hash e avisa quando houver
  diferenca (o perfil ativo e preservado ao atualizar).
- A aba Sistema traz a linha "vkBasalt.conf (effects)", que verifica se
  os efeitos configurados incluem o MultiLUT.
- O botao de informacao no cabecalho abre a janela Sobre do aplicativo.

VALIDACAO
---------

O nucleo foi testado para leitura, alteracao, backup, restauracao, recusa de
perfil invalido, validacao do shader, ordenacao alfabetica dos perfis, as
duas secoes da lista, historico, versionamento, bibliotecas Steam, CLI de
ponta a ponta, cartoes de mapa, opcoes de inicializacao do Steam (leitura e
escrita com backup), diagnostico, backup do aplicativo, piloto automatico por
mapa (leitura incremental do console, casamento de mapa/perfil, ciclo de
perfis) e atalho global (ciclo e registro no historico) — 78 testes e 18
subtestes (tests/test_core.py, tests/test_lote1.py, tests/test_lote2.py e
tests/test_lote3.py).
A interface foi verificada em GTK real sob Xvfb, incluindo o piloto
automatico de ponta a ponta (linha de console → troca de perfil) e a falha
graciosa do atalho global sem portal; o teste visual final no seu ambiente
GNOME/Wayland continua recomendado.
