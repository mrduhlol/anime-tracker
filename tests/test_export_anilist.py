"""
Tests del exportador de mutaciones AniList (replay manual).

El builder es PURO y offline: ninguna función toca la red. La ruta
POST /api/export/anilist solo compone el JSON que un usuario repite
(replay) contra graphql.anilist.co con SU PROPIO token — ver el
docstring de anilist_export.py.

Los tests de la ruta usan el patrón de tests/test_cache_invalidez.py:
env vars de BD aislada ANTES de importar main, siembra SIN red por
POST /api/animes/restore (restauración completa sin consultar fuente).
"""
from __future__ import annotations

import os
import tempfile

# Aislar la BD antes de importar main (patrón de tests/test_cache_invalidez.py).
_TMP = tempfile.mkdtemp(prefix="miraru_export_anilist_")
os.environ["ANIME_APP_DIR"] = _TMP
os.environ["ANIME_DB_PATH"] = os.path.join(_TMP, "export.db")
os.environ.setdefault(
    "ANIME_FROZEN_DIR",
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)
# Sin hilos de fondo (ver conftest y main._sin_hilos_de_fondo).
os.environ.setdefault("MIRARU_SIN_HILOS_FONDO", "1")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import anilist_export  # noqa: E402
import database as db  # noqa: E402
import main  # noqa: E402
from anilist_export import build_mutation  # noqa: E402

# ── Builder puro: mapeo de estados ───────────────────────────────────────────

def _anime(**kw):
    """Anime en la forma que devuelve database.listar_animes()."""
    base = {
        "nombre": "Cowboy Bebop", "fuente": "kyb", "capitulos": 26,
        "anilist_id": 1, "estado_usuario": "completado",
        "puntuacion": 7.5, "episodios_vistos": 26,
    }
    base.update(kw)
    return base


class TestMapeoEstados:
    def test_viendo(self):
        v = build_mutation([_anime(estado_usuario="viendo")], 7)[0]
        assert v["variables"]["status"] == "CURRENT"

    def test_completado(self):
        v = build_mutation([_anime(estado_usuario="completado")], 7)[0]
        assert v["variables"]["status"] == "COMPLETED"

    def test_pendiente(self):
        v = build_mutation([_anime(estado_usuario="pendiente")], 7)[0]
        assert v["variables"]["status"] == "PLANNING"

    def test_pausa(self):
        # Canónico en la BD desde el import XML de MAL
        v = build_mutation([_anime(estado_usuario="pausa")], 7)[0]
        assert v["variables"]["status"] == "PAUSED"

    def test_alias_en_pausa(self):
        # Histórico: algunos registros antiguos guardan "en pausa"
        v = build_mutation([_anime(estado_usuario="en pausa")], 7)[0]
        assert v["variables"]["status"] == "PAUSED"

    def test_abandonado(self):
        v = build_mutation([_anime(estado_usuario="abandonado")], 7)[0]
        assert v["variables"]["status"] == "DROPPED"

    def test_estado_desconocido_cae_en_planning(self):
        # La salida segura de anilist_sync
        v = build_mutation([_anime(estado_usuario="otro")], 7)[0]
        assert v["variables"]["status"] == "PLANNING"

    def test_estado_ausente(self):
        a = _anime()
        a.pop("estado_usuario")
        v = build_mutation([a], 7)[0]
        assert v["variables"]["status"] == "PLANNING"


# ── Builder puro: campos de salida ───────────────────────────────────────────

class TestCamposDeSalida:
    def test_cada_anime_un_post_body_query_plus_variables(self):
        """Cada item replica el cuerpo JSON del POST a AniList:
        {"query": ..., "variables": {...}} — replay = copiar el dict."""
        muts = build_mutation([_anime(), _anime(nombre="Ed", anilist_id=2)], 7)
        assert len(muts) == 2
        assert muts[0]["query"].count("SaveMediaListEntry") == 1
        assert muts[0]["variables"] == {
            "mediaId": 1, "userId": 7, "status": "COMPLETED",
            "progress": 26, "scoreRaw": 75,  # 7.5 * 10 → escala 0-100
        }

    def test_el_query_es_la_misma_plantilla_para_todos(self):
        muts = build_mutation([_anime(), _anime(anilist_id=2)], 7)
        plantilla = anilist_export._MUTACION
        for m in muts:  # plantilla POR ÍTEM, compartida por referencia
            assert m["query"] is plantilla

    def test_puntuacion_ausente_no_se_envia(self):
        v = build_mutation([_anime(puntuacion=None)], 7)[0]
        assert "scoreRaw" not in v["variables"]
        v = build_mutation([_anime(puntuacion=0)], 7)[0]
        assert "scoreRaw" not in v["variables"]

    def test_score_round(self):
        # 8.35 * 10 == 83.5 → round → 84
        v = build_mutation([_anime(puntuacion=8.35)], 7)[0]
        assert v["variables"]["scoreRaw"] == 84

    def test_cap_de_score_a_la_escala_anilist(self):
        v = build_mutation([_anime(puntuacion=10.0)], 7)[0]
        assert v["variables"]["scoreRaw"] == 100

    def test_progress_toma_episodios_vistos(self):
        """El progreso de capitulos sale de `episodios_vistos`
        (contador de progreso de Miraru, ver database.py)."""
        v = build_mutation([_anime(episodios_vistos=3,
                                   estado_usuario="viendo")], 7)[0]
        assert v["variables"]["progress"] == 3

    def test_progress_ausente_es_cero(self):
        a = _anime()
        a.pop("episodios_vistos")
        v = build_mutation([a], 7)[0]
        assert v["variables"]["progress"] == 0


# ── Builder puro: manga → progressVolumes ────────────────────────────────────

class TestManga:
    def test_tomos_mapen_a_progress_volumes(self):
        """volúmenes leídos (database: `volumenes_leidos`) → progressVolumes
        SOLO cuando tipo == 'manga'."""
        v = build_mutation([_anime(tipo="manga", volumenes_leidos=4,
                                   volumenes_totales=8)], 7)[0]
        assert v["variables"]["progressVolumes"] == 4
        assert v["variables"]["progress"] == 26  # capaz sigue = episodios_vistos

    def test_anime_no_manda_progress_volumes(self):
        v = build_mutation([_anime(volumenes_leidos=4)], 7)[0]
        assert "progressVolumes" not in v["variables"]

    def test_manga_sin_tomos_no_manda_progress_volumes(self):
        # 0 → no se envía (evita sobreescribir en AniList)
        v = build_mutation([_anime(tipo="manga", volumenes_leidos=0)], 7)[0]
        assert "progressVolumes" not in v["variables"]


# ── Builder puro: anilist_id obligatorio y userId ────────────────────────────

class TestFiltroYUserId:
    def test_sin_anid_se_omiten(self):
        muts = build_mutation([_anime(anilist_id=None),
                               _anime(anilist_id=0),
                               _anime(anilist_id=""),  # no convertible
                               _anime(anilist_id=42)], 7)
        assert len(muts) == 1
        assert muts[0]["variables"]["mediaId"] == 42

    def test_lista_vacia_o_sin_ids_devuelve_lista_vacia(self):
        assert build_mutation([], 7) == []
        assert build_mutation([_anime(anilist_id=None)], 7) == []

    def test_id_texto_se_normaliza(self):
        muts = build_mutation([_anime(anilist_id="991")], 7)
        assert muts[0]["variables"]["mediaId"] == 991

    def test_user_id_dentro_de_variables(self):
        """userId viaja en variables (la mutación lo declara $userId: Int):
        el cuerpo es el POST real a AniList."""
        muts = build_mutation([_anime()], 7)
        assert muts[0]["variables"]["userId"] == 7

    def test_sin_user_id_no_se_manda(self):
        muts = build_mutation([_anime()], 0)
        assert "userId" not in muts[0]["variables"]


# ── Ruta POST /api/export/anilist ────────────────────────────────────────────

@pytest.fixture
def client():
    """Cliente HTTP sobre la app; al salir deja las tablas vacías."""
    with TestClient(main.app, client=("127.0.0.1", 1)) as c:
        yield c
    with db.get_conn() as conn:
        for t in ("animes", "media", "ep_log", "historial", "episode_notes"):
            conn.execute(f"DELETE FROM {t}")
        conn.execute("DELETE FROM config")
    # Limpieza SQL directa → invalidar la caché para el siguiente test.
    db._invalidar_cache()


def _sembrar(client, nombre, **campos):
    """Crea un anime SIN red: /api/animes/restore restaura el registro tal cual
    (guardar_anime sin fuente), así se fija anilist_id/tipo/puntuación."""
    data = {"nombre": nombre, "capitulos": "26", "fuente": "test"}
    data.update(campos)
    r = client.post("/api/animes/restore", json=data)
    assert r.status_code == 200, r.text


def test_ruta_devuelve_mutaciones_con_conteo(client):
    _sembrar(client, "A1", anilist_id=1, estado_usuario="completado",
             puntuacion=7.5, episodios_vistos=26)
    _sembrar(client, "A2", anilist_id=2, estado_usuario="viendo",
             episodios_vistos=3)
    _sembrar(client, "Sin AniList")  # sin anilist_id → se omite
    r = client.post("/api/export/anilist", json={})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["count"] == 2
    assert len(d["mutaciones"]) == 2
    mut = d["mutaciones"][0]
    assert mut["variables"]["mediaId"] == 1
    assert "SaveMediaListEntry" in mut["query"]
    assert set(d.keys()) == {"mutaciones", "count"}


def test_ruta_con_volumenes_de_manga(client):
    _sembrar(client, "MangaX", anilist_id=9, tipo="manga",
             estado_usuario="viendo", episodios_vistos=12, volumenes_leidos=4)
    d = client.post("/api/export/anilist", json={}).json()
    assert d["mutaciones"][0]["variables"]["progressVolumes"] == 4


def test_ruta_sin_ningun_anilist_id(client):
    _sembrar(client, "Solo local A")
    _sembrar(client, "Solo local B")
    r = client.post("/api/export/anilist", json={})
    assert r.status_code == 400
    assert "anilist_id" in r.json()["detail"]  # mensaje en español


def test_ruta_biblioteca_vacia(client):
    r = client.post("/api/export/anilist", json={})
    assert r.status_code == 400


def test_body_vacio_es_valido(client):
    _sembrar(client, "Uno", anilist_id=1)
    r = client.post("/api/export/anilist")
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_userid_anilist_guardado_viaja_en_variables(client):
    """El userid guardado por el OAuth de anilist_sync (config) sale en las
    variables de las mutaciones."""
    _sembrar(client, "Con UID", anilist_id=5)
    db.set_config("anilist_userid", "31")
    d = client.post("/api/export/anilist", json={}).json()
    assert d["mutaciones"][0]["variables"]["userId"] == 31


def test_userid_del_cuerpo_tiene_prioridad(client):
    _sembrar(client, "Override", anilist_id=3)
    d = client.post("/api/export/anilist", json={"user_id": 55}).json()
    assert d["mutaciones"][0]["variables"]["userId"] == 55


def test_userid_malo_en_el_cuerpo_es_400(client):
    _sembrar(client, "UID malo", anilist_id=3)
    r = client.post("/api/export/anilist", json={"user_id": "x"})
    assert r.status_code == 400
