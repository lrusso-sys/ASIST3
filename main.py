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
# CONFIGURACIÓN DE ESTILO (Colores en String para evitar errores)
# ==============================================================================
# Paleta de colores "Institutional Pro"
PRIMARY = "#3F51B5"       # Indigo principal
ON_PRIMARY = "white"      # Texto sobre primario
BG_COLOR = "#F0F4F8"      # Fondo general suave
CARD_BG = "white"         # Fondo de tarjetas
TEXT_COLOR = "#1F2937"    # Texto principal oscuro
SUBTEXT_COLOR = "#6B7280" # Texto secundario gris
DANGER = "#EF4444"        # Rojo error
SUCCESS = "#10B981"       # Verde éxito
WARNING = "#F59E0B"       # Naranja advertencia

# ==============================================================================
# 1. BASE DE DATOS (POSTGRESQL PURO)
# ==============================================================================

def get_db_connection():
    """Obtiene conexión a PostgreSQL desde variables de entorno."""
    database_url = os.environ.get('DATABASE_URL')
    
    try:
        if database_url:
            # Fix para Render
            if database_url.startswith('postgres://'):
                database_url = database_url.replace('postgres://', 'postgresql://', 1)
            conn = psycopg2.connect(database_url, sslmode='require')
            return conn
        else:
            # Fallback local (Configura esto si pruebas en tu PC con Postgres local)
            print("⚠️ Conectando a Postgres Local...", flush=True)
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
            # Tablas (Sintaxis PostgreSQL: SERIAL, %s)
            cur.execute("""CREATE TABLE IF NOT EXISTS Usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Ciclos (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 0)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Cursos (id SERIAL PRIMARY KEY, nombre TEXT, ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Alumnos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, nombre TEXT, dni TEXT, observaciones TEXT, tutor_nombre TEXT, tutor_telefono TEXT, UNIQUE(curso_id, nombre))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Asistencia (id SERIAL PRIMARY KEY, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, fecha TEXT, status TEXT, UNIQUE(alumno_id, fecha))""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, descripcion TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS Requisitos_Cumplidos (requisito_id INTEGER REFERENCES Requisitos(id) ON DELETE CASCADE, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, PRIMARY KEY (requisito_id, alumno_id))""")
            
            # Datos semilla (Admin)
            cur.execute("SELECT COUNT(*) FROM Usuarios")
            if cur.fetchone()[0] == 0:
                pwd = hashlib.sha256("admin".encode()).hexdigest()
                cur.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", ("admin", pwd, "admin"))
            
            # Datos semilla (Ciclo)
            cur.execute("SELECT COUNT(*) FROM Ciclos")
            if cur.fetchone()[0] == 0:
                cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (str(date.today().year),))
        conn.commit()
        print("✅ Base de datos PostgreSQL inicializada.")
    except Exception as e:
        print(f"❌ Error Init DB: {e}")
    finally:
        conn.close()

# --- Helpers de Base de Datos ---
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
# 2. INTERFAZ DE USUARIO (Flet Moderno)
# ==============================================================================

def main(page: ft.Page):
    # Configuración General
    page.title = "Sistema de Asistencia"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0
    page.bgcolor = BG_COLOR
    
    # Inicializar DB
    init_db()

    # Estado de la sesión
    state = {
        "role": None,
        "username": None,
        "curso_id": None,
        "curso_nombre": None,
        "alumno_id": None,
        "search_term": ""
    }

    # --- COMPONENTES VISUALES ---

    def show_snack(msg, is_error=False):
        page.snack_bar = ft.SnackBar(
            content=ft.Text(msg, color="white"),
            bgcolor=DANGER if is_error else SUCCESS
        )
        page.snack_bar.open = True
        page.update()

    def create_header(title, subtitle=None, leading=None, actions=None):
        return ft.Container(
            content=ft.Row([
                ft.Row([
                    leading if leading else ft.Container(),
                    ft.Column([
                        ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color=ON_PRIMARY),
                        ft.Text(subtitle, size=12, color="white70") if subtitle else ft.Container()
                    ], spacing=2)
                ]),
                ft.Row(actions) if actions else ft.Container()
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=20, vertical=15),
            bgcolor=PRIMARY,
            shadow=ft.BoxShadow(blur_radius=5, color="black26", offset=ft.Offset(0, 2))
        )

    def create_card(content, padding=20, on_click=None):
        return ft.Container(
            content=content,
            padding=padding,
            bgcolor=CARD_BG,
            border_radius=10,
            shadow=ft.BoxShadow(blur_radius=4, spread_radius=0, color="black12", offset=ft.Offset(0, 2)),
            margin=ft.margin.only(bottom=10),
            on_click=on_click,
            ink=True if on_click else False
        )

    # --- VISTAS ---

    def view_login():
        user = ft.TextField(label="Usuario", prefix_icon="person", width=300, bgcolor="white", border_radius=8)
        pwd = ft.TextField(label="Contraseña", password=True, can_reveal_password=True, prefix_icon="lock", width=300, bgcolor="white", border_radius=8)

        def login_click(e):
            if not user.value or not pwd.value: return show_snack("Complete los campos", True)
            hashed = hashlib.sha256(pwd.value.encode()).hexdigest()
            # Auth contra Postgres
            u_data = run_query_one("SELECT * FROM Usuarios WHERE username=%s", (user.value,))
            
            if u_data and u_data['password'] == hashed:
                state["role"] = u_data['role']
                state["username"] = user.value
                page.go("/dashboard")
            else:
                show_snack("Usuario o contraseña incorrectos", True)

        return ft.View("/", [
            ft.Container(
                content=ft.Column([
                    ft.Icon("school_rounded", size=80, color=PRIMARY),
                    ft.Text("Bienvenido", size=28, weight=ft.FontWeight.BOLD, color=PRIMARY),
                    ft.Text("Gestión de Asistencia", size=16, color=SUBTEXT_COLOR),
                    ft.Divider(height=40, color="transparent"),
                    user, pwd,
                    ft.Container(height=20),
                    ft.ElevatedButton("INICIAR SESIÓN", on_click=login_click, width=300, height=45, bgcolor=PRIMARY, color=ON_PRIMARY, style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8))),
                    ft.Text("Admin default: admin / admin", size=12, color="grey")
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                alignment=ft.alignment.center, expand=True,
                gradient=ft.LinearGradient(begin=ft.alignment.top_center, end=ft.alignment.bottom_center, colors=["#E8EAF6", "white"])
            )
        ])

    def view_dashboard():
        ciclo = run_query_one("SELECT * FROM Ciclos WHERE activo = 1")
        ciclo_nombre = ciclo['nombre'] if ciclo else "Sin Ciclo Activo"
        
        search = ft.TextField(hint_text="Buscar alumno...", expand=True, bgcolor="white", border_radius=20, border_color="transparent", prefix_icon="search")
        def do_search(e): 
            if search.value: state["search_term"]=search.value; page.go("/search")
        search.on_submit = do_search

        # Grid Responsivo
        grid = ft.GridView(runs_count=2, max_extent=400, child_aspect_ratio=2.5, spacing=15, run_spacing=15)
        
        def load_cursos():
            grid.controls.clear()
            if not ciclo: return grid.controls.append(ft.Text("⚠️ No hay ciclo lectivo activo."))
            
            cursos = run_query("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],), fetch=True)
            for c in cursos:
                def go_c(e, cid=c['id'], cn=c['nombre']): state["curso_id"]=cid; state["curso_nombre"]=cn; page.go("/curso")
                grid.controls.append(create_card(ft.Row([
                    ft.Row([ft.Icon("class_", color=PRIMARY), ft.Text(c['nombre'], weight="bold", size=16, color=TEXT_COLOR)]),
                    ft.Icon("chevron_right", color=SUBTEXT_COLOR)
                ], alignment="spaceBetween"), on_click=go_c))
            page.update()

        load_cursos()

        fab = None
        if state["role"] == "admin":
            def add_curso_dlg(e):
                tf = ft.TextField(label="Nombre")
                def save(e):
                    if not ciclo: return show_snack("Active un ciclo", True)
                    if tf.value: run_query("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (tf.value, ciclo['id'])); page.close_dialog(); load_cursos()
                page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Curso"), content=tf, actions=[ft.TextButton("Guardar", on_click=save)])
                page.dialog.open = True; page.update()
            fab = ft.FloatingActionButton(icon="add", on_click=add_curso_dlg, bgcolor=PRIMARY)

        actions = [ft.IconButton("logout", icon_color=ON_PRIMARY, on_click=lambda _: page.go("/"))]
        if state["role"]=="admin": actions.insert(0, ft.IconButton("settings", icon_color=ON_PRIMARY, on_click=lambda _: page.go("/admin")))

        return ft.View("/dashboard", [
            create_header("Panel Principal", f"Ciclo: {ciclo_nombre}", actions=actions),
            ft.Container(content=ft.Column([
                ft.Container(content=search, padding=ft.padding.only(bottom=20)),
                ft.Text("Mis Cursos", size=20, weight="bold", color=TEXT_COLOR),
                ft.Divider(height=10, color="transparent"),
                grid
            ], expand=True), padding=20, expand=True)
        ], floating_action_button=fab)

    def view_curso():
        if not state["curso_id"]: return view_dashboard()
        
        # Tabs contents
        list_alumnos = ft.Column(scroll="auto")
        list_asistencia = ft.Column(scroll="auto")
        col_reporte = ft.Column(scroll="auto")
        
        # Fecha para asistencia
        dt_picker = ft.TextField(label="Fecha", value=date.today().isoformat(), width=150, height=40, text_size=14, bgcolor="white")

        def load_alumnos_tab():
            list_alumnos.controls.clear()
            rows = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            if not rows: list_alumnos.controls.append(ft.Text("Sin alumnos", italic=True))
            for r in rows:
                def go_det(e, aid=r['id']): state["alumno_id"]=aid; page.go("/student_detail")
                def del_al(e, aid=r['id']): run_query("DELETE FROM Alumnos WHERE id=%s", (aid,)); load_alumnos(); page.update()
                
                trailing = ft.IconButton("delete", icon_color=DANGER, on_click=lambda e, aid=r['id']: del_al(e, aid)) if state["role"]=="admin" else None
                
                list_alumnos.controls.append(create_card(ft.ListTile(
                    leading=ft.CircleAvatar(content=ft.Text(r['nombre'][0]), bgcolor=SECONDARY_COLOR, color=PRIMARY),
                    title=ft.Text(r['nombre'], weight="bold"), subtitle=ft.Text(f"DNI: {r['dni'] or '-'}"),
                    on_click=go_det, trailing=trailing
                ), padding=0))
            page.update()

        def load_asistencia_tab(e=None):
            list_asistencia.controls.clear()
            fecha = dt_picker.value
            # Traer estados
            saved = run_query("SELECT alumno_id, status FROM Asistencia WHERE fecha=%s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, state["curso_id"]), fetch=True)
            mapa = {x['alumno_id']: x['status'] for x in saved}
            
            alumnos = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            for a in alumnos:
                dd = ft.Dropdown(
                    width=90, height=40, text_size=14, value=mapa.get(a['id'], "P"),
                    options=[ft.dropdown.Option(x) for x in ["P","T","A","J"]],
                    on_change=lambda e, aid=a['id']: run_query("INSERT INTO Asistencia (alumno_id, fecha, status) VALUES (%s, %s, %s) ON CONFLICT (alumno_id, fecha) DO UPDATE SET status = EXCLUDED.status", (aid, fecha, e.control.value))
                )
                list_asistencia.controls.append(create_card(ft.Row([ft.Text(a['nombre'], weight="bold", expand=True), dd], alignment="spaceBetween"), padding=10))
            page.update()

        def export_excel(e):
            if not pd or not xlsxwriter: return show_snack("Faltan librerías", True)
            # Query reporte
            alumnos = run_query("SELECT * FROM Alumnos WHERE curso_id=%s ORDER BY nombre", (state["curso_id"],), fetch=True)
            asist = run_query("SELECT * FROM Asistencia WHERE alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (state["curso_id"],), fetch=True)
            
            data = []
            for a in alumnos:
                mine = [x for x in asist if x['alumno_id'] == a['id']]
                counts = {k: 0 for k in ['P','T','A','J']}
                for m in mine: 
                    if m['status'] in counts: counts[m['status']]+=1
                faltas = counts['A'] + (counts['T']*0.5)
                data.append({"Alumno": a['nombre'], "DNI": a['dni'], "P": counts['P'], "A": counts['A'], "Faltas": faltas})
            
            df = pd.DataFrame(data)
            bio = io.BytesIO(); df.to_excel(bio, index=False); b64 = base64.b64encode(bio.getvalue()).decode()
            page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="reporte.xlsx")

        col_reporte.controls = [ft.ElevatedButton("Descargar Excel", icon="download", bgcolor="green", color="white", on_click=export_excel)]

        tabs = ft.Tabs(selected_index=0, tabs=[
            ft.Tab(text="Alumnos", icon="people", content=ft.Container(content=list_alumnos, padding=10)),
            ft.Tab(text="Asistencia", icon="check_circle", content=ft.Container(content=ft.Column([ft.Row([dt_picker, ft.IconButton("refresh", on_click=load_asistencia_tab)]), ft.Divider(), list_asistencia]), padding=10)),
            ft.Tab(text="Reportes", icon="bar_chart", content=ft.Container(content=col_reporte, padding=10))
        ], expand=True, on_change=lambda e: load_alumnos() if e.control.selected_index==0 else (load_asistencia_tab() if e.control.selected_index==1 else None))

        load_alumnos()

        def add_student_dlg(e):
            n, d = ft.TextField(label="Nombre"), ft.TextField(label="DNI")
            def save(e):
                if n.value:
                    run_query("INSERT INTO Alumnos (curso_id, nombre, dni) VALUES (%s, %s, %s)", (state["curso_id"], n.value, d.value))
                    page.close_dialog(); load_alumnos()
            page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Alumno"), content=ft.Column([n,d], height=150), actions=[ft.TextButton("Guardar", on_click=save)])
            page.dialog.open=True; page.update()

        return ft.View("/curso", [
            create_header(state["curso_nombre"], "Gestión de Curso", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=tabs, expand=True, bgcolor=BG_COLOR),
            ft.FloatingActionButton(icon="person_add", on_click=add_student_dlg, bgcolor=PRIMARY)
        ])

    def view_student_detail():
        aid = state["alumno_id"]
        if not aid: return view_dashboard()
        s = run_query_one("SELECT * FROM Alumnos WHERE id=%s", (aid,))
        
        # Stats
        asist = run_query("SELECT status FROM Asistencia WHERE alumno_id=%s", (aid,), fetch=True)
        counts = {k: 0 for k in ['P','T','A','J']}
        for r in asist: 
            if r['status'] in counts: counts[r['status']] += 1
        faltas = counts['A'] + (counts['T']*0.5)

        def stat_card(lbl, val, clr="black"):
            return ft.Container(content=ft.Column([ft.Text(str(val), size=22, weight="bold", color=clr), ft.Text(lbl, size=12, color="grey")], horizontal_alignment="center"), padding=10, bgcolor="white", border_radius=8, expand=True, border=ft.border.all(1, "grey200"))

        return ft.View("/student_detail", [
            create_header("Ficha Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
            ft.Container(content=create_card(ft.Column([
                ft.Row([ft.Icon("person", size=50, color=PRIMARY), ft.Column([ft.Text(s['nombre'], size=24, weight="bold"), ft.Text(f"DNI: {s.get('dni') or '-'}", color="grey")])]),
                ft.Divider(),
                ft.Row([stat_card("Faltas", faltas, DANGER if faltas>20 else "black"), stat_card("Presentes", counts['P'], SUCCESS)]),
                ft.Divider(),
                ft.Text("Contacto", weight="bold"),
                ft.ListTile(leading=ft.Icon("phone"), title=ft.Text(s.get('tutor_nombre') or '-'), subtitle=ft.Text(s.get('tutor_telefono') or '-'))
            ], scroll="auto")), padding=20, expand=True, bgcolor=BG_COLOR)
        ])

    def view_admin():
        if state["role"] != "admin": return ft.View("/error", [ft.Text("Acceso Denegado")])
        
        def view_ciclos():
            page.go("/ciclos")
        def view_users():
            page.go("/users")

        return ft.View("/admin", [
            create_header("Admin", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
            ft.Container(content=ft.Column([
                create_card(ft.ListTile(leading=ft.Icon("calendar_month", color=PRIMARY), title=ft.Text("Ciclos Lectivos"), on_click=lambda _: page.go("/ciclos"))),
                create_card(ft.ListTile(leading=ft.Icon("people", color=PRIMARY), title=ft.Text("Usuarios"), on_click=lambda _: page.go("/users")))
            ]), padding=20, expand=True, bgcolor=BG_COLOR)
        ])

    def view_ciclos():
        tf = ft.TextField(label="Año", expand=True, bgcolor="white", border_radius=8); col = ft.Column(scroll="auto")
        def load():
            col.controls.clear()
            for c in run_query("SELECT * FROM Ciclos ORDER BY nombre DESC", fetch=True):
                act = c['activo']==1
                tr = ft.Container(content=ft.Text("ACTIVO", color="white", weight="bold", size=10), bgcolor=SUCCESS, padding=5, border_radius=5) if act else ft.ElevatedButton("Activar", on_click=lambda e, cid=c['id']: activate(cid))
                col.controls.append(create_card(ft.ListTile(leading=ft.Icon("check_circle" if act else "circle", color=SUCCESS if act else "grey"), title=ft.Text(c['nombre']), trailing=tr), padding=5))
            page.update()
        def add(e):
            if tf.value:
                run_query("UPDATE Ciclos SET activo = 0"); run_query("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (tf.value,)); tf.value=""; load()
        def activate(cid):
            run_query("UPDATE Ciclos SET activo = 0"); run_query("UPDATE Ciclos SET activo = 1 WHERE id=%s", (cid,)); load()
        load()
        return ft.View("/ciclos", [create_header("Ciclos", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))), ft.Container(content=ft.Column([create_card(ft.Row([tf, ft.IconButton("add_circle", icon_color=SUCCESS, icon_size=40, on_click=add)])), col]), padding=20, bgcolor=BG_COLOR, expand=True)])

    def view_users():
        u = ft.TextField(label="User", expand=True, bgcolor="white", border_radius=8); p = ft.TextField(label="Pass", password=True, expand=True, bgcolor="white", border_radius=8); r = ft.Dropdown(value="preceptor", options=[ft.dropdown.Option("admin"), ft.dropdown.Option("preceptor")], width=100)
        col = ft.Column(scroll="auto")
        def load():
            col.controls.clear()
            for user in run_query("SELECT * FROM Usuarios ORDER BY username", fetch=True):
                col.controls.append(create_card(ft.ListTile(leading=ft.Icon("person", color=PRIMARY), title=ft.Text(user['username']), subtitle=ft.Text(user['role']), trailing=ft.IconButton("delete", icon_color=DANGER, on_click=lambda e, uid=user['id']: delete(uid))), padding=5))
            page.update()
        def add(e):
            if u.value and p.value:
                run_query("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", (u.value, hashlib.sha256(p.value.encode()).hexdigest(), r.value)); u.value=""; p.value=""; load()
        def delete(uid):
            run_query("DELETE FROM Usuarios WHERE id=%s", (uid,)); load()
        load()
        return ft.View("/users", [create_header("Usuarios", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))), ft.Container(content=ft.Column([create_card(ft.Row([u, p, r, ft.IconButton("add_circle", icon_color=SUCCESS, icon_size=40, on_click=add)])), col]), padding=20, bgcolor=BG_COLOR, expand=True)])

    def view_search():
        st = ft.TextField(hint_text="Buscar...", expand=True, bgcolor="white", border_radius=20); col = ft.Column(scroll="auto")
        def search(e):
            if not st.value: return
            res = run_query("SELECT * FROM Alumnos WHERE nombre ILIKE %s OR dni ILIKE %s", (f"%{st.value}%", f"%{st.value}%"), fetch=True)
            col.controls.clear()
            for r in res:
                col.controls.append(create_card(ft.ListTile(leading=ft.Icon("person", color=PRIMARY), title=ft.Text(r['nombre']), subtitle=ft.Text(f"DNI: {r['dni']}"), on_click=lambda e, aid=r['id']: (state.update({"alumno_id": aid}), page.go("/student_detail")))))
            page.update()
        st.on_submit = search
        if state.get("search_term"): st.value = state["search_term"]; search(None)
        
        return ft.View("/search", [create_header("Búsqueda", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))), ft.Container(content=ft.Column([st, col]), padding=20, bgcolor=BG_COLOR, expand=True)])

    # --- ROUTER ---
    def route_change(route):
        page.views.clear()
        
        if page.route == "/": page.views.append(view_login())
        elif page.route == "/dashboard": page.views.append(view_dashboard())
        elif page.route == "/curso": page.views.append(view_curso())
        elif page.route == "/student_detail": page.views.append(view_student_detail())
        elif page.route == "/admin": page.views.append(view_admin())
        elif page.route == "/ciclos": page.views.append(view_ciclos())
        elif page.route == "/users": page.views.append(view_users())
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
        
