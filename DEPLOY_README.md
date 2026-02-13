# Errores Corregidos para Deploy en Render

## ❌ Errores Encontrados y Solucionados

### 1. **ERROR CRÍTICO: Método `delete_alumno` no existía**
- **Problema**: En `view_curso` se llamaba a `db.delete_alumno(aid)` pero este método no estaba definido en `DatabaseManager`
- **Solución**: Agregado el método completo con manejo de transacciones SQL

### 2. **ERROR CRÍTICO: Íconos de Material en formato string**
- **Problema**: Flet usa `ft.icons.NOMBRE` no strings como `"school"`
- **Solución**: Todos los íconos cambiados a formato `ft.icons.NOMBRE` (ej: `ft.icons.SCHOOL`, `ft.icons.PERSON`)

### 3. **ERROR CRÍTICO: `AppView.WEB_BROWSER` no funciona en Render**
- **Problema**: `WEB_BROWSER` intenta abrir un navegador local que no existe en el servidor
- **Solución**: Cambiado a `view=None` cuando corre en producción (PORT está definido)

### 4. **ERROR: `xlsxwriter` no estaba definido cuando fallaba import**
- **Problema**: `except ImportError: print(...)` no asignaba `xlsxwriter = None`
- **Solución**: Agregada la asignación `xlsxwriter = None`

### 5. **ERROR: PopupMenuItem requiere `text=` explícito**
- **Problema**: `ft.PopupMenuItem("Editar", ...)` debe ser `ft.PopupMenuItem(text="Editar", ...)`
- **Solución**: Agregado el parámetro `text=` en todos los PopupMenuItem

### 6. **ERROR: Falta `requirements.txt`**
- **Problema**: Render no sabe qué dependencias instalar
- **Solución**: Creado archivo `requirements.txt` con flet, pandas y xlsxwriter

### 7. **ADVERTENCIA: Manejo de sesiones en Flet Web**
- **Nota**: `page.session` en Flet web puede no persistir entre navegaciones dependiendo de la configuración
- **Recomendación**: Considerar usar `page.client_storage` para datos persistentes en el navegador

---

## 📁 Archivos a Subir al Repositorio

```
.
├── main_fixed.py       # Código corregido (renómbralo a main.py)
├── requirements.txt    # Dependencias obligatorias
└── render.yaml         # Configuración de Render (opcional)
```

---

## 🚀 Instrucciones de Deploy en Render

1. **Crea un nuevo Web Service** en Render
2. **Conecta tu repositorio** de GitHub/GitLab
3. **Configuración:**
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main_fixed.py`
4. **Agrega variable de entorno** (opcional):
   - `PYTHON_VERSION`: `3.11.0`

---

## ⚠️ Notas Importantes para Render

### Base de Datos SQLite
- SQLite en Render es **EFÍMERO** (se borra en cada deploy/reinicio)
- Para producción real, considera:
  - PostgreSQL (Render tiene add-on gratuito)
  - O acepta que los datos se reiniciarán

### Persistencia de Sesión
- Las sesiones de Flet en modo web pueden no persistir correctamente
- Si hay problemas de login, considera implementar JWT o similar

---

## 🔧 Cambios Realizados en el Código

| Archivo | Líneas Cambiadas | Descripción |
|---------|-----------------|-------------|
| `main_fixed.py` | ~50 | Corrección de íconos, métodos faltantes, configuración de deploy |
| `requirements.txt` | Nuevo | Dependencias necesarias |
| `render.yaml` | Nuevo | Configuración de Render |
