# Migración a PostgreSQL - Guía de Deploy

## Cambios Realizados

### 1. DatabaseManager Migrado a PostgreSQL

| Aspecto | SQLite | PostgreSQL |
|---------|--------|------------|
| Librería | `sqlite3` | `psycopg2` |
| Placeholders | `?` | `%s` |
| Autoincremental | `INTEGER PRIMARY KEY AUTOINCREMENT` | `SERIAL PRIMARY KEY` |
| Booleanos | `0/1` | `TRUE/FALSE` |
| Upsert | `INSERT OR REPLACE` | `ON CONFLICT ... DO UPDATE` |
| Búsqueda case-insensitive | `LIKE` | `ILIKE` |

### 2. Conexión a Base de Datos

```python
# Render proporciona DATABASE_URL automáticamente
database_url = os.environ.get('DATABASE_URL')

# Para desarrollo local, usa variables de entorno:
DB_HOST=localhost
DB_PORT=5432
DB_NAME=asistencia_db
DB_USER=postgres
DB_PASSWORD=password
```

---

## 🚀 Instrucciones de Deploy en Render

### Paso 1: Crear Base de Datos PostgreSQL

1. Ve a tu dashboard de Render
2. Click en **"New"** → **"PostgreSQL"**
3. Configura:
   - **Name**: `asistencia-db`
   - **Database**: `asistencia_db`
   - **User**: `asistencia_user`
   - **Plan**: Free
4. Click **"Create Database"**

### Paso 2: Crear Web Service

1. Click en **"New"** → **"Web Service"**
2. Conecta tu repositorio de GitHub/GitLab
3. Configura:
   - **Name**: `asistencia-unsam`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`

### Paso 3: Variables de Entorno

Render configura `DATABASE_URL` automáticamente cuando vinculas la base de datos.

Si necesitas configurar manualmente (desarrollo local):

```bash
# Linux/Mac
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=asistencia_db
export DB_USER=postgres
export DB_PASSWORD=tu_password

# Windows
set DB_HOST=localhost
set DB_PORT=5432
set DB_NAME=asistencia_db
set DB_USER=postgres
set DB_PASSWORD=tu_password
```

---

## 📁 Archivos a Subir

```
.
├── main.py              # Código principal (renombrado de main_postgres.py)
├── requirements.txt     # Dependencias (renombrado de requirements_postgres.txt)
└── render.yaml          # Opcional - config como código
```

---

## 🧪 Prueba Local con PostgreSQL

### 1. Instalar PostgreSQL

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install postgresql postgresql-contrib
```

**Mac (Homebrew):**
```bash
brew install postgresql
brew services start postgresql
```

**Windows:**
Descarga el instalador de https://www.postgresql.org/download/windows/

### 2. Crear Base de Datos

```bash
sudo -u postgres psql

CREATE DATABASE asistencia_db;
CREATE USER asistencia_user WITH PASSWORD 'tu_password';
GRANT ALL PRIVILEGES ON DATABASE asistencia_db TO asistencia_user;
\q
```

### 3. Configurar Variables de Entorno

```bash
export DB_HOST=localhost
export DB_PORT=5432
export DB_NAME=asistencia_db
export DB_USER=asistencia_user
export DB_PASSWORD=tu_password
```

### 4. Instalar Dependencias y Ejecutar

```bash
pip install -r requirements.txt
python main.py
```

---

## ✅ Ventajas de PostgreSQL sobre SQLite

| Característica | SQLite | PostgreSQL |
|----------------|--------|------------|
| **Persistencia** | ❌ Se borra al reiniciar | ✅ Datos persistentes |
| **Concurrencia** | ⚠️ Limitada | ✅ Alta concurrencia |
| **Escalabilidad** | ❌ Local solo | ✅ Escalable |
| **Backups** | ❌ Manual | ✅ Automáticos en Render |
| **Múltiples usuarios** | ⚠️ Problemas | ✅ Sin problemas |

---

## 🔧 Troubleshooting

### Error: "database does not exist"
```bash
# Crear la base de datos manualmente
sudo -u postgres createdb asistencia_db
```

### Error: "password authentication failed"
```bash
# Verificar usuario y contraseña
sudo -u postgres psql -c "\du"
```

### Error: "could not connect to server"
```bash
# Verificar que PostgreSQL está corriendo
sudo systemctl status postgresql
```

### Error en Render: "DATABASE_URL not found"
- Asegúrate de haber vinculado la base de datos al web service
- Ve a Settings → Environment → Link Database

---

## 📊 Estructura de la Base de Datos

```sql
-- Tablas creadas automáticamente
Usuarios (id, username, password, role)
Ciclos (id, nombre, activo)
Cursos (id, nombre, ciclo_id)
Alumnos (id, curso_id, nombre, dni, observaciones, tutor_nombre, tutor_telefono)
Asistencia (id, alumno_id, fecha, status)
Requisitos (id, curso_id, descripcion)
Requisitos_Cumplidos (requisito_id, alumno_id)
```

---

## 📝 Notas Importantes

1. **Datos semilla**: El usuario `admin` con contraseña `admin` se crea automáticamente
2. **Ciclo activo**: Se crea automáticamente con el año actual
3. **SSL**: La conexión usa `sslmode='require'` en producción (Render)
4. **Migraciones**: Las tablas se crean automáticamente al iniciar la app
