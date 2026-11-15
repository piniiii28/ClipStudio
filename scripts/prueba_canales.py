"""Comprobacion optativa de canales reales en una carpeta de datos aislada.

Debe ejecutarse contra un servidor de pruebas propio. Guarda un clip corto si el canal
emite y registra por separado captura, imagen, chat y error de plataforma.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--base', required=True)
    ap.add_argument('--datos', type=Path, required=True)
    ap.add_argument('--salida', type=Path, required=True)
    ap.add_argument('urls', nargs='+')
    args = ap.parse_args()

    def api(metodo, ruta, cuerpo=None):
        req = urllib.request.Request(args.base + '/api' + ruta,
            data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
            method=metodo, headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.loads(r.read())

    estado = api('GET','/estado')
    if Path(estado['carpeta_datos']).resolve() != args.datos.resolve():
        raise SystemExit('La carpeta del servidor no coincide con la prueba aislada')
    if api('GET','/vivo'):
        raise SystemExit('El servidor ya tiene una sesion. Se conserva sin cambios.')
    resultados = []
    for url in args.urls:
        resultado = {'url':url,'grabando':False,'imagen':False,'chat':None,'clip':None}
        sid = None
        try:
            sesion = api('POST','/vivo',{'url':url,'usar_chat':True,'automaticos':False,'calidad':720,'buffer_min':10})
            sid = sesion['id']
            for _ in range(90):
                sesion = api('GET','/vivo')
                if sesion['estado'] == 'error':
                    resultado['error'] = sesion.get('error')
                    break
                resultado['grabando'] = sesion['estado'] == 'grabando'
                resultado['chat'] = sesion.get('chat_estado')
                resultado['mensajes'] = sum(sesion.get('chat_actividad') or [])
                resultado['imagen'] = bool(sesion.get('vista_version'))
                if resultado['imagen'] and sesion.get('cobertura_s',0) >= 15:
                    resultado['clip'] = api('POST', f'/vivo/{sid}/clip',{'segundos':30,'calidad':'buffer'})
                    break
                time.sleep(1)
            else:
                resultado['error'] = 'No se obtuvo cobertura suficiente en 90 segundos.'
        except Exception as exc:
            if isinstance(exc, urllib.error.HTTPError):
                resultado['error'] = exc.read().decode('utf-8',errors='replace')[:1500]
            else:
                resultado['error'] = str(exc)
        finally:
            if sid:
                try:
                    api('POST',f'/vivo/{sid}/parar',{})
                except Exception as exc:
                    resultado['error_parada'] = str(exc)
        resultados.append(resultado)
        args.salida.write_text(json.dumps(resultados, ensure_ascii=False,indent=2), encoding='utf-8')
        print(json.dumps(resultado,ensure_ascii=True),flush=True)
    correcto = all(r['grabando'] and r['imagen'] and r['clip']
                   and not r.get('error') and not r.get('error_parada') for r in resultados)
    return 0 if correcto else 1


if __name__ == '__main__':
    raise SystemExit(main())
