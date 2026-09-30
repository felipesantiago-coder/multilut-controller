MULTILUT CONTROLLER 1.8
=======================

Aplicativo nativo GTK4/Libadwaita para selecionar e aplicar os 25 perfis do
MultiLUT Insurgency Optimized v1.8 no vkBasalt e para ampliar as lunetas do
Insurgency até 12x, com opções rápidas de 3x, 5x e 10x. Os recursos de treino
de mira, progresso e mira na tela foram removidos nesta versão.

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

1. Escolha um perfil na lista.
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

LUNETAS AMPLIADAS (ATE 12X)
---------------------------

A aba "Lunetas" aumenta a ampliação das lunetas do Insurgency usando o
mecanismo oficial de theaters: o aplicativo gera o arquivo
scripts/theaters/multilut_zoom.theater dentro da pasta do jogo e aponta
mp_theater_override para ele.

COMO FUNCIONA:

- A ampliação de cada luneta vem do valor fov_wpn_scope do theater:
  quanto menor o FOV, maior o zoom. A luneta "7x" usa FOV 10.
- Para 12x, o aplicativo grava FOV 5.83 (10 x 7/12) nas lunetas
  selecionadas. Lunetas 1x (red dots) não são alteradas.
- O override cobre também os sub-blocos por arma (weapon_mosin,
  weapon_fal, weapon_m40a1…) que o theater oficial define dentro de
  optics_fov_override — sem isso o jogo ignora o FOV novo e a luneta
  fica sem ampliação extra.
- O theater gerado herda o classic.theater inteiro (#base): squads,
  classes coop, gear e armas continuam os oficiais — só os FOVs das
  lunetas mudam. Isso é obrigatório: os playlists coop do jogo forçam o
  theater classic, e substituí-lo sem herdar os squads quebra o modo
  (o jogo rejeita o jogador com "PLAYER LIMIT REACHED (0/0)").
- Nenhum VPK ou arquivo original do jogo é modificado: o theater é um
  arquivo novo, e restaurar o padrão é apagar o arquivo e os blocos de
  ativação no autoexec.cfg, no listenserver.cfg e a opção de inicialização
  (o botão "Restaurar padrão do jogo" faz tudo isso).

ATIVAÇÃO (o playlist coop força mp_theater_override "classic"; para vencer
isso, a ativação precisa acontecer DEPOIS dos playlists):

1. Ativação automática por partida (recomendado, único que vence o
   playlist): ao clicar em "Ativar lunetas ampliadas", o aplicativo grava
   mp_theater_override "multilut_zoom" no cfg/listenserver.cfg do jogo.
   O Insurgency executa esse arquivo ao iniciar qualquer partida hospedada
   por você — o modo solo também, pois é um servidor local — DEPOIS de
   aplicar os playlists e ANTES de escolher o theater, então é o único
   ponto que sobrepõe o "classic" forçado. Em instalações limpas o arquivo
   nem existe (o console mostra "exec: couldn't exec listenserver.cfg"),
   então criá-lo é seguro. Vale já na PRÓXIMA partida: saia da partida
   atual e comece outra — não precisa reiniciar o jogo.
2. Opção de inicialização do Steam: grava +mp_theater_override
   multilut_zoom nas opções de inicialização. Nos modos coop o playlist
   do jogo sobrepõe esse valor (forced_cvars), então vale como reforço —
   não como ativação principal. Requer o Steam fechado na hora de aplicar
   (o Steam regrava o localconfig.vdf ao sair); backup
   localconfig.vdf.multilut.bak é criado na primeira alteração.
3. autoexec.cfg: o bloco gravado no cfg/autoexec.cfg do jogo ativa
   sozinho — mas o Insurgency (2014) nem sempre o executa e, como o
   autoexec roda antes dos playlists, o coop sobrepõe o valor.
4. Console do jogo (manual): mp_theater_override multilut_zoom só vale
   depois de um mapa ser recarregado (changelevel <mapa>, ou sair da
   partida e começar outra). Digitado no MEIO da partida, o comando
   apenas reinicia a rodada e o theater NÃO é recarregado — o console
   continua mostrando "Loading theater file 'classic'" e nenhuma
   "multilut_zoom". Esse é o sintoma de "apliquei e não mudou nada".

USO EM SERVIDORES DE TERCEIROS (SOMENTE COM AUTORIZAÇÃO DO ADMIN):

O theater é autoritativo no servidor: ao conectar, o cliente recebe o
theater do servidor (o console mostra "Loading theater file ..." com o
nome escolhido pelo servidor) e nenhum ajuste no cliente vale lá. Para a
ampliação funcionar num servidor de terceiros, ela precisa ser instalada
NO SERVIDOR — assim vale igualmente para todos os jogadores:

1. No aplicativo, aba Lunetas, botão "Gerar para servidor…": grava o
   arquivo multilut_zoom.theater (com a ampliação e as lunetas
   selecionadas no momento) em qualquer pasta, para você enviar ao admin.
2. Servidor SEM theater custom: copie o arquivo para
   <servidor>/insurgency/scripts/theaters/ e force o theater no playlist
   do servidor (forced_cvars: mp_theater_override multilut_zoom) — em
   coop é o único ponto que vence, igual no jogo local; server.cfg é
   sobrescrito pelo playlist.
3. Servidor COM theater custom (ex.: um mod de gameplay): mescle o bloco
   "weapon_upgrades" do multilut_zoom.theater dentro do theater do
   servidor. O merge de theaters é profundo: os FOVs por arma vencem os
   valores de nível superior e todo o resto do mod permanece intacto.
4. Servidor com fastdl: distribua o theater no pacote de download, como
   qualquer outro arquivo custom do servidor.

Sem autorização do admin não use: editar a cópia local do theater do
servidor configura vantagem indevida sobre os demais jogadores e risco
de banimento (consistência, BattlEye, regras do servidor).

OVERRIDE CLIENT-SIDE (SOMENTE COM AUTORIZAÇÃO DE TODOS OS ADMINS):

O Insurgency (2014) não tem mais servidores oficiais — se TODOS os
administradores dos servidores que você frequenta autorizarem, o
aplicativo pode aplicar a ampliação direto na CÓPIA LOCAL dos theaters
que o servidor entrega no seu disco (scripts/theaters/*.theater):

- Marque "Aplicar também nos theaters de servidores (client-side)" na
  aba Lunetas e clique em Ativar. Cada theater local recebe o FOV novo
  das ópticas selecionadas; para as ópticas que não existem no arquivo,
  é acrescentada a linha "#base" multilut_zoom_fov.theater (um arquivo
  só com os FOVs, sem herdar conteúdo de outro modo) marcada com o
  comentário "multilut-zoom-client". O original de cada arquivo fica em
  <arquivo>.multilut.bak na primeira alteração.
- Os theaters de fábrica (default_weapon_upgrades.theater etc.) NÃO
  ficam soltos na instalação — vivem dentro dos VPKs em insurgency/vpk.
  O aplicativo extrai automaticamente para scripts/theaters os theaters
  empacotados que definem FOV de luneta e aplica o patch neles: a cópia
  solta prevalece sobre o VPK na busca de arquivos do Source, então o
  theater que o servidor pedir (default, classic…) já carrega o FOV
  novo. O backup .multilut.bak guarda o conteúdo original do VPK.
- O botão "Restaurar padrão do jogo" também devolve todos os theaters
  de servidor ao original, apaga os backups e remove o
  multilut_zoom_fov.theater.
- O patch é somente visual (FOV): dano, recuo e equipamentos continuam
  definidos pelo servidor. Se um servidor atualizar o theater dele, o
  jogo baixa a versão nova por cima — clique em Ativar de novo para
  reaplicar a ampliação.
- Formatos exóticos de theater são recusados com segurança (o arquivo
  aparece como ignorado no toast e não é modificado).
- Riscos que ficam por sua conta: servidores com BattlEye ou checagens
  próprias podem rejeitar arquivos alterados; sem autorização dos
  admins, o recurso configura vantagem indevida e pode render
  banimento.

OPÇÕES DE AMPLIAÇÃO:

- Opções rápidas na aba: 3x, 5x, 10x e 12x — um clique ajusta e grava.
- Ajuste fino pelo controle deslizante, de 1x a 12x, em passos de 0,5x.
- A ampliação escolhida se aplica a todas as lunetas marcadas.

LUNETAS DISPONÍVEIS:

- Luneta 7x (Mosin, FAL, SKS) — 7x até 12x.
- Luneta MK4 (M40A1, M14, M16A4) — 7x até 12x.
- PO 4x24 (AKM, FAL, Galil, Mosin) — 4x até 12x.
- Elcan (armas Security) — 4x até 12x.
- Aimpoint 2x — 2x até 12x.

ONDE VALE E JOGO JUSTO:

- O theater é carregado quando VOCÊ hospeda a partida: coop (Checkpoint,
  Survival…), PvP com bots ou servidor próprio — em qualquer modo local,
  a partir da primeira partida iniciada DEPOIS de clicar em Ativar
  (o modo solo incluído).
- Em servidores de terceiros o theater é definido pelo servidor, então
  o ajuste não se aplica lá. Respeite as regras do servidor ou torneio.
- O recurso usa apenas arquivos de configuração suportados pelo jogo:
  não lê memória, não injeta código e não interfere na rede.

O caminho do jogo é detectado automaticamente nas bibliotecas Steam
(incluindo Flatpak); também pode ser informado manualmente na aba. A pasta
é reconhecida pelas subpastas típicas do jogo (maps, cfg, materials…) — a
instalação não precisa ter a pasta scripts/ no disco: o aplicativo cria
scripts/theaters na hora de gravar o theater.

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

Shader padrao:
  ~/.config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx

Atlas padrao:
  ~/.config/vkBasalt/reshade-shaders/Textures/MultiLut_Insurgency_Optimized.png

VALIDACAO
---------

O nucleo foi testado para leitura, alteracao, backup, restauracao, recusa de
perfil invalido, validacao do shader e ordenacao alfabetica dos perfis
(tests/test_core.py). A geracao de theaters das lunetas (FOV, autoexec,
restauracao e deteccao da instalacao) tem testes em tests/test_scopes.py.
A interface foi verificada estaticamente; o teste visual final precisa ser
realizado no seu ambiente GNOME/Wayland.
