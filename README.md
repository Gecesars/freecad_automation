# FreeCAD Prompt Forge

FreeCAD Prompt Forge e uma aplicacao local para desenhar pecas CAD a partir de prompts tecnicos. Ela interpreta o texto do usuario, valida dimensoes, consulta uma base RAG local sobre FreeCAD, usa DeepSeek como apoio opcional na revisao da macro, gera Python para FreeCAD, executa o FreeCAD em modo headless e prepara arquivos CAD e preview 3D.

O foco do projeto e transformar descricoes como "flange redondo de 80 mm com 8 furos de 10 mm em raio de 20 mm e espessura de 10 mm" em uma peca real exportada em formatos industriais.

## Principais recursos

- Interface grafica em PySide6, com area de prompt, progresso do job, logs, configuracoes, diagnostico e visualizacao.
- CLI para uso headless, automacao e testes.
- Parser parametrico para pecas comuns: placas, flanges, cilindros/eixos, caixas e suportes em L.
- Validacao geometrica antes de executar o FreeCAD, incluindo checagem de furos fora da flange.
- Gerador deterministico de macro FreeCAD com fallback local quando a IA falha.
- Integracao opcional com DeepSeek via `.env`, sem chave hardcoded no codigo.
- RAG local com BM25 + TF-IDF sobre documentacao e API do FreeCAD.
- Execucao robusta do FreeCAD headless com timeout, logs e relatorios.
- Exportacao para `.FCStd`, `.STEP`, `.STL`, `.OBJ`, `.BREP`, metadata JSON e relatorio Markdown.
- Viewer fallback por malha STL/OBJ com preview solido, vistas ISO/frente/topo/lateral, rotacao, zoom, bbox, eixos e exportacao PNG.
- Importadores/diagnosticos para DXF, SVG, DWG, STEP e malhas.
- Suite de testes automatizados com `pytest`.

## Como o fluxo funciona

```text
Prompt do usuario
  -> parser local extrai tipo, dimensoes, material e features
  -> validador geometrico bloqueia combinacoes invalidas
  -> RAG local busca contexto tecnico de FreeCAD
  -> DeepSeek revisa a intencao/macro quando configurado
  -> gerador deterministico cria a macro FreeCAD
  -> FreeCAD headless executa e exporta arquivos CAD
  -> viewer carrega STL/OBJ e gera previews
```

Para pecas parametrizadas conhecidas, o gerador local validado e a fonte de verdade da geometria. O DeepSeek ajuda na revisao e no contexto, mas nao deve sobrescrever dimensoes ja validadas pelo parser.

## Requisitos

- Linux recomendado.
- Python 3.11+ ou 3.12.
- `python3-venv` ou `virtualenv`.
- FreeCAD instalado ou AppImage acessivel.
- Opcional: `xvfb-run` para ambientes sem display.
- Opcional: chave DeepSeek para revisao assistida por IA.

O app tenta encontrar o FreeCAD nestes caminhos/comandos:

- `freecadcmd`
- `FreeCADCmd`
- `freecad`
- `FreeCAD`
- `~/bin/freecad`
- AppImages em `~/Applications`, na raiz do projeto e em `/opt`

Tambem e possivel forcar o caminho via `.env`.

## Instalacao rapida

```bash
git clone https://github.com/Gecesars/freecad_automation.git
cd freecad_automation
make install
```

Se `make install` nao funcionar por falta de `venv`:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## Configuracao

Copie o arquivo de exemplo:

```bash
cp .env.example .env
```

Configure somente no `.env` local:

```dotenv
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-pro
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TIMEOUT=45
FREECAD_CMD=
FREECAD_PYTHON=
```

Notas importantes:

- Nunca versione `.env`.
- `.env` ja esta no `.gitignore`.
- Em repositorios publicos, mantenha apenas `.env.example`.
- Se DeepSeek nao estiver configurado ou falhar, o gerador local continua funcionando.
- Se o FreeCAD nao for encontrado automaticamente, preencha `FREECAD_CMD` com o caminho do executavel.

Exemplo:

```dotenv
FREECAD_CMD=/home/usuario/bin/freecad
```

## Rodar a interface grafica

```bash
make run
```

Ou:

```bash
./run.sh
```

A janela abre maximizada e mostra:

- `Prompt CAD`: cria macro, executa headless, gera/exporta e visualiza.
- `Visualizacao 3D`: carrega a malha gerada e permite navegar a peca.
- `Importar CAD`: importa/diagnostica arquivos externos.
- `Biblioteca`: lista jobs e artefatos.
- `RAG`: consulta a base local.
- `Macro`: mostra macro gerada.
- `Execucao`: mostra status do FreeCAD.
- `Exportacao`: mostra arquivos gerados.
- `Diagnostico Visual`: ajuda a investigar viewer/importacao.
- `Configuracoes`: caminhos e opcoes.
- `Logs`: saidas do app e do FreeCAD.

## Rodar via CLI

Gerar e executar uma peca no FreeCAD headless:

```bash
.venv/bin/python -m app.main \
  --prompt "flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm espessura de 10mm" \
  --run-freecad \
  --view \
  --json
```

Gerar apenas a macro:

```bash
.venv/bin/python -m app.main \
  --prompt "placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos" \
  --generate-only
```

## Exemplos de prompts

```text
placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e rasgo central de 40x12 mm
```

```text
flange redondo de 80mm com 8 furos de 10 mm num raio de 20mm espessura de 10mm
```

```text
flange circular de diametro 45mm com 8 furos de 4mm num diametro primitivo de 30mm espessura de 10mm
```

```text
caixa aberta 100x80x40 mm com parede de 3 mm
```

```text
suporte em L 80x60x30 mm espessura 5 mm com furos de 6 mm em cada aba
```

## Saidas geradas

Os jobs ficam em:

```text
data/outputs/jobs/<job_id>/
```

Cada job pode conter:

- macro Python gerada
- `.FCStd`
- `.STEP`
- `.STL`
- `.OBJ`
- `.BREP`
- `metadata.json`
- `build_report.md`
- previews PNG
- logs de execucao

Esses arquivos sao artefatos locais e nao devem ser commitados.

## RAG local

Reconstruir a base:

```bash
make ingest
```

Auditar uma consulta:

```bash
.venv/bin/python -m app.rag_audit --query "FreeCAD Part cut cylinder export STEP STL"
```

Os indices e documentos ingeridos ficam em:

```text
data/docs/
data/rag/
data/knowledge/
```

Esses arquivos sao grandes e reconstruiveis. Por isso ficam fora do git por padrao.

## DeepSeek

A integracao fica em `app/deepseek_assistant.py`.

Variaveis suportadas:

- `DEEPSEEK_API_KEY`: chave local da API.
- `DEEPSEEK_MODEL`: modelo a usar. Padrao do projeto: `deepseek-v4-pro`.
- `DEEPSEEK_BASE_URL`: endpoint base. Padrao: `https://api.deepseek.com`.
- `DEEPSEEK_TIMEOUT`: timeout em segundos.

Comportamento esperado:

- Se a API responder, o app registra revisao/notas da IA.
- Se a API falhar, o app informa o fallback e usa o gerador local.
- A macro final de pecas parametrizadas continua obedecendo ao spec validado localmente.

## Testes

Rodar suite principal:

```bash
make test
```

Smoke test com FreeCAD:

```bash
make smoke
```

Diagnostico:

```bash
make doctor
```

Teste completo:

```bash
make full-test
```

Importadores:

```bash
.venv/bin/python -m app.importers.dxf_importer --self-test
.venv/bin/python -m app.importers.svg_importer --self-test
.venv/bin/python -m app.importers.dwg_importer --doctor
```

## Estrutura do projeto

```text
app/
  agent.py                    orquestracao de prompt -> macro
  prompt_parser.py            parser parametrico
  geometry_validator.py       validacao geometrica
  macro_generator.py          geracao de macro FreeCAD
  freecad_runner.py           execucao headless do FreeCAD
  job_manager.py              pipeline completo de job
  deepseek_assistant.py       cliente DeepSeek
  rag_*.py                    ingestao, consulta e auditoria RAG
  generators/                 geradores por tipo de peca
  importers/                  DXF, DWG, SVG, STEP e mesh
  viewer3d/                   viewers e previews 3D
  workers/                    workers Qt/processos
  diagnostics/                pacotes e relatorios de falha

tests/                        testes automatizados
scripts/                      scripts auxiliares
tools/                        ferramentas de dump/inspecao FreeCAD
data/                         runtime local ignorado pelo git
```

## Higiene de repositorio publico

Este repo foi preparado para ser publico:

- `.env` nao e versionado.
- Chaves de API nao devem aparecer no codigo, docs ou historico.
- `.venv`, caches, logs, outputs CAD, macros geradas e indices RAG sao ignorados.
- `.env.example` mostra apenas nomes de variaveis.

Antes de commitar:

```bash
git status --short
git diff --cached --name-only
rg -n --hidden "sk-|API_KEY|SECRET|TOKEN|PASSWORD" . \
  --glob '!**/.venv/**' \
  --glob '!data/**' \
  --glob '!.git/**'
```

Se a busca encontrar segredo real, remova antes do commit.

## Troubleshooting rapido

FreeCAD nao encontrado:

```bash
which freecadcmd || which FreeCADCmd || which freecad
```

Depois configure:

```dotenv
FREECAD_CMD=/caminho/para/freecad
```

Interface nao abre por Qt:

```bash
make doctor
```

RAG vazio ou sem resultados:

```bash
make ingest
```

Macro gerada mas peca nao aparece:

```bash
.venv/bin/python -m app.main --prompt "placa 80x50x5 mm" --run-freecad --view --json
```

Verifique tambem:

```text
data/logs/
data/diagnostics/
data/outputs/jobs/
```

## Estado atual

O projeto ainda esta em evolucao. A direcao atual e priorizar pecas parametrizadas robustas, execucao FreeCAD headless confiavel, visualizacao solida da malha e feedback claro do que o sistema esta fazendo.
