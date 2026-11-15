"""Regresión de la posición del actualizador junto a los bordes de la ventana."""
import shutil
import subprocess
from pathlib import Path

import pytest

from clipstudio import config


def test_panel_actualizaciones_permanece_dentro_de_la_ventana():
    node = config.find_tool('node') or shutil.which('node')
    if not node:
        pytest.skip('Requiere Node.js')
    modulo = (Path(__file__).resolve().parents[1] / 'clipstudio/web/actualizaciones.js').as_uri()
    codigo = '''
import assert from 'node:assert/strict';
const { posicionPanel } = await import(process.argv[1]);
for (const [ancho, alto] of [[1426, 933], [1020, 760], [640, 480], [360, 320]]) {
  for (const boton of [
    { left: 18, top: alto - 60, bottom: alto - 30 },
    { left: ancho - 160, top: 20, bottom: 50 },
    { left: 18, top: alto + 100, bottom: alto + 130 },
  ]) {
    for (const altura of [100, 450, 1200]) {
      const p = posicionPanel(boton, ancho, alto, altura);
      assert(p.left >= 12 && p.top >= 12);
      assert(p.left + p.width <= ancho - 12);
      assert(p.top + Math.min(altura, p.maxHeight) <= alto - 12);
    }
  }
}
const arriba = posicionPanel({ left: 18, top: 850, bottom: 880 }, 1426, 933, 450);
assert(arriba.top + 450 < 850);
const debajo = posicionPanel({ left: 700, top: 20, bottom: 50 }, 1020, 760, 450);
assert.equal(debajo.top, 58);
'''
    subprocess.run([node, '--input-type=module', '-e', codigo, modulo], check=True, capture_output=True, text=True)
