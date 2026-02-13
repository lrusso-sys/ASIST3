import flet as ft
import psycopg2
import psycopg2.extras
import hashlib
from datetime import date, datetime
import os
import base64
import io
import threading

# --- IMPORTACIÓN DE LIBRERÍAS EXTERNAS ---
try:
    import pandas as pd
except ImportError:
    pd = None
    print("⚠️ Pandas no instalado.")

try:
    import xlsxwriter
except ImportError:
    print("⚠️ XlsxWriter no instalado.")

# ======================================================================
# CAPA 1: UTILIDADES Y VALIDACIONES
# ======================================================================

class Validator:
    @staticmethod
    def is_weekend(date_str: str) -> bool:
        try:
            d = date.fromisoformat(date_str)
            return d.weekday() >= 5
        except ValueError:
            return False

    @staticmethod
    def is_future_date(date_str: str) -> bool:
        try:
            d = date.fromisoformat(date_str)
            return d > date.today()
        except ValueError:
            return False

class Security:
    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

# ======================================================================
# CAPA 2: GESTIÓN DE BASE DE DATOS (PostgreSQL)
# ======================================================================

class DatabaseManager:
    def __init__(self):
        self.lock = threading.Lock()
        self._init_db()

    def get_connection(self):
        """Obtiene conexión a PostgreSQL desde variables de entorno."""
        database_url = os.environ.get('DATABASE_URL')
        
        try:
            if database_url:
                # Fix para Render que usa postgres:// a veces
                if database_url.startswith('postgres://'):
                    database_url = database_url.replace('postgres://', 'postgresql://', 1)
                conn = psycopg2.connect(database_url, sslmode='require')
            else:
                # Configuración local (fallback)
                conn = psycopg2.connect(
                    host=os.environ.get('DB_HOST', 'localhost'),
                    port=os.environ.get('DB_PORT', '5432'),
                    database=os.environ.get('DB_NAME', 'asistencia_db'),
                    user=os.environ.get('DB_USER', 'postgres'),
                    password=os.environ.get('DB_PASSWORD', 'password')
                )
            return conn
        except Exception as e:
            print(f"Error de conexión a DB: {e}")
            return None

    def _init_db(self):
        conn = self.get_connection()
        if not conn:
            print("CRÍTICO: No se pudo conectar a la base de datos.")
            return

        try:
            with conn.cursor() as cursor:
                # Tablas con sintaxis PostgreSQL (SERIAL en lugar de AUTOINCREMENT)
                queries = [
                    """CREATE TABLE IF NOT EXISTS Usuarios (
                        id SERIAL PRIMARY KEY, 
                        username TEXT NOT NULL UNIQUE, 
                        password TEXT NOT NULL, 
                        role TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS Ciclos (
                        id SERIAL PRIMARY KEY, 
                        nombre TEXT NOT NULL UNIQUE, 
                        activo INTEGER DEFAULT 0
                    )""",
                    """CREATE TABLE IF NOT EXISTS Cursos (
                        id SERIAL PRIMARY KEY, 
                        nombre TEXT NOT NULL, 
                        ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE
                    )""",
                    """CREATE TABLE IF NOT EXISTS Alumnos (
                        id SERIAL PRIMARY KEY, 
                        curso_id INTEGER NOT NULL REFERENCES Cursos(id) ON DELETE CASCADE, 
                        nombre TEXT NOT NULL, 
                        dni TEXT, 
                        observaciones TEXT, 
                        tutor_nombre TEXT, 
                        tutor_telefono TEXT, 
                        UNIQUE(curso_id, nombre)
                    )""",
                    """CREATE TABLE IF NOT EXISTS Asistencia (
                        id SERIAL PRIMARY KEY, 
                        alumno_id INTEGER NOT NULL REFERENCES Alumnos(id) ON DELETE CASCADE, 
                        fecha TEXT NOT NULL, 
                        status TEXT NOT NULL, 
                        UNIQUE(alumno_id, fecha)
                    )""",
                    """CREATE TABLE IF NOT EXISTS Requisitos (
                        id SERIAL PRIMARY KEY, 
                        curso_id INTEGER NOT NULL REFERENCES Cursos(id) ON DELETE CASCADE, 
                        descripcion TEXT NOT NULL
                    )""",
                    """CREATE TABLE IF NOT EXISTS Requisitos_Cumplidos (
                        requisito_id INTEGER NOT NULL REFERENCES Requisitos(id) ON DELETE CASCADE, 
                        alumno_id INTEGER NOT NULL REFERENCES Alumnos(id) ON DELETE CASCADE, 
                        PRIMARY KEY (requisito_id, alumno_id)
                    )"""
                ]
                
                for q in queries:
                    cursor.execute(q)

                # Seed Data (Admin)
                cursor.execute("SELECT COUNT(*) FROM Usuarios")
                if cursor.fetchone()[0] == 0:
                    cursor.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", 
                                   ("admin", Security.hash_password("admin"), "admin"))
                
                # Seed Data (Ciclo por defecto)
                cursor.execute("SELECT COUNT(*) FROM Ciclos")
                if cursor.fetchone()[0] == 0:
                    anio = str(date.today().year)
                    cursor.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1) RETURNING id", (anio,))
                    # cid = cursor.fetchone()[0] # No hay cursos viejos en DB limpia

                conn.commit()
                print("Base de datos PostgreSQL inicializada correctamente.")
        except Exception as e:
            print(f"Error inicializando DB: {e}")
            conn.rollback()
        finally:
            conn.close()

    # --- Métodos CRUD ---

    def fetch_all(self, query, params=()):
        conn = self.get_connection()
        if not conn: return []
        try:
            # RealDictCursor permite acceder a las columnas por nombre
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Fetch All Error: {e}")
            return []
        finally:
            conn.close()

    def fetch_one(self, query, params=()):
        conn = self.get_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None
        except Exception as e:
            print(f"Fetch One Error: {e}")
            return None
        finally:
            conn.close()

    def execute_query(self, query, params=()):
        conn = self.get_connection()
        if not conn: return False
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
            conn.commit()
            return True
        except Exception as e:
            print(f"Execute Error: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    # --- Lógica de Negocio ---

    def authenticate(self, username, password):
        user = self.fetch_one("SELECT * FROM Usuarios WHERE username = %s", (username,))
        if user and user['password'] == Security.hash_password(password):
            return user
        return None

    def get_ciclo_activo(self):
        return self.fetch_one("SELECT * FROM Ciclos WHERE activo = 1")

    def get_cursos_activos(self):
        ciclo = self.get_ciclo_activo()
        if not ciclo: return []
        return self.fetch_all("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],))

    def get_alumnos_curso(self, curso_id):
        return self.fetch_all("SELECT * FROM Alumnos WHERE curso_id = %s ORDER BY nombre", (curso_id,))

    def get_asistencia_fecha(self, curso_id, fecha):
        rows = self.fetch_all("SELECT alumno_id, status FROM Asistencia WHERE fecha = %s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, curso_id))
        return {row['alumno_id']: row['status'] for row in rows}

    def registrar_asistencia(self, alumno_id, fecha, status):
        # Postgres UPSERT
        query = """
            INSERT INTO Asistencia (alumno_id, fecha, status) 
            VALUES (%s, %s, %s)
            ON CONFLICT (alumno_id, fecha) 
            DO UPDATE SET status = EXCLUDED.status
        """
        return self.execute_query(query, (alumno_id, fecha, status))

    def get_reporte_curso(self, curso_id, start_date, end_date):
        alumnos = self.get_alumnos_curso(curso_id)
        asistencias = self.fetch_all("""
            SELECT alumno_id, status 
            FROM Asistencia 
            WHERE fecha >= %s AND fecha <= %s 
            AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)
        """, (start_date, end_date, curso_id))

        asis_map = {}
        for r in asistencias:
            if r['alumno_id'] not in asis_map: asis_map[r['alumno_id']] = []
            asis_map[r['alumno_id']].append(r['status'])

        reporte = []
        for a in alumnos:
            statuses = asis_map.get(a['id'], [])
            counts = {k: statuses.count(k) for k in ['P','T','A','J','S','N']}
            faltas = counts['A'] + counts['S'] + (counts['T'] * 0.25)
            total = sum(counts[k] for k in ['P','T','A','J','S'])
            pct = (faltas / total * 100) if total > 0 else 0
            
            reporte.append({
                'id': a['id'],
                'nombre': a['nombre'], 
                'dni': a.get('dni', '-'),
                'tutor_nombre': a.get('tutor_nombre', '-'),
                'tutor_telefono': a.get('tutor_telefono', '-'),
                'observaciones': a.get('observaciones', ''),
                'p': counts['P'], 't': counts['T'], 'a': counts['A'], 
                'j': counts['J'], 's': counts['S'], 
                'faltas': faltas, 'pct': round(pct, 1),
                'total_registros': total
            })
        return reporte
    
    def get_historial_alumno(self, alumno_id):
        return self.fetch_all("SELECT fecha, status FROM Asistencia WHERE alumno_id = %s ORDER BY fecha DESC", (alumno_id,))

    def search_alumnos(self, term):
        term_like = f"%{term}%"
        return self.fetch_all("""
            SELECT a.*, c.nombre as curso_nombre, ci.nombre as ciclo_nombre 
            FROM Alumnos a 
            JOIN Cursos c ON a.curso_id = c.id 
            JOIN Ciclos ci ON c.ciclo_id = ci.id
            WHERE (a.nombre ILIKE %s OR a.dni ILIKE %s) AND ci.activo = 1
            ORDER BY a.nombre
        """, (term_like, term_like))

    def get_requisitos_estado(self, alumno_id, curso_id):
        reqs = self.fetch_all("SELECT * FROM Requisitos WHERE curso_id = %s", (curso_id,))
        cumplidos_raw = self.fetch_all("SELECT requisito_id FROM Requisitos_Cumplidos WHERE alumno_id = %s", (alumno_id,))
        cumplidos_ids = {r['requisito_id'] for r in cumplidos_raw}
        
        result = []
        for r in reqs:
            result.append({
                'id': r['id'],
                'desc': r['descripcion'],
                'ok': r['id'] in cumplidos_ids
            })
        return result

    # --- Admin DB ---
    def get_ciclos(self):
        return self.fetch_all("SELECT * FROM Ciclos ORDER BY nombre DESC")

    def add_ciclo(self, nombre):
        conn = self.get_connection()
        if not conn: return False
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE Ciclos SET activo = 0")
                cursor.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (nombre,))
            conn.commit()
            return True
        except: 
            conn.rollback()
            return False
        finally: conn.close()

    def activar_ciclo(self, cid):
        conn = self.get_connection()
        if not conn: return
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE Ciclos SET activo = 0")
                cursor.execute("UPDATE Ciclos SET activo = 1 WHERE id = %s", (cid,))
            conn.commit()
        except: pass
        finally: conn.close()

    def get_users(self):
        return self.fetch_all("SELECT * FROM Usuarios")

    def add_user(self, u, p, r):
        return self.execute_query("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", (u, Security.hash_password(p), r))

    def delete_user(self, uid):
        return self.execute_query("DELETE FROM Usuarios WHERE id = %s", (uid,))
    
    def add_curso(self, nombre, ciclo_id):
        return self.execute_query("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (nombre, ciclo_id))
    
    def delete_curso(self, cid):
        return self.execute_query("DELETE FROM Cursos WHERE id = %s", (cid,))
    
    def delete_alumno(self, aid):
        return self.execute_query("DELETE FROM Alumnos WHERE id = %s", (aid,))
    
    def add_alumno(self, curso_id, nombre, dni, obs, tn, tt):
        return self.execute_query("INSERT INTO Alumnos (curso_id, nombre, dni, observaciones, tutor_nombre, tutor_telefono) VALUES (%s, %s, %s, %s, %s, %s)", 
                                  (curso_id, nombre, dni, obs, tn, tt))

    def update_alumno(self, aid, nombre, dni, obs, tn, tt):
        return self.execute_query("UPDATE Alumnos SET nombre=%s, dni=%s, observaciones=%s, tutor_nombre=%s, tutor_telefono=%s WHERE id=%s", 
                                  (nombre, dni, obs, tn, tt, aid))

    def add_requisito(self, cid, desc):
        return self.execute_query("INSERT INTO Requisitos (curso_id, descripcion) VALUES (%s, %s)", (cid, desc))
    
    def delete_requisito(self, rid):
        return self.execute_query("DELETE FROM Requisitos WHERE id=%s", (rid,))
    
    def toggle_requisito(self, rid, aid, val):
        if val:
            return self.execute_query("INSERT INTO Requisitos_Cumplidos (requisito_id, alumno_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (rid, aid))
        else:
            return self.execute_query("DELETE FROM Requisitos_Cumplidos WHERE requisito_id=%s AND alumno_id=%s", (rid, aid))

db = DatabaseManager()

# ======================================================================
# CAPA 3: INTERFAZ DE USUARIO (Vistas)
# ======================================================================

THEME = {
    "primary": "blue",
    "secondary": "#1A237E",
    "bg": "#F5F7FB",
    "card": "#FFFFFF",
    "danger": "red",
    "success": "green",
    "warning": "orange"
}

def create_card(content, padding=15, on_click=None):
    return ft.Container(
        content=content, padding=padding, bgcolor=THEME["card"], border_radius=8,
        shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2)),
        margin=ft.margin.only(bottom=10), on_click=on_click
    )

def show_snack(page, message, color=THEME["success"]):
    page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=color)
    page.snack_bar.open = True
    page.update()

def view_login(page: ft.Page):
    user_input = ft.TextField(label="Usuario", width=300, bgcolor="white")
    pass_input = ft.TextField(label="Contraseña", password=True, width=300, bgcolor="white", can_reveal_password=True)

    def login_action(e):
        user = db.authenticate(user_input.value, pass_input.value)
        if user:
            page.session.set("user", user)
            page.go("/dashboard")
        else:
            show_snack(page, "Credenciales incorrectas", THEME["danger"])

    return ft.View("/", [
        ft.Container(
            content=ft.Column([
                ft.Icon("school", size=80, color=THEME["primary"]),
                ft.Text("Sistema de Asistencia", size=24, weight="bold"),
                ft.Text("UNSAM", size=16, color="grey"),
                ft.Divider(height=20, color="transparent"),
                user_input, pass_input,
                ft.ElevatedButton("INGRESAR", on_click=login_action, width=300, height=50, bgcolor=THEME["primary"], color="white")
            ], horizontal_alignment="center"),
            alignment=ft.alignment.center, expand=True, bgcolor=THEME["bg"]
        )
    ])

def view_dashboard(page: ft.Page):
    user = page.session.get("user")
    if not user: return view_login(page)
    ciclo = db.get_ciclo_activo()
    ciclo_txt = ciclo['nombre'] if ciclo else "Sin Ciclo Activo"
    search_input = ft.TextField(hint_text="Buscar alumno...", expand=True, bgcolor="white")
    
    def search_action(e):
        if search_input.value:
            page.session.set("search_term", search_input.value)
            page.go("/search")

    cursos_grid = ft.Column(scroll="auto", expand=True)

    def load_cursos():
        cursos_grid.controls.clear()
        cursos = db.get_cursos_activos()
        for c in cursos:
            def on_click_curso(e, cid=c['id'], cname=c['nombre']):
                page.session.set("curso_id", cid)
                page.session.set("curso_nombre", cname)
                page.go("/curso")
            def on_delete_curso(e, cid=c['id']):
                if db.delete_curso(cid): load_cursos(); page.update()

            actions_row = [ft.IconButton("arrow_forward", icon_color=THEME["primary"], on_click=on_click_curso)]
            if user['role'] == 'admin':
                actions_row.append(ft.IconButton("delete", icon_color=THEME["danger"], on_click=on_delete_curso))

            cursos_grid.controls.append(create_card(ft.Row([
                ft.Row([ft.Icon("book", color=THEME["primary"]), ft.Text(c['nombre'], weight="bold", size=16)]),
                ft.Row(actions_row)
            ], alignment="spaceBetween")))
        page.update()

    load_cursos()
    return ft.View("/dashboard", [
        ft.AppBar(title=ft.Text("Panel Principal"), bgcolor=THEME["primary"], color="white", 
                  actions=[ft.IconButton("settings", icon_color="white", on_click=lambda _: page.go("/admin")) if user['role']=='admin' else ft.Container(),
                           ft.IconButton("logout", icon_color="white", on_click=lambda _: page.go("/"))]),
        ft.Container(content=ft.Column([
            ft.Text(f"Ciclo: {ciclo_txt}", color=THEME["primary"], weight="bold"),
            ft.Row([search_input, ft.IconButton("search", on_click=search_action)]),
            ft.Row([ft.Text("Mis Cursos", size=20, weight="bold"), ft.IconButton("add_circle", icon_color="green", icon_size=30, on_click=lambda _: page.go("/form_curso"))], alignment="spaceBetween"),
            cursos_grid
        ]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_curso(page: ft.Page):
    curso_id = page.session.get("curso_id")
    if not curso_id: return view_dashboard(page)
    alumnos_list = ft.Column(scroll="auto", expand=True)

    def load_alumnos():
        alumnos_list.controls.clear()
        for a in db.get_alumnos_curso(curso_id):
            def go_det(aid): page.session.set("alumno_id", aid); page.go("/student_detail")
            def go_edit(aid): page.session.set("alumno_id_edit", aid); page.go("/form_student")
            def go_del(aid): db.delete_alumno(aid); load_alumnos(); page.update()
            
            alumnos_list.controls.append(create_card(ft.ListTile(
                leading=ft.Icon("person"), title=ft.Text(a['nombre']), subtitle=ft.Text(f"DNI: {a['dni'] or '-'}"),
                on_click=lambda e, aid=a['id']: go_det(aid),
                trailing=ft.PopupMenuButton(items=[ft.PopupMenuItem("Editar", on_click=lambda e, aid=a['id']: go_edit(aid)), ft.PopupMenuItem("Borrar", on_click=lambda e, aid=a['id']: go_del(aid))])
            ), padding=0))
        page.update()

    load_alumnos()
    return ft.View("/curso", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard")), title=ft.Text(page.session.get("curso_nombre")), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([
            ft.Row([
                ft.ElevatedButton("Asistencia", icon="check", on_click=lambda _: page.go("/asistencia"), expand=True),
                ft.ElevatedButton("Pedidos", icon="list", on_click=lambda _: page.go("/pedidos"), expand=True),
                ft.ElevatedButton("Reportes", icon="bar_chart", on_click=lambda _: page.go("/reportes"), expand=True)
            ]),
            ft.Divider(),
            ft.Row([ft.Text("Alumnos", size=18, weight="bold"), ft.IconButton("person_add", icon_color="green", on_click=lambda _: (page.session.set("alumno_id_edit", None), page.go("/form_student")))], alignment="spaceBetween"),
            alumnos_list
        ]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_asistencia(page: ft.Page):
    curso_id = page.session.get("curso_id")
    dp = ft.TextField(label="Fecha", value=date.today().isoformat(), bgcolor="white")
    list_col = ft.Column(scroll="auto", expand=True)
    inputs_map = {}

    def load(e=None):
        ex = db.get_asistencia_fecha(curso_id, dp.value)
        list_col.controls.clear(); inputs_map.clear()
        for a in db.get_alumnos_curso(curso_id):
            dd = ft.Dropdown(options=[ft.dropdown.Option(x) for x in ["P","T","A","J","S","N"]], value=ex.get(a['id'], "P"), width=80, bgcolor="white")
            inputs_map[a['id']] = dd
            list_col.controls.append(create_card(ft.Row([ft.Text(a['nombre'], expand=True), dd]), padding=10))
        page.update()

    def save(e):
        if Validator.is_future_date(dp.value): return show_snack(page, "Fecha futura no permitida", THEME["danger"])
        for aid, dd in inputs_map.items(): db.registrar_asistencia(aid, dp.value, dd.value)
        show_snack(page, "Guardado"); page.go("/curso")

    load()
    return ft.View("/asistencia", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso")), title=ft.Text("Asistencia"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([ft.Row([dp, ft.IconButton("refresh", on_click=load)]), ft.ElevatedButton("GUARDAR", on_click=save, bgcolor="green", color="white"), list_col]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_form_student(page: ft.Page):
    aid = page.session.get("alumno_id_edit")
    nm = ft.TextField(label="Nombre", bgcolor="white"); dni = ft.TextField(label="DNI", bgcolor="white")
    obs = ft.TextField(label="Obs", bgcolor="white"); tn = ft.TextField(label="Tutor", bgcolor="white"); tt = ft.TextField(label="Tel", bgcolor="white")
    
    if aid:
        a = db.fetch_one("SELECT * FROM Alumnos WHERE id=%s", (aid,))
        if a: nm.value=a['nombre']; dni.value=a['dni']; obs.value=a['observaciones']; tn.value=a['tutor_nombre']; tt.value=a['tutor_telefono']

    def save(e):
        if nm.value:
            if aid: db.update_alumno(aid, nm.value, dni.value, obs.value, tn.value, tt.value)
            else: db.add_alumno(page.session.get("curso_id"), nm.value, dni.value, obs.value, tn.value, tt.value)
            page.go("/curso")
            
    return ft.View("/form_student", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso")), title=ft.Text("Alumno"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=create_card(ft.Column([nm, dni, obs, tn, tt, ft.ElevatedButton("Guardar", on_click=save, bgcolor="green", color="white")])), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_form_curso(page: ft.Page):
    tf = ft.TextField(label="Nombre", bgcolor="white")
    def save(e):
        if db.add_curso(tf.value, db.get_ciclo_activo()['id']): page.go("/dashboard")
        else: show_snack(page, "Error al crear", "red")
    return ft.View("/form_curso", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard")), title=ft.Text("Nuevo Curso"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=create_card(ft.Column([tf, ft.ElevatedButton("Crear", on_click=save, bgcolor="green", color="white")])), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_search(page: ft.Page):
    term = page.session.get("search_term")
    col = ft.Column(scroll="auto")
    for r in db.search_alumnos(term):
        def go(aid, cid, cname): 
             page.session.set("alumno_id", aid); page.session.set("curso_id", cid); page.session.set("curso_nombre", cname); page.go("/student_detail")
        col.controls.append(create_card(ft.ListTile(title=ft.Text(r['nombre']), subtitle=ft.Text(f"{r['curso_nombre']} - {r['dni']}"), on_click=lambda e, aid=r['id'], cid=r['curso_id'], cn=r['curso_nombre']: go(aid, cid, cn)), padding=0))
    return ft.View("/search", [ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard")), title=ft.Text("Búsqueda"), bgcolor=THEME["primary"], color="white"), ft.Container(content=col, padding=20, bgcolor=THEME["bg"], expand=True)])

def view_student_detail(page: ft.Page):
    aid = page.session.get("alumno_id")
    s = db.fetch_one("SELECT * FROM Alumnos WHERE id=%s", (aid,))
    stats = db.get_reporte_curso(s['curso_id'], "2000-01-01", "2100-12-31")
    stat = next((x for x in stats if x['id'] == aid), None)
    
    def export(e):
        if not pd: return show_snack(page, "Pandas no instalado", "red")
        output = io.BytesIO()
        writer = pd.ExcelWriter(output, engine='xlsxwriter')
        pd.DataFrame([s]).to_excel(writer, sheet_name="Ficha", index=False)
        pd.DataFrame([stat]).to_excel(writer, sheet_name="Stats", index=False)
        hist = db.get_historial_alumno(aid)
        pd.DataFrame(hist).to_excel(writer, sheet_name="Historial", index=False)
        writer.close(); output.seek(0)
        b64 = base64.b64encode(output.read()).decode()
        page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="ficha.xlsx")

    return ft.View("/student_detail", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso")), title=ft.Text("Ficha"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([
            create_card(ft.Column([
                ft.Text(s['nombre'], size=24, weight="bold"),
                ft.Text(f"Faltas: {stat['faltas']} - Aus: {stat['pct']}%"),
                ft.ElevatedButton("Excel", on_click=export, bgcolor="green", color="white")
            ])),
        ]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_admin(page: ft.Page):
    col_u = ft.Column(); col_c = ft.Column()
    
    def load():
        col_u.controls.clear(); col_c.controls.clear()
        for u in db.fetch_all("SELECT * FROM Usuarios"):
            col_u.controls.append(ft.ListTile(title=ft.Text(u['username']), trailing=ft.IconButton("delete", on_click=lambda e, uid=u['id']: (db.delete_user(uid), load())) if u['username']!=page.session.get("user")['username'] else None))
        for c in db.get_ciclos():
            act = c['activo'] == 1
            btn = ft.Text("ACTIVO", color="green") if act else ft.ElevatedButton("Activar", on_click=lambda e, cid=c['id']: (db.activar_ciclo(cid), load()))
            col_c.controls.append(ft.ListTile(title=ft.Text(c['nombre']), trailing=btn))
        page.update()

    u_in = ft.TextField(label="User"); p_in = ft.TextField(label="Pass"); r_in = ft.Dropdown(options=[ft.dropdown.Option("admin"), ft.dropdown.Option("preceptor")], value="preceptor")
    c_in = ft.TextField(label="Ciclo")

    def add_u(e): db.add_user(u_in.value, p_in.value, r_in.value); load()
    def add_c(e): db.add_ciclo(c_in.value); load()

    load()
    return ft.View("/admin", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard")), title=ft.Text("Admin"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([
            ft.Text("Usuarios", weight="bold"), ft.Row([u_in, p_in, r_in, ft.IconButton("add", on_click=add_u)]), col_u,
            ft.Divider(),
            ft.Text("Ciclos", weight="bold"), ft.Row([c_in, ft.IconButton("add", on_click=add_c)]), col_c
        ], scroll="auto"), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_pedidos(page: ft.Page):
    cid = page.session.get("curso_id")
    dd = ft.Dropdown(label="Pedido", expand=True, on_change=lambda e: lc())
    col = ft.Column(scroll="auto"); rm = {}
    
    def lr():
        rs = db.fetch_all("SELECT * FROM Requisitos WHERE curso_id=?", (cid,))
        rm.clear(); dd.options.clear()
        for r in rs: rm[r['descripcion']]=r['id']; dd.options.append(ft.dropdown.Option(r['descripcion']))
        if rs: dd.value=rs[0]['descripcion']
        page.update(); lc()
    
    def lc():
        col.controls.clear()
        if not dd.value: return
        rid = rm[dd.value]
        done = {x['alumno_id'] for x in db.fetch_all("SELECT alumno_id FROM Requisitos_Cumplidos WHERE requisito_id=?", (rid,))}
        for a in db.get_alumnos_curso(cid):
            col.controls.append(create_card(ft.Checkbox(label=a['nombre'], value=(a['id'] in done), on_change=lambda e, aid=a['id'], rid=rid: db.toggle_requisito(rid, aid, e.control.value)), padding=5))
        page.update()
    
    def add(e): page.go("/form_req")
    def dele(e): 
        if dd.value: db.delete_requisito(rm[dd.value]); lr()

    lr()
    return ft.View("/pedidos", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso")), title=ft.Text("Pedidos"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([ft.Row([dd, ft.IconButton("add", on_click=add), ft.IconButton("delete", icon_color="red", on_click=dele)]), col]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_form_req(page: ft.Page):
    tf = ft.TextField(label="Descripción")
    def save(e): db.add_requisito(page.session.get("curso_id"), tf.value); page.go("/pedidos")
    return ft.View("/form_req", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/pedidos")), title=ft.Text("Nuevo Pedido"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=create_card(ft.Column([tf, ft.ElevatedButton("Crear", on_click=save)])), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_reportes(page: ft.Page):
    cid = page.session.get("curso_id")
    d1 = ft.TextField(label="Desde", value=date.today().replace(day=1).isoformat())
    d2 = ft.TextField(label="Hasta", value=date.today().isoformat())
    col = ft.Column(scroll="auto", expand=True)

    def gen(e):
        data = db.get_reporte_curso(cid, d1.value, d2.value)
        rows = []
        for d in data:
            c = "red" if d['faltas']>=25 else "black"
            rows.append(ft.DataRow(cells=[
                ft.DataCell(ft.Text(d['nombre'], color=c)), ft.DataCell(ft.Text(str(d['p']))), ft.DataCell(ft.Text(str(d['a']))),
                ft.DataCell(ft.Text(str(d['faltas']), color=c, weight="bold")), ft.DataCell(ft.Text(f"{d['pct']}%", color=c))
            ]))
        col.controls = [ft.DataTable(columns=[ft.DataColumn(ft.Text("Alum")), ft.DataColumn(ft.Text("P"), numeric=True), ft.DataColumn(ft.Text("A"), numeric=True), ft.DataColumn(ft.Text("Faltas"), numeric=True), ft.DataColumn(ft.Text("%"), numeric=True)], rows=rows)]
        page.update()

    def exp(e):
        if not pd: return show_snack(page, "No pandas", "red")
        df = pd.DataFrame(db.get_reporte_curso(cid, d1.value, d2.value))
        out = io.BytesIO(); df.to_excel(out, index=False, engine='xlsxwriter')
        b64 = base64.b64encode(out.getvalue()).decode()
        page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="rep.xlsx")

    return ft.View("/reportes", [
        ft.AppBar(leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso")), title=ft.Text("Reportes"), bgcolor=THEME["primary"], color="white"),
        ft.Container(content=ft.Column([ft.Row([d1, d2, ft.ElevatedButton("Ver", on_click=gen)]), ft.ElevatedButton("Excel", on_click=exp, bgcolor="green", color="white"), col]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

# ======================================================================
# CONTROLADOR PRINCIPAL (Router)
# ======================================================================

def main(page: ft.Page):
    page.title = "Asistencia UNSAM"
    page.theme_mode = "light"
    page.padding = 0

    routes = {
        "/": view_login,
        "/dashboard": view_dashboard,
        "/curso": view_curso,
        "/asistencia": view_asistencia,
        "/reportes": view_reportes,
        "/student_detail": view_student_detail,
        "/form_student": view_form_student,
        "/form_curso": view_form_curso,
        "/pedidos": view_pedidos,
        "/form_req": view_form_req,
        "/search": view_search,
        "/admin": view_admin
    }

    def route_change(route):
        page.views.clear()
        if page.route != "/" and not page.session.get("user"):
            page.go("/")
            return

        view_fn = routes.get(page.route)
        if view_fn:
            page.views.append(view_fn(page))
        else:
            page.views.append(view_login(page))
        page.update()

    def view_pop(view):
        page.views.pop()
        if page.views:
            top_view = page.views[-1]
            page.go(top_view.route)

    page.on_route_change = route_change
    page.on_view_pop = view_pop
    page.go("/")

if __name__ == "__main__":
    # Configuración de puerto para Nube vs Local
    port_env = os.environ.get("PORT")
    if port_env:
        ft.app(target=main, port=int(port_env), host="0.0.0.0")
    else:
        ft.app(target=main, port=8550)
