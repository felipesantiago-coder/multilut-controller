MULTILUT INSURGENCY OPTIMIZED v1.8 COMPLETE-MAPS
================================================

Pacote competitivo para Insurgency (2014), ReShade FX e vkBasalt.

OBJETIVO
--------

- Melhorar a leitura de personagens e materiais sem detectar objetos.
- Recuperar sombras sem transformar preto em cinza.
- Preservar contornos, microcontraste e profundidade.
- Controlar céu, areia, paredes claras e neve sem estourar o branco.
- Evitar filtro sépia, dominante azul/roxa, cores lavadas e haze artificial.

ARQUIVOS
--------

Shaders/MultiLUT_Insurgency_Optimized.fx
Textures/MultiLut_Insurgency_Optimized.png
vkBasalt_MultiLUT_TEST.conf

O atlas mantém obrigatoriamente 1024 x 544 pixels:

- 32 fatias azuis por LUT;
- cada LUT mede 32 x 32 pixels por fatia;
- 17 linhas físicas de LUT;
- perfis adicionais podem reutilizar uma LUT-base e aplicar parâmetros tonais
  próprios. Isso não reduz a independência dos perfis selecionados no .fx.

COMO SELECIONAR UM PERFIL
-------------------------

Use preferencialmente o MultiLUT Controller. A alteração é aplicada ao arquivo
.fx e o vkBasalt recarrega o shader enquanto o jogo está aberto.

Para selecionar manualmente, altere somente esta linha no início do .fx:

  #define ACTIVE_LUT_PROFILE 14

Use um número inteiro entre 0 e 24. Não altere fLUT_LutSelector; ele representa
somente a linha física do atlas e é escolhido automaticamente pelo perfil.

PERFIS DE MAPA
--------------

 ID  MAPA         CARACTERÍSTICA PRINCIPAL
 --  -----------  -----------------------------------------------------------
  1  Buhriz       Céu/areia claros e sombras sob estruturas
  2  Contact      Paredes claras, fachadas e iluminação noturna/mista
  3  District     Ambiente urbano, fumaça e detalhes distantes
  4  Dry Canal    Haze quente, luz extrema e baixo contraste local
  5  Embassy      Concreto claro, pátios, céu e interiores
  6  Heights      Neve, lama, vegetação e construções
  7  Panj         Vegetação densa e iluminação baixa
  8  Sinjar       Relevo, estrada e longa distância desértica
  9  Station      Sombras profundas com céu/neve claros
 10  Verticality  Neve, ruas escuras, pinheiros e distância
 17  Market       Ruas, lojas, sacadas e interiores urbanos costeiros
 18  Ministry     Corredores e salas com concreto e iluminação mista
 19  Peak         Montanhas, árvores e combate de média/longa distância
 20  Revolt       Ruas claras, túneis e edifícios escuros
 21  Siege        Fachadas claras e sombras urbanas na variante diurna
 22  Tell         Sol forte, paredes quentes, becos e interiores densos
 23  Uprising     Ruas estreitas e combate urbano de curta distância
 24  Kandagal     Vale com haze, rio, vegetação, ponte e vila

PERFIS UTILITÁRIOS E COMPETITIVOS
---------------------------------

  0  Neutro / referência
     Desativa todo o tratamento para comparação direta.

 11  Interior muito escuro
     Recuperação máxima controlada para salas quase sem iluminação.

 12  Interior + exterior
     Para portas e janelas claras vistas de dentro de um ambiente escuro.

 13  Longa distância / pouco haze
     Microcontraste reforçado para alvos pequenos e materiais distantes.

 14  Competitivo neutro
     Perfil geral recomendado quando não quiser trocar por mapa.

 15  Recuperação competitiva
     Sombras profundas e interiores difíceis, mantendo preto ancorado.

 16  Alto contraste competitivo
     Separação tonal mais forte para cenas planas ou enevoadas.

MAPAS ADICIONADOS NA v1.8
-------------------------

Market, Ministry, Peak, Revolt, Siege, Tell, Uprising e Kandagal.

Esses mapas foram identificados nos arquivos finais do jogo e em registros
oficiais de lançamento/atualização. Os ajustes consideram o ambiente dominante,
a distância típica de combate, a alternância interior/exterior, o haze, o tipo
de material e o risco de clipping. Referências da internet podem conter
compressão diferente da saída local; por isso os valores foram mantidos
conservadores e protegidos contra preto cinza e branco estourado.

ARQUITETURA DOS NOVOS PERFIS
----------------------------

O número do perfil e a linha física da LUT não precisam ser iguais. A v1.8 usa
uma LUT-base ambiental e aplica parâmetros exclusivos de:

- recuperação de sombras comuns e profundas;
- separação de low-mid;
- contraste local limitado por luminância;
- saturação adaptativa;
- separação cromática sem rotação de matiz;
- ganho de iluminação protegido;
- compressão suave de highlights.

Mapeamento das novas LUTs-base:

- Market e Uprising: base District, por materiais urbanos e contraste local.
- Ministry: base Interior + Exterior, pela iluminação interna mista.
- Peak e Kandagal: base Longa Distância / Pouco Haze.
- Revolt: base Embassy, por concreto, ruas e interiores alternados.
- Siege: base Contact, pois compartilham a mesma família ambiental.
- Tell: base Buhriz, por areia, paredes quentes e luz intensa.

Cada mapa continua recebendo parâmetros diferentes; compartilhar a LUT-base não
significa compartilhar o resultado final.

RECOMENDAÇÕES
-------------

- Use o perfil específico do mapa durante os testes.
- Para uso geral, comece pelo perfil 14.
- Para interior extremamente escuro, teste 15 e depois 11.
- Para longa distância e haze, compare 13 com o perfil específico do mapa.
- Não combine inicialmente com outros efeitos de gamma, exposição, Levels,
  Curves, Tonemap, LiftGammaGain ou Vibrance.
- Caso outro shader altere a luminância antes do MultiLUT, o resultado pode
  ficar lavado mesmo com o perfil correto.

INSTALAÇÃO MANUAL
-----------------

1. Copie o .fx para:

   ~/.config/vkBasalt/reshade-shaders/Shaders/

2. Copie o .png para:

   ~/.config/vkBasalt/reshade-shaders/Textures/

3. Confirme no vkBasalt.conf:

   effects = MultiLUT
   MultiLUT = ~/.config/vkBasalt/reshade-shaders/Shaders/MultiLUT_Insurgency_Optimized.fx

4. Inicie o jogo com vkBasalt habilitado.

VALIDAÇÃO
---------

- Atlas: 1024 x 544, RGB, 17 linhas válidas.
- Perfil 0: bypass real, sem alteração oculta.
- Perfis 0 a 24: pré-processamento individual verificado.
- Novos perfis: IDs independentes e LUT-base limitada a 0..16.
- Controller: leitura, gravação atômica, backup e restauração testados.

HISTÓRICO RESUMIDO
------------------

v1.4  Removeu recuperação de sombras duplicada e o véu cinza.
v1.5  Removeu deslocamentos fixos de temperatura e o filtro sépia.
v1.6  Reforçou separação de cores e iluminação protegida para neve.
v1.7  Ancorou o preto e limitou a recuperação agressiva das sombras.
v1.8  Adicionou oito mapas ausentes e desacoplou perfil lógico da linha física
      do atlas, preservando integralmente a geometria 1024 x 544.
