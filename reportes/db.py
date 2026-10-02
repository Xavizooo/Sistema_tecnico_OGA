"""Perfiles, asignaciones y reportes en SQLite; horas en minutos enteros."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
import json
import math
import re
import sqlite3
import uuid

DB_FILE = Path(__file__).resolve().parent.parent / 'data' / 'REPORTES' / 'reportes.db'
BOGOTA = timezone(timedelta(hours=-5))

def now(): return datetime.now(BOGOTA)
def today(): return now().date()
def timestamp(): return now().isoformat(timespec='seconds')

@contextmanager
def connection():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=20000')
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally: conn.close()

def ensure_database():
    with connection() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS profiles (
          user_id TEXT PRIMARY KEY, manager_id TEXT NOT NULL DEFAULT '',
          designer_id TEXT NOT NULL DEFAULT '', config TEXT NOT NULL,
          version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE UNIQUE INDEX IF NOT EXISTS profile_designer_unique ON profiles(designer_id) WHERE designer_id != '';
        CREATE TABLE IF NOT EXISTS profile_history (
          id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, effective_date TEXT NOT NULL,
          config TEXT NOT NULL, changed_by TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS profile_history_user ON profile_history(user_id,effective_date);
        CREATE TABLE IF NOT EXISTS assignments (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(user_id), manager_id TEXT NOT NULL,
          title TEXT NOT NULL, project_id TEXT NOT NULL DEFAULT '', project_label TEXT NOT NULL DEFAULT '',
          description TEXT NOT NULL DEFAULT '', start_date TEXT NOT NULL, due_date TEXT NOT NULL,
          planned_minutes INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVA',
          version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS assignment_user ON assignments(user_id,status);
        CREATE TABLE IF NOT EXISTS reports (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(user_id), day TEXT NOT NULL,
          start_minute INTEGER NOT NULL, end_minute INTEGER NOT NULL, minutes INTEGER NOT NULL,
          description TEXT NOT NULL, blocker TEXT NOT NULL DEFAULT '', assignment_id TEXT REFERENCES assignments(id),
          progress REAL, schedule TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ENVIADO',
          review_note TEXT NOT NULL DEFAULT '', reviewed_by TEXT NOT NULL DEFAULT '', reviewed_at TEXT,
          version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS reports_user_day ON reports(user_id,day);
        CREATE TABLE IF NOT EXISTS review_history (
          id INTEGER PRIMARY KEY, report_id TEXT NOT NULL REFERENCES reports(id),
          status TEXT NOT NULL, note TEXT NOT NULL, reviewer TEXT NOT NULL, created_at TEXT NOT NULL);
        ''')

        columns={r['name'] for r in c.execute('PRAGMA table_info(assignments)')}
        for name,definition in [('source_id',"TEXT NOT NULL DEFAULT ''"),('source_completed',"INTEGER NOT NULL DEFAULT 0"),('source_completion_date',"TEXT NOT NULL DEFAULT ''")]:
            if name not in columns: c.execute(f'ALTER TABLE assignments ADD COLUMN {name} {definition}')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS assignment_source ON assignments(source_id,user_id) WHERE source_id!=''")
        c.execute('CREATE TABLE IF NOT EXISTS project_completions(report_id TEXT PRIMARY KEY, source_id TEXT NOT NULL)')
        report_columns={r['name'] for r in c.execute('PRAGMA table_info(reports)')}
        if 'details' not in report_columns:
            c.execute("ALTER TABLE reports ADD COLUMN details TEXT NOT NULL DEFAULT '{}'")
        c.executescript("""
        CREATE TABLE IF NOT EXISTS personal_tasks (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES profiles(user_id),
          day TEXT NOT NULL, start_minute INTEGER NOT NULL, end_minute INTEGER NOT NULL,
          description TEXT NOT NULL, assignment_id TEXT REFERENCES assignments(id),
          details TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'PENDIENTE',
          report_id TEXT REFERENCES reports(id), created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS personal_tasks_user_day ON personal_tasks(user_id,day);
        """)

def parse_day(value):
    try: return date.fromisoformat(str(value))
    except (TypeError, ValueError): raise ValueError('Seleccione una fecha válida.')

def time_minute(value):
    text = str(value or '')
    if not re.fullmatch(r'\d{2}:\d{2}', text): raise ValueError('Use horas en formato HH:MM.')
    h,m = map(int,text.split(':'))
    if h > 23 or m > 59: raise ValueError('Hora fuera de rango.')
    return h*60+m

def time_label(minutes): return f'{int(minutes)//60:02}:{int(minutes)%60:02}'

def duration_label(minutes):
    total=max(0,int(round(minutes)))
    return f'{total//60} h {total%60:02} min'

def finite_number(value, label, low, high):
    try: n = float(value)
    except (TypeError, ValueError): raise ValueError(f'{label}: escriba un número válido.')
    if not math.isfinite(n) or not low <= n <= high: raise ValueError(f'{label}: debe estar entre {low} y {high}.')
    return n

def validate_config(raw):
    start = str(raw.get('start') or '07:00'); end = str(raw.get('end') or '17:00')
    lo,hi = time_minute(start),time_minute(end)
    if hi <= lo: raise ValueError('La salida debe ser posterior a la entrada; use una jornada dentro del mismo día.')
    breaks = raw.get('breaks', [])
    if isinstance(breaks,str):
        try: breaks = [line.strip().split('-') for line in breaks.splitlines() if line.strip()]
        except Exception: raise ValueError('Descansos: use una línea HH:MM-HH:MM por descanso.')
    parsed = []
    for item in breaks:
        if not isinstance(item,(list,tuple)) or len(item)!=2: raise ValueError('Descansos: use HH:MM-HH:MM.')
        a,b = time_minute(str(item[0]).strip()),time_minute(str(item[1]).strip())
        if a < lo or b > hi or b <= a: raise ValueError('Los descansos deben estar dentro de la jornada y tener duración positiva.')
        parsed.append((a,b))
    parsed.sort()
    if any(parsed[i][0] < parsed[i-1][1] for i in range(1,len(parsed))): raise ValueError('Los descansos no pueden superponerse.')
    daily = hi-lo-sum(b-a for a,b in parsed)
    if daily <= 0: raise ValueError('La jornada debe tener tiempo laboral disponible.')
    minimum = 0
    weekdays = sorted(set(int(finite_number(x,'Día laboral',0,6)) for x in raw.get('weekdays',[0,1,2,3,4])))
    if not weekdays: raise ValueError('Seleccione al menos un día laboral.')
    from permisos import MODULES
    modules = sorted(set(raw.get('modules',[])))
    if any(x not in MODULES for x in modules): raise ValueError('Se recibió un módulo inválido.')
    return {'start':start,'end':end,'breaks':[[time_label(a),time_label(b)] for a,b in parsed],
            'minimum_reports':int(minimum),'weekdays':weekdays,'modules':modules,'daily_minutes':daily}

def _profile(row):
    if not row: return None
    result=dict(row); result.update(json.loads(result.pop('config')))
    result['breaks_text']='\n'.join('-'.join(x) for x in result['breaks'])
    return result

def get_profile(user_id):
    with connection() as c: return _profile(c.execute('SELECT * FROM profiles WHERE user_id=?',(user_id,)).fetchone())

def profiles():
    with connection() as c: return [_profile(r) for r in c.execute('SELECT * FROM profiles ORDER BY created_at')]

def can_manage(actor,profile):
    return bool(actor.get('is_admin') or (actor.get('is_chief') and (not profile or profile['manager_id'] in {'',actor['id']})))

def save_profile(user_id, manager_id, designer_id, config, actor, version=None):
    config=validate_config(config)
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        old=_profile(c.execute('SELECT * FROM profiles WHERE user_id=?',(user_id,)).fetchone())
        if not can_manage(actor,old): raise PermissionError('El diseñador pertenece a otro Jefe de Diseño.')
        if old and int(version or 0)!=old['version']: raise ValueError('Otro usuario cambió este perfil. Recargue antes de guardar.')
        if actor.get('is_chief') and manager_id!=actor['id']: raise PermissionError('Solo puede administrar su propio equipo.')
        if old and designer_id != old['designer_id'] and c.execute('SELECT 1 FROM assignments WHERE user_id=? LIMIT 1',(user_id,)).fetchone():
            raise ValueError('El vínculo con el diseñador no puede cambiar después de crear asignaciones.')
        stamp=timestamp(); payload=json.dumps(config,ensure_ascii=False)
        try:
            c.execute('''INSERT INTO profiles(user_id,manager_id,designer_id,config,created_at,updated_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET manager_id=excluded.manager_id,
              designer_id=excluded.designer_id,config=excluded.config,version=profiles.version+1,updated_at=excluded.updated_at''',
              (user_id,manager_id,designer_id,payload,stamp,stamp))
        except sqlite3.IntegrityError: raise ValueError('Ese diseñador del tablero ya está vinculado a otra cuenta.')
        c.execute('INSERT INTO profile_history(user_id,effective_date,config,changed_by,created_at) VALUES(?,?,?,?,?)',
                  (user_id,today().isoformat(),payload,actor['id'],stamp))
    return get_profile(user_id)

@lru_cache(maxsize=12)
def national_holidays(year):
    from proyectos_diseno.services import colombia_holidays
    return {d for d,label in colombia_holidays(year)}

def is_workday(day,profile):
    if day.weekday() not in profile['weekdays'] or day in national_holidays(day.year): return False
    from proyectos_diseno.routes import storage
    for row in storage.read('holidays'):
        if row.get('activo',True) and str(row.get('fecha',''))[:10] == day.isoformat(): return False
    return True

def net_minutes(start,end,profile):
    return max(0,end-start-sum(max(0,min(end,time_minute(b))-max(start,time_minute(a))) for a,b in profile['breaks']))

def schedule_for(user_id,day,c):
    # La primera presentación fija la jornada de ese día, incluso si luego cambia el perfil.
    row=c.execute('SELECT schedule FROM reports WHERE user_id=? AND day=? ORDER BY created_at,id LIMIT 1',(user_id,day.isoformat())).fetchone()
    if row: return json.loads(row['schedule'])
    row=c.execute('SELECT config FROM profile_history WHERE user_id=? AND effective_date<=? ORDER BY effective_date DESC,id DESC LIMIT 1',
                  (user_id,day.isoformat())).fetchone()
    if row: return json.loads(row['config'])
    return None

def assignment(task_id):
    with connection() as c:
        r=c.execute('SELECT * FROM assignments WHERE id=?',(task_id,)).fetchone()
        return dict(r) if r else None

def save_assignment(raw,actor,task_id=None):
    user_id=str(raw.get('user_id','')); profile=get_profile(user_id)
    if not profile or not can_manage(actor,profile): raise PermissionError('No puede asignar trabajo a este diseñador.')
    title=str(raw.get('title','')).strip(); description=str(raw.get('description','')).strip()
    if not 3<=len(title)<=180 or len(description)>4000: raise ValueError('Título: entre 3 y 180 caracteres. Descripción: máximo 4000.')
    start=parse_day(raw.get('start_date')); due=parse_day(raw.get('due_date'))
    if due<start or (due-start).days>730: raise ValueError('La fecha final debe ser posterior o igual al inicio y el rango no debe superar dos años.')
    if not any(is_workday(start+timedelta(days=i),profile) for i in range((due-start).days+1)):
        raise ValueError('La asignación debe incluir al menos un día laborable.')
    planned=round(finite_number(raw.get('planned_hours'),'Horas planificadas',0.02,10000)*60)
    status=raw.get('status','ACTIVA')
    if status not in {'ACTIVA','CANCELADA'}: raise ValueError('Estado de asignación inválido.')
    project_id=str(raw.get('project_id','')); project_label=''
    if project_id and not task_id: raise ValueError('Las actividades de los proyectos aparecen automáticamente. Cree aquí únicamente trabajo adicional sin proyecto.')
    if project_id:
        from proyectos_diseno.routes import storage
        project=storage.get('projects',project_id)
        if not project: raise ValueError('El proyecto seleccionado ya no existe.')
        if profile['designer_id'] and str(project.get('designer_id',''))!=profile['designer_id']:
            raise ValueError('El proyecto está asignado a otro diseñador en el tablero.')
        project_label=f"{project.get('numero','')} · {project.get('cliente','')}"
    stamp=timestamp()
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        if task_id:
            old=c.execute('SELECT * FROM assignments WHERE id=?',(task_id,)).fetchone()
            if not old: raise ValueError('Asignación no encontrada.')
            if old['source_id']: raise ValueError('Esta actividad se planifica en Seguimiento de Proyectos; no se edita nuevamente aquí.')
            if not can_manage(actor,get_profile(old['user_id'])): raise PermissionError('No puede modificar esta asignación.')
            if old['user_id']!=user_id: raise ValueError('No cambie el diseñador de una asignación existente; cree otra.')
            if old['version']!=int(raw.get('version',0)): raise ValueError('La asignación cambió. Recargue antes de guardar.')
            c.execute('''UPDATE assignments SET title=?,project_id=?,project_label=?,description=?,start_date=?,due_date=?,
               planned_minutes=?,status=?,updated_at=?,version=version+1 WHERE id=?''',
               (title,project_id,project_label,description,start.isoformat(),due.isoformat(),planned,status,stamp,task_id))
        else:
            task_id=uuid.uuid4().hex
            c.execute('''INSERT INTO assignments(id,user_id,manager_id,title,project_id,project_label,description,start_date,due_date,
              planned_minutes,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
              (task_id,user_id,actor['id'],title,project_id,project_label,description,start.isoformat(),due.isoformat(),planned,status,stamp,stamp))
    return task_id

def submit_report(raw,user):
    if user.get('is_chief') or user.get('role')=='JEFE DE DISEÑO': raise PermissionError('El Jefe de Diseño no envía reportes.')
    user_id=user['id']; day=parse_day(raw.get('day'))
    if day>today(): raise ValueError('No puede reportar una fecha futura.')
    if day<today()-timedelta(days=31): raise ValueError('Solo puede reportar dentro de los últimos 31 días.')
    a,b=time_minute(raw.get('start')),time_minute(raw.get('end'))
    if b<=a: raise ValueError('La hora final debe ser posterior a la inicial.')
    if day==today() and b>now().hour*60+now().minute: raise ValueError('No puede reportar horas que aún no han transcurrido.')
    description=str(raw.get('description') or raw.get('activity') or '').strip(); blocker=str(raw.get('blocker','')).strip()
    if not 3<=len(description)<=4000 or len(blocker)>2000: raise ValueError('Actividad: entre 3 y 4000 caracteres. Bloqueos: máximo 2000.')
    task_id=str(raw.get('assignment_id','')) or None
    progress=finite_number(raw.get('progress'),'Avance acumulado',0,100) if task_id else None
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        profile=_profile(c.execute('SELECT * FROM profiles WHERE user_id=?',(user_id,)).fetchone())
        if not profile: raise ValueError('El Jefe de Diseño debe configurar primero su horario.')
        schedule=schedule_for(user_id,day,c)
        if not schedule: raise ValueError('No hay horario configurado para esa fecha.')
        if not is_workday(day,schedule): raise ValueError('La fecha no corresponde a un día laboral de su horario.')
        if a<time_minute(schedule['start']) or b>time_minute(schedule['end']): raise ValueError('El intervalo debe estar dentro de su jornada laboral.')
        minutes=net_minutes(a,b,schedule)
        if minutes<=0: raise ValueError('El intervalo contiene únicamente tiempo de descanso.')
        if c.execute("SELECT 1 FROM reports WHERE user_id=? AND day=? AND status!='DEVUELTO' AND start_minute<? AND end_minute>?",
                     (user_id,day.isoformat(),b,a)).fetchone(): raise ValueError('Ese intervalo se superpone con otro reporte vigente.')
        if task_id:
            task=c.execute('SELECT * FROM assignments WHERE id=? AND user_id=?',(task_id,user_id)).fetchone()
            if task and task['source_id'] and task['source_completed']: raise ValueError('La actividad del proyecto ya está cumplida; registre apoyo como trabajo general.')
            if not task or task['status']!='ACTIVA': raise ValueError('La asignación no está activa o no le pertenece.')
            if day<parse_day(task['start_date']): raise ValueError('El reporte es anterior al inicio de la asignación.')
            if raw.get('_complete_assigned') and c.execute("SELECT 1 FROM reports WHERE assignment_id=? AND status!='DEVUELTO' AND progress>=100",(task_id,)).fetchone():
                raise ValueError('La tarea ya fue completada.')
            previous=c.execute("SELECT progress FROM reports WHERE assignment_id=? AND status!='DEVUELTO' AND (day<? OR (day=? AND end_minute<=?)) ORDER BY day DESC,end_minute DESC,created_at DESC LIMIT 1",
                               (task_id,day.isoformat(),day.isoformat(),b)).fetchone()
            following=c.execute("SELECT progress FROM reports WHERE assignment_id=? AND status!='DEVUELTO' AND (day>? OR (day=? AND end_minute>?)) ORDER BY day,end_minute,created_at LIMIT 1",
                                (task_id,day.isoformat(),day.isoformat(),b)).fetchone()
            if previous and progress<float(previous['progress']): raise ValueError('El avance acumulado no puede ser menor que el reporte anterior.')
            if following and progress>float(following['progress']): raise ValueError('El avance acumulado no puede superar el reporte posterior de esa asignación.')
        pending_id=str(raw.get('pending_id') or '')
        if pending_id:
            pending=c.execute('SELECT * FROM personal_tasks WHERE id=? AND user_id=?',(pending_id,user_id)).fetchone()
            if not pending or pending['status']!='PENDIENTE':
                raise ValueError('La tarea no le pertenece o ya fue completada.')
            if pending['day']!=day.isoformat() or (pending['assignment_id'] or None)!=task_id:
                raise ValueError('Conserve la fecha y la asignación de la tarea programada.')
        details=report_details(raw)
        report_id=uuid.uuid4().hex
        c.execute('''INSERT INTO reports(id,user_id,day,start_minute,end_minute,minutes,description,blocker,assignment_id,progress,schedule,created_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
          (report_id,user_id,day.isoformat(),a,b,minutes,description,blocker,task_id,progress,json.dumps(schedule),timestamp()))
        c.execute('UPDATE reports SET details=? WHERE id=?',(json.dumps(details,ensure_ascii=False),report_id))
        if pending_id:
            c.execute("UPDATE personal_tasks SET status='COMPLETADA',report_id=? WHERE id=?",(report_id,pending_id))
    return report_id

def report(report_id):
    with connection() as c:
        row=c.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
        return dict(row) if row else None

def review_report(report_id,raw,actor):
    status=raw.get('status'); note=str(raw.get('review_note','')).strip()
    if status not in {'REVISADO','DEVUELTO'} or len(note)>2000: raise ValueError('Seleccione un estado válido; observaciones: máximo 2000 caracteres.')
    if status=='DEVUELTO' and len(note)<5: raise ValueError('Indique el motivo de la devolución.')
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
        if not row: raise ValueError('Reporte no encontrado.')
        if not can_manage(actor,get_profile(row['user_id'])): raise PermissionError('No puede revisar este reporte.')
        if row['version']!=int(raw.get('version',0)): raise ValueError('El reporte ya cambió. Recargue antes de revisar.')
        if row['status']=='DEVUELTO': raise ValueError('Un reporte devuelto queda conservado en el historial. El diseñador debe presentar uno nuevo.')
        c.execute('UPDATE reports SET status=?,review_note=?,reviewed_by=?,reviewed_at=?,version=version+1 WHERE id=?',
                  (status,note,actor['id'],timestamp(),report_id))
        c.execute('INSERT INTO review_history(report_id,status,note,reviewer,created_at) VALUES(?,?,?,?,?)',
                  (report_id,status,note,actor['id'],timestamp()))

def list_reports(user_ids,start,end):
    if not user_ids: return []
    placeholders=','.join('?' for _ in user_ids)
    with connection() as c:
        rows=c.execute(f'''SELECT r.*,a.title AS task_title,a.project_label FROM reports r LEFT JOIN assignments a ON r.assignment_id=a.id
          WHERE r.user_id IN ({placeholders}) AND r.day>=? AND r.day<=? ORDER BY r.day DESC,r.start_minute DESC,r.created_at DESC''',
          (*user_ids,start.isoformat(),end.isoformat())).fetchall()
        return [dict(r) for r in rows]

def day_summary(user_id,day):
    with connection() as c:
        profile=schedule_for(user_id,day,c)
        rows=c.execute("SELECT * FROM reports WHERE user_id=? AND day=? AND status!='DEVUELTO'",(user_id,day.isoformat())).fetchall()
    working=bool(profile and is_workday(day,profile)); expected=net_minutes(time_minute(profile['start']),time_minute(profile['end']),profile) if working else 0
    minimum=0
    actual=sum(r['minutes'] for r in rows); count=len(rows)
    if not working or day>today():elapsed=0
    elif day<today():elapsed=expected
    else:
        cutoff=max(time_minute(profile['start']),min(now().hour*60+now().minute,time_minute(profile['end'])))
        elapsed=net_minutes(time_minute(profile['start']),cutoff,profile)
    finished=day<today() or (day==today() and profile and now().hour*60+now().minute>=time_minute(profile['end']))
    if not profile: status='SIN HORARIO'
    elif not working: status='NO LABORAL'
    elif actual>=expected: status='CUMPLIDO'
    elif finished: status='PENDIENTE'
    else: status='EN CURSO'
    return {'day':day.isoformat(),'expected':expected,'actual':actual,'missing':max(0,expected-actual),
      'elapsed':elapsed,'unregistered_elapsed':max(0,elapsed-actual),'remaining_work':max(0,expected-elapsed),
      'count':count,'minimum':minimum,'missing_reports':max(0,minimum-count),'status':status,
      'profile':profile,'unreviewed':sum(r['status']=='ENVIADO' for r in rows)}

def assignments(user_ids,as_of=None):
    if not user_ids: return []
    day=as_of or today(); marks=','.join('?' for _ in user_ids)
    with connection() as c:
        tasks=[dict(r) for r in c.execute(f'SELECT * FROM assignments WHERE user_id IN ({marks}) ORDER BY due_date,title',tuple(user_ids))]
        for task in tasks:
            reports=c.execute("SELECT * FROM reports WHERE assignment_id=? AND day<=? AND status!='DEVUELTO' ORDER BY day,end_minute,created_at",
                              (task['id'],day.isoformat())).fetchall()
            profile=_profile(c.execute('SELECT * FROM profiles WHERE user_id=?',(task['user_id'],)).fetchone())
            start=parse_day(task['start_date']); due=parse_day(task['due_date'])
            workdays=[start+timedelta(days=i) for i in range((due-start).days+1) if is_workday(start+timedelta(days=i),profile)]
            denominator=len(workdays)*profile['daily_minutes']
            elapsed=sum(profile['daily_minutes'] for d in workdays if d<day)
            if day in workdays:
                cutoff=time_minute(profile['end']) if day<today() else (now().hour*60+now().minute if day==today() else time_minute(profile['start']))
                elapsed+=net_minutes(time_minute(profile['start']),max(time_minute(profile['start']),min(cutoff,time_minute(profile['end']))),profile)
            expected=round(min(100,elapsed/denominator*100),1) if denominator else 0
            progress=100 if task['source_completed'] else (float(reports[-1]['progress']) if reports else 0)
            completion=parse_day(task['source_completion_date']) if task['source_completed'] and task['source_completion_date'] else next((parse_day(r['day']) for r in reports if float(r['progress'])>=100),None)
            if task['source_completed'] and not task['source_completion_date'] and not completion: trend='CUMPLIDA EN PROYECTO'
            elif task['status']=='CANCELADA': trend='CANCELADA'
            elif completion: trend='TERMINADA ANTES' if completion<due else ('TERMINADA TARDE' if completion>due else 'TERMINADA A TIEMPO')
            elif day>due or (day==due and (day<today() or day==today() and now().hour*60+now().minute>=time_minute(profile['end']))): trend='ATRASADA'
            elif day<start: trend='POR INICIAR'
            elif progress<expected-5: trend='ATRASADA'
            elif progress>expected+5: trend='ADELANTADA'
            else: trend='EN TIEMPO'
            task.update(progress=progress,expected_progress=expected,delta=round(progress-expected,1),
              actual_minutes=sum(r['minutes'] for r in reports),trend=trend,
              blockers=[r['blocker'] for r in reports if r['blocker']][-3:])
    return tasks


def sync_project_activities():
    """Proyectos es fuente de planificación; SQLite conserva el vínculo y reportes."""
    from proyectos_diseno.routes import storage
    from proyectos_diseno.services import stage_bounds, planned_hours_and_cost, holiday_dates
    designers={str(d['id']):d for d in storage.read('designers')}
    projects={str(p['id']):p for p in storage.read('projects')}
    periods=storage.read('stage_periods'); holidays=holiday_dates(storage.read('holidays'))
    profiles_by_designer={p['designer_id']:p for p in profiles() if p['designer_id']}
    sources=[]
    for activity in storage.read('project_progress'):
        project=projects.get(str(activity.get('project_id')))
        if not project: continue
        profile=profiles_by_designer.get(str(project.get('designer_id')))
        if not profile: continue
        working={**project,'stage_periods':[r for r in periods if str(r.get('project_id'))==str(project['id'])]}
        stage=int(float(activity.get('etapa') or 0))
        if stage not in {1,2,3}:continue
        start,due=stage_bounds(working,stage)
        if not start or not due or due<start:continue
        hours,_,_=planned_hours_and_cost(working,designers.get(str(project.get('designer_id'))),holidays)
        budget=max(1,round(hours*float(activity.get('porcentaje') or 0)/100*60))
        sources.append((activity,project,profile,start,due,budget))
    stamp=timestamp();active=set()
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        for activity,project,profile,start,due,budget in sources:
            source_id=str(activity['id']);user_id=profile['user_id'];active.add((source_id,user_id))
            label=f"{project.get('numero','')} · {project.get('cliente','')}"
            status='ACTIVA' if activity.get('cumplida') or str(project.get('estado','Activo')).lower()!='finalizado' else 'CANCELADA'
            existing=c.execute('SELECT * FROM assignments WHERE source_id=? AND user_id=?',(source_id,user_id)).fetchone()
            fields=(str(activity.get('actividad') or 'Actividad del proyecto'),str(project['id']),label,
                    f"Etapa {activity.get('etapa')} · actividad del proyecto",start.isoformat(),due.isoformat(),budget,status,
                    int(bool(activity.get('cumplida'))),str(activity.get('fecha_cumplimiento') or '')[:10])
            if not existing:
                legacy=[r for r in c.execute("SELECT * FROM assignments WHERE source_id='' AND user_id=? AND project_id=?",(user_id,str(project['id']))) if str(r['title']).strip().casefold()==str(activity.get('actividad','')).strip().casefold()]
                if len(legacy)==1:
                    c.execute('UPDATE assignments SET source_id=? WHERE id=?',(source_id,legacy[0]['id']))
                    existing=c.execute('SELECT * FROM assignments WHERE id=?',(legacy[0]['id'],)).fetchone()
            if existing:
                names=['title','project_id','project_label','description','start_date','due_date','planned_minutes','status','source_completed','source_completion_date']
                if tuple(existing[n] for n in names)!=fields:
                    c.execute('UPDATE assignments SET title=?,project_id=?,project_label=?,description=?,start_date=?,due_date=?,planned_minutes=?,status=?,source_completed=?,source_completion_date=?,version=version+1,updated_at=? WHERE id=?',(*fields,stamp,existing['id']))
            else:
                c.execute('INSERT INTO assignments(id,user_id,manager_id,title,project_id,project_label,description,start_date,due_date,planned_minutes,status,source_completed,source_completion_date,source_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                          (uuid.uuid4().hex,user_id,profile['manager_id'],*fields,source_id,stamp,stamp))
        for row in c.execute("SELECT id,source_id,user_id,status FROM assignments WHERE source_id!=''").fetchall():
            if (row['source_id'],row['user_id']) not in active and row['status']!='CANCELADA':
                c.execute("UPDATE assignments SET status='CANCELADA',version=version+1,updated_at=? WHERE id=?",(stamp,row['id']))


def sync_reviewed_activity(report_id,actor):
    """Una aprobación completa la actividad; una devolución revierte solo su cierre automático."""
    r=report(report_id)
    if not r or r['progress']!=100 or not r['assignment_id']:return
    task=assignment(r['assignment_id'])
    if not task or not task['source_id']:return
    if not can_manage(actor,get_profile(r['user_id'])):raise PermissionError('No pertenece a su equipo.')
    from proyectos_diseno.routes import storage
    activity=storage.get('project_progress',task['source_id'])
    project=storage.get('projects',task['project_id'])
    if not activity or not project or str(project.get('designer_id'))!=get_profile(r['user_id'])['designer_id']:return
    if r['status']=='REVISADO':
        if not activity.get('cumplida'):
            with connection() as c: c.execute('INSERT OR IGNORE INTO project_completions VALUES(?,?)',(report_id,task['source_id']))
            activity.update(cumplida=True,fecha_cumplimiento=r['day'])
            storage.upsert('project_progress',activity)
    elif r['status']=='DEVUELTO':
        with connection() as c:
            origin=c.execute('SELECT 1 FROM project_completions WHERE report_id=?',(report_id,)).fetchone()
            approved=c.execute("SELECT 1 FROM reports WHERE assignment_id=? AND status='REVISADO' AND progress=100 LIMIT 1",(task['id'],)).fetchone()
        if origin and not approved and str(activity.get('fecha_cumplimiento') or '')[:10]==r['day']:
            activity.update(cumplida=False,fecha_cumplimiento='')
            storage.upsert('project_progress',activity)
    sync_project_activities()

# Planificación personal: independiente de las asignaciones del jefe.
def report_details(raw):
    result={}
    for key,label,limit in [('project','Proyecto',180),('equipment','Equipo',180),('equipment_number','Número de equipo',80),('activity','Actividad',180),('stage','Etapa',80),('workplace','Centro de trabajo',120)]:
        value=str(raw.get(key) or '').strip()
        if len(value)>limit: raise ValueError(f'{label}: máximo {limit} caracteres.')
        result[key]=value
    return result

def personal_tasks(user_id,day):
    with connection() as c:
        rows=c.execute('''SELECT p.*,r.status AS report_status FROM personal_tasks p
            LEFT JOIN reports r ON r.id=p.report_id
            WHERE p.user_id=? AND p.day=? ORDER BY p.start_minute,p.created_at''',(user_id,day.isoformat())).fetchall()
        return [{**dict(r),'details':json.loads(r['details'])} for r in rows]

def plan_personal_task(raw,user):
    if user.get('is_chief') or user.get('role')=='JEFE DE DISEÑO': raise PermissionError('El Jefe de Diseño no programa tareas personales.')
    day=parse_day(raw.get('day')); a,b=time_minute(raw.get('start')),time_minute(raw.get('end'))
    if day<today() or day>today()+timedelta(days=31): raise ValueError('Programe desde hoy hasta los próximos 31 días.')
    if b<=a: raise ValueError('La hora final debe ser posterior a la inicial.')
    description=str(raw.get('description') or raw.get('activity') or '').strip()
    if not 3<=len(description)<=4000: raise ValueError('Actividad: entre 3 y 4000 caracteres.')
    details=report_details(raw); task_id=str(raw.get('assignment_id') or '') or None
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        config=schedule_for(user['id'],day,c)
        if not config: raise ValueError('El jefe debe configurar primero su horario.')
        if not is_workday(day,config): raise ValueError('La fecha no corresponde a un día laboral.')
        if a<time_minute(config['start']) or b>time_minute(config['end']) or not net_minutes(a,b,config):
            raise ValueError('Programe dentro de la jornada y fuera de intervalos de solo descanso.')
        if task_id:
            assignment=c.execute('SELECT * FROM assignments WHERE id=? AND user_id=?',(task_id,user['id'])).fetchone()
            if not assignment or assignment['status']!='ACTIVA' or assignment['source_completed']:
                raise ValueError('Seleccione una asignación propia y activa.')
            if day<parse_day(assignment['start_date']): raise ValueError('La tarea es anterior al inicio de la asignación.')
        if c.execute("SELECT 1 FROM personal_tasks WHERE user_id=? AND day=? AND status='PENDIENTE' AND start_minute<? AND end_minute>?",(user['id'],day.isoformat(),b,a)).fetchone() or c.execute("SELECT 1 FROM reports WHERE user_id=? AND day=? AND status!='DEVUELTO' AND start_minute<? AND end_minute>?",(user['id'],day.isoformat(),b,a)).fetchone():
            raise ValueError('El intervalo se superpone con otra tarea pendiente o reporte vigente.')
        task_id_new=uuid.uuid4().hex
        c.execute('''INSERT INTO personal_tasks(id,user_id,day,start_minute,end_minute,description,assignment_id,details,created_at)
                     VALUES(?,?,?,?,?,?,?,?,?)''',(task_id_new,user['id'],day.isoformat(),a,b,description,task_id,json.dumps(details,ensure_ascii=False),timestamp()))
    return task_id_new

def cancel_personal_task(task_id,user):
    with connection() as c:
        c.execute('BEGIN IMMEDIATE')
        changed=c.execute("UPDATE personal_tasks SET status='CANCELADA' WHERE id=? AND user_id=? AND status='PENDIENTE'",(task_id,user['id'])).rowcount
        if not changed: raise ValueError('La tarea no le pertenece o ya no está pendiente.')

def personal_analysis(user_id,start,end):
    rows=[];day=start
    while day<=end:
        summary=day_summary(user_id,day)
        summary['productivity']=round(summary['actual']/summary['expected']*100,1) if summary['expected'] else None
        rows.append(summary);day+=timedelta(days=1)
    actual=sum(r['actual'] for r in rows);expected=sum(r['expected'] for r in rows)
    count=sum(r['count'] for r in rows);working=sum(r['expected']>0 for r in rows)
    weeks={}
    for row in rows:
        day=parse_day(row['day']);monday=day-timedelta(days=day.weekday());key=monday.isoformat()
        week=weeks.setdefault(key,{'start':key,'end':(monday+timedelta(days=6)).isoformat(),
             'period_start':row['day'],'period_end':row['day'],'actual':0,'expected':0,'count':0,'working_days':0})
        week['period_end']=row['day'];week['actual']+=row['actual'];week['expected']+=row['expected'];week['count']+=row['count'];week['working_days']+=row['expected']>0
    for week in weeks.values():
        week['productivity']=round(week['actual']/week['expected']*100,1) if week['expected'] else None
        week['average']=round(week['count']/week['working_days'],2) if week['working_days'] else 0
    # Una muestra por cada tarea vigente, sin reducir a totales diarios ni a extremos.
    series=[];accumulated={}
    reports=sorted(list_reports([user_id],start,end),key=lambda r:(r['day'],r['end_minute'],r['start_minute'],r['id']))
    for report in reports:
        if report['status']=='DEVUELTO':continue
        config=json.loads(report['schedule']);day=report['day']
        accumulated[day]=accumulated.get(day,0)+report['minutes']
        available=net_minutes(time_minute(config['start']),report['end_minute'],config)
        details=json.loads(report['details'])
        series.append({'report_id':report['id'],'day':day,'time':time_label(report['end_minute']),
             'label':day+' '+time_label(report['end_minute']),
             'activity':details.get('activity') or report['task_title'] or report['description'],
             'minutes':report['minutes'],'accumulated':accumulated[day],'elapsed':available,
             'productivity':round(accumulated[day]/available*100,1) if available else None})
    return {'days':rows,'weeks':list(weeks.values()),'series':series,'actual':actual,'expected':expected,'count':count,'working_days':working,
            'average':round(count/working,2) if working else 0,
            'productivity':round(actual/expected*100,1) if expected else None}
