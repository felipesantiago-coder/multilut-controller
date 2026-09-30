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

Shader padrao:
  ~/.config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx

Atlas padrao:
  ~/.config/vkBasalt/reshade-shaders/Textures/MultiLut_Insurgency_Optimized.png

VALIDACAO
---------

O nucleo foi testado para leitura, alteracao, backup, restauracao, recusa de
perfil invalido, validacao do shader, ordenacao alfabetica dos perfis e as
duas secoes da lista (tests/test_core.py). A interface foi verificada
estaticamente; o teste visual final precisa ser realizado no seu ambiente
GNOME/Wayland.
