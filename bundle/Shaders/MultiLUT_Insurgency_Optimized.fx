// MultiLUT optimized for Insurgency (2014) + vkBasalt - v1.8 Complete-Maps
// Atlas layout: 32 blue slices x 17 LUT rows, 32x32 pixels per slice.
// Derived from the Multi-LUT shader by Otis / Infuse Project, itself based on
// Marty's LUT shader 1.0 for ReShade 3.0 (Copyright 2008-2016 Marty McFly).

#ifndef fLUT_TextureName
    #define fLUT_TextureName "MultiLut_Insurgency_Optimized.png"
#endif
#ifndef fLUT_TileSizeXY
    #define fLUT_TileSizeXY 32
#endif
#ifndef fLUT_TileAmount
    #define fLUT_TileAmount 32
#endif
#ifndef fLUT_LutAmount
    #define fLUT_LutAmount 17
#endif

// ============================================================================
// SELETOR FACIL — ESTA E A UNICA LINHA QUE VOCE PRECISA ALTERAR
// ============================================================================
//
// Troque somente o numero 14 abaixo por um numero entre 0 e 24.
// Nao descomente outras linhas e nao e necessario trocar o arquivo PNG.
// O shader ativa apenas a LUT escolhida e aplica automaticamente os valores
// recomendados de sombras, contraste, saturacao e protecao de highlights.
//
// PERFIS DISPONIVEIS
//
//  0 = NEUTRAL / REFERENCE
//      Imagem neutra, sem tratamento. Use para comparacao e diagnostico.
//
//  1 = BUHRIZ
//      Protege ceu e areia claros, mantendo detalhe sob a ponte e no terreno.
//
//  2 = CONTACT
//      Controla paredes claras e sol forte, preservando veiculos e fachadas.
//
//  3 = DISTRICT
//      Aumenta separacao de predios, fumaca, ruas e detalhes urbanos distantes.
//
//  4 = DRY CANAL
//      Reduz haze quente e clipping, recuperando contraste sob luz extrema.
//
//  5 = EMBASSY
//      Equilibra concreto claro, ceu e sombras com neutralizacao moderada.
//
//  6 = HEIGHTS
//      Preserva neve clara e separa terra, construcoes e vegetacao sem cinza.
//
//  7 = PANJ
//      Recupera o mapa escuro e vegetado sem destruir atmosfera ou pretos.
//
//  8 = SINJAR
//      Maximiza longa distancia, relevo e estrada sob iluminacao desertica.
//
//  9 = STATION
//      Trata simultaneamente sombras profundas e ceu/neve muito claros.
//
// 10 = VERTICALITY
//      Recupera ruas escuras e preserva neve, ceu, pinheiros e longa distancia.
//
// 11 = UNIVERSAL DARK INTERIOR
//      Perfil utilitario para qualquer interior extremamente escuro.
//
// 12 = MIXED INTERIOR / EXTERIOR
//      Para portas e janelas claras vistas a partir de um ambiente escuro.
//
// 13 = LONG RANGE / LOW HAZE
//      Perfil utilitario de alcance, microcontraste e reducao de haze.
//
// 14 = COMPETITIVE NEUTRAL  [RECOMENDADO PARA USO GERAL]
//      Equilibrio entre naturalidade, visibilidade e contraste.
//
// 15 = COMPETITIVE SHADOW RECOVERY  [INTERIORES MAIS ESCUROS]
//      Maxima visibilidade competitiva em sombras e ambientes internos.
//
// 16 = COMPETITIVE HIGH CONTRAST
//      Separacao tonal mais forte, indicada para cenas planas ou enevoadas.
//
// 17 = MARKET
//      Equilibra ruas, lojas, sacadas e interiores urbanos costeiros.
//
// 18 = MINISTRY
//      Recupera corredores e salas sem achatar concreto ou portas iluminadas.
//
// 19 = PEAK
//      Aumenta leitura de relevo, vegetacao e alvos em media/longa distancia.
//
// 20 = REVOLT
//      Controla a alternancia entre ruas claras, tuneis e predios escuros.
//
// 21 = SIEGE
//      Ajuste diurno para fachadas claras, ruas expostas e sombras urbanas.
//
// 22 = TELL
//      Protege sol e paredes quentes, recuperando becos e interiores densos.
//
// 23 = UPRISING
//      Reforca separacao em combate urbano curto sem criar camada cinza.
//
// 24 = KANDAGAL
//      Reduz haze no vale e preserva rio, vegetacao, cidade e longa distancia.
//
#ifndef ACTIVE_LUT_PROFILE
    #define ACTIVE_LUT_PROFILE 14
#endif

// ============================================================================
// PRESETS AUTOMATICOS — NAO E NECESSARIO ALTERAR ESTA PARTE
// ============================================================================
// Cada bloco define: chroma, luminancia, sombras, sombras profundas, low-mid,
// contraste local, raio, saturacao adaptativa, separacao cromatica, ganho de
// iluminacao protegido e protecao de highlights.

// O atlas continua fisicamente limitado a 17 linhas. Perfis adicionais usam
// a LUT-base ambiental mais proxima e recebem parametros tonais exclusivos.
#if ACTIVE_LUT_PROFILE == 17
    #define P_LUT_ROW 3
#elif ACTIVE_LUT_PROFILE == 18
    #define P_LUT_ROW 12
#elif ACTIVE_LUT_PROFILE == 19
    #define P_LUT_ROW 13
#elif ACTIVE_LUT_PROFILE == 20
    #define P_LUT_ROW 5
#elif ACTIVE_LUT_PROFILE == 21
    #define P_LUT_ROW 2
#elif ACTIVE_LUT_PROFILE == 22
    #define P_LUT_ROW 1
#elif ACTIVE_LUT_PROFILE == 23
    #define P_LUT_ROW 3
#elif ACTIVE_LUT_PROFILE == 24
    #define P_LUT_ROW 13
#else
    #define P_LUT_ROW ACTIVE_LUT_PROFILE
#endif

#if ACTIVE_LUT_PROFILE == 0
    #define P_CHROMA     0.00
    #define P_LUMA       0.00
    #define P_SHADOW     0.00
    #define P_DEEP       0.00
    #define P_LOWMID     0.00
    #define P_LOCAL      0.00
    #define P_RADIUS     1.00
    #define P_SAT        0.000
    #define P_HIGHLIGHT  0.00
    #define P_BRIGHT     0.00
    #define P_SEP        0.00
#elif ACTIVE_LUT_PROFILE == 1
    #define P_CHROMA     0.78
    #define P_LUMA       0.92
    #define P_SHADOW     0.14
    #define P_DEEP       0.14
    #define P_LOWMID     0.28
    #define P_LOCAL      0.28
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.52
    #define P_BRIGHT     0.00
    #define P_SEP        0.10
#elif ACTIVE_LUT_PROFILE == 2
    #define P_CHROMA     0.74
    #define P_LUMA       0.94
    #define P_SHADOW     0.12
    #define P_DEEP       0.12
    #define P_LOWMID     0.28
    #define P_LOCAL      0.27
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.64
    #define P_BRIGHT     0.00
    #define P_SEP        0.10
#elif ACTIVE_LUT_PROFILE == 3
    #define P_CHROMA     0.80
    #define P_LUMA       0.94
    #define P_SHADOW     0.28
    #define P_DEEP       0.32
    #define P_LOWMID     0.32
    #define P_LOCAL      0.30
    #define P_RADIUS     1.00
    #define P_SAT        0.070
    #define P_HIGHLIGHT  0.36
    #define P_BRIGHT     0.00
    #define P_SEP        0.12
#elif ACTIVE_LUT_PROFILE == 4
    #define P_CHROMA     0.68
    #define P_LUMA       0.96
    #define P_SHADOW     0.08
    #define P_DEEP       0.08
    #define P_LOWMID     0.32
    #define P_LOCAL      0.31
    #define P_RADIUS     1.00
    #define P_SAT        0.045
    #define P_HIGHLIGHT  0.68
    #define P_BRIGHT     0.00
    #define P_SEP        0.11
#elif ACTIVE_LUT_PROFILE == 5
    #define P_CHROMA     0.78
    #define P_LUMA       0.92
    #define P_SHADOW     0.26
    #define P_DEEP       0.30
    #define P_LOWMID     0.28
    #define P_LOCAL      0.27
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.42
    #define P_BRIGHT     0.00
    #define P_SEP        0.11
#elif ACTIVE_LUT_PROFILE == 6
    #define P_CHROMA     0.72
    #define P_LUMA       0.94
    #define P_SHADOW     0.30
    #define P_DEEP       0.38
    #define P_LOWMID     0.30
    #define P_LOCAL      0.30
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.56
    #define P_BRIGHT     0.34
    #define P_SEP        0.12
#elif ACTIVE_LUT_PROFILE == 7
    #define P_CHROMA     0.72
    #define P_LUMA       0.94
    #define P_SHADOW     0.44
    #define P_DEEP       0.56
    #define P_LOWMID     0.38
    #define P_LOCAL      0.33
    #define P_RADIUS     1.00
    #define P_SAT        0.075
    #define P_HIGHLIGHT  0.18
    #define P_BRIGHT     0.00
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 8
    #define P_CHROMA     0.70
    #define P_LUMA       0.95
    #define P_SHADOW     0.08
    #define P_DEEP       0.10
    #define P_LOWMID     0.30
    #define P_LOCAL      0.31
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.62
    #define P_BRIGHT     0.00
    #define P_SEP        0.11
#elif ACTIVE_LUT_PROFILE == 9
    #define P_CHROMA     0.72
    #define P_LUMA       0.94
    #define P_SHADOW     0.46
    #define P_DEEP       0.58
    #define P_LOWMID     0.36
    #define P_LOCAL      0.32
    #define P_RADIUS     1.00
    #define P_SAT        0.075
    #define P_HIGHLIGHT  0.56
    #define P_BRIGHT     0.26
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 10
    #define P_CHROMA     0.72
    #define P_LUMA       0.94
    #define P_SHADOW     0.40
    #define P_DEEP       0.55
    #define P_LOWMID     0.34
    #define P_LOCAL      0.31
    #define P_RADIUS     1.00
    #define P_SAT        0.075
    #define P_HIGHLIGHT  0.62
    #define P_BRIGHT     0.38
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 11
    #define P_CHROMA     0.68
    #define P_LUMA       0.94
    #define P_SHADOW     0.60
    #define P_DEEP       0.75
    #define P_LOWMID     0.36
    #define P_LOCAL      0.28
    #define P_RADIUS     1.00
    #define P_SAT        0.100
    #define P_HIGHLIGHT  0.28
    #define P_BRIGHT     0.00
    #define P_SEP        0.14
#elif ACTIVE_LUT_PROFILE == 12
    #define P_CHROMA     0.72
    #define P_LUMA       0.94
    #define P_SHADOW     0.45
    #define P_DEEP       0.58
    #define P_LOWMID     0.34
    #define P_LOCAL      0.30
    #define P_RADIUS     1.00
    #define P_SAT        0.085
    #define P_HIGHLIGHT  0.64
    #define P_BRIGHT     0.00
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 13
    #define P_CHROMA     0.68
    #define P_LUMA       0.96
    #define P_SHADOW     0.10
    #define P_DEEP       0.12
    #define P_LOWMID     0.32
    #define P_LOCAL      0.34
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.56
    #define P_BRIGHT     0.00
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 14
    #define P_CHROMA     0.80
    #define P_LUMA       0.92
    #define P_SHADOW     0.34
    #define P_DEEP       0.48
    #define P_LOWMID     0.28
    #define P_LOCAL      0.28
    #define P_RADIUS     1.00
    #define P_SAT        0.070
    #define P_HIGHLIGHT  0.34
    #define P_BRIGHT     0.00
    #define P_SEP        0.12
#elif ACTIVE_LUT_PROFILE == 15
    #define P_CHROMA     0.68
    #define P_LUMA       0.94
    #define P_SHADOW     0.58
    #define P_DEEP       0.72
    #define P_LOWMID     0.34
    #define P_LOCAL      0.27
    #define P_RADIUS     1.00
    #define P_SAT        0.105
    #define P_HIGHLIGHT  0.18
    #define P_BRIGHT     0.00
    #define P_SEP        0.14
#elif ACTIVE_LUT_PROFILE == 16
    #define P_CHROMA     0.72
    #define P_LUMA       0.96
    #define P_SHADOW     0.24
    #define P_DEEP       0.36
    #define P_LOWMID     0.34
    #define P_LOCAL      0.36
    #define P_RADIUS     1.00
    #define P_SAT        0.075
    #define P_HIGHLIGHT  0.42
    #define P_BRIGHT     0.00
    #define P_SEP        0.15
#elif ACTIVE_LUT_PROFILE == 17
    #define P_CHROMA     0.76
    #define P_LUMA       0.95
    #define P_SHADOW     0.34
    #define P_DEEP       0.46
    #define P_LOWMID     0.33
    #define P_LOCAL      0.33
    #define P_RADIUS     1.00
    #define P_SAT        0.065
    #define P_HIGHLIGHT  0.46
    #define P_BRIGHT     0.00
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 18
    #define P_CHROMA     0.70
    #define P_LUMA       0.94
    #define P_SHADOW     0.52
    #define P_DEEP       0.66
    #define P_LOWMID     0.35
    #define P_LOCAL      0.32
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.50
    #define P_BRIGHT     0.06
    #define P_SEP        0.13
#elif ACTIVE_LUT_PROFILE == 19
    #define P_CHROMA     0.70
    #define P_LUMA       0.96
    #define P_SHADOW     0.18
    #define P_DEEP       0.24
    #define P_LOWMID     0.35
    #define P_LOCAL      0.37
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.58
    #define P_BRIGHT     0.00
    #define P_SEP        0.15
#elif ACTIVE_LUT_PROFILE == 20
    #define P_CHROMA     0.74
    #define P_LUMA       0.95
    #define P_SHADOW     0.40
    #define P_DEEP       0.52
    #define P_LOWMID     0.35
    #define P_LOCAL      0.34
    #define P_RADIUS     1.00
    #define P_SAT        0.065
    #define P_HIGHLIGHT  0.50
    #define P_BRIGHT     0.00
    #define P_SEP        0.14
#elif ACTIVE_LUT_PROFILE == 21
    #define P_CHROMA     0.72
    #define P_LUMA       0.95
    #define P_SHADOW     0.25
    #define P_DEEP       0.34
    #define P_LOWMID     0.31
    #define P_LOCAL      0.32
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.58
    #define P_BRIGHT     0.00
    #define P_SEP        0.12
#elif ACTIVE_LUT_PROFILE == 22
    #define P_CHROMA     0.70
    #define P_LUMA       0.96
    #define P_SHADOW     0.43
    #define P_DEEP       0.56
    #define P_LOWMID     0.35
    #define P_LOCAL      0.35
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.62
    #define P_BRIGHT     0.00
    #define P_SEP        0.14
#elif ACTIVE_LUT_PROFILE == 23
    #define P_CHROMA     0.74
    #define P_LUMA       0.95
    #define P_SHADOW     0.40
    #define P_DEEP       0.52
    #define P_LOWMID     0.35
    #define P_LOCAL      0.35
    #define P_RADIUS     1.00
    #define P_SAT        0.060
    #define P_HIGHLIGHT  0.48
    #define P_BRIGHT     0.00
    #define P_SEP        0.14
#elif ACTIVE_LUT_PROFILE == 24
    #define P_CHROMA     0.68
    #define P_LUMA       0.96
    #define P_SHADOW     0.25
    #define P_DEEP       0.34
    #define P_LOWMID     0.38
    #define P_LOCAL      0.38
    #define P_RADIUS     1.00
    #define P_SAT        0.055
    #define P_HIGHLIGHT  0.60
    #define P_BRIGHT     0.00
    #define P_SEP        0.15
#else
    #error ACTIVE_LUT_PROFILE deve usar um numero inteiro entre 0 e 24
#endif

#include "ReShadeUI.fxh"

uniform int fLUT_LutSelector <
    ui_type = "combo";
    ui_items = "Neutral / Reference\0Buhriz\0Contact\0District\0Dry Canal\0Embassy\0Heights\0Panj\0Sinjar\0Station\0Verticality\0Universal Dark Interior\0Mixed Interior / Exterior\0Long Range / Low Haze\0Competitive Neutral\0Competitive Shadow Recovery\0Competitive High Contrast\0";
    ui_label = "LUT base (advanced)";
    ui_tooltip = "Atlas row selected automatically by ACTIVE_LUT_PROFILE.";
> = P_LUT_ROW;

uniform float fLUT_AmountChroma < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "LUT chroma amount";
    ui_tooltip = "Blends LUT chroma independently from luminance.";
> = P_CHROMA;

uniform float fLUT_AmountLuma < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "LUT luma amount";
    ui_tooltip = "Blends LUT luminance independently from chroma.";
> = P_LUMA;

uniform float fLUT_ShadowRecovery < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "Selective shadow recovery";
    ui_tooltip = "Recovers shadow information without globally lifting black.";
> = P_SHADOW;

uniform float fLUT_DeepShadowRecovery < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "Deep-shadow visibility";
    ui_tooltip = "Stronger toe recovery for extremely dark interiors; black remains anchored.";
> = P_DEEP;

uniform float fLUT_LowMidSeparation < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "Low-mid separation";
    ui_tooltip = "Restores depth after shadow recovery.";
> = P_LOWMID;

uniform float fLUT_LocalContrast < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "Local contrast";
    ui_tooltip = "Edge-limited local luminance contrast; this is not sharpening.";
> = P_LOCAL;

uniform float fLUT_LocalRadius < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.50; ui_max = 2.00;
    ui_label = "Local contrast radius";
    ui_tooltip = "Sampling radius in screen pixels.";
> = P_RADIUS;

uniform float fLUT_AdaptiveSaturation < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 0.20;
    ui_label = "Adaptive saturation";
    ui_tooltip = "Adds restrained saturation mainly to midtones.";
> = P_SAT;

uniform float fLUT_HighlightProtection < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 1.00;
    ui_label = "Highlight protection";
    ui_tooltip = "Softly protects bright sky, snow, sand and walls.";
> = P_HIGHLIGHT;

uniform float fLUT_SceneBrightness < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 0.50;
    ui_label = "Protected scene brightness";
    ui_tooltip = "Raises dark and middle values while excluding snow-white highlights.";
> = P_BRIGHT;

uniform float fLUT_ColorSeparation < __UNIFORM_SLIDER_FLOAT1
    ui_min = 0.00; ui_max = 0.30;
    ui_label = "Hue-preserving color separation";
    ui_tooltip = "Separates adjacent colors without shifting hue or white balance.";
> = P_SEP;

#include "ReShade.fxh"

texture texMultiLUT <
    source = fLUT_TextureName;
> {
    Width = fLUT_TileSizeXY * fLUT_TileAmount;
    Height = fLUT_TileSizeXY * fLUT_LutAmount;
    Format = RGBA8;
};

sampler SamplerMultiLUT
{
    Texture = texMultiLUT;
    MinFilter = LINEAR;
    MagFilter = LINEAR;
    MipFilter = LINEAR;
    AddressU = CLAMP;
    AddressV = CLAMP;
};

static const float3 kLuma = float3(0.2126, 0.7152, 0.0722);
static const float kEpsilon = 0.0001;

float Luma709(float3 color)
{
    return dot(color, kLuma);
}

float RecoverLuma(float luma)
{
    // The black gate keeps encoded/true black anchored. A square-root toe then
    // recovers useful information from the extremely compressed 0.2%-8% range.
    // It fades well before midtones, so bright doors, sky, snow and sand are
    // unaffected by this stronger interior treatment.
    float deepBlackGate = smoothstep(0.002, 0.018, luma);
    float deepShadowMask = 1.0 - smoothstep(0.075, 0.34, luma);
    float deepRecovery = fLUT_DeepShadowRecovery * 0.30 * sqrt(max(luma, 0.0)) *
                         deepBlackGate * deepShadowMask;

    // The original selective stage remains responsible for ordinary shadows.
    float blackGate = smoothstep(0.006, 0.060, luma);
    float shadowMask = 1.0 - smoothstep(0.10, 0.52, luma);
    float recovery = fLUT_ShadowRecovery * 0.115 * blackGate * shadowMask;
    return min(luma + deepRecovery + recovery, 1.0);
}

float3 SetLumaStable(float3 color, float oldLuma, float newLuma)
{
    // Multiplicative reconstruction preserves hue. Near black, the blend moves
    // toward neutral luminance to avoid amplifying chromatic noise.
    float safeLuma = max(oldLuma, kEpsilon);
    float3 scaled = color * (newLuma / safeLuma);
    float chromaConfidence = smoothstep(0.006, 0.050, oldLuma);
    float3 neutral = newLuma.xxx;
    return lerp(neutral, scaled, chromaConfidence);
}

float3 ApplyShadowAndLowMid(float3 color)
{
    float sourceLuma = Luma709(color);
    float recoveredLuma = RecoverLuma(sourceLuma);

    // A bounded S-shaped low-mid term prevents recovered shadows from becoming
    // a flat gray layer. It is zero at black and fades before highlights.
    float lowMidWindow = smoothstep(0.045, 0.20, recoveredLuma) *
                         (1.0 - smoothstep(0.54, 0.78, recoveredLuma));
    float separation = (recoveredLuma - 0.30) * 0.16 *
                       fLUT_LowMidSeparation * lowMidWindow;
    float targetLuma = saturate(recoveredLuma + separation);
    return saturate(SetLumaStable(color, sourceLuma, targetLuma));
}

float3 ApplyProtectedBrightness(float3 color)
{
    float sourceLuma = Luma709(color);
    float blackGate = smoothstep(0.006, 0.035, sourceLuma);
    float whiteExclusion = 1.0 - smoothstep(0.58, 0.86, sourceLuma);
    float lift = fLUT_SceneBrightness * 0.18 * blackGate * whiteExclusion *
                 (1.0 - sourceLuma);
    float targetLuma = min(sourceLuma + lift, 1.0);
    return saturate(SetLumaStable(color, sourceLuma, targetLuma));
}

float3 SampleMultiLUT(float3 color)
{
    color = saturate(color);

    float blue = color.b * (fLUT_TileAmount - 1.0);
    float slice0 = floor(blue);
    float slice1 = min(slice0 + 1.0, fLUT_TileAmount - 1.0);
    float blueBlend = frac(blue);

    float atlasWidth = fLUT_TileSizeXY * fLUT_TileAmount;
    float atlasHeight = fLUT_TileSizeXY * fLUT_LutAmount;
    float row = clamp(float(fLUT_LutSelector), 0.0, fLUT_LutAmount - 1.0);

    float xInTile = color.r * (fLUT_TileSizeXY - 1.0) + 0.5;
    float yInTile = color.g * (fLUT_TileSizeXY - 1.0) + 0.5;
    float2 uv0 = float2((slice0 * fLUT_TileSizeXY + xInTile) / atlasWidth,
                        (row * fLUT_TileSizeXY + yInTile) / atlasHeight);
    float2 uv1 = float2((slice1 * fLUT_TileSizeXY + xInTile) / atlasWidth,
                        (row * fLUT_TileSizeXY + yInTile) / atlasHeight);

    return lerp(tex2D(SamplerMultiLUT, uv0).rgb,
                tex2D(SamplerMultiLUT, uv1).rgb, blueBlend);
}

float3 BlendLumaChroma(float3 source, float3 graded)
{
    float sourceLuma = Luma709(source);
    float gradedLuma = Luma709(graded);
    float targetLuma = lerp(sourceLuma, gradedLuma, fLUT_AmountLuma);

    // Chroma ratios are bounded and confidence-gated near black. This replaces
    // normalize()/length(), eliminating the unstable near-black direction.
    float3 sourceRatio = (source - sourceLuma.xxx) / max(sourceLuma, 0.025);
    float3 gradedRatio = (graded - gradedLuma.xxx) / max(gradedLuma, 0.025);
    sourceRatio = clamp(sourceRatio, -1.75, 1.75);
    gradedRatio = clamp(gradedRatio, -1.75, 1.75);

    // The LUT chroma fades at encoded near-black and extreme highlights, but
    // source chroma is retained instead of being replaced by neutral gray.
    float lutChromaConfidence = smoothstep(0.008, 0.060, targetLuma) *
                                (1.0 - smoothstep(0.96, 1.0, targetLuma));
    float3 ratio = lerp(sourceRatio, gradedRatio,
                        fLUT_AmountChroma * lutChromaConfidence);
    return saturate(targetLuma.xxx + ratio * targetLuma);
}

float RecoveredNeighborLuma(float2 uv)
{
    float y = Luma709(tex2D(ReShade::BackBuffer, uv).rgb);
    return RecoverLuma(y);
}

void PS_MultiLUT_Apply(float4 vpos : SV_Position, float2 texcoord : TEXCOORD,
                       out float4 res : SV_Target0)
{
    float3 original = saturate(tex2D(ReShade::BackBuffer, texcoord).rgb);

    // Profile 0 is a true reference bypass. No hidden shadow desaturation or
    // highlight neutralization is allowed in the comparison profile.
    if (ACTIVE_LUT_PROFILE == 0)
    {
        res = float4(original, 1.0);
        return;
    }

    float3 prepared = ApplyShadowAndLowMid(original);
    prepared = ApplyProtectedBrightness(prepared);
    float3 lutColor = SampleMultiLUT(prepared);
    float3 color = BlendLumaChroma(prepared, lutColor);

    // Four inexpensive taps estimate local luminance. The bounded detail term
    // acts only from shadows through midtones and does not create outlines.
    float2 stepUV = ReShade::PixelSize * fLUT_LocalRadius;
    float localAverage = 0.25 * (
        RecoveredNeighborLuma(texcoord + float2(stepUV.x, 0.0)) +
        RecoveredNeighborLuma(texcoord - float2(stepUV.x, 0.0)) +
        RecoveredNeighborLuma(texcoord + float2(0.0, stepUV.y)) +
        RecoveredNeighborLuma(texcoord - float2(0.0, stepUV.y)));
    float currentLuma = Luma709(color);
    float detail = clamp(currentLuma - localAverage, -0.055, 0.055);
    float detailWindow = smoothstep(0.035, 0.18, currentLuma) *
                         (1.0 - smoothstep(0.76, 0.94, currentLuma));
    color = saturate(color + (detail * fLUT_LocalContrast *
                              detailWindow).xxx);

    // Perceptual color-density restoration. It begins inside useful shadows
    // so recovered interiors do not become gray, then fades before clipping.
    currentLuma = Luma709(color);
    float saturationWindow = smoothstep(0.018, 0.12, currentLuma) *
                             (1.0 - smoothstep(0.82, 0.99, currentLuma));
    color = currentLuma.xxx + (color - currentLuma.xxx) *
            (1.0 + fLUT_AdaptiveSaturation * saturationWindow);

    // Expands the distance between nearby colors without rotating their hue.
    // Near-neutrals, encoded black and almost-white snow remain protected.
    currentLuma = Luma709(color);
    float3 chromaVector = color - currentLuma.xxx;
    float chromaMagnitude = length(chromaVector);
    float chromaWindow = smoothstep(0.012, 0.090, chromaMagnitude) *
                         (1.0 - smoothstep(0.38, 0.62, chromaMagnitude));
    float colorRangeWindow = smoothstep(0.020, 0.10, currentLuma) *
                             (1.0 - smoothstep(0.86, 0.99, currentLuma));
    color = currentLuma.xxx + chromaVector *
            (1.0 + fLUT_ColorSeparation * chromaWindow * colorRangeWindow);

    // Soft luminance-domain highlight compression preserves hue and avoids
    // hard clipping. The effect starts high enough to leave midtones intact.
    currentLuma = Luma709(color);
    float highlightMask = smoothstep(0.72, 1.0, currentLuma);
    float protectedLuma = currentLuma - fLUT_HighlightProtection * 0.085 *
                          highlightMask * (currentLuma - 0.72) / 0.28;
    color = SetLumaStable(color, currentLuma, max(protectedLuma, 0.0));

    res = float4(saturate(color), 1.0);
}

technique MultiLUT
{
    pass MultiLUT_Apply
    {
        VertexShader = PostProcessVS;
        PixelShader = PS_MultiLUT_Apply;
    }
}
