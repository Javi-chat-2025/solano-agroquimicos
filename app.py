import os
import io
import json
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from fpdf import FPDF
import extra_streamlit_components as stx  # 👈 1. LIBRERÍA DE COOKIES AGREGADA

# Cargar variables de entorno desde .env
load_dotenv()

st.set_page_config(
    page_title="Solano Agroquímicos - Recetas y Citas", 
    page_icon="🥑", 
    layout="wide"
)

# ==========================================
# CARGAR ESTILOS EXTERNOS (style.css)
# ==========================================
def cargar_css(nombre_archivo="style.css"):
    if os.path.exists(nombre_archivo):
        with open(nombre_archivo, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

cargar_css("style.css")

# Función auxiliar para obtener la fecha del día en formato DD/MM/YYYY
def obtener_fecha_actual():
    ahora = datetime.now()
    return ahora.strftime("%d/%m/%Y")

# Función auxiliar para formatear de forma limpia el ID de Cliente
def formatear_id_cliente(id_raw):
    if id_raw is None:
        return "N/A"
    if isinstance(id_raw, int) or (isinstance(id_raw, str) and id_raw.isdigit()):
        return f"CLI-{int(id_raw):04d}"
    return str(id_raw)

# Función para generar archivo .ics para el Calendario del iPhone / Android
def generar_evento_ics(titulo, descripcion, ubicacion, fecha_inicio_dt, duracion_horas=1):
    fecha_fin_dt = fecha_inicio_dt + timedelta(hours=duracion_horas)
    
    fmt = "%Y%m%dT%H%M%S"
    inicio_str = fecha_inicio_dt.strftime(fmt)
    fin_str = fecha_fin_dt.strftime(fmt)
    
    desc_clean = str(descripcion or "").replace("\n", " - ")
    
    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Solano Agroquimicos//Visitas Tecnicas//ES
CALSCALE:GREGORIAN
METHOD:PUBLISH
BEGIN:VEVENT
SUMMARY:{titulo}
DESCRIPTION:{desc_clean}
LOCATION:{ubicacion}
DTSTART:{inicio_str}
DTEND:{fin_str}
STATUS:CONFIRMED
END:VEVENT
END:VCALENDAR"""
    
    return ics_content.encode("utf-8")

@st.cache_resource
def init_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    return create_client(url, key)

supabase = init_supabase()

def obtener_siguiente_num_factura():
    try:
        res = supabase.table("recetas").select("num_factura").order("id_receta", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            ultimo_num = res.data[0].get("num_factura")
            if ultimo_num and str(ultimo_num).strip().isdigit():
                siguiente = int(str(ultimo_num).strip()) + 1
                return f"{siguiente:07d}"
        return "0000001"
    except Exception:
        return "0000001"

# ==========================================
# CONTROL DE SESIÓN Y AUTENTICACIÓN (PERSISTENTE POR URL)
# ==========================================
if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = None

# Intentar auto-login al cargar si existe la variable 'session' en la URL (al presionar F5)
if not st.session_state.autenticado and "session" in st.query_params:
    correo_guardado = st.query_params.get("session")
    if correo_guardado:
        try:
            res = supabase.table("usuarios").select("*").eq("correo", correo_guardado).execute()
            if res.data and len(res.data) > 0:
                st.session_state.autenticado = True
                st.session_state.usuario = res.data[0]
            else:
                st.query_params.clear()
        except Exception:
            st.query_params.clear()

def pantalla_login():
    col1, col2, col3 = st.columns([1, 1.2, 1])
    with col2:
        st.write("")
        st.write("")
        with st.container(border=True):
            if os.path.exists("logo.png"):
                st.image("logo.png", width=120)
            st.title("🔐 Iniciar Sesión")
            st.caption("Solano Agroquímicos — Sistema de Gestión")
            
            with st.form("form_login"):
                correo_input = st.text_input("Correo Electrónico", placeholder="Introduce el correo")
                pass_input = st.text_input("Contraseña", type="password", placeholder="••••••••")
                btn_ingresar = st.form_submit_button("Ingresar al Sistema", type="primary", use_container_width=True)
                
                if btn_ingresar:
                    if not correo_input or not pass_input:
                        st.error("Ingresa correo y contraseña.")
                    else:
                        try:
                            res = supabase.table("usuarios").select("*").eq("correo", correo_input).eq("contrasena", pass_input).execute()
                            if res.data and len(res.data) > 0:
                                user_data = res.data[0]
                                st.session_state.autenticado = True
                                st.session_state.usuario = user_data
                                
                                # Guardar el correo en la URL del navegador
                                st.query_params["session"] = str(user_data.get("correo"))
                                st.success("¡Acceso concedido!")
                                st.rerun()
                            else:
                                st.error("Credenciales incorrectas. Verifica tus datos.")
                        except Exception as e:
                            st.error(f"Error de conexión: {e}")

if not st.session_state.autenticado:
    pantalla_login()
    st.stop()

# Variables de navegación y estado de sesión de la app
if "cliente_sel" not in st.session_state:
    st.session_state.cliente_sel = None
if "huerta_sel" not in st.session_state:
    st.session_state.huerta_sel = None
if "productos_receta_temp" not in st.session_state:
    st.session_state.productos_receta_temp = []
if "producto_a_editar" not in st.session_state:
    st.session_state.producto_a_editar = None
if "cliente_a_editar" not in st.session_state:
    st.session_state.cliente_a_editar = None
if "huerta_a_editar" not in st.session_state:
    st.session_state.huerta_a_editar = None

# ==========================================
# DIÁLOGOS DE CONFIRMACIÓN DE ELIMINACIÓN
# ==========================================
@st.dialog("⚠️ Confirmar Eliminación de Cliente")
def confirmar_eliminar_cliente(cliente):
    st.write(f"¿Estás seguro de que deseas eliminar al cliente **{cliente.get('nombre')}** (`{formatear_id_cliente(cliente.get('id_cliente'))}`)?")
    st.warning("⚠️ Esta acción es permanente y no se podrá deshacer.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Sí, eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("clientes").delete().eq("id_cliente", cliente["id_cliente"]).execute()
                st.success("Cliente eliminado con éxito.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar el cliente porque tiene huertas vinculadas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()

@st.dialog("⚠️ Confirmar Eliminación de Huerta")
def confirmar_eliminar_huerta(huerta):
    st.write(f"¿Estás seguro de que deseas eliminar la huerta **{huerta.get('nombre_huerta')}**?")
    st.warning("⚠️ Esta acción es permanente y no se podrá deshacer.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Sí, eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("huertas").delete().eq("id_huerta", huerta["id_huerta"]).execute()
                st.success("Huerta eliminada con éxito.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar la huerta porque tiene recetas asociadas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()

@st.dialog("⚠️ Confirmar Eliminación de Producto")
def confirmar_eliminar_producto(producto):
    st.write(f"¿Estás seguro de que deseas eliminar el producto **[{producto.get('id_producto')}] {producto.get('nombre_comercial')}**?")
    st.warning("⚠️ Esta acción es permanente y no se podrá deshacer.")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Sí, eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("productos").delete().eq("id_producto", producto["id_producto"]).execute()
                st.success("Producto eliminado del catálogo.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar: este producto forma parte de recetas generadas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()

# ==========================================
# ENCABEZADO DE LA APP WEB Y SALIDA
# ==========================================
col_logo_web, col_titulo_web, col_user = st.columns([1, 4, 1.5])

with col_logo_web:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=110)
    else:
        st.title("🥑")

with col_titulo_web:
    st.title("SOLANO AGROQUÍMICOS")
    st.caption("Nutrición Especializada — Sistema de Gestión de Huertas y Recetas Agrícolas")

with col_user:
    st.write(f"👤 **{st.session_state.usuario.get('nombre', 'Usuario')}**")
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.query_params.clear()
        st.session_state.autenticado = False
        st.session_state.usuario = None
        st.rerun()

st.divider()

# Navegación por pestañas
tab_perfiles, tab_nueva_receta, tab_visitas, tab_registro, tab_productos = st.tabs([
    "📂 Perfiles y Huertas",
    "📜 Emitir Receta",
    "📅 Agendar Visitas",
    "👥 Gestionar Clientes y Huertas",
    "🧪 Catálogo de Productos"
])

# ==========================================
# GENERADOR DE PDF CON TABLA MULTILÍNEA DINÁMICA
# ==========================================
def generar_pdf_estilo_solano(
    empresa="SOLANO AGROQUÍMICOS",
    subtitulo="NUTRICIÓN ESPECIALIZADA",
    fecha=None,
    num_factura="0000001",
    id_cliente="CLI-0001",
    cliente_nombre="Cliente General",
    huerta_nombre="Huerta General",
    huerta_ubicacion="Apatzingán, Michoacán",
    objetivo="Aplicación agrícola",
    volumen_tanque="2000 litros",
    productos_detalle=[],
    asesor_nombre="Q.F.B. Jose Luis Infante Magaña",
    asesor_ced="Ced: 10649771",
    asesor_rfc="RFC: IAML9204182U2",
    logo_path="logo.png"
):
    if not fecha:
        fecha = obtener_fecha_actual()
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    def dividir_texto_en_lineas(texto, max_w):
        txt = str(texto or "").strip()
        if not txt:
            return [""]
        txt = txt.replace("/", " / ").replace("-", "- ")
        words = txt.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = f"{current_line} {word}".strip() if current_line else word
            if pdf.get_string_width(test_line) <= (max_w - 2):
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                    current_line = word
                else:
                    sub_word = ""
                    for char in word:
                        if pdf.get_string_width(sub_word + char) <= (max_w - 2):
                            sub_word += char
                        else:
                            lines.append(sub_word)
                            sub_word = char
                    current_line = sub_word
        if current_line:
            lines.append(current_line)
        return lines

    C_PURPLE = (140, 30, 130)
    C_BLUE = (0, 150, 214)
    C_GREEN = (46, 160, 67)
    C_DARK_GREEN = (35, 130, 55)
    C_YELLOW = (250, 235, 70)
    C_DARK = (40, 40, 40)
    C_WHITE = (255, 255, 255)
    C_GRAY = (120, 120, 120)
    
    # LOGO
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=28)
    
    # TÍTULO PRINCIPAL
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(*C_DARK)
    pdf.cell(0, 8, "RECETA DE APLICACIÓN", ln=True, align="C")
    
    pdf.set_draw_color(210, 210, 210)
    pdf.line(10, 36, 200, 36)
    
    y_start = 24
    x_empresa = 42 if os.path.exists(logo_path) else 10
    
    # ENCABEZADO Y FOLIO
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*C_GRAY)
    pdf.text(x_empresa, y_start + 3, empresa)
    pdf.set_font("Helvetica", "", 8)
    pdf.text(x_empresa, y_start + 7, subtitulo)
    
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_DARK)
    pdf.text(138, y_start + 1, f"FECHA:   {fecha}")
    pdf.text(138, y_start + 5, f"N.° FACTURA:   {num_factura}")
    pdf.text(138, y_start + 9, f"ID. CLIENTE:   {id_cliente}")
    
    pdf.set_y(40)
    
    # DATOS CLIENTE Y HUERTA
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*C_GRAY)
    pdf.cell(0, 5, "RECETAR A", ln=True)
    
    pdf.set_fill_color(*C_BLUE)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.cell(140, 5.5, f"  Cliente: {cliente_nombre}", fill=True, ln=True)
    
    pdf.set_fill_color(*C_GREEN)
    pdf.cell(140, 5.5, f"  Nombre de la Huerta: {huerta_nombre}", fill=True, ln=True)
    
    if huerta_ubicacion:
        pdf.set_fill_color(*C_DARK_GREEN)
        pdf.cell(140, 5.5, f"  Ubicación: {huerta_ubicacion}", fill=True, ln=True)
        
    pdf.ln(3)
    
    # OBJETIVO DE APLICACIÓN
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*C_DARK)
    pdf.cell(0, 5, "OBJETIVO DE LA APLICACIÓN", ln=True, align="C")
    
    pdf.set_fill_color(*C_YELLOW)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 6, f"{objetivo}", fill=True, ln=True, align="C")
    pdf.ln(3)
    
    # TABLA DE PRODUCTOS
    w_id = 14
    w_com = 32
    w_tec = 38
    w_conc = 26
    w_tipo = 26
    w_func = 28
    w_cant = 26
    
    pdf.set_fill_color(*C_PURPLE)
    pdf.set_text_color(*C_WHITE)
    pdf.set_font("Helvetica", "B", 7.5)
    
    pdf.cell(w_id, 7, "Id Prod", fill=True, align="C")
    pdf.cell(w_com, 7, "Nombre Comercial", fill=True, align="C")
    pdf.cell(w_tec, 7, "Nombre Técnico", fill=True, align="C")
    pdf.cell(w_conc, 7, "Concentración", fill=True, align="C")
    pdf.cell(w_tipo, 7, "Formulación", fill=True, align="C")
    pdf.cell(w_func, 7, "Uso", fill=True, align="C")
    pdf.cell(w_cant, 7, f"Cant. / {volumen_tanque}", fill=True, align="C", ln=True)
    
    # CONTENIDO MULTILÍNEA DE LA TABLA
    pdf.set_font("Helvetica", "", 7)
    pdf.set_draw_color(220, 220, 220)
    
    for prod in productos_detalle:
        pdf.set_text_color(*C_DARK)
        
        id_lines = dividir_texto_en_lineas(prod.get("id_producto", ""), w_id)
        com_lines = dividir_texto_en_lineas(prod.get("nombre_comercial", ""), w_com)
        tec_lines = dividir_texto_en_lineas(prod.get("nombre_tecnico", ""), w_tec)
        conc_lines = dividir_texto_en_lineas(prod.get("concentracion", ""), w_conc)
        tipo_lines = dividir_texto_en_lineas(prod.get("formulacion", ""), w_tipo)
        func_lines = dividir_texto_en_lineas(prod.get("uso", ""), w_func)
        cant_lines = dividir_texto_en_lineas(f"{prod.get('dosis', '')} {prod.get('unidad', '')}", w_cant)
        
        col_data = [
            (w_id, id_lines, False),
            (w_com, com_lines, False),
            (w_tec, tec_lines, False),
            (w_conc, conc_lines, False),
            (w_tipo, tipo_lines, False),
            (w_func, func_lines, False),
            (w_cant, cant_lines, True)
        ]
        
        max_num_lines = max([len(lines) for _, lines, _ in col_data])
        line_height = 3.8
        row_h = max(max_num_lines * line_height + 3, 7.0)
        
        if pdf.get_y() + row_h > 270:
            pdf.add_page()
            
        y_pos = pdf.get_y()
        x_pos = 10
        
        for w, lines, is_yellow in col_data:
            if is_yellow:
                pdf.set_fill_color(*C_YELLOW)
                pdf.rect(x_pos, y_pos, w, row_h, style="F")
                
            pdf.set_draw_color(220, 220, 220)
            pdf.line(x_pos, y_pos + row_h, x_pos + w, y_pos + row_h)
            
            content_h = len(lines) * line_height
            y_start_line = y_pos + (row_h - content_h) / 2 + 2.8
            
            for idx_line, line_str in enumerate(lines):
                txt_w = pdf.get_string_width(line_str)
                x_txt = x_pos + (w - txt_w) / 2
                pdf.text(x_txt, y_start_line + (idx_line * line_height), line_str)
                
            x_pos += w
            
        pdf.set_y(y_pos + row_h)
        
    pdf.ln(10)
    
    # DATOS Y FIRMA DEL ASESOR
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(*C_DARK)
    pdf.cell(0, 4.5, asesor_nombre, ln=True, align="C")
    pdf.set_font("Helvetica", "", 7.5)
    pdf.cell(0, 4, asesor_ced, ln=True, align="C")
    pdf.cell(0, 4, asesor_rfc, ln=True, align="C")
    
    return pdf.output()

# ==========================================
# PESTAÑA 1: EXPLORADOR POR PERFILES
# ==========================================
with tab_perfiles:
    if st.session_state.cliente_sel is None:
        st.subheader("👥 Perfiles de Clientes")
        
        busqueda_cliente = st.text_input(
            "🔍 Buscar cliente", 
            placeholder="Escribe un nombre, teléfono o correo para filtrar..."
        )
        
        res_clientes = supabase.table("clientes").select("*").execute()
        clientes = res_clientes.data if res_clientes.data else []
        
        if busqueda_cliente:
            term = busqueda_cliente.lower()
            clientes = [
                c for c in clientes 
                if term in str(c.get("nombre", "")).lower() 
                or term in str(c.get("telefono", "")).lower() 
                or term in str(c.get("correo", "")).lower()
            ]
        
        if not clientes:
            st.info("No se encontraron clientes registrados o que coincidan con la búsqueda.")
        else:
            st.write("")
            cols = st.columns(3)
            for idx, c in enumerate(clientes):
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.markdown(f"### 👤 {c['nombre']}")
                        st.caption(f"🆔 ID: `{formatear_id_cliente(c.get('id_cliente'))}`")
                        st.write(f"📞 **Tel:** {c.get('telefono') or 'Sin registro'}")
                        st.write(f"✉️ **Correo:** {c.get('correo') or 'Sin registro'}")
                        st.write("")
                        if st.button("Ver Huertas 🌳", key=f"btn_cli_{c['id_cliente']}", type="primary"):
                            st.session_state.cliente_sel = c
                            st.session_state.huerta_sel = None
                            st.rerun()

    elif st.session_state.cliente_sel is not None and st.session_state.huerta_sel is None:
        cliente = st.session_state.cliente_sel
        
        col_back, col_info = st.columns([1, 4])
        with col_back:
            if st.button("⬅️ Volver"):
                st.session_state.cliente_sel = None
                st.rerun()
        with col_info:
            st.subheader(f"🌳 Huertas de: {cliente['nombre']}")
            st.caption(f"ID Cliente: `{formatear_id_cliente(cliente.get('id_cliente'))}`")

        st.write("---")
        
        res_huertas = supabase.table("huertas").select("*").eq("id_cliente", cliente["id_cliente"]).execute()
        huertas = res_huertas.data if res_huertas.data else []
        
        if not huertas:
            st.info(f"El cliente '{cliente['nombre']}' no tiene huertas registradas.")
        else:
            cols = st.columns(3)
            for idx, h in enumerate(huertas):
                with cols[idx % 3]:
                    with st.container(border=True):
                        st.markdown(f"### 🥑 {h['nombre_huerta']}")
                        st.write(f"📍 **Ubicación:** {h.get('ubicacion') or 'N/A'}")
                        st.write(f"📏 **Superficie:** {h.get('hectareas') or '0'} ha")
                        st.write("")
                        if st.button("Ver Recetas 📜", key=f"btn_huer_{h['id_huerta']}", type="primary"):
                            st.session_state.huerta_sel = h
                            st.rerun()

    elif st.session_state.huerta_sel is not None:
        cliente = st.session_state.cliente_sel
        huerta = st.session_state.huerta_sel
        
        col_back, col_info = st.columns([1, 4])
        with col_back:
            if st.button("⬅️ Volver"):
                st.session_state.huerta_sel = None
                st.rerun()
        with col_info:
            st.subheader("📜 Recetas Emitidas")
            st.write(f"👤 **Cliente:** {cliente['nombre']} (ID: `{formatear_id_cliente(cliente.get('id_cliente'))}`) | 🌳 **Huerta:** {huerta['nombre_huerta']} ({huerta.get('ubicacion') or 'N/A'})")

        st.write("---")
        
        res_recetas = supabase.table("recetas").select(
            "id_receta, fecha, num_factura, objetivo, volumen_tanque, "
            "receta_detalles(dosis, unidad, productos(id_producto, nombre_comercial, nombre_tecnico, concentracion, formulacion, uso))"
        ).eq("id_huerta", huerta["id_huerta"]).order("id_receta", desc=True).execute()
        
        recetas = res_recetas.data if res_recetas.data else []
        
        if not recetas:
            st.info(f"No hay recetas emitidas para la huerta '{huerta['nombre_huerta']}'.")
        else:
            for r in recetas:
                with st.container(border=True):
                    col_detalles, col_pdf = st.columns([3, 1])
                    
                    detalles = r.get("receta_detalles", [])
                    prods_pdf = []
                    
                    with col_detalles:
                        st.markdown(f"### 📄 Receta #{r['id_receta']} — Fecha: `{r.get('fecha', 'N/A')}`")
                        st.write(f"**N.° Factura:** `{r.get('num_factura', 'N/A')}` | **Volumen:** {r.get('volumen_tanque', 'N/A')}")
                        st.write(f"🎯 **Objetivo:** {r.get('objetivo', 'N/A')}")
                        
                        prod_resumen = []
                        for d in detalles:
                            p = d.get("productos") or {}
                            prod_obj = {
                                "id_producto": p.get("id_producto", ""),
                                "nombre_comercial": p.get("nombre_comercial", ""),
                                "nombre_tecnico": p.get("nombre_tecnico", ""),
                                "concentracion": p.get("concentracion", ""),
                                "formulacion": p.get("formulacion", ""),
                                "uso": p.get("uso", ""),
                                "dosis": d.get("dosis", ""),
                                "unidad": d.get("unidad", "")
                            }
                            prods_pdf.append(prod_obj)
                            prod_resumen.append(f"• **[{p.get('id_producto', 'ID')}] {p.get('nombre_comercial', '')}**: {d.get('dosis')} {d.get('unidad')}")
                        
                        st.write("**Productos recomendados:**")
                        st.markdown("\n".join(prod_resumen) if prod_resumen else "Sin productos")
                        
                    with col_pdf:
                        st.write("")
                        st.write("")
                        id_cli_str = formatear_id_cliente(cliente.get("id_cliente"))
                        pdf_bytes = generar_pdf_estilo_solano(
                            empresa="SOLANO AGROQUÍMICOS",
                            subtitulo="NUTRICIÓN ESPECIALIZADA",
                            fecha=r.get("fecha") or obtener_fecha_actual(),
                            num_factura=r.get("num_factura", ""),
                            id_cliente=id_cli_str,
                            cliente_nombre=cliente.get("nombre", "Cliente General"),
                            huerta_nombre=huerta.get("nombre_huerta", "Huerta General"),
                            huerta_ubicacion=huerta.get("ubicacion", "N/A"),
                            objetivo=r.get("objetivo", ""),
                            volumen_tanque=r.get("volumen_tanque", ""),
                            productos_detalle=prods_pdf,
                            logo_path="logo.png"
                        )
                        
                        st.download_button(
                            label="⬇️ Descargar PDF",
                            data=bytes(pdf_bytes),
                            file_name=f"Receta_{r['id_receta']}_{huerta['nombre_huerta']}.pdf",
                            mime="application/pdf",
                            key=f"dl_pdf_{r['id_receta']}",
                            type="primary"
                        )

# ==========================================
# PESTAÑA 2: EMITIR NUEVA RECETA
# ==========================================
with tab_nueva_receta:
    st.subheader("Emitir Nueva Receta")
    
    huertas_data = supabase.table("huertas").select("id_huerta, nombre_huerta, ubicacion, id_cliente, clientes(id_cliente, nombre)").execute().data
    productos_data = supabase.table("productos").select("*").execute().data
    
    if not huertas_data or not productos_data:
        st.warning("⚠️ Asegúrate de tener al menos una huerta y un producto registrados.")
    else:
        dict_huertas = {f"{h['nombre_huerta']} ({h['clientes']['nombre'] if h.get('clientes') else 'Sin cliente'})": h for h in huertas_data}
        dict_prods = {f"[{p['id_producto']}] {p['nombre_comercial']}": p for p in productos_data}
        
        col_c1, col_c2 = st.columns(2)
        
        with col_c1:
            st.markdown("### 1. Datos Generales")
            huerta_sel_key = st.selectbox("Seleccionar Huerta *", list(dict_huertas.keys()))
            huerta_info = dict_huertas[huerta_sel_key]
            
            cliente_info = huerta_info.get("clientes") or {}
            cliente_nombre_val = cliente_info.get("nombre", "Cliente General")
            id_cliente_raw = huerta_info.get("id_cliente") or cliente_info.get("id_cliente")
            id_cliente_formateado = formatear_id_cliente(id_cliente_raw)
            
            st.info(
                f"👤 **Cliente:** {cliente_nombre_val} (ID: `{id_cliente_formateado}`)\n\n"
                f"🌳 **Huerta:** {huerta_info.get('nombre_huerta', 'N/A')}\n\n"
                f"📍 **Ubicación:** {huerta_info.get('ubicacion') or 'Sin ubicación'}"
            )
            
            fecha_receta = st.text_input("Fecha (Día/Mes/Año)", value=obtener_fecha_actual(), disabled=True)
            num_factura_autoincrementado = obtener_siguiente_num_factura()
            num_factura = st.text_input("N.° Factura", value=num_factura_autoincrementado, disabled=True)
            volumen_tanque = st.text_input("Volumen del Tanque", value="2000 litros")
            objetivo_aplicacion = st.text_input("Objetivo de la Aplicación", value="Aplicación para defoliadores + control de hongos")
            
        with col_c2:
            st.markdown("### 2. Agregar Productos")
            prod_sel_nombre = st.selectbox("Seleccionar Producto *", list(dict_prods.keys()))
            prod_info = dict_prods[prod_sel_nombre]
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                dosis_val = st.text_input("Cantidad / Dosis", value="1")
            with col_d2:
                unidad_val = st.selectbox("Unidad", ["lt", "kg", "g", "ml", "L / Ha", "Kg / Ha"])
                
            if st.button("➕ Añadir Producto"):
                st.session_state.productos_receta_temp.append({
                    "id_producto": prod_info["id_producto"],
                    "nombre_comercial": prod_info["nombre_comercial"],
                    "nombre_tecnico": prod_info.get("nombre_tecnico", ""),
                    "concentracion": prod_info.get("concentracion", ""),
                    "formulacion": prod_info.get("formulacion", ""),
                    "uso": prod_info.get("uso", ""),
                    "dosis": dosis_val,
                    "unidad": unidad_val
                })
                st.success(f"Añadido: [{prod_info['id_producto']}] {prod_info['nombre_comercial']}")
                st.rerun()

        # TABLA TEMPORAL
        if st.session_state.productos_receta_temp:
            st.write("---")
            st.markdown("### 📋 Resumen de Productos de la Receta")
            
            col_h_id, col_h_com, col_h_tec, col_h_conc, col_h_tipo, col_h_func, col_h_cant, col_h_del = st.columns(
                [1.0, 2.0, 2.0, 1.5, 1.3, 1.8, 1.8, 0.7]
            )
            
            with col_h_id: st.markdown("**ID**")
            with col_h_com: st.markdown("**Nombre Comercial**")
            with col_h_tec: st.markdown("**Nombre Técnico**")
            with col_h_conc: st.markdown("**Concentración**")
            with col_h_tipo: st.markdown("**Formulación**")
            with col_h_func: st.markdown("**Uso**")
            with col_h_cant: st.markdown(f"**Cant / {volumen_tanque}**")
            with col_h_del: st.markdown("**Acción**")
            
            st.divider()

            for idx, item in enumerate(st.session_state.productos_receta_temp):
                c_id, c_com, c_tec, c_conc, c_tipo, c_func, c_cant, c_del = st.columns(
                    [1.0, 2.0, 2.0, 1.5, 1.3, 1.8, 1.8, 0.7]
                )
                
                with c_id: st.write(f"`{item['id_producto']}`")
                with c_com: st.write(item["nombre_comercial"])
                with c_tec: st.write(item.get("nombre_tecnico") or "-")
                with c_conc: st.write(item.get("concentracion") or "-")
                with c_tipo: st.write(item.get("formulacion") or "-")
                with c_func: st.write(item.get("uso") or "-")
                with c_cant: st.write(f"{item['dosis']} {item['unidad']}")
                with c_del:
                    if st.button("❌", key=f"del_prod_receta_{idx}"):
                        st.session_state.productos_receta_temp.pop(idx)
                        st.rerun()

            st.write("")
            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("🗑️ Limpiar Todo"):
                    st.session_state.productos_receta_temp = []
                    st.rerun()
                    
            with col_b2:
                if st.button("💾 Guardar Receta y Generar PDF", type="primary"):
                    try:
                        res_receta = supabase.table("recetas").insert({
                            "id_huerta": huerta_info["id_huerta"],
                            "fecha": fecha_receta,
                            "num_factura": num_factura,
                            "objetivo": objetivo_aplicacion,
                            "volumen_tanque": volumen_tanque
                        }).execute()
                        
                        if res_receta.data:
                            id_receta_creada = res_receta.data[0]["id_receta"]
                            
                            detalles_insert = [{
                                "id_receta": id_receta_creada,
                                "id_producto": item["id_producto"],
                                "dosis": item["dosis"],
                                "unidad": item["unidad"]
                            } for item in st.session_state.productos_receta_temp]
                            
                            supabase.table("receta_detalles").insert(detalles_insert).execute()
                            
                            pdf_bytes = generar_pdf_estilo_solano(
                                empresa="SOLANO AGROQUÍMICOS",
                                subtitulo="NUTRICIÓN ESPECIALIZADA",
                                fecha=fecha_receta,
                                num_factura=num_factura,
                                id_cliente=id_cliente_formateado,
                                cliente_nombre=cliente_nombre_val,
                                huerta_nombre=huerta_info["nombre_huerta"],
                                huerta_ubicacion=huerta_info.get("ubicacion", "N/A"),
                                objetivo=objetivo_aplicacion,
                                volumen_tanque=volumen_tanque,
                                productos_detalle=st.session_state.productos_receta_temp,
                                logo_path="logo.png"
                            )
                            
                            st.session_state.productos_receta_temp = []
                            st.success(f"¡Receta #{id_receta_creada} guardada con éxito (Factura: #{num_factura})!")
                            
                            st.download_button(
                                label="📄 Descargar PDF",
                                data=bytes(pdf_bytes),
                                file_name=f"Receta_{id_receta_creada}_{huerta_info['nombre_huerta']}.pdf",
                                mime="application/pdf"
                            )
                    except Exception as e:
                        st.error(f"Error al guardar la receta: {e}")

# ==========================================
# PESTAÑA 3: AGENDAR VISITAS (VISTA LIMPIA CON VALIDACIÓN)
# ==========================================
with tab_visitas:
    st.subheader("📅 Gestión de Visitas Técnicas")
    st.caption("Agenda citas para prospección o seguimiento en campo y sincronízalas con el calendario de tu celular.")

    col_form_v, col_hist_v = st.columns([1.3, 2.7])

    with col_form_v:
        st.markdown("### ➕ Agendar Nueva Visita")
        
        try:
            res_huertas_v = supabase.table("huertas").select("id_huerta, nombre_huerta, ubicacion, id_cliente, clientes(id_cliente, nombre)").execute()
            huertas_v_data = res_huertas_v.data if res_huertas_v.data else []
        except Exception as e_huer:
            st.error(f"Error al cargar huertas: {e_huer}")
            huertas_v_data = []

        if not huertas_v_data:
            st.warning("⚠️ Debes registrar al menos un cliente y una huerta antes de agendar una visita.")
        else:
            dict_huertas_visita = {
                f"👤 {h['clientes']['nombre'] if h.get('clientes') else 'Sin cliente'} — 🌳 {h['nombre_huerta']}": h 
                for h in huertas_v_data
            }

            with st.form("form_agendar_visita"):
                huerta_sel_v_key = st.selectbox("Seleccionar Cliente / Huerta *", list(dict_huertas_visita.keys()))
                huerta_v_info = dict_huertas_visita[huerta_sel_v_key]

                col_f1, col_f2 = st.columns(2)
                with col_f1:
                    fecha_v = st.date_input("Fecha de la visita *", format="DD/MM/YYYY")
                with col_f2:
                    hora_v = st.time_input("Hora aproximada *")

                notas_v = st.text_area("Objetivo / Notas de la visita", placeholder="Ej. Revisión de plagas, foliarización o aplicación de nutrientes...")

                btn_guardar_visita = st.form_submit_button("💾 Agendar Visita", type="primary", use_container_width=True)

                if btn_guardar_visita:
                    fecha_hora_dt = datetime.combine(fecha_v, hora_v)

                    try:
                        res_ins = supabase.table("visitas").insert({
                            "id_huerta": huerta_v_info["id_huerta"],
                            "fecha_visita": fecha_hora_dt.isoformat(),
                            "notas": notas_v
                        }).execute()

                        st.success("¡Visita agendada correctamente!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar la visita en Supabase: {e}")

    with col_hist_v:
        st.markdown("### 📋 Citas Agendadas")

        try:
            res_visitas = supabase.table("visitas").select("*, huertas(nombre_huerta, ubicacion, clientes(nombre, telefono))").order("fecha_visita", desc=False).execute()
            list_visitas = res_visitas.data if res_visitas.data else []
        except Exception as e_vis:
            st.error(f"Error al consultar las visitas de Supabase: {e_vis}")
            list_visitas = []

        if not list_visitas:
            st.info("No hay visitas programadas por el momento.")
        else:
            for v in list_visitas:
                h_info = v.get("huertas") or {}
                c_info = h_info.get("clientes") or {}
                
                fecha_obj = datetime.fromisoformat(v["fecha_visita"].replace("Z", ""))
                fecha_formateada = fecha_obj.strftime("%d/%m/%Y a las %I:%M %p")
                
                nombre_cliente = c_info.get("nombre", "Cliente General")
                nombre_huerta = h_info.get("nombre_huerta", "Huerta General")
                ubicacion_huerta = h_info.get("ubicacion") or "Apatzingán, Michoacán"
                notas_visita = v.get("notas") or "Visita técnica de seguimiento"

                with st.container(border=True):
                    col_v_det, col_v_btn = st.columns([2.5, 1.5])

                    with col_v_det:
                        st.markdown(f"#### 🌳 {nombre_huerta}")
                        st.write(f"👤 **Cliente:** {nombre_cliente}")
                        st.write(f"🗓️ **Fecha:** `{fecha_formateada}`")
                        st.write(f"📍 **Ubicación:** {ubicacion_huerta}")
                        if notas_visita:
                            st.caption(f"📝 **Notas:** {notas_visita}")

                    with col_v_btn:
                        st.write("")
                        titulo_evento = f"Visita Técnica: {nombre_huerta} ({nombre_cliente})"
                        desc_evento = f"Cliente: {nombre_cliente}\nHuerta: {nombre_huerta}\nNotas: {notas_visita}"
                        
                        ics_bytes = generar_evento_ics(
                            titulo=titulo_evento,
                            descripcion=desc_evento,
                            ubicacion=ubicacion_huerta,
                            fecha_inicio_dt=fecha_obj,
                            duracion_horas=1
                        )

                        st.download_button(
                            label="📲 Agregar al iPhone",
                            data=ics_bytes,
                            file_name=f"Visita_{nombre_huerta}_{fecha_obj.strftime('%d%m%Y')}.ics",
                            mime="text/calendar",
                            key=f"dl_ics_{v['id_visita']}",
                            type="primary",
                            use_container_width=True
                        )

# ==========================================
# PESTAÑA 4: GESTIÓN DE CLIENTES Y HUERTAS (CRUD)
# ==========================================
with tab_registro:
    st.subheader("👥 Gestión e Historial de Clientes y Huertas")
    
    sub_tab_cli, sub_tab_hue = st.tabs(["👤 Clientes", "🌳 Huertas"])
    
    # ------------------------------------------
    # SUB-PESTAÑA 1: GESTIÓN DE CLIENTES
    # ------------------------------------------
    with sub_tab_cli:
        col_f_cli, col_t_cli = st.columns([1.2, 2.8])
        
        with col_f_cli:
            cli_edit = st.session_state.cliente_a_editar
            
            if cli_edit:
                st.markdown("### ✏️ Editar Cliente")
                with st.form("form_edit_cliente"):
                    edit_nombre = st.text_input("Nombre completo *", value=cli_edit.get("nombre", ""))
                    edit_telefono = st.text_input("Teléfono", value=cli_edit.get("telefono", "") or "")
                    edit_correo = st.text_input("Correo electrónico *", value=cli_edit.get("correo", "") or "")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        guardar_cli_edit = st.form_submit_button("💾 Actualizar", type="primary")
                    with c2:
                        cancel_cli_edit = st.form_submit_button("❌ Cancelar")
                    
                    if guardar_cli_edit:
                        if edit_nombre and edit_correo:
                            supabase.table("clientes").update({
                                "nombre": edit_nombre,
                                "telefono": edit_telefono,
                                "correo": edit_correo
                            }).eq("id_cliente", cli_edit["id_cliente"]).execute()
                            
                            st.session_state.cliente_a_editar = None
                            st.success("¡Cliente actualizado!")
                            st.rerun()
                        else:
                            st.error("Campos obligatorios (*).")
                            
                    if cancel_cli_edit:
                        st.session_state.cliente_a_editar = None
                        st.rerun()
            else:
                st.markdown("### ➕ Registrar Nuevo Cliente")
                with st.form("form_nuevo_cliente"):
                    nuevo_nombre = st.text_input("Nombre completo *")
                    nuevo_telefono = st.text_input("Teléfono")
                    nuevo_correo = st.text_input("Correo electrónico *")
                    
                    guardar_cli = st.form_submit_button("💾 Registrar Cliente", type="primary")
                    
                    if guardar_cli:
                        if nuevo_nombre and nuevo_correo:
                            try:
                                supabase.table("clientes").insert({
                                    "nombre": nuevo_nombre,
                                    "telefono": nuevo_telefono,
                                    "correo": nuevo_correo
                                }).execute()
                                st.success(f"Cliente '{nuevo_nombre}' guardado exitosamente.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al guardar cliente: {e}")
                        else:
                            st.error("Campos obligatorios (*).")

        with col_t_cli:
            st.markdown("### 📋 Clientes Registrados")
            res_cli_all = supabase.table("clientes").select("*").order("id_cliente", desc=True).execute()
            list_cli = res_cli_all.data if res_cli_all.data else []
            
            if not list_cli:
                st.info("No hay clientes en el sistema.")
            else:
                for c in list_cli:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 1, 1])
                        with c1:
                            st.markdown(f"**{c['nombre']}** (`{formatear_id_cliente(c['id_cliente'])}`)")
                            st.caption(f"📞 {c.get('telefono') or 'S/T'} | ✉️ {c.get('correo') or 'S/C'}")
                        with c2:
                            if st.button("✏️ Editar", key=f"edit_cli_{c['id_cliente']}"):
                                st.session_state.cliente_a_editar = c
                                st.rerun()
                        with c3:
                            if st.button("🗑️ Borrar", key=f"del_cli_{c['id_cliente']}"):
                                confirmar_eliminar_cliente(c)

    # ------------------------------------------
    # SUB-PESTAÑA 2: GESTIÓN DE HUERTAS
    # ------------------------------------------
    with sub_tab_hue:
        col_f_hue, col_t_hue = st.columns([1.2, 2.8])
        
        res_cli_select = supabase.table("clientes").select("id_cliente, nombre").execute()
        cli_options = res_cli_select.data if res_cli_select.data else []
        dict_cli_lookup = {f"{c['nombre']} ({formatear_id_cliente(c['id_cliente'])})": c['id_cliente'] for c in cli_options}
        
        with col_f_hue:
            if not cli_options:
                st.warning("Primero debes registrar al menos un cliente.")
            else:
                hue_edit = st.session_state.huerta_a_editar
                
                if hue_edit:
                    st.markdown("### ✏️ Editar Huerta")
                    with st.form("form_edit_huerta"):
                        edit_nombre_h = st.text_input("Nombre de Huerta *", value=hue_edit.get("nombre_huerta", ""))
                        edit_ubicacion_h = st.text_input("Ubicación", value=hue_edit.get("ubicacion", "") or "")
                        edit_ha_h = st.number_input("Hectáreas", value=float(hue_edit.get("hectareas", 0.0) or 0.0))
                        
                        default_cli_idx = 0
                        for idx, (k, v) in enumerate(dict_cli_lookup.items()):
                            if v == hue_edit.get("id_cliente"):
                                default_cli_idx = idx
                                break
                                
                        edit_cli_key = st.selectbox("Cliente *", list(dict_cli_lookup.keys()), index=default_cli_idx)
                        
                        c1, c2 = st.columns(2)
                        with c1:
                            guardar_hue_edit = st.form_submit_button("💾 Actualizar", type="primary")
                        with c2:
                            cancel_hue_edit = st.form_submit_button("❌ Cancelar")
                            
                        if guardar_hue_edit:
                            if edit_nombre_h:
                                supabase.table("huertas").update({
                                    "nombre_huerta": edit_nombre_h,
                                    "ubicacion": edit_ubicacion_h,
                                    "hectareas": edit_ha_h,
                                    "id_cliente": dict_cli_lookup[edit_cli_key]
                                }).eq("id_huerta", hue_edit["id_huerta"]).execute()
                                
                                st.session_state.huerta_a_editar = None
                                st.success("¡Huerta actualizada!")
                                st.rerun()
                            else:
                                st.error("Campos obligatorios (*).")
                                
                        if cancel_hue_edit:
                            st.session_state.huerta_a_editar = None
                            st.rerun()
                else:
                    st.markdown("### ➕ Registrar Nueva Huerta")
                    with st.form("form_nueva_huerta"):
                        nuevo_nombre_h = st.text_input("Nombre de Huerta *")
                        nuevo_ubicacion_h = st.text_input("Ubicación")
                        nuevo_ha_h = st.number_input("Hectáreas", value=0.0, step=0.5)
                        nuevo_cli_key = st.selectbox("Cliente *", list(dict_cli_lookup.keys()))
                        
                        guardar_hue = st.form_submit_button("💾 Registrar Huerta", type="primary")
                        
                        if guardar_hue:
                            if nuevo_nombre_h:
                                try:
                                    supabase.table("huertas").insert({
                                        "nombre_huerta": nuevo_nombre_h,
                                        "ubicacion": nuevo_ubicacion_h,
                                        "hectareas": nuevo_ha_h,
                                        "id_cliente": dict_cli_lookup[nuevo_cli_key]
                                    }).execute()
                                    st.success(f"Huerta '{nuevo_nombre_h}' registrada con éxito.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al guardar huerta: {e}")
                            else:
                                st.error("Campos obligatorios (*).")

        with col_t_hue:
            st.markdown("### 📋 Huertas Registradas")
            res_hue_all = supabase.table("huertas").select("*, clientes(nombre)").order("id_huerta", desc=True).execute()
            list_hue = res_hue_all.data if res_hue_all.data else []
            
            if not list_hue:
                st.info("No hay huertas registradas.")
            else:
                for h in list_hue:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([3, 1, 1])
                        with c1:
                            cli_nombre_h = h['clientes']['nombre'] if h.get('clientes') else 'Sin Cliente'
                            st.markdown(f"**🥑 {h['nombre_huerta']}** — Cliente: `{cli_nombre_h}`")
                            st.caption(f"📍 Ubicación: {h.get('ubicacion') or 'N/A'} | 📏 Superficie: {h.get('hectareas') or 0} ha")
                        with c2:
                            if st.button("✏️ Editar", key=f"edit_hue_{h['id_huerta']}"):
                                st.session_state.huerta_a_editar = h
                                st.rerun()
                        with c3:
                            if st.button("🗑️ Borrar", key=f"del_hue_{h['id_huerta']}"):
                                confirmar_eliminar_huerta(h)

# ==========================================
# PESTAÑA 5: CATÁLOGO DE PRODUCTOS (CRUD)
# ==========================================
with tab_productos:
    st.subheader("🧪 Catálogo de Productos Agroquímicos")
    
    col_f_prod, col_t_prod = st.columns([1.2, 2.8])
    
    with col_f_prod:
        prod_edit = st.session_state.producto_a_editar
        
        if prod_edit:
            st.markdown("### ✏️ Editar Producto")
            with st.form("form_edit_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", value=prod_edit.get("id_producto", ""), disabled=True)
                nombre_com = st.text_input("Nombre Comercial *", value=prod_edit.get("nombre_comercial", ""))
                nombre_tec = st.text_input("Nombre Técnico / Ingrediente Activo", value=prod_edit.get("nombre_tecnico", "") or "")
                concentracion_val = st.text_input("Concentración", value=prod_edit.get("concentracion", "") or "")
                formulacion_val = st.text_input("Formulación", value=prod_edit.get("formulacion", "") or "")
                uso_val = st.text_input("Uso Recomendado", value=prod_edit.get("uso", "") or "")
                
                c1, c2 = st.columns(2)
                with c1:
                    guardar_prod_edit = st.form_submit_button("💾 Actualizar", type="primary")
                with c2:
                    cancel_prod_edit = st.form_submit_button("❌ Cancelar")
                
                if guardar_prod_edit:
                    if nombre_com:
                        supabase.table("productos").update({
                            "nombre_comercial": nombre_com,
                            "nombre_tecnico": nombre_tec,
                            "concentracion": concentracion_val,
                            "formulacion": formulacion_val,
                            "uso": uso_val
                        }).eq("id_producto", prod_edit["id_producto"]).execute()
                        
                        st.session_state.producto_a_editar = None
                        st.success("¡Producto actualizado!")
                        st.rerun()
                    else:
                        st.error("Campos obligatorios (*).")
                        
                if cancel_prod_edit:
                    st.session_state.producto_a_editar = None
                    st.rerun()
        else:
            st.markdown("### ➕ Registrar Nuevo Producto")
            with st.form("form_nuevo_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", placeholder="Ej. PROD-001")
                nombre_com = st.text_input("Nombre Comercial *", placeholder="Ej. Amistar Extra")
                nombre_tec = st.text_input("Nombre Técnico / Ingrediente Activo", placeholder="Ej. Azoxistrobin + Ciproconazol")
                concentracion_val = st.text_input("Concentración", placeholder="Ej. 200 g/L")
                formulacion_val = st.text_input("Formulación", placeholder="Ej. Suspensión Concentrada (SC)")
                uso_val = st.text_input("Uso Recomendado", placeholder="Ej. Fungicida de amplio espectro")
                
                guardar_prod = st.form_submit_button("💾 Registrar Producto", type="primary")
                
                if guardar_prod:
                    if id_prod_val and nombre_com:
                        try:
                            supabase.table("productos").insert({
                                "id_producto": id_prod_val,
                                "nombre_comercial": nombre_com,
                                "nombre_tecnico": nombre_tec,
                                "concentracion": concentracion_val,
                                "formulacion": formulacion_val,
                                "uso": uso_val
                            }).execute()
                            st.success(f"Producto '[{id_prod_val}] {nombre_com}' registrado.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar producto: {e}")
                    else:
                        st.error("Campos obligatorios (*).")

    with col_t_prod:
        st.markdown("### 📋 Productos en Catálogo")
        
        busqueda_prod = st.text_input("🔍 Buscar Producto", placeholder="Buscar por ID, nombre comercial o técnico...")
        
        res_prod_all = supabase.table("productos").select("*").order("id_producto", desc=False).execute()
        list_prods = res_prod_all.data if res_prod_all.data else []
        
        if busqueda_prod:
            term_p = busqueda_prod.lower()
            list_prods = [
                p for p in list_prods
                if term_p in str(p.get("id_producto", "")).lower()
                or term_p in str(p.get("nombre_comercial", "")).lower()
                or term_p in str(p.get("nombre_tecnico", "")).lower()
                or term_p in str(p.get("uso", "")).lower()
            ]
            
        if not list_prods:
            st.info("No hay productos registrados o que coincidan con la búsqueda.")
        else:
            for p in list_prods:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    with c1:
                        st.markdown(f"**[{p['id_producto']}] {p['nombre_comercial']}**")
                        st.caption(f"🧪 Técnico: {p.get('nombre_tecnico') or 'N/A'} | Conc: {p.get('concentracion') or 'N/A'} | Form: {p.get('formulacion') or 'N/A'}")
                        st.write(f"🎯 **Uso:** {p.get('uso') or 'N/A'}")
                    with c2:
                        if st.button("✏️ Editar", key=f"edit_prod_{p['id_producto']}"):
                            st.session_state.producto_a_editar = p
                            st.rerun()
                    with c3:
                        if st.button("🗑️ Borrar", key=f"del_prod_{p['id_producto']}"):
                            confirmar_eliminar_producto(p)
