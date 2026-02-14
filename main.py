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

# --- CAPA 0: DEPENDENCIAS EXTERNAS ---
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

# --- CONFIGURACIÓN UI (Constantes) ---
THEME = {
    "primary": "indigo",
    "on_primary": "white",
    "secondary": "indigo100",
    "bg": "grey50",
    "card": "white",
    "danger": "red",
    "success": "green",
    "warning": "orange",
    "text": "bluegrey900"
}

# ==============================================================================
# CAPA 1: UTILIDADES Y SEGURIDAD
# ==============================================================================

class Validator:
    """Centraliza la lógica de validación de datos."""
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
    
    @staticmethod
    def is_valid_text(text: str, min_len: int = 1) -> bool:
        return text is not None and len(text.strip()) >= min_len

class Security:
    """Manejo de criptografía y seguridad básica."""
    @staticmethod
    def hash_password(password: str) -> str:
        # En producción real se recomienda bcrypt, aquí SHA256 por compatibilidad estándar
        return hashlib.sha256(password.encode()).hexdigest()

class UIHelper:
    """Componentes visuales reutilizables para mantener consistencia."""
    @staticmethod
    def show_snack(page: ft.Page, message: str, is_error: bool = False):
        color = THEME["danger"] if is_error else THEME["success"]
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=color)
        page.snack_bar.open = True
        page.update()

    @staticmethod
    def create_card(content, padding=20, on_click=None):
        return ft.Container(
            content=content, padding=padding, bgcolor=THEME["card"], border_radius=12,
            shadow=ft.BoxShadow(blur_radius=10, color="black12", offset=ft.Offset(0, 4)),
            margin=ft.margin.only(bottom=10), on_click=on_click,
            animate=ft.animation.Animation(200, "easeOut")
        )

    @staticmethod
    def create_header(title, subtitle="", leading=None, actions=None):
        return ft.Container(
            content=ft.Row([
                ft.Row([
                    leading if leading else ft.Container(),
                    ft.Column([
                        ft.Text(title, size=20, weight=ft.FontWeight.BOLD, color="white"),
                        ft.Text(subtitle, size=12, color="white70") if subtitle else ft.Container()
                    ], spacing=2)
                ]),
                ft.Row(actions, spacing=0) if actions else ft.Container()
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=20, vertical=15),
            bgcolor=THEME["primary"],
            shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2))
        )

# ==============================================================================
# CAPA 2: GESTIÓN DE BASE DE DATOS (PostgreSQL)
# ==============================================================================

class DatabaseManager:
    """
    Singleton para el manejo de conexiones a PostgreSQL.
    Maneja la inicialización, conexión y ejecución de queries.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    # Inicializamos la estructura al crear la instancia
                    cls._instance._init_db_structure()
        return cls._instance

    def get_connection(self):
        """Fabrica de conexiones segura."""
        database_url = os.environ.get('DATABASE_URL')
        try:
            if database_url:
                if database_url.startswith('postgres://'):
                    database_url = database_url.replace('postgres://', 'postgresql://', 1)
                return psycopg2.connect(database_url, sslmode='require')
            else:
                # Fallback local
                print("⚠️ Usando conexión local (sin DATABASE_URL)", flush=True)
                return psycopg2.connect(
                    host=os.environ.get('DB_HOST', 'localhost'),
                    port=os.environ.get('DB_PORT', '5432'),
                    database=os.environ.get('DB_NAME', 'postgres'),
                    user=os.environ.get('DB_USER', 'postgres'),
                    password=os.environ.get('DB_PASSWORD', 'password')
                )
        except Exception as e:
            print(f"❌ Error conexión DB: {e}")
            return None

    def _init_db_structure(self):
        """Inicialización de esquema (DDL) y datos semilla."""
        conn = self.get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS Usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
                cur.execute("CREATE TABLE IF NOT EXISTS Ciclos (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 0)")
                cur.execute("CREATE TABLE IF NOT EXISTS Cursos (id SERIAL PRIMARY KEY, nombre TEXT, ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE)")
                cur.execute("CREATE TABLE IF NOT EXISTS Alumnos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, nombre TEXT, dni TEXT, observaciones TEXT, tutor_nombre TEXT, tutor_telefono TEXT, UNIQUE(curso_id, nombre))")
                cur.execute("CREATE TABLE IF NOT EXISTS Asistencia (id SERIAL PRIMARY KEY, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, fecha TEXT, status TEXT, UNIQUE(alumno_id, fecha))")
                cur.execute("CREATE TABLE IF NOT EXISTS Requisitos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, descripcion TEXT)")
                cur.execute("CREATE TABLE IF NOT EXISTS Requisitos_Cumplidos (requisito_id INTEGER REFERENCES Requisitos(id) ON DELETE CASCADE, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, PRIMARY KEY (requisito_id, alumno_id))")
                
                # Datos iniciales (Admin)
                cur.execute("SELECT COUNT(*) FROM Usuarios")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", ("admin", Security.hash_password("admin"), "admin"))
                
                # Ciclo inicial
                cur.execute("SELECT COUNT(*) FROM Ciclos")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (str(date.today().year),))
            conn.commit()
            print("✅ DB PostgreSQL Inicializada.")
        except Exception as e:
            print(f"❌ Error Init DB: {e}")
        finally:
            conn.close()

    # --- Helpers de Ejecución ---
    def fetch_all(self, query, params=()):
        conn = self.get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            print(f"Fetch All Error: {e}")
            return []
        finally: conn.close()

    def fetch_one(self, query, params=()):
        conn = self.get_connection()
        if not conn: return None
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None
        except: return None
        finally: conn.close()

    def execute(self, query, params=()):
        conn = self.get_connection()
        if not conn: return False
        try:
            with conn.cursor() as cur:
                cur.execute(query, params)
            conn.commit()
            return True
        except Exception as e:
            print(f"Execute Error: {e}")
            conn.rollback()
            return False
        finally: conn.close()

    # --- Métodos de Negocio ---
    # Usuarios
    def authenticate(self, username, password):
        user = self.fetch_one("SELECT * FROM Usuarios WHERE username = %s", (username,))
        if user and user['password'] == Security.hash_password(password):
            return user
        return None
    
    def get_users(self): return self.fetch_all("SELECT * FROM Usuarios ORDER BY username")
    def add_user(self, u, p, r): return self.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", (u, Security.hash_password(p), r))
    def delete_user(self, uid): return self.execute("DELETE FROM Usuarios WHERE id = %s", (uid,))

    # Escuela
    def get_ciclo_activo(self): return self.fetch_one("SELECT * FROM Ciclos WHERE activo = 1")
    
    def get_cursos_activos(self):
        ciclo = self.get_ciclo_activo()
        if not ciclo: return []
        return self.fetch_all("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],))

    def get_alumnos_curso(self, curso_id):
        return self.fetch_all("SELECT * FROM Alumnos WHERE curso_id = %s ORDER BY nombre", (curso_id,))

    def get_alumno(self, aid):
        return self.fetch_one("""
            SELECT a.*, c.nombre as curso_nombre, ci.nombre as ciclo_nombre
            FROM Alumnos a 
            JOIN Cursos c ON a.curso_id = c.id 
            JOIN Ciclos ci ON c.ciclo_id = ci.id
            WHERE a.id = %s
        """, (aid,))

    def search_alumnos(self, term):
        term = f"%{term}%"
        return self.fetch_all("""
            SELECT a.*, c.nombre as curso_nombre, ci.nombre as ciclo_nombre 
            FROM Alumnos a 
            JOIN Cursos c ON a.curso_id = c.id 
            JOIN Ciclos ci ON c.ciclo_id = ci.id
            WHERE (a.nombre ILIKE %s OR a.dni ILIKE %s) AND ci.activo = 1
            ORDER BY a.nombre
        """, (term, term))

    def add_curso(self, nombre, ciclo_id): return self.execute("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (nombre, ciclo_id))
    def delete_curso(self, cid): return self.execute("DELETE FROM Cursos WHERE id = %s", (cid,))
    
    def add_alumno(self, data):
        return self.execute("INSERT INTO Alumnos (curso_id, nombre, dni, observaciones, tutor_nombre, tutor_telefono) VALUES (%s, %s, %s, %s, %s, %s)", 
                          (data['curso_id'], data['nombre'], data['dni'], data['obs'], data['tn'], data['tt']))
    
    def update_alumno(self, aid, data):
        return self.execute("UPDATE Alumnos SET nombre=%s, dni=%s, observaciones=%s, tutor_nombre=%s, tutor_telefono=%s WHERE id=%s", 
                          (data['nombre'], data['dni'], data['obs'], data['tn'], data['tt'], aid))
    
    def delete_alumno(self, aid): return self.execute("DELETE FROM Alumnos WHERE id = %s", (aid,))

    # Asistencia
    def get_day_status(self, curso_id, fecha):
        rows = self.fetch_all("SELECT alumno_id, status FROM Asistencia WHERE fecha = %s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, curso_id))
        return {row['alumno_id']: row['status'] for row in rows}

    def mark_attendance(self, aid, fecha, status):
        q = "INSERT INTO Asistencia (alumno_id, fecha, status) VALUES (%s, %s, %s) ON CONFLICT (alumno_id, fecha) DO UPDATE SET status = EXCLUDED.status"
        return self.execute(q, (aid, fecha, status))

    def get_stats(self, aid):
        rows = self.fetch_all("SELECT status FROM Asistencia WHERE alumno_id = %s", (aid,))
        statuses = [r['status'] for r in rows]
        c = {k: statuses.count(k) for k in ['P','T','A','J','S','N']}
        faltas = c['A'] + c['S'] + (c['T'] * 0.25)
        total = sum(c[k] for k in ['P','T','A','J','S'])
        pct = (faltas / total * 100) if total > 0 else 0
        return {'p': c['P'], 'a': c['A'], 't': c['T'], 'faltas': faltas, 'pct': round(pct, 1), 'total': total}

    def get_history(self, aid):
        return self.fetch_all("SELECT fecha, status FROM Asistencia WHERE alumno_id = %s ORDER BY fecha DESC", (aid,))

    def get_report_matrix(self, curso_id, start, end):
        alumnos = self.get_alumnos_curso(curso_id)
        raw_data = self.fetch_all("SELECT alumno_id, status FROM Asistencia WHERE fecha >= %s AND fecha <= %s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (start, end, curso_id))
        
        map_asis = {}
        for r in raw_data:
            if r['alumno_id'] not in map_asis: map_asis[r['alumno_id']] = []
            map_asis[r['alumno_id']].append(r['status'])
            
        report = []
        for a in alumnos:
            sts = map_asis.get(a['id'], [])
            c = {k: sts.count(k) for k in ['P','T','A','J','S','N']}
            faltas = c['A'] + c['S'] + (c['T'] * 0.25)
            total = sum(c[k] for k in ['P','T','A','J','S'])
            pct = (faltas / total * 100) if total > 0 else 0
            
            report.append({
                **a, 'p': c['P'], 't': c['T'], 'a': c['A'], 'j': c['J'], 's': c['S'],
                'faltas': faltas, 'pct': round(pct, 1)
            })
        return report

# Instancia global (Singleton)
db = DatabaseManager()

# ==============================================================================
# CAPA 4: VISTAS (FRONTEND)
# ==============================================================================

def view_login(page: ft.Page):
    user_tf = ft.TextField(label="Usuario", width=300, bgcolor="white", border_radius=8, prefix_icon="person")
    pass_tf = ft.TextField(label="Contraseña", password=True, width=300, bgcolor="white", border_radius=8, prefix_icon="lock", can_reveal_password=True)

    def login(e):
        user = db.authenticate(user_tf.value, pass_tf.value)
        if user:
            page.session.set("user", user)
            page.go("/dashboard")
        else:
            UIHelper.show_snack(page, "Credenciales incorrectas", True)

    return ft.View("/", [
        ft.Container(
            content=ft.Column([
                ft.Icon("school_rounded", size=80, color=THEME["primary"]),
                ft.Text("Sistema de Asistencia", size=28, weight="bold", color=THEME["primary"]),
                ft.Text("UNSAM", size=18, color="grey"),
                ft.Divider(height=30, color="transparent"),
                UIHelper.create_card(ft.Column([
                    user_tf, ft.Container(height=10), pass_tf, ft.Container(height=20),
                    ft.ElevatedButton("INGRESAR", on_click=login, width=300, height=50, bgcolor=THEME["primary"], color="white")
                ], horizontal_alignment="center"), padding=40),
                ft.Container(height=20),
                ft.Text("Admin: admin / admin", size=12, color="grey")
            ], horizontal_alignment="center"),
            alignment=ft.alignment.center, expand=True, bgcolor=THEME["bg"]
        )
    ])

def view_dashboard(page: ft.Page):
    user = page.session.get("user")
    if not user: return view_login(page)
    
    ciclo = db.get_ciclo_activo()
    ciclo_txt = ciclo['nombre'] if ciclo else "Sin Ciclo Activo"
    search_tf = ft.TextField(hint_text="Buscar alumno...", expand=True, bgcolor="white", border_radius=20, border_color="transparent")
    
    def search(e):
        if search_tf.value:
            page.session.set("search_term", search_tf.value)
            page.go("/search")
    search_tf.on_submit = search
    
    grid = ft.GridView(runs_count=2, max_extent=400, child_aspect_ratio=2.5, spacing=15, run_spacing=15)
    
    def load():
        grid.controls.clear()
        cursos = db.get_cursos_activos()
        if not cursos:
            grid.controls.append(ft.Text("No hay cursos activos.", italic=True, color="grey"))

        for c in cursos:
            def go(e, cid=c['id'], cn=c['nombre']):
                page.session.set("curso_id", cid)
                page.session.set("curso_nombre", cn)
                page.go("/curso")
            
            grid.controls.append(UIHelper.create_card(
                ft.Row([
                    ft.Row([
                        ft.Container(content=ft.Icon("class_", color="white"), bgcolor=THEME["primary"], border_radius=10, padding=12),
                        ft.Text(c['nombre'], size=18, weight=ft.FontWeight.W_600, color=THEME["text"])
                    ]),
                    ft.IconButton("arrow_forward_ios", icon_color=THEME["primary"], on_click=go)
                ], alignment="spaceBetween"), padding=15, on_click=go
            ))
        page.update()

    load()
    
    actions = [ft.IconButton("logout", icon_color="white", on_click=lambda _: page.go("/"))]
    if user['role'] == 'admin': actions.insert(0, ft.IconButton("settings", icon_color="white", on_click=lambda _: page.go("/admin")))

    fab = None
    if user['role'] == 'admin':
        def add_curso_dlg(e):
            tf = ft.TextField(label="Nombre")
            def save(e):
                if not ciclo: return UIHelper.show_snack(page, "Falta ciclo activo", True)
                if tf.value:
                     db.add_curso(tf.value, ciclo['id'])
                     page.close_dialog()
                     load()
            page.dialog = ft.AlertDialog(title=ft.Text("Nuevo Curso"), content=tf, actions=[ft.TextButton("Guardar", on_click=save)])
            page.dialog.open = True; page.update()
        fab = ft.FloatingActionButton(icon="add", on_click=add_curso_dlg, bgcolor=THEME["primary"])

    return ft.View("/dashboard", [
        UIHelper.create_header("Panel Principal", f"Ciclo: {ciclo_txt}", actions=actions),
        ft.Container(content=ft.Column([
            ft.Container(content=search_tf, padding=ft.padding.only(bottom=20)),
            ft.Text("Mis Cursos", size=22, weight="bold"),
            ft.Divider(height=10, color="transparent"),
            grid
        ], expand=True), padding=20, expand=True)
    ], floating_action_button=fab)

def view_curso(page: ft.Page):
    cid = page.session.get("curso_id")
    if not cid: return view_dashboard(page)
    
    # --- TAB 1: ALUMNOS ---
    lv = ft.Column(scroll="auto", expand=True)
    def load_alumnos():
        lv.controls.clear()
        als = db.get_alumnos_curso(cid)
        if not als: lv.controls.append(ft.Text("Sin alumnos", italic=True))
        for a in als:
            def det(e, aid=a['id']): page.session.set("alumno_id", aid); page.go("/student_detail")
            def edt(e, aid=a['id']): page.session.set("alumno_id_edit", aid); page.go("/form_student")
            
            lv.controls.append(UIHelper.create_card(ft.ListTile(
                leading=ft.CircleAvatar(content=ft.Text(a['nombre'][0]), bgcolor=THEME["secondary"], color="white"),
                title=ft.Text(a['nombre'], weight="bold"),
                subtitle=ft.Text(f"DNI: {a['dni'] or '-'}"),
                on_click=det,
                trailing=ft.IconButton("edit", on_click=edt)
            ), padding=0))
        page.update()

    # --- TAB 2: ASISTENCIA ---
    date_tf = ft.TextField(label="Fecha", value=date.today().isoformat(), width=150, height=40, text_size=14)
    asist_col = ft.Column(scroll="auto", expand=True)
    
    def load_asist(e=None):
        asist_col.controls.clear()
        status_map = db.get_day_status(cid, date_tf.value)
        for a in db.get_alumnos_curso(cid):
            dd = ft.Dropdown(
                width=100, height=40, text_size=14, value=status_map.get(a['id'], "P"),
                options=[ft.dropdown.Option(x) for x in ["P","T","A","J"]],
                on_change=lambda e, aid=a['id']: db.mark_attendance(aid, date_tf.value, e.control.value)
            )
            asist_col.controls.append(ft.Container(content=ft.Row([ft.Text(a['nombre'], expand=True, weight="w500"), dd]), padding=5, border=ft.border.only(bottom=ft.border.BorderSide(1, "grey200"))))
        page.update()

    # --- TAB 3: REPORTES ---
    rep_col = ft.Column(scroll="auto", expand=True)
    
    def export_excel(e):
        if not pd: return UIHelper.show_snack(page, "Error librerias", True)
        data = db.get_report_matrix(cid, date.today().replace(month=1, day=1).isoformat(), date.today().isoformat())
        df = pd.DataFrame(data).drop(columns=['id','curso_id','tutor_nombre','tutor_telefono','observaciones'], errors='ignore')
        
        bio = io.BytesIO()
        df.to_excel(bio, index=False)
        b64 = base64.b64encode(bio.getvalue()).decode()
        page.launch_url(f"data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}", web_window_name="reporte.xlsx")

    tabs = ft.Tabs(selected_index=0, tabs=[
        ft.Tab(text="Alumnos", icon="people", content=ft.Container(content=lv, padding=10)),
        ft.Tab(text="Asistencia", icon="check_circle", content=ft.Container(content=ft.Column([ft.Row([date_tf, ft.IconButton("refresh", on_click=load_asistencia_ui)]), ft.Divider(), asist_col]), padding=10)),
        ft.Tab(text="Reportes", icon="bar_chart", content=ft.Container(content=ft.Column([ft.ElevatedButton("Exportar Excel", icon="download", on_click=export_excel, bgcolor="green", color="white")]), padding=10))
    ], expand=True, on_change=lambda e: (load_alumnos() if e.control.selected_index==0 else (load_asistencia_ui() if e.control.selected_index==1 else None)))

    # Wrapper para refrescar la tab correcta
    def load_asistencia_ui(e=None): load_asist(e)

    load_alumnos()

    return ft.View("/curso", [
        UIHelper.create_header(page.session.get("curso_nombre"), "Gestión", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
        ft.Container(content=tabs, expand=True, bgcolor=THEME["bg"]),
        ft.FloatingActionButton(icon="add", bgcolor=THEME["primary"], on_click=lambda _: (page.session.set("alumno_id_edit", None), page.go("/form_student")))
    ])

def view_student_detail(page: ft.Page):
    aid = page.session.get("alumno_id")
    if not aid: return view_dashboard(page)
    
    st = db.get_alumno(aid)
    stats = db.get_stats(aid)
    
    def stat_card(label, val, color="black"):
        return ft.Container(content=ft.Column([ft.Text(str(val), size=24, weight="bold", color=color), ft.Text(label, size=12, color="grey")], horizontal_alignment="center"), padding=15, bgcolor="white", border_radius=10, expand=True, border=ft.border.all(1, "grey200"))

    stat_row = ft.Row([
        stat_card("Faltas", stats['faltas'], THEME["danger"] if stats['faltas']>20 else "black"),
        stat_card("% Aus.", f"{stats['pct']}%"),
        stat_card("Presentes", stats['p'], THEME["success"])
    ], spacing=10)

    return ft.View("/student_detail", [
        UIHelper.create_header("Ficha Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
        ft.Container(content=ft.Column([
            UIHelper.create_card(ft.Column([
                ft.Row([ft.Icon("person", size=50, color=THEME["primary"]), ft.Column([ft.Text(st['nombre'], size=24, weight="bold"), ft.Text(f"DNI: {st['dni']}", color="grey")])]),
                ft.Divider(),
                ft.Text("Estadísticas", weight="bold", color=THEME["primary"]), stat_row,
                ft.Divider(),
                ft.Text("Contacto", weight="bold"), ft.Text(f"Tutor: {st['tutor_nombre']} ({st['tutor_telefono']})"),
                ft.Text("Observaciones", weight="bold"), ft.Text(st['observaciones'], italic=True)
            ]), padding=25)
        ], scroll="auto"), padding=20, expand=True, bgcolor=THEME["bg"])
    ])

def view_form_student(page: ft.Page):
    cid = page.session.get("curso_id"); aid = page.session.get("alumno_id_edit"); is_edit = aid is not None
    nm = ft.TextField(label="Nombre"); dn = ft.TextField(label="DNI"); tn = ft.TextField(label="Tutor"); tt = ft.TextField(label="Tel. Tutor"); ob = ft.TextField(label="Obs", multiline=True)
    
    if is_edit:
        d = db.get_alumno(aid)
        nm.value=d['nombre']; dn.value=d['dni']; tn.value=d['tutor_nombre']; tt.value=d['tutor_telefono']; ob.value=d['observaciones']

    def save(e):
        if not nm.value: return UIHelper.show_snack(page, "Nombre obligatorio", True)
        data = {'curso_id': cid, 'nombre': nm.value, 'dni': dn.value, 'tn': tn.value, 'tt': tt.value, 'obs': ob.value}
        if is_edit: db.update_alumno(aid, data)
        else: 
            if not db.add_alumno(data): return UIHelper.show_snack(page, "Error al guardar", True)
        page.go("/curso")

    return ft.View("/form_student", [
        UIHelper.create_header("Editar Alumno" if is_edit else "Nuevo Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
        ft.Container(content=UIHelper.create_card(ft.Column([nm, dn, tn, tt, ob, ft.ElevatedButton("Guardar", on_click=save, bgcolor=THEME["success"], color="white", width=float("inf"))])), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_admin(page: ft.Page):
    return ft.View("/admin", [
        UIHelper.create_header("Admin", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
        ft.Container(content=ft.Column([
            UIHelper.create_card(ft.ListTile(leading=ft.Icon("calendar_month"), title=ft.Text("Gestión de Ciclos"), on_click=lambda _: UIHelper.show_snack(page, "Demo: No implementado", True))),
            UIHelper.create_card(ft.ListTile(leading=ft.Icon("people"), title=ft.Text("Gestión de Usuarios"), on_click=lambda _: UIHelper.show_snack(page, "Demo: No implementado", True)))
        ]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_search(page: ft.Page):
    term = page.session.get("search_term"); res = db.search_alumnos(term); col = ft.Column(scroll="auto")
    if not res: col.controls.append(ft.Text("Sin resultados"))
    for r in res:
        def clk(e, aid=r['id'], cid=r['curso_id'], cn=r['curso_nombre']): 
             page.session.set("alumno_id", aid); page.session.set("curso_id", cid); page.session.set("curso_nombre", cn); page.go("/student_detail")
        col.controls.append(UIHelper.create_card(ft.ListTile(title=ft.Text(r['nombre']), subtitle=ft.Text(f"{r['curso_nombre']} - {r['dni']}"), on_click=clk), padding=0))
    return ft.View("/search", [
        UIHelper.create_header(f"Búsqueda: {term}", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
        ft.Container(content=col, padding=20, bgcolor=THEME["bg"], expand=True)
    ])

# ==============================================================================
# MAIN ROUTER
# ==============================================================================

def main(page: ft.Page):
    page.title = "Asistencia UNSAM"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 0

    routes = {
        "/": view_login,
        "/dashboard": view_dashboard,
        "/curso": view_curso,
        "/student_detail": view_student_detail,
        "/form_student": view_form_student,
        "/form_curso": view_form_student, # Reusado temporalmente o crear view_form_curso
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
