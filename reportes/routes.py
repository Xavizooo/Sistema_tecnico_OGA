from __future__ import annotations
from datetime import timedelta
from functools import wraps
from io import StringIO
import csv
import json
import uuid
from flask import Blueprint, abort, flash, g, redirect, render_template, request, Response, url_for
from auth_store import ROLE_ADMIN, ROLE_CHIEF, ROLE_COLLABORATOR, create_user, get_user_by_id, list_users, audit_event, reset_password, set_user_status, unlock_user
from permisos import MODULES
from . import db

bp=Blueprint('reportes',__name__,url_prefix='/reportes')

def manager_required(view):
    @wraps(view)
    def wrapped(*args,**kwargs):
        if not (g.current_user.get('is_admin') or g.current_user.get('is_chief')): abort(403)
        return view(*args,**kwargs)
    return wrapped

def _audit(action,detail):
    audit_event(action,'REPORTES',detail,'OK',g.current_user,request.remote_addr or '')
    g.audit_logged=True

def _users():
    actor=g.current_user; rows=[]
    for user in list_users():
        if user['role']!=ROLE_COLLABORATOR: continue
        profile=db.get_profile(user['id'])
        if db.can_manage(actor,profile): rows.append({**user,'profile':profile})
    return rows

def _configured_users(): return [u for u in _users() if u['profile']]

def _range():
    try:
        start=db.parse_day(request.args.get('desde') or db.today().isoformat())
        end=db.parse_day(request.args.get('hasta') or start.isoformat())
        if end<start or (end-start).days>30 or end>db.today(): raise ValueError('Seleccione hasta 31 días, sin fechas futuras.')
        return start,end
    except ValueError as e: abort(400,description=str(e))

def _render(template,**context):
    return render_template(template,reportes_page=True,admin_page=True,modules=MODULES,
      today=db.today().isoformat(),time_label=db.time_label,**context)

@bp.get('/')
def index():
    day=db.today()
    if request.args.get('fecha'):
        try:
            day=db.parse_day(request.args['fecha'])
            if day>db.today(): raise ValueError('No puede consultar una jornada futura.')
        except ValueError as e: abort(400,description=str(e))
    user=g.current_user
    db.sync_project_activities()
    return _render('reportes/mis_reportes.html',profile=db.get_profile(user['id']),
      summary=db.day_summary(user['id'],day),selected_day=day.isoformat(),
      reports=db.list_reports([user['id']],day,day),assignments=db.assignments([user['id']],day))

@bp.post('/enviar')
def submit():
    try:
        db.sync_project_activities()
        report_id=db.submit_report(request.form,g.current_user)
        _audit('ENVIAR REPORTE',report_id)
        flash('Reporte enviado al Jefe de Diseño.','ok')
    except ValueError as e: flash(str(e),'error')
    return redirect(url_for('reportes.index',fecha=request.form.get('day') or db.today().isoformat()))

@bp.get('/equipo')
@manager_required
def team():
    from proyectos_diseno.routes import storage
    users=_users(); selected=None
    user_id=request.args.get('usuario','')
    if user_id:
        selected=next((u for u in users if u['id']==user_id),None)
        if not selected: abort(403)
    board=storage.read('designers')
    selected_designer=request.args.get('disenador','')
    board_designer=next((d for d in board if d['id']==selected_designer),None)
    if selected_designer:
        if not board_designer: abort(404)
        linked=next((u for u in users if u['profile'] and u['profile']['designer_id']==selected_designer),None)
        occupied=next((p for p in db.profiles() if p['designer_id']==selected_designer),None)
        if occupied and not db.can_manage(g.current_user,occupied): abort(403)
        if linked: selected=linked
    elif selected and selected['profile']:
        board_designer=next((d for d in board if d['id']==selected['profile']['designer_id']),None)
    unlinked=[d for d in board if not any(p['designer_id']==d['id'] for p in db.profiles())]
    return _render('reportes/equipo.html',users=users,selected=selected,board_designer=board_designer,unlinked=unlinked,
      designers=storage.read('designers'),chiefs=[u for u in list_users() if u['role']==ROLE_CHIEF and u['is_active']])

@bp.post('/equipo/guardar')
@manager_required
def save_team():
    from proyectos_diseno.routes import storage
    actor=g.current_user; user_id=request.form.get('user_id','')
    raw={'start':request.form.get('start'),'end':request.form.get('end'),'breaks':request.form.get('breaks',''),
         'minimum_reports':request.form.get('minimum_reports'),'weekdays':request.form.getlist('weekdays'),
         'modules':request.form.getlist('modules')}
    try:
        config=db.validate_config(raw)
        db.finite_number(request.form.get('monthly_cost') or 0,'Costo mensual',0,1000000000)
        manager_id=actor['id'] if actor.get('is_chief') else request.form.get('manager_id','')
        manager=get_user_by_id(manager_id)
        if not manager or not manager['is_active'] or manager['role'] not in {ROLE_CHIEF,ROLE_ADMIN}:
            raise ValueError('Seleccione un Jefe de Diseño activo (o el Desarrollador responsable).')
        old=db.get_profile(user_id) if user_id else None
        if not db.can_manage(actor,old): abort(403)
        if old and old['version']!=int(request.form.get('version','0')): raise ValueError('El perfil cambió. Recargue antes de guardar.')
        designer_id=request.form.get('designer_id','')
        linked=storage.get('designers',designer_id) if designer_id else None
        if designer_id and not linked and not (old and designer_id==old['designer_id']): raise ValueError('Seleccione un diseñador existente válido.')
        if not designer_id:
            existing_user=get_user_by_id(user_id) if user_id else None
            name=(existing_user or {}).get('name') or request.form.get('name','')
            matches=[d for d in storage.read('designers') if str(d.get('nombre','')).strip().casefold()==str(name).strip().casefold()]
            if len(matches)>1: raise ValueError('Seleccione el diseñador existente: hay varias coincidencias de nombre.')
            if len(matches)==1: designer_id=matches[0]['id']; linked=matches[0]
        if designer_id and any(p['designer_id']==designer_id and p['user_id']!=user_id for p in db.profiles()):
            raise ValueError('Ese diseñador del tablero ya tiene otra cuenta vinculada.')
        if old and old['designer_id'] and designer_id!=old['designer_id']:
            raise ValueError('Conserve el vínculo actual del perfil con el diseñador del tablero.')
        # Comprueba primero que el catálogo del tablero es accesible.
        storage.read('designers')
        if user_id:
            target=get_user_by_id(user_id)
            if not target or target['role']!=ROLE_COLLABORATOR: raise ValueError('Solo se configuran perfiles de Diseñador.')
        else:
            target=create_user(request.form.get('username'),request.form.get('name'),request.form.get('password'),ROLE_COLLABORATOR,actor['username'])
            user_id=target['id']
        if not designer_id:
            matches=[d for d in storage.read('designers') if str(d.get('nombre','')).strip().casefold()==target['name'].strip().casefold()]
            if len(matches)==1:
                designer_id=matches[0]['id']; linked=matches[0]
            elif len(matches)>1: raise ValueError('Hay diseñadores existentes con el mismo nombre. Seleccione el registro que corresponde.')
            else: designer_id=str(uuid.uuid4())
        if any(p['designer_id']==designer_id and p['user_id']!=user_id for p in db.profiles()):
            raise ValueError('El diseñador ya está vinculado a otra cuenta; no se creará un duplicado.')
        profile=db.save_profile(user_id,manager_id,designer_id,config,actor,request.form.get('version'))
        designer=dict(linked or {'id':designer_id,'nombre':target['name'],'color':'#1268c9','costo_mensual_empresa':0,'activo':True})
        first_break=config['breaks'][0] if config['breaks'] else ['','']
        designer.update(nombre=target['name'],activo=target['is_active'],color=request.form.get('color') or designer.get('color','#1268c9'),
                        costo_mensual_empresa=db.finite_number(request.form.get('monthly_cost') or designer.get('costo_mensual_empresa',0),'Costo mensual',0,1000000000))
        designer.update(hora_entrada=config['start'],hora_salida=config['end'],almuerzo_inicio=first_break[0],almuerzo_fin=first_break[1],
                        descansos=json.dumps(config['breaks']),dias_laborales=json.dumps(config['weekdays']))
        try:
            storage.upsert('designers',designer)
        except OSError:
            flash('El perfil fue guardado, pero no se pudo sincronizar el tablero. Cierre los Excel abiertos y vuelva a guardar este perfil.','error')
            return redirect(url_for('reportes.team',usuario=user_id))
        _audit('CONFIGURAR DISEÑADOR',f"{target['username']} · horario, reportes y módulos")
        db.sync_project_activities()
        flash('Diseñador configurado y vinculado al tablero. Sus permisos se aplican en la siguiente solicitud.','ok')
    except PermissionError: abort(403)
    except ValueError as e: flash(str(e),'error')
    except OSError:
        flash('No se pudo sincronizar el diseñador con el tablero. Cierre los Excel abiertos y vuelva a guardar el perfil. La cuenta y el perfil se conservan.','error')
    return redirect(url_for('reportes.team',usuario=user_id) if user_id else url_for('reportes.team'))

@bp.post('/equipo/<user_id>/cuenta')
@manager_required
def account(user_id):
    target=get_user_by_id(user_id); profile=db.get_profile(user_id)
    if not target or target['role']!=ROLE_COLLABORATOR or not db.can_manage(g.current_user,profile): abort(403)
    action=request.form.get('action')
    try:
        if action=='password': reset_password(user_id,request.form.get('password'))
        elif action=='unlock': unlock_user(user_id)
        elif action=='status': set_user_status(user_id,request.form.get('status'))
        else: raise ValueError('Acción inválida.')
        _audit('ADMINISTRAR CUENTA DISEÑADOR',f'{target["username"]} · {action}')
        flash('Cuenta actualizada.','ok')
    except ValueError as e: flash(str(e),'error')
    return redirect(url_for('reportes.team',usuario=user_id))

@bp.get('/asignaciones')
def tasks():
    db.sync_project_activities()
    manager=g.current_user.get('is_admin') or g.current_user.get('is_chief')
    users=_configured_users() if manager else [{'id':g.current_user['id'],'name':g.current_user['name']}]
    items=db.assignments([u['id'] for u in users]); names={u['id']:u['name'] for u in users}
    selected=None
    if request.args.get('editar'):
        selected=next((t for t in items if t['id']==request.args['editar']),None)
        if not selected or not manager: abort(403)
        if selected.get('source_id'): return redirect(url_for('proyectos_diseno.index',view='projects',project_id=selected['project_id']))
    from proyectos_diseno.routes import storage
    projects=storage.read('projects') if manager else []
    return _render('reportes/asignaciones.html',users=users,assignments=items,names=names,selected=selected,projects=projects,manager=manager)

@bp.post('/asignaciones/guardar')
@manager_required
def save_task():
    try:
        user=get_user_by_id(request.form.get('user_id'))
        if not user or not user['is_active'] or user['role']!=ROLE_COLLABORATOR: raise ValueError('Seleccione un diseñador activo.')
        task_id=db.save_assignment(request.form,g.current_user,request.form.get('id') or None)
        _audit('GUARDAR ASIGNACIÓN',task_id); flash('Asignación guardada.','ok')
    except PermissionError: abort(403)
    except ValueError as e: flash(str(e),'error')
    return redirect(url_for('reportes.tasks'))

@bp.get('/tablero')
@manager_required
def dashboard():
    db.sync_project_activities()
    start,end=_range(); users=_configured_users(); filter_user=request.args.get('usuario','')
    if filter_user:
        if not any(u['id']==filter_user for u in users): abort(403)
        users=[u for u in users if u['id']==filter_user]
    ids=[u['id'] for u in users]; names={u['id']:u['name'] for u in users}
    days=[start+timedelta(days=i) for i in range((end-start).days+1)]
    summaries=[]
    for user in users:
        rows=[db.day_summary(user['id'],d) for d in days]
        summaries.append({'user':user,'days':rows,'expected':sum(r['expected'] for r in rows),'actual':sum(r['actual'] for r in rows),
          'pending_days':sum(r['status']=='PENDIENTE' for r in rows),'missing_reports':sum(r['missing_reports'] for r in rows if r['status']=='PENDIENTE')})
    tasks=db.assignments(ids,end); reports=db.list_reports(ids,start,end)
    return _render('reportes/tablero.html',users=_configured_users(),selected_user=filter_user,start=start.isoformat(),end=end.isoformat(),
      summaries=summaries,assignments=tasks,reports=reports,names=names,
      metrics={'expected':sum(s['expected'] for s in summaries),'actual':sum(s['actual'] for s in summaries),
      'late':sum(t['trend']=='ATRASADA' for t in tasks),'ahead':sum(t['trend'] in {'ADELANTADA','TERMINADA ANTES'} for t in tasks),
      'unreviewed':sum(r['status']=='ENVIADO' for r in reports)})

@bp.post('/<report_id>/revisar')
@manager_required
def review(report_id):
    try:
        db.review_report(report_id,request.form,g.current_user)
        db.sync_reviewed_activity(report_id,g.current_user)
        _audit('REVISAR REPORTE',report_id); flash('Revisión registrada.','ok')
    except PermissionError: abort(403)
    except ValueError as e: flash(str(e),'error')
    except OSError: flash('La revisión quedó guardada, pero no se pudo actualizar el tablero. Cierre el Excel y vuelva a guardar la revisión para sincronizar.','error')
    return redirect(url_for('reportes.dashboard',desde=request.form.get('desde'),hasta=request.form.get('hasta'),usuario=request.form.get('usuario','')))

@bp.get('/exportar')
@manager_required
def export():
    start,end=_range(); users=_configured_users(); wanted=request.args.get('usuario','')
    if wanted:
        if not any(u['id']==wanted for u in users): abort(403)
        users=[u for u in users if u['id']==wanted]
    names={u['id']:u['name'] for u in users}; reports=db.list_reports(list(names),start,end)
    out=StringIO(); writer=csv.writer(out,delimiter=';')
    writer.writerow(['Fecha','Diseñador','Inicio','Fin','Horas netas','Asignación','Proyecto','Avance acumulado %','Trabajo realizado','Bloqueos','Estado','Observación jefe'])
    for r in reports:
        values=[r['day'],names[r['user_id']],db.time_label(r['start_minute']),db.time_label(r['end_minute']),
        f"{r['minutes']/60:.2f}".replace('.',','),r['task_title'] or '',r['project_label'] or '',r['progress'] if r['progress'] is not None else '',r['description'],r['blocker'],r['status'],r['review_note']]
        writer.writerow([("'"+str(v)) if str(v).lstrip().startswith(('=','+','-','@')) else v for v in values])
    _audit('EXPORTAR REPORTES',f'{start} a {end}')
    return Response('\ufeff'+out.getvalue(),mimetype='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="REPORTES_{start}_{end}.csv"'})
