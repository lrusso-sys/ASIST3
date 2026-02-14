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
    print("⚠️ Pandas no instalado. La exportación a Excel estará deshabilitada.")

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
    print("⚠️ XlsxWriter no instalado. La exportación a Excel estará deshabilitada.")

# ==============================================================================
# CONFIGURACIÓN DE COLORES Y ESTILO
# ==============================================================================
PRIMARY_COLOR = "indigo"
SECONDARY_COLOR = "indigo100" 
BG_COLOR = "grey50"
CARD_BG = "white"
TEXT_COLOR = "bluegrey900"
DANGER_COLOR = "red"
SUCCESS_COLOR = "green"
WARNING_COLOR = "orange"

# ==============================================================================
# 1. BASE DE DATOS (POSTGRESQL)
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
            print("⚠️ No se detectó DATABASE_URL. Intentando conexión local...", flush=True)
            return psycopg2.connect(
                host=os.environ.get('DB_HOST', 'localhost'),
                port=os.environ.get('DB_PORT', '5432'),
                database=os.environ.get('DB_NAME', 'postgres'),
                user=os.environ.get('DB_USER', 'postgres'),
                password=os.environ.get('DB_PASSWORD', 'password')
            )
    except Exception as e:
        print(f"❌ Error de conexión a DB: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: 
        print("❌ CRÍTICO: Sin conexión a DB.", flush=True)
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS Usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Ciclos (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 0)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Cursos (id SERIAL PRIMARY KEY, nombre TEXT, ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Alumnos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, nombre TEXT, dni TEXT, observaciones TEXT, tutor_nombre TEXT, tutor_telefono TEXT, tpp INTEGER DEFAULT 0, tpp_dias TEXT, UNIQUE(curso_id, nombre))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Asistencia (id SERIAL PRIMARY KEY, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, fecha TEXT, status TEXT, UNIQUE(alumno_id, fecha))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, descripcion TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos_Cumplidos (requisito_id INTEGER REFERENCES Requisitos(id) ON DELETE CASCADE, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, PRIMARY KEY (requisito_id, alumno_id))""")
            
            # Migraciones TPP
            try:
                cur.execute("ALTER TABLE Alumnos ADD COLUMN tpp INTEGER DEFAULT 0")
                conn.commit()
            except: conn.rollback()

            try:
                cur.execute("ALTER TABLE Alumnos ADD COLUMN tpp_dias TEXT")
                conn.commit()
            except: conn.rollback()

            # Datos Semilla
            cur.execute("SELECT COUNT(*) FROM Usuarios")
            if cur.fetchone()[0] == 0:
                pwd = hashlib.sha256("admin".encode()).hexdigest()
                cur.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", ("admin", pwd, "admin"))
            
            cur.execute("SELECT COUNT(*) FROM Ciclos")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (str(date.today().year),))
        conn.commit()
        print("✅ DB Inicializada.")
    except Exception as e:
        print(f"❌ Error Init DB: {e}")
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

# Funciones de transacción específicas para Admin (Ciclos)
def db_add_ciclo(nombre):
    conn = get_db_connection()
    if not conn: return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE Ciclos SET activo = 0") # Desactivar otros
            cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (nombre,))
        conn.commit()
        return True
    except Exception as e:
        print(f"Error add_ciclo: {e}")
        conn.rollback()
        return False
    finally: conn.close()

def db_activar_ciclo(cid):
    conn = get_db_connection()
    if not conn: return
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE Ciclos SET activo = 0")
            cur.execute("UPDATE Ciclos SET activo = 1 WHERE id = %s", (cid,))
        conn.commit()
    except: conn.rollback()
    finally: conn.close()

# ==============================================================================
# 2. VISTAS Y COMPONENTES VISUALES
# ==============================================================================

def main(page: ft.Page):
    page.title = "Asistencia UNSAM"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = BG_COLOR
    
    init_db()

    state = {
        "role": None,
        "username": None,
        "curso_id": None,
        "curso_nombre": None,
        "alumno_id": None
    }

    # --- COMPONENTES UI REUTILIZABLES ---

    def create_header(title, subtitle="", leading_action=None, trailing_action=None):
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
        snack = ft.SnackBar(
            content=ft.Text(message),
            bgcolor="red600" if is_error else "green600",
        )
        page.open(snack)

    # --- SERVICIOS ---
    
    class AdminService:
        @staticmethod
        def get_ciclos(): return run_query("SELECT * FROM Ciclos ORDER BY nombre DESC", fetch=True)
        @staticmethod
        def add_ciclo(nombre): return db_add_ciclo(nombre)
        @staticmethod
        def activar_ciclo(cid): db_activar_ciclo(cid)
        
        @staticmethod
        def get_users(): return run_query("SELECT * FROM Usuarios ORDER BY username", fetch=True)
        @staticmethod
        def add_user(u, p, r): 
            pwd = hashlib.sha256(p.encode()).hexdigest()
            return run_query("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", (u, pwd, r))
        @staticmethod
        def delete_user(uid): return run_query("DELETE FROM Usuarios WHERE id=%s", (uid,))

    # --- VISTAS ---

    def view_login():
        user = ft.TextField(label="Usuario", prefix_icon="person", width=300, border_radius=10, bgcolor="white")
        pwd = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, prefix_icon="lock", width=300, border_radius=10, bgcolor="white")

        def login_click(e):
            if not user.value or not pwd.value: return show_snack("Complete los campos", True)
            hashed = hashlib.sha256(pwd.value.encode()).hexdigest()
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
                    ft.ElevatedButton("INICIAR SESIÓN", on_click=login_click, width=300, height=45, bgcolor=PRIMARY_COLOR, color=ft.colors.WHITE, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=10), elevation=5)),
                    ft.Text("Admin default: admin / admin", size=12, color="grey")
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.alignment.center, expand=True,
                gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center, colors=["blue50", "white"])
            )
        ])

    def view_dashboard():
        # Elementos de UI
        text_ciclo_status = ft.Text("Cargando...", weight=ft.FontWeight.BOLD, color=PRIMARY_COLOR)
        search_input = ft.TextField(hint_text="Buscar alumno...", expand=True, bgcolor="white", border_radius=20, border_color="transparent", prefix_icon="search")
        cursos_grid = ft.GridView(runs_count=2, max_extent=400, child_aspect_ratio=2.5, spacing=15, run_spacing=15)
        
        # Referencia mutable para guardar el ID del ciclo activo en el contexto del dashboard
        active_cycle_ref = {"id": None} 

        def search_action(e):
            if search_input.value:
                page.session.set("search_term", search_input.value)
                page.go("/search")
        search_input.on_submit = search_action

        def load_dashboard_data():
            """Función central para refrescar todo el dashboard."""
            # 1. Obtener Ciclo Activo Fresco
            ciclo = run_query_one("SELECT * FROM Ciclos WHERE activo = 1")
            
            cursos_grid.controls.clear()
            
            if ciclo:
                active_cycle_ref["id"] = ciclo['id']
                text_ciclo_status.value = f"Ciclo Lectivo: {ciclo['nombre']}"
                text_ciclo_status.color = PRIMARY_COLOR
                
                # 2. Cargar cursos de ese ciclo
                cursos = run_query("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],), fetch=True)
                
                if not cursos:
                    cursos_grid.controls.append(ft.Text("No hay cursos creados en este ciclo.", italic=True, color="grey"))
                
                for c in cursos:
                    def go_curso(e, cid=c['id'], cn=c['nombre']):
                        state["curso_id"] = cid
                        state["curso_nombre"] = cn
                        page.go("/curso")

                    def delete_c(e, cid=c['id']):
                         run_query("DELETE FROM Cursos WHERE id=%s", (cid,))
                         load_dashboard_data() # Recargar dashboard
                         page.update()

                    card = ft.Container(
                        content=ft.Row([
                            ft.Row([
                                ft.Container(content=ft.Icon("class_", color="white"), bgcolor=PRIMARY_COLOR, border_radius=10, padding=12),
                                ft.Text(c['nombre'], size=18, weight=ft.FontWeight.W_600, color=TEXT_COLOR)
                            ]),
                            ft.Row([
                                ft.IconButton("arrow_forward", icon_color=PRIMARY_COLOR, on_click=go_curso),
                                ft.IconButton("delete", icon_color=DANGER_COLOR, on_click=delete_c) if state["role"] == "admin" else ft.Container()
                            ])
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=15, bgcolor=CARD_BG, border_radius=15,
                        shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2)),
                        on_click=go_curso, ink=True
                    )
                    cursos_grid.controls.append(card)
            else:
                active_cycle_ref["id"] = None
                text_ciclo_status.value = "⚠️ No hay ciclo lectivo activo. Configure uno en Admin."
                text_ciclo_status.color = DANGER_COLOR
                cursos_grid.controls.append(ft.Text("Configure un ciclo lectivo para ver los cursos."))

            page.update()

        # Botón Flotante (Admin)
        fab = None
        if state["role"] == "admin":
            def add_curso_dlg(e):
                # Verificar ciclo AL MOMENTO de hacer click
                if not active_cycle_ref["id"]:
                    return show_snack("¡Error! No hay un ciclo lectivo activo. Vaya a Admin -> Ciclos.", True)

                tf = ft.TextField(label="Nombre del Curso")
                dlg = ft.AlertDialog(title=ft.Text("Nuevo Curso"), content=tf)
                
                def save(e):
                    if tf.value:
                        if run_query("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (tf.value, active_cycle_ref["id"])):
                            page.close(dlg)
                            load_dashboard_data() # Recargar dashboard
                            show_snack("Curso creado")
                        else:
                            show_snack("Error al crear curso", True)
                
                dlg.actions = [ft.TextButton("Guardar", on_click=save)]
                page.open(dlg)
                page.update()
            
            fab = ft.FloatingActionButton(icon="add", on_click=add_curso_dlg, bgcolor=PRIMARY_COLOR)

        # Cargar datos iniciales
        load_dashboard_data()

        actions = [ft.IconButton("logout", icon_color="white", tooltip="Salir", on_click=lambda _: page.go("/"))]
        if state["role"]=="admin": actions.insert(0, ft.IconButton("settings", icon_color="white", tooltip="Configuración", on_click=lambda _: page.go("/admin")))

        return ft.View("/dashboard", [
            create_header("Panel Principal", "", trailing_action=ft.Row(actions, spacing=0, tight=True)),
            ft.Container(content=ft.Column([
                ft.Container(content=text_ciclo_status, padding=ft.padding.only(bottom=5)),
                ft.Container(content=search_input, padding=ft.padding.only(bottom=20)),
                ft.Text("Mis Cursos", size=22, weight=ft.FontWeight.BOLD, color=TEXT_COLOR),
                ft.Divider(height=20, color="transparent"),
                cursos_grid
            ], expand=True), padding=20, expand=True)
        ], floating_action_button=fab)

    def view_admin():
        if state["role"] != "admin": return ft.View("/error", [ft.Text("Acceso Denegado")])
        
        return ft.View("/admin", [
            create_header("Administración", "Configuración", leading_action=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=ft.Column([
                create_card(ft.ListTile(
                    leading=ft.Icon("calendar_month", color=PRIMARY_COLOR, size=30),
                    title=ft.Text("Ciclos Lectivos", weight="bold"),
                    subtitle=ft.Text("Crear, activar y cerrar años escolares"),
                    on_click=lambda _: page.go("/ciclos"),
                    trailing=ft.Icon("chevron_right")
                )),
                create_card(ft.ListTile(
                    leading=ft.Icon("people", color=PRIMARY_COLOR, size=30),
                    title=ft.Text("Gestión de Usuarios"),
                    subtitle=ft.Text("Administrar preceptores y administradores"),
                    on_click=lambda _: page.go("/users"),
                    trailing=ft.Icon("chevron_right")
                ))
            ]), padding=20, expand=True, bgcolor=BG_COLOR)
        ])

    def view_ciclos():
        tf_nombre = ft.TextField(label="Año / Nombre del Ciclo (Ej: 2025)", expand=True, bgcolor="white", border_radius=8)
        list_col = ft.Column(scroll=ft.ScrollMode.AUTO)

        def load_ciclos():
            list_col.controls.clear()
            for c in AdminService.get_ciclos():
                is_active = c['activo'] == 1
                
                trailing = ft.Container()
                if is_active:
                    trailing = ft.Container(content=ft.Text("ACTIVO", color="white", weight="bold", size=12), bgcolor=SUCCESS_COLOR, padding=5, border_radius=5)
                else:
                    trailing = ft.ElevatedButton("Activar", bgcolor=WARNING_COLOR, color="white", height=30, 
                                                 on_click=lambda e, cid=c['id']: (AdminService.activar_ciclo(cid), load_ciclos(), show_snack("Ciclo activado")))

                card = create_card(ft.ListTile(
                    leading=ft.Icon("check_circle" if is_active else "radio_button_unchecked", color=SUCCESS_COLOR if is_active else "grey"),
                    title=ft.Text(c['nombre'], weight="bold"),
                    trailing=trailing
                ), padding=5)
                list_col.controls.append(card)
            page.update()

        def add_ciclo_click(e):
            if not tf_nombre.value: return show_snack("Ingrese un nombre", True)
            if AdminService.add_ciclo(tf_nombre.value):
                tf_nombre.value = ""
                load_ciclos()
                show_snack("Ciclo creado y activado")
            else:
                show_snack("Error al crear (¿Ya existe?)", True)

        load_ciclos()

        return ft.View("/ciclos", [
            create_header("Ciclos Lectivos", "Gestión de Años Escolares", leading_action=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))),
            ft.Container(content=ft.Column([
                create_card(ft.Row([tf_nombre, ft.IconButton("add_circle", icon_color=SUCCESS_COLOR, icon_size=40, on_click=add_ciclo_click)])),
                ft.Text("Historial", weight="bold", color=TEXT_COLOR),
                list_col
            ], expand=True), padding=20, bgcolor=BG_COLOR, expand=True)
        ])

    def view_users():
        u_tf = ft.TextField(label="Usuario", expand=True, bgcolor="white", border_radius=8)
        p_tf = ft.TextField(label="Contraseña", password=True, expand=True, bgcolor="white", border_radius=8)
        r_dd = ft.Dropdown(options=[ft.dropdown.Option("preceptor"), ft.dropdown.Option("admin")], value="preceptor", width=120, bgcolor="white", border_radius=8)
        list_col = ft.Column(scroll=ft.ScrollMode.AUTO)

        def load_users():
            list_col.controls.clear()
            for u in AdminService.get_users():
                is_me = u['username'] == state['username']
                trailing = None
                if not is_me:
                    trailing = ft.IconButton("delete", icon_color=DANGER_COLOR, on_click=lambda e, uid=u['id']: (AdminService.delete_user(uid), load_users()))
                
                card = create_card(ft.ListTile(
                    leading=ft.Icon("security" if u['role']=='admin' else "person", color=PRIMARY_COLOR),
                    title=ft.Text(u['username'], weight="bold"),
                    subtitle=ft.Text(u['role'].upper(), color="grey"),
                    trailing=trailing
                ), padding=5)
                list_col.controls.append(card)
            page.update()

        def add_user_click(e):
            if not u_tf.value or not p_tf.value: return show_snack("Complete todos los campos", True)
            if AdminService.add_user(u_tf.value, p_tf.value, r_dd.value):
                u_tf.value = ""; p_tf.value = ""
                load_users()
                show_snack("Usuario creado")
            else:
                show_snack("Error: Usuario existe", True)

        load_users()

        return ft.View("/users", [
            create_header("Usuarios", "Gestión de Acceso", leading_action=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))),
            ft.Container(content=ft.Column([
                create_card(ft.Column([
                    ft.Text("Nuevo Usuario", weight="bold"),
                    ft.Row([u_tf, p_tf, r_dd]),
                    ft.ElevatedButton("Crear Usuario", icon="add", on_click=add_user_click, bgcolor=SUCCESS_COLOR, color="white", width=float("inf"))
                ])),
                ft.Text("Lista de Usuarios", weight="bold", color=TEXT_COLOR),
                list_col
            ], expand=True), padding=20, bgcolor=BG_COLOR, expand=True)
        ])

    def view_curso_detail():
        if not state["curso_id"]: return view_dashboard()
        
        # TAB 1: ALUMNOS
        alumnos_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        def load_alumnos():
            alumnos_col.controls.clear()
            rows = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            for r in rows:
                avatar = ft.CircleAvatar(content=ft.Text(r['nombre'][0].upper()), bgcolor=SECONDARY_COLOR, color=PRIMARY_COLOR)
                
                # Helpers para lambdas
                def open_edit(e, s=r):
                    page.session.set("alumno_id_edit", s['id'])
                    page.go("/form_student")

                def open_detail(e, s=r):
                    state["alumno_id"] = s['id']
                    page.go("/student_detail")
                
                def delete_st(e, aid=r['id']):
                     run_query("DELETE FROM Alumnos WHERE id=%s", (aid,))
                     load_alumnos()

                tile = create_card(ft.ListTile(
                    leading=avatar, title=ft.Text(r['nombre'], weight=ft.FontWeight.BOLD), subtitle=ft.Text(f"DNI: {r['dni'] or 'S/D'}"),
                    trailing=ft.IconButton("edit", icon_color="grey", on_click=lambda e, s=r: open_edit(e, s)),
                    on_click=lambda e, s=r: open_detail(e, s) 
                ), padding=0)
                alumnos_col.controls.append(tile)
            page.update()

        # TAB 2: ASISTENCIA
        asist_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        date_pk = ft.TextField(label="Fecha", value=date.today().isoformat(), width=150, height=40, text_size=14)
        def load_asistencia_ui(e=None):
            asist_col.controls.clear()
            fecha = date_pk.value
            guardados = run_query("SELECT alumno_id, status FROM Asistencia WHERE fecha=%s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, state["curso_id"]), fetch=True)
            mapa = {g['alumno_id']: g['status'] for g in guardados}
            
            # --- Lógica TPP para Prellenado ---
            try:
                dt_obj = date.fromisoformat(fecha)
                dia_semana = dt_obj.weekday() # 0=Lunes
            except:
                dia_semana = -1

            for a in run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True):
                # Valor por defecto
                val_defecto = "P"
                
                # Si no hay dato guardado Y el alumno tiene TPP
                if a['id'] not in mapa and a.get('tpp', 0) == 1:
                    tpp_dias_str = a.get('tpp_dias', "")
                    if tpp_dias_str:
                        # Si hoy NO está en sus días permitidos
                        if str(dia_semana) not in tpp_dias_str.split(','):
                            val_defecto = "N" # No corresponde

                status_val = mapa.get(a['id'], val_defecto)
                
                dd = ft.Dropdown(width=100, height=40, text_size=14, value=status_val, options=[ft.dropdown.Option("P"), ft.dropdown.Option("T"), ft.dropdown.Option("A"), ft.dropdown.Option("J"), ft.dropdown.Option("N")], on_change=lambda e, aid=a['id']: run_query("INSERT INTO Asistencia (alumno_id, fecha, status) VALUES (%s, %s, %s) ON CONFLICT (alumno_id, fecha) DO UPDATE SET status = EXCLUDED.status", (aid, date_pk.value, e.control.value)))
                
                # Estilo especial si es N (por TPP)
                style_color = "grey" if status_val == "N" else TEXT_COLOR
                
                asist_col.controls.append(ft.Container(content=ft.Row([ft.Text(a['nombre'], expand=True, weight="w500", color=style_color), dd]), padding=ft.padding.symmetric(vertical=5), border=ft.border.only(bottom=ft.border.BorderSide(1, "grey200"))))
            page.update()

        # TAB 3: REPORTES
        report_col = ft.Column(scroll=ft.ScrollMode.AUTO)
        def load_report_ui():
            btn_export = ft.ElevatedButton("Exportar Excel Completo", icon="download", bgcolor="green700", color="white", on_click=export_excel_action)
            report_col.controls = [ft.Text("Resumen del Ciclo Lectivo", size=16, weight="bold"), ft.Container(height=10), btn_export]
        def export_excel_action(e):
            if not pd or not xlsxwriter: return show_snack("Faltan librerías", True)
            alumnos = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            asistencias = run_query("SELECT * FROM Asistencia WHERE alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (state["curso_id"],), fetch=True)
            data_list = []
            for a in alumnos:
                a_asist = [x for x in asistencias if x['alumno_id'] == a['id']]
                counts = {k: 0 for k in ['P','T','A','J']}
                for r in a_asist:
                    if r['status'] in counts: counts[r['status']]+=1
                total_faltas = counts['A'] + (counts['T']*0.5)
                data_list.append({"Alumno": a['nombre'], "DNI": a['dni'], "Pres": counts['P'], "Aus": counts['A'], "Faltas Eq": total_faltas})
            df = pd.DataFrame(data_list)
            bio = io.BytesIO(); df.to_excel(bio, index=False); b64 = base64.b64encode(bio.getvalue()).decode()
            page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="reporte.xlsx")

        tabs = ft.Tabs(selected_index=0, animation_duration=300, tabs=[
            ft.Tab(text="Alumnos", icon="people", content=ft.Container(content=alumnos_col, padding=10)),
            ft.Tab(text="Asistencia", icon="check_circle", content=ft.Container(content=ft.Column([ft.Row([date_pk, ft.IconButton("refresh", on_click=load_asistencia_ui)]), ft.Divider(), asist_col]), padding=10)),
            ft.Tab(text="Reportes", icon="bar_chart", content=ft.Container(content=report_col, padding=10))
        ], expand=True, on_change=lambda e: (load_alumnos() if e.control.selected_index==0 else (load_asistencia_ui() if e.control.selected_index==1 else load_report_ui())))

        load_alumnos()

        def open_add_student(e):
            page.session.set("alumno_id_edit", None)
            page.go("/form_student")

        return ft.View("/curso", [
            create_header(state["curso_nombre"], "Gestión del Curso", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=tabs, expand=True, bgcolor=BG_COLOR),
            ft.FloatingActionButton(icon="add", on_click=open_add_student, bgcolor=PRIMARY_COLOR)
        ])

    def view_form_student():
        cid = page.session.get("curso_id")
        aid = page.session.get("alumno_id_edit")
        is_edit = aid is not None
        
        nm = ft.TextField(label="Nombre")
        dn = ft.TextField(label="DNI")
        tn = ft.TextField(label="Tutor")
        tt = ft.TextField(label="Tel. Tutor")
        ob = ft.TextField(label="Observaciones", multiline=True)
        
        # Componentes TPP
        sw_tpp = ft.Switch(label="Activar Trayectoria (TPP)", value=False)
        
        # Checkboxes para días (0=Lun, 4=Vie)
        days_checks = [
            ft.Checkbox(label="Lunes", value=True, data="0"),
            ft.Checkbox(label="Martes", value=True, data="1"),
            ft.Checkbox(label="Miércoles", value=True, data="2"),
            ft.Checkbox(label="Jueves", value=True, data="3"),
            ft.Checkbox(label="Viernes", value=True, data="4"),
        ]
        
        days_container = ft.Column(
            [ft.Text("Días de Asistencia Obligatoria:", size=12, weight="bold")] + days_checks,
            visible=False
        )

        def toggle_tpp(e):
            days_container.visible = sw_tpp.value
            page.update()

        sw_tpp.on_change = toggle_tpp

        if is_edit:
            d = run_query_one("SELECT * FROM Alumnos WHERE id=%s", (aid,))
            if d:
                nm.value = d['nombre']; dn.value = d['dni']; tn.value = d['tutor_nombre']; tt.value = d['tutor_telefono']; ob.value = d['observaciones']
                if d.get('tpp') == 1:
                    sw_tpp.value = True
                    days_container.visible = True
                    saved_days = (d.get('tpp_dias') or "").split(',')
                    for chk in days_checks:
                        chk.value = chk.data in saved_days

        def save(e):
            if not nm.value: return show_snack("Nombre obligatorio", True)
            
            tpp_val = 1 if sw_tpp.value else 0
            tpp_days_str = ",".join([c.data for c in days_checks if c.value]) if sw_tpp.value else ""

            if is_edit:
                run_query("""UPDATE Alumnos SET nombre=%s, dni=%s, tutor_nombre=%s, tutor_telefono=%s, observaciones=%s, tpp=%s, tpp_dias=%s WHERE id=%s""", 
                          (nm.value, dn.value, tn.value, tt.value, ob.value, tpp_val, tpp_days_str, aid))
            else:
                run_query("""INSERT INTO Alumnos (curso_id, nombre, dni, tutor_nombre, tutor_telefono, observaciones, tpp, tpp_dias) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""", 
                          (cid, nm.value, dn.value, tn.value, tt.value, ob.value, tpp_val, tpp_days_str))
            
            page.go("/curso")

        return ft.View("/form_student", [
            create_header("Editar Alumno" if is_edit else "Nuevo Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
            ft.Container(content=create_card(ft.Column([
                nm, dn, ft.Divider(), 
                tn, tt, ft.Divider(), 
                ob, ft.Divider(),
                ft.Container(content=ft.Column([sw_tpp, days_container]), bgcolor=ft.colors.BLUE_50, padding=10, border_radius=10),
                ft.Container(height=10),
                ft.ElevatedButton("Guardar", on_click=save, width=float("inf"), bgcolor=PRIMARY_COLOR, color="white")
            ])), padding=20, bgcolor=BG_COLOR, expand=True)
        ])

    def view_student_detail():
        aid = page.session.get("alumno_id"); cid = page.session.get("curso_id")
        if not aid: return view_dashboard()
        s = run_query_one("SELECT * FROM Alumnos WHERE id=%s", (aid,))
        
        # Stats
        asist = run_query("SELECT status FROM Asistencia WHERE alumno_id=%s", (aid,), fetch=True)
        counts = {k: 0 for k in ['P','T','A','J']}
        for r in asist: 
            if r['status'] in counts: counts[r['status']] += 1
        faltas = counts['A'] + (counts['T']*0.5)

        def stat_card(lbl, val, clr="black"):
            return ft.Container(content=ft.Column([ft.Text(str(val), size=22, weight=ft.FontWeight.BOLD, color=clr), ft.Text(lbl, size=12, color="grey")], horizontal_alignment="center"), padding=10, bgcolor="white", border_radius=8, expand=True, border=ft.border.all(1, "grey200"))
        
        # Info TPP en Ficha
        tpp_info = ft.Container()
        if s.get('tpp') == 1:
            dias_map = {"0":"Lun", "1":"Mar", "2":"Mié", "3":"Jue", "4":"Vie"}
            dias_str = ", ".join([dias_map.get(d, "?") for d in (s.get('tpp_dias') or "").split(',') if d])
            tpp_info = ft.Container(
                content=ft.Row([ft.Icon("warning", color="orange"), ft.Text(f"Régimen TPP: Asiste {dias_str}", weight="bold", color="orange")], alignment="center"),
                bgcolor=ft.colors.ORANGE_50, padding=10, border_radius=10, margin=ft.margin.only(bottom=10)
            )

        return ft.View("/student_detail", [
            create_header("Ficha Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
            ft.Container(content=create_card(ft.Column([
                ft.Row([ft.Icon("person", size=50, color=PRIMARY_COLOR), ft.Column([ft.Text(s['nombre'], size=24, weight="bold"), ft.Text(f"DNI: {s.get('dni') or '-'}", color="grey")])]),
                ft.Divider(),
                tpp_info, # Mostrar cartel TPP si corresponde
                ft.Row([stat_card("Faltas", faltas, DANGER_COLOR if faltas>20 else "black"), stat_card("Pres", counts['P'], SUCCESS_COLOR)], spacing=10),
                ft.Divider(),
                ft.Text("Contacto", weight="bold"), ft.ListTile(leading=ft.Icon("phone"), title=ft.Text(s.get('tutor_nombre') or '-'), subtitle=ft.Text(s.get('tutor_telefono') or '-')),
                ft.Text("Obs", weight="bold"), ft.Container(content=ft.Text(s.get('observaciones') or '-', italic=True), padding=10, bgcolor=BG_COLOR, border_radius=5, width=float("inf")),
            ], scroll="auto")), padding=20, expand=True, bgcolor=BG_COLOR)
        ])

    def view_search():
        term = page.session.get("search_term"); 
        col = ft.Column(scroll="auto", expand=True)
        # Búsqueda global (limitada a ciclo activo en DB)
        res = run_query("""
            SELECT a.*, c.nombre as curso_nombre, ci.nombre as ciclo_nombre 
            FROM Alumnos a 
            JOIN Cursos c ON a.curso_id = c.id 
            JOIN Ciclos ci ON c.ciclo_id = ci.id
            WHERE (a.nombre ILIKE %s OR a.dni ILIKE %s) AND ci.activo = 1
            ORDER BY a.nombre
        """, (f"%{term}%", f"%{term}%"), fetch=True)
        
        if not res: col.controls.append(ft.Text("Sin resultados"))
        for r in res:
            def clk(e, aid=r['id'], cid=r['curso_id'], cname=r['curso_nombre']): 
                page.session.set("alumno_id", aid); page.session.set("curso_id", cid); page.session.set("curso_nombre", cname); page.go("/student_detail")
            col.controls.append(create_card(ft.ListTile(leading=ft.Icon("person", color=PRIMARY_COLOR), title=ft.Text(r['nombre'], weight="bold"), subtitle=ft.Text(f"{r['curso_nombre']} - {r['dni']}"), on_click=clk), padding=0))
        return ft.View("/search", [
            create_header(f"Búsqueda: {term}", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=col, padding=20, bgcolor=BG_COLOR, expand=True)
        ])

    def route_change(route):
        page.views.clear()
        if page.route == "/": page.views.append(view_login())
        elif page.route == "/dashboard": page.views.append(view_dashboard())
        elif page.route == "/curso": page.views.append(view_curso())
        elif page.route == "/student_detail": page.views.append(view_student_detail())
        elif page.route == "/admin": page.views.append(view_admin())
        elif page.route == "/ciclos": page.views.append(view_ciclos())
        elif page.route == "/users": page.views.append(view_users())
        elif page.route == "/form_student": page.views.append(view_form_student())
        elif page.route == "/search": page.views.append(view_search())
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
        ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=int(port_env), host="0.0.0.0")
    else:
        ft.app(target=main, view=ft.AppView.WEB_BROWSER, port=8550)
