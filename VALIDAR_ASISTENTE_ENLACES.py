from __future__ import annotations
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
FILES = [
    ROOT / 'asistente_oga' / 'local_engine.py',
    ROOT / 'asistente_oga' / 'tools.py',
    ROOT / 'asistente_oga' / 'universal_readonly.py',
]

forbidden = {
    '/oportunidades/?': 'ruta antigua de Oportunidades',
    '"/proyectos-diseno/"': 'slash final invalido en la ruta puente de Proyectos Diseño',
    '"/proyectos-diseno/?': 'slash final invalido antes de query en Proyectos Diseño',
}

errors: list[str] = []
text = '\n'.join(p.read_text(encoding='utf-8') for p in FILES)
for token, reason in forbidden.items():
    if token in text:
        errors.append(f'{reason}: {token}')

app = (ROOT / 'app.py').read_text(encoding='utf-8')
if '@app.route("/proyectos-diseno")' not in app:
    errors.append('No existe la ruta puente /proyectos-diseno')
if 'project_id = str(request.args.get("project_id", "")).strip()' not in app:
    errors.append('La ruta puente no conserva project_id')

tpl = (ROOT / 'proyectos_diseno' / 'templates' / 'index.html').read_text(encoding='utf-8')
if 'data-initial-project-id=' not in tpl:
    errors.append('La plantilla no expone project_id para deep-link')

js = (ROOT / 'proyectos_diseno' / 'static' / 'app.js').read_text(encoding='utf-8')
for required in ('INITIAL_PROJECT_ID', 'await openProjectDetail(INITIAL_PROJECT_ID)'):
    if required not in js:
        errors.append(f'Falta soporte JS de deep-link: {required}')

# Rutas canónicas que el asistente puede devolver.
expected = [
    '/oportunidades-proyecto/', '/proyectos-diseno', '/factory', '/biblioteca/',
    '/biblioteca/equipos', '/capacitaciones/', '/planos/', '/rq', '/historico', '/calendario',
]
for prefix in expected:
    if prefix not in text:
        errors.append(f'No se encontró referencia canónica esperada: {prefix}')

if errors:
    print('VALIDACION CON ERRORES')
    for error in errors:
        print(' -', error)
    raise SystemExit(1)

print('VALIDACION OK')
print(' - Oportunidades: enlaces canónicos')
print(' - Proyectos Diseño: vistas y apertura directa por project_id')
print(' - Biblioteca: equipos/documentos')
print(' - Capacitaciones: detalle de video')
print(' - Revisor de Planos: módulo/reportes')
print(' - RQ / Histórico / Factory / Calendario: enlaces canónicos')
