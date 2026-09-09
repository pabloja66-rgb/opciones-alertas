# Despliegue: dejar el job corriendo solo en GitHub Actions

El job diario corre en los servidores de GitHub (gratis), no en el PC de Pablo.
Una vez montado, no hay que tocar nada.

## Opción A — Claude lo hace (más rápido)

Pablo crea un **token** y Claude sube el repo y configura todo:

1. Ve a **[github.com/settings/tokens](https://github.com/settings/tokens)** →
   *Generate new token* → **Fine-grained token**.
2. *Repository access*: **All repositories** (o creas antes un repo vacío
   `opciones-alertas` y eliges solo ese).
3. Permisos: **Contents** = Read and write, **Secrets** = Read and write,
   **Workflows** = Read and write, **Administration** = Read and write
   (para poder crear el repo).
4. Genera, copia el token (empieza con `github_pat_...`) y pásaselo a Claude.

Claude entonces: crea el repo privado, sube el código, carga los secrets y
lanza una primera corrida de prueba. Después puedes borrar el token.

## Opción B — Pablo lo hace por la web

1. **Crear el repo**: [github.com/new](https://github.com/new) → nombre
   `opciones-alertas` → **Private** → *Create*.

2. **Subir el código** (una vez, desde la carpeta del proyecto):
   ```
   cd C:\Users\pablo\opciones-alertas
   git remote add origin https://github.com/<tu-usuario>/opciones-alertas.git
   git push -u origin master
   ```
   (te pedirá usuario y una contraseña = un token de acceso personal)

3. **Cargar los secrets**: en el repo → **Settings** → *Secrets and variables*
   → **Actions** → *New repository secret*. Crea uno por cada línea:

   | Nombre | Valor |
   |---|---|
   | `ALPHAVANTAGE_API_KEY` | (tu API key de Alpha Vantage) |
   | `SUPABASE_URL` | `https://iryutxgqhozexjxydscl.supabase.co` |
   | `SUPABASE_SECRET_KEY` | (la `sb_secret_...`) |
   | `GMAIL_ADDRESS` | `pabloja66@gmail.com` |
   | `GMAIL_APP_PASSWORD` | (las 16 letras, sin espacios) |
   | `EMAIL_RECIPIENTS` | `pabloja66@gmail.com,simonjara2@hotmail.com` |
   | `DASHBOARD_URL` | (déjalo vacío por ahora) |

4. **Probar**: pestaña **Actions** → *Alertas de opciones (diario)* → *Run workflow*.

## Horario

`cron: "0 23 * * 1-5"` = 23:00 UTC, lunes a viernes (≈ 6-7 pm hora del Este,
después del cierre). GitHub puede retrasarlo unos minutos; no importa.
Para cambiarlo, edita `.github/workflows/daily.yml`.

## Qué hace cada corrida

`python src/daily_run.py`:
1. Captura la IV ATM del día → `iv_history`
2. Recalcula IV Rank → `iv_rank_cache`
3. Evalúa reglas → `alerts` (con anti-duplicados de 48 h)
4. Si hay alertas nuevas, manda el correo consolidado

Idempotente: si una corrida falla y se repite, no duplica datos.
