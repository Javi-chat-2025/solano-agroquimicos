import os
import io
import json
import hashlib
import re
from datetime import datetime, timedelta
import pytz
import streamlit as st
import pandas as pd
from dotenv import load_dotenv
from supabase import create_client
from fpdf import FPDF
import extra_streamlit_components as stx
import qrcode
from streamlit_dnd import dnd, apply_move

# ==========================================
# CONFIGURACIÓN DE ZONA HORARIA (MÉXICO UTC-6)
# ==========================================
ZONA_HORARIA_MX = pytz.timezone("America/Mexico_City")

def obtener_datetime_local():
    return datetime.now(ZONA_HORARIA_MX)

def obtener_fecha_actual():
    return obtener_datetime_local().strftime("%d/%m/%Y")

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
    fecha_hora_emision = obtener_datetime_local().strftime("%d/%m/%Y %H:%M:%S")
    
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
                correo_input = st.text_input("📧 Correo electrónico", placeholder="Introduce el correo")
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
                                
                                fecha_exp = obtener_datetime_local() + timedelta(days=7)
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

# Borrador de nueva receta: las claves permanecen entre reruns y pestañas.
# No se guarda en Supabase hasta pulsar Guardar Receta.
if st.session_state.pop("nueva_receta_reiniciar_pendiente", False):
    for nombre in ("borrador_huerta", "borrador_fecha", "borrador_volumen",
                   "borrador_objetivo", "borrador_producto", "borrador_dosis",
                   "borrador_unidad"):
        st.session_state.pop(nombre, None)

if "borrador_volumen" not in st.session_state:
    st.session_state.borrador_volumen = "2000 litros"
if "borrador_objetivo" not in st.session_state:
    st.session_state.borrador_objetivo = "Aplicación para defoliadores + control de hongos"
if "borrador_dosis" not in st.session_state:
    st.session_state.borrador_dosis = "1"

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
    st.write(f"👤 **Q.F.B Jose Luis Infante Magaña**")
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
    """Receta A4 rediseñada. Mantiene el logotipo original y los datos guardados."""
    productos_detalle = productos_detalle or []
    fecha = fecha or obtener_fecha_actual()

    def fecha_en_letras(valor):
        """Formato español para la fecha visible del PDF: 22-Octubre-2026.

        Mantiene intacta la fecha original que se guarda en Supabase y se
        utiliza para el sello digital / QR.
        """
        meses = ("Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                 "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre")
        if isinstance(valor, (datetime,)):
            dia, mes, anio = valor.day, valor.month, valor.year
        elif hasattr(valor, "day") and hasattr(valor, "month") and hasattr(valor, "year"):
            dia, mes, anio = valor.day, valor.month, valor.year
        else:
            texto = str(valor).strip()
            fecha_parseada = None
            for patron in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    fecha_parseada = datetime.strptime(texto, patron)
                    break
                except ValueError:
                    pass
            if fecha_parseada is None:
                return str(valor)
            dia, mes, anio = fecha_parseada.day, fecha_parseada.month, fecha_parseada.year
        return f"{dia:02d}-{meses[mes-1]}-{anio}"

    fecha_pdf = fecha_en_letras(fecha)
    class PDFReceta(FPDF):
        def footer(self):
            # Pie presente en todas las páginas, también en continuaciones.
            self.set_y(-12.7)
            self.set_draw_color(215, 226, 216)
            self.line(12.7, self.get_y(), 197.3, self.get_y())
            self.set_font("Arial", "", 8.5)
            self.set_text_color(92, 105, 112)
            self.cell(0, 8, f"Página {self.page_no()} de {{nb}}", align="C")

    pdf = PDFReceta(format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(12.7, 12.7, 12.7)  # 1.27 cm exactos, izquierda / arriba / derecha
    pdf.set_auto_page_break(auto=False)
    VERDE = (27, 67, 50)
    VERDE_MEDIO = (45, 106, 79)
    AMARILLO = (255, 244, 184)
    GRIS = (92, 105, 112)
    BLANCO = (255, 255, 255)
    ANCHO = 184.6  # A4: 210 - 12.7 mm por cada lado
    COLS = [50.5, 56.3, 43.8, 34.0]  # Total 184.6 mm; cuatro columnas aprobadas

    def limpio(valor):
        """Normaliza caracteres para las fuentes Arial compatibles integradas en FPDF."""
        texto = str(valor if valor is not None else "")
        return texto.replace("\u2022", "-").replace("\u2014", "-").replace("\u2013", "-").replace("\u2705", "")

    def set_color(color):
        pdf.set_text_color(*color)

    def texto_ajustado(x, y, ancho, valor, size=10, bold=False, max_height=30, align="L"):
        pdf.set_font("Arial", "B" if bold else "", size)
        set_color(VERDE if bold else (36, 49, 54))
        pdf.set_xy(x, y)
        pdf.multi_cell(ancho, 5.1, limpio(valor), border=0, align=align)
        return min(pdf.get_y() - y, max_height)

    def lineas(valor, ancho, size=10, bold=False):
        pdf.set_font("Arial", "B" if bold else "", size)
        return pdf.multi_cell(ancho - 4, 5.1, limpio(valor), dry_run=True, output="LINES")

    def encabezado(continuacion=False):
        pdf.add_page()
        pdf.set_fill_color(*VERDE)
        pdf.rect(0, 0, 210, 4, style="F")
        if os.path.exists(logo_path):
            # Usa el logo real del proyecto, conservando su proporción.
            try:
                pdf.image(logo_path, x=12.7, y=12.7, w=27, h=24, keep_aspect_ratio=True)
            except Exception:
                pass
        x_brand = 43 if os.path.exists(logo_path) else 12.7
        pdf.set_font("Arial", "B", 13)
        set_color(VERDE)
        pdf.set_xy(x_brand, 15.7)
        pdf.cell(106, 7, limpio(empresa), align="C")
        pdf.set_font("Arial", "", 9)
        set_color(GRIS)
        pdf.set_xy(x_brand, 23.7)
        pdf.cell(106, 5, limpio(subtitulo), align="C")
        pdf.set_draw_color(235, 185, 32)
        pdf.set_line_width(0.7)
        pdf.line(x_brand + 4, 30.2, x_brand + 102, 30.2)
        pdf.set_font("Arial", "B", 9.5)
        set_color(VERDE)
        pdf.set_xy(141.3, 16.7)
        pdf.cell(56, 6, f"FECHA: {limpio(fecha_pdf)}", align="R")
        pdf.set_font("Arial", "B", 17)
        set_color(VERDE)
        pdf.set_xy(12.7, 37.7)
        pdf.cell(184.6, 9, "RECETA DE APLICACIÓN", align="C")
        if continuacion:
            return 54.7

        # Datos del productor. En renglones separados, para permitir nombres extensos.
        y = 51.7
        for etiqueta, valor in (
            ("CLIENTE", cliente_nombre),
            ("NOMBRE DE LA HUERTA", huerta_nombre),
            ("UBICACIÓN", huerta_ubicacion or "Sin ubicación"),
        ):
            n = len(lineas(valor, 136, 10.5, True))
            alto = max(9.2, 5.1 * n + 2.5)
            pdf.set_fill_color(237, 247, 238)
            pdf.rect(12.7, y, 184.6, alto, style="F")
            pdf.set_fill_color(*VERDE)
            pdf.rect(12.7, y, 39, alto, style="F")
            pdf.set_font("Arial", "B", 8)
            set_color(BLANCO)
            pdf.set_xy(14.7, y + 1)
            pdf.multi_cell(35, 4.2, limpio(etiqueta), align="C")
            texto_ajustado(54.7, y + 1, 139.6, valor, 10.5, True, align="L")
            y += alto + 1

        y += 1
        objetivo_lineas = len(lineas(objetivo, 180.6, 10.5))
        alto_objetivo = max(15, 5.1 * objetivo_lineas + 9)
        pdf.set_fill_color(247, 205, 66)
        pdf.rect(12.7, y, 184.6, 6, style="F")
        pdf.set_font("Arial", "B", 10)
        set_color(VERDE)
        pdf.set_xy(15.7, y + 0.5)
        pdf.cell(178.6, 5, "OBJETIVO DE LA APLICACIÓN", align="C")
        pdf.set_fill_color(255, 250, 231)
        pdf.rect(12.7, y + 6, 184.6, alto_objetivo - 6, style="F")
        texto_ajustado(15.7, y + 7, 178.6, objetivo, 10.5, align="C")
        y += alto_objetivo + 2
        return y + 2

    def cabecera_tabla(y):
        pdf.set_fill_color(*VERDE)
        pdf.rect(12.7, y, ANCHO, 10, style="F")
        x = 12.7
        for ancho, nombre in zip(COLS, ["Nombre Comercial", "Ingrediente Activo", "Familia - Grupo", "Dosis / 2000 L"]):
            pdf.set_font("Arial", "B", 9.2)
            set_color(BLANCO)
            pdf.set_xy(x + 1, y + 2)
            pdf.multi_cell(ancho - 2, 5.4, nombre, align="C")
            x += ancho
        return y + 10

    def fila(y, prod, indice, ultimo=False):
        valores = [
            prod.get("nombre_comercial", ""),
            prod.get("nombre_tecnico", ""),
            prod.get("uso", ""),
            (f"{prod.get('dosis', '')} {prod.get('unidad', '')}").strip(),
        ]
        alturas = [len(lineas(valor, col, 9.5, idx in (0, 3))) for idx, (valor, col) in enumerate(zip(valores, COLS))]
        altura = max(10.5, max(alturas) * 5.1 + 3.5)
        # Cada producto se pagina por separado: NO reservar espacio
        # para la firma ni para el QR durante el dibujo de la tabla.
        # Así la penúltima hoja se aprovecha hasta el límite seguro.
        if y + altura > 275:
            y = cabecera_tabla(encabezado(continuacion=True))
        x = 12.7
        for i, (ancho, valor) in enumerate(zip(COLS, valores)):
            pdf.set_fill_color(*(AMARILLO if i == 3 else ((255, 255, 255) if indice % 2 else (247, 250, 248))))
            pdf.rect(x, y, ancho, altura, style="F")
            pdf.set_draw_color(214, 224, 216)
            pdf.rect(x, y, ancho, altura)
            pdf.set_font("Arial", "B" if i in (0, 3) else "", 9.5)
            set_color(VERDE if i == 3 else (37, 49, 44))
            pdf.set_xy(x + 2, y + 1.5)
            pdf.multi_cell(ancho - 4, 5.1, limpio(valor), align="C")
            x += ancho
        return y + altura

    y = cabecera_tabla(encabezado())
    if not productos_detalle:
        y = fila(y, {"nombre_comercial": "Sin productos registrados"}, 0, ultimo=True)
    else:
        for i, prod in enumerate(productos_detalle):
            y = fila(y, prod, i, ultimo=(i == len(productos_detalle) - 1))

    # Firma y verificación se paginan INDEPENDIENTEMENTE.
    # Puede quedar la firma en una hoja y el QR en la siguiente.
    # No se crea una página nueva hasta que el elemento correspondiente
    # deje de caber, reduciendo espacios en blanco innecesarios.
    y += 5
    if y + 30 > 276:
        y = encabezado(continuacion=True) + 6

    pdf.set_draw_color(*VERDE_MEDIO)
    pdf.line(50, y + 10, 160, y + 10)
    texto_ajustado(12.7, y + 13, 184.6, asesor_nombre, 10.5, True, align="C")
    texto_ajustado(12.7, y + 19, 184.6, asesor_ced, 9.5, align="C")
    texto_ajustado(12.7, y + 24, 184.6, asesor_rfc, 9.5, align="C")

    datos_qr = generar_sello_y_qr(
        num_factura=num_factura, cliente_nombre=cliente_nombre,
        huerta_nombre=huerta_nombre, fecha=fecha, productos_detalle=productos_detalle
    )
    sello_texto = sello_digital or datos_qr["sello"]
    y_qr = y + 30
    if y_qr + 26 > 276:
        # QR y sus textos permanecen juntos, pero no obligan
        # a mover la firma a esta página.
        y_qr = encabezado(continuacion=True) + 6
    pdf.set_draw_color(*VERDE_MEDIO)
    pdf.set_fill_color(248, 251, 248)
    pdf.rect(12.7, y_qr, 184.6, 26, style="DF")
    datos_qr["qr_bytes"].seek(0)
    pdf.image(datos_qr["qr_bytes"], x=16.7, y=y_qr + 2.5, w=21, h=21)
    pdf.set_font("Arial", "B", 8.2)
    set_color(VERDE)
    pdf.set_xy(44.7, y_qr + 3)
    pdf.cell(150, 5, "VERIFICACIÓN Y AUTENTICIDAD DIGITAL - SOLANO AGROQUÍMICOS")
    usuario = getattr(st, "session_state", {}).get("usuario") or {}
    emisor = limpio(usuario.get("nombre", "Administrador Solano"))
    texto_ajustado(44.7, y_qr + 9, 149, f"Emitido por: Q.F.B Jose Luis Infante Magaña | Fecha: {fecha_pdf}", 8)
    texto_ajustado(44.7, y_qr + 15, 149, f"Código de autenticidad: {sello_texto}", 8, True)
    texto_ajustado(44.7, y_qr + 21, 149, "Escanee el QR para consultar los datos de esta receta.", 7.5)
    # Detalle importante: el QR actual contiene información, no un enlace de consulta.
    return pdf.output()

# ==========================================
# EDICIÓN SEGURA: CREA UNA NUEVA VERSIÓN DE RECETA
# Se conserva la receta original y su historial.
# ==========================================
def ordenar_productos_arrastrando(productos, clave, nombres=None):
    """Ordena productos completos con streamlit-dnd, sin modificar sus dosis.

    Cada hijo directo tiene key propia. El evento solo mueve elementos de la
    lista existente: no toca Supabase hasta guardar la receta.
    """
    if len(productos) < 2:
        return
    st.caption("☰ Arrastra las tarjetas de esta lista para cambiar el orden de la receta.")
    with st.container(key=clave):
        for i, item in enumerate(productos):
            nombre = (nombres or {}).get(str(item.get("id_producto")), item.get("nombre_comercial", "Producto"))
            with st.container(key=f"{clave}_fila_{i}", border=True):
                st.markdown(f"**☰ {i + 1}. {nombre}**")
                st.caption(f"💧 Dosis: {item.get('dosis', '')} {item.get('unidad', '')}")
    evento = dnd(clave, key=f"{clave}_dnd", cross=False, handle=True, handle_corner="top-right", indicator="line", color="#40916c")
    if evento:
        apply_move(evento, productos)
        st.rerun()


@st.dialog("✏️ Editar receta", width="large")
def editar_receta(receta, cliente, huerta):
    id_original = receta["id_receta"]
    clave = f"editor_receta_{id_original}"
    st.info(f"Receta #{id_original}. Al guardar, se creará una nueva versión en esta huerta y se conservará la anterior.")
    if st.button("✖️ Cerrar editor", key=f"{clave}_cerrar"):
        st.session_state.pop(clave, None)
        st.session_state.pop("receta_editor_activa", None)
        st.rerun()

    try:
        catalogo = supabase.table("productos").select("id_producto,nombre_comercial,nombre_tecnico,uso").execute().data or []
    except Exception as e:
        st.error(f"No se pudo cargar el catálogo: {e}")
        return
    por_id = {str(p["id_producto"]): p for p in catalogo}
    unidades = ["ml", "lt", "gr", "kg", "ml / Ha", "lt / Ha", "gr / Ha", "kg / Ha",
                "ml / 2000 lt", "lt / 2000 lt", "gr / 2000 lt", "kg / 2000 lt"]

    # Cargar los productos originales una sola vez por apertura de la receta.
    if clave not in st.session_state:
        detalles = []
        for d in sorted(receta.get("receta_detalles", []), key=lambda row: row.get("posicion") if row.get("posicion") is not None else 999999):
            producto = d.get("productos") or {}
            detalles.append({"id_producto": producto.get("id_producto"),
                             "dosis": str(d.get("dosis") or ""),
                             "unidad": str(d.get("unidad") or "ml")})
        st.session_state[clave] = {"productos": detalles, "editar": None, "agregar": False}

    editor = st.session_state[clave]
    try:
        fecha_inicial = datetime.strptime(str(receta.get("fecha", "")), "%d/%m/%Y").date()
    except ValueError:
        fecha_inicial = obtener_datetime_local().date()
    fecha = st.date_input("📅 Fecha de receta", value=fecha_inicial, format="DD/MM/YYYY", key=f"{clave}_fecha")
    volumen = st.text_input("🛢️ Volumen del tanque", value=str(receta.get("volumen_tanque") or ""), key=f"{clave}_volumen")
    objetivo = st.text_input("🎯 Objetivo de la aplicación", value=str(receta.get("objetivo") or ""), key=f"{clave}_objetivo")

    st.markdown("### 🧪 Lista de productos de la receta")
    if not editor["productos"]:
        st.warning("La receta no tiene productos. Agrega al menos uno antes de guardar.")

    ordenar_productos_arrastrando(editor["productos"], f"arrastrar_editor_{id_original}",
                                {str(k): v["nombre_comercial"] for k, v in por_id.items()})

    st.caption("✏️ Para cambiar cantidades o eliminar productos, utiliza los controles siguientes.")
    for i, d in enumerate(editor["productos"]):
        codigo = str(d["id_producto"])
        producto = por_id.get(codigo)
        nombre = producto["nombre_comercial"] if producto else f"Producto [{codigo}] (fuera del catálogo)"
        with st.container(border=True):
            st.markdown(f"**{i + 1}. [{codigo}] {nombre}**")
            st.write(f"💧 **Cantidad / Dosis:** {d['dosis']} {d['unidad']}")
            col_ed, col_del = st.columns(2)
            with col_ed:
                if st.button("✏️ Editar producto", key=f"{clave}_abrir_ed_{i}", use_container_width=True):
                    editor["editar"] = i
                    editor["agregar"] = False
                    st.rerun()
            with col_del:
                if st.button("🗑️ Eliminar producto", key=f"{clave}_borrar_{i}", use_container_width=True):
                    editor["productos"].pop(i)
                    editor["editar"] = None
                    st.rerun()

            if editor["editar"] == i:
                with st.form(f"{clave}_form_ed_{i}"):
                    dosis_ed = st.text_input("💧 Nueva cantidad / dosis", value=d["dosis"])
                    unidad_actual = d["unidad"]
                    opciones_unidad = unidades if unidad_actual in unidades else [unidad_actual] + unidades
                    unidad_ed = st.selectbox("📏 Unidad", opciones_unidad,
                                             index=opciones_unidad.index(unidad_actual))
                    guardar_ed = st.form_submit_button("✅ Aplicar cambio", type="primary")
                if guardar_ed:
                    if not dosis_ed.strip():
                        st.error("La dosis no puede estar vacía.")
                    else:
                        d["dosis"] = dosis_ed.strip()
                        d["unidad"] = unidad_ed
                        editor["editar"] = None
                        st.rerun()

    if st.button("➕ Agregar producto", key=f"{clave}_abrir_agregar", use_container_width=True):
        editor["agregar"] = True
        editor["editar"] = None
        st.rerun()

    if editor["agregar"]:
        opciones = [k for k in por_id if k not in {str(d["id_producto"]) for d in editor["productos"]}]
        if not opciones:
            st.info("No quedan productos disponibles en el catálogo para agregar.")
        else:
            with st.form(f"{clave}_form_agregar"):
                codigo_nuevo = st.selectbox("🧪 Seleccionar producto", opciones,
                                            format_func=lambda k: f"[{k}] {por_id[k]['nombre_comercial']}")
                dosis_nueva = st.text_input("💧 Cantidad / dosis", value="1")
                unidad_nueva = st.selectbox("📏 Unidad", unidades)
                confirmar_agregar = st.form_submit_button("✅ Añadir a la lista", type="primary")
            if confirmar_agregar:
                if not dosis_nueva.strip():
                    st.error("Escribe una dosis válida.")
                else:
                    editor["productos"].append({"id_producto": por_id[codigo_nuevo]["id_producto"],
                                                 "dosis": dosis_nueva.strip(), "unidad": unidad_nueva})
                    editor["agregar"] = False
                    st.rerun()

    st.divider()
    confirmar = st.checkbox("Confirmo que revisé los productos y deseo crear una versión corregida", key=f"{clave}_confirmar")
    if st.button("💾 Guardar nueva versión de receta", type="primary", use_container_width=True, key=f"{clave}_guardar"):
        detalle_nuevo = editor["productos"]
        if not confirmar or not detalle_nuevo or not objetivo.strip() or not volumen.strip() or any(not d["dosis"].strip() for d in detalle_nuevo):
            st.error("Revisa los datos, incluye al menos un producto y marca la confirmación.")
            return
        if any(str(d["id_producto"]) not in por_id for d in detalle_nuevo):
            st.error("Hay productos que ya no están disponibles en el catálogo. Elimínalos o restáuralos antes de guardar.")
            return
        id_creado = None
        try:
            nueva_fecha = fecha.strftime("%d/%m/%Y")
            folio = obtener_siguiente_num_factura()
            nuevos_productos = [dict(por_id[str(d["id_producto"])], dosis=d["dosis"], unidad=d["unidad"]) for d in detalle_nuevo]
            sello = generar_sello_y_qr(folio, cliente["nombre"], huerta["nombre_huerta"], nueva_fecha, nuevos_productos)["sello"]
            res = supabase.table("recetas").insert({
                "id_huerta": huerta["id_huerta"], "fecha": nueva_fecha, "num_factura": folio,
                "objetivo": objetivo.strip(), "volumen_tanque": volumen.strip(), "sello_digital": sello,
            }).execute()
            if not res.data:
                raise RuntimeError("No se recibió el identificador de la nueva receta")
            id_creado = res.data[0]["id_receta"]
            datos = [dict(d, id_receta=id_creado, posicion=i + 1) for i, d in enumerate(detalle_nuevo)]
            supabase.table("receta_detalles").insert(datos).execute()
        except Exception as e:
            if id_creado is not None:
                try:
                    supabase.table("receta_detalles").delete().eq("id_receta", id_creado).execute()
                    supabase.table("recetas").delete().eq("id_receta", id_creado).execute()
                except Exception:
                    st.warning("No se pudo revertir el registro incompleto. Revísalo en Supabase.")
            st.error(f"No se pudo guardar la nueva versión: {e}")
            return
        st.session_state.pop(clave, None)
        st.session_state.pop("receta_editor_activa", None)
        st.session_state["receta_ultima_editada"] = id_creado
        st.rerun()

# Cierra cualquier editor de una receta anterior al trabajar con una receta nueva.
# Solo limpia el estado del editor; no toca productos_receta_temp ni el borrador.
def cerrar_editor_anterior():
    id_anterior = st.session_state.pop("receta_editor_activa", None)
    if id_anterior is not None:
        st.session_state.pop(f"editor_receta_{id_anterior}", None)

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
                "receta_detalles(dosis, unidad, posicion, productos(id_producto, nombre_comercial, nombre_tecnico, uso))"
            ).eq("id_huerta", huerta["id_huerta"]).order("id_receta", desc=True).execute()
            recetas = res_recetas.data if res_recetas.data else []
        except Exception as e:
            st.error(f"Error al consultar recetas: {e}")
            recetas = []
        
        if not recetas:
            st.info(f"No hay recetas emitidas para la huerta '{huerta['nombre_huerta']}'.")
        else:
            if st.session_state.get("receta_ultima_editada"):
                st.success(f"Nueva versión #{st.session_state.pop('receta_ultima_editada')} guardada. Puedes descargar su PDF en este perfil.")
            for r in recetas:
                with st.container(border=True):
                    col_detalles, col_pdf = st.columns([3, 1])
                    
                    detalles = sorted(r.get("receta_detalles", []), key=lambda row: row.get("posicion") if row.get("posicion") is not None else 999999)
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
                            type="primary",
                            on_click=cerrar_editor_anterior
                        )
                        if st.button("✏️ Editar receta", key=f"editar_receta_{r['id_receta']}"):
                            st.session_state["receta_editor_activa"] = r["id_receta"]

            # El diálogo debe llamarse en CADA ejecución mientras haya una receta activa.
            # De lo contrario, st.rerun() lo cerraría al agregar, editar o quitar productos.
            id_activo = st.session_state.get("receta_editor_activa")
            if id_activo is not None:
                receta_activa = next((r for r in recetas if str(r["id_receta"]) == str(id_activo)), None)
                if receta_activa is not None:
                    editar_receta(receta_activa, cliente, huerta)
                else:
                    st.session_state.pop("receta_editor_activa", None)

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
        
        col_c1, col_c2 = st.container(), st.container()
        
        with col_c1:
            st.markdown("### 1. Datos Generales")
            opciones_huertas = list(dict_huertas.keys())
            if st.session_state.get("borrador_huerta") not in opciones_huertas:
                st.session_state.borrador_huerta = opciones_huertas[0]
            huerta_sel_key = st.selectbox("🌳 Seleccionar huerta *", opciones_huertas, key="borrador_huerta")
            huerta_info = dict_huertas[huerta_sel_key]
            
            cliente_info = huerta_info.get("clientes") or {}
            cliente_nombre_val = cliente_info.get("nombre", "Cliente General")
            
            st.info(
                f"👤 **Cliente:** {cliente_nombre_val}\n\n"
                f"🌳 **Huerta:** {huerta_info.get('nombre_huerta', 'N/A')}\n\n"
                f"📍 **Ubicación:** {huerta_info.get('ubicacion') or 'Sin ubicación'}"
            )
            
            fecha_receta_dt = st.date_input("📅 Fecha de receta", value=obtener_datetime_local().date(), format="DD/MM/YYYY", key="borrador_fecha")
            fecha_receta = fecha_receta_dt.strftime("%d/%m/%Y")
            
            num_factura_autoincrementado = obtener_siguiente_num_factura()
            volumen_tanque = st.text_input("🛢️ Volumen del tanque", key="borrador_volumen")
            objetivo_aplicacion = st.text_input("🎯 Objetivo de la aplicación", key="borrador_objetivo")
            
        with col_c2:
            st.markdown("### 2. Agregar Productos")
            opciones_productos = list(dict_prods.keys())
            if st.session_state.get("borrador_producto") not in opciones_productos:
                st.session_state.borrador_producto = opciones_productos[0]
            prod_sel_nombre = st.selectbox("🧪 Seleccionar producto *", opciones_productos, key="borrador_producto")
            prod_info = dict_prods[prod_sel_nombre]
            
            col_d1, col_d2 = st.columns(2)
            with col_d1:
                dosis_val = st.text_input("💧 Cantidad / dosis", key="borrador_dosis")
            with col_d2:
                unidad_val = st.selectbox("📏 Unidad", ["ml","lt", "gr", "kg"," ml / Ha", "lt / Ha", "gr / Ha","kg / Ha","ml / 2000 lt","lt / 2000 lt","gr / 2000 lt","kg / 2000 lt"], key="borrador_unidad")
                
            if st.button("➕ Añadir Producto", on_click=cerrar_editor_anterior):
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
            
            ordenar_productos_arrastrando(st.session_state.productos_receta_temp, "arrastrar_receta_nueva")
            st.caption("🗑️ Para eliminar productos, utiliza los controles siguientes.")
            for idx, item in enumerate(st.session_state.productos_receta_temp):
                with st.container(border=True):
                    st.markdown(f"**{idx + 1}. [{item['id_producto']}] {item['nombre_comercial']}**")
                    st.caption(f"🧬 Ingrediente activo: {item.get('nombre_tecnico') or '-'}  |  🧪 Familia - Grupo: {item.get('uso') or '-'}")
                    st.write(f"💧 **Dosis / 2000 L:** {item['dosis']} {item['unidad']}")
                    col_del = st.container()
                    with col_del:
                        if st.button("🗑️ Eliminar", key=f"del_prod_receta_{idx}", use_container_width=True):
                            st.session_state.productos_receta_temp.pop(idx)
                            st.rerun()

            st.write("")
            col_b1, col_b2 = st.columns([1, 4])
            with col_b1:
                if st.button("🗑️ Limpiar Todo"):
                    st.session_state.productos_receta_temp = []
                    st.rerun()
                    
            with col_b2:
                if st.button("💾 Guardar Receta y Generar PDF", type="primary", on_click=cerrar_editor_anterior):
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
                                "posicion": indice + 1,
                                "id_receta": id_receta_creada,
                                "id_producto": item["id_producto"],
                                "dosis": item["dosis"],
                                "unidad": item["unidad"]
                            } for indice, item in enumerate(st.session_state.productos_receta_temp)]
                            
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
                            # Reiniciar campos únicamente cuando finalizó el guardado.
                            st.session_state.nueva_receta_reiniciar_pendiente = True
                            st.success(f"¡Receta #{id_receta_creada} guardada con éxito!")
                            
                            st.download_button(
                                label="📄 Descargar PDF Con QR y Sello Digital",
                                data=bytes(pdf_bytes),
                                file_name=f"Receta_{id_receta_creada}_{huerta_info['nombre_huerta']}.pdf",
                                mime="application/pdf",
                                on_click=cerrar_editor_anterior
                            )
                    except Exception as e:
                        st.error(f"Error al guardar la receta: {e}")

# ==========================================
# PESTAÑA 3: AGENDAR VISITAS
# ==========================================
with tab_visitas:
    st.subheader("📅 Gestión de Visitas Técnicas")
    st.caption("Agenda citas para prospección o seguimiento en campo y sincronízalas con el calendario de tu celular.")

    col_form_v, col_hist_v = st.container(), st.container()

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
                    fecha_v = st.date_input("📅 Fecha de la visita *", value=obtener_datetime_local(), format="DD/MM/YYYY")
                with col_f2:
                    hora_v = st.time_input("🕒 Hora aproximada *", value=obtener_datetime_local().time())

                notas_v = st.text_area("📝 Objetivo / notas de la visita", placeholder="Ej. Revisión de plagas, foliarización o aplicación de nutrientes...")

                btn_guardar_visita = st.form_submit_button("💾 Agendar Visita", type="primary", use_container_width=True)

                if btn_guardar_visita:
                    fecha_hora_naive = datetime.combine(fecha_v, hora_v)
                    fecha_hora_dt = ZONA_HORARIA_MX.localize(fecha_hora_naive)

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
                
                try:
                    fecha_obj = datetime.fromisoformat(v["fecha_visita"].replace("Z", ""))
                    if fecha_obj.tzinfo is None:
                        fecha_obj = ZONA_HORARIA_MX.localize(fecha_obj)
                    else:
                        fecha_obj = fecha_obj.astimezone(ZONA_HORARIA_MX)
                except Exception:
                    fecha_obj = obtener_datetime_local()

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
        col_f_cli, col_t_cli = st.container(), st.container()
        
        with col_f_cli:
            cli_edit = st.session_state.cliente_a_editar
            
            if cli_edit:
                st.markdown("### ✏️ Editar Cliente")
                with st.form("form_edit_cliente"):
                    edit_nombre = st.text_input("👤 Nombre completo *", value=cli_edit.get("nombre", ""))
                    edit_telefono = st.text_input("📞 Teléfono", value=cli_edit.get("telefono", "") or "")
                    edit_correo = st.text_input("📧 Correo electrónico *", value=cli_edit.get("correo", "") or "")
                    
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
                    nuevo_nombre = st.text_input("👤 Nombre completo *")
                    nuevo_telefono = st.text_input("📞 Teléfono")
                    nuevo_correo = st.text_input("📧 Correo electrónico *")
                    
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
        col_f_hue, col_t_hue = st.container(), st.container()
        
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
                        edit_nombre_h = st.text_input("🌳 Nombre de huerta *", value=hue_edit.get("nombre_huerta", ""))
                        edit_ubicacion_h = st.text_input("📍 Ubicación", value=hue_edit.get("ubicacion", "") or "")
                        edit_ha_h = st.number_input("📏 Hectáreas", value=float(hue_edit.get("hectareas", 0.0) or 0.0))
                        
                        default_cli_idx = 0
                        for idx, (k, v) in enumerate(dict_cli_lookup.items()):
                            if v == hue_edit.get("id_cliente"):
                                default_cli_idx = idx
                                break
                                
                        edit_cli_key = st.selectbox("👤 Cliente *", list(dict_cli_lookup.keys()), index=default_cli_idx)
                        
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
                        nuevo_nombre_h = st.text_input("🌳 Nombre de huerta *")
                        nuevo_ubicacion_h = st.text_input("📍 Ubicación")
                        nuevo_ha_h = st.number_input("📏 Hectáreas", value=0.0, step=0.5)
                        nuevo_cli_key = st.selectbox("👤 Cliente *", list(dict_cli_lookup.keys()))
                        
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
        col_ex1, col_ex2 = st.container(), st.container()
        
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

    # IDs disponibles: la sugerencia se basa en el catálogo completo, no en el orden alfabético.
    # El ID permanece editable porque algunas instalaciones usan códigos personalizados.
    def obtener_referencia_ids_productos():
        ids = []
        tamano_lote = 1000
        try:
            for inicio in range(0, 50000, tamano_lote):
                datos = (supabase.table("productos")
                         .select("id_producto")
                         .order("id_producto")
                         .range(inicio, inicio + tamano_lote - 1)
                         .execute().data or [])
                ids.extend(str(fila["id_producto"]).strip() for fila in datos if fila.get("id_producto") is not None)
                if len(datos) < tamano_lote:
                    break
            else:
                return None, None, "El catálogo es muy grande para sugerir un ID con seguridad."
        except Exception:
            return None, None, "No fue posible consultar los IDs registrados."

        if not ids:
            return "Ninguno", "PROD-001", None

        grupos = {}
        for identificador in ids:
            coincidencia = re.fullmatch(r"(.*?)(\d+)", identificador)
            if coincidencia:
                prefijo, numero = coincidencia.groups()
                grupos.setdefault(prefijo, []).append((int(numero), len(numero), identificador))

        if not grupos:
            return "Sin secuencia numérica", None, "Los IDs no siguen una numeración identificable. Ingresa un ID manualmente."

        # No elegir arbitrariamente un formato si el catálogo mezcla distintas familias de ID.
        if len(grupos) > 1:
            return "Varios formatos", None, "Se encontraron varios formatos de ID. Ingresa un ID manualmente para evitar confusiones."

        prefijo, elementos = next(iter(grupos.items()))
        numero_max, ancho, ultimo = max(elementos, key=lambda e: e[0])
        ocupados = set(ids)
        siguiente_num = numero_max + 1
        siguiente = f"{prefijo}{siguiente_num:0{ancho}d}"
        while siguiente in ocupados:
            siguiente_num += 1
            siguiente = f"{prefijo}{siguiente_num:0{ancho}d}"
        return ultimo, siguiente, None

    ultimo_id_producto, siguiente_id_producto, aviso_ids = obtener_referencia_ids_productos()

    col_f_prod, col_t_prod = st.container(), st.container()
    
    with col_f_prod:
        prod_edit = st.session_state.producto_a_editar
        
        if prod_edit:
            st.markdown("### ✏️ Editar Producto")
            with st.form("form_edit_producto"):
                id_prod_val = st.text_input("ID / Código Producto *", value=prod_edit.get("id_producto", ""), disabled=True)
                nombre_com = st.text_input("🏷️ Nombre comercial *", value=prod_edit.get("nombre_comercial", ""))
                nombre_tec = st.text_input("🧪 Ingrediente activo (con concentración)", value=prod_edit.get("nombre_tecnico", "") or "")
                uso_val = st.text_input("🧬 Familia - Grupo", value=prod_edit.get("uso", "") or "")
                
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
            if aviso_ids:
                st.warning(aviso_ids)
            else:
                st.info(f"🆔 Último ID de la secuencia: **{ultimo_id_producto}**  |  ✅ Siguiente sugerido: **{siguiente_id_producto}**")
            st.caption("El ID sugerido sigue la numeración existente. Puedes cambiarlo si necesitas otro código.")
            if st.session_state.pop("solano_producto_registrado", False):
                st.session_state.pop("solano_nuevo_id_producto", None)
            if "solano_nuevo_id_producto" not in st.session_state:
                st.session_state.solano_nuevo_id_producto = siguiente_id_producto or ""
            with st.form("form_nuevo_producto"):
                id_prod_val = st.text_input("🆔 ID / Código Producto *", key="solano_nuevo_id_producto", placeholder="Ej. PROD-001").strip()
                nombre_com = st.text_input("🏷️ Nombre comercial *", placeholder="Ej. Amistar Extra")
                nombre_tec = st.text_input("🧪 Ingrediente activo (con concentración)", placeholder="Ej. Azoxistrobin + Ciproconazol (200 g/L)")
                uso_val = st.text_input("🧬 Familia - Grupo", placeholder="Ej. Estrobilurinas + Triazoles")
                
                guardar_prod = st.form_submit_button("💾 Registrar Producto", type="primary")
                
                if guardar_prod:
                    if id_prod_val and nombre_com.strip():
                        try:
                            id_ocupado = (supabase.table("productos")
                                          .select("id_producto")
                                          .eq("id_producto", id_prod_val)
                                          .limit(1).execute().data)
                            if id_ocupado:
                                st.error(f"El ID {id_prod_val} ya existe. Utiliza otro.")
                                st.stop()
                            supabase.table("productos").insert({
                                "id_producto": id_prod_val,
                                "nombre_comercial": nombre_com,
                                "nombre_tecnico": nombre_tec,
                                "uso": uso_val
                            }).execute()
                            st.session_state.solano_producto_registrado = True
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
