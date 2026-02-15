import flet as ft
import psycopg2
import psycopg2.extras
import hashlib
from datetime import date, datetime
import os
import threading
import io
import base64

# --- CAPA 0: DEPENDENCIAS EXTERNAS ---
print("--- Oñepyrũ aplicación v5.0 (Excel + Docs por Curso) ---", flush=True)

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None
    print("⚠️ XlsxWriter no instalado. La exportación fallará.")

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

class UIHelper:
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
        if isinstance(subtitle, str):
            sub_control = ft.Text(subtitle, size=12, color="white70") if subtitle else ft.Container()
        elif isinstance(subtitle, ft.Control):
            sub_control = subtitle
        else:
            sub_control = ft.Container()
            
        return ft.Container(
            content=ft.Row([
                ft.Row([
                    leading if leading else ft.Container(),
                    ft.Column([
                        ft.Text(title, size=20, weight="bold", color="white"),
                        sub_control
                    ], spacing=2)
                ]),
                ft.Row(actions, spacing=0) if actions else ft.Container()
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=20, vertical=15),
            bgcolor=THEME["primary"],
            shadow=ft.BoxShadow(blur_radius=5, color="black12", offset=ft.Offset(0, 2))
        )

class Security:
    @staticmethod
    def hash_password(password: str) -> str:
        return hashlib.sha256(password.encode()).hexdigest()

# ==============================================================================
# CAPA 2: GESTIÓN DE BASE DE DATOS
# ==============================================================================

class DatabaseManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(DatabaseManager, cls).__new__(cls)
                    cls._instance._init_db_structure()
        return cls._instance

    def get_connection(self):
        database_url = os.environ.get('DATABASE_URL')
        try:
            if database_url:
                if database_url.startswith('postgres://'):
                    database_url = database_url.replace('postgres://', 'postgresql://', 1)
                return psycopg2.connect(database_url, sslmode='require')
            else:
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
        conn = self.get_connection()
        if not conn: return
        try:
            with conn.cursor() as cur:
                cur.execute("CREATE TABLE IF NOT EXISTS Usuarios (id SERIAL PRIMARY KEY, username TEXT UNIQUE, password TEXT, role TEXT)")
                cur.execute("CREATE TABLE IF NOT EXISTS Ciclos (id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, activo INTEGER DEFAULT 0)")
                cur.execute("CREATE TABLE IF NOT EXISTS Cursos (id SERIAL PRIMARY KEY, nombre TEXT, ciclo_id INTEGER REFERENCES Ciclos(id) ON DELETE CASCADE)")
                cur.execute("CREATE TABLE IF NOT EXISTS Usuario_Cursos (usuario_id INTEGER REFERENCES Usuarios(id) ON DELETE CASCADE, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, PRIMARY KEY (usuario_id, curso_id))")

                cur.execute("""CREATE TABLE IF NOT EXISTS Alumnos (
                    id SERIAL PRIMARY KEY, 
                    curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, 
                    nombre TEXT, dni TEXT, observaciones TEXT, 
                    tutor_nombre TEXT, tutor_telefono TEXT, 
                    tpp INTEGER DEFAULT 0, tpp_dias TEXT, 
                    UNIQUE(curso_id, nombre)
                )""")
                
                cur.execute("CREATE TABLE IF NOT EXISTS Asistencia (id SERIAL PRIMARY KEY, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, fecha TEXT, status TEXT, UNIQUE(alumno_id, fecha))")

                # MODIFICADO: Requisitos ahora dependen del CURSO
                cur.execute("CREATE TABLE IF NOT EXISTS Requisitos (id SERIAL PRIMARY KEY, curso_id INTEGER REFERENCES Cursos(id) ON DELETE CASCADE, descripcion TEXT)")
                cur.execute("CREATE TABLE IF NOT EXISTS Documentacion_Alumno (requisito_id INTEGER REFERENCES Requisitos(id) ON DELETE CASCADE, alumno_id INTEGER REFERENCES Alumnos(id) ON DELETE CASCADE, entregado INTEGER DEFAULT 0, PRIMARY KEY (requisito_id, alumno_id))")

                cur.execute("SELECT COUNT(*) FROM Usuarios")
                if cur.fetchone()[0] == 0:
                    cur.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", ("admin", Security.hash_password("admin"), "admin"))
            conn.commit()
            print("✅ DB PostgreSQL Estructura OK.")
        except Exception as e:
            print(f"❌ Error Init DB: {e}")
        finally:
            conn.close()

    def fetch_all(self, query, params=()):
        conn = self.get_connection()
        if not conn: return []
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                return [dict(row) for row in cur.fetchall()]
        except Exception as e:
            print(f"❌ Error Fetch All: {e}")
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
        except Exception as e:
            print(f"❌ Error Fetch One: {e}")
            return None
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
            print(f"❌ Error Execute: {e}")
            conn.rollback()
            return False
        finally: conn.close()

db = DatabaseManager()

# ==============================================================================
# CAPA 3: SERVICIOS DE NEGOCIO
# ==============================================================================

class UserService:
    @staticmethod
    def login(username, password):
        user = db.fetch_one("SELECT * FROM Usuarios WHERE username = %s", (username,))
        if user and user['password'] == Security.hash_password(password):
            return user
        return None
    @staticmethod
    def get_users(): return db.fetch_all("SELECT * FROM Usuarios ORDER BY username")
    @staticmethod
    def add_user(u, p, r): return db.execute("INSERT INTO Usuarios (username, password, role) VALUES (%s, %s, %s)", (u, Security.hash_password(p), r))
    @staticmethod
    def delete_user(uid): return db.execute("DELETE FROM Usuarios WHERE id = %s", (uid,))
    
    @staticmethod
    def get_user_cursos(uid):
        rows = db.fetch_all("SELECT curso_id FROM Usuario_Cursos WHERE usuario_id = %s", (uid,))
        return [r['curso_id'] for r in rows]

    @staticmethod
    def toggle_user_curso(uid, cid, assign):
        if assign:
            db.execute("INSERT INTO Usuario_Cursos (usuario_id, curso_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (uid, cid))
        else:
            db.execute("DELETE FROM Usuario_Cursos WHERE usuario_id = %s AND curso_id = %s", (uid, cid))

class SchoolService:
    @staticmethod
    def get_ciclos(): return db.fetch_all("SELECT * FROM Ciclos ORDER BY nombre DESC")
    @staticmethod
    def get_ciclo_activo(): return db.fetch_one("SELECT * FROM Ciclos WHERE activo = 1 LIMIT 1")
    
    @staticmethod
    def add_ciclo(nombre):
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE Ciclos SET activo = 0")
                cur.execute("INSERT INTO Ciclos (nombre, activo) VALUES (%s, 1)", (nombre,))
            conn.commit(); return True
        except: conn.rollback(); return False
        finally: conn.close()

    @staticmethod
    def activar_ciclo(cid):
        conn = db.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE Ciclos SET activo = 0")
                cur.execute("UPDATE Ciclos SET activo = 1 WHERE id = %s", (int(cid),))
            conn.commit()
        finally: conn.close()
    
    @staticmethod
    def delete_ciclo(cid): return db.execute("DELETE FROM Ciclos WHERE id = %s", (cid,))

    @staticmethod
    def get_cursos_activos(user_id=None, role=None):
        ciclo = SchoolService.get_ciclo_activo()
        if not ciclo: return []
        if role == 'admin':
            return db.fetch_all("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],))
        else:
            return db.fetch_all("SELECT c.* FROM Cursos c JOIN Usuario_Cursos uc ON c.id = uc.curso_id WHERE c.ciclo_id = %s AND uc.usuario_id = %s ORDER BY c.nombre", (ciclo['id'], user_id))
            
    @staticmethod
    def get_cursos_all_active():
        ciclo = SchoolService.get_ciclo_activo()
        if not ciclo: return []
        return db.fetch_all("SELECT * FROM Cursos WHERE ciclo_id = %s ORDER BY nombre", (ciclo['id'],))

    @staticmethod
    def get_alumnos(curso_id): return db.fetch_all("SELECT * FROM Alumnos WHERE curso_id = %s ORDER BY nombre", (curso_id,))
    
    @staticmethod
    def get_alumno(aid):
        return db.fetch_one("""
            SELECT a.*, c.nombre as curso_nombre, ci.nombre as ciclo_nombre, c.id as curso_id
            FROM Alumnos a 
            JOIN Cursos c ON a.curso_id = c.id 
            JOIN Ciclos ci ON c.ciclo_id = ci.id
            WHERE a.id = %s
        """, (aid,))

    @staticmethod
    def add_curso(nombre, ciclo_id): return db.execute("INSERT INTO Cursos (nombre, ciclo_id) VALUES (%s, %s)", (nombre, ciclo_id))
    
    @staticmethod
    def add_alumno(data):
        return db.execute("INSERT INTO Alumnos (curso_id, nombre, dni, observaciones, tutor_nombre, tutor_telefono, tpp, tpp_dias) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", 
                          (data['curso_id'], data['nombre'], data['dni'], data['obs'], data['tn'], data['tt'], data['tpp'], data['tpp_dias']))
    
    @staticmethod
    def update_alumno(aid, data):
        return db.execute("UPDATE Alumnos SET nombre=%s, dni=%s, observaciones=%s, tutor_nombre=%s, tutor_telefono=%s, tpp=%s, tpp_dias=%s WHERE id=%s", 
                          (data['nombre'], data['dni'], data['obs'], data['tn'], data['tt'], data['tpp'], data['tpp_dias'], aid))

class DocService:
    @staticmethod
    def get_requisitos_curso(curso_id):
        # AHORA filtra por curso
        return db.fetch_all("SELECT * FROM Requisitos WHERE curso_id = %s ORDER BY descripcion", (curso_id,))
    
    @staticmethod
    def add_requisito(curso_id, desc):
        return db.execute("INSERT INTO Requisitos (curso_id, descripcion) VALUES (%s, %s)", (curso_id, desc))
    
    @staticmethod
    def delete_requisito(rid):
        return db.execute("DELETE FROM Requisitos WHERE id = %s", (rid,))
    
    @staticmethod
    def get_estado_alumno(aid):
        rows = db.fetch_all("SELECT requisito_id, entregado FROM Documentacion_Alumno WHERE alumno_id = %s", (aid,))
        return {r['requisito_id']: r['entregado'] for r in rows}
    
    @staticmethod
    def toggle_entrega(aid, rid, estado):
        val = 1 if estado else 0
        q = "INSERT INTO Documentacion_Alumno (requisito_id, alumno_id, entregado) VALUES (%s, %s, %s) ON CONFLICT (requisito_id, alumno_id) DO UPDATE SET entregado=EXCLUDED.entregado"
        db.execute(q, (rid, aid, val))

class AttendanceService:
    @staticmethod
    def get_day_status(curso_id, fecha):
        rows = db.fetch_all("SELECT alumno_id, status FROM Asistencia WHERE fecha = %s AND alumno_id IN (SELECT id FROM Alumnos WHERE curso_id=%s)", (fecha, curso_id))
        return {row['alumno_id']: row['status'] for row in rows}

    @staticmethod
    def mark(aid, fecha, status):
        q = "INSERT INTO Asistencia (alumno_id, fecha, status) VALUES (%s, %s, %s) ON CONFLICT (alumno_id, fecha) DO UPDATE SET status = EXCLUDED.status"
        return db.execute(q, (aid, fecha, status))

    @staticmethod
    def get_stats(aid):
        rows = db.fetch_all("SELECT status FROM Asistencia WHERE alumno_id = %s", (aid,))
        c = {k: 0 for k in ['P','T','A','J','S','N']}
        for r in rows:
            if r['status'] in c: c[r['status']] += 1
        faltas = c['A'] + c['S'] + (c['T'] * 0.25)
        total = sum(c[k] for k in ['P','T','A','J','S'])
        pct = (faltas / total * 100) if total > 0 else 0
        return {'p': c['P'], 'a': c['A'], 't': c['T'], 'faltas': faltas, 'pct': round(pct, 1), 'total': total}

    @staticmethod
    def get_history(aid):
        return db.fetch_all("SELECT fecha, status FROM Asistencia WHERE alumno_id = %s ORDER BY fecha DESC", (aid,))

class ReportService:
    @staticmethod
    def generate_excel_curso(curso_id):
        if not xlsxwriter: return None
        
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        ws = workbook.add_worksheet("Alumnos")
        
        # Estilos
        bold = workbook.add_format({'bold': True, 'bg_color': '#D3D3D3', 'border': 1})
        border = workbook.add_format({'border': 1})
        red = workbook.add_format({'color': 'red', 'border': 1})
        
        # Headers
        headers = ["Nombre", "DNI", "Tutor", "% Asist.", "Faltas", "Docs Faltantes"]
        ws.write_row(0, 0, headers, bold)
        ws.set_column(0, 0, 25) # Nombre ancho
        
        alumnos = SchoolService.get_alumnos(curso_id)
        reqs = DocService.get_requisitos_curso(curso_id)
        
        for i, a in enumerate(alumnos, start=1):
            stats = AttendanceService.get_stats(a['id'])
            
            # Docs
            estado_docs = DocService.get_estado_alumno(a['id'])
            faltantes = []
            for r in reqs:
                if estado_docs.get(r['id']) != 1:
                    faltantes.append(r['descripcion'])
            
            ws.write(i, 0, a['nombre'], border)
            ws.write(i, 1, a['dni'] or "-", border)
            ws.write(i, 2, f"{a['tutor_nombre'] or ''} ({a['tutor_telefono'] or ''})", border)
            ws.write(i, 3, f"{100 - stats['pct']}%", border)
            ws.write(i, 4, stats['faltas'], red if stats['faltas'] > 10 else border)
            ws.write(i, 5, ", ".join(faltantes), border)
            
        workbook.close()
        output.seek(0)
        return output

# ==============================================================================
# CAPA 4: VISTAS (FRONTEND)
# ==============================================================================

def view_login(page: ft.Page):
    user_tf = ft.TextField(label="Usuario", width=300, bgcolor="white", border_radius=8, prefix_icon="person")
    pass_tf = ft.TextField(label="Contraseña", password=True, width=300, bgcolor="white", border_radius=8, prefix_icon="lock", can_reveal_password=True)

    def login(e):
        user = UserService.login(user_tf.value, pass_tf.value)
        if user:
            page.session.set("user", user)
            page.route = "/dashboard"
            page.update()
        else:
            UIHelper.show_snack(page, "Credenciales incorrectas", True)

    return ft.View("/", [
        ft.Container(
            content=ft.Column([
                ft.Icon("school_rounded", size=80, color=THEME["primary"]),
                ft.Text("Asistencia UNSAM", size=28, weight="bold", color=THEME["secondary"]),
                UIHelper.create_card(ft.Column([
                    user_tf, ft.Container(height=10), pass_tf, ft.Container(height=20),
                    ft.ElevatedButton("INGRESAR", on_click=login, width=300, height=50, bgcolor=THEME["primary"], color="white")
                ], horizontal_alignment="center"), padding=40),
            ], horizontal_alignment="center"),
            alignment=ft.alignment.center, expand=True, bgcolor=THEME["bg"]
        )
    ])

def view_dashboard(page: ft.Page):
    user = page.session.get("user")
    if not user: return view_login(page)
    
    txt_ciclo = ft.Text("Cargando...", weight="bold", color="white")
    grid = ft.GridView(runs_count=2, max_extent=400, child_aspect_ratio=2.5, spacing=15, run_spacing=15)
    
    def load():
        ciclo = SchoolService.get_ciclo_activo()
        grid.controls.clear()
        
        if not ciclo:
            txt_ciclo.value = "⚠️ SIN CICLO ACTIVO"
            txt_ciclo.color = "#FFCDD2"
            grid.controls.append(ft.Text("No hay ciclo lectivo activo.", italic=True, color="red"))
        else:
            txt_ciclo.value = f"Ciclo: {ciclo['nombre']}"
            txt_ciclo.color = "white"
            cursos = SchoolService.get_cursos_activos(user['id'], user['role'])
            
            if not cursos:
                msg = "No tenés cursos asignados." if user['role'] != 'admin' else "No hay cursos."
                grid.controls.append(ft.Text(msg, italic=True, color="grey"))

            for c in cursos:
                def go(e, cid=c['id'], cn=c['nombre']):
                    page.session.set("curso_id", cid); page.session.set("curso_nombre", cn); page.route = "/curso"; page.update()
                
                grid.controls.append(UIHelper.create_card(
                    ft.Row([
                        ft.Row([
                            ft.Container(content=ft.Icon("class_", color="white"), bgcolor=THEME["primary"], border_radius=10, padding=12),
                            ft.Text(c['nombre'], size=18, weight="bold", color=THEME["text"])
                        ]),
                        ft.IconButton("arrow_forward_ios", icon_color=THEME["primary"], on_click=go)
                    ], alignment="spaceBetween"), padding=15, on_click=go
                ))

    load()

    actions = [ft.IconButton("logout", icon_color="white", on_click=lambda _: page.go("/"))]
    if user['role'] == 'admin': 
        actions.insert(0, ft.IconButton("settings", icon_color="white", on_click=lambda _: page.go("/admin")))

    fab = None
    if user['role'] == "admin":
        def add_curso_dlg(e):
            ciclo_actual = SchoolService.get_ciclo_activo()
            if not ciclo_actual: 
                return UIHelper.show_snack(page, "Debe activar un ciclo primero", True)
            
            tf_nombre = ft.TextField(label="Nombre del Curso")
            def save_curso(e):
                if tf_nombre.value:
                    if SchoolService.add_curso(tf_nombre.value, ciclo_actual['id']):
                        page.close(dlg); load(); page.update(); UIHelper.show_snack(page, "Curso creado")
                    else: UIHelper.show_snack(page, "Error al crear", True)
            
            dlg = ft.AlertDialog(title=ft.Text("Nuevo Curso"), content=tf_nombre, actions=[ft.TextButton("Guardar", on_click=save_curso)])
            page.open(dlg)
        fab = ft.FloatingActionButton(icon="add", on_click=add_curso_dlg, bgcolor=THEME["primary"])
        
    return ft.View("/dashboard", [
        UIHelper.create_header("Panel Principal", subtitle=txt_ciclo, actions=actions),
        ft.Container(content=ft.Column([
            ft.Text("Mis Cursos", size=22, weight="bold"),
            ft.Divider(height=10, color="transparent"),
            grid
        ], expand=True), padding=20, expand=True)
    ], floating_action_button=fab)

def view_curso(page: ft.Page):
    cid = page.session.get("curso_id")
    cn = page.session.get("curso_nombre")
    if not cid: return view_dashboard(page)
    
    # --- Gestor de Archivos (Para exportar Excel) ---
    file_picker = ft.FilePicker(on_result=lambda e: save_file_result(e))
    page.overlay.append(file_picker)

    def save_file_result(e: ft.FilePickerResultEvent):
        if e.path:
            try:
                excel_data = ReportService.generate_excel_curso(cid)
                if excel_data:
                    with open(e.path, "wb") as f:
                        f.write(excel_data.read())
                    UIHelper.show_snack(page, "Archivo guardado exitosamente.")
                else:
                    UIHelper.show_snack(page, "Error al generar Excel (¿Librería instalada?)", True)
            except Exception as ex:
                UIHelper.show_snack(page, f"Error guardando: {ex}", True)

    def export_excel(e):
        fname = f"Reporte_{cn}_{date.today()}.xlsx"
        file_picker.save_file(file_name=fname)

    # --- Gestor de Requisitos (Docs) ---
    def open_reqs_dlg(e):
        tf_req = ft.TextField(label="Nuevo Requisito (ej: Ficha Médica)")
        list_col = ft.Column()
        
        def load_reqs_local():
            list_col.controls.clear()
            reqs = DocService.get_requisitos_curso(cid)
            if not reqs: list_col.controls.append(ft.Text("Sin requisitos.", italic=True, size=12))
            for r in reqs:
                list_col.controls.append(ft.ListTile(
                    title=ft.Text(r['descripcion'], size=14),
                    trailing=ft.IconButton("delete", icon_color="red", icon_size=20, on_click=lambda e, rid=r['id']: (DocService.delete_requisito(rid), load_reqs_local(), page.update()))
                ))
            page.update()

        def add_req_local(e):
            if tf_req.value:
                DocService.add_requisito(cid, tf_req.value)
                tf_req.value = ""
                load_reqs_local()
        
        load_reqs_local()
        dlg = ft.AlertDialog(
            title=ft.Text("Documentación del Curso"),
            content=ft.Container(content=ft.Column([
                ft.Row([tf_req, ft.IconButton("add", icon_color="green", on_click=add_req_local)]),
                ft.Divider(),
                ft.Text("Lista de pedidos:", weight="bold", size=12),
                ft.Container(content=list_col, height=200) # Scroll limitado
            ], width=300), height=300),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: page.close(dlg))]
        )
        page.open(dlg)

    # --- UI Principal ---
    lv = ft.Column(scroll="auto", expand=True)
    def load_alumnos():
        lv.controls.clear()
        for a in SchoolService.get_alumnos(cid):
            def det(e, aid=a['id']): page.session.set("alumno_id", aid); page.go("/student_detail")
            def edt(e, aid=a['id']): page.session.set("alumno_id_edit", aid); page.go("/form_student")
            sub = f"DNI: {a['dni'] or '-'}"
            if a['tpp'] == 1: sub += " | ⚠️ TPP"
            lv.controls.append(UIHelper.create_card(ft.ListTile(
                leading=ft.CircleAvatar(content=ft.Text(a['nombre'][0]), bgcolor=THEME["secondary"], color="white"),
                title=ft.Text(a['nombre'], weight="bold"),
                subtitle=ft.Text(sub),
                on_click=det,
                trailing=ft.IconButton("edit", on_click=edt)
            ), padding=0))
        page.update()

    date_tf = ft.TextField(label="Fecha", value=date.today().isoformat(), width=150, height=40, text_size=14)
    asist_col = ft.Column(scroll="auto", expand=True)
    
    def load_asist(e=None):
        asist_col.controls.clear()
        try:
            d_obj = date.fromisoformat(date_tf.value)
            dia_sem = d_obj.weekday()
            if dia_sem >= 5: UIHelper.show_snack(page, "Aviso: Fin de semana", False)
        except: dia_sem = -1

        status_map = AttendanceService.get_day_status(cid, date_tf.value)
        for a in SchoolService.get_alumnos(cid):
            def_val = "P"
            if a['tpp'] == 1 and a['tpp_dias']:
                if str(dia_sem) not in a['tpp_dias'].split(','):
                    def_val = "N"
            
            val = status_map.get(a['id'], def_val)
            dd = ft.Dropdown(
                width=100, height=40, text_size=14, value=val,
                options=[ft.dropdown.Option(x) for x in ["P","T","A","J","N"]],
                on_change=lambda e, aid=a['id']: AttendanceService.mark(aid, date_tf.value, e.control.value)
            )
            asist_col.controls.append(ft.Container(content=ft.Row([ft.Text(a['nombre'], expand=True, weight="w500"), dd]), padding=5, border=ft.border.only(bottom=ft.border.BorderSide(1, "grey200"))))
        page.update()

    tabs = ft.Tabs(selected_index=0, tabs=[
        ft.Tab(text="Alumnos", icon="people", content=ft.Container(content=lv, padding=10)),
        ft.Tab(text="Asistencia", icon="check_circle", content=ft.Container(content=ft.Column([ft.Row([date_tf, ft.IconButton("refresh", on_click=load_asist)]), ft.Divider(), asist_col]), padding=10))
    ], expand=True, on_change=lambda e: (load_alumnos() if e.control.selected_index==0 else load_asist()))

    load_alumnos()
    
    # Botones de Acción Header
    actions_header = [
        ft.ElevatedButton("📋 Docs", color="white", bgcolor="orange", on_click=open_reqs_dlg),
        ft.ElevatedButton("📊 Excel", color="white", bgcolor="green", on_click=export_excel)
    ]
    
    return ft.View("/curso", [
        UIHelper.create_header(cn, "Gestión", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard")), actions=actions_header),
        ft.Container(content=tabs, expand=True, bgcolor=THEME["bg"]),
        ft.FloatingActionButton(icon="person_add", bgcolor=THEME["primary"], on_click=lambda _: (page.session.set("alumno_id_edit", None), page.go("/form_student")))
    ])

def view_form_student(page: ft.Page):
    cid = page.session.get("curso_id"); aid = page.session.get("alumno_id_edit"); is_edit = aid is not None
    nm = ft.TextField(label="Nombre"); dn = ft.TextField(label="DNI"); tn = ft.TextField(label="Tutor"); tt = ft.TextField(label="Tel. Tutor"); ob = ft.TextField(label="Observaciones", multiline=True)
    
    sw_tpp = ft.Switch(label="Activar Trayectoria (TPP)", value=False)
    checks = [ft.Checkbox(label=d, value=True, data=str(i)) for i, d in enumerate(["Lun","Mar","Mié","Jue","Vie"])]
    cont_days = ft.Column([ft.Text("Días Asistencia:")] + checks, visible=False)
    sw_tpp.on_change = lambda e: (setattr(cont_days, 'visible', sw_tpp.value), page.update())

    if is_edit:
        d = SchoolService.get_alumno(aid)
        if d:
            nm.value=d['nombre']; dn.value=d['dni']; tn.value=d['tutor_nombre']; tt.value=d['tutor_telefono']; ob.value=d['observaciones']
            if d['tpp'] == 1:
                sw_tpp.value = True; cont_days.visible = True
                sd = (d['tpp_dias'] or "").split(',')
                for c in checks: c.value = c.data in sd

    def save(e):
        if not nm.value: return UIHelper.show_snack(page, "Nombre obligatorio", True)
        tpp_days = ",".join([c.data for c in checks if c.value]) if sw_tpp.value else ""
        data = {'curso_id': cid, 'nombre': nm.value, 'dni': dn.value, 'tn': tn.value, 'tt': tt.value, 'obs': ob.value, 'tpp': 1 if sw_tpp.value else 0, 'tpp_dias': tpp_days}
        if is_edit: SchoolService.update_alumno(aid, data)
        else: SchoolService.add_alumno(data)
        page.go("/curso")

    return ft.View("/form_student", [
        UIHelper.create_header("Alumno", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
        ft.Container(content=UIHelper.create_card(ft.Column([
            nm, dn, ft.Divider(), tn, tt, ft.Divider(), ob, ft.Divider(),
            ft.Container(content=ft.Column([sw_tpp, cont_days]), bgcolor="blue50", padding=10, border_radius=10),
            ft.Container(height=10),
            ft.ElevatedButton("Guardar", on_click=save, width=float("inf"), bgcolor=THEME["primary"], color="white")
        ])), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_student_detail(page: ft.Page):
    aid = page.session.get("alumno_id")
    if not aid: return view_dashboard(page)
    alumno = SchoolService.get_alumno(aid)
    if not alumno: return view_dashboard(page)
    
    stats = AttendanceService.get_stats(aid)
    history = AttendanceService.get_history(aid)
    
    # --- Tab Info ---
    info_col = ft.Column([
        ft.Text(f"Nombre: {alumno['nombre']}", size=18, weight="bold"),
        ft.Text(f"DNI: {alumno['dni'] or '-'}"),
        ft.Text(f"Curso: {alumno['curso_nombre']} | Ciclo: {alumno['ciclo_nombre']}"),
        ft.Divider(),
        ft.Text(f"Tutor: {alumno['tutor_nombre'] or '-'} | Tel: {alumno['tutor_telefono'] or '-'}"),
    ])
    
    stats_row = ft.Row([
        UIHelper.create_card(ft.Column([ft.Text("P", size=12), ft.Text(str(stats['p']), size=24, color="green")]), padding=10),
        UIHelper.create_card(ft.Column([ft.Text("A", size=12), ft.Text(str(stats['a']), size=24, color="red")]), padding=10),
        UIHelper.create_card(ft.Column([ft.Text("Faltas", size=12), ft.Text(str(stats['faltas']), size=24, color="indigo")]), padding=10),
    ], spacing=10)
    
    hist_col = ft.Column([ft.Text(f"{h['fecha']}: {h['status']}", size=12) for h in history[:10]], scroll="auto", height=200)

    # --- NUEVO: Tab Documentación (Específico del curso) ---
    docs_col = ft.Column(scroll="auto")
    def load_docs():
        docs_col.controls.clear()
        # Buscamos los requisitos DEL CURSO del alumno
        reqs = DocService.get_requisitos_curso(alumno['curso_id'])
        estados = DocService.get_estado_alumno(aid)
        
        if not reqs:
            docs_col.controls.append(ft.Text("No hay pedidos de documentación en este curso.", italic=True))
        
        for r in reqs:
            is_checked = estados.get(r['id']) == 1
            cb = ft.Checkbox(label=r['descripcion'], value=is_checked, on_change=lambda e, rid=r['id']: (DocService.toggle_entrega(aid, rid, e.control.value), UIHelper.show_snack(page, "Actualizado")))
            docs_col.controls.append(cb)
        page.update()

    tabs = ft.Tabs(selected_index=0, on_change=lambda e: load_docs() if e.control.selected_index == 2 else None, tabs=[
        ft.Tab(text="Info", content=ft.Container(content=info_col, padding=20)),
        ft.Tab(text="Historial", content=ft.Container(content=ft.Column([stats_row, ft.Divider(), hist_col]), padding=20)),
        ft.Tab(text="Documentación", content=ft.Container(content=docs_col, padding=20)),
    ])

    return ft.View("/student_detail", [
        UIHelper.create_header(alumno['nombre'], "Detalle", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/curso"))),
        ft.Container(content=tabs, padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_admin(page: ft.Page):
    return ft.View("/admin", [
        UIHelper.create_header("Administración", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/dashboard"))),
        ft.Container(content=ft.Column([
            UIHelper.create_card(ft.ListTile(leading=ft.Icon("calendar_month", color=THEME["primary"]), title=ft.Text("Ciclos Lectivos"), trailing=ft.Icon("chevron_right"), on_click=lambda _: page.go("/ciclos"))),
            UIHelper.create_card(ft.ListTile(leading=ft.Icon("people", color=THEME["primary"]), title=ft.Text("Usuarios"), trailing=ft.Icon("chevron_right"), on_click=lambda _: page.go("/users"))),
        ]), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_ciclos(page: ft.Page):
    tf = ft.TextField(label="Año (Ej: 2026)", expand=True)
    col = ft.Column(scroll="auto")
    
    def load():
        col.controls.clear()
        for c in SchoolService.get_ciclos():
            is_active = c['activo'] == 1
            if is_active:
                act_btn = ft.Container(content=ft.Text("ACTIVO", color="white", size=10, weight="bold"), bgcolor="green", padding=5, border_radius=5)
            else:
                act_btn = ft.ElevatedButton("Activar", on_click=lambda e, cid=c['id']: (SchoolService.activar_ciclo(cid), load(), page.update()))
            
            del_btn = ft.IconButton("delete", icon_color="red", on_click=lambda e, cid=c['id']: (SchoolService.delete_ciclo(cid), load(), page.update()))
            
            col.controls.append(UIHelper.create_card(ft.ListTile(
                leading=ft.Icon("check_circle" if is_active else "circle_outlined", color="green" if is_active else "grey"),
                title=ft.Text(c['nombre'], weight="bold"),
                trailing=ft.Row([act_btn, del_btn], tight=True)
            ), padding=5))
    
    def add(e):
        if tf.value:
            if SchoolService.add_ciclo(tf.value): tf.value=""; load(); page.update()
            else: UIHelper.show_snack(page, "Error: ¿Ya existe?", True)
            
    load()
    return ft.View("/ciclos", [
        UIHelper.create_header("Ciclos Lectivos", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))),
        ft.Container(content=ft.Column([
            UIHelper.create_card(ft.Row([tf, ft.IconButton("add_circle", icon_color="green", icon_size=40, on_click=add)])),
            ft.Text("Historial", weight="bold"), col
        ], expand=True), padding=20, bgcolor=THEME["bg"], expand=True)
    ])

def view_users(page: ft.Page):
    u = ft.TextField(label="Usuario"); p = ft.TextField(label="Clave", password=True); r = ft.Dropdown(value="preceptor", options=[ft.dropdown.Option("admin"), ft.dropdown.Option("preceptor")])
    col = ft.Column(scroll="auto")
    
    def open_assign_dlg(uid, username):
        cursos = SchoolService.get_cursos_all_active()
        assigned = UserService.get_user_cursos(uid)
        
        checks_col = ft.Column(scroll="auto", height=300)
        
        for c in cursos:
            is_checked = c['id'] in assigned
            cb = ft.Checkbox(label=c['nombre'], value=is_checked, 
                             on_change=lambda e, cid=c['id']: UserService.toggle_user_curso(uid, cid, e.control.value))
            checks_col.controls.append(cb)
            
        dlg = ft.AlertDialog(title=ft.Text(f"Cursos para {username}"), content=checks_col)
        page.open(dlg)

    def load():
        col.controls.clear()
        for us in UserService.get_users():
            actions = []
            if us['role'] != 'admin':
                actions.append(ft.IconButton("assignment_ind", icon_color="blue", tooltip="Asignar Cursos", on_click=lambda e, uid=us['id'], un=us['username']: open_assign_dlg(uid, un)))
            
            if us['username'] != page.session.get("user")['username']:
                actions.append(ft.IconButton("delete", icon_color="red", tooltip="Eliminar", on_click=lambda e, uid=us['id']: (UserService.delete_user(uid), load(), page.update())))
            
            col.controls.append(UIHelper.create_card(ft.ListTile(
                leading=ft.Icon("person"), 
                title=ft.Text(us['username']), 
                subtitle=ft.Text(us['role']), 
                trailing=ft.Row(actions, tight=True)
            ), padding=5))

    def add(e):
        if u.value and p.value:
            UserService.add_user(u.value, p.value, r.value)
            u.value = ""; p.value = ""; load(); page.update()

    load()
    return ft.View("/users", [
        UIHelper.create_header("Usuarios", leading=ft.IconButton("arrow_back", icon_color="white", on_click=lambda _: page.go("/admin"))),
        ft.Container(content=ft.Column([
            UIHelper.create_card(ft.Column([ft.Row([u, p, r]), ft.ElevatedButton("Crear", on_click=add, bgcolor="green", color="white", width=float("inf"))])),
            ft.Text("Lista", weight="bold"), col
        ], expand=True), padding=20, bgcolor=THEME["bg"], expand=True)
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
        "/admin": view_admin,
        "/ciclos": view_ciclos,
        "/users": view_users
    }

    def route_change(route):
        page.views.clear()
        if page.route != "/" and not page.session.get("user"):
            page.route = "/"
        
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

# ==============================================================================
# 🧨 ZONA DE LIMPIEZA V5 (REQUERIDO PARA ACTIVAR LOS NUEVOS CAMBIOS)
# ==============================================================================
try:
    print("--- 🧹 LIMPIEZA DB PARA V5 (ESTRUCTURA NUEVA) ---")
    conn_fix = db.get_connection()
    if conn_fix:
        with conn_fix.cursor() as cur:
            # Borramos para recrear porque cambio la tabla Requisitos
            cur.execute("DROP TABLE IF EXISTS Asistencia CASCADE")
            cur.execute("DROP TABLE IF EXISTS Alumnos CASCADE") 
            cur.execute("DROP TABLE IF EXISTS Cursos CASCADE")
            cur.execute("DROP TABLE IF EXISTS Ciclos CASCADE")
            cur.execute("DROP TABLE IF EXISTS Usuario_Cursos CASCADE") 
            cur.execute("DROP TABLE IF EXISTS Requisitos CASCADE")     
            cur.execute("DROP TABLE IF EXISTS Documentacion_Alumno CASCADE")
            conn_fix.commit()
        conn_fix.close()
        print("✅ TABLAS BORRADAS.")
        print("🔨 RE-CREANDO ESTRUCTURA V5...")
        db._init_db_structure()
except Exception as e:
    print(f"❌ ERROR EN LIMPIEZA: {e}")
