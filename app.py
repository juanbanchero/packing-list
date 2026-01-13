"""
Procesador de Picking List - Banchero Sanitarios
Versión mejorada: soporta PDFs con texto multilínea y códigos pegados
"""
import streamlit as st
import pdfplumber
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from pypdf import PdfReader, PdfWriter
from io import BytesIO
import re
from datetime import datetime

st.set_page_config(
    page_title="Picking List - Banchero Sanitarios",
    page_icon="📦",
    layout="wide"
)


def split_cod_viejo_articulo(cod_viejo_raw, articulo_raw):
    """
    Separa código viejo del artículo cuando están pegados.
    Casos manejados:
    1. Mayúscula+minúscula: FVMB1CR181Grifería -> FVMB1CR181 + Grifería
    2. Códigos FV pegados: RPFV0521CB0416/15.6-D -> RPFV0521CB + 0416/15.6-D
    3. Asteriscos: código** texto -> código + ** texto
    """
    cod_viejo_raw = cod_viejo_raw.strip() if cod_viejo_raw else ''
    articulo_raw = articulo_raw.strip() if articulo_raw else ''
    full_text = cod_viejo_raw + articulo_raw
    
    # Caso 1: Mayúscula+minúscula en cod_viejo (código pegado a nombre)
    match = re.search(r'[A-Z][a-záéíóúñ]', cod_viejo_raw)
    if match and match.start() > 0:
        cod_viejo = cod_viejo_raw[:match.start()]
        articulo = cod_viejo_raw[match.start():] + (" " + articulo_raw if articulo_raw else "")
        return cod_viejo.strip(), articulo.strip()
    
    # Caso 2: Códigos FV pegados a número de artículo (ej: RPFV0521CB0416/15.6-D)
    match = re.search(r'^([A-Z0-9]*[A-Z]{1,2})(\d{4}[/\.\-].*)$', full_text)
    if match:
        return match.group(1), match.group(2)
    
    # Caso 3: ** al final del código
    if cod_viejo_raw.endswith('**'):
        return cod_viejo_raw[:-2].strip(), '** ' + articulo_raw
    
    return cod_viejo_raw, articulo_raw


def extract_picking_data(pdf_file):
    """
    Extrae datos del picking list usando método robusto:
    1. Acumula todo el texto de las páginas de picking
    2. Separa por 'RIESTRA' (fin de cada línea)
    3. Parsea cada segmento buscando el patrón de datos
    """
    all_rows = []
    header_info = {}
    packing_start_page = None
    
    with pdfplumber.open(pdf_file) as pdf:
        accumulated_text = ""
        
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            
            # Detectar inicio de packing list
            if "Codigo Cliente" in text and "LN" in text:
                packing_start_page = page_num
                break
            
            # Extraer header de página 1
            if page_num == 0:
                n_match = re.search(r'N[°º]:\s*(\d+)', text)
                if n_match:
                    header_info['numero'] = n_match.group(1)
                fecha_match = re.search(r'FECHA:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
                if fecha_match:
                    header_info['fecha'] = fecha_match.group(1)
                hora_match = re.search(r'HORA:\s*(\d{2}:\d{2}:\d{2})', text)
                if hora_match:
                    header_info['hora'] = hora_match.group(1)
            
            # Acumular texto limpio (sin headers)
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                # Saltar líneas de header/footer
                if any(x in line.upper() for x in [
                    'PICKING LIST', 'N°:', 'FECHA:', 'HORA:', 'ESTADO:', 
                    'COD VIEJO', 'PÁGINA', 'PREPARO:', 'CONTROLO:', 
                    'COD COD', 'COMIENZO', 'FINALIZADO', 'ARTICULO', 'ALMACEN'
                ]):
                    continue
                accumulated_text += " " + line
        
        # Separar por RIESTRA (final de cada línea de datos)
        segments = accumulated_text.split('RIESTRA')
        
        for seg in segments:
            seg = seg.strip()
            if not seg:
                continue
            
            # Buscar patrón: (basura) + LINEA + CODIGO + COD_VIEJO + ARTICULO + CANT + STOCK
            # El número de línea puede estar pegado al código (ej: 109IAREPU...)
            match = re.search(
                r'(\d{1,3})\s*([A-Z]{2}[A-Z0-9]+)\s+([A-Z0-9][A-Za-z0-9]*)\s*(.+?)\s+(\d+)\s+(-?[\d.,]+)\s*$',
                seg
            )
            
            if match:
                linea = int(match.group(1))
                codigo = match.group(2)
                cod_viejo_raw = match.group(3)
                articulo_raw = match.group(4).strip()
                
                # Separar cod_viejo y artículo si están pegados
                cod_viejo, articulo = split_cod_viejo_articulo(cod_viejo_raw, articulo_raw)
                
                # Parsear cantidad
                cantidad = float(match.group(5))
                
                # Parsear stock (puede tener punto de miles: 2.203)
                stock_str = match.group(6).replace('.', '').replace(',', '.')
                stock = float(stock_str)
                
                all_rows.append({
                    'linea_original': linea,
                    'codigo': codigo,
                    'cod_viejo': cod_viejo,
                    'articulo': articulo,
                    'cantidad': cantidad,
                    'stock': stock,
                    'almacen': 'RIESTRA'
                })
    
    return all_rows, header_info, packing_start_page


def process_picking_data(rows):
    """Agrupa por cod_viejo, suma cantidades y ordena."""
    if not rows:
        return []
    
    df = pd.DataFrame(rows)
    grouped = df.groupby('cod_viejo', as_index=False).agg({
        'codigo': 'first',
        'articulo': 'first',
        'cantidad': 'sum',
        'stock': 'first',
        'almacen': 'first'
    }).sort_values('cod_viejo')
    
    grouped['linea'] = range(1, len(grouped) + 1)
    return grouped[['linea', 'codigo', 'cod_viejo', 'articulo', 'cantidad', 'stock', 'almacen']].to_dict('records')


def generate_pdf(data, header_info):
    """Genera PDF en formato A4 vertical con columnas para llenado manual."""
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=0.3*cm,
        leftMargin=0.3*cm,
        topMargin=0.6*cm,
        bottomMargin=0.6*cm
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Estilos para celdas - 10pt
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=10, leading=11, wordWrap='CJK')
    cod_style = ParagraphStyle('CodStyle', parent=styles['Normal'], fontSize=10, leading=11)
    
    title_style = ParagraphStyle(
        'Title', 
        parent=styles['Heading1'], 
        fontSize=12, 
        alignment=TA_CENTER, 
        spaceAfter=3
    )
    
    # Header
    header_text = f"""<b>PICKING LIST N° {header_info.get('numero', '-')}</b> | Fecha: {header_info.get('fecha', '-')} | <i>Ordenado por Cód. Viejo</i>"""
    elements.append(Paragraph(header_text, title_style))
    elements.append(Spacer(1, 0.1*cm))
    
    # Header de tabla
    table_data = [['#', 'COD VIEJO', 'ARTÍCULO', 'STK', 'CANT', 'REAL', '✓']]
    
    for row in data:
        cant = row['cantidad']
        cant_str = str(int(cant)) if cant == int(cant) else f"{cant:.2f}"
        
        stock = row['stock']
        stock_str = str(int(stock)) if stock == int(stock) else f"{stock:.0f}"
        
        # Paragraph para wrap automático
        cod_p = Paragraph(str(row['cod_viejo']), cod_style)
        articulo_p = Paragraph(str(row['articulo']), cell_style)
        
        table_data.append([
            str(row['linea']),
            cod_p,
            articulo_p,
            stock_str,
            cant_str,
            '',  # REAL - para llenar a mano
            ''   # ✓ - check
        ])
    
    # Anchos de columna para A4 vertical
    col_widths = [0.6*cm, 2.4*cm, 12.4*cm, 1.1*cm, 1*cm, 1.4*cm, 0.8*cm]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    table.setStyle(TableStyle([
        # Header
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B5E20')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        
        # Body
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
        ('TOPPADDING', (0, 1), (-1, -1), 2),
        
        # Alineaciones
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (1, 1), (1, -1), 'LEFT'),
        ('ALIGN', (2, 1), (2, -1), 'LEFT'),
        ('ALIGN', (3, 1), (3, -1), 'RIGHT'),
        ('ALIGN', (4, 1), (4, -1), 'RIGHT'),
        ('ALIGN', (5, 1), (5, -1), 'CENTER'),
        ('ALIGN', (6, 1), (6, -1), 'CENTER'),
        ('VALIGN', (0, 1), (-1, -1), 'MIDDLE'),
        
        # Bordes
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        
        # Colores alternados
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
        
        # Columna REAL amarilla para destacar
        ('BACKGROUND', (5, 1), (5, -1), colors.HexColor('#FFFDE7')),
    ]))
    
    elements.append(table)
    
    # Footer
    elements.append(Spacer(1, 0.3*cm))
    footer_style = ParagraphStyle('Footer', fontSize=10, alignment=TA_LEFT)
    footer_text = """<b>PREPARO:</b> __________ <b>COMIENZO:</b> ________ | <b>CONTROLÓ:</b> __________ <b>FINALIZADO:</b> ________"""
    elements.append(Paragraph(footer_text, footer_style))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def merge_with_packing(picking_buffer, original_pdf, packing_start_page):
    """Combina el picking procesado con las páginas de packing del original."""
    output_buffer = BytesIO()
    writer = PdfWriter()
    
    # Agregar páginas del picking procesado
    picking_reader = PdfReader(picking_buffer)
    for page in picking_reader.pages:
        writer.add_page(page)
    
    # Agregar páginas del packing list original
    original_pdf.seek(0)
    original_reader = PdfReader(original_pdf)
    for i in range(packing_start_page, len(original_reader.pages)):
        writer.add_page(original_reader.pages[i])
    
    writer.write(output_buffer)
    output_buffer.seek(0)
    return output_buffer, len(picking_reader.pages), len(original_reader.pages) - packing_start_page


def main():
    st.title("📦 Procesador de Picking List")
    st.caption("Banchero Sanitarios")
    
    st.markdown("**Ordena** por código viejo • **Consolida** duplicados • **Incluye** packing list")
    st.divider()
    
    uploaded_file = st.file_uploader("Subí el PDF del Picking List", type=['pdf'])
    
    if uploaded_file:
        with st.spinner("Procesando..."):
            # Hacer copia para merge posterior
            uploaded_file.seek(0)
            original_copy = BytesIO(uploaded_file.read())
            uploaded_file.seek(0)
            
            # Extraer datos
            rows, header_info, packing_start = extract_picking_data(uploaded_file)
            
            if not rows:
                st.error("No se pudieron extraer datos. Verificá que sea un picking list válido.")
                return
            
            st.success(f"✅ {len(rows)} líneas extraídas del picking list")
            
            # Procesar
            processed_data = process_picking_data(rows)
            df_original = pd.DataFrame(rows)
            duplicados = len(rows) - len(processed_data)
            
            # Métricas
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Originales", len(rows))
            col2.metric("Consolidadas", len(processed_data))
            col3.metric("Duplicados", duplicados)
            if packing_start:
                col4.metric("Packing list", "✓ Detectado")
            else:
                col4.metric("Packing list", "No encontrado")
            
            # Mostrar duplicados si los hay
            if duplicados > 0:
                dupes = df_original[df_original.duplicated('cod_viejo', keep=False)]
                with st.expander("Ver duplicados consolidados"):
                    for cod in dupes['cod_viejo'].unique():
                        subset = df_original[df_original['cod_viejo'] == cod]
                        st.write(f"**{cod}**: {list(subset['cantidad'])} → **{sum(subset['cantidad'])}**")
            
            st.divider()
            
            # Preview de datos
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Original")
                st.dataframe(
                    df_original[['linea_original', 'cod_viejo', 'articulo', 'cantidad']].head(15), 
                    height=300, use_container_width=True
                )
            with col2:
                st.markdown("#### Procesado")
                df_proc = pd.DataFrame(processed_data)
                st.dataframe(
                    df_proc[['linea', 'cod_viejo', 'articulo', 'cantidad']].head(15), 
                    height=300, use_container_width=True
                )
            
            st.divider()
            
            # Generar PDF
            picking_buffer = generate_pdf(processed_data, header_info)
            
            st.markdown("### 📄 Descargar PDF")
            
            if packing_start:
                picking_buffer.seek(0)
                merged_buffer, picking_pages, packing_pages = merge_with_packing(
                    picking_buffer, original_copy, packing_start
                )
                
                st.info(f"📋 PDF completo: {picking_pages} pág. picking + {packing_pages} pág. packing = **{picking_pages + packing_pages} páginas**")
                
                st.download_button(
                    "⬇️ Descargar PDF Completo (Picking + Packing)",
                    merged_buffer,
                    f"picking_{header_info.get('numero', 'procesado')}_completo.pdf",
                    "application/pdf",
                    type="primary",
                    use_container_width=True
                )
                
                # Opción de solo picking
                picking_buffer.seek(0)
                with st.expander("Descargar solo el Picking List"):
                    st.download_button(
                        "⬇️ Solo Picking List",
                        picking_buffer,
                        f"picking_{header_info.get('numero', 'procesado')}_ordenado.pdf",
                        "application/pdf"
                    )
            else:
                st.download_button(
                    "⬇️ Descargar PDF",
                    picking_buffer,
                    f"picking_{header_info.get('numero', 'procesado')}_ordenado.pdf",
                    "application/pdf",
                    type="primary",
                    use_container_width=True
                )


if __name__ == "__main__":
    main()