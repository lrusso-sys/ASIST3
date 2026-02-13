import flet as ft
import psycopg2
import psycopg2.extras
import hashlib
from datetime import date, datetime
import os
import base64
import io
import threading
import sys

# --- IMPORTACIÓN DE LIBRERÍAS EXTERNAS ---
print("--- Iniciando aplicación ---", flush=True)

try:
    import pandas as pd
except ImportError:
    pd = None
    print("⚠️ Pandas no instalado.")

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
    print("⚠️ XlsxWriter no instalado.")

# ==============================================================================
# CONFIGURACIÓN DE COLORES Y ESTILO (USANDO STRINGS)
# ==============================================================================
PRIMARY_COLOR = "indigo"
SECONDARY_COLOR = "indigo100" 
BG_COLOR = "grey50"
CARD_BG = "white"
TEXT_COLOR = "bluegrey900"
DANGER_COLOR = "red"
SUCCESS_COLOR = "green"

# ==============================================================================
# 1. BASE DE DATOS (PostgreSQL)
# ==============================================================================

def get_db_connection():
    """Obtiene conexión a PostgreSQL desde variables de entorno."""
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        if database_url:
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            conn = psycopg2.connect(database_url, sslmode='require')
            return conn
        else:
            # Fallback local
            return psycopg2.connect(
                host=os.environ.get('DB_HOST', 'localhost'),
                port=os.environ.get('DB_PORT', '5432'),
                database=os.environ.get('DB_NAME', 'postgres'),
                user=os.environ.get('DB_USER', 'postgres'),
                password=os.environ.get('DB_PASSWORD', 'password')
            )
    except Exception as e:
        print(f"❌ Error DB: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS Usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Ciclos (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 0)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Cursos (id SERIAL PRIMARY KEY, nombre TEXT, ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Alumnos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, nombre TEXT, dni TEXT, observaciones TEXT, tutor_nombre TEXT, tutor_telefono TEXT, UNIQUE(curso_id, nombre))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Asistencia (id SERIAL PRIMARY KEY, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, fecha TEXT, status TEXT, UNIQUE(alumno_id, fecha))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, descripcion TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos_Cumplidos (requisito_id INTEGER REFERENCES Requisitos(id) ON DELETE CASCADE, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, PRIMARY KEY (requisito_id, alumno_id))""")
            
            cur.execute("SELECT COUNT(*) FROM Usuarios")
            if cur.fetchone()[0] == 0:
                pwd = hashlib.sha256("admin".encode()).hexdigest()
                cur.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", ("admin", pwd, "admin"))
            
            cur.execute("SELECT COUNT(*) FROM Ciclos")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (str(date.today().year),))
        conn.commit()
    except Exception as e:
        print(f"Error Init DB: {e}")
    finally:
        conn.close()

# Helpers de DB
def run_query(query, params=(), fetch=False):
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch:
                return [dict(row) for row in cur.fetchall()]
            conn.commit()
            return True
    except Exception as e:
        print(f"Query Error: {e}")
        return None
    finally:
        conn.close()

def run_query_one(query, params=()):
    conn = get_db_connection()
    if not conn: return None
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        print(f"Query One Error: {e}")
        return None
    finally:
        conn.close()

# ==============================================================================
# 2. VISTAS Y COMPONENTES VISUALES
# ==============================================================================

def main(page: ft.Page):
    # Configuración Global de la Página
    page.title = "Asistencia UNSAM"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = BG_COLOR
    
    # Inicializar DB al arranque
    init_db()

    # Estado de sesión simple
    state = {
        "role": None,
        "username": None,
        "curso_id": None,
        "curso_nombre": None,
        "alumno_id": None
    }

    # --- COMPONENTES UI REUTILIZABLES ---

    def create_header(title, subtitle="", leading_action=None, trailing_action=None):
        """Crea una barra superior estilizada."""
        return ft.Container(
            content=ft.Row([
                ft.Row([
                    leading_action if leading_action else ft.Container(),
                    ft.Column([
                        ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(subtitle, size=12, color="white70") if subtitle else ft.Container()
                    ], spacing=2)
                ]),
                trailing_action if trailing_action else ft.Container()
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=20, vertical=15),
            bgcolor=PRIMARY_COLOR,
            shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2))
        )

    def create_card(content, padding=20):
        """Contenedor estilo tarjeta Material Design."""
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=CARD_BG,
            border_radius=12,
            shadow=ft.BoxShadow(
                blur_radius=10,
                spread_radius=1,
                color=ft.colors.with_opacity(0.08, "black"),
                offset=ft.Offset(0, 4)
            ),
            margin=ft.margin.only(bottom=10)
        )

    def show_snack(message, is_error=False):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(message),
            bgcolor="red600" if is_error else "green600",
        )
        page.snack_bar.open = True
        page.update()

    # --- VISTAS ---

    def view_login():
        user = ft.TextField(label="Usuario", prefix_icon="person", width=300, border_radius=10, bgcolor="white")
        pwd = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, prefix_icon="lock", width=300, border_radius=10, bgcolor="white")

        def login_click(e):
            if not user.value or not pwd.value: return show_snack("Complete los campos", True)
            
            hashed = hashlib.sha256(pwd.value.encode()).hexdigest()
            # Login con Postgres
            u_data = run_query_one("SELECT * FROM Usuarios WHERE username=%s", (user.value,))
            
            if u_data and u_data['password'] == hashed:
                state["role"] = u_data['role']
                state["username"] = user.value
                page.go("/dashboard")
            else:
                show_snack("Usuario o contraseña inválidos", True)

        return ft.View("/", [
            ft.Container(
                content=ft.Column([
                    ft.Icon("school_rounded", size=80, color=PRIMARY_COLOR),
                    ft.Text("Bienvenido", size=30, weight=ft.FontWeight.BOLD, color=PRIMARY_COLOR),
                    ft.Text("Sistema de Gestión UNSAM", size=16, color="grey600"),
                    ft.Divider(height=40, color="transparent"),
                    user,
                    pwd,
                    ft.Container(height=20),
                    ft.ElevatedButton(
                        "INICIAR SESIÓN", 
                        on_click=login_click, 
                        width=300, height=50, 
                        bgcolor=PRIMARY_COLOR, color="white",
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), elevation=5)
                    ),
                    ft.Text("Admin default: admin / admin", size=12, color="grey")
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.alignment.center,
                expand=True,
                # Fondo con gradiente sutil
                gradient=ft.LinearGradient(
                    begin=ft.alignment.top_center,
                    end=ft.alignment.bottom_center,
                    colors=["blue50", "white"]
                )
            )
        ])

    def view_dashboard():
        ciclo = run_query_one("SELECT * FROM Ciclos WHERE activo = 1")
        ciclo_nombre = ciclo['nombre'] if ciclo else "Sin Ciclo Activo"
        
        # Grid de Cursos
        cursos_grid = ft.GridView(
            runs_count=2, # 2 columnas en movil/web
            max_extent=400,
            child_aspect_ratio=2.5,
            spacing=15,
            run_spacing=15,
        )

        def load_cursos():
            cursos_grid.controls.clear()
            if not ciclo:
                cursos_grid.controls.append(ft.Text("No hay ciclo lectivo activo."))
                return

            cursos = run_query("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],), fetch=True)
            for c in cursos:
                def go_curso(e, cid=c['id'], cn=c['nombre']):
                    state["curso_id"] = cid
                    state["curso_nombre"] = cn
                    page.go("/curso")

                # Tarjeta de Curso
                card = ft.Container(
                    content=ft.Row([
                        ft.Row([
                            ft.Container(
                                content=ft.Icon("class_", color="white"),
                                bgcolor=PRIMARY_COLOR, border_radius=10, padding=12
                            ),
                            ft.Text(c['nombre'], size=18, weight=ft.FontWeight.W_600, color=TEXT_COLOR)
                        ]),
                        ft.Icon("chevron_right", color="grey400")
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=15,
                    bgcolor=CARD_BG,
                    border_radius=15,
                    shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2)),
                    on_click=go_curso,
                    ink=True
                )
                cursos_grid.controls.append(card)
            page.update()

        load_cursos()

        # Botón flotante para agregar (solo admin)
        fab = None
        if state["role"] == "admin":
            def add_curso_dlg(e):
                tf = ft.TextField(label="Nombre del Curso")
                def save(e):
                    if not ciclo: return show_snack("Active un ciclo primero", True)
                    if tf.value:
                        run_query("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (tf.value, ciclo['id']))
                        page.close_dialog()
                        load_cursos()
                page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Curso"), content=tf, actions=[ft.TextButton("Guardar", on_click=save)])
                page.dialog.open = True
                page.update()
            
            fab = ft.FloatingActionButton(icon="add", on_click=add_curso_dlg, bgcolor=PRIMARY_COLOR)

        return ft.View("/dashboard", [
            create_header(
                "Panel Principal", 
                f"Ciclo Lectivo: {ciclo_nombre}", 
                trailing_action=ft.IconButton("logout", icon_color="white", tooltip="Salir", on_click=lambda _: page.go("/"))
            ),
            ft.Container(
                content=ft.Column([
                    ft.Text("Mis Cursos", size=22, weight=ft.FontWeight.BOLD, color=TEXT_COLOR),
                    ft.Divider(height=20, color="transparent"),
                    cursos_grid
                ], expand=True),
                padding=20, expand=True
            )
        ], floating_action_button=fab)

    def view_curso_detail():
        if not state["curso_id"]: return view_dashboard()
        
        # --- TAB 1: LISTADO ALUMNOS ---
        alumnos_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        def load_alumnos():
            alumnos_col.controls.clear()
            rows = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            for r in rows:
                # Avatar con inicial
                avatar = ft.CircleAvatar(
                    content=ft.Text(r['nombre'][0].upper()),
                    bgcolor=SECONDARY_COLOR, 
                    color=PRIMARY_COLOR
                )
                
                # Fila de Alumno
                tile = create_card(
                    ft.ListTile(
                        leading=avatar,
                        title=ft.Text(r['nombre'], weight=ft.FontWeight.BOLD),
                        subtitle=ft.Text(f"DNI: {r['dni'] or 'S/D'}"),
                        trailing=ft.IconButton("edit", icon_color="grey", on_click=lambda e, s=r: open_edit_student(s)),
                        on_click=lambda e, s=r: open_student_detail(s) # Ir a ficha
                    ), padding=0
                )
                alumnos_col.controls.append(tile)
            page.update()

        # --- TAB 2: ASISTENCIA RÁPIDA ---
        asist_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        date_pk = ft.TextField(label="Fecha", value=date.today().isoformat(), width=150, height=40, text_size=14)
        
        def load_asistencia_ui(e=None):
            asist_col.controls.clear()
            fecha = date_pk.value
            # Obtener guardados
            guardados = run_query("SELECT alumno_id, status FROM Asistencia WHERE fecha=%s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, state["curso_id"]), fetch=True)
            mapa = {g['alumno_id']: g['status'] for g in guardados}
            
            alumnos = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            
            # UI de lista de asistencia
            for a in alumnos:
                status_val = mapa.get(a['id'], "P")
                
                # Selector de estado
                dd = ft.Dropdown(
                    width=100, 
                    height=40,
                    text_size=14,
                    value=status_val,
                    options=[
                        ft.dropdown.Option("P"), ft.dropdown.Option("T"), 
                        ft.dropdown.Option("A"), ft.dropdown.Option("J")
                    ],
                    on_change=lambda e, aid=a['id']: save_single_assist(aid, fecha, e.control.value)
                )
                
                row = ft.Container(
                    content=ft.Row([
                        ft.Text(a['nombre'], expand=True, weight=ft.FontWeight.W_500),
                        dd
                    ]),
                    padding=ft.padding.symmetric(vertical=5),
                    border=ft.border.only(bottom=ft.border.BorderSide(1, "grey200"))
                )
                asist_col.controls.append(row)
            page.update()

        def save_single_assist(aid, fecha, status):
            # Guardado automático al cambiar el dropdown (UX moderna)
            query = """
                INSERT INTO Asistencia (alumno_id, fecha, status) VALUES (%s, %s, %s)
                ON CONFLICT (alumno_id, fecha) DO UPDATE SET status = EXCLUDED.status
            """
            run_query(query, (aid, fecha, status))

        # --- TAB 3: REPORTES ---
        report_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        def load_report_ui():
            # Generar tabla simple
            # (Aquí iría la lógica compleja de reportes, simplificada para UI)
            btn_export = ft.ElevatedButton("Exportar Excel Completo", icon="download", 
                                           bgcolor="green700", color="white", 
                                           on_click=export_excel_action)
            report_col.controls = [
                ft.Text("Resumen del Ciclo Lectivo", size=16, weight="bold"),
                ft.Container(height=10),
                btn_export,
                # Aquí podrías agregar una DataTable de Flet si quisieras mostrarlo en pantalla
            ]

        def export_excel_action(e):
            if not pd or not xlsxwriter: return show_snack("Faltan librerías de Excel", True)
            
            # Lógica de reporte
            alumnos = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            # Fetch masivo de asistencia
            asistencias = run_query("SELECT * FROM Asistencia WHERE alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (state["curso_id"],), fetch=True)
            
            # Procesar datos
            data_list = []
            for a in alumnos:
                a_asist = [x for x in asistencias if x['alumno_id'] == a['id']]
                counts = {k: 0 for k in ['P','T','A','J']}
                for r in a_asist:
                    if r['status'] in counts: counts[r['status']] += 1
                
                total_faltas = counts['A'] + (counts['T'] * 0.5) # Ejemplo de regla
                data_list.append({
                    "Alumno": a['nombre'], "DNI": a['dni'], 
                    "Pres": counts['P'], "Aus": counts['A'], "Faltas Eq": total_faltas
                })
            
            # Crear Excel
            df = pd.DataFrame(data_list)
            bio = io.BytesIO()
            df.to_excel(bio, index=False)
            b64 = base64.b64encode(bio.getvalue()).decode()
            page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="reporte.xlsx")


        # --- ESTRUCTURA DE TABS ---
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=300,
            tabs=[
                ft.Tab(text="Alumnos", icon="people", content=ft.Container(content=alumnos_col, padding=10)),
                ft.Tab(text="Asistencia", icon="check_circle", content=ft.Container(content=ft.Column([
                    ft.Row([date_pk, ft.IconButton("refresh", on_click=load_asistencia_ui)]),
                    ft.Divider(),
                    asist_col
                ]), padding=10)),
                ft.Tab(text="Reportes", icon="bar_chart", content=ft.Container(content=report_col, padding=10))
            ],
            expand=True,
            on_change=lambda e: load_tab_data(e.control.selected_index)
        )

        def load_tab_data(index):
            if index == 0: load_alumnos()
            elif index == 1: load_asistencia_ui()
            elif index == 2: load_report_ui()

        # Carga inicial
        load_alumnos()

        # Modal Agregar Alumno
        def open_add_student(e):
            nm = ft.TextField(label="Nombre")
            dn = ft.TextField(label="DNI")
            def save(e):
                if nm.value:
                    run_query("INSERT INTO Alumnos (curso_id, nombre, dni) VALUES (%s, %s, %s)", (state["curso_id"], nm.value, dn.value))
                    page.close_dialog()
                    load_alumnos()
            page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Alumno"), content=ft.Column([nm, dn], height=150), actions=[ft.TextButton("Guardar", on_click=save)])
            page.dialog.open = True
            page.update()
        
        # Modal Editar/Ver
        def open_edit_student(student):
            # Similar a add pero con UPDATE
            pass # (Simplificado para brevedad)

        def open_student_detail(student):
            state["alumno_id"] = student['id']
            # Aquí podrías navegar a una vista detallada, pero por ahora mostramos un SnackBar
            show_snack(f"Seleccionado: {student['nombre']}")

        return ft.View("/curso", [
            create_header(state["curso_nombre"], "Gestión del Curso", leading_action=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=tabs, expand=True, bgcolor=BG_COLOR),
            ft.FloatingActionButton(icon="add", on_click=open_add_student, bgcolor=PRIMARY_COLOR)
        ])

    # --- RUTAS ---
    def route_change(route):
        page.views.clear()
        
        if page.route == "/":
            page.views.append(view_login())
        elif page.route == "/dashboard":
            page.views.append(view_dashboard())
        elif page.route == "/curso":
            page.views.append(view_curso_detail())
        
        page.update()

    def view_pop(view):
        page.views.pop()
        top_view = page.views[-1]
        page.go(top_view.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    page.go("/")

if __name__ == "__main__":
    port_env = os.environ.get("PORT")
    
    if port_env:
        # === MODO RENDER/PRODUCCIÓN ===
        # IMPORTANTE: No usar WEB_BROWSER en producción
        # Usar FLET_APP_WEB para servir como web app
        ft.app(
            target=main, 
            view=ft.AppView.FLET_APP_WEB,  # ← CAMBIO CRÍTICO
            port=int(port_env), 
            host="0.0.0.0"
        )
    else:
        # === MODO LOCAL ===
        ft.app(
            target=main, 
            view=ft.AppView.WEB_BROWSER,  # Esto sí funciona localmente
            port=8550
        )
