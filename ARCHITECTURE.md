# Architecture

FreeCAD Prompt Forge e dividido em camadas pequenas para manter o CAD real verificavel.

## Fluxo de Prompt

1. `app.prompt_parser` transforma texto em `PartSpec`.
2. `app.rag_store` recupera contexto local para a macro e para a UI.
3. `app.macro_generator` cria script FreeCAD com `main()`, validacao, exportacao e relatorio.
4. `app.freecad_runner` descobre o backend FreeCAD, executa a macro e captura tentativas.
5. `app.ui_main` mostra resultados, arquivos, logs e carrega STL/OBJ no viewer.

## Backend FreeCAD

O runner tenta `freecadcmd`, `FreeCADCmd`, `freecad`, `FreeCAD`, wrapper local, AppImage, AppImage extraido, `xvfb-run` quando existe e `FREECAD_PYTHON` para Python embutido. Cada tentativa registra comando, modo, stdout, stderr, retorno e timeout.

## RAG v2

`app.rag_ingest_v2` coleta docs locais, dump de API e addons FreeCAD em `~/.local/share/FreeCAD/v1-1/Mod`. `app.rag_index_v2` cria BM25 e TF-IDF. `app.rag_retriever_v2` combina scores e aplica bonus tecnico por dominio.

## Viewer

O modo confiavel atual e `app.viewer3d.fallback_viewer.FallbackMeshViewer`, que carrega STL/OBJ com `trimesh`, projeta faces no Qt Graphics View e oferece controles de camera, display, eixos, bounding box e screenshot.

## Importadores

DXF usa `ezdxf` como fallback 2D, lista layers e gera solido envelope extrudado. SVG usa `svgpathtools`. DWG detecta conversores e so converte quando uma ferramenta externa esta presente.
