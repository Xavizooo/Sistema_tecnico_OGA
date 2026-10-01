"""Integración de roles y reportes. Ejecutar con VALIDAR_ROLES_REPORTES.py."""
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ISOLATED=os.environ.get('OGA_TEST_ISOLATED')=='1'
if ISOLATED:
    import app as application
    import auth_store as auth
    import permisos
    from reportes import db
    from proyectos_diseno.routes import storage

@unittest.skipUnless(ISOLATED,'Use VALIDAR_ROLES_REPORTES.py para no tocar datos originales.')
class RolesReportsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app=application.app;cls.app.config['TESTING']=True
        cls.admin=auth.create_user('test.dev','Desarrollador Pruebas','ClaveSegura_4095!',auth.ROLE_ADMIN,'PRUEBAS')
        cls.chief=auth.create_user('test.chief','Jefe Pruebas','ClaveSegura_4095!',auth.ROLE_CHIEF,'PRUEBAS')
        cls.other_chief=auth.create_user('test.chief2','Otro Jefe Pruebas','ClaveSegura_4095!',auth.ROLE_CHIEF,'PRUEBAS')
        cls.fixed=datetime(2026,10,1,17,30,tzinfo=db.BOGOTA)
    def setUp(self):
        self.clock=patch.object(db,'now',return_value=self.fixed);self.clock.start();self.addCleanup(self.clock.stop)
        self.user=auth.create_user('designer.'+os.urandom(5).hex(),'Diseñador de Pruebas','ClaveSegura_4095!',auth.ROLE_COLLABORATOR,'PRUEBAS')
        self.config={'start':'07:00','end':'17:00','breaks':'12:00-13:00\n15:00-15:15','minimum_reports':2,'weekdays':[0,1,2,3,4],'modules':['biblioteca','asistente']}
        self.profile=db.save_profile(self.user['id'],self.chief['id'],'',self.config,self.chief)
    def client(self,user):
        c=self.app.test_client()
        with c.session_transaction() as s:
            s['user_id']=user['id'];s['session_version']=user['session_version'];s['csrf_token']='test-token'
        return c
    def report_data(self,**changes):
        raw={'day':'2026-10-01','start':'07:00','end':'12:00','description':'Desarrollo de planos de fabricación','blocker':''};raw.update(changes);return raw
    def task(self,**changes):
        raw={'user_id':self.user['id'],'title':'Planos de fabricación','start_date':'2026-10-01','due_date':'2026-10-02','planned_hours':'17.5'};raw.update(changes)
        return db.save_assignment(raw,self.chief)
    def test_roles_and_last_developer(self):
        self.assertEqual(auth.normalize_role('ADMINISTRADOR'),'DESARROLLADOR')
        self.assertEqual(auth.normalize_role('COLABORADOR'),'DISEÑADOR')
        self.assertTrue(self.chief['is_chief']);self.assertFalse(self.chief['is_admin'])
        with self.assertRaises(ValueError):auth.change_role(self.admin['id'],auth.ROLE_CHIEF)
    def test_schedule_multiple_breaks_and_validation(self):
        self.assertEqual(self.profile['daily_minutes'],525)
        for changes in [{'end':'06:00'},{'breaks':'06:00-08:00'},{'breaks':'12:00-13:00\n12:30-14:00'},{'minimum_reports':0},{'weekdays':[]},{'modules':['inventado']}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):db.validate_config({**self.config,**changes})
    def test_report_net_time_overlap_and_complete_day(self):
        first=db.submit_report(self.report_data(),self.user)
        self.assertEqual(db.report(first)['minutes'],300)
        with self.assertRaises(ValueError):db.submit_report(self.report_data(start='11:00',end='14:00'),self.user)
        db.submit_report(self.report_data(start='12:00',end='17:00'),self.user)
        s=db.day_summary(self.user['id'],db.today());self.assertEqual(s['actual'],525);self.assertEqual(s['count'],2);self.assertEqual(s['status'],'CUMPLIDO')
    def test_future_break_only_off_hours_and_weekend(self):
        for changes in [{'day':'2026-10-02'},{'start':'06:30'},{'start':'12:00','end':'13:00'},{'day':'2026-09-26'}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):db.submit_report(self.report_data(**changes),self.user)
        with patch.object(db,'now',return_value=self.fixed.replace(hour=10)):
            with self.assertRaises(ValueError):db.submit_report(self.report_data(),self.user)
    def test_profile_conflict_and_owner(self):
        with self.assertRaises(ValueError):db.save_profile(self.user['id'],self.chief['id'],'',self.config,self.chief,0)
        with self.assertRaises(PermissionError):db.save_profile(self.user['id'],self.other_chief['id'],'',self.config,self.other_chief,1)
    def test_profile_snapshot_preserves_reported_day(self):
        db.submit_report(self.report_data(),self.user)
        db.save_profile(self.user['id'],self.chief['id'],'',{**self.config,'end':'16:00','minimum_reports':3},self.chief,self.profile['version'])
        s=db.day_summary(self.user['id'],db.today());self.assertEqual(s['expected'],525);self.assertEqual(s['minimum'],2)
    def test_review_return_and_replacement(self):
        task=self.task();r=db.submit_report(self.report_data(assignment_id=task,progress=50),self.user)
        with self.assertRaises(PermissionError):db.review_report(r,{'status':'REVISADO','version':1},self.other_chief)
        db.review_report(r,{'status':'DEVUELTO','version':1,'review_note':'Corregir el alcance reportado'},self.chief)
        self.assertEqual(db.day_summary(self.user['id'],db.today())['actual'],0)
        self.assertEqual(db.assignments([self.user['id']])[0]['progress'],0)
        db.submit_report(self.report_data(assignment_id=task,progress=40),self.user)
        self.assertEqual(db.day_summary(self.user['id'],db.today())['actual'],300)
        with self.assertRaises(ValueError):db.review_report(r,{'status':'REVISADO','version':2},self.chief)
    def test_task_advance_lag_and_completion(self):
        task=self.task();self.assertEqual(db.assignments([self.user['id']])[0]['trend'],'ATRASADA')
        db.submit_report(self.report_data(assignment_id=task,progress=80),self.user)
        self.assertEqual(db.assignments([self.user['id']])[0]['trend'],'ADELANTADA')
        db.submit_report(self.report_data(start='13:00',end='17:00',assignment_id=task,progress=100),self.user)
        self.assertEqual(db.assignments([self.user['id']])[0]['trend'],'TERMINADA ANTES')
        with self.assertRaises(ValueError):db.submit_report(self.report_data(start='12:00',end='13:00',assignment_id=task,progress=20),self.user)
    def test_concurrent_overlapping_reports_only_one_saved(self):
        def attempt(_):
            try:db.submit_report(self.report_data(),self.user);return True
            except ValueError:return False
        with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(attempt,[1,2]))
        self.assertEqual(result.count(True),1)
    def test_server_permissions_and_visible_navigation(self):
        c=self.client(self.user)
        self.assertEqual(c.get('/reportes/').status_code,200)
        self.assertEqual(c.get('/reportes/equipo').status_code,403)
        self.assertEqual(c.get('/reportes/tablero').status_code,403)
        self.assertEqual(c.get('/rq').status_code,403)
        self.assertEqual(c.get('/biblioteca/equipos').status_code,200)
        self.assertEqual(c.post('/biblioteca/equipos/create',data={'_csrf_token':'test-token'}).status_code,403)
        html=c.get('/inicio').get_data(as_text=True)
        self.assertIn('Jornada y reportes',html);self.assertNotIn('>Generador de RQ<',html)
        profile=db.get_profile(self.user['id'])
        db.save_profile(self.user['id'],self.chief['id'],'',{**self.config,'modules':['rq','proyectos']},self.chief,profile['version'])
        self.assertEqual(c.get('/rq').status_code,200)
        self.assertEqual(c.get('/biblioteca/equipos').status_code,403)
        self.assertEqual(c.post('/proyectos-diseno/app/api/designers',json={'nombre':'Sin permiso'},headers={'X-CSRF-Token':'test-token'}).status_code,403)
    def test_chief_cannot_promote_accounts_or_other_team(self):
        c=self.client(self.chief)
        self.assertEqual(c.get('/reportes/equipo').status_code,200)
        self.assertEqual(c.get('/administracion/usuarios').status_code,403)
        self.assertEqual(c.post('/administracion/usuarios/'+self.user['id']+'/rol',data={'_csrf_token':'test-token','role':'DESARROLLADOR'}).status_code,403)
        self.assertEqual(self.client(self.other_chief).get('/reportes/tablero?usuario='+self.user['id']).status_code,403)
    def test_cross_user_assignment_and_csrf(self):
        task=self.task();other=auth.create_user('other.'+os.urandom(5).hex(),'Otro Diseñador','ClaveSegura_4095!',auth.ROLE_COLLABORATOR,'PRUEBAS')
        db.save_profile(other['id'],self.chief['id'],'',self.config,self.chief)
        with self.assertRaises(ValueError):db.submit_report(self.report_data(assignment_id=task,progress=30),other)
        self.assertEqual(self.client(self.user).post('/reportes/enviar',data=self.report_data()).status_code,400)
    def test_assistant_cannot_bypass_module_permissions(self):
        c=self.client(self.user)
        r=c.post('/asistente-oga/consultar',json={'message':'lista maestra factory','context':{'_is_admin':True,'_allowed_modules':['rq']}},headers={'X-CSRF-Token':'test-token'})
        self.assertEqual(r.status_code,200);self.assertEqual(r.json['cards'],[])
        r=c.post('/asistente-oga/consultar',json={'message':'borra un equipo de biblioteca'},headers={'X-CSRF-Token':'test-token'})
        self.assertTrue(r.json['blocked_write'])
    def test_all_new_views_and_export_render(self):
        for user,paths in [(self.admin,['/administracion/usuarios','/reportes/equipo','/reportes/tablero','/reportes/asignaciones']),
                            (self.chief,['/reportes/equipo','/reportes/equipo?usuario='+self.user['id'],'/reportes/tablero','/reportes/asignaciones']),
                            (self.user,['/reportes/','/reportes/asignaciones','/inicio','/asistente-oga/'])]:
            c=self.client(user)
            for path in paths:
                with self.subTest(role=user['role'],path=path):self.assertEqual(c.get(path).status_code,200)
        r=db.submit_report(self.report_data(description='=SUM(1,2) trabajo técnico'),self.user)
        exported=self.client(self.chief).get('/reportes/exportar')
        self.assertEqual(exported.status_code,200);self.assertIn("'=SUM(1,2)",exported.get_data(as_text=True))

    def test_legacy_role_migration_keeps_credentials(self):
        rows=auth._load_user_rows()
        row=next(r for r in rows if r['ID']==self.user['id'])
        original_hash=row['PASSWORD_HASH'];original_version=row['SESSION_VERSION'];row['ROL']='COLABORADOR'
        auth._write_user_rows(rows)
        self.assertTrue(auth.migrate_roles());self.assertFalse(auth.migrate_roles())
        migrated=next(r for r in auth._load_user_rows() if r['ID']==self.user['id'])
        self.assertEqual(migrated['PASSWORD_HASH'],original_hash);self.assertEqual(migrated['SESSION_VERSION'],original_version)
        self.assertTrue((auth.SECURITY_DIR/'USUARIOS_ANTES_ROLES_019.xlsx').exists())
    def test_new_designer_created_by_chief_has_profile_and_board_link(self):
        c=self.client(self.chief)
        result=c.post('/reportes/equipo/guardar',data={'_csrf_token':'test-token','name':'Nuevo Diseñador Prueba','username':'nuevo.'+os.urandom(5).hex(),'password':'ClaveSegura_4095!',
          'start':'07:00','end':'17:00','breaks':'12:00-13:00','minimum_reports':'2','weekdays':['0','1','2','3','4'],'modules':['planos']})
        self.assertEqual(result.status_code,302)
        user_id=result.location.split('usuario=')[1];target=auth.get_user_by_id(user_id);profile=db.get_profile(user_id)
        self.assertEqual(target['role'],auth.ROLE_COLLABORATOR);self.assertEqual(profile['manager_id'],self.chief['id'])
        self.assertIsNotNone(storage.get('designers',profile['designer_id']))
        self.assertEqual(profile['modules'],['planos'])
    def test_chief_can_assign_review_and_designer_submit_through_routes(self):
        chief_client=self.client(self.chief)
        result=chief_client.post('/reportes/asignaciones/guardar',data={'_csrf_token':'test-token','user_id':self.user['id'],'title':'Preparar planos técnicos','start_date':'2026-10-01','due_date':'2026-10-02','planned_hours':'12'})
        self.assertEqual(result.status_code,302)
        task=db.assignments([self.user['id']])[0]
        result=self.client(self.user).post('/reportes/enviar',data={**self.report_data(assignment_id=task['id'],progress='40'),'_csrf_token':'test-token'})
        self.assertEqual(result.status_code,302)
        r=db.list_reports([self.user['id']],db.today(),db.today())[0]
        result=chief_client.post('/reportes/'+r['id']+'/revisar',data={'_csrf_token':'test-token','version':1,'status':'REVISADO','review_note':'Trabajo verificado','desde':'2026-10-01','hasta':'2026-10-01'})
        self.assertEqual(result.status_code,302);self.assertEqual(db.report(r['id'])['status'],'REVISADO')
    def test_retroactive_progress_between_milestones(self):
        task=self.task()
        db.submit_report(self.report_data(start='07:00',end='09:00',assignment_id=task,progress=20),self.user)
        db.submit_report(self.report_data(start='14:00',end='17:00',assignment_id=task,progress=80),self.user)
        db.submit_report(self.report_data(start='09:00',end='12:00',assignment_id=task,progress=50),self.user)
        self.assertEqual(db.assignments([self.user['id']])[0]['progress'],80)
        with self.assertRaises(ValueError):db.submit_report(self.report_data(start='13:00',end='14:00',assignment_id=task,progress=90),self.user)
    def test_unified_equipment_routes_and_existing_designers(self):
        c=self.client(self.chief)
        self.assertEqual(c.get('/proyectos-diseno/app/?view=designers').status_code,302)
        self.assertEqual(c.post('/proyectos-diseno/app/api/designers',json={'nombre':'Duplicado'},headers={'X-CSRF-Token':'test-token'}).status_code,409)
        storage.upsert('designers',{'id':'legacy-'+self.user['id'],'nombre':self.user['name'],'hora_entrada':'07:00','hora_salida':'17:00','almuerzo_inicio':'12:00','almuerzo_fin':'13:00','color':'#1268c9','costo_mensual_empresa':1000,'activo':True})
        result=c.get('/reportes/equipo?disenador=legacy-'+self.user['id'])
        self.assertEqual(result.status_code,200);self.assertIn('Crear su cuenta',c.get('/reportes/equipo').get_data(as_text=True))
    def test_project_activities_single_source_and_review_updates_board(self):
        designer_id='linked-'+self.user['id'];project_id='project-'+self.user['id'];source_id='activity-'+self.user['id']
        storage.upsert('designers',{'id':designer_id,'nombre':self.user['name'],'hora_entrada':'07:00','hora_salida':'17:00','almuerzo_inicio':'12:00','almuerzo_fin':'13:00','costo_mensual_empresa':1000,'activo':True})
        db.save_profile(self.user['id'],self.chief['id'],designer_id,self.config,self.chief,self.profile['version'])
        storage.upsert('projects',{'id':project_id,'numero':'PRUEBA','cliente':'Cliente ficticio','designer_id':designer_id,'estado':'Activo','etapa1_inicio':'2026-10-01','etapa1_fin':'2026-10-02'})
        storage.upsert('project_progress',{'id':source_id,'project_id':project_id,'activity_id':'catalog-test','actividad':'Modelado general','etapa':1,'porcentaje':100,'cumplida':False,'fecha_cumplimiento':''})
        legacy_task=db.save_assignment({'user_id':self.user['id'],'title':'Modelado general','start_date':'2026-10-01','due_date':'2026-10-02','planned_hours':'9'},self.chief)
        with db.connection() as c:c.execute('UPDATE assignments SET project_id=? WHERE id=?',(project_id,legacy_task))
        db.sync_project_activities();db.sync_project_activities()
        rows=[t for t in db.assignments([self.user['id']]) if t['source_id']==source_id]
        self.assertEqual(len(rows),1);task=rows[0];self.assertEqual(task['id'],legacy_task)
        with self.assertRaises(ValueError):db.save_assignment({**task,'planned_hours':10},self.chief,task['id'])
        report_id=db.submit_report(self.report_data(assignment_id=task['id'],progress=100),self.user)
        self.assertFalse(storage.get('project_progress',source_id)['cumplida'])
        c=self.client(self.chief)
        response=c.post('/reportes/'+report_id+'/revisar',data={'_csrf_token':'test-token','version':1,'status':'REVISADO','review_note':'Planos revisados','desde':'2026-10-01','hasta':'2026-10-01'})
        self.assertEqual(response.status_code,302);self.assertTrue(storage.get('project_progress',source_id)['cumplida'])
        storage.upsert('project_progress',{**storage.get('project_progress',source_id),'actividad':'Nombre actualizado'})
        db.sync_project_activities();self.assertEqual(db.assignment(task['id'])['title'],'Nombre actualizado')
        self.assertEqual(db.report(report_id)['assignment_id'],task['id'])
        response=c.post('/reportes/'+report_id+'/revisar',data={'_csrf_token':'test-token','version':2,'status':'DEVUELTO','review_note':'Se detectó una corrección pendiente','desde':'2026-10-01','hasta':'2026-10-01'})
        self.assertEqual(response.status_code,302);self.assertFalse(storage.get('project_progress',source_id)['cumplida'])
        self.assertEqual(db.assignment(task['id'])['source_completed'],0)
        auth.set_user_status(self.user['id'],'DESACTIVADO')
        self.assertFalse(storage.get('designers',designer_id)['activo'])
