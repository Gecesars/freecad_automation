# Troubleshooting

## FreeCAD nao executa

Rode:

```bash
make doctor
```

Leia `data/diagnostics/freecad_execution_report.md`. Se `xvfb-run` estiver ausente e o FreeCAD precisar de GUI em headless:

```bash
sudo apt install xvfb
```

## AppImage e FUSE

Se aparecer erro de FUSE/libfuse, confirme `/dev/fuse` e permissoes do AppImage. O runner tambem tenta modos de console do proprio AppImage.

## UI nao abre

Rode `./run.sh` pelo terminal. O launcher adiciona `vendor/lib/usr/lib/x86_64-linux-gnu` ao `LD_LIBRARY_PATH` quando existe.

## DWG nao importa

DWG e proprietario. Instale LibreDWG, ODA/Teigha File Converter ou QCAD Pro, ou converta manualmente para DXF.

## RAG pobre ou vazio

Rode:

```bash
make ingest
.venv/bin/python -m app.rag_audit --query "FreeCAD import DXF SVG DWG converter"
```

## DeepSeek nao responde

Confira `.env` sem imprimir a chave. O app usa fallback local quando a API falha ou quando a resposta nao passa pela validacao de AST.
