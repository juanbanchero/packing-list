# 📦 Procesador de Picking List - Banchero Sanitarios

Aplicación web para procesar picking lists en PDF:
- **Ordena** las líneas por código viejo
- **Consolida** líneas duplicadas sumando cantidades
- **Genera** un nuevo PDF limpio y ordenado

## 🚀 Deploy rápido en Streamlit Cloud (GRATIS - 5 minutos)

### Paso 1: Subir a GitHub
1. Creá un repositorio nuevo en GitHub (puede ser privado)
2. Subí estos archivos:
   - `app.py`
   - `requirements.txt`

### Paso 2: Deploy en Streamlit Cloud
1. Andá a [share.streamlit.io](https://share.streamlit.io)
2. Logueate con tu cuenta de GitHub
3. Click en "New app"
4. Seleccioná tu repo y el archivo `app.py`
5. Click en "Deploy"

¡Listo! En 2-3 minutos tenés la app corriendo.

## 💻 Correr localmente

```bash
# Instalar dependencias
pip install -r requirements.txt

# Correr la app
streamlit run app.py
```

Se abre automáticamente en http://localhost:8501

## 🔧 Cómo funciona

1. **Extracción**: Lee el PDF con `pdfplumber` y extrae las tablas del picking list
2. **Filtrado**: Solo procesa hasta encontrar "PREPARO:" (ignora la packing list)
3. **Consolidación**: Agrupa por código viejo y suma las cantidades
4. **Ordenamiento**: Ordena alfabéticamente por código viejo
5. **Generación**: Crea un nuevo PDF con `reportlab`

## 📋 Formato del PDF de entrada

El picking list debe tener estas columnas:
- Línea (número)
- Código
- Código Viejo
- Artículo
- Cantidad
- Stock
- Almacén
- Listo (checkbox)

## 🐛 Troubleshooting

Si el PDF no se procesa correctamente:
1. Verificá que sea un picking list de Banchero Sanitarios
2. Asegurate que tenga el formato estándar de columnas
3. El PDF no debe estar escaneado (necesita tener texto seleccionable)

## 📝 Notas

- La packing list (separada por cliente) se ignora automáticamente
- Los artículos muy largos se truncan a 50 caracteres en el PDF de salida
- El stock se toma del primer registro cuando hay duplicados
