import os
import io
import json
import hashlib
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from fpdf import FPDF
import extra_streamlit_components as stx
import qrcode

# ==========================================
# CONFIGURACIÓN INICIAL DE LA APLICACIÓN
# ==========================================
load_dotenv()

st.set_page_config(
    page_title="Solano Agroquímicos - Recetas y Citas", 
    page_icon="🥑", 
    layout="wide"
)

URL_BASE_APP = "https://solano-agroquimicos.streamlit.app"

# ==========================================
# CARGAR ESTILOS EXTERNOS (style.css)
# ==========================================
def cargar_css(nombre_archivo="style.css"):
    if os.path.exists(nombre_archivo):
        with open(nombre_archivo, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

cargar_css("style.css")

# ==========================================
# FUNCIONES AUXILIARES GENERALES
# ==========================================
def obtener_fecha_actual():
    return datetime.now().strftime("%d/%m/%Y")

def formatear_id_cliente(id_raw):
    if id_raw is None:
        return "N/A"
    if isinstance(id_raw, int) or (isinstance(id_raw, str) and str(id_raw).isdigit()):
        return f"CLI-{int(id_raw):04d}"
    return str(id_raw)

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
    if not url or not key:
        st.error("⚠️ Faltan las credenciales de Supabase en las variables de entorno.")
        st.stop()
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
# GENERACIÓN DE SELLO DIGITAL Y QR
# ==========================================
def generar_sello_y_qr(num_factura, cliente_nombre, huerta_nombre, fecha, productos_detalle):
    """Genera sello Hash SHA-256 e imagen QR con los datos legibles de la receta."""
    fecha_hora_emision = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    resumen_productos = []
    if productos_detalle:
        for prod in productos_detalle:
            nombre = prod.get("nombre_comercial", "Producto")
            dosis = prod.get("dosis", "")
            unidad = prod.get("unidad", "")
            resumen_productos.append(f"• {nombre}: {dosis} {unidad}")
    
    lista_productos_txt = "\n".join(resumen_productos) if resumen_productos else "Sin productos registrados"

    contenido_qr = (
        f"✅ VERIFICACIÓN EXITOSA\n"
        f"-------------------------------\n"
        f"DOCUMENTO AUTÉNTICO\n"
        f"SOLANO AGROQUÍMICOS\n"
        f"-------------------------------\n"
        f"Folio Receta: {num_factura}\n"
        f"Fecha: {fecha}\n"
        f"Cliente: {cliente_nombre}\n"
        f"Huerta: {huerta_nombre}\n"
        f"-------------------------------\n"
        f"PRODUCTOS APLICADOS:\n"
        f"{lista_productos_txt}"
    )

    cadena_original = f"SOLANO|{num_factura}|{fecha}|{cliente_nombre}|{huerta_nombre}"
    sello_hash = hashlib.sha256(cadena_original.encode('utf-8')).hexdigest()[:16].upper()
    sello_formateado = "-".join([sello_hash[i:i+4] for i in range(0, 16, 4)])
    
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(contenido_qr)
    qr.make(fit=True)
    
    img_qr = qr.make_image(fill_color="black", back_color="white")
    
    qr_bytes = io.BytesIO()
    img_qr.save(qr_bytes, format='PNG')
    qr_bytes.seek(0)
    
    return {
        "sello": sello_formateado,
        "fecha_hora": fecha_hora_emision,
        "qr_bytes": qr_bytes
    }

# ==========================================
# VERIFICACIÓN PÚBLICA DE QR (SIN NECESIDAD DE LOGIN)
# ==========================================
if "validar" in st.query_params:
    codigo_qr = st.query_params["validar"]
    
    st.markdown("<h2 style='text-align: center; color: #1b4332;'>🥑 Solano Agroquímicos</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align: center;'>Verificación de Autenticidad de Receta</h4>", unsafe_allow_html=True)
    st.write("---")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        try:
            res = supabase.table("recetas").select("*, huertas(nombre_huerta, clientes(nombre))").eq("sello_digital", codigo_qr).execute()
            
            if res.data and len(res.data) > 0:
                receta = res.data[0]
                huerta_info = receta.get("huertas") or {}
                cliente_info = huerta_info.get("clientes") or {}
                
                st.success("✅ **DOCUMENTO AUTÉNTICO Y REGISTRADO**")
                
                with st.container(border=True):
                    st.markdown(f"**Folio Receta:** #{receta.get('id_receta', 'N/A')}")
                    st.markdown(f"**Fecha de Emisión:** {receta.get('fecha', 'N/A')}")
                    st.markdown(f"**Cliente:** {cliente_info.get('nombre', 'Cliente General')}")
                    st.markdown(f"**Huerta:** {huerta_info.get('nombre_huerta', 'N/A')}")
                    st.markdown(f"**Objetivo:** {receta.get('objetivo', 'N/A')}")
                    st.markdown(f"**Sello Digital:** `{codigo_qr}`")
                    
                st.caption("Este documento ha sido autenticado por el sistema central de Solano Agroquímicos.")
            else:
                st.error("❌ **DOCUMENTO NO ENCONTRADO O INVÁLIDO**")
                st.warning("El código escaneado no coincide con ninguna receta registrada.")
                
        except Exception as e:
            st.error(f"Error al verificar la receta: {e}")
            
        st.write("")
        if st.button("⬅️ Ir al Inicio de Sesión", use_container_width=True):
            st.query_params.clear()
            st.rerun()
            
    st.stop()

# ==========================================
# CONTROL DE SESIÓN Y PERSISTENCIA POR COOKIES
# ==========================================
cookie_manager = stx.CookieManager(key="solano_cookie_manager")

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = None

try:
    solano_cookie = cookie_manager.get(cookie="solano_session")
    if solano_cookie and not st.session_state.autenticado:
        if isinstance(solano_cookie, str):
            user_data = json.loads(solano_cookie)
        else:
            user_data = solano_cookie
        st.session_state.autenticado = True
        st.session_state.usuario = user_data
except Exception:
    pass

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
                                user_clean = {
                                    "id_usuario": str(user_data.get("id_usuario", "")),
                                    "nombre": str(user_data.get("nombre", "")),
                                    "correo": str(user_data.get("correo", ""))
                                }
                                st.session_state.autenticado = True
                                st.session_state.usuario = user_clean
                                
                                fecha_exp = datetime.now() + timedelta(days=7)
                                cookie_manager.set(
                                    cookie="solano_session", 
                                    val=json.dumps(user_clean), 
                                    expires_at=fecha_exp,
                                    key="set_solano_session"
                                )
                                st.success("¡Acceso concedido!")
                                st.rerun()
                            else:
                                st.error("Credenciales incorrectas. Verifica tus datos.")
                        except Exception as e:
                            st.error(f"Error de conexión: {e}")

if not st.session_state.autenticado:
    pantalla_login()
    st.stop()

# Inicialización de variables de sesión
for key in ["cliente_sel", "huerta_sel", "producto_a_editar", "cliente_a_editar", "huerta_a_editar"]:
    if key not in st.session_state:
        st.session_state[key] = None

if "productos_receta_temp" not in st.session_state:
    st.session_state.productos_receta_temp = []

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
        try:
            cookie_manager.delete("solano_session", key="delete_solano_session")
        except Exception:
            pass
        st.session_state.clear()
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
# GENERADOR DE PDF
# ==========================================
def generar_pdf_estilo_solano(
    empresa="SOLANO AGROQUÍMICOS",
    subtitulo="NUTRICIÓN ESPECIALIZADA",
    fecha=None,
    num_factura="0000001",
    cliente_nombre="Cliente General",
    huerta_nombre="Huerta General",
    huerta_ubicacion="Apatzingán, Michoacán",
    objetivo="Aplicación agrícola",
    volumen_tanque="2000 litros",
    productos_detalle=None,
    asesor_nombre="Q.F.B. Jose Luis Infante Magaña",
    asesor_ced="Ced: 10649771",
    asesor_rfc="RFC: IAML9204182U2",
    sello_digital=None,
    logo_path="logo.png"
):
    if productos_detalle is None:
        productos_detalle = []
    if not fecha:
        fecha = obtener_fecha_actual()
        
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    # ----------------------------------------------------
    # 1. ENCABEZADO (LOGO Y DATOS DE EMPRESA / FECHA)
    # ----------------------------------------------------
    if os.path.exists(logo_path):
        pdf.image(logo_path, x=10, y=8, w=22)
    
    # Título central
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(40, 40, 40)
    pdf.set_xy(10, 8)
    pdf.cell(190, 6, "RECETA DE APLICACIÓN", align="C", ln=True)
    
    # Subtítulos / Datos Empresa (Izquierda)
    x_empresa = 35 if os.path.exists(logo_path) else 10
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_text_color(120, 120, 120)
    pdf.text(x_empresa, 18, empresa)
    pdf.set_font("Helvetica", "", 7.5)
    pdf.text(x_empresa, 22, subtitulo)
    
    # Fecha (Derecha)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(40, 40, 40)
    pdf.text(145, 20, f"FECHA: {fecha}")
    
    # Línea divisora
    pdf.set_draw_color(210, 210, 210)
    pdf.line(10, 28, 200, 28)
    
    # ----------------------------------------------------
    # 2. DATOS DEL CLIENTE Y HUERTA
    # ----------------------------------------------------
    pdf.set_xy(10, 31)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4, "RECETAR A:", ln=True)
    
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(255, 255, 255)
    
    # Cuadro Cliente (Azul)
    pdf.set_fill_color(0, 150, 214)
    pdf.cell(190, 5, f"  Cliente: {cliente_nombre}", fill=True, ln=True)
    
    # Cuadro Huerta (Verde)
    pdf.set_fill_color(46, 160, 67)
    pdf.cell(190, 5, f"  Nombre de la Huerta: {huerta_nombre}", fill=True, ln=True)
    
    # Cuadro Ubicación (Verde Oscuro)
    if huerta_ubicacion:
        pdf.set_fill_color(35, 130, 55)
        pdf.cell(190, 5, f"  Ubicación: {huerta_ubicacion}", fill=True, ln=True)
        
    # ----------------------------------------------------
    # 3. OBJETIVO DE LA APLICACIÓN
    # ----------------------------------------------------
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(190, 4, "OBJETIVO DE LA APLICACIÓN", align="C", ln=True)
    
    pdf.set_fill_color(250, 235, 70)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.cell(190, 5.5, f"{objetivo}", fill=True, align="C", ln=True)
    
    pdf.ln(4)
    
    # ----------------------------------------------------
    # 4. TABLA DE PRODUCTOS (CON MULTI-LÍNEA DINÁMICA)
    # ----------------------------------------------------
    w_id = 20
    w_com = 45
    w_tec = 65  # Ampliado para Ingrediente Activo
    w_func = 35 # Familia - Grupo
    w_cant = 25 # Dosis
    
    pdf.set_fill_color(140, 30, 130)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 7.5)
    
    pdf.cell(w_id, 6, "Id Prod", fill=True, align="C")
    pdf.cell(w_com, 6, "Nombre Comercial", fill=True, align="C")
    pdf.cell(w_tec, 6, "Ingrediente Activo", fill=True, align="C")
    pdf.cell(w_func, 6, "Familia - Grupo", fill=True, align="C")
    pdf.cell(w_cant, 6, "Dosis", fill=True, align="C", ln=True)
    
    pdf.set_font("Helvetica", "", 7)
    pdf.set_draw_color(220, 220, 220)
    
    h_linea = 4.0  # Altura por cada línea individual de texto
    
    for prod in productos_detalle:
        pdf.set_text_color(40, 40, 40)
        
        str_id = str(prod.get("id_producto", ""))
        str_com = str(prod.get("nombre_comercial", ""))
        str_tec = str(prod.get("nombre_tecnico", ""))
        str_func = str(prod.get("uso", ""))
        str_cant = f"{prod.get('dosis', '')} {prod.get('unidad', '')}"
        
        # Calcular cuántas líneas tomará el texto más largo en este renglón
        num_lineas_com = len(pdf.multi_cell(w_com, h_linea, str_com, dry_run=True, output="LINES"))
        num_lineas_tec = len(pdf.multi_cell(w_tec, h_linea, str_tec, dry_run=True, output="LINES"))
        num_lineas_func = len(pdf.multi_cell(w_func, h_linea, str_func, dry_run=True, output="LINES"))
        
        max_lineas = max(1, num_lineas_com, num_lineas_tec, num_lineas_func)
        row_h = max_lineas * h_linea + 2  # Altura total adaptativa con margen interno
        
        y_pos = pdf.get_y()
        
        # Dibujar rectángulos de fondo/borde para mantener la estructura uniforme
        pdf.rect(10, y_pos, w_id, row_h)
        pdf.rect(10 + w_id, y_pos, w_com, row_h)
        pdf.rect(10 + w_id + w_com, y_pos, w_tec, row_h)
        pdf.rect(10 + w_id + w_com + w_tec, y_pos, w_func, row_h)
        
        # Resaltado amarillo para la dosis
        pdf.set_fill_color(250, 235, 70)
        pdf.rect(10 + w_id + w_com + w_tec + w_func, y_pos, w_cant, row_h, style='DF')
        
        # Imprimir ID
        pdf.set_xy(10, y_pos + (row_h - h_linea)/2)
        pdf.multi_cell(w_id, h_linea, str_id, border=0, align="C")
        
        # Imprimir Nombre Comercial
        pdf.set_xy(10 + w_id, y_pos + 1)
        pdf.multi_cell(w_com, h_linea, str_com, border=0, align="C")
        
        # Imprimir Ingrediente Activo
        pdf.set_xy(10 + w_id + w_com, y_pos + 1)
        pdf.multi_cell(w_tec, h_linea, str_tec, border=0, align="C")
        
        # Imprimir Familia - Grupo
        pdf.set_xy(10 + w_id + w_com + w_tec, y_pos + 1)
        pdf.multi_cell(w_func, h_linea, str_func, border=0, align="C")
        
        # Imprimir Dosis
        pdf.set_xy(10 + w_id + w_com + w_tec + w_func, y_pos + (row_h - h_linea)/2)
        pdf.multi_cell(w_cant, h_linea, str_cant, border=0, align="C")
        
        # Mover el cursor Y al final del renglón para la siguiente fila
        pdf.set_y(y_pos + row_h)

    # ----------------------------------------------------
    # 5. FIRMA DEL ASESOR TÉCNICO
    # ----------------------------------------------------
    pdf.set_y(230)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(190, 3.5, asesor_nombre, align="C", ln=True)
    pdf.set_font("Helvetica", "", 7)
    pdf.cell(190, 3, asesor_ced, align="C", ln=True)
    pdf.cell(190, 3, asesor_rfc, align="C", ln=True)
    
    # ----------------------------------------------------
    # 6. SELLO DIGITAL Y QR
    # ----------------------------------------------------
    datos_qr = generar_sello_y_qr(
        num_factura=num_factura,
        cliente_nombre=cliente_nombre,
        huerta_nombre=huerta_nombre,
        fecha=fecha,
        productos_detalle=productos_detalle
    )
    
    sello_texto = sello_digital if sello_digital else datos_qr["sello"]
    
    y_sello = 250
    
    pdf.set_fill_color(248, 249, 250)
    pdf.set_draw_color(200, 210, 220)
    pdf.rect(10, y_sello, 190, 24, style='DF')
    
    datos_qr["qr_bytes"].seek(0)
    pdf.image(datos_qr["qr_bytes"], x=12, y=y_sello + 2, w=20, h=20, title="QR Code")
    
    pdf.set_xy(35, y_sello + 2.5)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(27, 67, 50)
    pdf.cell(0, 3.5, "VERIFICACIÓN Y AUTENTICIDAD DIGITAL - SOLANO AGROQUÍMICOS", ln=True)
    
    pdf.set_xy(35, y_sello + 7)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 3.5, f"Emitido por: {st.session_state.usuario.get('nombre', 'Administrador Solano')} | Fecha: {datos_qr['fecha_hora']}", ln=True)
    
    pdf.set_xy(35, y_sello + 11.5)
    pdf.set_font("Courier", "B", 7.5)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 3.5, f"Código de Autenticidad: {sello_texto}", ln=True)
    
    pdf.set_xy(35, y_sello + 16)
    pdf.set_font("Helvetica", "I", 6)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 3.5, "Escanee el código QR para validar este documento oficialmente en el sistema.", ln=True)
    
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
        
        try:
            res_clientes = supabase.table("clientes").select("*").execute()
            clientes = res_clientes.data if res_clientes.data else []
        except Exception as e:
            st.error(f"Error al cargar clientes: {e}")
            clientes = []
        
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
        
        try:
            res_huertas = supabase.table("huertas").select("*").eq("id_cliente", cliente["id_cliente"]).execute()
            huertas = res_huertas.data if res_huertas.data else []
        except Exception as e:
            st.error(f"Error al obtener huertas: {e}")
            huertas = []
        
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
            st.write(f"👤 **Cliente:** {cliente['nombre']} | 🌳 **Huerta:** {huerta['nombre_huerta']} ({huerta.get('ubicacion') or 'N/A'})")

        st.write("---")
        
        try:
            res_recetas = supabase.table("recetas").select(
                "id_receta, fecha, num_factura, objetivo, volumen_tanque, sello_digital, "
                "receta_detalles(dosis, unidad, productos(id_producto, nombre_comercial, nombre_tecnico, uso))"
            ).eq("id_huerta", huerta["id_huerta"]).order("id_receta", desc=True).execute()
            recetas = res_recetas.data if res_recetas.data else []
        except Exception as e:
            st.error(f"Error al consultar recetas: {e}")
            recetas = []
        
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
                        st.write(f"**Volumen:** {r.get('volumen_tanque', 'N/A')}")
                        st.write(f"🎯 **Objetivo:** {r.get('objetivo', 'N/A')}")
                        if r.get("sello_digital"):
                            st.caption(f"🛡️ **Sello Digital:** `{r.get('sello_digital')}`")
                        
                        prod_resumen = []
                        for d in detalles:
                            p = d.get("productos") or {}
                            prod_obj = {
                                "id_producto": p.get("id_producto", ""),
                                "nombre_comercial": p.get("nombre_comercial", ""),
                                "nombre_tecnico": p.get("nombre_tecnico", ""),
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
                        pdf_bytes = generar_pdf_estilo_solano(
                            empresa="SOLANO AGROQUÍMICOS",
                            subtitulo="NUTRICIÓN ESPECIALIZADA",
                            fecha=r.get("fecha") or obtener_fecha_actual(),
                            num_factura=r.get("num_factura", ""),
                            cliente_nombre=cliente.get("nombre", "Cliente General"),
                            huerta_nombre=huerta.get("nombre_huerta", "Huerta General"),
                            huerta_ubicacion=huerta.get("ubicacion", "N/A"),
                            objetivo=r.get("objetivo", ""),
                            volumen_tanque=r.get("volumen_tanque", ""),
                            productos_detalle=prods_pdf,
                            sello_digital=r.get("sello_digital"),
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
    
    try:
        huertas_data = supabase.table("huertas").select("id_huerta, nombre_huerta, ubicacion, id_cliente, clientes(id_cliente, nombre)").execute().data
        productos_data = supabase.table("productos").select("*").execute().data
    except Exception as e:
        st.error(f"Error al obtener datos: {e}")
        huertas_data = []
        productos_data = []
    
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
            
            st.info(
                f"👤 **Cliente:** {cliente_nombre_val}\n\n"
                f"🌳 **Huerta:** {huerta_info.get('nombre_huerta', 'N/A')}\n\n"
                f"📍 **Ubicación:** {huerta_info.get('ubicacion') or 'Sin ubicación'}"
            )
            
            fecha_receta = st.text_input("Fecha (Día/Mes/Año)", value=obtener_fecha_actual(), disabled=True)
            num_factura_autoincrementado = obtener_siguiente_num_factura()
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
                    "uso": prod_info.get("uso", ""),
                    "dosis": dosis_val,
                    "unidad": unidad_val
                })
                st.success(f"Añadido: [{prod_info['id_producto']}] {prod_info['nombre_comercial']}")
                st.rerun()

        if st.session_state.productos_receta_temp:
            st.write("---")
            st.markdown("### 📋 Resumen de Productos de la Receta")
            
            col_h_id, col_h_com, col_h_tec, col_h_func, col_h_cant, col_h_del = st.columns(
                [1.0, 2.5, 2.5, 2.0, 1.8, 0.7]
            )
            
            with col_h_id: st.markdown("**ID**")
            with col_h_com: st.markdown("**Nombre Comercial**")
            with col_h_tec: st.markdown("**Ingrediente Activo**")
            with col_h_func: st.markdown("**Familia - Grupo**")
            with col_h_cant: st.markdown("**Dosis**")
            with col_h_del: st.markdown("**Acción**")
            
            st.divider()

            for idx, item in enumerate(st.session_state.productos_receta_temp):
                c_id, c_com, c_tec, c_func, c_cant, c_del = st.columns(
                    [1.0, 2.5, 2.5, 2.0, 1.8, 0.7]
                )
                
                with c_id: st.write(f"`{item['id_producto']}`")
                with c_com: st.write(item["nombre_comercial"])
                with c_tec: st.write(item.get("nombre_tecnico") or "-")
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
                        sello_info = generar_sello_y_qr(
                            num_factura=num_factura_autoincrementado,
                            cliente_nombre=cliente_nombre_val,
                            huerta_nombre=huerta_info["nombre_huerta"],
                            fecha=fecha_receta,
                            productos_detalle=st.session_state.productos_receta_temp
                        )
                        
                        res_receta = supabase.table("recetas").insert({
                            "id_huerta": huerta_info["id_huerta"],
                            "fecha": fecha_receta,
                            "num_factura": num_factura_autoincrementado,
                            "objetivo": objetivo_aplicacion,
                            "volumen_tanque": volumen_tanque,
                            "sello_digital": sello_info["sello"]
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
                                num_factura=num_factura_autoincrementado,
                                cliente_nombre=cliente_nombre_val,
                                huerta_nombre=huerta_info["nombre_huerta"],
                                huerta_ubicacion=huerta_info.get("ubicacion", "N/A"),
                                objetivo=objetivo_aplicacion,
                                volumen_tanque=volumen_tanque,
                                productos_detalle=st.session_state.productos_receta_temp,
                                sello_digital=sello_info["sello"],
                                logo_path="logo.png"
                            )
                            
                            st.session_state.productos_receta_temp = []
                            st.success(f"¡Receta #{id_receta_creada} guardada con éxito!")
                            
                            st.download_button(
                                label="📄 Descargar PDF Con QR y Sello Digital",
                                data=bytes(pdf_bytes),
                                file_name=f"Receta_{id_receta_creada}_{huerta_info['nombre_huerta']}.pdf",
                                mime="application/pdf"
                            )
                    except Exception as e:
                        st.error(f"Error al guardar la receta: {e}")

# ==========================================
# PESTAÑA 3: AGENDAR VISITAS
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
                    opciones_horas = [
                        "06:00 AM", "06:30 AM", "07:00 AM", "07:30 AM", "08:00 AM", "08:30 AM",
                        "09:00 AM", "09:30 AM", "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM",
                        "12:00 PM", "12:30 PM", "01:00 PM", "01:30 PM", "02:00 PM", "02:30 PM",
                        "03:00 PM", "03:30 PM", "04:00 PM", "04:30 PM", "05:00 PM", "05:30 PM",
                        "06:00 PM", "06:30 PM", "07:00 PM", "07:30 PM", "08:00 PM"
                    ]
                    hora_v_str = st.selectbox("Hora aproximada *", opciones_horas, index=6)

                notas_v = st.text_area("Objetivo / Notas de la visita", placeholder="Ej. Revisión de plagas, foliarización o aplicación de nutrientes...")

                btn_guardar_visita = st.form_submit_button("💾 Agendar Visita", type="primary", use_container_width=True)

                if btn_guardar_visita:
                    hora_v = datetime.strptime(hora_v_str, "%I:%M %p").time()
                    fecha_hora_dt = datetime.combine(fecha_v, hora_v)

                    try:
                        supabase.table("visitas").insert({
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
                            try:
                                supabase.table("clientes").update({
                                    "nombre": edit_nombre,
                                    "telefono": edit_telefono,
                                    "correo": edit_correo
                                }).eq("id_cliente", cli_edit["id_cliente"]).execute()
                                
                                st.session_state.cliente_a_editar = None
                                st.success("¡Cliente actualizado!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al actualizar cliente: {e}")
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
            try:
                res_cli_all = supabase.table("clientes").select("*").order("id_cliente", desc=True).execute()
                list_cli = res_cli_all.data if res_cli_all.data else []
            except Exception as e:
                st.error(f"Error al obtener clientes: {e}")
                list_cli = []
            
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

    with sub_tab_hue:
        col_f_hue, col_t_hue = st.columns([1.2, 2.8])
        
        try:
            res_cli_select = supabase.table("clientes").select("id_cliente, nombre").execute()
            cli_options = res_cli_select.data if res_cli_select.data else []
        except Exception:
            cli_options = []
            
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
                                try:
                                    supabase.table("huertas").update({
                                        "nombre_huerta": edit_nombre_h,
                                        "ubicacion": edit_ubicacion_h,
                                        "hectareas": edit_ha_h,
                                        "id_cliente": dict_cli_lookup[edit_cli_key]
                                    }).eq("id_huerta", hue_edit["id_huerta"]).execute()
                                    
                                    st.session_state.huerta_a_editar = None
                                    st.success("¡Huerta actualizada!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar la huerta: {e}")
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
            try:
                res_hue_all = supabase.table("huertas").select("*, clientes(nombre)").order("id_huerta", desc=True).execute()
                list_hue = res_hue_all.data if res_hue_all.data else []
            except Exception as e:
                st.error(f"Error al consultar huertas: {e}")
                list_hue = []
            
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
# PESTAÑA 5: CATÁLOGO DE PRODUCTOS (CRUD Y EXCEL)
# ==========================================
with tab_productos:
    st.subheader("🧪 Catálogo de Productos Agroquímicos")
    
    with st.expander("📥 Importar o Actualizar Productos mediante Excel / CSV", expanded=False):
        col_ex1, col_ex2 = st.columns([2, 1])
        
        with col_ex1:
            st.markdown("##### Subir archivo de Excel")
            st.caption(
                "Asegúrate de que las columnas del Excel se llamen preferentemente así:\n"
                "`id_producto`, `nombre_comercial`, `Ingrediente Activo (con concentración)`, `Familia - Grupo`."
            )
            
            archivo_excel = st.file_uploader("Selecciona tu archivo (.xlsx o .csv)", type=["xlsx", "xls", "csv"])
            
            if archivo_excel is not None:
                try:
                    if archivo_excel.name.endswith('.csv'):
                        df_import = pd.read_csv(archivo_excel)
                    else:
                        df_import = pd.read_excel(archivo_excel)
                    
                    mapa_columnas = {
                        "Ingrediente Activo (con concentración)": "nombre_tecnico",
                        "Ingrediente Activo": "nombre_tecnico",
                        "Familia - Grupo": "uso",
                        "Familia": "uso",
                        "Grupo": "uso"
                    }
                    df_import = df_import.rename(columns=mapa_columnas)
                    
                    st.write("🔍 **Vista previa de los datos a importar:**")
                    st.dataframe(df_import.head(5), use_container_width=True)
                    
                    cols_requeridas = {"id_producto", "nombre_comercial"}
                    cols_presentes = set(df_import.columns)
                    
                    if not cols_requeridas.issubset(cols_presentes):
                        st.error(f"❌ Al archivo le faltan columnas obligatorias: {cols_requeridas - cols_presentes}")
                    else:
                        if st.button("🚀 Cargar Productos a la Base de Datos", type="primary"):
                            cols_permitidas = ["id_producto", "nombre_comercial", "nombre_tecnico", "uso"]
                            cols_validas = [col for col in cols_permitidas if col in df_import.columns]
                            
                            df_final = df_import[cols_validas].fillna("")
                            registros = df_final.to_dict(orient="records")
                            
                            supabase.table("productos").upsert(registros).execute()
                            st.success(f"✅ ¡Se han importado/actualizado {len(registros)} productos con éxito!")
                            st.rerun()
                            
                except Exception as e:
                    st.error(f"Error al procesar el archivo Excel: {e}")
                    
        with col_ex2:
            st.markdown("##### Descargar Plantilla")
            st.caption("Usa esta plantilla base para rellenar tus productos en Excel con los encabezados exactos:")
            
            df_plantilla = pd.DataFrame([
                {
                    "id_producto": "PROD-001",
                    "nombre_comercial": "Amistar Extra",
                    "Ingrediente Activo (con concentración)": "Azoxistrobin + Ciproconazol (200 g/L)",
                    "Familia - Grupo": "Estrobilurinas + Triazoles"
                },
                {
                    "id_producto": "PROD-002",
                    "nombre_comercial": "Akron 300",
                    "Ingrediente Activo (con concentración)": "Chlorpyrifos (480 g/L)",
                    "Familia - Grupo": "Organofosforados"
                }
            ])
            
            buffer_excel = io.BytesIO()
            with pd.ExcelWriter(buffer_excel, engine='openpyxl') as writer:
                df_plantilla.to_excel(writer, index=False, sheet_name='Productos')
            buffer_excel.seek(0)
            
            st.download_button(
                label="📥 Descargar Plantilla Excel (.xlsx)",
                data=buffer_excel,
                file_name="Plantilla_Productos_Solano.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    st.write("---")

    col_f_prod, col_t_prod = st.columns([1.2, 2.8])
    
    with col_f_prod:
        prod_edit = st.session_state.producto_a_editar
        
        if prod_edit:
            st.markdown("### ✏️ Editar Producto")
            with st.form("form_edit_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", value=prod_edit.get("id_producto", ""), disabled=True)
                nombre_com = st.text_input("Nombre Comercial *", value=prod_edit.get("nombre_comercial", ""))
                nombre_tec = st.text_input("Ingrediente Activo (con concentración)", value=prod_edit.get("nombre_tecnico", "") or "")
                uso_val = st.text_input("Familia - Grupo", value=prod_edit.get("uso", "") or "")
                
                c1, c2 = st.columns(2)
                with c1:
                    guardar_prod_edit = st.form_submit_button("💾 Actualizar", type="primary")
                with c2:
                    cancel_prod_edit = st.form_submit_button("❌ Cancelar")
                
                if guardar_prod_edit:
                    if nombre_com:
                        try:
                            supabase.table("productos").update({
                                "nombre_comercial": nombre_com,
                                "nombre_tecnico": nombre_tec,
                                "uso": uso_val
                            }).eq("id_producto", prod_edit["id_producto"]).execute()
                            
                            st.session_state.producto_a_editar = None
                            st.success("¡Producto actualizado!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al actualizar producto: {e}")
                    else:
                        st.error("Campos obligatorios (*).")
                        
                if cancel_prod_edit:
                    st.session_state.producto_a_editar = None
                    st.rerun()
        else:
            st.markdown("### ➕ Registrar Nuevo Producto (Manual)")
            with st.form("form_nuevo_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", placeholder="Ej. PROD-001")
                nombre_com = st.text_input("Nombre Comercial *", placeholder="Ej. Amistar Extra")
                nombre_tec = st.text_input("Ingrediente Activo (con concentración)", placeholder="Ej. Azoxistrobin + Ciproconazol (200 g/L)")
                uso_val = st.text_input("Familia - Grupo", placeholder="Ej. Estrobilurinas + Triazoles")
                
                guardar_prod = st.form_submit_button("💾 Registrar Producto", type="primary")
                
                if guardar_prod:
                    if id_prod_val and nombre_com:
                        try:
                            supabase.table("productos").insert({
                                "id_producto": id_prod_val,
                                "nombre_comercial": nombre_com,
                                "nombre_tecnico": nombre_tec,
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
        
        busqueda_prod = st.text_input("🔍 Buscar Producto", placeholder="Buscar por ID, nombre comercial o ingrediente activo...")
        
        try:
            res_prod_all = supabase.table("productos").select("*").order("id_producto", desc=False).execute()
            list_prods = res_prod_all.data if res_prod_all.data else []
        except Exception as e:
            st.error(f"Error al consultar productos: {e}")
            list_prods = []
        
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
                        st.caption(f"🧪 Ingrediente Activo: {p.get('nombre_tecnico') or 'N/A'}")
                        st.write(f"🧬 **Familia - Grupo:** {p.get('uso') or 'N/A'}")
                    with c2:
                        if st.button("✏️ Editar", key=f"edit_prod_{p['id_producto']}"):
                            st.session_state.producto_a_editar = p
                            st.rerun()
                    with c3:
                        if st.button("🗑️ Borrar", key=f"del_prod_{p['id_producto']}"):
                            confirmar_eliminar_producto(p)
