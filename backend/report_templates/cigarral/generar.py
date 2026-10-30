#!/usr/bin/env python3
"""Genera el informe mensual del restaurante desde datos normalizados y roadmap.
   Uso: python generar.py --datos datos_ejemplo.json --roadmap roadmap.json --out .
   Las entradas de GSC/GBP/crawl han de normalizarse antes de generar; los
   análisis estratégicos están en `editorial`, revisables cada mes.
"""
import argparse, json, base64, math, html, os, re
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, select_autoescape

BASE=Path(__file__).resolve().parent
MONTHS=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre']

def fmt_num(n):
    if n is None:return 'Sin dato'
    return f'{n:,}'.replace(',','.') if isinstance(n,int) else str(n)
def fmt_pct(n):
    if n is None:return 'Sin dato'
    return f'{n:+.1f}%'.replace('.',',')
def share(n):
    if n is None:return 'Sin dato'
    return f'{n:.1f}%'.replace('.',',')
def pos(n):return 'Sin dato' if n is None else f'{n:.1f}'.replace('.',',')
def month_label(mon):
    year,month=map(int,mon.split('-'));return MONTHS[month-1].capitalize()+' '+str(year)
def shortmonth(mon):return MONTHS[int(mon[5:7])-1][:3].capitalize()
def blank(n):
    return '' if n is None else fmt_num(n)
def pctblank(n):
    return '' if n is None else fmt_pct(n)
def statuslabel(s):return {'previsto':'Prevista','hecho':'Realizada','curso':'En curso','bloqueado':'En espera','eliminado':'Eliminada'}.get(s,s)

def draw_chart(series,key='clics',unidad='clics'):
    """Responsive SVG with hover data; two independent scales/metrics."""
    data=sorted(series,key=lambda d:d['mes']);w,h=600,245;left,right,top,bottom=53,12,18,33
    plot_w=w-left-right;plot_h=h-top-bottom;mx=math.ceil(max(p[key] for p in data)/max(10,100 if key=='clics' else 2000))*max(10,100 if key=='clics' else 2000)
    def xx(i):return left+(i/max(1,len(data)-1))*plot_w
    def yy(v):return top+(1-v/mx)*plot_h
    pts=' '.join(f'{xx(i):.1f},{yy(p[key]):.1f}' for i,p in enumerate(data))
    svg=[f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Evolución mensual de {html.escape(unidad)} de la página del restaurante">']
    for i in range(5):
        val=mx*i/4;y=yy(val)
        svg += [f'<line class="gridline" x1="{left}" x2="{w-right}" y1="{y:.1f}" y2="{y:.1f}"/>',f'<text class="charttick" x="{left-9}" y="{y+3:.1f}" text-anchor="end">{fmt_num(int(val))}</text>']
    svg += [f'<polygon class="chartarea" points="{left},{yy(0):.1f} {pts} {xx(len(data)-1):.1f},{yy(0):.1f}"/>',f'<polyline class="chartline" points="{pts}"/>']
    visual=[]
    for i,row in enumerate(data):
        x=xx(i);y=yy(row[key]);name=month_label(row['mes']);visual.append({'nombre':name,'valor':row[key],'unidad':unidad})
        svg.append(f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3.6"><title>{html.escape(name)}: {fmt_num(row[key])} {unidad}</title></circle>')
        svg.append(f'<circle class="chartspot" data-i="{i}" tabindex="0" aria-label="{html.escape(name)}: {fmt_num(row[key])} {unidad}" cx="{x:.1f}" cy="{y:.1f}" r="12"/>')
        if i in (0,len(data)-1) or i%4==0:
            label=MONTHS[int(row['mes'][5:7])-1][:3]+' '+row['mes'][2:4]
            svg.append(f'<text class="charttick" x="{x:.1f}" y="{h-9}" text-anchor="middle">{label}</text>')
    svg.append('</svg>')
    return ''.join(svg),visual

TEXTOS_EJEMPLO={
    "resumen_fuente_cola": "Los valores señalados como ejemplo son simulados para mostrar el formato.",
    "aviso_etiqueta": "Informe de muestra:",
    "impresiones_grafico_nota": "Distribución mensual simulada",
    "reparto_nota": "Distribución por consultas simulada para ilustrar la presentación. En producción el porcentaje se calculará sobre los clics de las consultas clasificables y se indicará su cobertura.",
    "intencion_nota": "Datos ficticios de clasificación mensual. Los clics totales históricos de agosto y septiembre sí proceden de Search Console.",
    "grupos_nota_etiqueta": "Datos simulados:",
    "grupos_nota": "todas las cifras mensuales de esta tabla son ejemplos para comprobar su diseño. Las consultas proceden del histórico real de Search Console y sus datos acumulados se conservan en el archivo de trabajo.",
    "ficha_nota": "Datos de mayo a octubre de 2026. Son acciones de la ficha, no contactos atendidos ni reservas confirmadas.",
    "grupos_acumulado_nota": "Search Console · datos acumulados del 21 de junio de 2025 al 20 de octubre de 2026. El seguimiento mensual se muestra con detalle en \"Grupos y celebraciones\".",
    "ficha_grupos_nota": "Ficha del restaurante · mayo a octubre de 2026 (octubre incompleto). Son cifras generales de la ficha, no acciones identificadas como consultas de grupos.",
    "plan_nota": "Los estados de octubre en este ejemplo son ficticios para mostrar el funcionamiento del seguimiento. El estudio original no confirma todavía ninguna actuación ejecutada.",
    "fuentes_resumen": "Para interpretar correctamente el informe distinguimos entre cifras verificadas y datos incluidos solo para mostrar cómo funcionará la plantilla.",
    "fuentes_gsc": "datos reales de clics mensuales a /restaurante/ de julio de 2025 a septiembre de 2026. Las impresiones del trimestre julio-septiembre están contrastadas en conjunto, pero su distribución mensual en este ejemplo es simulada.",
    "fuentes_marca": "el histórico real muestra 3.321 clics en consultas identificables, de los cuales unos 3.192 corresponden a búsquedas con marca. El reparto por septiembre y agosto que aparece en el gráfico circular se ha simulado para ilustrar cómo se calcularán los porcentajes mensuales.",
    "fuentes_grupos": "las consultas y sus totales históricos proceden del estudio original. Las cifras comparativas de agosto y septiembre de la tabla son ficticias.",
    "fuentes_ficha": "datos reales del perfil del restaurante de mayo a octubre de 2026, con octubre incompleto. No son datos específicos de septiembre.",
    "ficha_resumen_cola": "Estos datos históricos no equivalen a reservas confirmadas.",
    "ficha_vistas_pie": "Mayo a octubre de 2026, octubre parcial",
    "web_clics_pie": "frente al mismo mes de 2025 · dato real",
    "web_impresiones_pie": "interanual · cifra mensual ficticia",
    "clics_grafico_nota": "Serie histórica real",
    "web_nota": "Clics: personas que acceden a la web desde los resultados de Google. Impresiones: veces que la página aparece en resultados, aunque nadie haga clic. En esta muestra, solo la serie mensual de clics es real.",
    "paginas_nota": "Clics desde Google a cada página de la web. En el ejemplo no se muestran datos.",
    "ga_pendiente_etiqueta": "Pendiente:",
    "ga_nota": "estos datos se incorporarán cuando tengamos acceso a Google Analytics.",
    "ga_periodos": "Comparación con el mes anterior y con el mismo mes del año anterior.",
    "fuentes_paginas": "clics desde Google a cada página de la web, según Search Console.",
    "fuentes_ga": "adquisición de tráfico y de usuarios por canal. Pendiente de acceso.",
    "fuentes_trabajo": "las incidencias técnicas se identificaron en la auditoría. Los estados de octubre del plan son ejemplos ficticios, no actuaciones ya realizadas. Los datos operativos definitivos deberán validarse antes de remitirlo al restaurante."
}
# Textos de las notas de cada sección. En el ejemplo se usan los de arriba; en un
# informe real (es_demo=false) hay que darlos todos en datos['textos'], para que
# ningún aviso de "simulado" o periodo del ejemplo se cuele en un informe real.

def textos(data):
    propios=data.get('textos') or {}
    if data['informe'].get('es_demo',False):
        return {**TEXTOS_EJEMPLO,**propios}
    faltan=[k for k in TEXTOS_EJEMPLO if not propios.get(k)]
    if faltan: raise ValueError('Informe real: faltan textos en datos["textos"]: '+', '.join(faltan))
    return propios

def normalizar_grupos(data):
    """Admite claves neutras (imp_anterior, imp_actual, clics_actual) además de las del ejemplo."""
    for q in (data.get('grupos') or {}).get('consultas',[]):
        if 'imp_actual' in q: q['sep_imp']=q['imp_actual']
        if 'imp_anterior' in q: q['ago_imp']=q['imp_anterior']
        if 'clics_actual' in q: q['sep_clics']=q['clics_actual']
        a,b=q.get('sep_imp'),q.get('ago_imp')
        q['evol']=None if not isinstance(a,(int,float)) or not b else 100*(a-b)/b
        if q.get('evol') is None and isinstance(a,(int,float)) and b==0:
            q['evol_txt']='Nueva' if a>0 else 'Sin cambios'

CANALES_GA=['Búsqueda orgánica','Directo','Referencia','Social orgánico','Búsqueda de pago','Sin asignar']

def preparar_paginas_y_ga(data):
    """Páginas más visitadas (Search Console) y adquisición de Google Analytics.
    Sin datos de Analytics, las tablas salen con los canales y las celdas en blanco."""
    pct=lambda a,b:None if a is None or not b else 100*(a-b)/b
    paginas=(data.get('gsc') or {}).get('paginas') or []
    for p in paginas:
        p['var_mes']=pct(p.get('clics'),p.get('clics_anterior'))
        p['var_ano']=pct(p.get('clics'),p.get('clics_ano_anterior'))
        if p['var_mes'] is None and p.get('clics_anterior')==0 and p.get('clics'): p['var_mes_txt']='Nueva'
        if p['var_ano'] is None and p.get('clics_ano_anterior')==0 and p.get('clics'): p['var_ano_txt']='Nueva'
    ga=data.get('ga4') or {}
    for clave,metrica in (('trafico','sesiones'),('usuarios','usuarios_nuevos')):
        filas=ga.get(clave) or [{'canal':c} for c in CANALES_GA]
        for r in filas:
            r['var_mes']=pct(r.get(metrica),r.get(metrica+'_mes_anterior'))
            r['var_ano']=pct(r.get(metrica),r.get(metrica+'_ano_anterior'))
        ga[clave]=filas
    ga['disponible']=bool(ga.get('disponible'))
    return paginas,ga

def validate(data,roadmap):
    g=data['gsc']; intent=g['intencion_mensual']['filas']; example=data['informe'].get('es_demo',False)
    clicks=sum(z['clics'] for z in intent)
    if clicks>g['clics_mes']: raise ValueError('Los clics clasificados no pueden superar los totales de Search Console.')
    if not example and clicks<g['clics_mes']:
        # Valid for real exports: Google Search Console may anonymize or omit queries.
        # The donut reports only the share of classified clicks, never percentages of all clicks.
        pass
    statuses={'previsto','hecho','curso','bloqueado','eliminado'}
    for month in roadmap['meses'].values():
        for task in month['tareas']:
            if task['estado'] not in statuses:raise ValueError('Estado inválido: '+task['estado'])
            if task['estado']=='hecho' and not example and not task.get('evidencia'):
                raise ValueError('Un trabajo realizado requiere evidencia interna: '+task['nombre'])
            if any('hora' in key.lower() for key in task):raise ValueError('No se admiten horas en los datos públicos.')

def normalize_quotes(obj):
    """Conserva la preferencia editorial: comillas dobles, nunca angulares."""
    if isinstance(obj, str): return obj.replace('\u00ab', '"').replace('\u00bb', '"')
    if isinstance(obj, list): return [normalize_quotes(v) for v in obj]
    if isinstance(obj, dict): return {k: normalize_quotes(v) for k,v in obj.items()}
    return obj

def render(data,roadmap,output):
    data=normalize_quotes(data)
    normalizar_grupos(data)
    roadmap=normalize_quotes(roadmap)
    output.mkdir(parents=True,exist_ok=True)
    validate(data,roadmap)
    paginas,ga4=preparar_paginas_y_ga(data)
    env=Environment(loader=FileSystemLoader(str(BASE)),autoescape=select_autoescape(['html']),trim_blocks=True,lstrip_blocks=True)
    env.filters.update(blank=blank,pctblank=pctblank,num=fmt_num,pct=fmt_pct,pos=pos,monthlabel=month_label,shortmonth=shortmonth,statuslabel=statuslabel,share=share)
    tpl=env.get_template('informe.html.j2')
    g=data['gsc']; chartsvg,chartdata=draw_chart(g['meses_serie'],'clics','clics'); impressionchartsvg,impressionchartdata=draw_chart(g['meses_serie'],'impresiones','impresiones')
    pct=lambda a,b:None if b is None or b==0 or a is None else 100*(a-b)/b
    allclicks=g['clics_totales_landing'];count=g['consultas_visibles_clics'];
    period=month_label(data['informe']['mes_datos'])
    # Los KPIs de portada se obtienen de las mismas fuentes que el resto del informe.
    # En el ejemplo se utilizan las cifras mensuales simuladas identificadas en el JSON.
    intent_rows=g['intencion_mensual']['filas']
    classified=sum(row['clics'] for row in intent_rows)
    summary_period=period
    grp=data.get('grupos',{})
    if data['informe'].get('es_demo',False):
        commercial=[r for r in grp.get('consultas',[]) if r.get('intencion') in ('Eventos y grupos','Celebraciones')]
        gp_now=sum(r['sep_imp'] for r in commercial) if commercial and all(isinstance(r.get('sep_imp'),int) for r in commercial) else None
        gp_prev=sum(r['ago_imp'] for r in commercial) if commercial and all(isinstance(r.get('ago_imp'),int) for r in commercial) else None
        gp_clicks=sum(r['sep_clics'] for r in commercial) if commercial and all(isinstance(r.get('sep_clics'),int) for r in commercial) else None
    else:
        # Al importar datos mensuales reales, suministrar este bloque normalizado.
        commercial=grp.get('resumen_mensual',{})
        gp_now=commercial.get('impresiones');gp_prev=commercial.get('impresiones_mes_anterior');gp_clicks=commercial.get('clics')
    def diff(a,b):
        value=pct(a,b)
        return 'sin comparativa' if value is None else fmt_pct(value)
    def ratio(part,total):
        return share(100*part/total) if isinstance(part,(int,float)) and total else 'Sin dato'
    def demo(txt):
        return (txt+' · Ejemplo') if data['informe'].get('es_demo',False) else txt
    maps_period=data['google'].get('periodo','periodo no facilitado')
    # Iconos SVG locales y estables. Siempre decorativos, asociados al KPI correspondiente.
    ICON_PATHS = {
        'click': '<path d="M4 3l7.5 17 2.2-6.3L20 11z"/><path d="M15 15l4 5"/>',
        'impression': '<path d="M2.5 12s3.4-6.5 9.5-6.5S21.5 12 21.5 12s-3.4 6.5-9.5 6.5S2.5 12 2.5 12z"/><circle cx="12" cy="12" r="2.7"/>',
        'brand': '<path d="M11 3H5a2 2 0 0 0-2 2v6l10 10 8-8L11 3z"/><circle cx="7.5" cy="7.5" r="1"/>',
        'search': '<circle cx="10.8" cy="10.8" r="6.5"/><path d="m16 16 5 5"/>',
        'groups': '<circle cx="9" cy="8.5" r="2.5"/><path d="M3 20v-2a5.5 5.5 0 0 1 11 0v2M17 5.5a3 3 0 0 1 0 6M17.5 14.5a5 5 0 0 1 3.5 4.7"/>',
        'profile': '<path d="M20 10c0 5.5-8 11-8 11S4 15.5 4 10a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="2.5"/>',
        'phone': '<path d="M7 3 4.5 5.5a3 3 0 0 0-.7 3c2 6 6.7 10.7 12.7 12.7a3 3 0 0 0 3-.7L22 18l-5.6-4-2.4 2a14 14 0 0 1-6-6l2-2.4z"/>',
        'route': '<path d="M4 5h3M7 5a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 21a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7 5v4a4 4 0 0 0 4 4h2a4 4 0 0 1 4 4"/>',
    }
    def metric(label,val,detail,footer,icon):
        svg = '<svg class="executive-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'+ICON_PATHS[icon]+'</svg>'
        return {'nombre':label,'valor':fmt_num(val),'detalle':detail,'pie':footer,'icon_svg':svg}
    kpi_groups=[
       {'titulo':'VISIBILIDAD EN GOOGLE · '+summary_period,'metricas':[
          metric('Clics orgánicos',g.get('clics_mes'),'Visitas desde Google',diff(g.get('clics_mes'),g.get('clics_mes_anterior'))+' vs. mes anterior · '+diff(g.get('clics_mes'),g.get('clics_mismo_mes_ano_anterior'))+' interanual','click'),
          metric('Impresiones orgánicas',g.get('impresiones_mes'),'Veces que se muestra la página',demo(diff(g.get('impresiones_mes'),g.get('impresiones_mes_anterior'))+' vs. mes anterior'),'impression'),
          metric('Clics con la marca',intent_rows[0].get('clics'),ratio(intent_rows[0].get('clics'),classified)+' de clics clasificados',demo(diff(intent_rows[0].get('clics'),intent_rows[0].get('prev_clics'))+' vs. mes anterior'),'brand'),
          metric('Clics sin la marca',intent_rows[1].get('clics'),ratio(intent_rows[1].get('clics'),classified)+' de clics clasificados',demo(diff(intent_rows[1].get('clics'),intent_rows[1].get('prev_clics'))+' vs. mes anterior'),'search'),
       ]},
       {'titulo':'OPORTUNIDAD COMERCIAL Y VISIBILIDAD LOCAL','metricas':[
          metric('Grupos y eventos',gp_now,'Impresiones · '+fmt_num(gp_clicks)+(' clic' if gp_clicks==1 else ' clics'),demo(diff(gp_now,gp_prev)+' vs. mes anterior'),'groups'),
          metric('Personas que vieron la ficha',data['google'].get('vistas_perfil'),'Perfil del restaurante',maps_period,'profile'),
          metric('Clics para llamar',data['google'].get('clics_llamada'),'Pulsaciones en la ficha',maps_period,'phone'),
          metric('Solicitudes de cómo llegar',data['google'].get('indicaciones'),'Consultas de la ruta',maps_period,'route'),
       ]},
    ]
    base={**data,'info':data['informe'],'mes_datos':period,'roadmap':roadmap,'months':sorted(roadmap['meses']),
       'css':(BASE/'estilos.css').read_text(), 'logo':(BASE/'logo_oficial_embebido.txt').read_text().strip(),
       'chartsvg':chartsvg,'chartdata':chartdata,'impressionchartsvg':impressionchartsvg,'impressionchartdata':impressionchartdata,
       'impressions_yoy':pct(g['impresiones_mes'],g['impresiones_mismo_mes_ano_anterior']), 'yoy':pct(g['clics_mes'],g['clics_mismo_mes_ano_anterior']),
       'trimester':pct(g['clics_trimestre_actual'],g['clics_trimestre_anterior']),
       'share_all_brand':round(g['marca_visibles_clics']/allclicks*100,3),
       'share_all_generic':round(g['no_marca_visibles_clics']/allclicks*100,3),
       'share_all_unknown':round(g['ocultos_clics']/allclicks*100,3),
       'brand_visible_pct':g['marca_visibles_clics']/count*100,
       'brand_click_pct':100*g['intencion_mensual']['filas'][0]['clics']/max(1,sum(q['clics'] for q in g['intencion_mensual']['filas'])),
       'generic_click_pct':100*g['intencion_mensual']['filas'][1]['clics']/max(1,sum(q['clics'] for q in g['intencion_mensual']['filas'])),
       'intent':{'marca':g['intencion_mensual']['filas'][0],'generica':g['intencion_mensual']['filas'][1],
          'rows':[{**q,'change':pct(q['clics'],q['prev_clics']),'descripcion':('Por el nombre del establecimiento' if i==0 else 'Restaurantes, vistas, eventos y similares')} for i,q in enumerate(g['intencion_mensual']['filas'])]},
       'preferred_month':data['informe'].get('mes_roadmap_preferido'),
       'first_period':month_label(g['meses_serie'][0]['mes']),'last_period':month_label(g['meses_serie'][-1]['mes']),
       'fallback_month':'2026-10',
       'kpi_groups':kpi_groups,
       't':textos(data),
       'paginas':paginas,'ga4':ga4,
       'lbl_interanual':(lambda m:MONTHS[int(m[5:7])-1].capitalize()+' '+str(int(m[:4])-1))(g['intencion_mensual'].get('mes_actual') or data['informe']['mes_datos']),
       'lbl_actual':month_label(g['intencion_mensual'].get('mes_actual') or data['informe']['mes_datos']).split(' ')[0],
       'lbl_anterior':month_label(g['intencion_mensual']['mes_anterior']).split(' ')[0],
    }
    # Nombre fijo: Cigarral_Seguimiento_Mensual_AAAA-Mes (p. ej. Cigarral_Seguimiento_Mensual_2026-Octubre.pdf)
    _m=data['informe']['mes_datos']
    stem='Cigarral_Seguimiento_Mensual_'+('Ejemplo_' if data['informe'].get('es_demo') else '')+_m[:4]+'-'+MONTHS[int(_m[5:7])-1].capitalize()
    base['pdf_filename']=stem+'.pdf'
    htmlfile=output/(stem+'.html'); pdffile=output/(stem+'.pdf')
    base['pdf_blob']=''
    page_html=tpl.render(**base)
    htmlfile.write_text(page_html,encoding='utf-8')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        exe=os.environ.get('CHROMIUM_PATH') or ('/usr/bin/chromium' if Path('/usr/bin/chromium').exists() else None)  # si no, el Chromium de Playwright
        browser=p.chromium.launch(executable_path=exe,headless=True,args=['--no-sandbox','--disable-gpu'])
        page=browser.new_page(viewport={'width':1440,'height':900})
        # The Agency: el informe es autónomo (logo y PDF en base64); cualquier petición de red se corta.
        page.route(re.compile(r'^(https?|ftp|file|wss?):'),lambda route:route.abort())
        page.set_content(page_html,wait_until='load',timeout=60000);page.emulate_media(media='print')
        page.pdf(path=str(pdffile),format='A4',print_background=True,prefer_css_page_size=True,display_header_footer=False)
        browser.close()
    base['pdf_blob']=base64.b64encode(pdffile.read_bytes()).decode('ascii')
    htmlfile.write_text(tpl.render(**base),encoding='utf-8')
    return htmlfile,pdffile

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--datos',default=str(BASE/'datos_ejemplo.json'));ap.add_argument('--roadmap',default=str(BASE/'roadmap.json'));ap.add_argument('--out',default=str(BASE));args=ap.parse_args()
    a,b=render(json.loads(Path(args.datos).read_text()),json.loads(Path(args.roadmap).read_text()),Path(args.out));print('HTML:',a,'\nPDF:',b)
if __name__=='__main__':main()
