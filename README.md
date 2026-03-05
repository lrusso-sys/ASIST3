🏫 Sistema de Gestión de Asistencia - ETEC UNSAM

Este proyecto es un sistema web mobile-friendly desarrollado para digitalizar, agilizar y centralizar la toma de asistencia y la gestión de legajos de alumnos en la Escuela Secundaria Técnica de la UNSAM. Está diseñado específicamente para facilitar el trabajo diario de los preceptores, permitiendo la carga de datos directamente desde el patio o el aula usando un celular.

✨ Características Principales
📱 Diseño Responsivo: Interfaz optimizada para celulares y computadoras de escritorio.

👥 Roles de Usuario: Accesos diferenciados para Administradores (configuración de ciclos, cursos y usuarios) y Preceptores (toma de lista y gestión de sus cursos asignados).

✅ Toma de Asistencia Inteligente:

Cálculo automático de inasistencias adaptado a jornadas de doble escolaridad:

Presente, Ausente, Justificado, Suspendido.

Llegadas Tarde (TM/TT) = 0.25 faltas.

Medias Faltas (MFM/MFT) = 0.5 faltas.

Guardado automático ("el que calla otorga") para agilizar la toma de lista.

⚠️ Trayectorias Personalizadas (TPP): Soporte para alumnos que solo asisten días específicos de la semana (se anula la falta los días que no les corresponde ir).

📅 Gestión de Feriados: El sistema alerta a los preceptores si intentan tomar asistencia en un día feriado o fin de semana.

📂 Gestión de Legajos: Control de entrega de documentación respaldatoria por curso.

📥 Importación Masiva: Carga rápida de listas de alumnos mediante archivos Excel (.xlsx).

📊 Exportación de Reportes: Generación automática de informes en Excel tanto a nivel Curso (resumen) como a nivel Alumno (historial detallado).

🛠️ Tecnologías Utilizadas
Backend & Frontend: Python + Flet (Framework UI).

Base de Datos: PostgreSQL.

Manejo de Excels: xlsxwriter (exportación) y openpyxl (importación).

Despliegue: Preparado para funcionar en la nube (Ej: Render, Railway, Heroku).

🚀 Instalación y Uso Local
Si querés correr el proyecto en tu propia computadora para hacer pruebas:

Clonar el repositorio y crear un entorno virtual:

Bash
git clone <tu-repo-url>
cd asistencia-unsam
python -m venv venv
source venv/Scripts/activate  # En Windows
# source venv/bin/activate    # En Linux/Mac
Instalar las dependencias:
Asegurate de tener un archivo requirements.txt con lo siguiente:

Plaintext
flet
psycopg2-binary
xlsxwriter
openpyxl
Luego ejecutá:

Bash
pip install -r requirements.txt
Configurar la Base de Datos:
El sistema requiere PostgreSQL. Podés usar una base de datos local o en la nube. Configurá la variable de entorno:

DATABASE_URL = postgresql://usuario:clave@host:puerto/nombre_db

Ejecutar la aplicación:

Bash
python main.py
(Nota: Al iniciar por primera vez con una base de datos vacía, el sistema creará automáticamente las tablas y un usuario administrador por defecto: Usuario admin, Clave admin).

📄 Formato para Importar Alumnos (Excel)
Para hacer una carga masiva de estudiantes, el preceptor debe subir un archivo .xlsx. La primera fila (encabezados) es ignorada por el sistema. El orden estricto de las columnas debe ser:

Columna A: Nombre Completo (Obligatorio)

Columna B: DNI

Columna C: Nombre del Tutor

Columna D: Teléfono del Tutor

Columna E: Observaciones

🔒 Seguridad
Las contraseñas de los usuarios se encriptan en la base de datos mediante hashing SHA-256.

Cambio de clave habilitado desde el panel principal para todos los usuarios.

Desarrollado para modernizar la gestión escolar. 🚀
