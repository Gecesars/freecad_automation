# User Manual

## Prompt CAD

Digite uma peca mecanica, por exemplo:

```text
placa de aluminio 120x80x6 mm com quatro furos de 6 mm nos cantos e rasgo central de 40x12 mm
```

Use `Gerar Macro` para inspecionar o script ou `Gerar, Executar e Visualizar` para criar arquivos CAD e carregar o STL/OBJ no viewer.

## Visualizacao 3D

A aba `Visualizacao 3D` carrega a malha exportada. Use as vistas Iso, Frente, Topo e Lateral, alterne wireframe/shaded, controle eixos, bounding box, cor, fundo, transparencia e exporte PNG.

## Importar CAD

Selecione DXF, SVG ou DWG. DXF e SVG podem ser analisados e extrudados. DWG mostra diagnostico claro quando nao ha conversor externo no sistema.

## Diagnostico

Use a aba `Diagnostico` ou rode:

```bash
make doctor
```

## Saidas

Arquivos gerados ficam em `data/outputs`. Macros ficam em `data/macros`.
