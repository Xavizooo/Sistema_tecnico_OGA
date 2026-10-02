"""Autorización central: se aplica en servidor y en navegación."""
from flask import abort, g, jsonify, request
from auth_store import ROLE_ADMIN, ROLE_CHIEF

MODULES = {
    'proyectos': 'Seguimiento de Proyectos', 'oportunidades': 'Proyectos',
    'clientes': 'Clientes', 'industria': 'Datos', 'rq': 'Generador de RQ',
    'planos': 'Revisor de Planos', 'biblioteca': 'Biblioteca',
    'capacitaciones': 'Capacitaciones', 'asistente': 'Asistente OGA',
}
RQ_ENDPOINTS = {'cargar','upload_inventor','upload_b1','upload_lge','upload_equipment_inventor',
'remove_lge_row','process_route','rq','rq_date','externos_add','externos_remove','load_mov','load_rq',
'lm','repuestos','valor','factory','factory_new','factory_reload','factory_replace','factory_download',
'calendario','calendario_config','holiday_add','holiday_delete','historico','archive','history_recover',
'history_delete','new_list','export_file','export_rq_category','export_all','backups','backup_create',
'backup_recover','backup_delete','autosave_checkpoint'}

def module_for(endpoint):
    endpoint = endpoint or ''
    prefixes = {'proyectos_diseno.':'proyectos','oportunidades.':'oportunidades',
    'clientes.':'clientes','industria.':'industria','planos.':'planos','biblioteca.':'biblioteca',
    'capacitaciones.':'capacitaciones','asistente_oga.':'asistente'}
    for prefix, module in prefixes.items():
        if endpoint.startswith(prefix): return module
    if endpoint == 'proyectos_diseno_page': return 'proyectos'
    if endpoint in RQ_ENDPOINTS: return 'rq'
    return None

def allowed_modules(user=None):
    user = user or getattr(g, 'current_user', None) or {}
    if user.get('role') in {ROLE_ADMIN, ROLE_CHIEF}: return set(MODULES)
    from reportes.db import get_profile
    profile = get_profile(user.get('id',''))
    return set(profile.get('modules', [])) if profile else set()

def can_access(module):
    return module == 'reportes' or (module=='equipo' and bool((getattr(g,'current_user',None) or {}).get('is_admin') or (getattr(g,'current_user',None) or {}).get('is_chief'))) or module in allowed_modules()

def enforce_permissions():
    user = getattr(g, 'current_user', None)
    if not user: return
    endpoint = request.endpoint or ''
    module = module_for(endpoint)
    forbidden = module is not None and not can_access(module)
    # Los diseñadores no administran catálogos compartidos ni el tablero del jefe.
    if user.get('role') not in {ROLE_ADMIN, ROLE_CHIEF} and request.method not in {'GET','HEAD','OPTIONS'}:
        if module in {'proyectos','oportunidades','clientes','industria','biblioteca'} and endpoint not in {'biblioteca.buscar_referencia'}:
            forbidden = True
        if endpoint in {'factory_new','factory_reload','factory_replace','calendario_config','holiday_add','holiday_delete'}:
            forbidden = True
    if forbidden:
        if request.is_json or '/api/' in request.path:
            return jsonify(ok=False, error='No tiene permiso para esta operación.', message='No tiene permiso para esta operación.'), 403
        abort(403, description='Su perfil no tiene permiso para esta operación. Consulte al Jefe de Diseño.')

def navigation():
    groups = [
      ('reportes','Jornada y reportes', [('reportes.index','Mis reportes',{}),('reportes.tasks','Mis asignaciones',{})]),
      ('proyectos',MODULES['proyectos'], [('proyectos_diseno.index','Tablero',{'view':'dashboard'}),('proyectos_diseno.index','Proyectos',{'view':'projects'}),('proyectos_diseno.index','Histórico',{'view':'history'})]),
      ('oportunidades',MODULES['oportunidades'], [('oportunidades.index','Lista de proyectos',{}),('industria.industria_index','Datos',{})]),
      ('clientes','Clientes',[('clientes.index','Directorio de clientes',{})]),
      ('rq',MODULES['rq'], [(e,l,{}) for e,l in [('cargar','Cargar listas'),('factory','Lista Maestra'),('lm','Lista de materiales'),('rq','Requisiciones'),('repuestos','Repuestos'),('valor','Valor del proyecto'),('calendario','Calendario'),('historico','Histórico'),('backups','Copias de seguridad')]]),
      ('planos',MODULES['planos'], [('planos.planos_home','Revisión y distribución',{})]),
      ('biblioteca','Biblioteca',[('biblioteca.equipos','Biblioteca de equipos',{}),('biblioteca.buscador','Buscador de referencias',{}),('biblioteca.costos','Costos',{})]),
      ('capacitaciones','Capacitaciones',[('capacitaciones.index','Videos y capacitaciones',{})]),
    ]
    user = getattr(g,'current_user',None) or {}
    if user.get('is_chief'):
        groups[0][2][:]=[('reportes.dashboard','Tablero del equipo',{}),('reportes.tasks','Asignar tareas',{})]
    if user.get('is_admin') or user.get('is_chief'):
        if not user.get('is_chief'):
            groups[0][2].extend([('reportes.dashboard','Tablero del equipo',{}),('reportes.tasks','Trabajo y actividades',{})])
        groups[1][2].extend([('proyectos_diseno.index',l,{'view':v}) for v,l in [('activities','Actividades'),('equipment','Equipos'),('additionals','Adicionales'),('holidays','Festivos')]])
    if user.get('is_admin') or user.get('is_chief'):
        groups.insert(0,('equipo','Equipo de Diseño',[('reportes.team','Personal, horarios y accesos',{})]))
    result = []
    for module, label, links in groups:
        # Industria comparte el grupo de navegación, conserva su permiso propio.
        if module == 'oportunidades':
            links = [link for link in links if can_access(module_for(link[0]))]
            if not links:
                continue
        elif not can_access(module):
            continue
        result.append({'module': module, 'label': label, 'links': links})
    return result
