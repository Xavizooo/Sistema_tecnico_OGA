"""Ejecuta pruebas en una instalación temporal; nunca usa los datos originales."""
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile

BASE=Path(__file__).resolve().parent
if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='oga_pruebas_reportes_') as folder:
        root=Path(folder)
        for source in BASE.rglob('*'):
            relative=source.relative_to(BASE)
            if any(x in relative.parts for x in ['data','.git','.venv','__pycache__','BASES_DE_DATOS','COPIAS_DE_SEGURIDAD','IMAGENES_PROYECTOS','upload','node_modules']): continue
            if source.is_file() and (source.suffix in {'.py','.html','.js','.css','.svg','.txt'}):
                target=root/relative; target.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(source,target)
        env=dict(os.environ,OGA_TEST_ISOLATED='1',OGA_NO_BROWSER='1')
        env.pop('OGA_OPENAI_API_KEY',None);env.pop('OPENAI_API_KEY',None)
        result=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=root,env=env)
        sys.exit(result.returncode)
