# Roadmap 200 Improvements

1. [done] Corrigir execução real de macro no FreeCAD.
2. [done] Adicionar modo headless com freecadcmd.
3. [done] Adicionar modo headless com FreeCAD --console.
4. [done] Adicionar fallback com xvfb-run.
5. [done] Detectar AppImage automaticamente.
6. [done] Detectar wrapper local `~/bin/freecad`.
7. [done] Detectar versão do FreeCAD.
8. [done] Criar teste mínimo FreeCAD.
9. [done] Criar relatório de execução FreeCAD.
10. [done] Salvar stdout e stderr de cada execução.
11. [done] Validar sintaxe da macro antes de executar.
12. [done] Validar imports da macro.
13. [done] Gerar macro com estrutura main.
14. [done] Salvar `.FCStd`.
15. [done] Exportar `.STEP`.
16. [done] Exportar `.STL`.
17. [done] Exportar `.BREP`.
18. [done] Exportar `.OBJ`.
19. [done] Gerar metadata JSON da peça.
20. [done] Gerar relatório markdown da peça.
21. [done] Validar shape com `isValid`.
22. [done] Calcular bounding box.
23. [done] Calcular volume.
24. [done] Calcular área superficial.
25. [done] Mostrar número de faces.
26. [done] Mostrar número de arestas.
27. [done] Mostrar número de sólidos.
28. [done] Adicionar material visual.
29. [done] Adicionar cores por material.
30. [done] Criar biblioteca de materiais.
31. [done] Melhorar parser de dimensões.
32. [done] Melhorar parser de unidades.
33. [done] Aceitar mm.
34. [done] Aceitar cm.
35. [done] Aceitar m.
36. [planned] Aceitar polegadas.
37. [done] Aceitar rosca M3.
38. [done] Aceitar rosca M4.
39. [done] Aceitar rosca M5.
40. [done] Aceitar rosca M6.
41. [done] Aceitar rosca M8.
42. [done] Aceitar rosca M10.
43. [done] Aceitar furos passantes.
44. [planned] Aceitar furos cegos.
45. [planned] Aceitar furo escareado.
46. [planned] Aceitar furo rebaixado.
47. [done] Aceitar rasgo oblongo.
48. [in_progress] Aceitar rasgo retangular.
49. [planned] Aceitar rasgo circular.
50. [done] Aceitar chanfro.
51. [done] Aceitar filete/arredondamento.
52. [done] Aceitar flange.
53. [done] Aceitar placa.
54. [done] Aceitar eixo.
55. [done] Aceitar cilindro.
56. [done] Aceitar suporte em L.
57. [done] Aceitar caixa aberta.
58. [done] Aceitar caixa fechada.
59. [planned] Aceitar tampa.
60. [done] Aceitar nervuras.
61. [done] Aceitar reforços.
62. [done] Aceitar padrão circular de furos.
63. [in_progress] Aceitar padrão retangular de furos.
64. [done] Aceitar furos nos cantos.
65. [done] Aceitar furo central.
66. [planned] Aceitar origem customizada.
67. [planned] Aceitar coordenadas explícitas.
68. [planned] Aceitar espelhamento.
69. [planned] Aceitar rotação.
70. [planned] Aceitar translação.
71. [planned] Criar histórico de prompts.
72. [planned] Criar favoritos de prompts.
73. [in_progress] Criar biblioteca de peças.
74. [planned] Criar templates paramétricos.
75. [planned] Criar editor de parâmetros.
76. [in_progress] Criar árvore de features.
77. [done] Criar árvore de objetos FreeCAD.
78. [in_progress] Criar visualização 3D embutida.
79. [done] Criar fallback viewer por STL.
80. [done] Criar fallback viewer por OBJ.
81. [done] Criar screenshot do viewer.
82. [done] Criar exportação PNG.
83. [done] Criar vista isométrica.
84. [done] Criar vista frontal.
85. [done] Criar vista lateral.
86. [done] Criar vista superior.
87. [done] Criar zoom extents.
88. [done] Criar pan.
89. [done] Criar rotação.
90. [done] Criar wireframe.
91. [done] Criar shaded.
92. [done] Criar shaded with edges.
93. [done] Mostrar eixos.
94. [planned] Mostrar grade.
95. [done] Mostrar bounding box.
96. [done] Controlar transparência.
97. [done] Controlar cor da peça.
98. [done] Controlar cor do fundo.
99. [in_progress] Medir distância.
100. [done] Medir bounding box visual.
101. [done] Importar DXF.
102. [done] Listar layers DXF.
103. [in_progress] Selecionar layers DXF.
104. [done] Limpar DXF.
105. [done] Centralizar DXF.
106. [done] Escalar DXF.
107. [done] Extrudar DXF.
108. [in_progress] Converter DXF para sketch.
109. [in_progress] Converter DXF para shape.
110. [done] Gerar relatório DXF.
111. [done] Importar SVG.
112. [done] Converter SVG paths.
113. [done] Escalar SVG.
114. [done] Extrudar SVG.
115. [in_progress] Simplificar SVG.
116. [in_progress] Preservar curvas SVG.
117. [done] Gerar relatório SVG.
118. [done] Diagnosticar DWG.
119. [done] Detectar conversor DWG.
120. [blocked] Converter DWG para DXF.
121. [blocked] Importar DWG convertido.
122. [done] Mostrar erro claro para DWG sem conversor.
123. [in_progress] Importar STEP.
124. [in_progress] Importar STL.
125. [in_progress] Importar OBJ.
126. [in_progress] Importar BREP.
127. [done] Exportar arquivo importado como FCStd.
128. [done] Exportar arquivo importado como STEP.
129. [done] Exportar arquivo importado como STL.
130. [done] Exportar arquivo importado como OBJ.
131. [done] Criar pipeline RAG v2.
132. [done] Ingerir documentação oficial.
133. [in_progress] Ingerir mirror GitHub da documentação.
134. [in_progress] Ingerir macros públicas.
135. [done] Ingerir exemplos locais do FreeCAD.
136. [done] Extrair API local FreeCAD.
137. [done] Criar dump de módulos FreeCAD.
138. [done] Criar dump de workbenches.
139. [done] Criar dump de importadores.
140. [done] Criar dump de exportadores.
141. [done] Criar chunks com metadados.
142. [done] Criar índice BM25.
143. [done] Criar índice TF-IDF.
144. [in_progress] Criar índice vetorial opcional.
145. [done] Criar reranking técnico.
146. [done] Criar auditoria RAG.
147. [done] Mostrar fontes RAG na UI.
148. [done] Mostrar score RAG.
149. [done] Mostrar chunks usados.
150. [planned] Permitir abrir documento local do RAG.
151. [done] Criar teste RAG para headless.
152. [done] Criar teste RAG para DXF.
153. [done] Criar teste RAG para SVG.
154. [done] Criar teste RAG para exportação STEP/STL.
155. [done] Criar teste RAG para viewer.
156. [done] Criar autocorreção de macro.
157. [done] Criar histórico de falhas.
158. [done] Criar classificação de erro.
159. [done] Criar tentativa automática de reparo.
160. [done] Limitar reparo a 3 tentativas.
161. [done] Salvar macros versionadas.
162. [done] Salvar outputs versionados.
163. [planned] Comparar macros antigas.
164. [planned] Comparar resultados CAD antigos.
165. [done] Criar smoke test completo.
166. [done] Criar teste unitário parser.
167. [done] Criar teste unitário macro generator.
168. [done] Criar teste unitário runner.
169. [in_progress] Criar teste unitário import DXF.
170. [in_progress] Criar teste unitário import SVG.
171. [in_progress] Criar teste unitário DWG diagnóstico.
172. [done] Criar teste unitário RAG.
173. [planned] Criar teste unitário viewer fallback.
174. [done] Criar teste CLI.
175. [in_progress] Criar teste UI básico.
176. [in_progress] Criar README atualizado.
177. [done] Criar manual técnico.
178. [done] Criar manual do usuário.
179. [done] Criar guia de troubleshooting.
180. [done] Criar página de arquitetura.
181. [done] Criar arquivo `.env.example`.
182. [planned] Criar configurações persistentes.
183. [in_progress] Criar seleção de binário FreeCAD na UI.
184. [done] Criar seleção de pasta de saída.
185. [planned] Criar seleção de pasta RAG.
186. [planned] Criar opção limpar cache.
187. [done] Criar opção reconstruir RAG.
188. [planned] Criar opção compactar RAG.
189. [planned] Criar opção exportar projeto.
190. [planned] Criar opção importar projeto.
191. [planned] Criar logs rotativos.
192. [planned] Criar nível de log.
193. [done] Criar console interno.
194. [done] Criar status bar com estado do FreeCAD.
195. [done] Criar indicador de modo viewer.
196. [done] Criar indicador de modo executor.
197. [done] Criar indicador de qualidade RAG.
198. [planned] Criar pacote de diagnóstico zip.
199. [done] Criar comando `make doctor`.
200. [done] Criar comando `make full-test`.
