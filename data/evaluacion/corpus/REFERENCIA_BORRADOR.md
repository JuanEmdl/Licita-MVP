# Borrador de la referencia del corpus SECOP (corrección funcional, capítulo 5)

Estado: lectura de los pliegos terminada para 01 a 08. Falta convertir esto en `NN_*.json`
(esperados con claves, categoría, habilitante, numeral y dictamen esperado; prohibidos;
portafolio construido) y escribir `scripts/evaluar_corpus.py`.

Alcance de la referencia: capacidad financiera y organizacional, experiencia, equipo mínimo,
RUP, garantía de seriedad, certificaciones y factores de ponderación. Lo demás que extraiga el
sistema se adjudica por muestreo para la precisión. Dictamen `null` = umbral relativo al
presupuesto o no verificable desde el texto: cuenta para extracción, no para exactitud.
Umbral acordado: exactitud del dictamen >= 0,80.

Excluidos: 09 Bucaramanga (pliego y requerimiento escaneados, sin texto) y 10 DIJIN (pliego
escaneado). Hallazgo: el lector no admite PDF escaneados (sin OCR).

Hallazgo DV-01: SECOP responde 403 a clientes no navegador; no se evade, la carga sigue manual.

## 01 Contraloría de Cundinamarca (LP, pliego 84 p.)
- 14.8 liquidez >= 4,0; endeudamiento <= 50 %; cobertura de intereses >= 10.
- 14.9 capital de trabajo >= 100 % POE ($6.351.097.824); ROE >= 0,25; ROA >= 0,15.
- 14.2.1 experiencia general: mínimo 3 certificaciones, >= 80 % del presupuesto.
- 14.2.2 experiencia específica: 1 certificación con entidad pública >= 50 % (SGDEA, OCR…).
- 14.3.1 perfiles: director (8 años generales, 4 como director), arquitecto de software,
  especialista/líder en gestión documental, líder técnico de desarrollo, especialista en
  ciberseguridad, ingeniero de pruebas, tres (3) técnicos operativos de archivo.
- 14.1.15 RUP; 14.1.16 garantía de seriedad.
- 15 puntaje: calidad técnica 30 (flujos adicionales a 20: 10; firma digital y estampa: 10;
  100 GB en la nube: 5; talleres de capacitación: 5), oferta económica 35, metros lineales
  adicionales a 150 ML 17,5, ISO 9001 5, mujeres 0,25, Mipyme 0,25, industria nacional 10,
  discapacidad. La adenda 1 solo cambia la matriz de riesgos (caso HU-06 sin requisitos afectados).

## 02 SDP fábrica de software (LP; memorando financiero + anexo técnico)
- 2.1.2 liquidez >= 1,5; endeudamiento <= 70 %; cobertura >= 2; capital de trabajo >= 36 % del
  presupuesto (null); ROE >= 5 %; ROA >= 3 %.
- Prohibidos: indicadores de otros procesos en las tablas del memorando (TransMilenio 1,52 y
  68 %, SDM 1,6 y 60 %, Alcaldía 1,43 y 69 %, Fiscalía 1,2…).
- Perfiles del anexo (células): de ejecución, la SDP no exige hojas de vida en la selección;
  ambiguos, no van a la referencia.

## 03 Medellín (LP)
- C. liquidez >= 1,3; endeudamiento <= 0,70; cobertura >= 1,0; ROE >= 0,04; ROA >= 0,02.
- B. experiencia general: hasta 5 contratos en RUP, >= 100 % del presupuesto en SMMLV, códigos
  81111500/81111600/81111900/81112200 (null).
- IV. precio 600; calidad 276: Azure certificación 50 y experiencia 50, IA certificación 50 y
  experiencia 50, ágiles certificación 38 y experiencia 38; industria nacional 100;
  discapacidad 20; mujeres 2; Mipyme 2. Personal clave evaluable: lista de cargos (ambiguo).

## 04 Corpocesar (CM)
- 3.5 liquidez >= 3,00; endeudamiento <= 0,48; cobertura >= 4,50; capital de trabajo >= CTd (null).
- 3.8 ROE >= 0,08; ROA >= 0,06.
- 3.10.1 tres (3) contratos de software (2 con procesos administrativos/contables).
- 4.1 contrato adicional (36,75 puntos, null); 4.2 director o coordinador 5 pts y administrador
  de servidores 5 pts; 4.3.1 plan de calidad 30 (null); 4.5 industria nacional 20;
  4.6 discapacidad 2.

## 05 Cali plataforma RCD (CM)
- 3.3 liquidez >= 1,50; endeudamiento <= 56 %; cobertura >= 4,56. 13.6 ROE >= 0,08.
- 3.1.9 RUP. 4.1 experiencia adicional: 2 contratos de gestión de residuos >= 50 % (título dice
  25 puntos, tabla 34.5: inconsistencia del pliego). 4.2 líder técnico con posgrado 30.
- 4.3 calidad técnica: soporte técnico adicional de 1 año, 24 puntos. 4.4 industria nacional 10.

## 06 CREMIL (SAMC)
- 5.3.2 (gran empresa) liquidez >= 2.10; endeudamiento <= 67 %; cobertura >= 2.67;
  capital de trabajo >= 70 % (null); ROE >= 0.15; ROA >= 0.08. Hay un segundo juego para Mipyme.
- 5.4.2 experiencia: suma >= 100 % del presupuesto en SMMLV, páginas web institucionales,
  81111500/81111800 (null).
- 6.1.1 precio 50; 6.1.2 técnica hasta 39,5 (documento técnico OLA 2: 8,5; desarrolladores
  back-end y front-end adicionales); 6.1.3 mujeres 0,25; Mipyme 0,25; industria nacional 10.

## 07 Sanidad Militar (SAMC)
- 11.3.3 liquidez > 1.5; endeudamiento < 66 %; cobertura > 0; ROE > 0.09; ROA > 0.03;
  capital de trabajo > 50 % (null).
- 11.4.2 (300): videos (mínimo 10) 100; CMMI DEV hasta 50; CMMI SVC hasta 50; 1 a 3
  certificaciones del sector salud >= 50 % (null) 50; capacitación Oracle, ciberseguridad y
  Azure 50. 11.4.3 precio 400; 11.4.3.1 industria nacional; 11.4.3.2 discapacidad.

## 08 Gobernación de Norte de Santander (SAMC, portal web)
- 6.2 liquidez >= 5; endeudamiento <= 27; cobertura >= 5; ROE y ROA (valores por leer, línea ~1082).
- 6.3 accesibilidad web; seguridad y protección de datos; equipo técnico (perfiles con 5 y 7
  años, PostgreSQL 2 años, técnico 4 años).
- Puntaje: precio 39,75; calidad técnica 25 (metodología 10, gobierno digital 5, UX/UI WCAG 2.1
  5, seguridad e interoperabilidad 5); industria nacional 15; emprendimiento y Mipymes 15;
  mujeres 0.25; cumplimiento histórico y experiencia específica (MSPI, IPv6) 5.

## Portafolio (por construir, ficticio, marcado "DATO DE PRUEBA FICTICIO")
Una empresa por caso con valores elegidos para repartir los dictámenes: unos ~40 % Cumple,
20 % No cumple, 20 % Cumple parcialmente y 20 % No verificable.
