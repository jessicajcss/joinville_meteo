# Tratamento de dados — Painel Meteorológico de Joinville (LaCiA)

Documento de rastreabilidade. Descreve, plot a plot, todo o tratamento aplicado
aos dados brutos até o que é exibido. Todos os scripts citados estão em `scripts/`
e são reexecutados automaticamente pela GitHub Action a cada envio de dados.

Princípio geral: nada é inventado. Onde há agregação, filtro ou controle de
qualidade (CQ), o critério é explícito e reprodutível.

---

## 0. Camada comum — do bruto às séries "master" (`toa5.py`, `build_hourly_daily.py`)

Todas as páginas partem das séries consolidadas por estação em `data/hourly/*.parquet`
(horária) e `data/daily/*.parquet` (diária), geradas assim:

- **Origem**: produtos nativos dos registradores (planilhas `*_HR` e `*_DIARIA`
  2011–2026 + arquivos `.dat` recentes). Nada derivado no lugar de valor medido.
- **Limpeza de sentinelas**: remoção de `-100`, `NAN`, `-6999`; carimbos de tempo
  anteriores a 2010-01-01 descartados.
- **CQ de faixa física (limites rígidos)** por variável — valores fora são
  descartados: temperatura −10…50 °C; umidade 0…100 %; precipitação 0…500 mm (1º passe);
  vento 0…100 m/s; rajada 0…120; direção 0…360°; radiação 0…1600 W/m²;
  pressão 800…1050 hPa; ponto de orvalho −10…40 °C; nível −50…5000 m.
- **CQ de chuva — código em polegadas / teto físico / despejo de acúmulo** (`rain_qc.py`,
  aplicado ao final de `build_hourly_daily.py` e `update_datasets.py`, sobre toda a rede):
  - *Diagnóstico*: as básculas são **em polegadas** (resolução 0,254 mm = 0,01 in). O
    código de falha do registrador surge como **valor exato em polegadas** no campo de
    chuva — `254,0 mm = 10 in` aparece **1.092×** (99,9º e 99,99º percentis ambos exatamente
    254,0: assinatura de sentinela, não de chuva) e `228,6 mm = 9 in` 6×. Os múltiplos
    baixos (25,4 e 50,8 mm) **são mantidos** (totais reais plausíveis).
  - *Regra (sinaliza, não apaga)*: `inch_code` (254,0/228,6) → marcado; `ceiling`
    (> 150 mm h⁻¹ ou > 350 mm d⁻¹) → marcado — há uma **lacuna vazia** nos dados entre
    valores de tempestade críveis (≤ ~115 mm h⁻¹) e uma prateleira de instrumento
    (≥ ~229 mm h⁻¹, quase toda de uma estação); `gap_dump` (valor ≥ 40 mm na hora após
    uma lacuna > 2 h = chuva de várias horas num só balde) → marcado.
  - *Efeito*: **1.236 pontos** (~0,14 %) viram **NaN** (ausente, não zero). Cada ponto
    removido é registrado em `data/processed/rain_qc_flags.csv` (trilha de auditoria; o
    arquivo bruto de origem permanece intocado). Corrige ~20,5 mil mm de chuva espúria
    em 41 estação-meses (ex.: udesc mai/2025 1.721 → 114 mm; meses inteiros só de
    sentinela → 0). Máx. horário retido por estação: 48–115 mm/h (todos físicos).
- **Deduplicação** por carimbo de tempo (linha nativa e mais completa preferida).
- **Diárias**: extremos/totais nativos (Tmax, Tmin, URmax/min, chuva, radiação,
  rajada). **Médias diárias** (temp_mean, umid_mean, ws_mean, pressure_mean,
  solar_mean) = média aritmética das horas do dia; `n_hours` registra quantas horas
  contribuíram (permite filtrar dias parciais). Vento em m/s, hora local.

---

## 1. Página **Agora** (`index.html` ← `build_site_data.py`)

Valores "de agora" derivados da observação **horária mais recente por estação e por
variável** (a cobertura difere entre variáveis; uma estação pode ter vento novo e
temperatura antiga).

- **"Online"/atual**: uma leitura é considerada fresca se está a ≤ 8 dias da
  observação mais nova da rede (dados enviados ~semanalmente).
- **Balões/condições por estação**: último valor válido de temp, umidade, sensação
  (heat index nativo), vento (ws/wd), chuva.
- **Agregados da rede**: temp/vento/umidade/sensação = **média aritmética apenas das
  estações online**.
- **Chuva 24 h** = soma de precipitação nas 24 h que terminam na última observação de
  chuva da estação; **taxa** = precipitação da última hora (mm/h).
- **Linha de vento (24 h)** = média horária de ws entre as estações que reportam cada
  hora.
- **Faixa de temperatura diária (20 dias)** = média, entre estações, de Tmax e Tmin
  diárias.
- **Rosa dos ventos** = 16 setores de direção × 5 classes de velocidade, frequência
  (%) das horas dos últimos 12 meses (estilo *openair*).
- **Alerta** = orientado a dados, com as classes de intensidade de chuva da OMM
  (mm/h: leve < 2,5; moderada 2,5–10; forte 10–50; violenta ≥ 50). Ativa em chuva
  "forte"+ ou temperatura ≥ 35/≤ 5 °C (limiares de temperatura marcados como
  provisórios até definição local).

---

## 2. Página **Cidade** e **Cidade · Temperatura × Chuva** (`cidade*.html` ← `build_city_history.py`)

Variáveis contínuas (temperatura, umidade, radiação, vento):
- Valor diário da **rede** = média, entre todas as estações que reportam no dia, da
  média diária da estação.
- Mensal = média dos valores diários (mês com < 10 dias válidos → cinza/nulo).
- Anual = média das mensais (ano com < 6 meses → nulo). Climatologia = média de longo
  prazo por mês-calendário.

Chuva (climatologia): usa a **série combinada de pluviômetros** (ver §5), **não** os
sensores de chuva das estações meteorológicas.
- Mensal = **soma**, exigindo ≥ 20 dias válidos; anual = soma (≥ 6 meses);
  climatologia = média do total mensal.
- Histórias de chuva: "dia chuvoso" = ≥ 1 mm; dia mais chuvoso, top-5 dias, dias
  chuvosos por ano (anos com ≥ 330 dias de cobertura).
- Referência: ~2.130 mm/ano (média de 42 postos desde 1950; De Mello, 2020).

**Direção predominante do vento (item 6 — resultante vetorial de Grange).** A direção
não pode ser promediada aritmeticamente (descontinuidade 0°/360°). Cada observação
horária vira um vetor `u = −vel·sen θ`, `v = −vel·cos θ` (θ = direção meteorológica,
de onde o vento vem); os vetores são promediados e a direção resultante é
`Θ = atan2(ū, v̄) + 180°`, com o módulo da resultante `|R| = √(ū² + v̄²)` — método de
**Grange, S. K. (2014), _Technical note: Averaging wind speeds and directions_,
University of Auckland** (o mesmo do pacote R `openair`). A combinação **entre estações**
é feita com **peso igual por estação** (média dos vetores médios de cada estação), para
que um registro litorâneo mais longo não domine o valor municipal. A **cor** das faixas
codifica a **predominância** = % das horas dentro do octante (±22,5°) da resultante — é
uma **frequência**, não uma grandeza de Grange. O **rótulo** (ex.: S, L, SO) é a direção
meteorológica **de onde** o vento vem; a **seta** mostra o **sentido do fluxo** — para onde
o vento vai (o oposto do rótulo): vento de sul → seta para o norte. QC idêntico ao da rosa
da página Agora: exclui
calmaria (vel < 0,5 m/s) e o sentinela de cata-vento travado (exatamente 0,000°), e
descarta estações com > 25 % das horas com vento cravadas em 0°. Requer ≥ 2 estações e
≥ 50 horas por grupo (mês-calendário ou ano). O estimador anterior — o setor de 22,5°
**mais frequente** (moda) — foi substituído por ser ruidoso na rosa quase plana de
Joinville e por **esconder o ciclo sazonal**. A resultante o recupera: verão de **L/ESE**
(brisa marítima da Baía da Babitonga); outono–inverno (abr–jul, pico mai–jun) girando
para **S/SO** (ar polar pós-frontal). A constância direcional `|R|/velocidade escalar`
é baixa (0,10–0,27), sinalizando que a resultante é uma **tendência média**, não uma
direção fixa.

---

## 3. Página **Risco Hidro-climático** (`risco.html` ← `build_disasters.py`)

Registro de ocorrências da SEPROT/Defesa Civil (tabela duplamente codificada em CSV,
desembrulhada no script).
- **Filtro por tipo**: mantém apenas eventos **hidro-climáticos** (Enxurrada,
  Vendaval, Alagamentos, Inundação, Granizo, Chuvas Intensas, Erosão de Margem,
  Movimento de Massa, Tempestade…); saúde/estrutural/tecnológico são excluídos.
- Data convertida do português; desabrigados extraídos; situação normalizada
  (Normalidade/Emergência/Calamidade); bairros casados ao `BAIRROS.geojson` oficial
  (normalização de acento/grafia, JARDIN→JARDIM).
- **Sem tratamento estatístico** — é um registro de eventos. O mapa coroplético
  apenas **conta** eventos / soma desabrigados / severidade por bairro; o botão de
  métrica só troca a agregação.

---

## 4. Página **Estação** (`estacao.html` ← `build_station_history.py`)

Tudo por estação e **não combinado** (registro próprio de cada uma):
- Vento: climatologia mensal da velocidade média.
- **Rosas dos ventos mensais** (12 meses, jan–dez): 16 setores de direção × 5 classes de
  velocidade, frequência das horas com vento ≥ 0,5 m/s vindo de cada setor (direção
  meteorológica, de onde o vento vem), acionadas pelos seletores estação+ano do topo da
  página; escala comum aos 12 meses do ano escolhido. Mesmo CQ de calmaria/cata-vento
  travado do §2/rosa da página Agora (`station_windrose.json` em `build_station_history.py`).
  A **direção predominante** resumida (resultante vetorial de Grange) é a da página Cidade §2,
  item 6.
- Condições de temperatura, por ano × mês: recorde de máxima (máx de Tmax), recorde
  de mínima (mín de Tmin), média das máximas, média das mínimas.
- Mapa de calor de chuva: totais mensais por ano (exigindo ≥ 15 dias válidos).
- Cobertura: fração de dias com algum dado por ano.
- Download por estação/período: entrega a série diária "master" (sem filtro além do
  CQ de ingestão).
- **Ressalva conhecida**: o mapa de calor anual mostra os totais brutos da estação;
  os totais recentes implausíveis (ex.: ~950 mm em jan/2026) são superestimação de
  sensor e **não** foram corrigidos nesta página (sinalizado à parte).

---

## 5. Chuva da cidade combinada (`build_gauges_city.py`) — alimenta Cidade e Chuva–Rio

Precipitação é muito local; combina as duas redes:
- Reúne pluviômetros da Defesa Civil (2014–2020 diário + 2021–2025 de 10 min
  reamostrado para diário com `min_count=100`) **e** a chuva diária das estações
  meteorológicas.
- **Exclusões**: pluviômetro "Nova Brasília" (zero constante, falha) e estação
  "UDESC" (superestima ~1,7×).
- Chuva negativa → 0. Chuva diária da cidade = **média espacial** de todos os sítios
  válidos no dia, exigindo ≥ 3 sítios.
- Anos completos batem com ~2.100–2.170 mm (referência ~2.130 mm).

---

## 6. Página **Chuva & Rio** (`rio.html` ← `build_river.py`)

### 6.1 Chuva (gradiente por estação, "chuva por mês", barra da cidade)
- Total mensal por estação exigindo ≥ 20 dias válidos; climatologia = média entre
  anos; **cobertura (%)** = dias válidos / dias do mês, por estação-mês (mostrada no
  cursor). Média da cidade = média espacial das estações.
- Cada "gota" ≈ 40 mm (unidade fixa); cor = intensidade relativa.

### 6.2 Nível da água do rio — o que é medido
A abordagem é **nível da água do rio (cota)**, com a maré tratada como *influência*
sobre as estações de baixo curso — não como o objeto da medição.

O sensor mede a **cota** (*stage* / *gage height*): a altura da superfície da água
em relação ao **zero de referência (datum) próprio da régua** (definição do USGS —
altura acima de um zero estabelecido, arbitrário, em geral próximo ao leito).
- **Não é a lâmina d'água (profundidade)**: só coincidiria com a profundidade se o
  zero estivesse no leito, o que não é garantido e não está documentado para estas
  réguas. Por isso reportamos a **cota relativa ao datum local**, e não uma profundidade.
- **Valor negativo** = superfície da água **abaixo do zero da régua** (não é erro):
  ocorre quando o zero foi fixado acima da estiagem ou, nos trechos sob maré, quando
  a maré baixa desce abaixo desse zero. É o comportamento esperado na literatura
  hidrométrica para cota referida a datum local.
- Valores absolutos **não são comparáveis entre estações** (ex.: Cubatão ~21 m,
  estações da baía ~0–1 m). Comparação de *padrão* entre estações → via **anomalia**.

### 6.2b Nível — CQ (o ponto mais delicado)
- **Limite físico rígido**: |h| < 50 m (remove picos de telemetria, ex.: 1.000+ m).
- **Janela robusta física**: mediana ± máx(6·1,4826·MAD, faixa física), com faixa
  física de −2,8 m / +3,5 m abaixo/acima da mediana da estação. Calculada na série
  **diária** (robusta a falhas de vários anos, que são minoria dos dias) e **aplicada
  também à série horária**. Isso remove **falhas sustentadas** (ex.: divobras ~−4 m
  por anos) sem cortar **baixios de maré reais** (ex.: Cachoeira Central chegando a
  −1,3 m). Substituiu a janela puramente estatística anterior, que cortava a maré.
  MAD = desvio absoluto mediano; constante 1,4826 → comparável ao desvio-padrão sob
  normalidade (Rousseeuw & Croux, 1993).
- **Detecção de maré**: oscilação diurna **regular, ancorada à hora do dia**,
  presente em ≥ 2 anos ≥ 0,20 m. Distingue maré (regular) de cheias (esporádicas) e
  é sensível a mudança de regime — por isso Cachoeira Central (que só passou a
  resolver a maré ~2021) é corretamente marcada como sob maré, e Cubatão (a montante,
  cheias) **não**.
- **Iate Clube incluído como estação de estuário**: situado no estuário da Baía
  Babitonga, o nível é dominado pela maré. É mantido no conjunto e **rotulado
  "(estuário)"**; no mapa de calor usa uma escala própria (`hm_alim_estuary`), maior,
  por ter oscilações bem mais amplas que os rios.

### 6.3 Nível — perfil mensal (dumbbell)
- Por estação: por mês, amplitude (mín–máx do nível **diário**, lollipop) + **mediana**
  mensal (linha). Escala própria da régua.
- "Todas as estações": um dumbbell por estação (pequenos múltiplos), cada um na
  escala do seu datum.

### 6.4 Nível — perfil horário (mapa de calor hora × mês)
- Média do nível por hora-do-dia × mês. A **cor vai da mínima à máxima da própria
  estação** (min → max por sítio, `matRange` da matriz exibida) — contraste total
  dentro de cada painel. Os **valores** continuam sendo a **cota em relação ao zero
  da régua** (mostrada no cursor). A estrutura vertical (por hora) revela a maré;
  colunas revelam a sazonalidade.
- Como cada estação usa a sua própria escala de cor, compara-se o **padrão**, não o
  valor absoluto entre estações. **"Todas as estações"** mostra um painel por estação
  (pequenos múltiplos), cada um na sua escala min→max.
- Seletor de Ano permite ver a matriz de um ano específico (útil onde o regime mudou).

### 6.5 Seletores de Ano por estação
Os seletores de Ano de cada gráfico de nível são povoados com os **anos realmente
disponíveis para a estação selecionada** — `level_years` (perfil mensal), `hm_years`
(mapa de calor) e `data_years` (análise diária), gravados por estação no `river.json`.
O rol muda ao trocar de estação; assim anos como 2021 ou pós-2024 aparecem onde há
registro (antes, os seletores herdavam a cobertura de chuva e escondiam esses anos).

### 6.6 Limites de escala
- Mapa de calor (perfil horário): escala de cor **calculada por estação no cliente**
  (`matRange`, mínima→máxima do sítio) — ver §6.4. `hm_alim`/`hm_alim_estuary`
  continuam no `river.json` como referência, mas não coloram mais o mapa de calor.
- Demais limites fixos (`lvl_alim`) são calculados no `build_river.py` e guardados
  no `river.json`, para que as escalas sejam consistentes e se atualizem sozinhas.

### 6.7 Análise diária — faixas de El Niño / La Niña (ENSO)
- As séries diárias (temperatura, chuva, nível) recebem um **fundo sombreado** que
  marca a fase do **ENSO**: El Niño (quente) e La Niña (frio). O perfil mensal, para
  um ano específico, traz uma **faixa ENSO** equivalente.
- **Fonte e critério**: **Oceanic Niño Index (ONI)** da NOAA/CPC — média móvel de 3
  meses da anomalia de TSM na região Niño 3.4. Evento oficial quando |ONI| ≥ 0,5 °C
  por **≥ 5 trimestres sobrepostos consecutivos**.
- **Intensidade** (profundidade da cor) pela magnitude do ONI: fraco 0,5–0,9 ·
  moderado 1,0–1,4 · forte 1,5–1,9 · muito forte ≥ 2,0. Períodos que não atingem o
  limiar (ex.: 2024–25, 2025–26) ficam neutros. Sem inferência de causa.
- **Atualização automática**: `scripts/build_enso.py` **puxa a tabela ONI ao vivo da
  NOAA** a cada execução da GitHub Action e grava `site/data/enso.json` (com reserva
  embutido caso a NOAA esteja indisponível). O `rio.html` consome esse arquivo; assim
  a classificação se mantém em dia sozinha conforme a NOAA publica novos trimestres.

---

## 7. Página **Previsão WRF** (`previsao.html` ← `build_wrf_basins.py` + notebook)

**Chuva, temperatura (2 m) e vento (10 m) previstos** pelo WRF do CPTEC/INPE (domínio
AMS, 7 km), resumidos por bacia, com o **limite municipal** sobreposto no mapa.

### 7.1 Do GRIB2 aos campos horários (`notebooks/CPTEC_WRF_Joinville_downloader.ipynb`)
- Baixa os GRIB2 do CPTEC para a caixa de Joinville e extrai chuva (`tp/acpcp/ncpcp`),
  temperatura 2 m (`t2m`/`2t`/`t@2m`) e vento 10 m (`u10`/`v10`).
- **Acumulado × instantâneo (a regra central, verificada nas notas do laboratório):**
  - **Chuva = acumulada desde a init → de-acumular** (diferença entre horas; o 1º lead é
    a linha de base, então a chuva horária começa no 2º lead). Convenção detectada
    (`stepRange` + monotonicidade), `tp ≈ acpcp + ncpcp` conferido, negativos de
    arredondamento registrados. Unidades kg m⁻² = mm.
  - **Temperatura = instantânea → K→°C, nunca diferenciada.**
  - **Vento = instantâneo → componentes u,v; velocidade √(u²+v²) e direção
    (270−atan2(v,u)); nunca diferenciado.**
  - Salva `wrf_joinville_<run>Z.nc` (`precip_mm_h`, `t2m_degC`, `wspd10_ms`, `wdir10_deg`,
    `u10_ms`, `v10_ms`).

### 7.2 Agregação por bacia (peso exato de área)
- Cada célula de 7 km vira polígono; células e bacias vão a um **CRS métrico**
  (EPSG:31982 — SIRGAS 2000 / UTM 22S; projeção conforme, com distorção de área desprezível
  nesta escala) e são cruzadas (`geopandas.overlay`). Valor da bacia por
  hora = **média ponderada pela área**: Σ(valor·área∩) / Σ(área∩). A grade é recortada à
  janela de Joinville (bbox bacias ∪ município + margem). **Invariante testado** para os
  três campos: campo uniforme → mesmo valor em toda bacia; cobertura ~100%.
- Chuva: total = Σ_t (horária)·Δt. Temperatura: média (mín/máx) no tempo. Vento:
  velocidade média (escalar) + direção do **vetor médio** (u,v) da bacia.

### 7.3 Agregação por **bairro** + limite de resolução
- Mesmo método de peso de área aplicado a `bairros.geojson` (43 bairros). **Ressalva
  honesta**: o WRF tem células de ~7 km, **maiores que a maioria dos bairros** — bairros
  dentro da mesma célula recebem o **mesmo valor**. A coropleta por bairro usa uma escala
  de cor com **span mínimo por variável** (para não transformar ~0,3 °C em falso
  vermelho×azul); temperatura fica quase uniforme (correto), chuva/vento mostram o
  gradiente possível.

### 7.4 Saídas (em `site/data/`)
- `wrf_basins.csv`, `wrf_bairros.csv` — resumos por bacia e por bairro (download);
  `wrf_basins_hourly.csv` — série horária; `wrf_basins.geojson`, `wrf_bairros.geojson` —
  polígonos com a previsão; **`wrf_grid.geojson`** — a grade WRF (caixa toda) como células
  poligonais (“fishnet”) com a previsão por célula, para SIG; `wrf_forecast.json` — grade
  **local** (janela de Joinville) + **regional** (caixa toda, para o mapa de retalhos) +
  séries por bacia/bairro. Mapas sobrepõem `limite.geojson` + `bacias.geojson` + `bairros.geojson`.
- **Mapa regional**: todo o domínio WRF em estilo pcolormesh (“retalhos”) com grade lat/lon;
  marca Joinville e dá o contexto de grande escala (Serra do Mar, contraste costa–interior),
  interpretado pelo texto explicativo da página.

### 7.5 Consistência com a verificação (cross-check)
- O tratamento de chuva e temperatura segue a metodologia TUPANN×WRF validada
  (`TUPANN_vs_WRF_methodology.md`, `Joinville_LAB_LOG.md`): unidades, `tp=acpcp+ncpcp`,
  de-acumulação from-init (confirmada empiricamente para o produto AMS 7 km) e a distinção
  acumulado×instantâneo. O mesmo `.nc` serve à página e ao Estágio A de verificação.

### 7.6 Escopo
- Saída **direta** do modelo (sem correção de viés). Cobertura depende da retenção do
  CPTEC. Fase atual: **estudo de caso** reproduzível; atualização automática da rodada
  mais recente é o passo seguinte (mesmo padrão de `fetch_airport.py` / `build_enso.py`).

---

## Exclusões e âncoras (resumo)
- Chuva-cidade: fora "Nova Brasília" (falha) e "UDESC" (superestima).
- Nível de rio: "Iate Clube" **incluído** como estação de **estuário** (rotulado, escala própria no mapa de calor). Nenhuma estação de nível é excluída.
- Referência de chuva anual de Joinville: ~2.130 mm (De Mello, 2020; 42 postos).
- Classes de intensidade de chuva: limiares de uso corrente (leve/moderada/forte/violenta); a OMM registra não haver definição internacional única — tratados como convenção operacional.
- Cota (stage/gage height) referida a datum local: USGS, *How Streamflow is Measured*. Estimador robusto (MAD, 1,4826): Rousseeuw & Croux (1993).
