"""
Procesador de Picking List - Banchero Sanitarios
Ordena por código viejo y agrupa líneas duplicadas sumando cantidades.
Genera PDF con picking procesado + packing list original.
"""
import streamlit as st
import pdfplumber
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.enums import TA_CENTER
from pypdf import PdfReader, PdfWriter
from io import BytesIO
import re
from datetime import datetime

st.set_page_config(
    page_title="Picking List - Banchero Sanitarios",
    page_icon="📦",
    layout="wide"
)


def extract_picking_data(pdf_file):
    """Extrae datos del picking list y detecta inicio del packing list."""
    all_rows = []
    header_info = {}
    packing_start_page = None
    
    with pdfplumber.open(pdf_file) as pdf:
        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            
            # Detectar inicio del packing list (por cliente)
            if "Codigo Cliente" in text and "LN" in text and "Liberado" in text:
                packing_start_page = page_num
                break
            
            # Header info
            if page_num == 0:
                n_match = re.search(r'N[°º]:\s*(\d+)', text)
                if n_match:
                    header_info['numero'] = n_match.group(1)
                fecha_match = re.search(r'FECHA:\s*(\d{2}/\d{2}/\d{4})', text)
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
                
                # Saltar headers
                if line.upper().startswith(('PICKING LIST', 'COD ', 'N°:', 'FECHA:', 'HORA:', 'ESTADO:', 'PREPARO:', 'CONTROLO:')):
                    continue
                if 'PÁGINA' in line.upper() or 'COD VIEJO' in line.upper():
                    continue
                
                # Patrón principal
                match = re.search(
                    r'^(\d+)\s+([A-Z]{2}[A-Z0-9]+)\s+(.+?)\s+(\d+,\d{2})\s+(-?[\d.]+)\s+([A-Z]+)\s*$',
                    line
                )
                
                if not match:
                    continue
                
                linea = int(match.group(1))
                codigo = match.group(2)
                resto = match.group(3)
                cantidad = float(match.group(4).replace(',', '.'))
                stock = float(match.group(5).replace('.', ''))
                almacen = match.group(6)
                
                # Extraer cod_viejo
                cod_match = re.match(r'^([A-Z]{2}\d+[A-Z]?\d*)\s*(.*)$', resto)
                if cod_match:
                    cod_viejo = cod_match.group(1)
                    articulo = cod_match.group(2).strip()
                else:
                    cod_match2 = re.match(r'^([A-Z]{2}\d+[A-Z]?\d*)([A-Z][a-záéíóúñ\*].*)$', resto)
                    if cod_match2:
                        cod_viejo = cod_match2.group(1)
                        articulo = cod_match2.group(2)
                    else:
                        parts = resto.split(None, 1)
                        cod_viejo = parts[0] if parts else resto
                        articulo = parts[1] if len(parts) > 1 else ''
                
                all_rows.append({
                    'linea_original': linea,
                    'codigo': codigo,
                    'cod_viejo': cod_viejo,
                    'articulo': articulo.strip() or resto,
                    'cantidad': cantidad,
                    'stock': stock,
                    'almacen': almacen
                })
    
    return all_rows, header_info, packing_start_page


def process_picking_data(rows):
    """Agrupa por cod_viejo, suma cantidades, ordena."""
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
    """Genera PDF del picking list procesado."""
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1.5*cm,
        bottomMargin=1*cm
    )
    
    styles = getSampleStyleSheet()
    elements = []
    
    # Header
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontSize=16, alignment=TA_CENTER, spaceAfter=5)
    header_text = f"""
    <b>PICKING LIST N° {header_info.get('numero', '-')}</b><br/>
    <font size="10">Estado: {header_info.get('estado', 'COMPLETO')} | 
    Fecha: {header_info.get('fecha', datetime.now().strftime('%d/%m/%Y'))} | 
    Hora: {header_info.get('hora', datetime.now().strftime('%H:%M:%S'))}<br/>
    <i>Ordenado por Código Viejo - Duplicados consolidados</i></font>
    """
    elements.append(Paragraph(header_text, title_style))
    elements.append(Spacer(1, 0.3*cm))
    
    # Tabla
    table_data = [['#', 'CÓDIGO', 'COD VIEJO', 'ARTÍCULO', 'CANT', 'STOCK', 'ALM', '✓']]
    for row in data:
        articulo = str(row['articulo'])[:45]
        cant = row['cantidad']
        cant_str = f"{int(cant)}" if cant == int(cant) else f"{cant:.2f}"
        stock = row['stock']
        stock_str = f"{int(stock)}" if stock == int(stock) else f"{stock:.0f}"
        table_data.append([str(row['linea']), str(row['codigo']), str(row['cod_viejo']), 
                          articulo, cant_str, stock_str, str(row['almacen'])[:6], '☐'])
    
    col_widths = [0.8*cm, 3.5*cm, 2.5*cm, 10*cm, 1.3*cm, 1.5*cm, 1.5*cm, 0.8*cm]
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1B5E20')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('ALIGN', (0, 1), (0, -1), 'CENTER'),
        ('ALIGN', (4, 1), (5, -1), 'RIGHT'),
        ('ALIGN', (6, 1), (7, -1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
        ('TOPPADDING', (0, 1), (-1, -1), 3),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
    ]))
    elements.append(table)
    
    # Footer
    elements.append(Spacer(1, 0.5*cm))
    footer = Table([['PREPARO:', '_'*20, 'COMIENZO:', '_'*15], ['CONTROLO:', '_'*20, 'FINALIZADO:', '_'*15]],
                   colWidths=[2.5*cm, 5*cm, 2.5*cm, 5*cm])
    footer.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9)]))
    elements.append(footer)
    
    doc.build(elements)
    buffer.seek(0)
    return buffer


def merge_with_packing(picking_buffer, original_pdf, packing_start_page):
    """Combina picking list procesado con packing list original."""
    output_buffer = BytesIO()
    writer = PdfWriter()
    
    # 1. Agregar picking list procesado
    picking_reader = PdfReader(picking_buffer)
    for page in picking_reader.pages:
        writer.add_page(page)
    
    # 2. Agregar packing list original
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
            # Guardar copia del archivo para merge posterior
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
            
            # Stats
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Originales", len(rows))
            col2.metric("Consolidadas", len(processed_data))
            col3.metric("Duplicados", duplicados)
            if packing_start:
                col4.metric("Packing list", "✓ Detectado")
            else:
                col4.metric("Packing list", "No encontrado")
            
            # Mostrar duplicados
            if duplicados > 0:
                dupes = df_original[df_original.duplicated('cod_viejo', keep=False)]
                with st.expander("Ver duplicados consolidados"):
                    for cod in dupes['cod_viejo'].unique():
                        subset = df_original[df_original['cod_viejo'] == cod]
                        st.write(f"**{cod}**: {list(subset['cantidad'])} → **{sum(subset['cantidad'])}**")
            
            st.divider()
            
            # Preview
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("#### Original")
                st.dataframe(df_original[['linea_original', 'cod_viejo', 'articulo', 'cantidad']].head(15), height=300)
            with col2:
                st.markdown("#### Procesado")
                st.dataframe(pd.DataFrame(processed_data)[['linea', 'cod_viejo', 'articulo', 'cantidad']].head(15), height=300)
            
            st.divider()
            
            # Generar PDF picking
            picking_buffer = generate_pdf(processed_data, header_info)
            
            # Opciones de descarga
            st.markdown("### 📄 Descargar PDF")
            
            if packing_start:
                # Merge con packing list
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
                
                # También ofrecer solo el picking
                picking_buffer.seek(0)
                with st.expander("Descargar solo el Picking List"):
                    st.download_button(
                        "⬇️ Solo Picking List (sin packing)",
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
