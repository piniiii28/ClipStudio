"""Persistencia en SQLite. Una conexion por operacion: simple y segura entre hilos."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS proyectos (
    id TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    origen TEXT NOT NULL,              -- 'archivo' | 'url'
    url TEXT,
    archivo_fuente TEXT,               -- nombre del archivo dentro de la carpeta del proyecto
    idioma TEXT NOT NULL DEFAULT 'auto',
    idioma_detectado TEXT,
    duracion REAL,
    ancho INTEGER,
    alto INTEGER,
    estado TEXT NOT NULL,              -- en_cola | procesando | listo | error | cancelado
    paso TEXT,
    progreso REAL NOT NULL DEFAULT 0,
    mensaje TEXT,
    error TEXT,
    creado REAL NOT NULL,
    actualizado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    proyecto_id TEXT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    inicio REAL NOT NULL,
    fin REAL NOT NULL,
    encuadre TEXT NOT NULL DEFAULT 'rellenar',   -- rellenar | ajustar
    recorte_x REAL NOT NULL DEFAULT 0.5,         -- 0 = izquierda, 1 = derecha
    subtitulos TEXT NOT NULL DEFAULT '[]',       -- JSON [{inicio, fin, texto}] en tiempo del video fuente
    estilo TEXT NOT NULL DEFAULT '{}',
    origen TEXT NOT NULL DEFAULT 'manual',       -- sugerido | manual | division
    motivos TEXT NOT NULL DEFAULT '[]',
    creado REAL NOT NULL,
    actualizado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exportaciones (
    id TEXT PRIMARY KEY,
    clip_id TEXT NOT NULL,
    proyecto_id TEXT NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
    titulo TEXT NOT NULL,
    parametros TEXT NOT NULL,          -- copia del clip al momento de exportar
    estado TEXT NOT NULL,              -- en_cola | procesando | listo | error | cancelado
    progreso REAL NOT NULL DEFAULT 0,
    error TEXT,
    archivo TEXT,
    creado REAL NOT NULL,
    actualizado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS preferencias (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL                -- JSON
);
CREATE TABLE IF NOT EXISTS sesiones_vivo (
    id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    titulo TEXT,
    estado TEXT NOT NULL,              -- conectando | grabando | detenido | error | interrumpida
    error TEXT,
    creado REAL NOT NULL,
    actualizado REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS momentos_vivo (
    id TEXT PRIMARY KEY,
    sesion_id TEXT NOT NULL REFERENCES sesiones_vivo(id) ON DELETE CASCADE,
    tiempo REAL NOT NULL,              -- segundos desde el inicio de la grabacion
    motivo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'nuevo',   -- nuevo | convertido
    proyecto_id TEXT,
    creado REAL NOT NULL,
    actualizado REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_momentos_sesion ON momentos_vivo(sesion_id);
CREATE INDEX IF NOT EXISTS idx_clips_proyecto ON clips(proyecto_id);
CREATE INDEX IF NOT EXISTS idx_exp_proyecto ON exportaciones(proyecto_id);
"""

JSON_FIELDS = {"subtitulos", "estilo", "motivos", "parametros", "cortes", "trayectoria", "composicion", "encuadre_vivo", "tiktok"}
ACTIVOS = ("en_cola", "procesando")


@contextmanager
def conectar() -> Iterator[sqlite3.Connection]:
    con = sqlite3.connect(config.DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    try:
        yield con
        con.commit()
    finally:
        con.close()


# Columnas anadidas despues de la primera version: se crean si faltan (bases ya existentes).
COLUMNAS_NUEVAS = {
    "clips": {"cortes": "TEXT NOT NULL DEFAULT '[]'", "trayectoria": "TEXT NOT NULL DEFAULT '[]'",
              "composicion": "TEXT NOT NULL DEFAULT '{}'", "tiktok": "TEXT NOT NULL DEFAULT '{}'"},
    "proyectos": {"min_s": "REAL NOT NULL DEFAULT 15", "max_s": "REAL NOT NULL DEFAULT 60",
                  "audio_idioma": "TEXT", "es_clip_vivo": "INTEGER NOT NULL DEFAULT 0", "encuadre_vivo": "TEXT NOT NULL DEFAULT '{}'"},
    "momentos_vivo": {"origen": "TEXT NOT NULL DEFAULT 'audio'", "error": "TEXT"},
}


def iniciar() -> None:
    config.ensure_dirs()
    with conectar() as con:
        con.executescript(SCHEMA)
        for tabla, columnas in COLUMNAS_NUEVAS.items():
            existentes = {fila["name"] for fila in con.execute(f"PRAGMA table_info({tabla})")}
            for nombre, definicion in columnas.items():
                if nombre not in existentes:
                    con.execute(f"ALTER TABLE {tabla} ADD COLUMN {nombre} {definicion}")


def leer_preferencia(clave: str, defecto: Any = None) -> Any:
    with conectar() as con:
        fila = con.execute("SELECT valor FROM preferencias WHERE clave = ?", (clave,)).fetchone()
    if fila is None:
        return defecto
    try:
        return json.loads(fila["valor"])
    except ValueError:
        return defecto


def guardar_preferencia(clave: str, valor: Any) -> None:
    with conectar() as con:
        con.execute(
            "INSERT INTO preferencias (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, json.dumps(valor, ensure_ascii=False)),
        )


def nuevo_id() -> str:
    return uuid.uuid4().hex


def _fila(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    d = dict(row)
    for k in JSON_FIELDS & d.keys():
        d[k] = json.loads(d[k]) if d[k] else None
    return d


def _codificar(campos: dict[str, Any]) -> dict[str, Any]:
    return {k: (json.dumps(v, ensure_ascii=False) if k in JSON_FIELDS else v) for k, v in campos.items()}


def insertar(tabla: str, campos: dict[str, Any]) -> dict[str, Any]:
    ahora = time.time()
    campos = {"id": nuevo_id(), "creado": ahora, "actualizado": ahora, **campos}
    cod = _codificar(campos)
    cols = ", ".join(cod)
    marcas = ", ".join("?" for _ in cod)
    with conectar() as con:
        con.execute(f"INSERT INTO {tabla} ({cols}) VALUES ({marcas})", list(cod.values()))
    return campos


def actualizar(tabla: str, id_: str, **campos: Any) -> None:
    if not campos:
        return
    campos["actualizado"] = time.time()
    cod = _codificar(campos)
    asignaciones = ", ".join(f"{k} = ?" for k in cod)
    with conectar() as con:
        con.execute(f"UPDATE {tabla} SET {asignaciones} WHERE id = ?", [*cod.values(), id_])


def obtener(tabla: str, id_: str) -> dict[str, Any] | None:
    with conectar() as con:
        return _fila(con.execute(f"SELECT * FROM {tabla} WHERE id = ?", (id_,)).fetchone())


def listar(tabla: str, donde: str = "", args: tuple = (), orden: str = "creado DESC") -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {tabla}"
    if donde:
        sql += f" WHERE {donde}"
    sql += f" ORDER BY {orden}"
    with conectar() as con:
        return [_fila(r) for r in con.execute(sql, args).fetchall()]  # type: ignore[misc]


def borrar(tabla: str, id_: str) -> None:
    with conectar() as con:
        con.execute(f"DELETE FROM {tabla} WHERE id = ?", (id_,))


def borrar_donde(tabla: str, donde: str, args: tuple) -> None:
    with conectar() as con:
        con.execute(f"DELETE FROM {tabla} WHERE {donde}", args)


def marcar_interrumpidos() -> None:
    """Al arrancar, lo que quedo a medias de una ejecucion anterior se marca como error."""
    msg = "El proceso se interrumpio porque la aplicacion se cerro. Puedes reintentarlo."
    ahora = time.time()
    with conectar() as con:
        for tabla in ("proyectos", "exportaciones"):
            con.execute(
                f"UPDATE {tabla} SET estado = 'error', error = ?, actualizado = ? WHERE estado IN (?, ?)",
                (msg, ahora, *ACTIVOS),
            )
