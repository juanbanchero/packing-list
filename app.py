"""
Procesador de Picking List - Banchero Sanitarios
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


def split_cod_viejo_articulo(resto):
    """
    Separa código viejo del artículo.
    El código viejo es alfanumérico y termina cuando empieza una palabra real
    (Mayúscula seguida de minúscula como Tee, Transición, Depósito, etc.)
    """
    if not resto:
        return '', ''
    
    resto = resto.strip()
    
    # Buscar Mayúscula + minúscula (inicio de palabra real)
    match = re.search(r'[A-Z][a-záéíóúñ]', resto)
    if match:
        pos = match.start()
        if pos > 0:
            cod_viejo = resto[:pos].strip()
            articulo = resto[pos:].strip()
            cod_viejo = cod_viejo.rstrip('* ').strip()
            if '**' in resto[:pos]:
                cod_viejo = cod_viejo + ' **'
            return cod_viejo, articulo
    
    # Buscar espacio + comillas
    match = re.search(r'\s+"', resto)
    if match:
        pos = match.start()
        cod_viejo = resto[:pos].strip()
        articulo = resto[pos:].strip().lstrip('"').strip()
        return cod_viejo, articulo
    
    # Buscar palabras MAYÚSCULAS conocidas
    palabras_mayus = ['CODO', 'TUBO', 'FLEX', 'CURVA', 'GRAMPA', 'GRASA', 'SELLADOR', 
                      'DECAPANTE', 'TEFLON', 'CAÑAMO', 'RECEPTACULO', 'RECEPT', 'CABINA',
                      'PILETA', 'RAMAL', 'CUPLA', 'CANILLA', 'LLAVE', 'REG.', 'CONJ.']
    resto_upper = resto.upper()
    for palabra in palabras_mayus:
        idx = resto_upper.find(' ' + palabra)
        if idx >= 0:
            cod_viejo = resto[:idx].strip()
            articulo = resto[idx+1:].strip()
            return cod_viejo, articulo
    
    # Último recurso
    parts = resto.split(' ', 1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    
    return resto, ''


def extract_picking_data(pdf_file):
    all_rows = []
    header_info = {}
    packing_start_page = None
    
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            
            # Detectar packing list (tiene "Codigo Cliente" y "LN")
            if "Codigo Cliente" in text and "LN" in text:
                packing_start_page = page_num
                break
            
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
                estado_match = re.search(r'Estado:\s*(\w+)', text)
                if estado_match:
                    header_info['estado'] = estado_match.group(1)
            
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                
                if line.upper().startswith(('PICKING LIST', 'COD ', 'N°:', 'FECHA:', 'HORA:', 'ESTADO:', 'PREPARO:', 'CONTROLO:')):
                    continue
                if 'PÁGINA' in line.upper() or 'COD VIEJO' in line.upper() or 'ARTICULO' in line.upper():
                    continue
                
                # Patrón flexible: soporta cantidad entera (12) o con decimales (12,00)
                # Soporta stock con punto de miles (3.228) o simple (78)
                match = re.search(
                    r'^(\d+)\s+([A-Z]{2}[A-Z0-9]+)\s+(.+?)\s+(\d+(?:,\d{2})?)\s+(-?[\d.,]+)\s+([A-Z]+)\s*$',
                    line
                )
                
                if not match:
                    continue
                
                linea = int(match.group(1))
                codigo = match.group(2)
                resto = match.group(3)
                
                # Parsear cantidad (puede ser "12" o "12,00")
                cantidad_str = match.group(4).replace(',', '.')
                cantidad = float(cantidad_str)
                
                # Parsear stock (puede ser "78", "3.228", "-5")
                stock_str = match.group(5).replace('.', '').replace(',', '.')
                stock = float(stock_str)
                
                almacen = match.group(6)
                
                cod_viejo, articulo = split_cod_viejo_articulo(resto)
                if not articulo:
                    articulo = resto
                
                all_rows.append({
                    'linea_original': linea,
                    'codigo': codigo,
                    'cod_viejo': cod_viejo,
                    'articulo': articulo,
                    'cantidad': cantidad,
                    'stock': stock,
                    'almacen': almacen
                })
    
    return all_rows, header_info, packing_start_page


def process_picking_data(rows):
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
    
    # Estilos para celdas con wrap automático - 10pt
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=10, leading=11, wordWrap='CJK')
    cod_style = ParagraphStyle('CodStyle', parent=styles['Normal'], fontSize=10, leading=11)
    
    title_style = ParagraphStyle(
        'Title', 
        parent=styles['Heading1'], 
        fontSize=12, 
        alignment=TA_CENTER, 
        spaceAfter=3
    )
    
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
            '',
            ''
        ])
    
    # Anchos optimizados para A4 vertical con 10pt
    col_widths = [0.6*cm, 2.4*cm, 12.4*cm, 1.1*cm, 1*cm, 1.4*cm, 0.8*cm]
    
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    table.setStyle(TableStyle([
        # Header 10pt
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B5E20')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 4),
        ('TOPPADDING', (0, 0), (-1, 0), 4),
        
        # Body 10pt
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
        
        # Columna REAL amarilla
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
    output_buffer = BytesIO()
    writer = PdfWriter()
    
    picking_reader = PdfReader(picking_buffer)
    for page in picking_reader.pages:
        writer.add_page(page)
    
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
            uploaded_file.seek(0)
            original_copy = BytesIO(uploaded_file.read())
            uploaded_file.seek(0)
            
            rows, header_info, packing_start = extract_picking_data(uploaded_file)
            
            if not rows:
                st.error("No se pudieron extraer datos. Verificá que sea un picking list válido.")
                return
            
            st.success(f"✅ {len(rows)} líneas extraídas del picking list")
            
            processed_data = process_picking_data(rows)
            df_original = pd.DataFrame(rows)
            duplicados = len(rows) - len(processed_data)
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Originales", len(rows))
            col2.metric("Consolidadas", len(processed_data))
            col3.metric("Duplicados", duplicados)
            if packing_start:
                col4.metric("Packing list", "✓ Detectado")
            else:
                col4.metric("Packing list", "No encontrado")
            
            if duplicados > 0:
                dupes = df_original[df_original.duplicated('cod_viejo', keep=False)]
                with st.expander("Ver duplicados consolidados"):
                    for cod in dupes['cod_viejo'].unique():
                        subset = df_original[df_original['cod_viejo'] == cod]
                        st.write(f"**{cod}**: {list(subset['cantidad'])} → **{sum(subset['cantidad'])}**")
            
            st.divider()
            
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