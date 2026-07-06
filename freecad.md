# FreeCAD Prompt Forge - Registro completo do que foi feito

Data do registro: 2026-07-06

Repositorio remoto:

```text
https://github.com/Gecesars/freecad_automation.git
```

Branch principal:

```text
main
```

Commits ja enviados:

```text
ae839c8 Initial FreeCAD Prompt Forge application
b84d7fc Handle flange typo in prompt parser
```

Este documento resume o estado do projeto FreeCAD Prompt Forge, tudo que foi construido, corrigido, validado e publicado ate aqui.

## 1. Objetivo do projeto

O projeto nasceu como uma aplicacao local para desenhar pecas no FreeCAD usando prompts em linguagem natural.

Objetivo principal:

```text
Usuario escreve uma descricao tecnica da peca.
O sistema interpreta parametros.
O sistema gera uma macro FreeCAD.
O FreeCAD roda em modo headless.
A peca e exportada em formatos CAD.
A interface mostra a peca em uma area de visualizacao.
```

O app foi pensado para evoluir como um agente especializado em FreeCAD, CAD parametrico, macros Python, RAG local e geracao assistida por IA.

## 2. Pasta e nome da aplicacao

A aplicacao foi criada em:

```text
/home/eftx3/freecad_prompt_forge
```

Nome usado:

```text
FreeCAD Prompt Forge
```

## 3. Estrutura geral implementada

Estrutura principal:

```text
app/
  agent.py
  auto_repair.py
  deepseek_assistant.py
  doctor.py
  freecad_runner.py
  geometry_validator.py
  job_manager.py
  macro_generator.py
  main.py
  models.py
  prompt_parser.py
  rag_*.py
  settings.py
  ui_main.py
  generators/
  importers/
  viewer3d/
  workers/
  diagnostics/

tests/
scripts/
tools/
data/
README.md
Makefile
requirements.txt
.env.example
.gitignore
```

Diretorios de runtime local:

```text
data/macros/
data/outputs/
data/outputs/jobs/
data/logs/
data/rag/
data/docs/
data/diagnostics/
data/repairs/
```

Esses diretorios sao usados pela aplicacao, mas artefatos gerados ficam ignorados pelo git.

## 4. Interface grafica

Foi criada uma interface grafica em PySide6.

Arquivo principal:

```text
app/ui_main.py
```

Entrada da aplicacao:

```text
app/main.py
```

Recursos da UI:

- Campo de prompt CAD.
- Botoes para gerar macro.
- Botoes para executar headless.
- Botao para gerar, executar e visualizar.
- Area de status do que o sistema esta fazendo.
- Barra de progresso.
- Log de atividade.
- Painel de visualizacao 3D.
- Painel de propriedades da malha.
- Abas para importacao, biblioteca, RAG, macro, execucao, exportacao, diagnostico, configuracoes e logs.
- Janela abrindo maximizada com `showMaximized()`.

Tambem foram feitas melhorias de contraste:

- Fonte do prompt mais escura.
- Texto dos labels com melhor contraste.
- Campos de texto brancos com fonte escura.
- Botoes e abas mais legiveis.
- Log de atividade visivel.

## 5. Feedback do sistema

Foi adicionado feedback de progresso para evitar a sensacao de que nada esta acontecendo.

Mensagens de status implementadas no pipeline:

```text
interpretando prompt
Parser local e validador geometrico ativos
Consultando RAG tecnico e gerando macro
Validando sintaxe da macro
Iniciando FreeCAD headless com timeout real
FreeCAD concluiu; arquivos CAD confirmados
Viewer carregou malha STL/OBJ
```

A UI tambem mostra logs e progresso durante jobs longos.

## 6. Pipeline completo de job

Foi criado um fluxo consolidado para executar tudo em sequencia.

Arquivo:

```text
app/job_manager.py
```

Fluxo:

```text
prompt
  -> parse_prompt()
  -> validate_geometry()
  -> RAG local
  -> MacroGenerator
  -> validacao de sintaxe da macro
  -> FreeCAD headless
  -> exportacao FCStd/STEP/STL/OBJ/BREP
  -> viewer por STL/OBJ
  -> metadata e build report
```

A UI passou a usar o pipeline completo em vez de tentar executar macro solta diretamente.

## 7. Parser de prompts

Arquivo principal:

```text
app/prompt_parser.py
```

O parser reconhece tipos de peca:

- `plate`
- `flange`
- `cylinder`
- `l_bracket`
- `box`

Reconhece dimensoes:

- comprimento
- largura
- altura
- espessura
- diametro
- diametro externo
- furo central
- diametro interno
- furos
- quantidade de furos
- diametro dos furos
- raio de furacao
- diametro primitivo
- rosca
- material

Materiais reconhecidos:

- aluminio
- aco
- inox
- latao
- plastico
- cobre
- nylon

Unidades:

- mm
- centimetros/cm
- metros/m

## 8. Correcoes feitas no parser

### 8.1 Dia 5mm

Problema:

```text
8 furos passantes dia 5mm
```

O sistema nao reconhecia `dia 5mm` corretamente e assumia furo padrao de 6 mm.

Correcao:

O parser passou a reconhecer:

```text
dia 5mm
diametro 5mm
diametro dos furos 5mm
furo de 5mm
furos de 5mm
8 furos passantes dia 5mm
8 furos passantes de 5mm
```

### 8.2 Furus/furu

Problema:

Usuarios escreviam:

```text
furus
furu
```

Correcao:

O parser agora aceita esses typos como termos de furo.

### 8.3 Rosda/rosca M5

Problema:

Prompt:

```text
rosda m5
```

O sistema podia confundir rosca com diametro do furo.

Correcao:

`rosda m5` e `rosca m5` sao reconhecidos como metadado de rosca.

Regra atual:

```text
Se o diametro do furo foi informado, ele continua mandando na geometria.
A rosca fica registrada como anotacao/parametro.
```

Exemplo:

```text
cada furo com dia 4mm rosda m5
```

Resultado:

```text
hole_diameter = 4
thread = M5
thread_nominal_diameter = 5
```

### 8.4 Num diametro de 30mm

Problema:

Prompt:

```text
8 furos de 4mm num diametro de 30mm
```

O sistema podia interpretar o diametro como diametro externo da peca.

Correcao:

Quando aparece depois dos furos, `num diametro de 30mm` e tratado como diametro primitivo/PCD.

Resultado:

```text
bolt_circle_diameter = 30
bolt_circle_radius = 15
```

### 8.5 Espesura

Problema:

Usuario escreveu:

```text
espesura
```

Correcao:

O parser aceita `espesura` como `espessura`.

### 8.6 Diametro externo sobrescrito por diametro ambiguo

Problema:

Prompt:

```text
flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm com diametro de 8mm espessura de 10mm
```

Antes, o sistema interpretava o ultimo `diametro de 8mm` como diametro externo do flange.

Resultado errado anterior:

```text
outer_diameter = 8
```

Correcao:

O parser agora trava o diametro externo quando ele aparece no inicio do contexto do flange.

Resultado correto:

```text
outer_diameter = 80
hole_count = 8
hole_diameter = 10
bolt_circle_radius = 20
thickness = 10
```

O `diametro de 8mm` fica como aviso de ambiguidade:

```text
Diametro de 8 mm apos a descricao dos furos ficou ambiguo; nao foi usado como diametro externo.
```

### 8.7 Flage

Problema:

Prompt:

```text
flage redondo com 100mm diametro 8 furos num raio de 30mm com diametro de 12mm espessura de 12mm
```

O sistema nao reconhecia `flage` como `flange`.

Resultado errado anterior:

```text
part_type = plate
length = 100
width = 60
diameter = 8
outer_diameter = 8
```

Isso gerava uma placa retangular com furos, nao uma flange.

Correcao:

O parser agora reconhece:

```text
flange
flanges
flage
flages
```

Resultado correto:

```text
part_type = flange
outer_diameter = 100
diameter = 100
hole_count = 8
hole_diameter = 12
bolt_circle_radius = 30
bolt_circle_diameter = 60
thickness = 12
```

Assuncao registrada:

```text
Interpretando 'flage' como flange.
```

## 9. Validador geometrico

Arquivo:

```text
app/geometry_validator.py
```

Foi criado um validador obrigatorio para impedir macros geometricamente invalidas.

Validacao principal para flange:

```python
outer_radius = outer_diameter / 2
hole_radius = hole_diameter / 2
max_allowed_bolt_radius = outer_radius - hole_radius - edge_margin
```

Margem padrao:

```text
edge_margin = 1 mm
```

Exemplo validado:

```text
flange redondo diametro 60mm com 8 furos dia 5mm num raio de 39mm
```

Calculo:

```text
outer_radius = 30
hole_radius = 2.5
max_allowed_bolt_radius = 26.5
bolt_circle_radius = 39
```

Resultado:

```text
Geometria invalida.
```

Mensagem explicativa:

```text
Geometria invalida: o raio dos furos informado e 39 mm,
mas o flange tem raio externo de apenas 30 mm.
Para furos de 5 mm, o raio maximo recomendado do circulo de furos e 26.5 mm.
Voce quis dizer diametro primitivo de 39 mm?
```

Tambem foi adicionada correcao automatica possivel:

```text
Interpretar raio de 39 mm como diametro primitivo,
usando raio 19.5 mm.
```

## 10. Geracao deterministica de macro

Arquivo:

```text
app/macro_generator.py
```

Foi implementado gerador de macro robusto com:

- `main()`
- criacao de documento FreeCAD
- criacao da geometria
- cortes booleanos
- validacao de shape
- tentativa de reparo
- `removeSplitter()`
- exportacao de formatos
- relatorio de build
- metadata JSON
- logs claros

Tipos de geracao:

- placa
- flange
- cilindro/eixo
- suporte em L
- caixa

Para flange, foi criado gerador especifico:

```text
app/generators/flange_generator.py
```

Regra importante:

```text
Furo central so e criado quando o prompt pede furo central.
```

Isso corrigiu o problema de furo central inventado.

## 11. FreeCAD headless

Arquivo:

```text
app/freecad_runner.py
```

Foi implementado executor do FreeCAD com deteccao de varias formas de execucao:

- `freecadcmd`
- `FreeCADCmd`
- `freecad`
- `FreeCAD`
- wrapper local `~/bin/freecad`
- AppImage
- `xvfb-run`
- `FREECAD_CMD`
- `FREECAD_PYTHON`

O sistema detecta neste ambiente:

```text
/home/eftx3/bin/freecad
```

Modo observado nos jobs:

```text
appimage_console
```

Tambem foi adicionado:

- timeout real
- logs de stdout/stderr
- checagem de arquivos esperados
- modo de cancelamento de processo
- processo em sessao separada
- kill por process group
- relatorio de execucao

## 12. Cancelamento real de jobs

Arquivo:

```text
app/workers/process_runner.py
```

Foi corrigido o problema em que o app dizia:

```text
Processos cancelados: 0
```

Agora o runner:

- inicia subprocessos em nova sessao
- guarda PID/PGID
- encerra grupo de processos
- reporta quando o processo foi morto
- trata timeout de verdade

## 13. Worker FreeCAD

Arquivo:

```text
app/workers/freecad_worker.py
```

Melhorias:

- teste minimo do FreeCAD antes da macro do usuario
- status durante execucao
- tratamento de erro
- logs mais claros
- integracao com UI sem travar a janela

## 14. DeepSeek

Arquivo:

```text
app/deepseek_assistant.py
```

Foi configurado suporte ao DeepSeek via `.env`.

Variaveis:

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=45
```

Importante:

```text
A chave real fica somente no .env local.
.env esta no .gitignore.
Nao foi commitado nenhum segredo.
```

Direcao final adotada:

```text
DeepSeek auxilia a revisao e o raciocinio.
DeepSeek nao e a fonte de verdade geometrica para pecas parametrizadas.
O parser local e o validador geometrico mandam nas dimensoes.
```

Isso foi feito para evitar que uma resposta da IA altere silenciosamente medidas tecnicas.

Comportamento observado:

- se DeepSeek responde, o app registra notas;
- se DeepSeek falha, o fallback local continua;
- a macro deterministica permanece valida.

## 15. RAG local

Arquivos:

```text
app/rag_store.py
app/rag_ingest_v2.py
app/rag_retriever_v2.py
app/rag_query.py
app/rag_audit.py
app/rag_index_v2.py
```

Foi criada uma base de conhecimento local RAG sobre FreeCAD.

Componentes:

- documentos locais em `data/docs/`
- chunks em `data/rag/`
- indices BM25
- indices TF-IDF
- dump de API FreeCAD
- recuperador hibrido

Melhorias feitas:

- filtro de chunks irrelevantes;
- reducao de resultados de README/licencas;
- foco em termos tecnicos de FreeCAD;
- auditoria por query;
- reconstrucao por comando.

Comandos:

```bash
make ingest
.venv/bin/python -m app.rag_audit --query "FreeCAD Part cut cylinder export STEP STL"
```

Arquivos RAG grandes ficam fora do git:

```text
data/rag/*
data/docs/*
data/knowledge/*
```

## 16. Viewer 3D

Arquivos:

```text
app/viewer3d/fallback_viewer.py
app/viewer3d/fallback_image_viewer.py
app/workers/viewer_worker.py
```

Foi implementado viewer por malha STL/OBJ.

Recursos:

- carregar STL/OBJ;
- modo shaded;
- modo shaded_with_edges;
- modo wireframe;
- rotacao com mouse;
- zoom;
- vistas iso/frente/topo/lateral;
- reset;
- eixos opcionais;
- bounding box opcional;
- cor da peca;
- cor do fundo;
- transparencia;
- exportar PNG.

Problema corrigido:

O preview ficava com triangulacao escura e aspecto de wireframe.

Correcoes:

- modo padrao passou a ser `shaded`;
- eixos e BBox desativados por padrao;
- PNG de preview passou a renderizar faces solidas;
- triangulacao escura foi removida;
- alpha do preview ficou opaco;
- costuras entre triangulos foram reduzidas.

## 17. Importadores

Diretorio:

```text
app/importers/
```

Implementado/estruturado:

- importador DXF;
- importador SVG;
- diagnostico DWG;
- diagnostico STEP;
- diagnostico de malhas;
- relatorio de importacao.

Arquivos:

```text
app/importers/dxf_importer.py
app/importers/svg_importer.py
app/importers/dwg_importer.py
app/importers/step_importer.py
app/importers/mesh_importer.py
app/importers/import_report.py
```

Observacao:

```text
DWG depende de conversor externo, como LibreDWG, ODA/Teigha ou QCAD Pro.
```

## 18. Diagnosticos

Arquivos:

```text
app/doctor.py
app/diagnostics/failure_package.py
app/diagnostics/freecad_minimal_test.py
app/diagnostics/freeze_detector.py
app/diagnostics/runtime_report.py
```

Recursos:

- `make doctor`
- teste minimo FreeCAD
- relatorio de ambiente
- relatorio de travamento
- pacote de falha em zip
- logs em `data/logs/`
- relatorios em `data/diagnostics/`

## 19. Testes automatizados

Diretorio:

```text
tests/
```

Testes criados/atualizados:

```text
tests/test_prompt_parser.py
tests/test_prompt_parser_flange.py
tests/test_macro_generator.py
tests/test_freecad_runner.py
tests/test_rag_store.py
```

Estado atual dos testes:

```text
15 passed
```

Comando:

```bash
make test
```

## 20. Casos reais validados

### 20.1 Flange 45 mm com typo e rosca

Prompt:

```text
crie um flange redondo de diametro 45mm com 8 furus num raio de 13mm cada furo com dia 4mm rosda m5
```

Resultado correto:

```text
outer_diameter = 45
hole_count = 8
hole_diameter = 4
bolt_circle_radius = 13
bolt_circle_diameter = 26
thread = M5
thickness = 10 padrao
```

FreeCAD headless executou e viewer carregou.

### 20.2 Flange 80 mm com diametro ambiguo

Prompt:

```text
flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm com diametro de 8mm espessura de 10mm
```

Resultado correto:

```text
outer_diameter = 80
hole_count = 8
hole_diameter = 10
bolt_circle_radius = 20
bolt_circle_diameter = 40
thickness = 10
```

Aviso:

```text
Diametro de 8 mm ficou ambiguo e nao foi usado como diametro externo.
```

FreeCAD gerou:

```text
FCStd
STEP
STL
OBJ
BREP
metadata
build_report
preview PNG
```

BBox validado:

```text
80 x ~80 x 10 mm
```

### 20.3 Flage 100 mm

Prompt:

```text
flage redondo com 100mm diametro 8 furos num raio de 30mm com diametro de 12mm espessura de 12mm
```

Problema anterior:

```text
Gerava placa retangular 100 x 60 x 12.
```

Resultado corrigido:

```text
part_type = flange
outer_diameter = 100
hole_count = 8
hole_diameter = 12
bolt_circle_radius = 30
bolt_circle_diameter = 60
thickness = 12
```

BBox validado:

```text
100 x ~100 x 12 mm
```

Preview confirmado visualmente:

```text
flange circular com 8 furos
sem furo central inventado
sem placa retangular
```

## 21. Arquivos gerados por job

Cada job gera pasta parecida com:

```text
data/outputs/jobs/<job_id>/
```

Conteudo tipico:

```text
<base>.py
<base>.FCStd
<base>.step
<base>.stl
<base>.obj
<base>.brep
<base>_metadata.json
<base>_build_report.md
metadata.json
build_report.md
preview_iso.png
preview_front.png
preview_top.png
preview_side.png
```

Esses arquivos sao runtime local e nao entram no GitHub.

## 22. Comandos principais

Instalar:

```bash
make install
```

Rodar UI:

```bash
make run
```

Ou:

```bash
./run.sh
```

Rodar CLI com FreeCAD:

```bash
.venv/bin/python -m app.main \
  --prompt "flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm espessura de 10mm" \
  --run-freecad \
  --view \
  --json
```

Rodar testes:

```bash
make test
```

Rodar diagnostico:

```bash
make doctor
```

Reconstruir RAG:

```bash
make ingest
```

## 23. Git e publicacao

O repositorio foi inicializado localmente.

Foram criados commits:

```text
ae839c8 Initial FreeCAD Prompt Forge application
b84d7fc Handle flange typo in prompt parser
```

O push foi feito para:

```text
https://github.com/Gecesars/freecad_automation.git
```

Branch:

```text
main -> origin/main
```

## 24. Higiene de seguranca

Foi criado `.gitignore` para nao versionar:

```text
.env
.venv/
__pycache__/
.pytest_cache/
data/outputs/*
data/macros/*
data/logs/*
data/diagnostics/*
data/repairs/*
data/docs/*
data/rag/*
data/knowledge/*
imp.md
```

O arquivo publico de exemplo e:

```text
.env.example
```

Ele contem apenas nomes de variaveis, sem chave real.

Antes do commit/push foram verificadas ocorrencias de:

```text
sk-...
/home/eftx3
```

No conteudo versionado, nao foi encontrado segredo real.

## 25. Estado atual

Estado funcional atual:

- app PySide6 criado;
- janela maximizada;
- campo de prompt com contraste melhor;
- logs e progresso visiveis;
- parser corrigido para os principais prompts testados;
- validador geometrico ativo;
- macro FreeCAD deterministica;
- FreeCAD headless executando;
- exportacao multi-formato funcionando;
- viewer solido por STL/OBJ funcionando;
- DeepSeek integrado como auxiliar;
- RAG local estruturado;
- diagnosticos disponiveis;
- testes passando;
- repositorio publicado.

## 26. Pontos ainda em evolucao

Ainda vale melhorar:

- suporte a mais tipos de pecas;
- parser mais robusto para frases muito ambiguas;
- representacao real de roscas, nao apenas anotacao;
- cotas visuais no viewer;
- controle mais preciso de features mecanicas;
- importacao geometrica completa de STEP/mesh para edicao;
- RAG com corpus curado menor e mais tecnico;
- empacotamento da aplicacao;
- CI no GitHub Actions;
- autenticao/configuracao guiada para DeepSeek;
- biblioteca local de pecas geradas.

## 27. Resumo curto

O FreeCAD Prompt Forge hoje ja consegue:

```text
Receber prompt tecnico.
Interpretar dimensoes.
Validar geometria.
Gerar macro FreeCAD.
Executar FreeCAD headless.
Exportar FCStd/STEP/STL/OBJ/BREP.
Carregar preview 3D solido.
Mostrar progresso e logs.
Usar DeepSeek como apoio.
Consultar RAG local.
Rodar testes.
Publicar codigo em GitHub sem segredos.
```

O caso critico mais recente, `flage redondo com 100mm...`, foi corrigido e validado com teste automatizado e execucao real no FreeCAD.
