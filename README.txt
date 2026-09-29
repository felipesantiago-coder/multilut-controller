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
mp_theater_override para ele (via autoexec.cfg ou comando no console).

COMO FUNCIONA:

- A ampliação de cada luneta vem do valor fov_wpn_scope do theater:
  quanto menor o FOV, maior o zoom. A luneta "7x" usa FOV 10.
- Para 12x, o aplicativo grava FOV 5.83 (10 x 7/12) nas lunetas
  selecionadas. Lunetas 1x (red dots) não são alteradas.
- Nenhum VPK ou arquivo original do jogo é modificado: o theater é um
  arquivo novo, e restaurar o padrão é apagar o arquivo e a linha do
  autoexec (o botão "Restaurar padrão do jogo" faz os dois).

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

- O theater é carregado quando VOCÊ hospeda a partida: coop, prática ou
  servidor próprio. Reinicie o jogo depois de ativar.
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
