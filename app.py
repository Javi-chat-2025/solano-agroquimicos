import os
import io
import json
import hashlib
from datetime import datetime, timedelta
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
import extra_streamlit_components as stx
import qrcode

# Importaciones necesarias de ReportLab para la generación del PDF
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors


# ==========================================
# CONFIGURACIÓN INICIAL DE LA APLICACIÓN
# ==========================================
load_dotenv()

st.set_page_config(
    page_title="Solano Agroquímicos - Recetas y Citas", 
    page_icon="🥑", 
    layout="wide"
)

# Cargar estilos CSS externos si existen
def cargar_css(nombre_archivo="style.css"):
    if os.path.exists(nombre_archivo):
        with open(nombre_archivo, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

cargar_css("style.css")


# ==========================================
# CONEXIÓN A SUPABASE Y FUNCIONES AUXILIARES
# ==========================================
@st.cache_resource
def init_supabase():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        st.error("⚠️ Faltan las credenciales de Supabase en las variables de entorno.")
        st.stop()
    return create_client(url, key)

supabase = init_supabase()

def obtener_fecha_actual():
    return datetime.now().strftime("%d/%m/%Y")

def formatear_id_cliente(id_raw):
    if id_raw is None:
        return "N/A"
    if isinstance(id_raw, int) or (isinstance(id_raw, str) and str(id_raw).isdigit()):
        return f"CLI-{int(id_raw):04d}"
    return str(id_raw)

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


# ==========================================
# GENERACIÓN DE SELLO DIGITAL Y QR
# ==========================================
def generar_sello_y_qr(num_factura, cliente_nombre, huerta_nombre, fecha, productos_detalle):
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
# GENERACIÓN DE PDF (REPORTLAB)
# ==========================================
def generar_pdf_estilo_solano(empresa, subtitulo, fecha, num_factura, cliente_nombre, 
                              huerta_nombre, huerta_ubicacion, objetivo, volumen_tanque, 
                              productos_detalle, sello_digital, qr_bytes, fecha_hora_emision, logo_path="logo.png"):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    
    style_title = ParagraphStyle('DocTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, textColor=colors.HexColor('#1b4332'), spaceAfter=2)
    style_subtitle = ParagraphStyle('DocSubTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#2d6a4f'), spaceAfter=5)
    style_label = ParagraphStyle('Label', fontName='Helvetica-Bold', fontSize=9, textColor=colors.HexColor('#1b4332'))
    style_val = ParagraphStyle('Val', fontName='Helvetica', fontSize=9, textColor=colors.black)
    style_cell_header = ParagraphStyle('CellHeader', fontName='Helvetica-Bold', fontSize=8, textColor=colors.white, alignment=1)
    style_cell_body = ParagraphStyle('CellBody', fontName='Helvetica', fontSize=8, textColor=colors.black, alignment=1)
    style_footer_text = ParagraphStyle('FooterText', fontName='Helvetica', fontSize=7, textColor=colors.HexColor('#4a5568'))

    elements = []

    # Encabezado
    logo_element = ""
    if os.path.exists(logo_path):
        try:
            logo_element = Image(logo_path, width=70, height=70)
        except:
            logo_element = Paragraph("<b>SOLANO</b>", style_title)
    else:
        logo_element = Paragraph("<b>SOLANO</b>", style_title)

    header_text = [
        Paragraph(empresa, style_title),
        Paragraph(subtitulo, style_subtitle),
        Paragraph("RECETA TÉCNICA Y RECOMENDACIÓN DE CAMPO", ParagraphStyle('SubHeader', fontName='Helvetica', fontSize=8, textColor=colors.gray))
    ]

    folio_box = [
        Paragraph(f"<b>FOLIO:</b> {num_factura}", ParagraphStyle('Folio', fontName='Helvetica-Bold', fontSize=12, textColor=colors.HexColor('#b7094c'), alignment=2)),
        Paragraph(f"<b>FECHA:</b> {fecha}", ParagraphStyle('Fecha', fontName='Helvetica', fontSize=9, alignment=2))
    ]

    header_table = Table([[logo_element, header_text, folio_box]], colWidths=[80, 300, 160])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (2,0), (2,0), 'RIGHT'),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    # Datos Generales
    datos_info = [
        [Paragraph("CLIENTE:", style_label), Paragraph(str(cliente_nombre), style_val), Paragraph("HUERTA:", style_label), Paragraph(str(huerta_nombre), style_val)],
        [Paragraph("UBICACIÓN:", style_label), Paragraph(str(huerta_ubicacion), style_val), Paragraph("VOLUMEN TANQUE:", style_label), Paragraph(f"{volumen_tanque}", style_val)],
        [Paragraph("OBJETIVO:", style_label), Paragraph(str(objetivo), style_val), Paragraph("", style_label), Paragraph("", style_val)]
    ]
    t_datos = Table(datos_info, colWidths=[90, 180, 100, 170])
    t_datos.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#d8f3dc')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e9ecef')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(t_datos)
    elements.append(Spacer(1, 12))

    # Tabla de Productos
    headers_tabla = ["ID PROD", "PRODUCTO", "INGREDIENTE ACTIVO", "FAMILIA / GRUPO", "DOSIS"]
    data_productos = [[Paragraph(h, style_cell_header) for h in headers_tabla]]

    if productos_detalle:
        for p in productos_detalle:
            data_productos.append([
                Paragraph(str(p.get("id_producto", "")), style_cell_body),
                Paragraph(str(p.get("nombre_comercial", "")), style_cell_body),
                Paragraph(str(p.get("nombre_tecnico", "N/A")), style_cell_body),
                Paragraph(str(p.get("uso", "N/A")), style_cell_body),
                Paragraph(f"{p.get('dosis', '')} {p.get('unidad', '')}", style_cell_body)
            ])

    t_productos = Table(data_productos, colWidths=[60, 130, 140, 120, 90])
    t_productos.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1b4332')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#2d6a4f')),
        ('TOPPADDING', (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(t_productos)
    elements.append(Spacer(1, 15))

    # Pie con QR y Sello Digital
    img_qr_obj = Image(qr_bytes, width=70, height=70)
    info_sello = [
        Paragraph(f"<b>SELLO DIGITAL DE AUTENTICIDAD:</b>", style_label),
        Paragraph(f"<font fontName='Courier'>{sello_digital}</font>", style_footer_text),
        Paragraph(f"<b>FECHA Y HORA DE EMISIÓN:</b> {fecha_hora_emision}", style_footer_text),
        Paragraph("Documento firmado digitalmente para validación e inspección técnica en campo.", style_footer_text)
    ]

    t_footer = Table([[img_qr_obj, info_sello]], colWidths=[80, 460])
    t_footer.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#ced4da')),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8f9fa')),
        ('TOPPADDING', (0,0), (-1,-1), 6),
        ('BOTTOMPADDING', (0,0), (-1,-1), 6),
    ]))
    elements.append(t_footer)

    doc.build(elements)
    buffer.seek(0)
    return buffer.getvalue()


# ==========================================
# VERIFICACIÓN PÚBLICA DE QR
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
                    st.markdown(f"**Folio Receta:** #{receta.get('num_factura', 'N/A')}")
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
# CONTROL DE SESIÓN Y AUTENTICACIÓN
# ==========================================
cookie_manager = stx.CookieManager(key="solano_cookie_manager")

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False
if "usuario" not in st.session_state:
    st.session_state.usuario = None

try:
    solano_cookie = cookie_manager.get(cookie="solano_session")
    if solano_cookie and not st.session_state.autenticado:
        user_data = json.loads(solano_cookie) if isinstance(solano_cookie, str) else solano_cookie
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
                correo_input = st.text_input("Correo Electrónico", placeholder="Introduce tu correo")
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

# Inicialización de variables globales en la sesión
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
    st.write(f"¿Deseas eliminar al cliente **{cliente.get('nombre')}** (`{formatear_id_cliente(cliente.get('id_cliente'))}`)?")
    st.warning("⚠️ Esta acción es permanente.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("clientes").delete().eq("id_cliente", cliente["id_cliente"]).execute()
                st.success("Cliente eliminado.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar: tiene huertas asociadas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()

@st.dialog("⚠️ Confirmar Eliminación de Huerta")
def confirmar_eliminar_huerta(huerta):
    st.write(f"¿Deseas eliminar la huerta **{huerta.get('nombre_huerta')}**?")
    st.warning("⚠️ Esta acción es permanente.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("huertas").delete().eq("id_huerta", huerta["id_huerta"]).execute()
                st.success("Huerta eliminada.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar: tiene recetas registradas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()

@st.dialog("⚠️ Confirmar Eliminación de Producto")
def confirmar_eliminar_producto(producto):
    st.write(f"¿Deseas eliminar el producto **[{producto.get('id_producto')}] {producto.get('nombre_comercial')}**?")
    st.warning("⚠️ Esta acción es permanente.")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔥 Eliminar", type="primary", use_container_width=True):
            try:
                supabase.table("productos").delete().eq("id_producto", producto["id_producto"]).execute()
                st.success("Producto eliminado del catálogo.")
                st.rerun()
            except Exception:
                st.error("No se puede eliminar: el producto está presente en recetas emitidas.")
    with col2:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()


# ==========================================
# ENCABEZADO DE LA APLICACIÓN WEB
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

# Navegación Principal
tab_perfiles, tab_nueva_receta, tab_visitas, tab_registro, tab_productos = st.tabs([
    "📂 Perfiles y Huertas",
    "📜 Emitir Receta",
    "📅 Agendar Visitas",
    "👥 Gestionar Clientes y Huertas",
    "🧪 Catálogo de Productos"
])


# ==========================================
# PESTAÑA 1: EXPLORADOR POR PERFILES
# ==========================================
with tab_perfiles:
    if st.session_state.cliente_sel is None:
        st.subheader("👥 Perfiles de Clientes")
        busqueda_cliente = st.text_input("🔍 Buscar cliente", placeholder="Filtrar por nombre, teléfono o correo...")
        
        try:
            res_clientes = supabase.table("clientes").select("*").execute()
            clientes = res_clientes.data if res_clientes.data else []
        except Exception as e:
            st.error(f"Error al cargar clientes: {e}")
            clientes = []
        
        if busqueda_cliente:
            term = busqueda_cliente.lower()
            clientes = [c for c in clientes if term in str(c.get("nombre", "")).lower() or term in str(c.get("telefono", "")).lower()]
        
        if not clientes:
            st.info("No se encontraron clientes registrados.")
        else:
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
            st.info("El cliente no tiene huertas registradas.")
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
            st.write(f"👤 **Cliente:** {cliente['nombre']} | 🌳 **Huerta:** {huerta['nombre_huerta']}")

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
            st.info("No hay recetas para esta huerta.")
        else:
            for r in recetas:
                with st.container(border=True):
                    col_detalles, col_pdf = st.columns([3, 1])
                    detalles = r.get("receta_detalles", [])
                    prods_pdf = []
                    
                    with col_detalles:
                        st.markdown(f"### 📄 Receta Folio #{r.get('num_factura', r['id_receta'])} — Fecha: `{r.get('fecha', 'N/A')}`")
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
                        sello_info = generar_sello_y_qr(
                            num_factura=r.get("num_factura", "0000001"),
                            cliente_nombre=cliente.get("nombre", "Cliente"),
                            huerta_nombre=huerta.get("nombre_huerta", "Huerta"),
                            fecha=r.get("fecha") or obtener_fecha_actual(),
                            productos_detalle=prods_pdf
                        )
                        
                        pdf_bytes = generar_pdf_estilo_solano(
                            empresa="SOLANO AGROQUÍMICOS",
                            subtitulo="NUTRICIÓN ESPECIALIZADA",
                            fecha=r.get("fecha") or obtener_fecha_actual(),
                            num_factura=r.get("num_factura", "0000001"),
                            cliente_nombre=cliente.get("nombre", "Cliente General"),
                            huerta_nombre=huerta.get("nombre_huerta", "Huerta General"),
                            huerta_ubicacion=huerta.get("ubicacion", "N/A"),
                            objetivo=r.get("objetivo", ""),
                            volumen_tanque=r.get("volumen_tanque", ""),
                            productos_detalle=prods_pdf,
                            sello_digital=r.get("sello_digital") or sello_info["sello"],
                            qr_bytes=sello_info["qr_bytes"],
                            fecha_hora_emision=sello_info["fecha_hora"]
                        )
                        
                        st.download_button(
                            label="⬇️ Descargar PDF",
                            data=pdf_bytes,
                            file_name=f"Receta_{r.get('num_factura', r['id_receta'])}.pdf",
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
        huertas_data, productos_data = [], []
    
    if not huertas_data or not productos_data:
        st.warning("⚠️ Debes tener registradas al menos una huerta y un producto.")
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
            st.text_input("Folio Consecutivo", value=num_factura_autoincrementado, disabled=True)
            volumen_tanque = st.text_input("Volumen del Tanque", value="2000 litros")
            objetivo_aplicacion = st.text_input("Objetivo de la Aplicación", value="Control plagas / nutrición foliar")
            
        with col_c2:
            st.markdown("### 2. Agregar Productos")
            prod_sel_nombre = st.selectbox("Seleccionar Producto *", list(dict_prods.keys()))
            prod_info = dict_prods[prod_sel_nombre]
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                dosis_val = st.text_input("Cantidad / Dosis", value="1")
            with col_d2:
                unidad_val = st.selectbox("Unidad", ["L", "Kg", "g", "mL", "L / Ha", "Kg / Ha"])
                
            if st.button("➕ Añadir Producto a la Receta"):
                st.session_state.productos_receta_temp.append({
                    "id_producto": prod_info["id_producto"],
                    "nombre_comercial": prod_info["nombre_comercial"],
                    "nombre_tecnico": prod_info.get("nombre_tecnico", ""),
                    "uso": prod_info.get("uso", ""),
                    "dosis": dosis_val,
                    "unidad": unidad_val
                })
                st.success(f"Añadido: {prod_info['nombre_comercial']}")
                st.rerun()

        if st.session_state.productos_receta_temp:
            st.write("---")
            st.markdown("### 📋 Resumen de Productos de la Receta")
            
            st.table(st.session_state.productos_receta_temp)

            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("🗑️ Limpiar Productos"):
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
                                qr_bytes=sello_info["qr_bytes"],
                                fecha_hora_emision=sello_info["fecha_hora"]
                            )
                            
                            st.session_state.productos_receta_temp = []
                            st.success(f"¡Receta Folio #{num_factura_autoincrementado} guardada con éxito!")
                            
                            st.download_button(
                                label="📄 Descargar Receta PDF Con Sello y QR",
                                data=pdf_bytes,
                                file_name=f"Receta_{num_factura_autoincrementado}.pdf",
                                mime="application/pdf"
                            )
                    except Exception as e:
                        st.error(f"Error al guardar la receta: {e}")


# ==========================================
# PESTAÑA 3: AGENDAR VISITAS
# ==========================================
with tab_visitas:
    st.subheader("📅 Gestión de Visitas Técnicas")
    
    col_form_v, col_hist_v = st.columns([1.3, 2.7])

    with col_form_v:
        st.markdown("### ➕ Agendar Nueva Visita")
        try:
            res_huertas_v = supabase.table("huertas").select("id_huerta, nombre_huerta, ubicacion, id_cliente, clientes(id_cliente, nombre)").execute()
            huertas_v_data = res_huertas_v.data if res_huertas_v.data else []
        except Exception as e:
            st.error(f"Error al cargar huertas: {e}")
            huertas_v_data = []

        if not huertas_v_data:
            st.warning("Asegúrate de registrar huertas antes de agendar una visita.")
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
                    fecha_v = st.date_input("Fecha *", format="DD/MM/YYYY")
                with col_f2:
                    hora_v = st.time_input("Hora *")

                notas_v = st.text_area("Notas / Objetivo", placeholder="Revisiones, foliarización...")

                btn_guardar_visita = st.form_submit_button("💾 Agendar Visita", type="primary", use_container_width=True)

                if btn_guardar_visita:
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
                        st.error(f"Error al agendar visita: {e}")

    with col_hist_v:
        st.markdown("### 📋 Citas Agendadas")
        try:
            res_visitas = supabase.table("visitas").select("*, huertas(nombre_huerta, ubicacion, clientes(nombre, telefono))").order("fecha_visita", desc=False).execute()
            list_visitas = res_visitas.data if res_visitas.data else []
        except Exception as e:
            st.error(f"Error al consultar visitas: {e}")
            list_visitas = []

        if not list_visitas:
            st.info("No hay visitas programadas.")
        else:
            for v in list_visitas:
                h_info = v.get("huertas") or {}
                c_info = h_info.get("clientes") or {}
                
                fecha_obj = datetime.fromisoformat(v["fecha_visita"].replace("Z", ""))
                fecha_formateada = fecha_obj.strftime("%d/%m/%Y a las %I:%M %p")
                
                nombre_cliente = c_info.get("nombre", "Cliente")
                nombre_huerta = h_info.get("nombre_huerta", "Huerta")
                ubicacion_huerta = h_info.get("ubicacion") or "Sin ubicación"
                notas_visita = v.get("notas") or "Seguimiento técnico"

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
                        ics_bytes = generar_evento_ics(
                            titulo=f"Visita Técnica: {nombre_huerta}",
                            descripcion=f"Cliente: {nombre_cliente}\nNotas: {notas_visita}",
                            ubicacion=ubicacion_huerta,
                            fecha_inicio_dt=fecha_obj
                        )

                        st.download_button(
                            label="📲 Agregar a Calendario (.ics)",
                            data=ics_bytes,
                            file_name=f"Visita_{nombre_huerta}.ics",
                            mime="text/calendar",
                            key=f"dl_ics_{v['id_visita']}",
                            type="primary",
                            use_container_width=True
                        )


# ==========================================
# PESTAÑA 4: GESTIÓN DE CLIENTES Y HUERTAS
# ==========================================
with tab_registro:
    st.subheader("👥 Gestión de Clientes y Huertas")
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
                    
                    if st.form_submit_button("💾 Actualizar", type="primary"):
                        if edit_nombre and edit_correo:
                            supabase.table("clientes").update({"nombre": edit_nombre, "telefono": edit_telefono, "correo": edit_correo}).eq("id_cliente", cli_edit["id_cliente"]).execute()
                            st.session_state.cliente_a_editar = None
                            st.success("Cliente actualizado")
                            st.rerun()
            else:
                st.markdown("### ➕ Registrar Nuevo Cliente")
                with st.form("form_nuevo_cliente"):
                    nuevo_nombre = st.text_input("Nombre completo *")
                    nuevo_telefono = st.text_input("Teléfono")
                    nuevo_correo = st.text_input("Correo electrónico *")
                    
                    if st.form_submit_button("💾 Registrar Cliente", type="primary"):
                        if nuevo_nombre and nuevo_correo:
                            supabase.table("clientes").insert({"nombre": nuevo_nombre, "telefono": nuevo_telefono, "correo": nuevo_correo}).execute()
                            st.success("Cliente guardado")
                            st.rerun()

        with col_t_cli:
            st.markdown("### 📋 Clientes Registrados")
            res_cli_all = supabase.table("clientes").select("*").order("id_cliente", desc=True).execute()
            list_cli = res_cli_all.data if res_cli_all.data else []
            
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
        res_cli_select = supabase.table("clientes").select("id_cliente, nombre").execute()
        cli_options = res_cli_select.data if res_cli_select.data else []
        dict_cli_lookup = {f"{c['nombre']} ({formatear_id_cliente(c['id_cliente'])})": c['id_cliente'] for c in cli_options}
        
        with col_f_hue:
            if cli_options:
                hue_edit = st.session_state.huerta_a_editar
                if hue_edit:
                    st.markdown("### ✏️ Editar Huerta")
                    with st.form("form_edit_huerta"):
                        edit_nombre_h = st.text_input("Nombre Huerta *", value=hue_edit.get("nombre_huerta", ""))
                        edit_ubicacion_h = st.text_input("Ubicación", value=hue_edit.get("ubicacion", "") or "")
                        edit_ha_h = st.number_input("Hectáreas", value=float(hue_edit.get("hectareas", 0.0) or 0.0))
                        
                        if st.form_submit_button("💾 Actualizar", type="primary"):
                            supabase.table("huertas").update({"nombre_huerta": edit_nombre_h, "ubicacion": edit_ubicacion_h, "hectareas": edit_ha_h}).eq("id_huerta", hue_edit["id_huerta"]).execute()
                            st.session_state.huerta_a_editar = None
                            st.success("Huerta actualizada")
                            st.rerun()
                else:
                    st.markdown("### ➕ Registrar Nueva Huerta")
                    with st.form("form_nueva_huerta"):
                        nuevo_nombre_h = st.text_input("Nombre de Huerta *")
                        nuevo_ubicacion_h = st.text_input("Ubicación")
                        nuevo_ha_h = st.number_input("Hectáreas", value=0.0)
                        nuevo_cli_key = st.selectbox("Cliente *", list(dict_cli_lookup.keys()))
                        
                        if st.form_submit_button("💾 Registrar Huerta", type="primary"):
                            if nuevo_nombre_h:
                                supabase.table("huertas").insert({
                                    "nombre_huerta": nuevo_nombre_h,
                                    "ubicacion": nuevo_ubicacion_h,
                                    "hectareas": nuevo_ha_h,
                                    "id_cliente": dict_cli_lookup[nuevo_cli_key]
                                }).execute()
                                st.success("Huerta registrada")
                                st.rerun()

        with col_t_hue:
            st.markdown("### 📋 Huertas Registradas")
            res_hue_all = supabase.table("huertas").select("*, clientes(nombre)").order("id_huerta", desc=True).execute()
            list_hue = res_hue_all.data if res_hue_all.data else []
            
            for h in list_hue:
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 1, 1])
                    with c1:
                        cli_nombre_h = h['clientes']['nombre'] if h.get('clientes') else 'Sin Cliente'
                        st.markdown(f"**🥑 {h['nombre_huerta']}** — Cliente: `{cli_nombre_h}`")
                    with c2:
                        if st.button("✏️ Editar", key=f"edit_hue_{h['id_huerta']}"):
                            st.session_state.huerta_a_editar = h
                            st.rerun()
                    with c3:
                        if st.button("🗑️ Borrar", key=f"del_hue_{h['id_huerta']}"):
                            confirmar_eliminar_huerta(h)


# ==========================================
# PESTAÑA 5: CATÁLOGO DE PRODUCTOS (EXCEL / CRUD)
# ==========================================
with tab_productos:
    st.subheader("🧪 Catálogo de Productos Agroquímicos")
    
    with st.expander("📥 Importar o Actualizar Productos mediante Excel / CSV"):
        archivo_excel = st.file_uploader("Selecciona archivo (.xlsx o .csv)", type=["xlsx", "csv"])
        if archivo_excel is not None:
            df_import = pd.read_csv(archivo_excel) if archivo_excel.name.endswith('.csv') else pd.read_excel(archivo_excel)
            mapa_columnas = {
                "Ingrediente Activo (con concentración)": "nombre_tecnico",
                "Ingrediente Activo": "nombre_tecnico",
                "Familia - Grupo": "uso"
            }
            df_import = df_import.rename(columns=mapa_columnas)
            st.dataframe(df_import.head(5), use_container_width=True)
            
            if st.button("🚀 Cargar a la Base de Datos", type="primary"):
                cols_validas = [c for c in ["id_producto", "nombre_comercial", "nombre_tecnico", "uso"] if c in df_import.columns]
                registros = df_import[cols_validas].fillna("").to_dict(orient="records")
                supabase.table("productos").upsert(registros).execute()
                st.success(f"¡Se importaron {len(registros)} productos con éxito!")
                st.rerun()

    st.write("---")
    col_f_prod, col_t_prod = st.columns([1.2, 2.8])
    
    with col_f_prod:
        prod_edit = st.session_state.producto_a_editar
        if prod_edit:
            st.markdown("### ✏️ Editar Producto")
            with st.form("form_edit_producto"):
                st.text_input("ID Producto", value=prod_edit.get("id_producto", ""), disabled=True)
                nombre_com = st.text_input("Nombre Comercial *", value=prod_edit.get("nombre_comercial", ""))
                nombre_tec = st.text_input("Ingrediente Activo", value=prod_edit.get("nombre_tecnico", "") or "")
                uso_val = st.text_input("Familia - Grupo", value=prod_edit.get("uso", "") or "")
                
                if st.form_submit_button("💾 Actualizar", type="primary"):
                    supabase.table("productos").update({"nombre_comercial": nombre_com, "nombre_tecnico": nombre_tec, "uso": uso_val}).eq("id_producto", prod_edit["id_producto"]).execute()
                    st.session_state.producto_a_editar = None
                    st.success("Producto actualizado")
                    st.rerun()
        else:
            st.markdown("### ➕ Registrar Nuevo Producto")
            with st.form("form_nuevo_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", placeholder="Ej. PROD-001")
                nombre_com = st.text_input("Nombre Comercial *", placeholder="Ej. Amistar Extra")
                nombre_tec = st.text_input("Ingrediente Activo", placeholder="Ej. Azoxistrobin (200 g/L)")
                uso_val = st.text_input("Familia - Grupo", placeholder="Ej. Estrobilurinas")
                
                if st.form_submit_button("💾 Registrar Producto", type="primary"):
                    if id_prod_val and nombre_com:
                        supabase.table("productos").insert({"id_producto": id_prod_val, "nombre_comercial": nombre_com, "nombre_tecnico": nombre_tec, "uso": uso_val}).execute()
                        st.success("Producto registrado")
                        st.rerun()

    with col_t_prod:
        st.markdown("### 📋 Productos en Catálogo")
        busqueda_prod = st.text_input("🔍 Buscar Producto")
        res_prod_all = supabase.table("productos").select("*").order("id_producto", desc=False).execute()
        list_prods = res_prod_all.data if res_prod_all.data else []
        
        if busqueda_prod:
            term_p = busqueda_prod.lower()
            list_prods = [p for p in list_prods if term_p in str(p.get("nombre_comercial", "")).lower() or term_p in str(p.get("id_producto", "")).lower()]
            
        for p in list_prods:
            with st.container(border=True):
                c1, c2, c3 = st.columns([3, 1, 1])
                with c1:
                    st.markdown(f"**[{p['id_producto']}] {p['nombre_comercial']}**")
                    st.caption(f"🧪 Ingrediente Activo: {p.get('nombre_tecnico') or 'N/A'}")
                with c2:
                    if st.button("✏️ Editar", key=f"edit_prod_{p['id_producto']}"):
                        st.session_state.producto_a_editar = p
                        st.rerun()
                with c3:
                    if st.button("🗑️ Borrar", key=f"del_prod_{p['id_producto']}"):
                        confirmar_eliminar_producto(p)
