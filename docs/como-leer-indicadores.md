# Cómo leer los indicadores

Guía de bolsillo para interpretar cada alerta. Este texto alimenta la sección
"Cómo leer esto" del dashboard.

---

## El semáforo 🟢 / 🟡 / 🔴

Cada alerta trae un color global y un color por cada criterio. El global se
calcula por puntos (🟢 = 2, 🟡 = 1, 🔴 = 0):

- **🟢 Verde** — 5-6 puntos y ningún criterio en rojo. Setup mecánicamente sólido.
- **🟡 Amarillo** — 3-4 puntos, o algún criterio en rojo pero el resto compensa.
- **🔴 Rojo** — algún criterio en rojo y pocos puntos. El setup tiene un problema claro.

El color **no dice "compra" o "no compres"**. Dice qué tan favorable está la
mecánica (precio de la prima, volatilidad, apalancamiento). La convicción sobre
la empresa y el tamaño de la posición los pones tú.

---

## COMPRAR CALL LEAPS (sustituto de acción)

| Criterio | 🟢 | 🟡 | 🔴 | Qué mide |
|---|---|---|---|---|
| **IV Rank** | ≤ 20 | 20–40 | > 40 | Qué tan barata está la volatilidad vs. su propio último año. Más bajo = pagas menos prima de tiempo. |
| **Subida a break-even** | < 10% | 10–20% | > 20% | Cuánto tiene que subir la acción para que empates al vencimiento. Es la "valla" que te pone la prima de tiempo. |
| **Apalancamiento efectivo** | ≥ 2.5× | 1.8–2.5× | < 1.8× | Por cada $1 que pones, a cuántos $ de acción quedas expuesto. Bajo = pagas mucha prima para poca ventaja. |

### Conceptos

**Prima = valor intrínseco + valor extrínseco (de tiempo)**
- *Intrínseco* = precio − strike. Ya lo "tienes", no se evapora.
- *Extrínseco* = lo que pagas de más por el tiempo. Es lo que se pierde si la
  acción no se mueve. La "subida a break-even" es básicamente extrínseco ÷ precio.

**Apalancamiento efectivo = (precio × delta) ÷ prima.**
Ejemplo QQQ: (718 × 0.78) ÷ 145.56 ≈ 3.8×. Con la misma plata que compra 20
acciones, el call sigue el movimiento de ~78 acciones. A cambio, QQQ debe subir
+7.3% en el año solo para empatar. Arriba de eso, el call multiplica la ganancia;
plano o abajo, sangra o se va a cero. El número baja hacia ~2× si la acción sube
fuerte (el delta se acerca a 1) y deja de ser ventaja si arranca cerca de 1×.

**Delta 0.70–0.85**: el contrato se mueve un 70–85% de lo que se mueve la acción,
casi como tenerla, con poco castigo por theta (decaimiento de tiempo).

### Lo que el sistema NO juzga
- **Convicción**: solo compra LEAPS en empresas donde ya tienes tesis fuerte de
  largo plazo. El correo dice "el setup está barato", no "la empresa es buena".
- **Tamaño**: 1 contrato = 100 acciones. Dimensiona por ese nominal, no por lo
  que costó la prima.

---

## VENDER PUT (generar prima / caja)

| Criterio | 🟢 | 🟡 | Qué mide |
|---|---|---|---|
| **IV Rank** | ≥ 65 | 55–65 | Volatilidad cara = prima más gorda por el mismo riesgo. |
| **Rendimiento anualizado** | ≥ 20% | 12–20% | Prima ÷ capital de garantía, llevado a base anual. |
| **Colchón a break-even** | ≥ 12% | 7–12% | Cuánto puede caer la acción antes de que empieces a perder. |

### Conceptos

**Rendimiento sobre garantía = prima ÷ strike.**
Ejemplo NU: cobras $0.34/acción con strike $14 → 2.4% sobre los $1.400 de
garantía en 45 días ≈ 20% anualizado.

**Break-even = strike − prima.** Bajo ese precio empiezas a perder. El colchón es
cuánto está ese punto por debajo del precio actual.

**Delta 0.20–0.30** ≈ 20–30% de probabilidad de que te asignen (termines
comprando la acción al strike).

### Lo que el sistema NO juzga
- ¿Te quedarías tranquilo **comprando la acción a ese strike** si te asignan? Si
  no, no vendas ese put — solo se venden puts sobre acciones que quieres tener.
- La garantía queda bloqueada hasta cerrar o vencer.

---

## Reglas de entrada (editables en `alert_rules`)

| | Vender PUT | Comprar CALL LEAPS |
|---|---|---|
| IV Rank | ≥ 55 | ≤ 40 |
| Delta (\|abs\|) | 0.20 – 0.30 | 0.70 – 0.85 |
| Días a vencimiento | 25 – 45 | 180 – 550 (prefiere ~365) |
| Strike | ≤ precio actual | — |

## Reglas de salida (Sección 10 de la spec — pendientes de construir)

**Call LEAPS comprada — tomar utilidad** si *cualquiera*:
- Ganancia ≥ 100% sobre la prima pagada
- Delta actual ≥ 0.90 (ya casi no hay ventaja de apalancamiento; rolar)
- IV Rank muy por encima del que tenía al comprar (el extrínseco se infló)

**Put vendido — recomprar y cerrar** si *cualquiera*:
- El put vale ≤ 25–30% de la prima cobrada (ya capturaste 70–75% de la ganancia)
- Menos de 7 días a vencimiento y sigue muy OTM (riesgo de gamma)
