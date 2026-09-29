MULTILUT CONTROLLER 1.8
=======================

Aplicativo nativo GTK4/Libadwaita para selecionar e aplicar os 25 perfis do
MultiLUT Insurgency Optimized v1.8 no vkBasalt. A partir desta versão, o
aplicativo também traz treino de mira (flick), histórico de progresso e um
overlay de mira na tela.

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

TREINO DE MIRA (FLICK)
----------------------

A aba "Treino de mira" é um mini-treinador dentro do próprio aplicativo,
sem contato com o jogo: nenhuma memória do Insurgency é lida ou modificada.

- Um alvo aparece por vez, em posição aleatória, sempre a uma distância
  mínima do anterior para forçar o movimento de flick.
- Clique no alvo o mais rápido possível. Cliques fora do alvo contam
  como erro e aparecem com um X vermelho.
- Ao final da rodada o aplicativo registra: reação média (ms), melhor
  reação, precisão (%) e ritmo (alvos por minuto).
- Configure a quantidade de alvos por rodada (5 a 100) e o raio do alvo
  (10 a 60 px) para aumentar ou diminuir a dificuldade.

Sugestão de rotina: 5 a 10 minutos de treino antes de jogar, sempre com a
mesma sensibilidade do jogo, e compare a tendência na aba Progresso.

PROGRESSO
---------

A aba "Progresso" mostra a evolução ao longo do tempo:

- Cartões de resumo: rodadas treinadas, melhor reação, precisão média e
  ritmo médio.
- Dois gráficos com média móvel das últimas 5 rodadas: reação média (ms)
  e precisão (%).
- O histórico é salvo em
  ~/.config/multilut-controller/training_history.json
  (máximo de 500 rodadas; as mais antigas são descartadas).
- O botão "Limpar histórico de treino" apaga todas as rodadas, com
  confirmação. Perfis, shader e configuração da mira não são afetados.

MIRA NA TELA (OVERLAY)
----------------------

A aba "Mira na tela" ativa um overlay com uma mira customizada (formato
cruz clássico com vão ajustável e ponto central opcional).

COMO FUNCIONA:

- O overlay roda em um processo separado forçado para o X11 do XWayland
  (GDK_BACKEND=x11). Como o Insurgency via Proton também roda no XWayland,
  o GNOME honra o estado "sempre acima" (EWMH _NET_WM_STATE_ABOVE).
- A janela do overlay usa região de entrada vazia (XShape ShapeInput),
  então nenhum clique ou movimento do mouse é capturado por ela.
- O overlay aparece no monitor onde o mouse estava quando você ativou.
- Ele é encerrado automaticamente quando o controlador fecha, ou pelo
  mesmo botão que o ativou.

OPÇÕES DA MIRA (aplicam em tempo real, com o overlay aberto):

- Cor, comprimento dos traços, espessura e vão central.
- Ponto central e contorno escuro (contraste sobre cenários claros).
- Opacidade de 10% a 100%.

A configuração fica em config.json, na chave "crosshair".

JOGO JUSTO / FAIR PLAY:

O overlay é apenas visual, como uma mira impressa no monitor. Ele não lê
memória do jogo, não injeta código, não move o mouse e não interfere na
rede. Ainda assim, regras de servidores ou torneios podem restringir
overlays de mira: verifique as regras antes de usar em competições.

REQUISITOS DA MIRA NA TELA:

- Sessão com XWayland ativo (padrão no GNOME com Steam/Proton).
- libX11 e libXext (presentes em qualquer instalação gráfica do Solus).
- Se o jogo estiver em tela cheia exclusiva e a mira não aparecer, use o
  modo "tela cheia (sem borda)" ou janela nas opções de vídeo do jogo.

SOLUÇÃO DE PROBLEMAS DA MIRA:

- Se a mira não aparecer, o jogo não precisa estar aberto: a mira funciona
  também sobre a área de trabalho. Verifique se o monitor escolhido é o
  mesmo que você está olhando (o overlay nasce onde o mouse estava).
- Se o aviso "O overlay saiu (código X)" aparecer, leia o log em
  ~/.local/state/multilut-controller/overlay.log — toda saída do processo
  do overlay é gravada nesse arquivo a cada ativação.
- Código 3 no log significa que o GTK não conseguiu abrir o XWayland:
  verifique se "echo $DISPLAY" retorna algo na sua sessão.

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

Historico de treino:
  ~/.config/multilut-controller/training_history.json

Shader padrao:
  ~/.config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx

Atlas padrao:
  ~/.config/vkBasalt/reshade-shaders/Textures/MultiLut_Insurgency_Optimized.png

VALIDACAO
---------

O nucleo foi testado para leitura, alteracao, backup, restauracao, recusa de
perfil invalido e validacao do shader. As novas funcoes de treino (validacao
de rodadas, limite de historico, medias ponderadas e media movel) e a
normalizacao do crosshair tambem possuem testes automatizados (tests/test_aim.py).
A interface foi verificada estaticamente; o teste visual final precisa ser
realizado no seu ambiente GNOME/Wayland.
